# Tenant isolation in the database (BE-03)

**Goal:** a request for one company can't read or write another company's
rows, even through a query that forgets `WHERE organization_id`.

## How it works

1. **The company is bound per request or message** (`backend/src/mesiri/infrastructure/postgres/tenant.py`):
   - dashboard API: `get_auth_context` (domains/projects/router.py), on the request's own transaction too
   - WhatsApp: the message journey, once the sender is resolved (`runtime/message_journey.py`)
   - the WhatsApp app's projects and users routers (their engine is a `TenantScopedEngine`)

   `TenantResetMiddleware` clears it at the start of every HTTP request.
2. **Every transaction carries it:** `PostgresDatabase.transaction()` and
   `TenantScopedEngine` run `set_config('mesiri.organization_id', <id>, true)`.
   Transaction-local, so a pooled connection never carries it further.
3. **Policies** (migration `0484`): every table with `organization_id`, plus
   `organizations`, has a `tenant_isolation` policy:
   - company set: only that company's rows are visible, and writes can't put
     a row into another company;
   - nothing set: unchanged. System work (automation runner, webhook sender
     lookup, login, signup, control panel, workers, migrations) binds nothing.
   - `admin_audit_log`, `inbound_messages`, `provider_executions`, `users`:
     rows with no company are hidden from a company but can still be written.
4. **Checks that must see every company** use `unscoped(conn)` for that one
   query: "number already registered" (BE-04), the WhatsApp add-user username
   check, contact sharing's other-company check, the dashboard email check.

## When it applies

Only to a login that is neither superuser nor table owner. Production's app
login is the Docker image's superuser until BE-03 step 3 switches the app and
worker to `mesiri_app`; migrations keep the owner login.

## Switching production to `mesiri_app` (step 3, run once by Ilan)

On the VPS, as root, after the deploy that brings migration `0484`:

```bash
bash /opt/mesiri/infra/deploy/app_db_login.sh check    # read-only
bash /opt/mesiri/infra/deploy/app_db_login.sh switch
```

`switch`:
1. creates `mesiri_app` (login; not superuser; no BYPASSRLS; read/write on
   tables, sequences and functions, including ones later migrations create)
   with a random password, and checks it connects and is not exempt;
2. copies `.env` to `.env.before-be03-<time>`, then sets
   `MESIRI_POSTGRES__USER/PASSWORD` to `mesiri_app` and keeps the old login as
   `MESIRI_MIGRATION_POSTGRES__USER/PASSWORD` (deploy.yml runs migrations with
   it);
3. restarts `mesiri` and `mesiri-worker`, waits for `/health`, and restores
   the previous `.env` by itself if it fails.

Then: one WhatsApp test message and the dashboard Today page.

**Rollback:** `bash /opt/mesiri/infra/deploy/app_db_login.sh rollback`
(restores the latest `.env` backup and restarts; `mesiri_app` stays, unused).

If Postgres runs from `infra/docker-compose.prod.yml`: that file reads
`MESIRI_POSTGRES__USER/PASSWORD` for the container's own user, which only
matters when a new, empty volume is initialised. With an existing volume the
switch changes nothing there.

Never prints a password. Rehearsed locally on 16 Oct against Postgres 16 with
password authentication: check, switch, app click-through as `mesiri_app`,
an automation-runner tick, migrations through deploy's migration login,
a new table usable by the app, rollback, re-switch, and the automatic
rollback when `/health` fails.

## Writing new code

- A new table with `organization_id` needs the policy in its migration;
  `test_every_company_table_has_the_policy` fails otherwise.
- New request code gets the company automatically through `get_auth_context`
  or `PostgresDatabase.transaction()`. A query that must look across
  companies inside a request uses `unscoped(conn)`, with a comment saying why.

## Not covered yet

- Child tables without `organization_id` (attendance lines, report versions,
  photos, project members...) are only reachable through their parents.
- "Nothing set" still means "everything visible"; making it "nothing" needs
  system jobs on their own login that bypasses RLS (a later item).
- Engines opened outside `PostgresDatabase`/`TenantScopedEngine` (control
  panel, loggers, sender lookup) are unscoped by design.
