#!/usr/bin/env python3
"""Fetch the user's own posts that have replies, with a "new since last check"
flag on each reply.

Subcommand:
  fetch   : emits {ok, posts: [{id, vibe_emoji, vibe_slug, text, created_relative,
                                 reactions, new_replies: [{author, text, created_relative}],
                                 total_replies}]}
  mark_read : updates last_check_ts to now, emits {ok}
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import shared  # noqa: E402


def cmd_fetch(_: argparse.Namespace) -> None:
    cfg = shared.load_config()
    repo = cfg["repo"]
    identity = shared.load_identity()
    username = identity.get("username")
    if not username:
        shared.emit_error(
            "I don't know who you are yet. Try /wayd to run setup.",
            code="no_identity",
        )
        return

    state = shared.load_last_check()
    last_check_iso = state.get("last_check_ts")
    last_check = (
        datetime.fromisoformat(last_check_iso.replace("Z", "+00:00"))
        if last_check_iso else None
    )

    # Fetch all open issues by this author with the wayd-post label
    try:
        raw = shared.gh(
            [
                "issue", "list",
                "--repo", repo,
                "--state", "open",
                "--author", username,
                "--label", "wayd-post",
                "--limit", "100",
                "--json", "number,title,body,createdAt,reactionGroups,comments",
            ],
            json_output=True,
        )
    except shared.GhError as e:
        shared.emit_error(shared.translate_gh_error(e, context="inbox"), code="gh_failed")
        return

    blocked = shared.load_blocked()
    posts = []
    for raw_post in raw or []:
        parsed = shared.parse_post_body(raw_post.get("body", ""))
        if parsed["deleted"] or parsed["vibe"] is None:
            continue
        comments = raw_post.get("comments", []) or []
        if not comments:
            continue

        new_replies = []
        for c in comments:
            author = c.get("author", {}).get("login", "")
            if author in blocked or author == username:
                continue
            c_ts = c.get("createdAt")
            if not c_ts:
                continue
            is_new = last_check is None or (
                datetime.fromisoformat(c_ts.replace("Z", "+00:00")) > last_check
            )
            if is_new:
                new_replies.append({
                    "author": author,
                    "text": c.get("body", "").strip(),
                    "created_relative": shared.relative_time(c_ts),
                })

        if not new_replies:
            continue

        vibe = shared.vibe_by_slug(parsed["vibe"])
        posts.append({
            "id": raw_post["number"],
            "title_preview": _title_preview(parsed["text"]),
            "vibe_slug": parsed["vibe"],
            "vibe_emoji": vibe["emoji"] if vibe else "",
            "text": parsed["text"],
            "created_relative": shared.relative_time(raw_post["createdAt"]),
            "reactions": _summarize_reactions(raw_post.get("reactionGroups", [])),
            "new_replies": new_replies,
            "total_replies": len(comments),
        })

    shared.emit({
        "ok": True,
        "posts": posts,
        "last_check": last_check_iso,
        "now": shared.now_iso(),
    })


def cmd_mark_read(_: argparse.Namespace) -> None:
    state = shared.load_last_check()
    state["last_check_ts"] = shared.now_iso()
    shared.save_last_check(state)
    shared.emit({"ok": True})


def _title_preview(text: str) -> str:
    """First line, truncated to 60 chars."""
    first = text.strip().split("\n", 1)[0]
    if len(first) > 60:
        first = first[:57] + "..."
    return first


def _summarize_reactions(groups: list[dict]) -> list[dict]:
    # Duplicated from scroll.py rather than importing to keep each script
    # standalone: keeps the dependency graph readable. If this grows,
    # promote to shared.py.
    cfg = shared.load_config()
    api_to_emoji = {r["api_name"].lower(): r["emoji"] for r in cfg["reactions"]}
    enum_to_api = {
        "THUMBS_UP": "+1",
        "THUMBS_DOWN": "-1",
        "LAUGH": "laugh",
        "HOORAY": "hooray",
        "CONFUSED": "confused",
        "HEART": "heart",
        "ROCKET": "rocket",
        "EYES": "eyes",
    }
    out = []
    for g in groups or []:
        content = g.get("content", "")
        count = g.get("users", {}).get("totalCount", 0)
        if count == 0:
            continue
        api = enum_to_api.get(content)
        if api and api in api_to_emoji:
            out.append({"emoji": api_to_emoji[api], "count": count})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="inbox")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch").set_defaults(func=cmd_fetch)
    sub.add_parser("mark_read").set_defaults(func=cmd_mark_read)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
