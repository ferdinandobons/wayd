# WAYD, Design Document

**Date:** 2026-05-25
**Author:** Ferdinando Bons (design via brainstorming with Claude)
**Status:** Approved, ready for implementation planning

---

## 1. Overview

**WAYD** (*What Are You Doing?*) is a skill that turns GitHub Issues into a lightweight social platform for programmers. Users install the skill in their AI coding agent of choice: **Claude Code, Cursor, Copilot CLI, Codex, or any tool that supports the agent-skill format**: then post short status updates ("vibes"), scroll a random feed of other people's posts, react with emojis, and reply via comments. They never touch the GitHub UI.

The product is positioned as **"the coffee break for programmers using AI coding agents"**: a r/ProgrammerHumor-style social feed accessible during compilations, test runs, or moments of frustration. It is intentionally lo-fi (text-only, terminal-rendered) and emotionally honest (self-deprecation, cursed code, existential dread, hot takes).

Although WAYD is agent-agnostic, **Claude Code is the primary target environment** (richest plugin/skill support, largest current user base in the agentic-coding space). Other agents are supported through the universal SkillKit / `npx skills` install channels, see §6.

### Goals

- Let strangers in the AI-coding-agents community talk to each other through an unconventional medium.
- Make it feel **fun and meme-y**, not like an issue tracker.
- Require **zero infrastructure**: no custom backend, no database, no auth server: only a public GitHub repo + each user's local `gh` CLI.
- Make all interactions feel **native to the terminal/chat**, never sending the user to a browser or showing raw shell output.
- **Always warn the user before consequential actions** (publishing, deleting, blocking) and provide contextual guidance for first-time and recurring use cases.

### Non-goals

- Real-time chat (notifications poll on-demand, not push).
- Rich media (images, video, file attachments).
- DMs or private channels (everything is public by design).
- Karma / leaderboards / streaks in MVP (kept minimal on purpose to avoid social-pressure dynamics).

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────┐
│ User (programmer with Claude Code installed)             │
└──────────────────────┬───────────────────────────────────┘
                       │ "/wayd scroll", "post a rant", etc.
                       ▼
┌──────────────────────────────────────────────────────────┐
│ WAYD Skill                                               │
│ - SKILL.md (natural-language instructions for Claude)    │
│ - Python helper scripts (post / scroll / react / inbox)  │
│ - config.yml (target repo, vibes, marker regex)          │
│ - data/ (blocked users, last-check timestamps)           │
└──────────────────────┬───────────────────────────────────┘
                       │ shell calls (silent to user)
                       ▼
┌──────────────────────────────────────────────────────────┐
│ gh CLI (already authenticated on user's account)         │
│ - gh issue create / list / view / comment                │
│ - gh api (for reactions, user info, soft-delete)         │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTPS
                       ▼
┌──────────────────────────────────────────────────────────┐
│ github.com/<owner>/wayd  (single public repo)            │
│ - Issues  = posts                                        │
│ - Issue comments = replies                               │
│ - Issue reactions = likes/lol/love                       │
│ - Labels = vibes (vibe:cursed-code, vibe:rip-me, ...)    │
└──────────────────────────────────────────────────────────┘
```

### Why this architecture

- **No custom backend**: GitHub already provides storage, auth, abuse mitigation, rate limiting, and an API. Reinventing any of this would be wasteful.
- **`gh` CLI as the auth layer**: most Claude Code users already have it authenticated. The skill never touches tokens.
- **Trust model**: the repo owner (Ferdinando) is the only privileged identity. Everyone else is a regular GitHub user with no special permissions; posting an issue or a comment on a public repo requires no write access.
- **Identity is real**: usernames are the actual GitHub login. This trades anonymity for accountability, which fits the "small dev community" vibe.

### Key principle: backend opacity

**The user must never see shell commands, JSON, issue IDs, repository URLs, or any GitHub-native artifact.** They see posts, authors, vibes, reactions, replies. The skill instructions explicitly enforce this in SKILL.md: Claude runs `gh` commands silently and presents only formatted human-readable output.

---

## 3. Data model

### Post (= GitHub Issue)

**Title format:**
```
[<emoji> <vibe-slug>] <first 60 chars of body, ellipsized>
```
Example: `[🤡 cursed-code] Looking at a doStuff() method that's 800 lines long...`

**Body format:**
```
<user's post text, 1-1000 characters>

<!-- wayd:v1 vibe=<vibe-slug> -->
```
The trailing HTML comment is a **machine-readable marker** the skill uses to:
- distinguish WAYD posts from any other issues that might exist in the repo,
- carry a schema version (`v1`) so we can evolve the format without breaking old posts,
- redundantly store the vibe (also encoded in labels, but having it in-body is robust to label edits).

The marker is invisible in GitHub's UI but trivially parseable.

**Labels applied automatically:**
- `wayd-post` (filters real WAYD posts from anything else)
- `vibe:<slug>` (exactly one of: `vibe:cursed-code`, `vibe:rip-me`, `vibe:brain-melt`, `vibe:dark-arts`, `vibe:hot-take`, `vibe:shower-thought`, `vibe:existential`, `vibe:procrastinating`)

### Reply (= GitHub Issue Comment)

A standard issue comment. No marker needed, its parent issue's `wayd-post` label is enough to identify the thread as WAYD-owned.

### Reaction (= GitHub Reaction)

Standard GitHub reactions on **issues only** (not on comments, that's a v1.1 candidate, see §8 open questions). Set via `POST /repos/{owner}/{repo}/issues/{n}/reactions`. WAYD exposes a curated subset: 👍 😂 ❤️ 🎉 🚀 👀 😭.

### Soft-delete

Regular users cannot delete issues on a repo they don't own. To allow "delete my own post" behavior, we soft-delete:

1. Edit the issue body to: `[deleted by author] <!-- wayd:v1 deleted=true -->`
2. Close the issue.
3. Lock the issue conversation (prevents further comments).

Scroll filters out any issue whose body matches the `deleted=true` marker. Posts deleted this way still exist on GitHub but disappear from WAYD.

### Vibes (the eight categories)

| Slug | Emoji | What it captures |
|------|-------|------------------|
| `cursed-code` | 🤡 | "Look at this monstrosity I have to deal with" |
| `rip-me` | 🪦 | "Something broke, possibly me" |
| `brain-melt` | 🫠 | "My brain is leaking out my ears" |
| `dark-arts` | 🧙 | "I solved it but please don't ask how" |
| `hot-take` | 🔥 | "Controversial opinion that will start a holy war" |
| `shower-thought` | 💭 | "Random profound or stupid thought" |
| `existential` | 🤔 | "Is this what I wanted to be when I grew up?" |
| `procrastinating` | ☕ | "I should be working but I'm here instead" |

Vibes are fixed in `config.yml`. Adding/removing vibes is a deliberate decision, not a runtime feature.

---

## 4. User experience

### Commands (intents Claude must recognize)

The user speaks in natural language or short slash commands. The skill maps both to the same intents.

| User says | Intent |
|-----------|--------|
| `/wayd`, "open wayd", "any new replies?" | Home: show inbox summary + main menu |
| `/wayd post`, "I want to post", "post a rant" | Compose flow: pick vibe → write text → preview → publish |
| `/wayd scroll`, "let me scroll" | Open scroll mode, random order |
| `/wayd scroll <vibe>`, "show me cursed-code posts" | Scroll filtered by a single vibe |
| `next`, `n`, `skip` (while in scroll) | Show next post |
| `😂`, `react ❤️`, `lol` (while a post is shown) | Add reaction, advance to next |
| `reply: <text>`, `comment: <text>` | Post a comment, advance to next |
| `open thread`, `t` | Show all comments on the current post |
| `/wayd inbox`, "any replies?" | List user's own posts with new replies since last check |
| `/wayd delete` (with one of your posts open) | Soft-delete the current post |
| `/wayd block @user` | Add user to local block list |
| `q`, `quit`, `bye` | Exit scroll mode with a friendly sign-off |

### Scroll-mode rendering

Each post is rendered in the terminal like this:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤡 cursed-code   ·   @mariorossi   ·   2h ago
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Looking at a doStuff() method that's 800 lines long,
written by me 6 months ago. Who is that idiot?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
😂 12   ❤️ 4   🚀 1                💬 7 replies
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

What now? [n]ext  [😂❤️🤯😭🚀👀]  [c]omment  [t]hread  [q]uit
```

### Compose flow

```
You: /wayd post

WAYD: Pick a vibe:
  1. 🤡 cursed-code  : "this code is an abomination"
  2. 🪦 rip-me       : "something died, possibly me"
  3. 🫠 brain-melt   : "my brain is leaking"
  4. 🧙 dark-arts    : "I solved it with evil"
  5. 🔥 hot-take     : "opinion that will start a war"
  6. 💭 shower-thought: "random thought"
  7. 🤔 existential  : "is this the life I wanted?"
  8. ☕ procrastinating: "I should be working"

You: 1

WAYD: Got it, 🤡 cursed-code. What's going on?
      (1-1000 chars, anything you want)

You: There's a function named `processData()` that returns a
     Promise<Promise<Array<any>>>. I'm not even mad. I'm impressed.

WAYD: Preview:
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      🤡 cursed-code   ·   @you   ·   just now
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      There's a function named processData() that returns
      a Promise<Promise<Array<any>>>. I'm not even mad.
      I'm impressed.
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

      Publish? [y]es / [n]o / [e]dit
```

### Inbox flow

```
You: /wayd inbox

WAYD: You have 3 new replies since last check (2 days ago).

  ◆ Your post: "Looking at a doStuff() method..."
    🤡 cursed-code · 3 days ago · 😂 12   ❤️ 4
    └─ 2 new replies
       @anna: "lol I once saw a 1200-line one named handleStuff()"
       @luca: "this is why I drink"

  ◆ Your post: "Is this what I wanted to be when I grew up?"
    🤔 existential · 5 days ago · 😭 8
    └─ 1 new reply
       @giulio: "we all ask ourselves this around 2am"

  [r]eply to one  [n]ext (mark all read)  [q]uit
```

### 4.5, User confirmations & contextual guidance

**Principle.** WAYD treats the user with respect and clarity. It **confirms anything consequential or hard to undo** before doing it, and **proactively explains what's happening** during first-time use, errors, or unfamiliar states. The skill never performs a destructive action silently.

#### Actions that require explicit confirmation

The skill must show a confirmation message and wait for `y` (or natural-language affirmation) before proceeding. A `n` or unclear answer aborts.

| Action | Confirmation shown to user |
|--------|---------------------------|
| **Publish a post** | Full preview + "Publish this? [y]es · [n]o · [e]dit" |
| **Soft-delete own post** | "This will mark your post as `[deleted by author]`. It stays in threads but disappears from scroll. Replies from others remain visible to them. Sure? [y/n]" |
| **Edit own post** (within 5-min grace window) | "Edit your post? Other people may have already seen the original. Edits are visible to them as 'edited X minutes ago'. [y/n]" |
| **Block a user** | "Block @user? You won't see their posts or comments anymore in your scroll. To unblock later: `/wayd unblock @user`. [y/n]" |
| **First-run: add gh to Bash allowlist** | "WAYD needs to call `gh` silently in the background. Add `gh issue *` and `gh api *` to allowed commands in `.claude/settings.json`? If you skip this, every action will trigger a permission prompt. [y/n]" |
| **First-run: accept Code of Conduct** | "By posting on WAYD you agree to the Code of Conduct: <link>. Tap [y] to accept (one time only)." |

#### Informational notices (no confirmation, but always shown)

These don't require a yes/no: but the skill MUST surface them so the user is never confused about what just happened.

| Trigger | Message shown |
|---------|--------------|
| Post published | "✓ Posted. Your vibe is live in others' scroll." |
| Soft-delete done | "✓ Done. The post will show as '[deleted by author]' to anyone in that thread." |
| User blocked | "✓ Blocked @user. To undo: `/wayd unblock @user`." |
| Rate limit hit (5 posts/h) | "Easy there: you've posted 5 times in the last hour. Try again in N minutes. (This limit prevents accidental spam.)" |
| `gh` missing | "WAYD needs the GitHub CLI. Install it: `brew install gh` (macOS) / see https://cli.github.com for other systems. Then run `gh auth login`." |
| `gh` unauthenticated | "Your GitHub CLI isn't logged in. Run: `gh auth login`. Then come back to WAYD." |
| Network failure | "Couldn't reach GitHub right now. Check your connection and try again in a moment." |
| Action only valid in scroll | "Open the feed first with `/wayd scroll`, then you can react/comment from there." |
| Trying to delete someone else's post | "You can only delete your own posts. Use `/wayd block @user` if you want to stop seeing their posts." |
| Empty inbox | "Nothing new. Your posts are quiet, but the world keeps scrolling: try `/wayd scroll` ☕." |
| Empty scroll (filtered too tightly) | "No posts match this vibe yet. Be the first: `/wayd post`." |

#### Contextual guidance (first-time and on-demand)

- **First-ever use of WAYD**: a 30-second tour explains the 8 vibes, the loop (post → scroll → react → repeat), the CoC, and how to ask for help. Stored as "seen tour" in `data/identity.json` so it never plays twice.
- **First time entering scroll mode**: a one-line hint explains the action footer (`[n]ext · 😂 · [c]omment · [t]hread · [q]uit`). Shown once per user.
- **First time composing a post**: a one-liner explains the 8 vibes are mood-tags, that posts are 1-1000 chars, and that they appear under your real GitHub username.
- **`/wayd help` at any moment**: shows the full command list and current context (e.g. "you're in scroll mode, here are scroll-specific actions").
- **Unrecognized intent**: when the user says something the skill can't map (e.g. "make me a sandwich"), respond with a friendly nudge: "Not sure what you mean. Try `/wayd help` for things I can do."

#### Implementation note for SKILL.md

The skill instruction file (`SKILL.md`) MUST encode these confirmations as **hard requirements** for Claude, not suggestions. The exact phrasing can vary (Claude should sound natural, not robotic), but **the confirmation step itself cannot be skipped under any circumstance** for the actions listed above. This applies even if the user appears to be in a hurry or has confirmed similar actions before in the session.

---

## 5. Code structure

### Repository layout

```
wayd/                              ← public GitHub repo
├── README.md                      ← landing page + install instructions
├── CODE_OF_CONDUCT.md             ← community rules
├── LICENSE                        ← MIT
├── plugin.json                    ← Claude Code Plugin manifest
├── wayd/                          ← THE SKILL itself
│   ├── SKILL.md                   ← natural-language instructions for Claude
│   ├── config.yml                 ← repo target, vibes list, limits
│   ├── scripts/
│   │   ├── shared.py              ← gh wrappers, parsing, formatting
│   │   ├── post.py                ← create + soft-delete posts
│   │   ├── scroll.py              ← list + random-shuffle posts
│   │   ├── react.py               ← add reaction to issue
│   │   ├── comment.py             ← post a reply
│   │   └── inbox.py               ← user's posts with new comments
│   └── data/                      ← per-user local state (not in repo)
│       ├── identity.json          ← cached gh username
│       ├── blocked.txt            ← locally blocked users
│       └── last-check.json        ← timestamps for inbox diffing
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   └── post.yml               ← discourages posting via GitHub UI directly
│   └── workflows/
│       ├── release.yml            ← bundles .skill artifact on tag push
│       └── moderation.yml         ← optional v2: auto-label/close non-WAYD issues
└── docs/superpowers/specs/        ← design docs (this file lives here)
```

### Why Python for helpers

- Already available on macOS / Linux / WSL.
- Stdlib has everything needed (`subprocess`, `json`, `random`, `re`, `pathlib`, `datetime`).
- No `pip install` step: keeps install friction at zero.
- Easier to reason about than shell for the parsing-heavy work.

`SKILL.md` orchestrates: it tells Claude *when* to call each helper and *how* to interpret the output. The Python scripts do the mechanical work (`gh` invocations, JSON munging, formatting).

### Boundaries

Each script has one job and a documented input/output contract. `shared.py` owns all `gh` invocations, other scripts call into it, never `subprocess.run` directly. This means: changing the GitHub backend (e.g. switching to Discussions later) touches one file.

---

## 6. Installation & distribution

The skill is distributed through five channels to cover the major Claude/AI-coding environments. The README publishes all of them.

```markdown
## Installation

### Claude Code Plugin (recommended)
claude plugin marketplace add <owner>/wayd
claude plugin install wayd@wayd

### CLI Install (universal)
npx skills add <owner>/wayd

### Clone & Copy
git clone https://github.com/<owner>/wayd.git
cp -r wayd/wayd ~/.claude/skills/

### Git Submodule
git submodule add https://github.com/<owner>/wayd.git .agents/wayd

### SkillKit (Claude Code, Cursor, Copilot)
npx skillkit install <owner>/wayd
```

A GitHub Action (`release.yml`) bundles the `wayd/` folder into a `.skill` zip on every tag push and attaches it to the GitHub Release, this is what Claude.ai users download.

### First-run setup

On the user's first `/wayd` invocation, the skill:

1. Runs `gh auth status` silently. If `gh` is missing or not authenticated, shows clear install/login instructions.
2. Caches the GitHub username via `gh api user --jq .login` into `data/identity.json`.
3. Asks the user (one time) for permission to add `gh issue *` and `gh api *` to the Bash allowlist in `.claude/settings.json`: so subsequent commands don't trigger a permission prompt for each call.
4. Greets the user and shows the menu.

---

## 7. Limits, edge cases, and safety

### Rate limiting (anti-spam)

- **5 posts per hour per user** (client-side, enforced by checking timestamps in `data/last-check.json`). On hit, the skill shows a friendly message: *"Easy there, take a breath. Try again in N minutes."* This doesn't prevent a determined abuser (they could delete the local file), but it stops well-meaning accidental spam.
- **GitHub's own abuse detection** handles serious cases.
- **Repo owner moderation**: standard GitHub abilities: block users, lock issues, hide comments. The optional `moderation.yml` action can auto-label suspicious posts but is **not** part of MVP.

### Block list (per-user)

`data/blocked.txt` is one username per line. `scroll.py` filters out posts and comments authored by anyone on this list. Local-only, has no effect on the repo.

### Soft-delete

Already described in §3. Important: the skill never claims to have "deleted" anything more strongly than the truth (it always shows posts as "[deleted by author]" in their parent threads).

### Network / `gh` failures

Each script catches `gh` errors and surfaces a single human-readable message ("WAYD couldn't reach GitHub right now. Try again in a moment.") rather than dumping a stack trace.

### Code of conduct

A short, plain-language `CODE_OF_CONDUCT.md` covers:
- No harassment, slurs, doxxing.
- No NSFW.
- No commercial spam / link farming.
- The repo owner (Ferdinando) is the final moderator and may ban users from the repo.

The skill shows a one-line consent message on first use: *"By posting, you agree to the Code of Conduct (read it: <link>)."*, required-acknowledge once, then never again.

### What we explicitly don't ship in MVP

- Notifications (push or otherwise): user pulls inbox manually.
- Threaded replies (replies to replies): GitHub issue comments are flat.
- Search.
- Profile pages.
- Following / friending.
- Hall of fame / trending / streaks / karma.

These are deliberate. Each could be added in v2 if the community sticks.

---

## 8. Risks and open questions

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Spam wave (someone scripts post creation) | Medium | Client-side rate limit + GitHub abuse detection + manual repo owner intervention |
| Toxic content / harassment | Medium | CoC + repo-level user blocking + local block list + community is small initially |
| `gh` CLI unauthenticated or missing | High at first use | First-run check with clear, copy-pasteable install/login commands |
| GitHub API rate limit hit | Low | 5000 req/h with auth is plenty; cache scroll lists locally for 5 min |
| Issue title/body XSS-style abuse breaks parsing | Low | All parsing is done from `gh`-emitted JSON (already escaped); user content is never executed as code or rendered as HTML: only printed verbatim in the terminal |
| Repo owner gets exhausted moderating | Medium | Make the optional `moderation.yml` workflow easy to enable when needed |

**Open questions (to revisit during implementation):**

1. Should the random scroll exclude posts the user has already seen recently? Yes for "fresh feel", but requires local tracking. **Tentative answer:** yes, track last 50 seen post IDs locally, exclude from random pool.
2. Should comments also support reactions? GitHub allows it. **Tentative answer:** yes for v1.1, no for MVP (keeps the action set small).
3. Should we let users edit their post after publishing? GitHub allows it. **Tentative answer:** yes, but only within 5 minutes of posting (matches Twitter-like norms).

---

## 9. Success criteria

WAYD is successful if:

1. **A user can install it** in under 2 minutes following the README.
2. **First post takes under 30 seconds** from `/wayd post` to "published".
3. **Scroll feels fun**: testers describe it as "I wasted 10 minutes scrolling and laughed".
4. **No one ever sees a raw shell command or `gh` output** during normal use.
5. The repo accumulates **≥50 posts and ≥3 distinct users** within 2 weeks of soft-launch in dev communities (Discord servers, X/Twitter dev circles).

---

## 10. Next steps

1. User reviews this spec and approves / requests changes.
2. Move to `writing-plans` to produce a concrete implementation plan with phases, tasks, and verification criteria.
3. Implement MVP (skill code + repo scaffolding).
4. Soft-launch to a small dev community for feedback.
