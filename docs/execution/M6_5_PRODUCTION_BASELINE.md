> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# M6.5 Production Baseline

**Tagged:** 2026-07-08  
**Alembic head:** `0195`  
**Server:** `187.127.180.98` (mesiri-postgres / mesiri)

## Smoke test (passed)

**Message (via signed localhost webhook, sender `917034926395` / `+91 7034926395`):**

> 50 bags of UltraTech cement arrived at site today from ABC Suppliers.

**Path verified:**

| Step | Evidence |
|---|---|
| Webhook POST `/webhook` | HTTP 200 |
| Identity gate (`PostgresActorReader`) | `context.resolved user=4d1f0571-… org=562aa8d5-…` |
| `external_identities` lookup | Digit subject `917034926395` ensured for resolver |
| `ResolvedContext.v2` | Context resolution completed (M4 resolver + bridge) |
| `CanonicalEvent.v2` | Material receipt, actionable (after field-alias normalization) |
| `PlannerDecision.v2` | `START_WORKFLOW` / `material.receipt` |
| Material graph (LangGraph) | Compiled on prod after `langgraph` install |
| `DraftAction.v2` + `WorkflowState.v2` | Persisted in `workflow_instances.state` JSONB |
| `workflow_instances` UUID scope | `organization_id` / `user_id` = canonical control-plane UUIDs |
| Phase | `awaiting_confirmation` |
| Outbound | Confirmation prompt sent via Graph API (not understanding fallback) |

**Workflow instance (prod):**

- `workflow_instance_id`: `8672e5e7-18a0-4dde-bfe2-9964f27c2f6a`
- `organization_id`: `562aa8d5-5376-4c8b-8b11-9cfeb6ceea33`
- `user_id`: `4d1f0571-6eba-4eb1-8968-f0fc837ac324`
- `workflow_key`: `material.receipt`
- `state.version`: `v2`
- `draft_action.version`: `v2`

**Not tested:** replying YES (M7 resume out of scope).

## Production fixes applied during deploy

1. **Alembic revision stamp** — `f7g8h9i0j1k2` → `0060` before upgrade chain
2. **0180 `MIN(uuid)`** — cast via `(MIN(created_by::text))::uuid` (Postgres has no `min(uuid)`)
3. **LangGraph** — not in prod venv; installed via `python -m ensurepip` + `pip install langgraph`
4. **Canonicalization aliases** — map `material`→`material_name`, `event: arrival`→`direction: received`
5. **`workflow_instances` insert** — `CAST(:state AS jsonb)` (asyncpg breaks on `:state::jsonb`)
6. **`external_identities` digit subject** — Meta sends digit-only `wa_id`; backfill stored formatted numbers

## Migration validation still required

Production success does **not** prove fresh `alembic upgrade head` works. Still run:

- Fresh DB → `0190` → backfill → `0195`
- Existing DB @ `0060` snapshot → head (prod path)

See `backend/tests/integration/test_migration_0180_catalog.py`.

## Verify commands

```bash
python scripts/verify_m6_5_prod.py
python scripts/verify_m6_5_smoke_row.py
python scripts/smoke_m6_5_whatsapp_prod.py   # creates another workflow row
```
