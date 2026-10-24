# Claude's read-only control-plane API (SA-16)

So Claude Code can investigate with live data ("why didn't Acme's DPR go out?", "what did the bot
do with that message?", "what's failing?") instead of guessing from code or waiting for someone to
open the control panel.

## Pieces

| Piece | Where |
|---|---|
| API `/claude-ops/whoami`, `/companies`, `/tables`, `/tables/{t}`, `POST /sql` | `backend/src/mesiri/domains/admin/claude_ops_router.py`, mounted by both apps |
| CLI (stdlib only) with built-in queries: `messages`, `traces`, `failures`, `reports` | `scripts/control_plane.py` |
| Skill telling Claude when and how to use it | `.claude/skills/control-plane/SKILL.md` |
| Token into the server's `.env` on deploy | `.github/workflows/deploy.yml` step "Claude ops token", `infra/deploy/set_env_value.py` |
| Tests | `backend/tests/unit/test_claude_ops_router.py`, `backend/tests/integration/test_claude_ops_postgres.py` |

SQL goes through the Database page's console (SA-15, `database_console.py`) in `read` mode, so
there is one set of rules: one statement, SELECT/WITH/EXPLAIN/SHOW/TABLE/VALUES, 15 s, 500 rows.

## Safeguards

- **Off by default.** No `MESIRI_CLAUDE_OPS_TOKEN` on the server (or one under 32 characters):
  every `/claude-ops/` path answers 404.
- **Dedicated token**, not a superadmin login: `Authorization: Bearer <token>`, compared in
  constant time. Revoke by changing or deleting it (GitHub secret + deploy, or `.env` + restart).
- **Read-only by Postgres**: every request's transaction is `READ ONLY`; writes fail even when
  hidden in a `WITH`. Changes go through the control panel's Database page.
- **Secrets hidden**: SQL naming `ai_provider_secrets`, `login_codes`, `hashed_password`,
  `code_hash` or `api_key` is refused; results hide those columns and any bcrypt / argon2 /
  pbkdf2 hash wherever it appears (a row cast to text, JSON). This guards against accidental
  exposure, **not against a token holder set on getting round it** (e.g. building a table name
  from pieces). Fully airtight needs a separate Postgres role with column grants — future work,
  needs a role the migration user may not be allowed to create.
- **Audited**: every SQL read is a `database.query_read` entry, actor `system` / "Claude (ops
  token)", with the statement. Browsing (`/companies`, `/tables`) is not recorded.
- No masking of names or message text in SQL results (the team's own debugging data); the
  built-in queries cut phone numbers to their last 4 digits. The skill tells Claude to keep
  customer data out of commits, tracker notes and team updates.

## Turning it on (ops)

1. Make a token: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. GitHub → repo Settings → Secrets and variables → Actions → New repository secret
   `MESIRI_CLAUDE_OPS_TOKEN` = the token. The next deploy writes it to `/opt/mesiri/.env`
   (on stdin, never logged) and the restart loads it.
3. claude.ai → Claude Code environment settings → environment variables / secrets:
   `MESIRI_CLAUDE_OPS_TOKEN` = the same token.
4. In a session: `python3 scripts/control_plane.py whoami`.

To turn it off: delete the line from `/opt/mesiri/.env` and restart (removing the GitHub secret
alone leaves the `.env` as it is), or set a new token to revoke the old one.

## Later

- A claude.ai MCP connector on the same endpoints (works outside coding sessions; needs OAuth).
- Actions (extend a trial, toggle a module) behind confirmation, each audited.
