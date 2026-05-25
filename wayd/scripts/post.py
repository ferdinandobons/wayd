#!/usr/bin/env python3
"""Create, edit, and soft-delete WAYD posts.

Subcommands:
  check_rate_limit            : emits {ok: bool, retry_in_min?: int}
  publish --vibe S --text T   : creates the issue, emits {ok, post_id, url}
  edit --post-id N --text T   : edits the body, emits {ok}
  soft_delete --post-id N     : locks/closes/marks body, emits {ok}

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
    Side effect: prunes stale entries from recent_posts.

    Splitting check from emit() lets publish() reuse the logic without
    racing on JSON output. The check_rate_limit subcommand wraps this.
    """
    cfg = shared.load_config()
    limit = cfg["limits"]["posts_per_hour"]
    state = shared.load_last_check()
    recent = state.get("recent_posts", [])

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    fresh = [
        r for r in recent
        if datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) > cutoff
    ]

    # Prune stale entries while we're here
    state["recent_posts"] = fresh
    shared.save_last_check(state)

    if len(fresh) >= limit:
        oldest = min(
            datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) for r in fresh
        )
        retry_at = oldest + timedelta(hours=1)
        retry_in_min = max(1, int((retry_at - datetime.now(timezone.utc)).total_seconds() / 60))
        return (False, 0, retry_in_min)

    return (True, limit - len(fresh), 0)


def cmd_check_rate_limit(_: argparse.Namespace) -> None:
    ok, remaining, retry_in_min = _check_rate_limit_internal()
    if not ok:
        shared.emit({"ok": False, "code": "rate_limit", "retry_in_min": retry_in_min})
        return
    shared.emit({"ok": True, "remaining": remaining})


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
    if len(text) > max_chars:
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

    title = shared.build_post_title(vibe["slug"], vibe["emoji"], text)
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

    # URL looks like https://github.com/<owner>/<repo>/issues/123
    post_id = int(url.rsplit("/", 1)[-1])
    ts = shared.now_iso()

    # Track in rate-limit log and editable window
    state = shared.load_last_check()
    state.setdefault("recent_posts", []).append({"id": post_id, "ts": ts})
    edit_window_sec = cfg["limits"]["edit_window_sec"]
    editable_until = (datetime.now(timezone.utc) + timedelta(seconds=edit_window_sec)).isoformat()
    state.setdefault("editable_until", {})[str(post_id)] = editable_until
    shared.save_last_check(state)

    shared.emit({"ok": True, "post_id": post_id, "url": url, "editable_until": editable_until})


def cmd_edit(args: argparse.Namespace) -> None:
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
    cfg = shared.load_config()
    repo = cfg["repo"]
    marker_version = cfg["marker_version"]

    # Verify the post is ours (defense-in-depth; the caller should also check)
    try:
        raw = shared.gh(
            ["issue", "view", str(args.post_id), "--repo", repo, "--json", "author"],
            json_output=True,
        )
    except shared.GhError as e:
        shared.emit_error(shared.translate_gh_error(e), code="gh_failed")
        return

    identity = shared.load_identity()
    if raw["author"]["login"] != identity.get("username"):
        shared.emit_error(
            "You can only delete your own posts.",
            code="not_your_post",
        )
        return

    new_body = f"[deleted by author] <!-- wayd:{marker_version} deleted=true -->"
    try:
        shared.gh(
            [
                "issue", "edit", str(args.post_id),
                "--repo", repo,
                "--body", new_body,
            ]
        )
        shared.gh(["issue", "close", str(args.post_id), "--repo", repo])
        # Lock the conversation so no new comments
        shared.gh(
            [
                "api", "-X", "PUT",
                f"repos/{repo}/issues/{args.post_id}/lock",
                "-f", "lock_reason=resolved",
            ]
        )
    except shared.GhError as e:
        shared.emit_error(shared.translate_gh_error(e), code="gh_failed")
        return

    shared.emit({"ok": True, "post_id": args.post_id})


def main() -> None:
    parser = argparse.ArgumentParser(prog="post")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check_rate_limit").set_defaults(func=cmd_check_rate_limit)

    p_pub = sub.add_parser("publish")
    p_pub.add_argument("--vibe", required=True)
    p_pub.add_argument("--text", required=True)
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
