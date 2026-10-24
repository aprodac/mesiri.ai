# Deployment Guide

This project uses GitHub Actions for automated CI/CD. Every push to `main` that passes tests is automatically deployed to the VPS. Two frontends are served from the same box on different domains:

> **Since 14 Oct 2026 (INF-11, INF-12):** Mesiri runs on **`82.29.167.128`** (a server
> shared with other apps) under its own domain, DNS in Cloudflare (`mesiri.ai`):
>
> - `api.whatsapp.mesiri.ai` — backend API, WhatsApp webhook (`/webhook`). nginx: [`infra/nginx/api.whatsapp.mesiri.ai.conf`](infra/nginx/api.whatsapp.mesiri.ai.conf).
> - `control.mesiri.ai` — `control-panel` (superadmin; Database page: [docs/backend/database-page.md](docs/backend/database-page.md)), static files from `/var/www/mesiricontrol` (built with `VITE_BASE=/`). nginx: [`infra/nginx/control.mesiri.ai.conf`](infra/nginx/control.mesiri.ai.conf). Set up by the deploy (INF-15, [`infra/deploy/nginx_control_panel.sh`](infra/deploy/nginx_control_panel.sh)): a port-80 block, then — once Cloudflare DNS `A control → 82.29.167.128` (DNS only) reaches the server — a Let's Encrypt certificate, then `api.whatsapp.mesiri.ai/mesiriadmin/...` redirects (301) to `https://control.mesiri.ai/...`. Until then the old address serves the control panel as before.
> - `app.whatsapp.mesiri.ai` — `apps/dashboard`, static files. nginx: [`infra/nginx/app.whatsapp.mesiri.ai.conf`](infra/nginx/app.whatsapp.mesiri.ai.conf).
> - The app listens on `127.0.0.1:8100` (`MESIRI_APP_PORT` in `/opt/mesiri/.env`; 8000 is taken on this server).
> - Postgres 16 and Redis 7 run from [`infra/docker-compose.prod.yml`](infra/docker-compose.prod.yml), bound to `127.0.0.1` only (Postgres on 5434): `docker compose -p mesiri -f infra/docker-compose.prod.yml --env-file .env up -d`.
> - Photos are stored on disk at `/var/lib/mesiri/media` (back it up with the database).
> - Migrations run from `/opt/mesiri` (`alembic -c backend/alembic.ini`) so the real `.env` is read.
> - The old names `mesiri.mercon.tech` / `mesiriweb.mercon.tech` still work: the old server
>   (`187.127.180.98`) forwards them here until Meta's webhook and users have moved. Everything
>   below that mentions those names or that IP describes the old setup.

Previously:

- `mesiri.mercon.tech` — backend API + `control-panel` (internal admin UI, under `/mesiriadmin`). Config: `/etc/nginx/sites-available/mesiri.mercon.tech.conf` (tracked in the repo as `mercon.conf`).
- `mesiriweb.mercon.tech` — `apps/dashboard` (customer-facing web app), static files only, talks to the same backend cross-origin. Config: `/etc/nginx/sites-available/mesiriweb.mercon.tech.conf` (tracked in the repo as `mercon_web.conf`).

(The `mercon.tech` root domain itself is a separate, unrelated app on the same box.)

## How it works

```
git push → main
    ↓
GitHub Actions: deploy.yml
    ├── Unit tests (Python, fakes only)
    ├── Build control-panel (Vite)
    ├── Build dashboard (Vite, VITE_API_URL=https://api.whatsapp.mesiri.ai)
    └── Deploy (only if all above pass)
            ├── Staging gate (infra/deploy/staging_deploy.sh, INF-02/03): this commit on
            │     /opt/mesiri-staging, 127.0.0.1:8101, with a FRESH COPY of prod data
            │     (database mesiri_staging), migrations, start, smoke test. Staging sends
            │     no WhatsApp (Graph API → closed port), automations off. Fail = stop.
            ├── SSH → git reset origin/main, uv pip install
            ├── backup_db.sh pre-migrate (INF-04) → /var/backups/mesiri
            ├── alembic upgrade head (migrations)
            ├── systemctl restart mesiri, health check (rollback on failure)
            ├── mesiri-worker refreshed + checked
            ├── timers refreshed (INF-05/06): mesiri-backup (nightly 02:15 IST, 14 kept),
            │     mesiri-timeline (every minute), mesiri-dpr-render (every 15 min)
            ├── smoke_test.sh (INF-04): build, storage, webhook handshake, worker
            ├── rsync control-panel dist → /var/www/mesiriadmin/ (old address) and
            │     its VITE_BASE=/ build → /var/www/mesiricontrol/ (control.mesiri.ai)
            ├── nginx_control_panel.sh (INF-15): control.mesiri.ai block, cert, redirect
            └── rsync dashboard dist → /var/www/mesiriweb/
```

If staging fails, production is not touched. If the production health check fails after restart, the code is reverted to the previous commit; a schema change is undone from the pre-migrate dump (restore steps at the top of `infra/deploy/backup_db.sh`). A failed smoke test fails the job without rolling back.

**Claude's read-only data access (SA-16):** set the GitHub secret `MESIRI_CLAUDE_OPS_TOKEN` (32+ characters); each deploy writes it to `/opt/mesiri/.env`. Off while unset. See [docs/backend/claude-ops.md](docs/backend/claude-ops.md).

**Ops without SSH (Claude Code, TM-12):** the manual workflow `.github/workflows/claude-ops.yml` runs `vps-check`, `vps-backup-now`, `vps-staging`, `vps-smoke` and the bot test chat with the secrets that stay in GitHub. To see what the assistant decided for recent messages, run `vps-agent-trace` (INF-14: per message, the tool calls with argument names and outcomes, the parked question, held calls and parts still to do; no message text or values).

---

## First-time VPS setup

This only needs to be done once (or when provisioning a new server).

### 1. Bootstrap the VPS

```bash
# Run from your local machine
ssh root@187.127.180.98 'bash -s' < scripts/setup_vps.sh
```

This will:
- Clone the repo to `/opt/mesiri`
- Create a Python venv at `/opt/mesiri/.venv`
- Install Python dependencies
- Install and enable the `mesiri` systemd service
- Create `/var/www/mesiriadmin/` for the frontend

### 2. Create the production `.env`

```bash
ssh root@187.127.180.98
cp /opt/mesiri/.env.example /opt/mesiri/.env
nano /opt/mesiri/.env
```

Fill in:
- `MESIRI_POSTGRES__HOST`, `MESIRI_POSTGRES__PASSWORD`, etc.
- `MESIRI_REDIS__HOST`
- WhatsApp credentials
- AI provider keys (Sarvam, Gemini)
- `MESIRI_ENVIRONMENT=production`

Then start the service:
```bash
systemctl start mesiri
journalctl -u mesiri -f   # watch logs
```

### 3. Create a deploy SSH key pair

```bash
# On your local machine (or on the VPS — either works)
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy -N ""
```

Add the **public key** to the VPS:
```bash
ssh root@187.127.180.98 "echo '$(cat ~/.ssh/github_deploy.pub)' >> ~/.ssh/authorized_keys"
```

### 4. Add GitHub Secrets

Go to: **Repo → Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `VPS_SSH_KEY` | Contents of `~/.ssh/github_deploy` (the private key) |
| `VPS_HOST` | `187.127.180.98` |
| `VPS_USER` | `root` |

### 5. Create a GitHub Environment (optional but recommended)

Go to: **Repo → Settings → Environments → New environment**

Name it `production`. You can add required reviewers or deployment protection rules here so pushes to main require approval before deploying.

---

## Direct VPS access (manual debugging / one-off fixes)

You don't need to wait for CI to inspect or fix things on the box directly — the same deploy key GitHub Actions uses (`VPS_SSH_KEY` secret) works for a normal SSH session if you have a local copy of the private key.

```bash
ssh -i ~/.ssh/<your-copy-of-the-deploy-key> root@187.127.180.98
```

- **Host**: `187.127.180.98` (same as the `VPS_HOST` secret)
- **User**: `root`
- **Key**: the same keypair from [First-time VPS setup](#first-time-vps-setup) step 3 (`~/.ssh/github_deploy` there). If you don't have a local copy, get the private key from wherever the team stores secrets, or generate a new keypair and append its public half to `~/.ssh/authorized_keys` on the VPS (you'll need an existing session to do that once).
- **Gotcha**: if `ssh -i` fails with `Load key "...": invalid format`, the key file has picked up CRLF line endings (common after copy-pasting on Windows) — re-save it with LF-only line endings, or run it through `tr -d '\r'` into a fresh file, before retrying.

Once connected you have full root access — see [Useful commands on the VPS](#useful-commands-on-the-vps) below, and [Directory layout](#directory-layout-on-the-vps) for where things live.

### Adding/editing an nginx site directly

Both `mercon.conf` (mesiri.mercon.tech) and `mercon_web.conf` (mesiriweb.mercon.tech) are tracked in the repo root as a record of what's live, but nginx reads from `/etc/nginx/sites-available/` on the VPS — editing the repo copy does **not** change production by itself. To add or change a site:

```bash
scp -i ~/.ssh/<key> ./mercon_web.conf root@187.127.180.98:/etc/nginx/sites-available/mesiriweb.mercon.tech.conf
ssh -i ~/.ssh/<key> root@187.127.180.98 \
  "ln -sf /etc/nginx/sites-available/mesiriweb.mercon.tech.conf /etc/nginx/sites-enabled/mesiriweb.mercon.tech.conf && nginx -t && systemctl reload nginx"
```

For a new subdomain, also point a DNS A record at `187.127.180.98` first (propagation is usually near-instant), and provision TLS once DNS resolves:

```bash
ssh -i ~/.ssh/<key> root@187.127.180.98 \
  "certbot --nginx -d <subdomain>.mercon.tech --non-interactive --agree-tos -m <your-email> --redirect"
```

Certbot rewrites the nginx config in place to add the `listen 443 ssl` block and the HTTP→HTTPS redirect. After running it, pull the updated config back into the repo so `mercon.conf`/`mercon_web.conf` stays in sync with what's actually live:

```bash
ssh -i ~/.ssh/<key> root@187.127.180.98 "cat /etc/nginx/sites-available/<subdomain>.mercon.tech.conf" > mercon_web.conf
```

### One-off `scripts/*.py` debugging helpers (paramiko, password auth)

`scripts/` has a number of ad hoc scripts (`deploy_*.py`, `check_*.py`, `fix_*.py`, `verify_*.py`, ...) written during past incidents that SSH into the VPS directly via `paramiko` using password auth, bypassing the key-based access above. They used to have the root password hardcoded in the file — that has been removed. They now read three required environment variables instead of embedding a credential in source:

```bash
export MESIRI_VPS_HOST=187.127.180.98
export MESIRI_VPS_USER=root
export MESIRI_VPS_PASSWORD=<current root password>
python scripts/<script_name>.py
```

Never hardcode the password back into one of these files. If you need a new one-off script, read the same three env vars rather than inlining a credential — anyone with read access to the repo (and its full git history) gets root on the box otherwise.

---

## Checking deploy / CI status from the terminal

Use the [GitHub CLI](https://cli.github.com/) (`gh`) instead of switching to the browser — run from the repo root, it infers the repo from the git remote.

```bash
# List recent workflow runs on main (name, status, conclusion, commit, duration)
gh run list --branch main --limit 10

# Watch a run live
gh run watch <run-id>

# Full logs for a specific run
gh run view <run-id> --log

# Only the failed step's logs — the fastest way to diagnose a red run
gh run view <run-id> --log-failed

# Re-run a failed workflow without a new commit (useful for transient
# network blips — e.g. the deploy step failing to reach the VPS)
gh run rerun <run-id>

# Manually trigger a deploy without pushing a commit
gh workflow run "Deploy to Production" --ref main
```

If `Deploy to Production` fails specifically at the **Configure SSH** step (`ssh-keyscan` exits non-zero) while `CI` and `CI (Python runtime)` both pass, that's a connectivity problem between GitHub's runners and the VPS, not a code problem — check `journalctl`/`/var/log/auth.log` on the VPS for whether the connection attempt even arrived (if it didn't, it's a network-level block upstream of the box, e.g. a provider firewall/DDoS filter, not anything `sshd`-side); a `gh run rerun` is often enough if it was transient.

---

## Migrations

Migrations use **Alembic**. The migration chain lives in `backend/migrations/versions/`.

### Create a new migration

```bash
# Auto-generate from SQLAlchemy model changes
make migrate-generate MSG="add_foo_table"

# Or write it by hand in backend/migrations/versions/
```

### Apply migrations locally

```bash
make migrate
```

### Apply migrations in production (done automatically by CD)

```bash
ssh root@187.127.180.98
cd /opt/mesiri/backend
PYTHONPATH=/opt/mesiri/shared/contracts/src:/opt/mesiri/platform/ai/src:/opt/mesiri/backend/src:/opt/mesiri/apps/whatsapp-assistant/src \
  /opt/mesiri/.venv/bin/alembic upgrade head
```

### Roll back one migration

```bash
ssh root@187.127.180.98
cd /opt/mesiri/backend
PYTHONPATH=... /opt/mesiri/.venv/bin/alembic downgrade -1
```

### Safe migrations: expand, then contract

A failed deploy rolls the **code** back to the previous commit, but `alembic
upgrade head` has already changed the **schema**. So the previous code must
keep working against the new schema. Every migration follows one rule:

- **Expand only.** A migration may add tables, add nullable columns (or
  columns with a default), add indexes, and backfill data.
- **Never in the same release as the code that stops using it:** dropping or
  renaming a table or column, making a column `NOT NULL` without a default,
  or changing a column's type. Ship the code that no longer needs the old
  shape first; remove the old shape in a later release (**contract**).

If a change can't follow this, take a backup first (below) and say so in the
commit message, so a rollback plan exists before the deploy starts.

### Backups before migrations

`infra/deploy/backup_db.sh [label]` writes a compressed `pg_dump` of the
production database to `/var/backups/mesiri/` and keeps the newest 14. The
restore steps are in the script's header. Run it by hand before any risky
migration until the deploy pipeline runs it automatically.

### Post-deploy smoke test

`infra/deploy/smoke_test.sh <expected-short-sha>` checks, on the VPS, that
the deployed app actually works, not just that it started: the API answers,
the running build is the commit just deployed, photos go to real storage, the
WhatsApp webhook verification handshake succeeds, and the queue worker is
alive. It reads only, and sends no WhatsApp message.

### Uptime monitor and error alerts (INF-07, INF-08)

**Uptime** — `.github/workflows/uptime.yml` runs `infra/deploy/uptime_check.sh`
from GitHub every 10 minutes: the API (`/health`), the WhatsApp worker
(`/health` → `"worker": "alive" | "down" | "off"`), the dashboard and the
control panel. A check counts as down only after 3 tries, 20 s apart. It posts
to the team WhatsApp group (and `NOTIFY_WEBHOOK_URL`, if set) when Mesiri goes
down, about hourly while it stays down, and when it is back. A run that finds
it down fails, so GitHub's failed-workflow email arrives even if the whole VPS
(and the teammate listener that posts to WhatsApp) is gone. Run it by hand:
Actions → Uptime → Run workflow, or `infra/deploy/uptime_check.sh` anywhere.

**Errors** — the app and the worker send unhandled exceptions and
`logger.error` lines to Sentry when `SENTRY_DSN` is set in `/opt/mesiri/.env`
(off without it). To switch on: create a free Sentry project (platform
Python → FastAPI), copy its DSN into `/opt/mesiri/.env` as `SENTRY_DSN=...`,
then `systemctl restart mesiri mesiri-worker`. Set Sentry's alert rule to
"a new issue is created" → email / Sentry mobile app. Request bodies, local
variables, IPs and phone numbers are kept out (`runtime/error_reporting.py`).

**Errors on WhatsApp (SA-11)** — the same errors, plus the AI provider alert,
go to the super admins on WhatsApp, with or without Sentry
(`runtime/ops_alerts.py`). Who: every platform admin with a WhatsApp number on
their account, plus the numbers in control panel → Settings → *Error alerts on
WhatsApp* (platform setting `ops_alerts`, audited); the same switch turns them
off. The same error goes at most once per 30 minutes. Inside a super admin's
24 h window it is a normal message; outside it, the `mesiri_ops_alert`
template once Meta approves it and it is listed in `WHATSAPP_APPROVED_TEMPLATES`
(text in `docs/ops/whatsapp-templates.md`); when nobody was reached, the team
WhatsApp group. Replies: `alert details`, `mute alerts 2h`, `unmute alerts`.
On wherever real Redis is configured; `MESIRI_OPS_ALERTS=off` in `.env`
switches it off for that server (staging sets it).

---

## Manual emergency deploy

If you need to deploy without waiting for CI:

```bash
# Trigger the workflow manually from the GitHub Actions UI:
# Actions → Deploy to Production → Run workflow → main
```

Or directly on the VPS (backend only — this does not rebuild/redeploy either frontend, see below for that):

```bash
ssh root@187.127.180.98
cd /opt/mesiri
git pull origin main
.venv/bin/uv pip install -e ".[infra,providers,workflow]" --quiet
cd backend && PYTHONPATH=... .venv/bin/alembic upgrade head && cd ..
systemctl restart mesiri
```

To manually deploy a frontend without CI, build it locally and `rsync` the `dist/` folder up:

```bash
# From the repo root, for either app
pnpm --filter @mesiri/dashboard build      # or: pnpm --filter control-panel build
rsync -avz --delete apps/dashboard/dist/ root@187.127.180.98:/var/www/mesiriweb/
ssh root@187.127.180.98 "chown -R www-data:www-data /var/www/mesiriweb/"
```

---

## Useful commands on the VPS

```bash
# Live backend logs
journalctl -u mesiri -f

# Service status
systemctl status mesiri

# Restart backend
systemctl restart mesiri

# Check which commit is deployed
git -C /opt/mesiri log -1 --oneline

# Current migration revision
cd /opt/mesiri/backend && PYTHONPATH=... .venv/bin/alembic current
```

---

## Directory layout on the VPS

```
/opt/mesiri/                  ← git repo (main branch)
├── .venv/                    ← Python virtualenv (not in git)
├── .env                      ← production env vars (not in git)
├── backend/
│   └── migrations/           ← Alembic migrations
├── apps/whatsapp-assistant/
│   └── src/main.py           ← uvicorn entrypoint
└── infra/
    └── mesiri.service        ← systemd unit (installed to /etc/systemd)

/var/www/mesiricontrol/       ← control panel static files for control.mesiri.ai (INF-15)
/var/www/mesiriadmin/         ← control panel built for the old /mesiriadmin address (unused once it redirects)
/var/www/mesiriweb/           ← dashboard static files (served by nginx)
/etc/nginx/sites-available/mesiri.mercon.tech.conf     ← nginx config (from mercon.conf) — mercon.tech's root domain is a separate app on the same VPS
/etc/nginx/sites-available/mesiriweb.mercon.tech.conf  ← nginx config (from mercon_web.conf)
/etc/systemd/system/mesiri.service  ← installed copy of infra/mesiri.service
```
