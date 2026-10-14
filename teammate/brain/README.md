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

Merging to `main` (production) is never part of the default flow; it happens only when the group
says so. For a hard guarantee, protect `main` on GitHub (required review).

## Group commands

- `@bot <question or request>` — answered by Claude (planning turn)
- `@bot ok <n>` — approve plan *n* (working turn)
- `@bot reset` — start a fresh conversation for this group
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
