"""Shared helpers for WAYD: gh CLI wrappers, config loading, post parsing.

All other scripts call into here: they never invoke `gh` directly. This means
swapping the backend (e.g. moving from Issues to Discussions one day) touches
one file, not five.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml  # PyYAML: usually available; falls back below if not
except ImportError:
    yaml = None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SKILL_DIR = Path(__file__).resolve().parent.parent  # wayd/
CONFIG_PATH = SKILL_DIR / "config.yml"
DATA_DIR = SKILL_DIR / "data"
IDENTITY_PATH = DATA_DIR / "identity.json"
BLOCKED_PATH = DATA_DIR / "blocked.txt"
LAST_CHECK_PATH = DATA_DIR / "last-check.json"
ERROR_LOG = DATA_DIR / "error.log"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_config_cache: dict[str, Any] | None = None


def load_config() -> dict[str, Any]:
    """Load wayd/config.yml. Cached after first call."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    raw = CONFIG_PATH.read_text(encoding="utf-8")
    if yaml is not None:
        _config_cache = yaml.safe_load(raw)
    else:
        # Minimal YAML fallback parser for our specific config shape.
        # Real YAML is preferred; this is purely a "don't crash if PyYAML
        # isn't installed" safety net.
        _config_cache = _naive_yaml(raw)
    return _config_cache


def _naive_yaml(text: str) -> dict[str, Any]:
    """Tiny YAML-ish parser for the config shape we actually use.

    Supports: top-level scalars, top-level lists of dicts, nested dicts.
    Doesn't try to be general: if PyYAML is unavailable and someone hand-edits
    config.yml in a weird way, they get a clear error.
    """
    # Practically: tell the user to install PyYAML. The fallback is too risky
    # for arbitrary YAML and we'd rather fail loudly here than silently parse
    # something wrong.
    raise RuntimeError(
        "PyYAML is not installed. Install it with: pip install pyyaml"
    )


# ---------------------------------------------------------------------------
# gh CLI wrapper
# ---------------------------------------------------------------------------


@dataclass
class GhError(Exception):
    """Raised when a gh command fails. Carries enough info to translate
    into a user-friendly message in the calling script."""

    stderr: str
    returncode: int

    def __str__(self) -> str:
        return f"gh failed (exit {self.returncode}): {self.stderr.strip()}"


def gh(args: list[str], *, json_output: bool = False) -> Any:
    """Run a `gh` command and return its stdout.

    If json_output=True, parse stdout as JSON and return the result.
    Raises GhError on non-zero exit.

    We capture stderr separately so we can present a clean error upstream.
    """
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        # gh binary itself is missing
        raise GhError(stderr="gh CLI not installed", returncode=127) from e

    if result.returncode != 0:
        raise GhError(stderr=result.stderr, returncode=result.returncode)

    out = result.stdout
    if json_output:
        if not out.strip():
            return None
        return json.loads(out)
    return out


def gh_check_installed() -> bool:
    """Return True if `gh` is on PATH."""
    try:
        gh(["--version"])
        return True
    except GhError:
        return False


def gh_check_authenticated() -> bool:
    """Return True if `gh auth status` says we're logged in."""
    try:
        gh(["auth", "status"])
        return True
    except GhError:
        return False


def gh_current_user() -> str:
    """Return the authenticated user's GitHub login."""
    return gh(["api", "user", "--jq", ".login"]).strip()


# ---------------------------------------------------------------------------
# Identity / state files
# ---------------------------------------------------------------------------


def load_identity() -> dict[str, Any]:
    """Load identity.json, creating a default if missing.

    Schema:
      {
        "username": str,
        "setup_complete": bool,
        "seen_tour": bool,
        "seen_scroll_hint": bool,
        "seen_compose_hint": bool,
        "coc_accepted": bool
      }
    """
    if not IDENTITY_PATH.exists():
        return {
            "username": "",
            "setup_complete": False,
            "seen_tour": False,
            "seen_scroll_hint": False,
            "seen_compose_hint": False,
            "coc_accepted": False,
        }
    return json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))


def save_identity(identity: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IDENTITY_PATH.write_text(json.dumps(identity, indent=2), encoding="utf-8")


def load_last_check() -> dict[str, Any]:
    """Load last-check.json. Schema:
      {
        "last_check_ts": ISO timestamp,
        "recent_posts": [{"id": int, "ts": ISO}, ...],   # for rate limit
        "recently_seen": [int, ...],                      # last 50 post IDs
        "editable_until": {"<post_id>": ISO}              # for /wayd edit
      }
    """
    if not LAST_CHECK_PATH.exists():
        return {
            "last_check_ts": None,
            "recent_posts": [],
            "recently_seen": [],
            "editable_until": {},
        }
    return json.loads(LAST_CHECK_PATH.read_text(encoding="utf-8"))


def save_last_check(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LAST_CHECK_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_blocked() -> set[str]:
    """Load blocked.txt as a set of usernames (no @ prefix)."""
    if not BLOCKED_PATH.exists():
        return set()
    try:
        lines = BLOCKED_PATH.read_text(encoding="utf-8").splitlines()
        return {line.strip().lstrip("@") for line in lines if line.strip()}
    except OSError:
        # Surface a non-fatal warning upstream; for now, just return empty
        return set()


def add_blocked(username: str) -> None:
    username = username.lstrip("@")
    blocked = load_blocked()
    if username in blocked:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with BLOCKED_PATH.open("a", encoding="utf-8") as f:
        f.write(username + "\n")


def remove_blocked(username: str) -> bool:
    username = username.lstrip("@")
    blocked = load_blocked()
    if username not in blocked:
        return False
    blocked.discard(username)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BLOCKED_PATH.write_text(
        "\n".join(sorted(blocked)) + ("\n" if blocked else ""),
        encoding="utf-8",
    )
    return True


# ---------------------------------------------------------------------------
# Post format: build, parse, render
# ---------------------------------------------------------------------------

MARKER_RE = re.compile(r"<!--\s*wayd:(v\d+)\s+([^>]+?)\s*-->")


def build_post_title(vibe_slug: str, vibe_emoji: str, body: str) -> str:
    """Build the issue title: '[<emoji> <slug>] <preview>'."""
    preview = body.strip().split("\n", 1)[0]
    if len(preview) > 60:
        preview = preview[:57] + "..."
    return f"[{vibe_emoji} {vibe_slug}] {preview}"


def build_post_body(vibe_slug: str, text: str, marker_version: str = "v1") -> str:
    """Build the issue body with the trailing marker comment."""
    return f"{text.strip()}\n\n<!-- wayd:{marker_version} vibe={vibe_slug} -->"


def parse_post_body(body: str) -> dict[str, Any]:
    """Parse a WAYD post body back into structured data.

    Returns:
      {
        "text": str,           # the user-facing text, marker stripped
        "vibe": str | None,    # slug, or None if not a WAYD post
        "deleted": bool,       # True if soft-deleted
        "version": str         # marker version (e.g. 'v1')
      }
    """
    m = MARKER_RE.search(body)
    if not m:
        return {"text": body.strip(), "vibe": None, "deleted": False, "version": ""}

    version = m.group(1)
    attrs_raw = m.group(2)
    attrs = {}
    for part in attrs_raw.split():
        if "=" in part:
            k, v = part.split("=", 1)
            attrs[k.strip()] = v.strip()

    text = MARKER_RE.sub("", body).strip()
    return {
        "text": text,
        "vibe": attrs.get("vibe"),
        "deleted": attrs.get("deleted", "false").lower() == "true",
        "version": version,
    }


def vibe_by_slug(slug: str) -> dict[str, str] | None:
    """Look up a vibe entry by slug in the config."""
    for v in load_config()["vibes"]:
        if v["slug"] == slug:
            return v
    return None


def vibe_by_number(n: int) -> dict[str, str] | None:
    """Look up a vibe entry by its 1-based menu position."""
    vibes = load_config()["vibes"]
    if 1 <= n <= len(vibes):
        return vibes[n - 1]
    return None


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------


def relative_time(iso_ts: str) -> str:
    """Render a GitHub ISO timestamp as 'Nh ago', 'yesterday', 'N days ago'."""
    then = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    delta = now - then
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        return f"{days // 7} weeks ago"
    if days < 365:
        return f"{days // 30} months ago"
    return f"{days // 365} years ago"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Error logging (for non-fatal issues we don't want to surface to the user)
# ---------------------------------------------------------------------------


def log_error(msg: str) -> None:
    """Append a non-fatal error to data/error.log. Never raises."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{now_iso()}] {msg}\n")
    except Exception:
        # Truly best-effort
        pass


# ---------------------------------------------------------------------------
# Output helpers (used by all scripts to print machine-readable JSON
# back to the orchestrating Claude prompt)
# ---------------------------------------------------------------------------


def emit(payload: dict[str, Any]) -> None:
    """Print a JSON payload to stdout for the calling skill to parse."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def emit_error(human_message: str, code: str = "error") -> None:
    """Emit an error payload. The human_message is what the user should see."""
    emit({"ok": False, "code": code, "message": human_message})


# ---------------------------------------------------------------------------
# Error translation: gh error → user-friendly sentence
# ---------------------------------------------------------------------------


def translate_gh_error(e: "GhError", context: str = "default") -> str:
    """Turn a GhError into a user-facing sentence.

    The `context` arg lets callers tweak the wording for their specific
    operation (e.g. "comment" → "Couldn't post your reply", "react" →
    "Couldn't add your reaction"). The default is generic.
    """
    s = (e.stderr or "").lower()

    # Not found: multiple shapes depending on REST vs GraphQL
    if (
        "404" in s
        or "not found" in s
        or "could not resolve to" in s   # GraphQL phrasing
        or "no issues match" in s
    ):
        if context == "comment":
            return "That post isn't there anymore. Maybe the author deleted it."
        return "That post isn't there anymore."

    # Locked thread (commenting on a soft-deleted post)
    if "423" in s or "locked" in s:
        return "This thread has been locked: probably because the post was deleted."

    # Permissions / auth
    if "403" in s or "permission" in s or "forbidden" in s:
        if context == "comment":
            return "GitHub says you can't reply here right now."
        return "GitHub says you can't do that. Try `gh auth status`."

    # Rate-limited by GitHub itself
    if "rate limit" in s or "abuse" in s or "secondary rate" in s:
        return "GitHub is rate-limiting us. Try again in a few minutes."

    # Network / gh-not-installed
    if (
        "could not resolve host" in s
        or "network" in s
        or "connection" in s
        or e.returncode == 127
    ):
        return "Couldn't reach GitHub right now. Check your connection and try again."

    # Generic catch-all: vary by context so the user gets a hint
    if context == "comment":
        return "Couldn't post your reply. Try again in a moment."
    if context == "react":
        return "Couldn't add your reaction. Try again."
    if context == "inbox":
        return "Couldn't load your inbox. Try again in a moment."
    return "Something went wrong on GitHub's end. Try again in a moment."
