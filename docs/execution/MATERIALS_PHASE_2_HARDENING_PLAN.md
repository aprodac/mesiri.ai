> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# Materials Module — Phase 2: Production Hardening & Stability

**Status:** PLAN — awaiting approval. No code to be written until approved.
**Author:** Claude (Opus 5), 2026-07-30.
**Scope basis:** "Materials Module – Project Context & Development Rules (Cloud Migration)".
**Predecessor:** Phase 1 (Purchase History / Purchase Details / KPI cards / search / filter / sort / responsive / empty state) — landed, currently uncommitted in the working tree.
**Related:** [MATERIALS_CATALOGUE_PLAN.md](MATERIALS_CATALOGUE_PLAN.md) (V1 catalogue + units + ledger — done).

---

## 1. Objective

Make the Materials Module safe to run a real construction company on, without adding
a single new business feature.

Concretely, close four classes of production risk that the current code carries:

1. **Silent stock corruption** from duplicate reversals and duplicate submissions — both
   permanent, because the ledger is append-only and nothing is ever edited or deleted.
2. **Catalogue fragmentation** from case/whitespace-variant material names, which splits
   one real material's stock across two catalogue rows.
3. **Unbounded queries** — inventory has no pagination and no server-side search at all.
4. **No stock safety net** on the dashboard — a storekeeper can issue 500 bags from a site
   holding 20 and get no warning whatsoever.

Plus the explicitly requested **concurrency & race-condition audit** (§ 12.4 / § 14.3).

Everything below reuses existing tables, existing APIs, and existing components. Three new
narrow endpoints/columns are proposed; each is justified individually in § 7 and § 8.

---

## 2. Existing Architecture Analysis

### 2.1 The write path

```
Dashboard / Mobile ──► POST /materials/inflows  ──┐
                       POST /materials/outflows ──┤
                                                  ├─► domains/materials/router.py
WhatsApp ─► workflows/material ─► application/    │      │
            materials/handlers.py ────────────────┘      │
                                                          ▼
                              INSERT material_receipts | material_usage   (operational record)
                                                    +
                              post_material_movement() ─► INSERT material_movements  (stock truth)
                                                    +
                              INSERT outbox_events                        (timeline)
                              ── all on ONE connection, ONE transaction ──
```

- `domains/materials/posting.py::post_material_movement` is the single canonical writer to
  the ledger. Both write paths call it on the connection they already hold, so the
  operational row and the ledger row are atomic by construction. **This design is sound and
  is not being changed.**
- `infrastructure/postgres/dependency.py::get_db_conn` yields a connection inside
  `PostgresDatabase.transaction()` → `engine.begin()`. **Every REST request is therefore one
  transaction, committed on success, rolled back on any exception.** Isolation level is the
  PostgreSQL default: **READ COMMITTED**.
- The CQRS/WhatsApp path opens its own transaction in
  `application/materials/handlers.py` and **has idempotency** via
  `MaterialExecutionRepository.check_idempotency(conn, cmd.idempotency_key)`.
  **The REST path has none.** Migration `0310`'s own docstring records this as a known gap.

### 2.2 The read path

- Stock is **never stored**. `PostgresMaterialReadRepository.get_stock_levels` computes it as
  `SUM(CASE WHEN movement_type='RECEIPT' THEN qty ELSE -qty END)` grouped by
  `(org, project, site, material, unit)`. There is no counter column anywhere.
  This is the single most important fact for the concurrency audit (§ 12.4).
- `get_ledger` reads `material_movements` and LEFT JOINs the two operational tables for
  audit metadata, computing a running balance with a window function over a CTE.

### 2.3 Constraints and indexes actually present

| Object | Defined in | Covers |
|---|---|---|
| `uq_materials_catalog_org_name (organization_id, name)` | `0180` | Exact-case duplicates only |
| `uq_material_movements_source (source_type, source_id, movement_type)` | `0310` | Re-posting a movement for an *already-created* receipt row |
| `ix_material_movements_org_project_site_material` | `0300` | The inventory GROUP BY |
| `ix_material_movements_source`, `ix_material_movements_material_id` | `0300` | Ledger/source lookups |
| `ix_material_receipts_material_id` / `..._unit_id`, same for usage | `0180`/`0290` | Per-material filters |
| `NOT NULL` on `material_id`, `unit_id`, `default_unit_id` | `0310` | No free-text rows possible |

**Not present:** any index supporting the inflow/outflow list's actual access pattern
(`organization_id` + `project_id` + `occurred_date` range, ordered by `occurred_date DESC,
created_at DESC`).

### 2.4 Confirmed defects (each verified by reading the code, not inferred)

| # | Defect | Evidence | Impact |
|---|---|---|---|
| **D1** | **Duplicate reversal is possible and permanent.** `reverse_inflow`/`reverse_outflow` never check whether the original was already reversed. Each call mints a fresh `row_id = uuid.uuid4()` used as `source_id`, so `uq_material_movements_source` can never fire — it guards a different thing. | `router.py:701-774`, `router.py:777-846` | Reverse twice → stock is wrong by 2× the original quantity, forever. Requires a *third* manual adjustment to fix, which itself can be double-applied. |
| **D2** | **No REST idempotency.** Server generates the row id; a double-click, a retry, or a mobile network hiccup creates two independent, equally valid movements. | `router.py:549`, `router.py:634`; contrast `handlers.py` | Phantom stock. Indistinguishable from two genuine deliveries — nobody can tell which to reverse. |
| **D3** | **Case-variant catalogue duplicates.** The unique constraint and `get_by_name` are both exact-match. `"Cement"`, `"cement"`, `"Cement "` all insert cleanly. | `0180:66-71`, `materials.py:534-541` | One material's stock splits across two rows. Worse: WhatsApp's `find_by_name_exact_active` *is* `lower()`-based and takes `.first()` — so with duplicates present it resolves to an **arbitrary** one of them. |
| **D4** | **Inventory is unbounded.** `GET /materials/inventory` takes no `limit`/`offset`/`search` and returns every row. The UI renders all of them and computes KPIs client-side from `rows.length`. | `router.py:406-425`, `inventory-view.tsx:47-99` | Full aggregate scan + unbounded JSON + unbounded DOM. Degrades continuously with data volume; no cliff, just a company that gets slower every month. |
| **D5** | **No stock check on outflow.** REST accepts any quantity. `NEGATIVE_STOCK` is a *display state*, meaning the system is designed to record the mistake rather than prevent it. WhatsApp warns (`_low_stock_warning`); the dashboard does not. | `router.py:608-690`, `nodes.py:55-69` | Typo "500" instead of "50" is accepted silently and needs an elevated-role correction. |
| **D6** | **Date filters exist in the API but the UI never sends them.** `date_from`/`date_to` are fully implemented server-side and indexed-adjacent. | `router.py:295-296`, `materials.py:148-151`; absent from `inflows-view.tsx`/`outflows-view.tsx` | Users scroll instead of filtering. Pure frontend work — zero backend cost. |

---

## 3. Components to Reuse

**Reused as-is, no modification:**

- `domains/materials/posting.py` — canonical ledger writer. All new paths call it.
- `PostgresMaterialReadRepository`, `PostgresMaterialCatalogRepository`,
  `MaterialMovementsRepository`, `UnitsOfMeasureRepository`.
- `_resolve_and_validate_material_unit`, `_authorize_write`, `_resolve_project_ids`,
  `_site_filter_denied`, `_assert_site_in_project` — all existing authorization helpers.
- `domains/materials/validation.py` reason/role rules.
- `idempotency_keys` table + the claim pattern already used by the CQRS path.
- Dashboard: `Table`, `Card`, `Badge`, `Input`, `Select`, `Skeleton`, `KpiCard`,
  `BulkActionBar`, `Dialog`, `Sheet` — **read-only reuse from `components/ui/`**.
- `lib/materials.ts` typed API boundary — extended, never forked.
- TanStack Query key convention `['materials', ...]` and the
  `invalidateQueries({ queryKey: ['materials'] })` prefix-invalidation already used by
  `correction-dialog.tsx`.
- `err.response?.data?.detail || '<friendly fallback>'` error-surfacing pattern.

**Explicitly NOT built:** no new stock table, no cached balance column, no new
transaction/unit-of-work abstraction, no service layer, no new state manager.

---

## 4. Files to Modify

### Backend
| File | Change |
|---|---|
| `backend/src/mesiri/domains/materials/router.py` | Idempotency-Key handling on 2 POSTs; already-reversed pre-check on 2 reverse endpoints; `limit`/`offset`/`search`/`stock_state` on `GET /inventory`; optional stock guard on outflow; case-insensitive conflict on create/update material |
| `backend/src/mesiri/infrastructure/postgres/repositories/materials.py` | `get_stock_levels` gains pagination + search + a companion summary query; `get_available_stock()`; `is_already_reversed()`; `get_by_name` → case-insensitive |
| `backend/src/mesiri/domains/materials/responses.py` | `MaterialStockListResponse` (items + total + summary); `already_reversed` flag on receipt/usage responses |
| `backend/src/mesiri/domains/materials/validation.py` | Pure helper for the stock-guard decision |

### Dashboard
| File | Change |
|---|---|
| `apps/dashboard/src/lib/materials.ts` | Idempotency key generation; `fetchInventory` paginated signature; `fetchAvailableStock`; date-filter params |
| `components/materials/inventory-view.tsx` | Server-side pagination, search box, server-provided KPI summary |
| `components/materials/inflows-view.tsx` | Date-range filter wired to existing `date_from`/`date_to` |
| `components/materials/outflows-view.tsx` | Same |
| `components/materials/record-inflow-dialog.tsx` | Idempotency key per submit; submit-button lockout |
| `components/materials/record-outflow-dialog.tsx` | Same + available-stock display + over-stock confirmation step |
| `components/materials/correction-dialog.tsx` | Handle 409 already-reversed with a clear message |
| `components/materials/movement-details-sheet.tsx` | Hide/disable "Correct" when `already_reversed` |
| `components/materials/purchase-history-view.tsx` | Adopt the shared date-range filter (Phase 1 file) |

**Not touched:** `components/ui/*` (shared with Labour — see § 15), `lib/api.ts`,
`catalogue-view.tsx` business logic, any mobile file, any WhatsApp file.

---

## 5. New Files

| File | Why it must be new |
|---|---|
| `backend/migrations/versions/<NNNN>_materials_phase2_integrity.py` | Case-insensitive catalogue unique index + dedupe; partial unique index preventing duplicate reversals; two composite performance indexes. **Number assigned at implementation time against the then-current head — see § 15.1.** |
| `apps/dashboard/src/components/materials/date-range-filter.tsx` | Shared by 3 materials views. Lives under `materials/`, **not** `ui/`, so Labour can never be affected. |
| `apps/dashboard/src/components/materials/table-pagination.tsx` | Same reasoning. |
| `backend/tests/unit/test_material_idempotency.py` | New behaviour |
| `backend/tests/unit/test_material_reversal_guard.py` | New behaviour |
| `backend/tests/integration/test_material_concurrency.py` | Race-condition proof (§ 16.4) |

---

## 6. Backend Plan

### 6.1 D1 — Prevent duplicate reversals *(highest priority)*

Two layers, because the application check alone is a check-then-act race (§ 12.4):

1. **Database (authoritative):** partial unique index
   `UNIQUE (reverses_movement_id) WHERE reverses_movement_id IS NOT NULL`
   on `material_receipts` and on `material_usage`. One original ⇒ at most one reversal.
   Enforced even against direct SQL or a future third write path.
2. **Application (for the good error):** `is_already_reversed(original_id)` before insert →
   `HTTPException(409, "This movement has already been corrected on <date> by <user>.")`.
   The IntegrityError from layer 1 is caught and mapped to the same 409, so a lost race
   still produces the right message rather than a 500.

Pre-flight: the migration must detect **pre-existing** duplicate reversals before creating
the index. It will `RAISE EXCEPTION` with the offending ids rather than silently deleting
ledger rows — deleting from an append-only ledger is never acceptable, and a human must
decide the correction. (Verify against production data before the deploy window.)

### 6.2 D2 — REST idempotency

- Optional `Idempotency-Key` header on `POST /materials/inflows` and `/outflows`.
- Reuse the existing `idempotency_keys` claim pattern (`INSERT ... ON CONFLICT DO NOTHING`)
  **inside the request's existing transaction** — no new abstraction.
- Claimed key ⇒ return the original `{id, status}` with `status: "replayed"` and HTTP 200
  instead of 201. Non-breaking: absent header ⇒ exact current behaviour.
- Dashboard generates a UUID **when the dialog opens**, not per click — so N clicks share
  one key. Regenerated only after a successful submit or an explicit reset.

*Justification for not doing this purely client-side:* debounce prevents double-click, not
retry-after-timeout, which is the case that actually produces phantom deliveries on site
wifi.

### 6.3 D3 — Case-insensitive material names

- Migration: report-then-merge. Detect `lower(btrim(name))` collisions per org; for each
  group keep the row with movement history (or the oldest), repoint `material_id` on
  `material_receipts`/`material_usage`/`material_movements` to the survivor, delete the
  now-unreferenced duplicates. If two colliding rows **both** have movements in *different*
  units, abort with the ids listed — that needs a human decision, not a guess.
- Then `CREATE UNIQUE INDEX ON materials_catalog (organization_id, lower(btrim(name)))`.
- `get_by_name` becomes case/whitespace-insensitive so `create_material`'s existing 409
  fires correctly; `update` gains the same check.

### 6.4 D4 — Inventory pagination, search, and server-side summary

- `get_stock_levels` gains `search`, `stock_state`, `limit`, `offset`, returns
  `(items, total, summary)`.
- **The summary must be computed server-side over the full filtered set.** Returning only
  a page while the UI keeps computing KPIs from `rows.length` would silently turn
  "Negative Stock: 7" into "Negative Stock: 2". This is the single largest regression risk
  in Phase 2 and is called out in § 14.1.
- Response becomes `{items, total, summary}` — a **breaking shape change** for
  `GET /materials/inventory`, currently a bare array. Consumers: dashboard
  `inventory-view.tsx` and mobile `materialsService.ts`. See § 14.2 for the compatibility
  decision required.
- New composite indexes:
  `material_receipts (organization_id, project_id, occurred_date DESC)` and the same on
  `material_usage`, matching the list queries' real filter+sort shape.

### 6.5 D5 — Over-stock guard

- New `GET /materials/stock-check?site_id=&material_id=` → `{available, unit}`.
  Reuses `get_stock_levels` with a `material_id` filter; no new query logic.
- `POST /materials/outflows` gains optional `allow_negative: bool = false`.
  If the resulting balance would go below zero and `allow_negative` is false →
  `409 {detail, available, requested, unit}`.
- Default `false` is a **deliberate behaviour change**: today the API silently accepts
  over-issue. WhatsApp and mobile do not send the flag, so they would begin receiving 409s.
  **This requires an explicit decision — see § 14.2.**
- Concurrency-correct via `pg_advisory_xact_lock` — see § 12.4.

### 6.6 D6 — Date filters

Backend: **no change required.** Already implemented and already authorization-scoped.

---

## 7. API Plan

| Endpoint | Change | Breaking? | Justification |
|---|---|---|---|
| `POST /materials/inflows` | Optional `Idempotency-Key` header | No | D2 |
| `POST /materials/outflows` | Optional `Idempotency-Key` header; optional `allow_negative` body field | **Behaviour change** (409 on over-issue) | D2, D5 |
| `POST /materials/inflows/{id}/reverse` | 409 if already reversed | **Behaviour change** (was: silent double-reverse) | D1 |
| `POST /materials/outflows/{id}/reverse` | Same | Same | D1 |
| `GET /materials/inventory` | `search`, `stock_state`, `limit`, `offset`; returns `{items,total,summary}` | **Yes — response shape** | D4 |
| `GET /materials/inflows` , `/outflows` | *No change* | No | Date filters already exist |
| `GET /materials/stock-check` | **New** | No | D5. Justified: no existing endpoint returns a single material's balance without fetching the whole inventory list — using `/inventory?material_id=` from a dialog would work but returns the full row shape for every site. This is one scalar the outflow dialog needs on every material selection. |

No other new endpoints. No endpoint is duplicated or forked.

---

## 8. Database Plan

**One migration**, number assigned at implementation time (§ 15.1).

| Step | Operation | Reversible |
|---|---|---|
| 1 | Detect + abort on pre-existing duplicate reversals (report ids, change nothing) | n/a |
| 2 | Detect + merge case-variant catalogue duplicates; abort on ambiguous unit conflicts | Data merge — **not** cleanly reversible; requires pre-deploy backup |
| 3 | `CREATE UNIQUE INDEX ... ON materials_catalog (organization_id, lower(btrim(name)))` | Yes |
| 4 | Partial unique index on `material_receipts.reverses_movement_id` | Yes |
| 5 | Partial unique index on `material_usage.reverses_movement_id` | Yes |
| 6 | `material_receipts (organization_id, project_id, occurred_date DESC)` | Yes |
| 7 | `material_usage (organization_id, project_id, occurred_date DESC)` | Yes |

- **No new tables.** **No new columns.** **No column type changes.**
- **No changes to `material_movements`** — the ledger stays exactly as `0300`/`0310` left it.
- Steps 3–7 use `CREATE INDEX CONCURRENTLY` if the deploy is against a live database
  (requires running outside a transaction — flagged for the deploy runbook).
- Step 2 is the only destructive step. It must be dry-run against a production snapshot and
  the report reviewed **by a human** before the real run.

---

## 9. UI & User Flow

### 9.1 Inventory (server-paginated)
```
[ Search materials… ]  [ Stock state ▾ ]              Showing 1–50 of 1,284

┌ KPI: Tracked 1,284 │ Available 1,190 │ Out 87 │ Negative 7 ┐   ← from server summary
└──────────────────── (whole filtered set, not this page) ───┘

│ Material │ Available │ Site │ Total In │ Total Out │ Last Movement │ State │
   … 50 rows …
                                    [ ‹ Prev ]  Page 1 of 26  [ Next › ]
```
Search debounced 300 ms. Page resets to 1 on any filter change. Existing row-click →
ledger sheet and the bulk-deactivate bar are unchanged.

### 9.2 Over-stock confirmation (outflow dialog)
```
Material: Cement (OPC)            Available at this site: 20 bags
Quantity: [ 500 ] bags

  ⚠ You are recording 500 bags but only 20 bags are in stock.
     This will leave the site at −480 bags.
     Corrections require a Project Manager and cannot be undone by editing.

     [ Cancel ]   [ Yes, record anyway ]
```
The warning is **inline, not a browser `confirm()`** — matches the existing dialog idiom.
Available stock loads when a material is chosen and shows "—" (never blocks) if it fails.

### 9.3 Date range (inflows / outflows / purchases)
```
[ Search ] [ Reason ▾ ] [ From: dd/mm/yyyy ] [ To: dd/mm/yyyy ] [ Clear ]
```
Sends the existing `date_from`/`date_to`. Presets: This Month · Last 30 Days · This Year.

### 9.4 Already-corrected movement
The "Correct" button is **hidden**, replaced by
`✓ Corrected on 12 Jul 2026` — showing a disabled button the user can't use is worse than
showing the fact. (Cross-reference: the Labour delete-button visibility fix, `8a7f615`.)

---

## 10. User Experience Considerations

- **Prefer prevention over correction.** Every correction in this module is permanent and
  role-gated; a warning at entry costs one click, a correction costs a Project Manager.
- **Never block on a warning the user might legitimately override.** Genuine negative stock
  happens (unrecorded historical deliveries). The over-stock guard is a *confirmation*, not
  a prohibition.
- **Error messages must say what to do, not what failed.**
  Current: `"unit_id does not match Cement's Stock Unit (expected bags)"` →
  Proposed: `"Cement is tracked in bags. Change the unit to bags to record this."`
- **Never lose typed input.** A 409 must leave the dialog open with values intact.
- **Site staff are on phones with poor connectivity.** Idempotency is a UX feature here, not
  just a correctness one.
- Search debounced; pagination state does not survive a scope change (correct — different
  data set).

---

## 11. Edge Cases

| # | Case | Handling |
|---|---|---|
| E1 | Duplicate reversals already in production data | Migration aborts with ids listed; human decides |
| E2 | Case-variant duplicates where both rows have movements in **different** units | Migration aborts — cannot merge without inventing a conversion |
| E3 | Same `Idempotency-Key` replayed with a **different body** | Return the original result. Do **not** 422 — a retried request with a mutated body is a client bug we cannot safely resolve, and replaying is the non-destructive choice |
| E4 | `Idempotency-Key` absent | Exact current behaviour (backward compatible) |
| E5 | Outflow where available stock is already negative | Guard still fires; the message states the current negative balance |
| E6 | Stock-check request fails / times out | Dialog shows "—" and permits submission; the server-side guard is the real gate |
| E7 | Material with no movements at all | `available = 0`; guard fires on any outflow. Correct — you cannot issue what was never received |
| E8 | Two users reverse the same movement simultaneously | One 409s (§ 12.4) |
| E9 | Two users issue against the same low stock simultaneously | Advisory lock serializes; the second sees the post-first balance (§ 12.4) |
| E10 | `date_from > date_to` | Client-side validation; server returns an empty set harmlessly |
| E11 | Page 26 requested after a filter change shrinks results to 1 page | Clamp to last valid page, do not show an empty table |
| E12 | Inventory search matches zero rows | Distinct empty state ("No materials match…" + Clear) — not the "no inventory yet" onboarding message |
| E13 | Portfolio scope, org with 50k site×material rows | Paginated; the summary is one aggregate query over an indexed group-by |
| E14 | Reversal of a movement whose material was later deactivated | Must still work — history must remain correctable. Verify the reverse path does not re-check `is_active` |

---

## 12. Performance Considerations

### 12.1 Wins
- Inventory: unbounded result set → 50 rows + 1 aggregate summary query.
- Inflow/outflow lists: composite index converts the filter+sort from a scan-and-sort into
  an index range scan.
- Payload: an org with 5,000 inventory rows currently ships every row on every load.

### 12.2 New costs
- One extra summary query per inventory page load — same indexed group-by, no new joins.
- One `/stock-check` call per material selection in the outflow dialog — single indexed
  aggregate; cached per `(site, material)` for the dialog's lifetime.
- Advisory lock held for the remainder of the transaction (microseconds).

### 12.3 Accepted, documented limits (not fixed in Phase 2)
- `ILIKE '%term%'` cannot use a B-tree index (leading wildcard). At V1 catalogue sizes
  (hundreds to low thousands per org) this is a fast scan. Trigram/`pg_trgm` is the fix if
  it ever matters — deliberately deferred as premature.
- `get_ledger` evaluates its CTE twice per page (once for `COUNT`, once for the page). Fine
  for per-site-per-material history; noted for the future.

### 12.4 Concurrency & race-condition audit *(explicitly requested)*

**Method:** traced every materials write path for read-modify-write patterns under the
actual isolation level in use.

**Finding — the current system is safe, and here is precisely why.**

Isolation is READ COMMITTED (PostgreSQL default; `engine.begin()` sets nothing else). Under
READ COMMITTED, the classic corruption is a *lost update*: two transactions read a value,
each computes a new value from what it read, and the second write silently overwrites the
first.

**The materials write path contains no such pattern:**

1. There is **no stored stock counter**. Nothing does
   `UPDATE stock SET qty = qty - :n`. Stock is derived by `SUM` at read time.
2. Every write is an **unconditional INSERT** of a positive quantity. No inserted value is
   computed from a prior read.
3. `SUM` over a set of committed rows is order-independent. Two concurrent outflows of 8 and
   5 against 20 insert two rows; the next read sums to 7 regardless of interleaving.
4. Receipt/usage and ledger inserts share one connection and one transaction, so a partial
   write is impossible — either both land or neither does.

**Conclusion: no concurrency fix is needed for the code as it exists today.** Reporting
otherwise would be inventing work.

**However — two Phase 2 changes introduce the risk that isn't there now.** This is the
substantive result of the audit:

| Risk | Shape | Why READ COMMITTED does not save us |
|---|---|---|
| **R1 — over-issue race** (from § 6.5) | `SELECT SUM(...)` → decide → `INSERT` | Two transactions both read `available = 10`, both approve an issue of 8, both insert. Result: −6, with both users having been told it was fine. The guard becomes theatre exactly when it matters. |
| **R2 — double-reversal race** (from § 6.1) | `SELECT already_reversed?` → `INSERT` | Two clicks land in different connections; both read "not reversed", both insert. |

**Mitigation — recommended:**

- **R1:** `SELECT pg_advisory_xact_lock(hashtextextended(site_id::text || material_id::text, 0))`
  immediately before the stock read, inside the existing request transaction. Serializes
  only concurrent writes **to the same site+material** — no impact on any other material,
  site, project, or module. Releases automatically at commit or rollback; no cleanup path,
  no deadlock risk (single lock, no ordering).
- **R2:** the **partial unique index is the real guard** (§ 6.1) — the database, not the
  application, is authoritative. The pre-check exists only to produce a friendly 409;
  a lost race surfaces as an IntegrityError mapped to that same 409.

**Mitigations considered and rejected:**
- `SERIALIZABLE` isolation — would require a retry loop on every write and, because
  `PostgresDatabase.transaction()` is **shared with Labour, Finance, and every other
  domain**, could not be changed without affecting them. Violates § 15.
- `SELECT ... FOR UPDATE` on movement rows — meaningless; the contended resource is an
  aggregate over rows that do not exist yet, not any existing row.
- Doing nothing and treating the check as advisory — defensible, but a warning that is
  wrong under exactly the conditions it was built for is worse than no warning.

**Also noted, low severity, no change proposed:** `PATCH /materials/{id}` does
`has_movements()` → `update()` as check-then-act. A movement landing between the two could
let a Stock Unit change slip through. Requires an admin editing a unit at the same
millisecond as a first movement for that material. Recorded here so it is a known
accepted risk rather than an oversight; the fix (same advisory lock) is one line if it is
ever wanted.

---

## 13. Security & Permissions

**No change to the authorization model.** All new and modified endpoints reuse
`get_auth_context`, `_resolve_project_ids`, `_site_filter_denied`, `_authorize_write`
exactly as the existing endpoints do.

- `GET /materials/stock-check` **must** apply the same site/project scope checks as
  `GET /materials/inventory` — it is a new endpoint and therefore a new place to get
  authorization wrong. Explicit test required (§ 16.1).
- Inventory `search`/`stock_state` are filters applied **after** the org+scope predicate,
  never in place of it.
- `allow_negative` is **not** a privilege escalation — over-issue is currently allowed
  unconditionally by anyone who can record an outflow; the flag makes an existing capability
  explicit rather than granting a new one.
- Reversal remains ADMIN/PROJECT_MANAGER-only (`role_can_adjust`). Unchanged.
- `Idempotency-Key` is scoped per organization when claimed, so a key from one org can never
  replay another org's result.
- All new SQL uses SQLAlchemy expression binding. The one place needing care:
  `lower(btrim(name))` in the migration is static SQL, not interpolated input.

---

## 14. Regression Risk Analysis

### 14.1 Highest risk — inventory KPI correctness
Pagination without moving the summary server-side would silently make the KPI cards report
page-local counts. A storekeeper reading "Negative Stock: 2" when the true figure is 7
is worse than the current slow-but-correct page. **The summary query and the pagination
must land in the same change**, and a test must assert `summary.negative` over a dataset
larger than one page.

### 14.2 Breaking changes requiring an explicit decision

| Change | Who breaks | Options |
|---|---|---|
| `GET /materials/inventory` array → `{items,total,summary}` | dashboard `inventory-view.tsx`, mobile `materialsService.ts` | (a) update both consumers in this phase; (b) keep the bare array when `limit` is absent. **Recommend (a)** — two consumers, both in this repo, and (b) leaves the unbounded path alive forever, which is the defect |
| Outflow 409 on over-issue by default | WhatsApp assistant, mobile — neither sends `allow_negative` | (a) default `false` everywhere, update WhatsApp+mobile — **out of Phase 2 scope and touches WhatsApp**; (b) default `false` for the dashboard only, `true` for other sources; (c) default `true`, dashboard opts in. **Recommend (c)** for Phase 2: the dashboard gets the safety net now, no other surface changes behaviour, and tightening the default later is a one-line follow-up once WhatsApp/mobile are ready |
| Reverse endpoints 409 on already-reversed | Any caller relying on double-reversal | None — that behaviour is the bug |

### 14.3 Other risks
| Risk | Severity | Mitigation |
|---|---|---|
| Catalogue merge repoints the wrong survivor | **High** — data loss shape | Dry-run + human-reviewed report; abort on ambiguity; DB backup before deploy |
| `CREATE INDEX` locks tables on a live DB | Medium | `CONCURRENTLY`, outside a transaction; documented in the runbook |
| Idempotency replay returns a stale result | Low | Replay returns the original id, which is the correct answer |
| Advisory lock contention | Low | Scoped to one site+material; held for microseconds |
| Date filter timezone drift | Medium | Reuse `toLocalISODate` (already used by Phase 1's `purchase-history-view.tsx`) |
| Phase 1's uncommitted files conflict | Medium | See § 15.3 |

---

## 15. Labour Module Isolation

**Backend: fully isolated.** Materials lives in `domains/materials/`,
`application/materials/`, `repositories/materials.py`, and the `material_*` /
`materials_catalog` / `units_of_measure` tables. Labour lives in `domains/workforce/` and
its own tables. No shared file, no shared table, no shared query. Confirmed by directory
inspection.

**Three genuine shared surfaces — flagging before implementation as required:**

### 15.1 Alembic migration numbering — REQUIRES COORDINATION
The current head is **`0456` (`0456_labour_attendance_sheet_fields`), and `0454`/`0456` are
Labour's own migrations — the Labour team is actively adding migrations right now.** If
Phase 2 creates a migration against head `0456` and Labour lands another concurrently, the
result is a **branched Alembic history that blocks deployment for both modules.**

This is the one item that cannot be solved by care on our side alone. Proposal: assign the
Phase 2 migration number immediately before implementation, confirm the head at that moment,
and notify the Labour team of the number claimed. **Requesting a decision on how to
coordinate this.**

### 15.2 Shared UI primitives — avoided by design
`components/ui/kpi-card.tsx`, `bulk-action-bar.tsx`, `table.tsx`, `input.tsx`, `select.tsx`
are used by `AttendancePage`, `LabourOverviewPage`, `LabourAnalyticsPage`, and others.
**Phase 2 modifies none of them.** The new pagination and date-range components are created
under `components/materials/`, accepting slightly narrower reuse in exchange for a zero
blast radius. If a shared primitive ever *needs* changing, work stops and it is reported.

### 15.3 `PostgresDatabase.transaction()` — shared, and deliberately untouched
Used by every domain. This is why SERIALIZABLE was rejected in § 12.4 in favour of a
per-request advisory lock that changes nothing globally.

### 15.4 Working-tree state
Phase 1's `purchase-history-view.tsx` and `purchase-details-sheet.tsx` are **currently
uncommitted**, alongside uncommitted edits to `AGENTS.md` and
`MATERIALS_CATALOGUE_PLAN.md`. Per the project's concurrent-agent situation, these should be
committed (or confirmed as ours) **before** Phase 2 begins, so Phase 2's diff is reviewable
in isolation and no other agent's work is clobbered.

**Verification method (§ 16.5):** after implementation, `git diff --stat` must show zero
files under `workforce/`, `attendance`, `labour`, or `components/ui/`; the full Labour test
suite must be run and pass.

---

## 16. Testing Plan

### 16.1 New unit tests
- Idempotency: same key twice → one row, `status: "replayed"`; different keys → two rows;
  no key → current behaviour; same key + different body → replay (E3)
- Reversal guard: reverse twice → second is 409; reversal of a reversal; reversing a
  movement whose material is now inactive still works (E14)
- Catalogue: `"Cement"` then `"cement"` → 409; `"  Cement  "` → 409; PATCH rename into an
  existing name → 409
- Stock guard: over-issue without flag → 409 with `available`/`requested`; with flag → 201;
  exact-stock issue → 201; issue against already-negative stock (E5)
- Inventory pagination: `total` is set-wide; **`summary` is set-wide, not page-wide**;
  page clamping (E11); search matches; `stock_state` filter

### 16.2 Contract tests
`test_materials_api_contract.py` extended for the new inventory response shape and
`/stock-check` — including **authorization**: a caller scoped to Site A must get 403/empty
for Site B's stock check.

### 16.3 Migration tests
Against a scratch DB seeded with deliberately messy data: pre-existing duplicate reversals
(expect abort), case-variant duplicates with and without movements (expect merge / expect
abort), and **stock-parity assertion — every material's computed stock is identical before
and after the migration.** That assertion is the one that proves no corruption was
introduced.

### 16.4 Concurrency tests *(the audit's proof)*
Two concurrent connections against a real Postgres:
- Both issue 8 against available 10 → exactly one succeeds, final stock ≥ 0
- Both reverse the same movement → exactly one succeeds, exactly one reversal row exists
- Both submit with the same idempotency key → exactly one row
- **Control test:** both issue with `allow_negative=true` → both succeed, and the summed
  stock is exactly correct (proving the lock did not change unlocked semantics)

### 16.5 Regression & isolation
- Full backend suite (`pytest backend/tests/`), full WhatsApp suite, dashboard build +
  typecheck + lint
- **Labour suite run explicitly and reported**, plus the `git diff --stat` file-path check
- Manual: record inflow/outflow, correct a movement, browse a paginated inventory,
  filter by date, trigger the over-stock warning, verify Labour pages render unchanged

---

## 17. Success Criteria

| # | Criterion | Verified by |
|---|---|---|
| S1 | A movement cannot be reversed twice — via UI, via API, or via two simultaneous requests | 16.1, 16.4 |
| S2 | A double-submitted inflow/outflow creates exactly one movement | 16.1, 16.4 |
| S3 | Case/whitespace-variant material names are impossible; existing duplicates merged with stock parity proven | 16.1, 16.3 |
| S4 | Inventory returns bounded pages with server-side search, and KPI cards reflect the **whole filtered set** | 16.1 |
| S5 | Recording an outflow above available stock requires explicit confirmation, and the check holds under concurrency | 16.1, 16.4 |
| S6 | Inflows, outflows, and purchases are filterable by date range | Manual |
| S7 | Every error a storekeeper can trigger says what to do next | Manual |
| S8 | Full backend + WhatsApp + dashboard suites pass | 16.5 |
| S9 | **Zero files changed under Labour paths or `components/ui/`; Labour suite passes** | 16.5 |
| S10 | No new tables, no new columns, no duplicated API, no new abstraction | Diff review |

---

## Priority Matrix

| ID | Item | Impact | Effort | Risk if skipped | Priority |
|---|---|---|---|---|---|
| D1 | Duplicate reversal guard | **Critical** | Low | Permanent, silent, doubling stock error | **P0** |
| D2 | REST idempotency | **Critical** | Medium | Phantom stock, unattributable | **P0** |
| D3 | Case-insensitive catalogue | High | Medium | Split stock; WhatsApp resolves arbitrarily | **P1** |
| D5 | Over-stock confirmation | High | Medium | Typos become permanent, PM-only to fix | **P1** |
| D4 | Inventory pagination + search | High | Medium | Degrades continuously with growth | **P1** |
| — | Perf indexes | Medium | Low | Slow lists as history accumulates | **P2** |
| D6 | Date filters | Medium | **Very low** | Usability only; backend already done | **P2** |
| — | Error-message polish | Low | Low | Support burden | **P3** |
| — | PATCH unit-lock race | Very low | Very low | Accepted, documented | **P4 — not planned** |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Catalogue merge picks the wrong survivor | Low | **Critical** (data) | Dry-run, human-reviewed report, abort-on-ambiguity, DB backup |
| Alembic branch from concurrent Labour migration | **Medium** | High (blocks both modules' deploys) | § 15.1 — coordinate the number before writing the file |
| Inventory KPIs become page-local | Medium | **High** (wrong numbers, silently) | § 14.1 — server-side summary lands in the same change |
| Breaking mobile via the inventory response shape | Medium | Medium | § 14.2 decision; mobile updated in the same change |
| Over-stock 409 unexpectedly breaks WhatsApp | Medium | Medium | § 14.2 recommendation (c) — default `true`, dashboard opts in |
| `CREATE INDEX` locking a live table | Low | Medium | `CONCURRENTLY` + runbook note |
| Advisory lock deadlock | **Very low** | Low | Single lock, no ordering, transaction-scoped |
| Scope creep into procurement/PO territory | Low | Medium | Scope rules in the brief; this plan adds no business feature |

---

## Recommended Implementation Order

Ordered so that the **irreversible data risks are addressed first, while the dataset is
smallest**, and so each step is independently testable and revertible.

**Step 1 — Integrity foundation (P0).** Migration: duplicate-reversal detection, catalogue
merge, unique indexes, perf indexes. Dry-run first; deploy alone; verify stock parity before
proceeding. *This is the only step with irreversible data effects and it must not share a
deploy with anything else.*

**Step 2 — Reversal guard (P0).** Application check + 409 + UI. Small, self-contained,
immediately valuable. Backed by Step 1's index.

**Step 3 — REST idempotency (P0).** Backend claim + dashboard key generation. Independent
of Steps 1–2.

**Step 4 — Inventory pagination, search, and server-side summary (P1).** Backend and both
consumers (dashboard + mobile) in one change — § 14.1.

**Step 5 — Over-stock guard (P1).** Advisory lock, `/stock-check`, outflow 409, dialog
confirmation. Placed after Step 4 so the concurrency work lands on a settled read path.

**Step 6 — Date filters + error-message polish (P2/P3).** Lowest risk, ends the phase on
pure UX. Frontend-only.

**Between every step:** full regression suite, Labour isolation check, and the § 16 tests
for that step. Steps 1 and 5 additionally require the concurrency tests (§ 16.4).

---

## Open Decisions — required before implementation begins

1. **§ 14.2 — inventory response shape.** Update both consumers (recommended), or keep a
   backward-compatible bare array?
2. **§ 14.2 — over-stock default.** Recommendation: `allow_negative` defaults to `true`, the
   dashboard opts in, so WhatsApp and mobile are unaffected this phase. Confirm?
3. **§ 15.1 — Alembic numbering.** How should the migration number be claimed given Labour
   is actively adding migrations at head `0456`?
4. **§ 15.4 — Phase 1's uncommitted files.** Commit them before Phase 2 starts?
5. **Scope confirmation:** Steps 1–6 as one Phase 2, or split at Step 3 (integrity first,
   then scalability/UX as Phase 2b)?

---

**Status: awaiting approval. No implementation will begin until this plan is approved.**
