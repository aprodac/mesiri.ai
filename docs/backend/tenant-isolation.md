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
