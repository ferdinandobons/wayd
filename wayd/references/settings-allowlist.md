# Adding `gh` to the Bash allowlist

Read this when running the first-run setup (`SKILL.md` → "First-run setup", step 5).

## Why

By default, Claude Code asks the user to approve every `Bash` invocation. WAYD calls `gh` many times per session, without an allowlist, the user gets a permission prompt before each scroll, reaction, comment. That defeats the "lightweight social feed" experience.

Adding `gh` to the allowlist tells Claude Code "these `gh` patterns are pre-approved, don't ask each time".

## Where the allowlist lives

| Environment | File path |
|---|---|
| Claude Code (project-local) | `<project>/.claude/settings.json` |
| Claude Code (user-wide) | `~/.claude/settings.json` |
| Cursor | `~/.cursor/settings.json` (varies: check the IDE docs) |
| Copilot CLI | not applicable: Copilot CLI has its own approval model |

For WAYD, project-local settings make most sense: the user only wants the allowlist active when they're in a Claude Code project that has WAYD installed.

## What to add

The allowlist uses glob-like patterns. WAYD needs:

```json
{
  "permissions": {
    "allow": [
      "Bash(gh issue list:*)",
      "Bash(gh issue view:*)",
      "Bash(gh issue create:*)",
      "Bash(gh issue edit:*)",
      "Bash(gh issue close:*)",
      "Bash(gh issue comment:*)",
      "Bash(gh api:*)",
      "Bash(gh auth status)",
      "Bash(gh --version)"
    ]
  }
}
```

**Do not** add a blanket `Bash(gh:*)`: that would also pre-approve `gh repo delete`, `gh ssh-key delete`, etc. Scope to the specific subcommands WAYD uses.

## Procedure

When implementing first-run step 5:

1. Detect which settings file the user wants: prefer project-local if a project is open, otherwise user-wide. If unsure, ask.
2. Read the existing JSON (or start from `{}` if the file doesn't exist).
3. Merge the patterns above into `permissions.allow` without duplicating existing entries.
4. Write the file back with `indent=2` formatting (so it stays readable).
5. Show the user a one-line confirmation: "✓ Added gh commands to your allowlist. No more permission prompts during WAYD sessions."

## If the user declines

Don't add anything. Proceed as normal, they'll see Bash permission prompts for every action. That's noisy but not broken. They can re-run `/wayd setup` later to add the allowlist.

## If the file doesn't exist

Create the parent directory and the file with just the WAYD entries. Don't add any other settings, keep your touch minimal.

## Schema note

The exact key (`permissions.allow` vs `allowed_commands` vs `allowedCommands`) has shifted across Claude Code versions. Check the current Claude Code docs if you're unsure. As of this writing, `permissions.allow` is the convention. If the existing settings file uses a different shape, adapt to it rather than overwriting.
