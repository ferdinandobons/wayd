#!/usr/bin/env python3
"""Add a reaction to a WAYD post.

Subcommand:
  add --post-id N --emoji E   : emits {ok}

We map the user's emoji (👍 😂 ❤️ 🎉 🚀 👀 😭) to the GitHub API name
("+1", "laugh", "heart", "hooray", "rocket", "eyes", "confused") using
the table in config.yml.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import shared  # noqa: E402


def cmd_add(args: argparse.Namespace) -> None:
    cfg = shared.load_config()
    repo = cfg["repo"]

    # Resolve the emoji → api_name. Accept either the emoji itself or the api_name.
    emoji_to_api = {r["emoji"]: r["api_name"] for r in cfg["reactions"]}
    api_names = {r["api_name"] for r in cfg["reactions"]}

    if args.emoji in emoji_to_api:
        api_name = emoji_to_api[args.emoji]
    elif args.emoji in api_names:
        api_name = args.emoji
    else:
        allowed = ", ".join(r["emoji"] for r in cfg["reactions"])
        shared.emit_error(
            f"I don't have that reaction. Pick one of: {allowed}",
            code="bad_emoji",
        )
        return

    try:
        shared.gh(
            [
                "api",
                "--method", "POST",
                f"repos/{repo}/issues/{args.post_id}/reactions",
                "-f", f"content={api_name}",
                "--header", "Accept: application/vnd.github+json",
            ]
        )
    except shared.GhError as e:
        shared.log_error(f"react failed: {e}")
        shared.emit_error(shared.translate_gh_error(e, context="react"), code="gh_failed")
        return

    shared.emit({"ok": True, "post_id": args.post_id, "emoji": args.emoji})


def main() -> None:
    parser = argparse.ArgumentParser(prog="react")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("--post-id", type=int, required=True)
    p_add.add_argument("--emoji", required=True)
    p_add.set_defaults(func=cmd_add)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
