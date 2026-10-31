> **HISTORICAL (31 Oct 2026).** The WhatsApp assistant is now v2: one agent + skills + tools, see [../architecture/assistant-v2.md](../architecture/assistant-v2.md).
> This document describes the classic chain (classifier / planner / workflows), now retiring; the body is unchanged. Treat workflow / router / planner wording as the classic path.

# Phase A — Inventory Integrity & Safety (Implementation Plan)

**Status:** PLAN — awaiting approval. No code until approved.
**Author:** Claude (Opus 5), 2026-07-30.
**Branch (to create):** `feature/materials-phase-a-integrity` off `origin/main` @ `ab3cf15`.
**Migration number claimed:** **0459** (head verified `0458`).
**Research basis:** [MATERIALS_MISSION_RESEARCH_REPORT.md](MATERIALS_MISSION_RESEARCH_REPORT.md)
§2.1, re-verified against current `main` on 2026-07-30 — all four gaps still present, materials
untouched by the 4 commits that landed since.

---

## 1. Objective

Make it impossible for material stock to go silently and permanently wrong.

Four specific defects, all of which corrupt data that **can never be edited or deleted** — only
corrected by someone who notices.

---

## 2. Business Value

Right now the system can quietly get stock wrong in ways nobody sees until a physical count
doesn't match. And because material records are append-only by design, a wrong number today is
still wrong next year unless a manager spots it and posts a correction.

Four ways that happens today:

- **A correction can be applied twice.** Reverse a 50-bag delivery twice and stock is out by
  100 bags, permanently. Fixing it needs a third correction — which can also be double-applied.
- **A slow connection turns one delivery into two.** Tap "record" on weak site wifi, nothing
  seems to happen, tap again — two identical deliveries that nobody can tell apart. Which one is
  real?
- **"Cement" and "cement" are two different materials.** One stockpile splits into two
  half-empty ones. Worse: the WhatsApp assistant *is* case-insensitive, so when both exist it
  picks one at random — the same message can hit either.
- **Issuing 500 bags from a site holding 20 is accepted silently.** A typo becomes permanent and
  needs a Project Manager to unwind.

After this phase, none of these are possible. **This is the phase that makes the module
trustworthy enough to run a site on** — and everything built later writes into the ledger it
protects.

---

## 3. Scope

**In:**
- G1 — prevent duplicate reversals (DB constraint + friendly error)
- G2 — request idempotency for web/mobile writes
- G3 — case/whitespace-insensitive material names + reviewed merge of existing duplicates
- G4 — negative-stock confirmation on outflows, correct under concurrency
- Concurrency protection for G4 and G1 (the mission lists this under Inventory)
- Two composite indexes matching the inflow/outflow list access pattern

**Out (and where it lives):** cost capture → **Phase B**; invoice work → **Phase C/D**;
inventory pagination, search, analytics → **Phase E**; error-message and mobile polish →
**Phase F**. The `PATCH /materials/{id}` unit-lock race is documented as an accepted low risk,
not fixed.

---

## 4. Files Expected To Change

**Backend** — `domains/materials/router.py` (guards on 2 reverse + 2 create endpoints);
`infrastructure/postgres/repositories/materials.py` (`is_already_reversed`,
`get_available_stock`, case-insensitive `get_by_name`); `domains/materials/responses.py`
(`already_reversed` flag); **new** `backend/migrations/versions/0459_materials_integrity.py`.

**Dashboard** — `lib/materials.ts` (idempotency key, stock-check call);
`record-inflow-dialog.tsx`, `record-outflow-dialog.tsx` (key per dialog-open, submit lockout,
available-stock display, over-stock confirmation); `correction-dialog.tsx` (409 handling);
`movement-details-sheet.tsx` (hide Correct when already corrected).

**Not touched:** `components/ui/*`, `lib/api.ts`, anything under `workforce/`, any WhatsApp
file, any Finance file.

---

## 5. Backend Work

**G1 — duplicate reversals.** Two layers, because an application check alone is a
check-then-act race:
1. **Database (authoritative):** partial unique index
   `UNIQUE (reverses_movement_id) WHERE reverses_movement_id IS NOT NULL` on
   `material_receipts` and `material_usage`. One original ⇒ at most one reversal, enforced even
   against direct SQL.
2. **Application (for the message):** `is_already_reversed()` pre-check → `409 "This movement
   was already corrected on <date>."` A lost race surfaces as `IntegrityError`, caught and
   mapped to the same 409 — never a 500.

**G2 — idempotency.** Optional `Idempotency-Key` header on `POST /materials/inflows` and
`/outflows`, reusing the existing `idempotency_keys` claim pattern
(`INSERT ... ON CONFLICT DO NOTHING`) **inside the request's existing transaction** — the same
mechanism `application/materials/handlers.py` already uses on the WhatsApp path. No new
abstraction. A claimed key returns the original result with HTTP 200 and `status: "replayed"`.
Absent header ⇒ exactly today's behaviour.

**G3 — case-insensitive names.** `get_by_name` becomes case/whitespace-insensitive so the
existing 409 fires correctly; the same check is added to the update path.

**G4 — negative-stock guard.** New `GET /materials/stock-check?site_id=&material_id=` returning
`{available, unit}` (reuses `get_stock_levels` with a `material_id` filter — no new query
logic). `POST /materials/outflows` gains optional `allow_negative: bool`. If the resulting
balance would go below zero and the flag is false → `409 {detail, available, requested, unit}`.

**Concurrency.** `pg_advisory_xact_lock` on `(site_id, material_id)` immediately before the
stock read, inside the existing request transaction. Without it the guard is theatre: two
concurrent outflows of 8 against 10 both read 10, both pass, both insert → −6, with both users
told it was fine. The lock serialises only writes to the *same site+material*, releases on
commit, and cannot deadlock (single lock, no ordering).

**Rejected:** `SERIALIZABLE` isolation — `PostgresDatabase.transaction()` is shared with Labour,
Finance and every other domain; changing it globally would violate module isolation.

---

## 6. Frontend Work

Idempotency key generated **when a dialog opens**, not per click, so N clicks share one key;
regenerated only after a successful submit. Submit button locks during flight. The outflow
dialog shows available stock on material selection and, when quantity exceeds it, an **inline**
confirmation (not a browser `confirm()`, matching the existing dialog idiom) stating the
resulting negative balance and that corrections need a Project Manager. Every 409 leaves the
dialog open with typed values intact. The "Correct" button is **hidden** on already-corrected
movements, replaced by `✓ Corrected on <date>` — a disabled button the user can't use is worse
than showing the fact.

---

## 7. Database Work

**One migration, `0459`.** No new tables, no new columns, no type changes, **no change to
`material_movements`**.

| Step | Operation | Reversible |
|---|---|---|
| 1 | Detect pre-existing duplicate reversals; **abort with the offending ids**, change nothing | n/a |
| 2 | Detect + merge case-variant catalogue duplicates; **abort on ambiguous unit conflicts** | Data merge — **not** cleanly reversible |
| 3 | `UNIQUE INDEX ON materials_catalog (organization_id, lower(btrim(name)))` | Yes |
| 4–5 | Partial unique index on `reverses_movement_id`, both operational tables | Yes |
| 6–7 | `material_receipts` / `material_usage` `(organization_id, project_id, occurred_date DESC)` | Yes |

Step 2 is the only destructive step. It merges by repointing `material_id` on receipts, usage
and movements to the surviving row, then deleting the now-unreferenced duplicates. It **aborts
rather than guesses** when two colliding rows both have movements in *different* units. Dry-run
against a production snapshot with a human-reviewed report before the real run.

Steps 3–7 use `CREATE INDEX CONCURRENTLY` against a live database (must run outside a
transaction — flagged for the deploy runbook).

---

## 8. API Work

**Reused:** every authorization helper, `post_material_movement`, all repositories, the
`idempotency_keys` table and claim pattern.
**Modified:** `POST /materials/inflows`, `POST /materials/outflows` (optional header; outflow
gains `allow_negative`); both `/reverse` endpoints (409 on repeat).
**Added:** `GET /materials/stock-check` — justified: no existing endpoint returns one material's
balance without fetching the whole inventory list, and the outflow dialog needs exactly one
number per material selection.

**Breaking-behaviour decision:** `allow_negative` defaults to **`true`** for non-web sources so
WhatsApp and mobile are unaffected this phase; the dashboard opts in explicitly. Tightening the
default later is a one-line change once those surfaces are ready. *(Confirm — this was
recommended earlier and not explicitly settled.)*

---

## 9. Risks

**Technical.** The catalogue merge is the only irreversible step in the whole mission —
mitigated by dry-run, human-reviewed report, abort-on-ambiguity, and a **stock-parity
assertion**: every material's computed stock must be identical before and after. That assertion
is what proves no corruption was introduced. `CREATE INDEX` locking is mitigated by
`CONCURRENTLY`.

**Business.** The over-stock 409 changes existing API behaviour; the `allow_negative` default
above confines it to the dashboard. Genuine negative stock happens (unrecorded historical
deliveries), so the guard is a **confirmation, not a prohibition**.

**Regression.** An incorrect merge would repoint history to the wrong material — the parity
assertion catches it. Idempotency is opt-in, so absent-header behaviour is bit-identical to
today.

---

## 10. Testing Strategy

**Unit** — idempotency replay/distinct-key/no-key/same-key-different-body; double reversal;
reversal of a reversal; reversing a movement whose material is now inactive; case-variant
rejection including whitespace; PATCH rename into an existing name; over-issue with and without
the flag; exact-stock issue; issue against already-negative stock.

**Integration (real Postgres, two connections)** — both issue 8 against available 10 → exactly
one succeeds, final stock ≥ 0; both reverse the same movement → exactly one succeeds; both
submit the same idempotency key → exactly one row; **control test:** both issue with
`allow_negative=true` → both succeed and the sum is exactly right, proving the lock did not
change unlocked semantics.

**Migration** — against a scratch DB seeded with deliberately messy data: pre-existing duplicate
reversals (expect abort), case variants with and without movements (expect merge / expect
abort), and **stock parity asserted across the whole migration**.

**Regression** — full backend suite, full WhatsApp suite, dashboard typecheck + lint + build.
Baseline captured **before** any change so a pre-existing failure is never mistaken for mine.

---

## 11. Rollback Strategy

- **Steps 3–7 (indexes):** `DROP INDEX` — clean, immediate, no data effect.
- **Step 2 (merge):** **not cleanly reversible.** Mitigation is prevention: dry-run first,
  human-reviewed report, abort on ambiguity, and a database backup taken immediately before the
  deploy. Recovery is restore-from-backup, not a down-migration.
- **Application code:** revert the branch. Idempotency and `allow_negative` are additive and
  optional, so reverting restores prior behaviour exactly. The 409s disappear with the code;
  the DB indexes can stay (they only forbid things that were already defects).
- **Deploy order:** migration first, verified, **alone**; application after. The migration is
  backward-compatible with the current code — the indexes forbid only what the new code also
  forbids.

---

## 12. Labour Module Isolation

No Labour, Attendance, Payroll or Workforce file is touched. No `components/ui/*` file is
touched. No shared AI prompt is touched (that risk belongs to Phase D). The shared
`PostgresDatabase.transaction()` is **used, not modified** — which is precisely why
`SERIALIZABLE` was rejected in favour of a per-request advisory lock.

**Migration numbering** remains the one cross-team hazard: `0459` is claimed against head
`0458`. If another team lands a migration first, the number must be re-claimed before merge to
avoid a branched Alembic history.

**Verification:** `git diff --stat main...HEAD` must show zero files under `workforce/`,
`labour`, `attendance`, `payroll` or `components/ui/`, plus a Labour suite run, reported.

---

## 13. Success Criteria

1. A movement cannot be reversed twice — via UI, via API, or by two simultaneous requests.
2. A double-submitted inflow/outflow creates exactly one movement.
3. Case/whitespace-variant material names are impossible; existing duplicates merged with
   **stock parity proven**.
4. Recording an outflow above available stock requires explicit confirmation, and the check
   holds under concurrency.
5. Every 409 leaves the user's typed input intact and says what to do next.
6. Full backend, WhatsApp and dashboard suites pass, with a before/after baseline.
7. Zero files changed under Labour paths or `components/ui/`; Labour suite passes.
8. No new tables, no new columns, no duplicated API, no new abstraction.

---

## 14. Implementation Order

1. **Baseline** — capture full-suite results before any change.
2. **Migration `0459`** with dry-run tooling and the parity assertion. Reviewed before running.
3. **G1** reversal guard (backend + UI) — smallest, highest value, backed by the index.
4. **G2** idempotency (backend + both dialogs).
5. **G3** case-insensitive names (the application half; the merge shipped in step 2).
6. **G4** stock guard + advisory lock + `/stock-check` + outflow dialog.
7. **Full regression**, Labour isolation check, docs update, commit, push, report, **stop**.

---

## Open Items

1. **`allow_negative` default** — recommended `true` for non-web sources this phase (§8).
2. **No Linear issue exists** for Phase A. The workflow requires updating one; there is nothing
   to update. Recommend creating the epic + a Phase A issue before implementation starts.
3. **Migration `0459`** — should the Labour/WhatsApp team be notified of the claim?

---

**Status: awaiting approval. No code until approved.**
