# M6.5 — Canonical Identity Bridge

> **Retired 15 Oct 2026 (BE-01).** The `context_*` copy this describes was removed in migration `0482`; WhatsApp reads the main tables directly. See [docs/backend/identity.md](../backend/identity.md).

**Status:** Deployed to prod — see [M6_5_PRODUCTION_BASELINE.md](M6_5_PRODUCTION_BASELINE.md) (2026-07-08, alembic `0195`, smoke test passed)
**Date:** 2026-07-08
**Last revised:** 2026-07-08 (incorporates contract-versioning, sync-scope, and migration-ordering review)
**Scope:** Establish immutable mappings between the WhatsApp Context Layer (M4 string IDs) and the Control Plane (UUID entities), propagate canonical UUIDs through downstream contracts, and revert migration `0170` before M7 domain persistence.

**Prerequisite milestones:** M4 (Context Foundation), M5 (Planner), M6 (Workflow Runtime — proof path)
**Blocks:** M7 (Interaction / resume), all domain command execution (`material_receipts`, `expenses`, `timeline_entries`, Digital Twin state)

---

## 1. Problem statement

The repository currently operates two parallel identity namespaces:

| Layer | Tables | ID type | Used by |
|---|---|---|---|
| **Control Plane** | `organizations`, `users`, `projects`, `sites` | UUID | Backend API, mobile app, admin, domain persistence |
| **Context Layer (M4)** | `context_organizations`, `context_users`, `context_projects`, `context_sites`, memberships, roles | String (`org_a`, `user_engineer`, …) | WhatsApp assistant: ContextResolver, authorization, preferences |

Contracts and workflow persistence currently propagate **Context Layer string IDs**:

```
ResolvedContext.v1 → CanonicalEvent.v1 → PlannerDecision.v1 → WorkflowState.v1 → DraftAction.v1 → workflow_instances
```

Domain tables (migrations `0070`–`0180`) already require **Control Plane UUID FKs**:

```
material_receipts, material_usage, expenses, equipment_events,
labour_attendance, timeline_entries, finance_accounts, materials_catalog, interactions
```

Without a bridge, M7 domain writes will either fail FK checks or require another workaround (like migration `0170`, which converted `workflow_instances.organization_id/user_id` from UUID to String).

**M6.5 establishes the identity bridge before M7.**

---

## 2. Verified current state (2026-07-08)

### Schema

- **19 tables** on deployed DB (revision `f7g8h9i0j1k2` = semantic `0060`)
- Control plane has data: 5 orgs, 6 users, 15 projects, 0 sites
- Context layer tables exist but are **empty (0 rows)**
- Migrations `0070`–`0180` **not applied** on deployed server
- **No mapping table or bridge columns exist**

### Runtime

- **Identity gate** (`PostgresActorReader`) resolves WhatsApp → `users.whatsapp_number` (UUID plane)
- **ContextResolver** resolves WhatsApp → `external_identities` → `context_users` (string plane)
- No runtime code links the two planes
- Migration `0170` deliberately broke `workflow_instances` UUID FKs to accept M4 string IDs

### Contracts

All five downstream contracts carry scope IDs as plain `str` with **M4 / Context Layer semantics** today:

- `ResolvedContext.v1` — `organization_id = "org_a"`
- `CanonicalEvent.v1`, `PlannerDecision.v1`, `WorkflowState.v1`, `DraftAction.v1` — same

---

## 3. M6.5 goal

> Establish immutable, FK-enforced mappings from Context Layer entities to Control Plane UUIDs; resolve them in `ContextResolver`; propagate **canonical UUID strings** through **new v2 contracts** and `workflow_instances`; retain Context Layer string IDs only inside context resolution and authorization.

### Canonical identity invariant (M6.5+)

**All operational records, workflow instances, timeline entries, and future Digital Twin state must use Control Plane UUIDs for business scope (`organization_id`, `user_id`, `project_id`, `site_id`).**

Context Layer string IDs must not become the primary business identity namespace.

---

## 4. Architectural decisions

### 4.1 Bridge schema: `canonical_*_id` columns on context entity tables

Use explicit 1:1 FK columns — not a polymorphic mapping table.

| Table | New column | FK target | Uniqueness | Phase 1 nullability | ON DELETE |
|---|---|---|---|---|---|
| `context_organizations` | `canonical_organization_id` | `organizations.id` | UNIQUE | NULL allowed | RESTRICT |
| `context_users` | `canonical_user_id` | `users.id` | UNIQUE | NULL allowed | RESTRICT |
| `context_projects` | `canonical_project_id` | `projects.id` | UNIQUE | NULL allowed | RESTRICT |
| `context_sites` | `canonical_site_id` | `sites.id` | UNIQUE | NULL allowed | RESTRICT |

**Indexes:** one B-tree index per `canonical_*_id` column.

**Phase 2 enforcement** (migration `0195`, after backfill): NOT NULL on bridge columns for active context rows; restore `workflow_instances` UUID FKs; enforce uniqueness.

**Why RESTRICT, not CASCADE:** Control plane deletion must go through explicit deactivation (`is_active = false` on projection), not silent cascade into the context/auth graph.

**Why not bridge on `external_identities`:** WhatsApp links to `context_users`. Org/project/site bridges live on those entity tables.

### 4.2 Ownership and synchronization

```
┌─────────────────────────────────────────────────────────┐
│                 CONTROL PLANE (canonical)                  │
│     organizations, users, projects, sites  [UUID writes] │
└──────────────────────────┬──────────────────────────────┘
                           │ one-way derived projection
                           ▼
┌─────────────────────────────────────────────────────────┐
│              CONTEXT LAYER (read-mostly projection)        │
│  context_* + memberships/roles  [string IDs + bridge FK] │
└─────────────────────────────────────────────────────────┘
```

| Event | Owner | Rule |
|---|---|---|
| Control plane entity exists | Control plane | Canonical source of truth |
| Context projection row | Derived | Created/updated by **reconciliation service**, not inline on every API write in M6.5 |
| WhatsApp message arrives | ContextResolver | Read context layer → resolve `canonical_*_id` → emit v2 contracts with UUIDs |
| Context-only row creation | **Forbidden** | No `context_*` row without a `canonical_*_id` FK (enforced after 0195) |
| Delete | Control plane | **Soft-delete only in M6.5** (`status = suspended`, `is_active = false`). Hard delete blocked by RESTRICT FK |

#### M6.5 sync scope (narrow)

**Do not** wire synchronous Context Layer projection into every Control Plane CRUD handler in M6.5. That couples subsystems at the transaction boundary and prevents independent deployment or future database separation.

**M6.5 delivers instead:**

| Mechanism | Purpose |
|---|---|
| `IdentityProjectionService.project_one(entity_type, canonical_id)` | Idempotent upsert of one context row + bridge from a canonical entity |
| `IdentityProjectionService.reconcile_all()` | Full scan: ensure every canonical org/user/project/site has a matching projection |
| `scripts/backfill_identity_bridge.py` | Initial prod/dev population (calls `reconcile_all()`) |

**Future milestone (not M6.5):** trigger projection via `outbox_events` when Control Plane entities change. The outbox table already exists (`0070`).

**Explicitly out of scope for M6.5:** same-transaction dual-write on every org/user/project/site API handler.

### 4.3 Contract strategy: version every contract whose identity semantics change

**Do not silently change v1 semantics.** Versioned contracts exist precisely to prevent `"org_a"` and `"550e8400-…"` from both claiming to be valid `WorkflowState.v1`.

| Contract | v1 semantics (unchanged, frozen) | v2 semantics (M6.5+) |
|---|---|---|
| `ResolvedContext.v1` | All scope IDs are Context Layer strings | **Frozen — do not modify** |
| `ResolvedContext.v2` | — | Dual namespace (see below) |
| `CanonicalEvent.v1` | Context Layer string scope IDs | **Frozen** |
| `CanonicalEvent.v2` | — | Canonical UUID string scope IDs |
| `PlannerDecision.v1` | Context Layer string scope IDs | **Frozen** |
| `PlannerDecision.v2` | — | Canonical UUID string scope IDs |
| `WorkflowState.v1` | Context Layer string scope IDs | **Frozen** |
| `WorkflowState.v2` | — | Canonical UUID string scope IDs |
| `DraftAction.v1` | Context Layer string scope IDs | **Frozen** |
| `DraftAction.v2` | — | Canonical UUID string scope IDs |

**Runtime in M6.5:** produce and consume **v2 only** on the inbound journey. No long-term dual-version runtime support is required because production context/workflow tables are empty today — but v1 contract files and scenario fixtures remain as the historical record of M4 semantics.

**Why not v1.1:** A minor version bump still implies compatible semantics. The identity namespace change is a **breaking semantic change** → major version bump (v2).

#### `ResolvedContext.v2` — dual namespace

| Field | Type | Meaning |
|---|---|---|
| `context_organization_id` | `str` | M4 string — auth/membership lookups only |
| `context_user_id` | `str` | M4 string |
| `context_project_id` | `str \| None` | M4 string |
| `context_site_id` | `str \| None` | M4 string |
| `organization_id` | `str` | **Canonical UUID string** |
| `user_id` | `str` | **Canonical UUID string** |
| `project_id` | `str \| None` | **Canonical UUID string** |
| `site_id` | `str \| None` | **Canonical UUID string** |
| `membership_id`, `role_ids`, `permissions` | unchanged | Stay in context namespace |

**Invariant:** if `organization_id` (canonical) is set, `context_organization_id` must also be set. Resolver fails closed if bridge is missing.

#### Downstream v2 contracts — canonical UUID strings only

`CanonicalEvent.v2`, `PlannerDecision.v2`, `WorkflowState.v2`, `DraftAction.v2`:

- `organization_id`, `user_id`, `project_id`, `site_id` = canonical UUID strings
- No context-layer ID fields
- Pydantic validators (`is_uuid()`) on scope fields recommended

New scenario fixtures go under `scenarios/contracts/*/v2/` (or filename suffix `_v2.json`) — v1 fixtures remain untouched.

---

## 5. ID propagation trace (after M6.5)

```
WhatsApp wa_id
  → external_identities.external_subject
  → context_users.id (string)
  → context_users.canonical_user_id → users.id (UUID)
  → ContextResolver builds ResolvedContext.v2 (dual namespace)
  → build_canonical_event() produces CanonicalEvent.v2 (canonical UUIDs only)
  → Planner.decide() produces PlannerDecision.v2
  → WorkflowRuntime.start() seeds WorkflowState.v2
  → material/nodes.py builds DraftAction.v2
  → PostgresWorkflowInstanceRepository saves UUID org/user (FK-restored in 0195)
  → (future M7+) domain services write material_receipts etc. with same UUIDs
```

`membership_id` and `role_ids` stop at `ResolvedContext.v2` — they do not propagate downstream (unchanged).

---

## 6. Migration plan

### 6.1 New migrations — split responsibilities

| Revision | File | Purpose | Depends on backfill? |
|---|---|---|---|
| `0190` | `0190_identity_add_canonical_bridge.py` | Add **nullable** `canonical_*_id` bridge columns + indexes + FKs (RESTRICT). **Schema only.** | **No** |
| — | `scripts/backfill_identity_bridge.py` | Run `reconcile_all()` — populate context rows + bridges | After 0190 |
| `0195` | `0195_identity_enforce_canonical_bridge.py` | Validate bridges; convert `workflow_instances` org/user to UUID; restore UUID FKs; enforce NOT NULL on bridge columns | **Yes** |

**Critical rule:** `0190` must be correct even if zero context rows exist and zero workflow rows exist. It must **not** convert `workflow_instances` using bridge mappings that do not exist yet.

#### What `0190` does

1. Add nullable `canonical_*_id` columns to `context_organizations`, `context_users`, `context_projects`, `context_sites`
2. Add UNIQUE indexes (PostgreSQL allows multiple NULLs in UNIQUE columns)
3. Add FK constraints with ON DELETE RESTRICT
4. **Does not** alter `workflow_instances`
5. **Does not** enforce NOT NULL

#### What `0195` does (after backfill/reconcile)

1. Pre-check: zero NULL `canonical_*_id` on active context rows (fail migration if violated)
2. `workflow_instances` UUID restoration:
   - If table empty: alter `organization_id`/`user_id` back to UUID, re-add FKs to `organizations`/`users`
   - If rows exist with string M4 IDs: UPDATE via bridge join, then alter + FK
   - If rows exist with UUID strings already: alter + FK only
3. Set NOT NULL on bridge columns (or on active rows only — document choice at implementation time)
4. Fail with clear error if any step cannot complete

### 6.2 Migration `0170` — forward strategy

Migration `0170` converted `workflow_instances.organization_id/user_id` from UUID FK → plain String. **M6.5 undoes this in `0195`, not `0190`.**

`0170` stays in the migration chain (history preserved). Fresh installs: `0170` (string) → `0190` (bridge columns) → backfill → `0195` (UUID restore).

### 6.3 Migrations `0070`–`0180` audit

| Rev | Table(s) | Scope columns | M6.5 action |
|---|---|---|---|
| 0070 | `outbox_events` | none | None (future projection trigger) |
| 0080 | `finance_accounts`, … | UUID FKs | **None** — already canonical |
| 0090 | `material_receipts`, `material_usage` | UUID FKs | **None** |
| 0100 | `expenses` | UUID FKs | **None** |
| 0110 | `equipment_events` | UUID FKs | **None** |
| 0120 | `labour_attendance`, … | UUID FKs | **None** |
| 0130 | `workflow_instances` | UUID (pre-0170) | Fixed by **0195** |
| 0140 | `interactions` | `user_id` UUID FK | **None** |
| 0150 | `timeline_entries` | UUID FKs | **None** |
| 0160 | `idempotency_keys` | none | None |
| 0170 | `workflow_instances` | string org/user | Undone by **0195** |
| 0180 | `materials_catalog` | UUID FKs | **None** |

**Only `workflow_instances` needs a schema fix.** Domain tables need v2 contracts/runtime at write time, not column changes.

### 6.4 Deployed DB revision mismatch — safe strategy

**Do not run `alembic upgrade head` on production without validation.**

#### Correct deploy sequence

```bash
# 1. Verify DB content matches semantic 0060, then stamp
alembic stamp 0060

# 2. Apply domain migrations (if not yet applied)
alembic upgrade 0180

# 3. Schema-only bridge columns (no backfill dependency)
alembic upgrade 0190

# 4. Populate projections + bridges (application script)
python scripts/backfill_identity_bridge.py --dry-run
python scripts/backfill_identity_bridge.py
psql -f scripts/verify_identity_bridge.sql

# 5. Enforce constraints + restore workflow_instances UUID FKs
alembic upgrade 0195
```

#### Revision ID map (old → semantic)

| Old revision ID | Semantic ID | Migration file |
|---|---|---|
| `0001_m1_infra_heartbeat` | `0010` | `0010_infra_heartbeat.py` |
| `c4936d8bcaec` | `0020` | `0020_identity_add_users.py` |
| `d5a47e9cdbfd` | `0030` | `0030_orgs_add_organizations.py` |
| `a1b2c3d4e5f6` | `0040` | `0040_core_add_context_foundation.py` |
| `b2c3d4e5f6a7` | `0050` | `0050_core_add_projects.py` |
| `f7g8h9i0j1k2` | `0060` | `0060_users_add_status_sites_access.py` |
| `1a2b3c4d5e6f` | `0070` | `0070_core_add_outbox_events.py` |
| … | … | … |
| `e5f6a7b8c9d0` | `0180` | `0180_material_add_catalog.py` |
| — | `0190` | `0190_identity_add_canonical_bridge.py` |
| — | `0195` | `0195_identity_enforce_canonical_bridge.py` |

---

## 7. Backfill and projection strategy

### 7.1 Deterministic context ID generation

**Do not use truncated UUID prefixes** (e.g. `ctx_org_{first_8_chars}`) — collision risk and harder reconciliation.

Use **deterministic IDs derived from the full canonical UUID**:

```python
def context_org_id(canonical_uuid: UUID) -> str:
    return f"ctx_org_{canonical_uuid}"   # full UUID string

def context_user_id(canonical_uuid: UUID) -> str:
    return f"ctx_user_{canonical_uuid}"

def context_project_id(canonical_uuid: UUID) -> str:
    return f"ctx_proj_{canonical_uuid}"

def context_site_id(canonical_uuid: UUID) -> str:
    return f"ctx_site_{canonical_uuid}"
```

Properties:
- **Deterministic:** same canonical UUID → same context ID every time
- **Idempotent:** `project_one()` can upsert safely
- **Reversible:** parse canonical UUID from context ID for debugging
- **No collision** across entity types (different prefix)

M4 unit-test seed IDs (`org_a`, `user_engineer`) remain in **fake repositories only**. Integration tests pair deterministic `ctx_*_{uuid}` IDs with control plane rows.

### 7.2 Reconciliation service

`IdentityProjectionService` (`apps/whatsapp-assistant/src/context/identity_projection.py`):

```python
def project_one(self, entity_type: Literal["organization", "user", "project", "site"], canonical_id: UUID) -> None:
    """Idempotent upsert: ensure context row + bridge exist for one canonical entity."""

def reconcile_all(self) -> ReconcileReport:
    """Scan all canonical tables; project any missing or stale context rows."""
```

`scripts/backfill_identity_bridge.py` calls `reconcile_all()`.

Per entity, reconciliation also creates:
- `external_identities` for users with `whatsapp_number`
- baseline `organization_memberships` where needed for resolver to function

### 7.3 Verification queries

```sql
-- No active context rows missing a bridge
SELECT COUNT(*) FROM context_users WHERE canonical_user_id IS NULL;
SELECT COUNT(*) FROM context_organizations WHERE canonical_organization_id IS NULL;

-- No duplicate bridges
SELECT canonical_user_id, COUNT(*) FROM context_users
GROUP BY canonical_user_id HAVING COUNT(*) > 1;

-- WhatsApp path complete
SELECT u.id, u.whatsapp_number, cu.id, cu.canonical_user_id
FROM users u
LEFT JOIN context_users cu ON cu.canonical_user_id = u.id
WHERE u.whatsapp_number IS NOT NULL;

-- Deterministic ID check
SELECT id, canonical_organization_id
FROM context_organizations
WHERE id != 'ctx_org_' || canonical_organization_id::text;
```

---

## 8. Migration validation procedure

| Scenario | Steps | Pass criteria |
|---|---|---|
| **Fresh DB → head** | `docker compose up` → `alembic upgrade 0190` → backfill → `alembic upgrade 0195` | Bridge columns exist after 0190; UUID FKs on `workflow_instances` after 0195 |
| **0190 without backfill** | `alembic upgrade 0190` only | Succeeds on empty context layer; nullable bridge columns present |
| **0195 without backfill** | `alembic upgrade 0195` without reconcile | **Must fail** with clear error (NULL bridges or unmappable workflow rows) |
| **Existing DB @ old 0060 → head** | stamp → upgrade 0180 → 0190 → reconcile → 0195 | Bridges populated; `workflow_instances` UUID FKs restored |
| **Rollback** | `alembic downgrade 0190` | Removes bridge columns; leaves 0170 string state on `workflow_instances` |

---

## 9. Implementation sequencing

| Phase | Work | Est. |
|---|---|---|
| **0 — Design sign-off** | Review this doc; agree v2 contract shapes | 0.5d |
| **1 — Schema (0190)** | Nullable bridge columns only | 0.5d |
| **2 — Projection service** | `project_one()` + `reconcile_all()` (no CRUD hooks) | 1.5d |
| **3 — Backfill script** | `backfill_identity_bridge.py` + verify SQL | 1d |
| **4 — Schema (0195)** | NOT NULL + `workflow_instances` UUID restore | 0.5d |
| **5 — Contracts v2** | All five contracts + scenario fixtures | 2d |
| **6 — Resolver + pipeline** | Bridge lookup; v2 propagation end-to-end | 1.5d |
| **7 — Tests** | See §10 | 2d |
| **8 — Deploy runbook** | stamp → 0180 → 0190 → reconcile → 0195 | 0.5d |

**Total estimate: ~10 dev days**, narrowly scoped.

---

## 10. Tests

| Test | Path | Proves |
|---|---|---|
| Contract v2 validation | `shared/contracts/tests/test_resolved_context_v2.py` | Dual namespace + UUID validators |
| Contract v2 downstream | `shared/contracts/tests/test_*_v2.py` | Canonical UUID scope fields |
| v1 fixtures still valid | existing contract tests | v1 semantics unchanged |
| Bridge schema 0190 | `backend/tests/integration/test_identity_bridge_schema.py` | Nullable columns, no workflow change |
| 0195 requires backfill | `backend/tests/integration/test_identity_bridge_enforce.py` | Fails without bridges |
| `project_one` idempotency | `tests/unit/test_identity_projection.py` | Same UUID → same context ID |
| `reconcile_all` | `tests/integration/test_identity_reconcile.py` | Full scan populates bridges |
| Resolver bridge lookup | `tests/unit/test_identity_bridge_resolver.py` | Missing bridge → error |
| v2 E2E propagation | `tests/integration/test_identity_propagation_e2e.py` | wa_id → ResolvedContext.v2 → … → `workflow_instances` UUID row |

### E2E test assertion sketch

```python
# Given: user with whatsapp_number, reconcile_all() has run
# When: inbound message processed through full journey
# Then:
assert resolved.version == "v2"
assert resolved.organization_id == str(control_plane_org_uuid)
assert resolved.context_organization_id == f"ctx_org_{control_plane_org_uuid}"
assert canonical_event.version == "v2"
assert workflow_state.version == "v2"
assert workflow_row.organization_id == control_plane_org_uuid  # UUID type in DB
```

---

## 11. Files to create

| File | Purpose |
|---|---|
| `backend/migrations/versions/0190_identity_add_canonical_bridge.py` | Nullable bridge columns only |
| `backend/migrations/versions/0195_identity_enforce_canonical_bridge.py` | NOT NULL + workflow_instances UUID FK restore |
| `apps/whatsapp-assistant/src/context/identity_bridge.py` | Bridge lookup helpers |
| `apps/whatsapp-assistant/src/context/identity_projection.py` | `project_one()` + `reconcile_all()` |
| `scripts/backfill_identity_bridge.py` | Calls `reconcile_all()` |
| `scripts/verify_identity_bridge.sql` | FK + null + deterministic ID checks |
| `shared/contracts/src/mesiri_contracts/assistant/resolved_context_v2.py` | v2 contract (or v2 class in same module) |
| `shared/contracts/src/mesiri_contracts/assistant/canonical_event_v2.py` | v2 contract |
| (+ v2 for planner_decision, workflow_state, draft_action) | |
| `scenarios/contracts/*/v2/*.json` | v2 fixtures (v1 fixtures untouched) |
| `tests/integration/test_identity_propagation_e2e.py` | End-to-end proof |

## 12. Files to edit

| File | Change |
|---|---|
| `shared/contracts/src/mesiri_contracts/assistant/__init__.py` | Export v2 types |
| `apps/whatsapp-assistant/src/context/resolver.py` | Bridge lookup; emit `ResolvedContext.v2` |
| `apps/whatsapp-assistant/src/context/models.py` | Add `canonical_*_id` fields |
| `apps/whatsapp-assistant/src/context/postgres_repositories.py` | SELECT bridge columns |
| `apps/whatsapp-assistant/src/canonicalization/builder.py` | Produce `CanonicalEvent.v2` |
| `apps/whatsapp-assistant/src/planner/planner.py` | Produce `PlannerDecision.v2` |
| `apps/whatsapp-assistant/src/workflows/runtime.py` | `WorkflowState.v2` |
| `apps/whatsapp-assistant/src/workflows/material/nodes.py` | `DraftAction.v2` |
| `apps/whatsapp-assistant/src/backend/postgres/workflow_instance.py` | UUID insert for org/user |
| `apps/whatsapp-assistant/src/runtime/inbound_journey.py` | Wire v2 types |

**Do not edit in M6.5:** Control-plane CRUD routers (users, orgs, projects, sites) — no inline projection hooks.

**Do not modify:** v1 contract classes or v1 scenario JSON files.

---

## 13. Explicit out of scope

- M7 interactions / resume / confirmation UX
- Additional workflows beyond material proof path
- Domain command execution (persisting `material_receipts`, etc.)
- Digital Twin state
- Unifying identity gate (`ActorReader`) with ContextResolver into one code path
- **Synchronous projection on every Control Plane CRUD write**
- **Outbox-driven projection** (future; `outbox_events` exists at `0070`)
- Hard deletes / GDPR erasure flows
- Renaming or removing `context_*` tables
- Changing domain table schemas (`0070`–`0180`) beyond `workflow_instances`
- Running production migration without stamp validation
- Modifying v1 contract semantics or fixtures

---

## 14. Risks and design review notes

### Risks

1. **Empty context layer on prod** — resolver fails until `reconcile_all()` runs. Deploy order: 0190 → reconcile → 0195 → enable v2 resolver.

2. **Two WhatsApp lookup paths** — gate uses `users`, context uses `external_identities`. Reconcile must create both links.

3. **v1/v2 coexistence in logs** — during development, old test output may show v1 IDs. v2 makes the break explicit; no silent mixing.

4. **0170 in git history** — fresh installs pass through string-state `workflow_instances` before 0195 fixes it.

### Review feedback incorporated (2026-07-08)

| Feedback | Verdict | Action taken |
|---|---|---|
| Do not change v1 contract semantics silently | **Accepted** | All affected contracts bump to **v2** |
| Do not sync-project inline on every CRUD write | **Accepted** | `project_one()` + `reconcile_all()` only; outbox sync deferred |
| Migration 0190 must not depend on backfill | **Accepted** | 0190 = schema only; 0195 = enforce + workflow UUID restore |
| Use deterministic full-UUID context IDs | **Accepted** | `ctx_org_{full_uuid}` pattern |

### Original assumptions challenged

| Assumption | Actual repo state |
|---|---|
| "Many tables in 0070–0180 need column changes" | **Only `workflow_instances`.** |
| "0170 needs forward migration to UUID" | Correct — undone in **0195**, not 0190. |
| "Bridge both namespaces symmetrically" | **Control plane canonical; context derived.** |
| "Run alembic upgrade head blindly" | **Must stamp first.** |
| "Empty prod tables justify silent v1 change" | **No.** Empty tables reduce migration risk, not contract versioning risk. |

---

## 15. Verification commands (post-implementation)

```bash
# Local fresh install
docker compose up -d
cd backend
alembic upgrade 0190
python scripts/backfill_identity_bridge.py
alembic upgrade 0195
alembic current   # expect 0195

# Run identity tests
pytest shared/contracts/tests/test_*_v2.py -v
pytest tests/integration/test_identity_propagation_e2e.py -v

# Prod deploy sequence
cd /opt/mesiri/backend
alembic stamp 0060
alembic upgrade 0180
alembic upgrade 0190
python scripts/backfill_identity_bridge.py
psql -U mesiri -d mesiri -f scripts/verify_identity_bridge.sql
alembic upgrade 0195
```

---

## 16. Sign-off checklist

Before starting implementation:

- [ ] Agree **v2** (not v1.1) for all contracts whose identity semantics change
- [ ] Agree deploy order: stamp → 0180 → **0190 → reconcile → 0195**
- [ ] Confirm `0195` fails loudly if reconcile was skipped
- [ ] Confirm deterministic context ID format: `ctx_{entity}_{full_uuid}`
- [ ] Confirm no inline CRUD projection hooks in M6.5
- [ ] Confirm prod reconcile pairs all 6 users + 5 orgs + 15 projects
- [ ] Review 0195 `workflow_instances` UUID restore with Alan (M6 owner)

---

*This document is the authoritative plan for M6.5. Update it when implementation begins or architectural decisions change.*
