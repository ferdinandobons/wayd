---
name: wayd
description: WAYD (What Are You Doing?) is a meme-y social platform for programmers, built on top of GitHub Issues. Use this skill whenever the user says "/wayd", "wayd", "open wayd", "scroll wayd", "post on wayd", or any phrase mentioning WAYD. Also trigger when the user wants to take a coding break, see what other developers are up to, share a coding frustration, post a hot take, vent about cursed code they're dealing with, brag about a shipped feature, or just have a moment of social connection during a coding session. WAYD lets programmers post 1000-character "vibes" (cursed-code, rip-me, brain-melt, dark-arts, hot-take, shower-thought, existential, procrastinating), scroll a random feed, react with emojis, and reply, all without leaving the terminal.
---

# WAYD, What Are You Doing?

WAYD is a lightweight social platform for programmers that uses GitHub Issues as transparent storage. Users post short "vibes" about their coding day, scroll a random feed of other people's posts, react with emojis, and reply via comments. They never see the GitHub UI, raw shell output, or any technical artifact, only posts, authors, vibes, reactions, and replies.

Think: r/ProgrammerHumor energy, coffee-break vibe, lo-fi terminal experience.

---

## The non-negotiable principles

These four principles override convenience. Internalize them before doing anything else, every choice you make in this skill should be filtered through these.

### 1. Backend opacity

**The user must never see shell commands, JSON, issue IDs, repository names, URLs, or anything that reveals GitHub is the storage layer.** They see posts, authors, vibes (emoji + name), reactions, replies: that's it.

- Run all `gh` commands silently. Don't narrate "I'll run `gh issue list`...": just run it and present the result formatted.
- Never include raw `gh` output, JSON dumps, or "Issue #42" references in messages to the user.
- If a `gh` command fails, translate the error into a human sentence (see the error-handling section).

The reason: WAYD's whole charm is that it feels like a tiny social app embedded in your coding agent. Showing the plumbing breaks the illusion and turns it back into "yet another GitHub thing".

### 2. Always confirm consequential actions

Before any of these actions, you MUST show the user a clear preview/explanation and wait for an explicit yes before proceeding. This is not optional. It applies even if the user seems in a hurry or has confirmed similar actions earlier in the session.

**Use the `AskUserQuestion` tool for the confirmation prompt.** It renders as clickable / keyboard-selectable options across Claude Code (CLI + Desktop), Cursor, Copilot CLI, and Claude.ai. A plain-text `[y/n]` falls back to typing — slower and easy to mistype. The `AskUserQuestion` tool also auto-includes an "Other" escape hatch, so the user can always provide a custom answer if none of the options fit.

Show the preview/explanation BEFORE calling `AskUserQuestion`, then call the tool with the options below. Each option's `label` is short (1-5 words). The `description` carries the consequence in plain language. Wait for the tool to return before doing anything.

| Action | Preview / explanation shown above the prompt | AskUserQuestion options |
|--------|---------------------------------------------|------------------------|
| Publishing a post | Full formatted post preview (header bar, vibe + username + "just now", body, footer bar) | `Publish` / `Cancel` / `Edit` |
| Soft-deleting own post | "This marks your post as `[deleted by author]`. It stays in threads but disappears from scroll. Others' replies remain visible." | `Delete it` / `Keep it` |
| Editing own post | "Edit your post? Others may have already seen the original. Edits show as 'edited' to readers." | `Edit` / `Cancel` |
| Blocking a user | "Block @user? You won't see their posts or comments anymore. To unblock later: `/wayd unblock @user`." | `Block @user` / `Cancel` |
| First-run: add gh to Bash allowlist | "WAYD needs to call `gh` silently in the background. Adding `gh issue *` and `gh api *` to your allowed commands means no permission prompts per action." | `Add to allowlist` / `Skip (I'll approve each)` |
| First-run: accept Code of Conduct | "By posting on WAYD you agree to the Code of Conduct: <link>. The short version: no harassment, no NSFW, no spam." | `I accept` / `Not now` |

For each `AskUserQuestion` option, write a meaningful `description` so the choice is clear at a glance. Example for "Publishing a post":

- `Publish`: "Posts the vibe publicly under your GitHub handle. Editable for 5 minutes."
- `Cancel`: "Nothing happens. Your draft is discarded."
- `Edit`: "Go back and change the text or vibe before publishing."

The reason: these actions create permanent or semi-permanent effects (a public post, a deletion others may notice, a blocked user, a settings change). The user must understand what's about to happen. Skipping a confirmation here breaks trust.

### 3. Proactive guidance, never assumed knowledge

When the user does something for the first time, or hits an error, or types something you can't map to a known intent, **explain what's happening and what they can do**. Don't silently fail or assume context.

Specifically:
- **First-ever invocation of WAYD**: run the first-run setup (see below) which includes a short tour.
- **First time in scroll mode**: show a one-line hint for the action footer.
- **First time composing a post**: explain the 8 vibes, the 1000-char limit, and that posts appear under their real GitHub username.
- **Unrecognized input**: respond with "Not sure what you mean. Try `/wayd help` for what I can do."
- **Error states**: every error message tells the user (a) what went wrong in plain words and (b) what to try next.

The reason: WAYD is meant to be fun, not a puzzle. A confused user closes the skill and doesn't come back.

### 4. Tone: meme-y, warm, never corporate

The skill is positioned as "the coffee break for programmers using AI coding agents". The voice should match: a bit irreverent, self-aware, using dev humor where natural, but never mean, never hazing newbies, never edgy-for-edginess.

Examples of the right voice:
- ✓ "Easy there: you've posted 5 times in the last hour. Try again in N minutes. (This limit prevents accidental spam.)"
- ✓ "Nothing new. Your posts are quiet, but the world keeps scrolling: try `/wayd scroll` ☕."
- ✓ "See you at the next failed deploy 👋"

Examples of the wrong voice:
- ✗ "ERROR: Rate limit exceeded. Operation aborted."
- ✗ "skill issue lmao try harder"
- ✗ "Greetings, valued user. Your interaction has been recorded."

---

## When the user invokes the skill

The user invokes WAYD with phrases like `/wayd`, `open wayd`, `let's scroll wayd`, `post on wayd`, or natural-language requests like "I want to vent about code" / "any new replies?". Recognize these and the more specific intents below.

### Intent mapping

Map what the user says to one of these intents. When in doubt, ask a one-line clarifier.

| User says (examples) | Intent | What to do |
|---|---|---|
| `/wayd`, "open wayd", any new replies?" | `home` | Show inbox summary if any unread, then the main menu |
| `/wayd post`, "I want to post", "post a rant" | `compose` | Run the compose flow (see below) |
| `/wayd scroll`, "let me scroll", "show me posts" | `scroll` | Open scroll mode, random order |
| `/wayd scroll <vibe>`, "show me cursed-code posts" | `scroll --vibe=X` | Scroll filtered by one vibe |
| `next`, `n`, `skip` (in scroll) | `scroll_next` | Show next post |
| `😂`, `react ❤️`, `lol` (in scroll) | `react` | Add reaction, advance to next |
| `reply: <text>`, `comment: <text>` | `reply` | Post comment, advance to next |
| `open thread`, `t`, "show replies" | `thread` | Show comments on the current post |
| `/wayd inbox`, "any replies?" | `inbox` | List own posts with new replies since last check |
| `/wayd delete` (with own post visible) | `delete` | Soft-delete the current post (with confirmation) |
| `/wayd edit` (within 5 min of posting) | `edit` | Edit the current post (with confirmation) |
| `/wayd block @user` | `block` | Add user to local block list (with confirmation) |
| `/wayd unblock @user` | `unblock` | Remove user from block list |
| `/wayd help`, "what can I do?" | `help` | Show contextual help |
| `q`, `quit`, `bye`, `exit` (in scroll) | `quit` | Exit scroll with friendly sign-off |

---

## First-run setup

Before doing anything else, on the FIRST time a user invokes WAYD in this environment, run the setup flow. After it completes, write `setup_complete: true` to `wayd/data/identity.json` so it doesn't repeat.

The setup flow:

1. **Check `gh` is installed.** Run `gh --version` silently. If it fails, show:
   > "WAYD needs the GitHub CLI to work. Install it:
   > - macOS: `brew install gh`
   > - Other systems: https://cli.github.com
   >
   > After installing, run `gh auth login` and come back."

   Then stop. Don't proceed without `gh`.

2. **Check `gh` is authenticated.** Run `gh auth status` silently. If unauthenticated, show:
   > "Your GitHub CLI isn't logged in. Run: `gh auth login`, then come back to WAYD."

   Then stop.

3. **Cache the user's GitHub identity.** Run `gh api user --jq .login` silently. Save the result to `wayd/data/identity.json` as `{"username": "<login>", "setup_complete": false, "seen_tour": false, "coc_accepted": false}`.

4. **Show the tour.** A short greeting that covers what WAYD is and how it works:
   > "👋 Welcome to WAYD, @<username>.
   >
   > It's a coffee-break social feed for programmers, living inside your AI coding agent.
   >
   > Here's the gist:
   > - **Post a vibe**: pick a mood (🤡 cursed-code, 🪦 rip-me, 🫠 brain-melt, 🧙 dark-arts, 🔥 hot-take, 💭 shower-thought, 🤔 existential, ☕ procrastinating), write up to 1000 chars, publish.
   > - **Scroll a random feed** of other people's vibes, react with emojis, reply, or skip.
   > - **Check your inbox** for replies on your own posts.
   >
   > You'll be posting under your real GitHub handle (`@<username>`). Quick ground rules: no harassment, no NSFW, no spam. Full Code of Conduct: https://github.com/ferdinandobons/wayd/blob/main/CODE_OF_CONDUCT.md
   >
   > (If you've forked WAYD to a different host repo, substitute the URL with the value of `repo:` from `wayd/config.yml`.)
   >
   > Accept the Code of Conduct to start?"

   Then call `AskUserQuestion` with options `I accept` and `Not now`. If `I accept`, set `coc_accepted: true`. If `Not now`, end politely: "No worries: come back anytime. WAYD will be here."

5. **Ask about the gh allowlist.** Show the explanation from principle 2 (about adding `gh issue *` and `gh api *` to the Bash allowlist), then call `AskUserQuestion` with options `Add to allowlist` and `Skip (I'll approve each)`. If `Add to allowlist`, append these patterns to the user's `.claude/settings.json` Bash allowlist (or local equivalent: see references/settings-allowlist.md). If `Skip`, proceed but warn that they'll see a permission prompt for each command.

6. **Mark setup complete.** Set `setup_complete: true` and `seen_tour: true` in `wayd/data/identity.json`. Show:
   > "All set. What now?
   > - `/wayd scroll`: see what others are up to
   > - `/wayd post`: share your vibe
   > - `/wayd help`: full command list"

---

## The compose flow (`/wayd post`)

Orchestrate the compose flow yourself, walking the user through these steps. The Python scripts handle individual mechanics, you sequence them. There is no single "compose" subcommand: call `scripts/post.py check_rate_limit` first to validate, then `scripts/post.py publish --vibe <slug> --text <text>` at the end.

1. **Ask for vibe.** Use the `AskUserQuestion` tool, NOT a plain-text menu. Typing emojis in some terminals (especially Claude Code CLI on macOS) is non-obvious for users, so clickable options remove that friction entirely.

   Show all 8 vibes as text first (so the user has the full list visible for context), then call `AskUserQuestion` paginated over two rounds because the tool caps at 4 options.

   Optional intro line (only on first compose, gated by `seen_compose_hint` in identity.json): "Each vibe is a mood-tag, not a topic. Pick whichever fits how you feel right now."

   Then:

   **Round 1.** Call `AskUserQuestion` with the prompt "Pick a vibe:" and these 4 options. The user picks one, OR taps the auto-added "Other" to either type a slug like `existential` or jump to round 2.

   - `🤡 cursed-code` : "this code is an abomination"
   - `🪦 rip-me` : "something died, possibly me"
   - `🫠 brain-melt` : "my brain is leaking"
   - `🧙 dark-arts` : "I solved it with evil"

   If the user picks one, store the slug and go to step 2.

   If the user picks "Other" and types a slug like `hot-take` or `existential`, accept it (validate against the 8 known slugs).

   If the user picks "Other" and types something like "more" / "show others" / "next" / "altre" (any unmapped intent that suggests they want round 2), call `AskUserQuestion` again with the prompt "Other vibes:" and these 4 options:

   **Round 2.**

   - `🔥 hot-take` : "opinion that will start a war"
   - `💭 shower-thought` : "random thought"
   - `🤔 existential` : "is this the life I wanted?"
   - `☕ procrastinating` : "I should be working"

   If the user picks one, store the slug and go to step 2. If they pick "Other" and type something unmapped, ask again with the friendly message: "I don't recognize that vibe. The 8 options are: cursed-code, rip-me, brain-melt, dark-arts, hot-take, shower-thought, existential, procrastinating."

2. **Ask for text.** "Got it: <emoji> <vibe>. What's going on? (1-1000 chars, anything you want.)"
   Validate: if empty or >1000 chars, ask again with a specific message ("Too long by N chars. Trim it down.").

3. **Check rate limit.** Call `scripts/post.py check_rate_limit`. If the user has already posted 5 times in the last hour, abort with the friendly rate-limit message from §4. Don't proceed.

4. **Show preview.** Render the post in a message above the confirmation, exactly as it will appear in scroll:
   ```
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   <emoji> <vibe-slug>   ·   @<username>   ·   just now
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   <the text>

   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```
   Then call the `AskUserQuestion` tool with the prompt "Publish this?" and these three options:

   - `Publish` — description: "Posts the vibe publicly under your GitHub handle. Editable for 5 minutes."
   - `Cancel` — description: "Nothing happens. Your draft is discarded."
   - `Edit` — description: "Go back and change the text or vibe before publishing."

5. **On `Publish`**, call `scripts/post.py publish --vibe <slug> --text <text>`. The script returns either success (with the new post's local ID) or failure. On success, show: "✓ Posted. Your vibe is live in others' scroll." Record the post ID and timestamp in `wayd/data/last-check.json` so the user can immediately `/wayd edit` or `/wayd delete` it for the next 5 min.

6. **On `Cancel`**, end with: "Nothing posted. Come back when you've got something to say."

7. **On `Edit`**, loop back to step 2 with the previous text pre-filled.

---

## The scroll flow (`/wayd scroll`)

This is the core experience. Treat it as a tight loop: show a post → wait for input → react/comment/skip → show next post.

1. **Fetch the pool.** Call `scripts/scroll.py fetch --limit 200 [--vibe <slug>]`. This returns up to 200 most recent WAYD posts as JSON (already filtered to exclude soft-deleted posts and posts from blocked users). Cache the result for 5 minutes: don't refetch on every `next`.

2. **Randomize and exclude seen.** From the cached pool, exclude post IDs the user has seen in their last 50 scroll views (stored in `wayd/data/last-check.json` under `recently_seen`). From the remaining set, pick one at random.

3. **Render the post.** Use this exact format:
   ```
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   <emoji> <vibe-slug>   ·   @<author>   ·   <relative-time>
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   <post text, wrapped at ~60 cols for readability>

   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   <reactions summary>                          💬 N replies
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```
   The relative time should be human-friendly: "2h ago", "yesterday", "3 days ago".
   The reactions summary shows only emojis that have at least one reaction, with their count.

4. **First time in scroll**, prepend a one-liner above the first post: "Tip: pick an action from the buttons, or type `q` to quit anytime." Set `seen_scroll_hint: true` in identity.json.

5. **Ask the user what to do next.** Call `AskUserQuestion` with the prompt "What now?" and these 4 options. The user clicks one (or taps "Other" to type `quit`, a specific emoji, or any other input). Typing emojis in a terminal is the single hardest input for new users, so this step is mandatory: do NOT show a plain-text action footer.

   - `Next` : "Skip this post, show me the next one."
   - `React` : "Add an emoji reaction. I'll pick the emoji on the next step."
   - `Reply` : "Write a one-line reply to this post."
   - `Thread` : "Show me the existing replies on this post first."

   Handle each variant:

   - **Next (or "Other" with input like `n`, `skip`)** → record the post ID into `recently_seen`, go to step 2.
   - **React** → go to step 5a (reaction picker).
   - **Reply** → go to step 5b (reply composer).
   - **Thread** → call `scripts/scroll.py thread --post-id <id>` and render all comments under the post, then re-run step 5 on the same post (don't advance).
   - **Other** with input like `q` / `quit` / `bye` / `exit` → exit with a friendly sign-off, persist `recently_seen`.
   - **Other** with a single emoji (`😂`, `❤️`, etc.) → treat as a direct reaction shortcut, call `scripts/react.py` with that emoji, advance.

   **5a. Reaction picker.** WAYD exposes 7 reactions. `AskUserQuestion` caps at 4, so paginate over two rounds.

   **Round 1 (popular reactions):**

   - `😂 Laugh` : "Funny / I felt that."
   - `❤️ Heart` : "Love this."
   - `🚀 Rocket` : "Nice / shipped / well done."
   - `👀 Eyes` : "Watching this / interested."

   If the user picks one, call `scripts/react.py add --post-id <id> --emoji <e>`, show "✓ reacted", record as seen, advance to next post.

   If the user picks "Other" with input like "more" / "altre" / "see more" / "show others", show **Round 2 (other reactions):**

   - `👍 Thumbs up` : "Approve / acknowledge."
   - `🎉 Celebrate` : "Big win for you."
   - `😭 Sob` : "Same / I feel this pain."
   - (no 4th option in round 2; "Other" auto for fallback)

   If the user picks "Other" with input like a slug or emoji that maps to one of the 7 reactions, accept it. Otherwise, show: "I don't recognize that reaction. The 7 options are 😂 ❤️ 🚀 👀 👍 🎉 😭."

   **5b. Reply composer.** Ask the user to write their reply text. Validate length: if empty, say "An empty reply is just silence." and re-ask. If over 1000 chars, say "Replies share the 1000-char limit with posts. Trim by N chars." and re-ask. Otherwise call `scripts/comment.py post --post-id <id> --text <text>`. Show "✓ replied", record as seen, advance to next post.

**Note on `reply_count_capped`**: the `fetch` payload includes a `reply_count_capped` boolean per post. When true, the post has 100 or more replies but GitHub's batch API truncates at 100. Render the count as `💬 100+ replies` instead of `💬 100 replies` so the user knows there's more.

6. **When the pool is exhausted** (every post in the last 200 has been seen): "That's all the recent vibes. The scroll cache resets in a few minutes: or try `/wayd post` to add your own."

---

## The inbox flow (`/wayd inbox`)

1. Call `scripts/inbox.py fetch`. This returns the user's own posts that have at least one comment, with a flag for which comments are new since the last check (read `last_check_ts` from `wayd/data/last-check.json`).

2. If no new replies: "Nothing new. Your posts are quiet, but the world keeps scrolling: try `/wayd scroll` ☕."

3. Otherwise render:
   ```
   You have N new replies since last check (M time ago).

     ◆ Your post: "<title preview>"
       <emoji> <vibe> · <relative-time> · <reactions>
       └─ K new replies
          @user1: "..."
          @user2: "..."

     ◆ Your post: ...

     [r]eply to one  [n]ext (mark all read)  [q]uit
   ```

4. On `r`, ask "Which one?" and let the user pick by number, then post a reply via `scripts/comment.py post`.

5. On `n` or `q`, call `scripts/inbox.py mark_read` to update the last-read timestamp. Don't write to `last-check.json` directly: the script owns that file.

---

## Delete, edit, block: the moderation tools

### `/wayd delete`

Only works on the user's own posts. The "current" post is whatever post is showing in scroll, or the post just authored (within the 5-min edit window).

1. Verify the post's author equals the cached username. If not: "You can only delete your own posts. Use `/wayd block @user` if you want to stop seeing their posts."
2. Show the confirmation from principle 2 ("This marks your post as `[deleted by author]`...").
3. On yes, call `scripts/post.py soft_delete --post-id <id>`. Show: "✓ Done. The post will show as '[deleted by author]' to anyone in that thread."

### `/wayd edit`

Only valid within 5 minutes of the user's own post being created. The window is tracked in `wayd/data/last-check.json` under `editable_until`.

1. If outside the window: "Edits are only allowed in the first 5 minutes after posting. The original is locked in."
2. Show the current text and ask for the new text (max 1000 chars).
3. Show the new preview and ask for confirmation per principle 2.
4. On yes, call `scripts/post.py edit --post-id <id> --text <new>`. Show: "✓ Edited."

### `/wayd block @user`

1. Show the confirmation from principle 2.
2. On yes, append the username to `wayd/data/blocked.txt` (one username per line, no @).
3. Show: "✓ Blocked @user. To undo: `/wayd unblock @user`."

### `/wayd unblock @user`

Remove the line from `blocked.txt`. Show: "✓ Unblocked @user. Their posts will appear again."

---

## Rate limit (anti-spam)

Enforced client-side via `scripts/post.py check_rate_limit`. The script reads recent timestamps from `wayd/data/last-check.json` (key: `recent_posts`). If 5+ entries within the last hour, return rate-limited.

If hit, show: "Easy there: you've posted 5 times in the last hour. Try again in N minutes. (This limit prevents accidental spam.)"

This is intentionally trivial to bypass (deleting the file resets it). It exists to catch well-meaning accidents, not determined abusers, GitHub's own systems handle those.

---

## Error handling

Every error gets translated into a human sentence. Never dump stack traces, JSON errors, or raw `gh` output to the user.

| Internal failure | What the user sees |
|---|---|
| `gh` returns non-zero (network) | "Couldn't reach GitHub right now. Check your connection and try again in a moment." |
| `gh` returns 404 (post not found) | "That post isn't there anymore. Maybe the author deleted it." |
| `gh` returns 403 (permissions) | "GitHub says you can't do that. Make sure you're logged in: `gh auth status`." |
| Rate limit on GitHub side | "GitHub is rate-limiting us. Try again in a few minutes." |
| Block list file unreadable | "Couldn't read the block list. Continuing without filtering." (Don't fail the scroll: log to data/error.log) |
| Vibe slug invalid | "I don't recognize that vibe. Pick one of: <list>." |
| Text >1000 chars | "Too long by N chars. Trim it down and try again." |
| Text empty | "An empty post is just silence. Want to write something?" |

---

## Config

`wayd/config.yml` defines:
- The target repo (e.g., `<owner>/wayd`): this is where issues live.
- The list of vibes with their slugs, emojis, and one-liner descriptions.
- The allowed reaction emojis (👍 😂 ❤️ 🎉 🚀 👀 😭).
- The character limit (1000) and rate limit (5/hour).
- The scroll pool size (200) and seen-history size (50).

Load it via `scripts/shared.py` (function `load_config()`). Don't read it directly elsewhere.

---

## Reference files

- `references/settings-allowlist.md`: How to add gh patterns to `.claude/settings.json` Bash allowlist safely.
- `references/post-format.md`: The exact issue title/body/marker format, and how to parse it back.

Read these only when needed; don't load them eagerly.

---

## What WAYD intentionally doesn't do (MVP)

If the user asks for these, politely explain they're not in the MVP and may come in v2:
- Notifications (push or otherwise): pull only via `/wayd inbox`.
- Threaded replies (replies to replies): GitHub issue comments are flat.
- Search / hashtags / mentions across posts.
- Profile pages / following / friending.
- Karma, streaks, trending, hall of fame.
- Reactions on comments (only on posts in MVP).
- Images, video, attachments.

The reason: WAYD is a small, focused experience. Each of these features would multiply complexity without proportionally improving the core loop (post → scroll → react → repeat).
