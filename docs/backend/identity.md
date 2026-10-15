# WhatsApp identity: one model (BE-01)

**Since 15 Oct 2026 the main (control-plane) tables are the only source of who a
WhatsApp sender is and what they may reach.** The WhatsApp assistant's private
copy (`context_*` tables, filled by a projection and repaired by a reconcile
watchdog) is gone (migration `0482`).

## How a message is resolved

`context/runtime.py` builds the M4 `ContextResolver` on the ports in
`apps/whatsapp-assistant/src/context/main_table_repositories.py`:

| Question | Read from |
| --- | --- |
| Who sent this? | `users.whatsapp_number`, compared on digits (index `ix_users_whatsapp_digits`). Two users with one number: the active one, then the oldest (BE-04 replaces this with an explicit choice) |
| Is the company usable? | `organizations.status` + `trial_ends_at` (`domains/organizations/lifecycle.is_operational`) |
| Which projects? | Org-wide users (role or `access_policy`, `mesiri.authorization.roles.is_org_wide`): every on-track project; others: their `project_members` rows |
| Which sites? | Sites of their projects, plus `site_members` sites (see BE-34: "explicit sites only" is not enforced yet) |
| Reply / open workflow scope | `inbound_messages`, `workflow_instances` |

Context IDs stay `ctx_user_<uuid>`, `ctx_org_<uuid>`, `ctx_proj_<uuid>`,
`ctx_site_<uuid>` (pure functions in `context/identity_bridge.py`), so Redis
active context and everything downstream are unchanged.

## What this means for writers

Nothing to sync. A user, project, site or membership written by the dashboard,
the control panel or a WhatsApp workflow is visible to the next message. There
are no projection hooks to call.

## History

- Step 0 (`abaa073`, `b3d30f5`): main tables read beside the copy, differences
  logged to `identity_shadow_mismatches`.
- Step 1 (`e2221dc`): main tables answer by default.
- Step 3 (this change): copy, projection hooks, reconcile watchdog, shadow
  comparison, Sync Health page and their tables removed. Roles, permissions and
  per-user defaults in the copy never had a writer, so there was no data to move
  (step 2).
