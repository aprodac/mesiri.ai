# Superadmin audit log (BE-05)

> Built 15 Oct 2026. Tracker: BE-05. Viewer: SA-08 (later). Trial controls that log
> through it: SS-10.

Every change a Mesiri operator makes to a company, its people or the platform leaves one
row in `admin_audit_log`: **who** did it, **what** they did, to **which company**, **when**,
and the **before/after** values.

## Writing an entry

One function, called with the same connection and inside the same transaction as the
change:

```python
from mesiri.application.audit.record import record_admin_action
from mesiri.domains.audit import actions as audit
from mesiri.domains.audit.actions import actor_from_admin

await record_admin_action(
    conn,
    actor=actor_from_admin(_admin),          # the JWT payload from require_platform_admin
    action=audit.COMPANY_TRIAL_EXTENDED,
    organization_id=org_id,
    target_type="organization",
    target_id=org_id,
    summary="Trial extended by 7 days",
    details={"before": {"trial_ends_at": old}, "after": {"trial_ends_at": new}},
)
```

- **Same transaction:** the entry is saved only if the change is. If the entry can't be
  written, the change fails too.
- **Closed list of actions** (`domains/audit/actions.py`): an unknown name raises
  `ValueError`. Add the name there when adding a new kind of admin action. The SS-10
  names (`company.trial_extended`, `company.converted`, `company.suspended`,
  `company.reactivated`, `company.status_changed`, `platform_setting.changed`) already
  exist.
- **No secrets:** `password`, `new_password`, `hashed_password`, `api_key` (and the other
  password fields) are replaced with `"[changed]"` at any depth before storing. IDs and
  dates become JSON strings.

## Who is recorded

| `actor_kind` | When | `actor_user_id` / `actor_label` |
| --- | --- | --- |
| `platform_admin` | any `/admin/...` route | the admin's user id (`sub`) / their `name` claim |
| `self_signup` | `create_company` with `signup_source` `whatsapp` or `web` | the new owner / their phone or email |
| `system` | `create_company` called with no actor otherwise (API, scripts) | none |

## What is recorded today

| Action | Where |
| --- | --- |
| `company.created` | inside `create_company`, so every path (superadmin `/provision`, WhatsApp signup, API) |
| `company.deleted` | `DELETE /admin/organizations/{id}` |
| `company.setting_changed` | `PUT /admin/organizations/{id}/settings` (includes module switches) |
| `company.finance_seeded` | `POST /admin/organizations/{id}/seed-finance` |
| `company_user.created` / `.updated` / `.status_changed` / `.access_changed` / `.deleted` | the `/admin/organizations/{id}/users...` routes |
| `platform_admin.created` / `.updated` | `/admin/platform-users` |
| `ai_config.changed` | `PUT /admin/providers/config` (records which providers got a new key, never the key) |
| `database.query_read` | `POST /admin/database/query`, mode `read` (SA-15; the statement, first 4000 characters); also `POST /claude-ops/sql` (SA-16, actor `system` / "Claude (ops token)") |
| `database.rows_changed` | `POST /admin/database/query`, mode `write` (SA-15; the statement and the rows changed) |

Not recorded, on purpose: reconcile runs, the simulator, review findings, log
acknowledge/retry (operator tools that don't change a company), and a tenant admin's own
dashboard edits (not superadmin actions).

## Reading

`GET /admin/organizations/{org_id}/audit?limit=50&before=<occurred_at>`, platform admins
only, newest first. Page back by passing the last entry's `occurred_at` as `before`. A
platform-wide list (entries with no company, such as platform admin changes) is for SA-08.

## Schema notes (migration 0475)

- `organization_id` and `actor_user_id` have **no foreign keys**. Every other
  organization-scoped table cascades on company delete, but the "company deleted" entry is
  the one that has to outlive the company, and an entry outlives the person who made it.
- Indexes: `(organization_id, occurred_at DESC)` and `(occurred_at DESC)`.
- Append-only by convention (the repository has no update or delete). Retention is
  future work; volumes are small (operator actions only).
