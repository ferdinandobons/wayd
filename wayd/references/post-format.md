# Post format reference

Read this when you need to understand exactly how WAYD posts are stored as GitHub issues, or when adding/changing the format.

## Why a custom marker

GitHub Issues weren't designed for social posts. To use them as one without polluting unrelated work, every WAYD post embeds a machine-readable marker in its body. This lets us:

1. Distinguish WAYD posts from regular issues if the repo ever gets used for other things.
2. Parse the vibe back from the body (also encoded in labels, but the body marker is the source of truth).
3. Carry a schema version so we can evolve without breaking old posts.
4. Mark soft-deleted posts (we can't actually delete issues as non-admin users).

## Title format

```
[<emoji> <vibe-slug>] <body first line, truncated to 60 chars>
```

Examples:
```
[🤡 cursed-code] Looking at a doStuff() method that's 800 lines long...
[🤔 existential] I move JSON from one endpoint to another for a living
[🪦 rip-me] git push --force on main at 23:47, please send help
```

If the first line is ≤60 chars, no ellipsis. If longer, truncate to 57 chars + "...".

## Body format

```
<user's text, 1 to 1000 characters>

<!-- wayd:v1 vibe=<slug> -->
```

The blank line between text and marker is intentional, it keeps the GitHub UI rendering clean even though we never tell users to look at GitHub.

Examples:
```
Looking at a doStuff() method that's 800 lines long, written by me 6 months ago. Who is that idiot?

<!-- wayd:v1 vibe=cursed-code -->
```

## Soft-deleted body

When a user deletes their own post (via `/wayd delete`), we can't actually remove the issue, non-admins lack that permission. Instead:

```
[deleted by author] <!-- wayd:v1 deleted=true -->
```

We also `close` and `lock` the issue so no further comments can be added. The scroll script filters these out by checking `parsed.deleted == True`.

## Labels

Every WAYD post gets exactly two labels:
- `wayd-post`: identifies any WAYD post (used for filtering in `gh issue list`)
- `vibe:<slug>`: one of `vibe:cursed-code`, `vibe:rip-me`, `vibe:brain-melt`, `vibe:dark-arts`, `vibe:hot-take`, `vibe:shower-thought`, `vibe:existential`, `vibe:procrastinating`

Labels must exist on the repo before they can be applied. The repo owner creates them once at setup time (see the `setup-labels.sh` script in the repo root, if present, or do it manually via GitHub UI).

## Marker grammar

```
<!-- wayd:<version> <key>=<value> [<key>=<value> ...] -->
```

- `version` is `v1` for the current schema.
- Keys we use: `vibe=<slug>`, `deleted=true`.
- Whitespace between attributes is flexible; the regex in `shared.py` (`MARKER_RE`) handles any reasonable spacing.

## Parsing

`shared.parse_post_body(body)` returns:

```python
{
    "text": str,        # body with marker stripped, whitespace trimmed
    "vibe": str | None, # the slug, or None if no marker present
    "deleted": bool,    # True if marker has deleted=true
    "version": str,     # the version string from the marker
}
```

If a post body has no marker, `vibe` is `None` and `deleted` is `False`. The scroll script treats markerless issues as "not a WAYD post" and skips them.

## Evolution

If we ever need a `v2` schema (e.g. adding a "language=<code>" attribute for language-filtered scrolling):

1. Bump `marker_version` in `config.yml`.
2. New posts use `v2`. Old posts keep `v1`: `parse_post_body` already handles both because it accepts any `v\d+`.
3. Update `parse_post_body` to extract any new attributes you care about.
4. Backward compatibility is automatic: code that only reads `vibe` and `deleted` works against both versions.
