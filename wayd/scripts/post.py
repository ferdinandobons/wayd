#!/usr/bin/env python3
"""Create, edit, and soft-delete WAYD posts.

Subcommands:
  check_rate_limit            : emits {ok: bool, retry_in_min?: int}
  publish --vibe S --text T   : creates the issue, emits {ok, post_id}
  edit --post-id N --text T   : edits the body, emits {ok}
  soft_delete --post-id N     : locks/closes/marks body, emits {ok}

publish deliberately does NOT include the issue URL in its payload. The
backend-opacity principle in SKILL.md forbids exposing GitHub-native
artifacts (URLs, raw issue numbers) to the user. post_id is what the
orchestrator needs for the edit/delete 5-minute window; it stays
internal to the data/last-check.json bookkeeping.

All output is JSON on stdout (via shared.emit). User-facing strings live in
SKILL.md and the calling Claude prompt, this script only handles mechanics.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta

# Import shared from sibling file. When invoked as a script, scripts/ is on
# sys.path automatically; we add a safety net so this also works from anywhere.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import shared  # noqa: E402


def _check_rate_limit_internal() -> tuple[bool, int, int]:
    """Internal helper used by both the standalone check and publish.

    Returns (is_within_limit, remaining_slots, retry_in_min).
    Side effect: prunes stale entries from recent_posts AND expired entries
    from editable_until (so neither structure grows without bound).

    Splitting check from emit() lets publish() reuse the logic without
    racing on JSON output. The check_rate_limit subcommand wraps this.
    """
    cfg = shared.load_config()
    limit = cfg["limits"]["posts_per_hour"]
    state = shared.load_last_check()
    recent = state.get("recent_posts", [])

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=1)
    fresh = [
        r for r in recent
        if datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) > cutoff
    ]

    # Prune stale rate-limit entries
    state["recent_posts"] = fresh

    # Prune expired edit windows. editable_until grows once per post; without
    # this it accumulates forever and bloats last-check.json for heavy users.
    editable = state.get("editable_until", {})
    state["editable_until"] = {
        pid: ts for pid, ts in editable.items()
        if datetime.fromisoformat(ts.replace("Z", "+00:00")) > now
    }

    shared.save_last_check(state)

    if len(fresh) >= limit:
        oldest = min(
            datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) for r in fresh
        )
        retry_at = oldest + timedelta(hours=1)
        retry_in_min = max(1, int((retry_at - now).total_seconds() / 60))
        return (False, 0, retry_in_min)

    return (True, limit - len(fresh), 0)


def cmd_check_rate_limit(_: argparse.Namespace) -> None:
    ok, remaining, retry_in_min = _check_rate_limit_internal()
    if not ok:
        shared.emit({"ok": False, "code": "rate_limit", "retry_in_min": retry_in_min})
        return
    shared.emit({"ok": True, "remaining": remaining})


def _convert_image_to_art(image_path: str, text_len: int, max_chars: int) -> str | None:
    """Convert image to ASCII art. Art is exempt from max_chars, so no budget cap.

    Returns the art string, or None if conversion fails (caller logs the error
    and continues without art so the post still goes through).
    """
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    try:
        from img2ascii import image_to_ascii  # type: ignore[import]
    except ImportError:
        shared.log_error("img2ascii not found; skipping image conversion")
        return None

    try:
        return image_to_ascii(image_path=image_path)
    except Exception as exc:
        shared.log_error(f"img2ascii failed for {image_path!r}: {exc}")
        return None


def cmd_publish(args: argparse.Namespace) -> None:
    cfg = shared.load_config()
    repo = cfg["repo"]
    max_chars = cfg["limits"]["max_chars"]

    vibe = shared.vibe_by_slug(args.vibe)
    if vibe is None:
        shared.emit_error(f"Unknown vibe: {args.vibe}", code="bad_vibe")
        return

    text = args.text.strip()
    if not text:
        shared.emit_error("An empty post is just silence.", code="empty")
        return

    # Only the visible text counts toward max_chars. ASCII art lives in an
    # HTML comment block and is visual content, not a wall of text — exempt.
    has_image = bool(getattr(args, "image", None))
    if not has_image and len(text) > max_chars:
        shared.emit_error(
            f"Too long by {len(text) - max_chars} chars. Trim it down.",
            code="too_long",
        )
        return

    # Defensive rate-limit check. Even though the caller (SKILL.md instructs
    # Claude to call check_rate_limit first), we re-check here so the limit
    # can't be bypassed by direct script invocation. Cheap to do, costly to
    # skip.
    ok, _, retry_in_min = _check_rate_limit_internal()
    if not ok:
        shared.emit({"ok": False, "code": "rate_limit", "retry_in_min": retry_in_min})
        return

    # Optional ASCII art from image. Art is embedded as an HTML comment so it's
    # invisible on GitHub.com but parseable by scroll.py for the "📎" indicator.
    art: str | None = None
    if getattr(args, "image", None):
        art = _convert_image_to_art(args.image, len(text), max_chars)

    title = shared.build_post_title(vibe["slug"], vibe["emoji"], text)
    if art:
        body = shared.build_post_body_with_art(vibe["slug"], text, art, cfg["marker_version"])
    else:
        body = shared.build_post_body(vibe["slug"], text, cfg["marker_version"])

    try:
        url = shared.gh(
            [
                "issue", "create",
                "--repo", repo,
                "--title", title,
                "--body", body,
                "--label", "wayd-post",
                "--label", f"vibe:{vibe['slug']}",
            ]
        ).strip()
    except shared.GhError as e:
        shared.log_error(f"publish failed: {e}")
        shared.emit_error(shared.translate_gh_error(e), code="gh_failed")
        return

    # URL looks like https://github.com/<owner>/<repo>/issues/123.
    # Guard against unexpected gh output formats (future gh version, redirect URL,
    # empty stdout) so we never propagate a raw ValueError traceback to the user.
    try:
        post_id = int(url.rsplit("/", 1)[-1])
    except ValueError:
        shared.log_error(f"publish: unexpected URL format from gh: {url!r}")
        shared.emit_error(
            "Your post may have been created, but I couldn't confirm it. Check it in your scroll in a moment.",
            code="parse_error",
        )
        return

    ts = shared.now_iso()

    # Track in rate-limit log and editable window. We deliberately don't
    # return the URL to the caller: SKILL.md's backend-opacity principle
    # forbids exposing GitHub-native artifacts to the user. The orchestrator
    # has post_id, which is all it needs for edit/delete.
    state = shared.load_last_check()
    state.setdefault("recent_posts", []).append({"id": post_id, "ts": ts})
    edit_window_sec = cfg["limits"]["edit_window_sec"]
    editable_until = (datetime.now(timezone.utc) + timedelta(seconds=edit_window_sec)).isoformat()
    state.setdefault("editable_until", {})[str(post_id)] = editable_until
    shared.save_last_check(state)

    shared.emit({"ok": True, "post_id": post_id, "has_art": art is not None})


def cmd_edit(args: argparse.Namespace) -> None:
    if not shared.validate_post_id(args.post_id):
        shared.emit_error("Invalid post id.", code="bad_post_id")
        return

    cfg = shared.load_config()
    repo = cfg["repo"]
    max_chars = cfg["limits"]["max_chars"]

    state = shared.load_last_check()
    editable_until_iso = state.get("editable_until", {}).get(str(args.post_id))
    if not editable_until_iso:
        shared.emit_error(
            "Edits are only allowed in the first 5 minutes after posting.",
            code="edit_window_expired",
        )
        return

    editable_until = datetime.fromisoformat(editable_until_iso.replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > editable_until:
        shared.emit_error(
            "Edits are only allowed in the first 5 minutes after posting.",
            code="edit_window_expired",
        )
        return

    text = args.text.strip()
    if not text or len(text) > max_chars:
        shared.emit_error(
            "Text empty or too long." if not text else f"Too long by {len(text) - max_chars} chars.",
            code="bad_text",
        )
        return

    # Fetch current body to recover the vibe slug (preserve it on edit)
    try:
        raw = shared.gh(
            ["issue", "view", str(args.post_id), "--repo", repo, "--json", "body,title"],
            json_output=True,
        )
    except shared.GhError as e:
        shared.emit_error(shared.translate_gh_error(e), code="gh_failed")
        return

    parsed = shared.parse_post_body(raw["body"])
    vibe_slug = parsed["vibe"] or "shower-thought"  # fallback; shouldn't happen
    vibe = shared.vibe_by_slug(vibe_slug)

    new_title = shared.build_post_title(vibe_slug, vibe["emoji"] if vibe else "", text)
    new_body = shared.build_post_body(vibe_slug, text, cfg["marker_version"])

    try:
        shared.gh(
            [
                "issue", "edit", str(args.post_id),
                "--repo", repo,
                "--title", new_title,
                "--body", new_body,
            ]
        )
    except shared.GhError as e:
        shared.emit_error(shared.translate_gh_error(e), code="gh_failed")
        return

    shared.emit({"ok": True, "post_id": args.post_id})


def cmd_soft_delete(args: argparse.Namespace) -> None:
    if not shared.validate_post_id(args.post_id):
        shared.emit_error("Invalid post id.", code="bad_post_id")
        return

    cfg = shared.load_config()
    repo = cfg["repo"]
    marker_version = cfg["marker_version"]

    # Fetch the post's author and verify ownership against the LIVE
    # authenticated identity (gh api user), not the cached identity.json.
    # The local file is user-writable and shouldn't be trusted as a
    # security boundary: someone editing it to "username": "victim" must
    # not be able to delete victim's posts.
    try:
        raw = shared.gh(
            ["issue", "view", str(args.post_id), "--repo", repo, "--json", "author"],
            json_output=True,
        )
    except shared.GhError as e:
        shared.emit_error(shared.translate_gh_error(e), code="gh_failed")
        return

    try:
        live_user = shared.gh_current_user()
    except shared.GhError as e:
        shared.emit_error(shared.translate_gh_error(e), code="gh_failed")
        return

    if raw["author"]["login"] != live_user:
        shared.emit_error(
            "You can only delete your own posts.",
            code="not_your_post",
        )
        return

    # Atomic-ish soft-delete: three steps, each tracked separately. A
    # partial failure logs the gap so the orchestrator can tell the user
    # what actually happened. We always *try* every step (no early return
    # mid-flight) because each step is independent at the GitHub side.
    new_body = f"[deleted by author] <!-- wayd:{marker_version} deleted=true -->"

    steps: list[tuple[str, list[str]]] = [
        ("edit_body", ["issue", "edit", str(args.post_id), "--repo", repo, "--body", new_body]),
        ("close", ["issue", "close", str(args.post_id), "--repo", repo]),
        ("lock", [
            "api", "-X", "PUT",
            f"repos/{repo}/issues/{args.post_id}/lock",
            "-f", "lock_reason=resolved",
        ]),
    ]

    failed_steps: list[str] = []
    for name, cmd in steps:
        try:
            shared.gh(cmd)
        except shared.GhError as e:
            failed_steps.append(name)
            shared.log_error(f"soft_delete step {name!r} on post #{args.post_id} failed: {e}")

    if not failed_steps:
        shared.emit({"ok": True, "post_id": args.post_id})
        return

    # Tailor the message: "body" failing is the worst (post still visible);
    # "close"/"lock" failing means the post disappears from scroll but
    # could still receive comments.
    if "edit_body" in failed_steps:
        shared.emit({
            "ok": False,
            "code": "partial_delete",
            "failed_steps": failed_steps,
            "message": "Couldn't fully delete your post. Try again in a moment.",
        })
        return

    shared.emit({
        "ok": True,
        "code": "partial_delete",
        "post_id": args.post_id,
        "failed_steps": failed_steps,
        "message": "Your post was removed from scroll, but cleanup didn't fully complete. New replies may still appear in the thread.",
    })


def main() -> None:
    parser = argparse.ArgumentParser(prog="post")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check_rate_limit").set_defaults(func=cmd_check_rate_limit)

    p_pub = sub.add_parser("publish")
    p_pub.add_argument("--vibe", required=True)
    p_pub.add_argument("--text", required=True)
    p_pub.add_argument("--image", default=None, help="Path to image; auto-converts to ASCII art")
    p_pub.set_defaults(func=cmd_publish)

    p_edit = sub.add_parser("edit")
    p_edit.add_argument("--post-id", type=int, required=True)
    p_edit.add_argument("--text", required=True)
    p_edit.set_defaults(func=cmd_edit)

    p_del = sub.add_parser("soft_delete")
    p_del.add_argument("--post-id", type=int, required=True)
    p_del.set_defaults(func=cmd_soft_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
