# Teammate brain — Claude Code behind the WhatsApp bot (TM-03b)

Approved people tag the bot in a project's team group; the listener (`../listener`) checks who
they are and passes the message here. The brain runs **one ongoing Claude Code session per group**
(Agent SDK) in that project's repo, and the answer is posted back to the team group.

```
@bot … ──► listener (approved?) ──► brain: Claude Code session for that group ──► reply in the team group
```

## Two kinds of turn, enforced in code (`src/brain.js`)

| Turn | When | Claude can |
| --- | --- | --- |
| **Planning** | every message | read code, git history, the inbox and request log; post **previews** (an HTML mockup rendered to an image, or a screenshot of an allowed dev page); record a plan. Nothing in the repo can change. |
| **Working** | only after an approved person replies `@bot ok <plan number>` in the team group | edit and run a fixed list of commands (git, gh pr, npm, python, tests…), following the project's git flow; post progress and screenshots of the result |

`permissionMode: "dontAsk"`: anything not on the list is refused, never asked. Always denied:
force pushes, `--no-verify`, `git config` / `-c` / `remote`, reading `.env` files, printing the
environment, `gh auth/secret/api`, editing `.git/`. A read-only pre-push hook (`hooks/pre-push`)
lets each repo push only to its own branch (Mercon `ilan`, Mesiri `main`). Caps: turns per day,
dollars per turn. Refusals during a working turn are posted as **🔐 Needs your permission**, and
Claude flags anything else that needs the owner (**👀 Please check Claude Code**, a decision, a
credential) with its `needs_attention` tool.

**Hybrid:** when a project has a cloud routine (`TEAMMATE_ROUTINE_<PROJECT>_URL` / `_TOKEN`), an approved
plan isn't worked on here: the brain fires the routine with the plan, and the group gets
"▶️ Working on [n] — watch it live in Claude Code: <session link>". The cloud session (your Teammate
environment, visible in your Claude Code app and on claude.ai) does the work and posts progress back.
Setup: `ROUTINE_PROMPT.md`.

Merging to `main` (production) is never part of the default flow; it happens only when the group
says so. For a hard guarantee, protect `main` on GitHub (required review).

## Group commands

- `@bot <question or request>` — answered by Claude (planning turn); **replying to one of the bot's messages works too, no @ needed**
- **Voice note sent as a reply to the bot** — transcribed (Gemini, ~₹0.10-0.50), echoed as `🗣 Heard: "…"`, then answered like a normal question. Team groups only; never run as a command (approvals need typed `@bot ok <n>`)
- `@bot ok <n>` — approve plan *n* (working turn)
- `@bot new <name>` — start a separate conversation in this group; the others are kept
- `@bot sessions` / `@bot switch <name>` — list / change the current conversation
- `@bot reset` — clear the current conversation
- `@bot upgrade: <what to change in the bot>` (owners) — plans the change in the bot's own repo (`StarShape-in/mesiri.ai`, `teammate/`) in a separate "upgrade" conversation; `@bot ok <n>` from an **owner** starts the **Teammate upgrade — Mesiri bot** cloud routine, which edits `teammate/` only, runs the bot's tests, pushes to `main`, and the push redeploys the bot automatically (`ROUTINE_PROMPT_MESIRI.md`). If an upgrade breaks the bot, fix it from a Claude Code session on the PC.
- `@bot settings` — the project's Claude model and effort; owners change them with `@bot model opus|sonnet|haiku|fable` (or a full `claude-…` id) and `@bot effort low|medium|high|xhigh|max|default`. Applies to the server brain; the cloud routine keeps the model set in the routine.

A reply always continues the conversation that wrote the message you reply to, so several topics can
run side by side in one group.
- `@bot who` / `approve @x` / `remove @x` / `make owner @x` — handled by the listener

## Running it

A systemd service (`../deploy/teammate-brain.service`) as its own user, writing only to
`/var/lib/teammate-brain`, with memory/CPU limits. It needs `CLAUDE_CODE_OAUTH_TOKEN`
(`claude setup-token`), `GH_TOKEN`, and the listener's `TEAMMATE_API_TOKEN`; the listener needs
`TEAMMATE_BRAIN_URL=http://127.0.0.1:8791`. Previews need Chromium in `/opt/pw-browsers`
(`npx playwright-core install --with-deps chromium`).

```bash
cd teammate/brain && npm install && npm test     # fake Claude, no tokens needed
```
