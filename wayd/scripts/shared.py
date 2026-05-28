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
    """Load wayd/config.yml. Cached after first call.

    PyYAML is required; we don't ship a fallback parser because any
    half-correct YAML implementation is worse than failing loudly.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    if yaml is None:
        raise RuntimeError(
            "PyYAML is not installed. Run: pip install pyyaml"
        )
    raw = CONFIG_PATH.read_text(encoding="utf-8")
    _config_cache = yaml.safe_load(raw)
    return _config_cache


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


def _default_identity() -> dict[str, Any]:
    """Returned when identity.json is missing or corrupted."""
    return {
        "username": "",
        "setup_complete": False,
        "seen_tour": False,
        "seen_scroll_hint": False,
        "seen_compose_hint": False,
        "coc_accepted": False,
    }


def _default_last_check() -> dict[str, Any]:
    """Returned when last-check.json is missing or corrupted."""
    return {
        "last_check_ts": None,
        "recent_posts": [],
        "recently_seen": [],
        "editable_until": {},
    }


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON via a tmp file + os.replace so partial writes can't leave
    the target file in a corrupted state. os.replace is atomic on POSIX and
    on Windows when the destination exists.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _safe_load_json(path: Path, default_factory) -> dict[str, Any]:
    """Load a JSON state file. If it's missing OR unparseable, return the
    default. Corruption is logged but never crashes the script: a single
    malformed file shouldn't take WAYD out of service. The orchestrator can
    re-derive identity by re-running setup; last-check is recreated on next
    use.
    """
    if not path.exists():
        return default_factory()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log_error(f"corrupted state file at {path.name}: {e}; using defaults")
        return default_factory()


def load_identity() -> dict[str, Any]:
    """Load identity.json, returning defaults if missing or corrupted.

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
    return _safe_load_json(IDENTITY_PATH, _default_identity)


def save_identity(identity: dict[str, Any]) -> None:
    _atomic_write_json(IDENTITY_PATH, identity)


def load_last_check() -> dict[str, Any]:
    """Load last-check.json, returning defaults if missing or corrupted.

    Schema:
      {
        "last_check_ts": ISO timestamp,
        "recent_posts": [{"id": int, "ts": ISO}, ...],   # for rate limit
        "recently_seen": [int, ...],                      # last 50 post IDs
        "editable_until": {"<post_id>": ISO}              # for /wayd edit
      }
    """
    return _safe_load_json(LAST_CHECK_PATH, _default_last_check)


def save_last_check(data: dict[str, Any]) -> None:
    _atomic_write_json(LAST_CHECK_PATH, data)


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

# Matches the ASCII art block in <details> format:
#   <details data-wayd-art>...<pre>...</pre>...</details>
# Group 1 = the art content (may be multi-line).
ART_MARKER_RE = re.compile(
    r"<details data-wayd-art>.*?<pre>(.*?)</pre>.*?</details>",
    re.DOTALL,
)

# Also match the old HTML-comment format for backward compat with old posts.
_ART_COMMENT_RE = re.compile(r"<!--\s*wayd:art\n(.*?)\n-->", re.DOTALL)


def build_post_title(vibe_slug: str, vibe_emoji: str, body: str) -> str:
    """Build the issue title: '[<emoji> <slug>] <preview>'."""
    preview = body.strip().split("\n", 1)[0]
    if len(preview) > 60:
        preview = preview[:57] + "..."
    return f"[{vibe_emoji} {vibe_slug}] {preview}"


def build_post_body(vibe_slug: str, text: str, marker_version: str = "v1") -> str:
    """Build the issue body with the trailing marker comment."""
    return f"{text.strip()}\n\n<!-- wayd:{marker_version} vibe={vibe_slug} -->"


def build_post_body_with_art(
    vibe_slug: str, text: str, art: str, marker_version: str = "v1"
) -> str:
    """Build issue body with ASCII art in a collapsible <details> block.

    Visible on GitHub as '📎 ASCII image' (click to expand), and parseable
    by scroll.py via ART_MARKER_RE. Uses <pre> for monospace rendering.
    Format:
        <text>

        <details data-wayd-art>
        <summary>📎 ASCII image</summary>

        <pre>
        [ascii lines]
        </pre>

        </details>

        <!-- wayd:v1 vibe=<slug> -->
    """
    art_block = f"<details data-wayd-art>\n<summary>📎 ASCII image</summary>\n\n<pre>\n{art}\n</pre>\n\n</details>"
    return f"{text.strip()}\n\n{art_block}\n\n<!-- wayd:{marker_version} vibe={vibe_slug} -->"


def extract_art(body: str) -> str | None:
    """Return the ASCII art embedded in body, or None if not present."""
    m = ART_MARKER_RE.search(body)
    if m:
        return m.group(1)
    # Backward compat: old posts used HTML comment format
    m2 = _ART_COMMENT_RE.search(body)
    return m2.group(1) if m2 else None


def strip_art(body: str) -> str:
    """Return body with the ASCII art block removed (for display purposes)."""
    body = ART_MARKER_RE.sub("", body)
    body = _ART_COMMENT_RE.sub("", body)
    return body.strip()


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
# Post-ID validation
# ---------------------------------------------------------------------------


def validate_post_id(n: int) -> bool:
    """A post-id is a GitHub issue number, which is always >= 1. Negative or
    zero ids could be interpolated into `gh api` URL paths and confuse
    callers; we reject them at the entry point of every script.
    """
    return isinstance(n, int) and n >= 1


# ---------------------------------------------------------------------------
# Reaction summarization (shared by scroll.py and inbox.py)
# ---------------------------------------------------------------------------

# gh's GraphQL output uses these enum names for reaction content
_GH_REACTION_ENUM_TO_API = {
    "THUMBS_UP": "+1",
    "THUMBS_DOWN": "-1",
    "LAUGH": "laugh",
    "HOORAY": "hooray",
    "CONFUSED": "confused",
    "HEART": "heart",
    "ROCKET": "rocket",
    "EYES": "eyes",
}


def summarize_reactions(groups: list[dict]) -> list[dict]:
    """Turn gh's reactionGroups (with enum-named content) into a list of
    {emoji, count} entries, filtered to reactions WAYD exposes in config.
    Reactions with zero count are skipped.
    """
    cfg = load_config()
    api_to_emoji = {r["api_name"].lower(): r["emoji"] for r in cfg["reactions"]}
    out = []
    for g in groups or []:
        content = g.get("content", "")
        count = g.get("users", {}).get("totalCount", 0)
        if count == 0:
            continue
        api = _GH_REACTION_ENUM_TO_API.get(content)
        if api and api in api_to_emoji:
            out.append({"emoji": api_to_emoji[api], "count": count})
    return out


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
