# Material plan: what to order, how much, and by when (Nov 2026)

> **Status:** plan, 8 Nov 2026. One of three independent plans split from
> [connected-project-plan.md](connected-project-plan.md); tracker section **MP** in [V1_TRACKER.md](V1_TRACKER.md).
> **Does not wait on the drawing reader (DR) or progress by place (LP).** Everything it needs is built: BOQ (CC-02),
> measured work per BOQ line (CC-04), schedule dates (ST-04), stock and open POs (PRC-17, PRC-27).
> CC-03 (material norms) is done here as MP-01.

## 1. The problem

"Cement ran out the morning of the slab pour" is the most expensive phone call on a site. Today Mesiri knows what is
left of each BOQ line, when each activity is planned, and what is in stock and on order, but nothing joins them. A PM
works out the week's order in his head on Saturday.

**Answer:** each BOQ line says what one unit of it consumes (norms). Remaining work × norms, spread over the
activity's dates, gives the need per material per week. Minus stock and open orders gives the week it runs short;
minus the supplier's lead time gives the day to order. The plan updates itself: site measures work on WhatsApp, the
remaining quantity drops; the schedule moves, the need moves.

## 2. Investigation (Phase 1, `main` at `e536b87`)

| Area | Exists | Reuse |
|---|---|---|
| BOQ line | `work_package_planned_items` (planned qty, unit, rates, `superseded_by_id` revisions; 0420 / 0508) | Norms hang off a line (current revision; carried over on a revision) |
| Done per line | `boq_router.done_by_line` (CC-04), also used by the Gantt (`schedule/store.measured_by_line`) | Remaining = planned − done, one rule everywhere |
| Dates | `work_packages.planned_start / planned_end` (ST-04), forecast finish at the site's pace (`schedule/logic.forecast_end`) | Need is spread over the remaining planned (or forecast) days |
| Stock | `get_stock_summary` (PRC-17): closing per site + material; `on_order_by_site` (PRC-27) | On hand + on order, per project |
| Reminders | the reminder pass (`application/procurement/alerts.queue_reminders`), schedule notes (ST-06, `schedule/reminders.py`) | Order-by note is one more note there |
| Money | `may_view_expenses` (BOQ, money) | Same rule for norms and the plan's money columns |
| Assistant | v3 `agent_api/tools.py` `ALLOWED` + `SOP.md` | `material_plan` read route |

## 3. Items

| ID | What | Size |
|---|---|---|
| **MP-01** | **Material norms per BOQ line** (was CC-03): `boq_material_norms` (planned_item_id, material_id, quantity_per_unit, wastage_pct); `GET/PUT /projects/{id}/boq/lines/{line}/norms`; "copy norms to lines of the same work"; BOQ page: a Materials row under each line | S |
| **MP-02** | **Weekly material plan:** `GET /projects/{id}/material-plan?weeks=8&site_id=`: per material, required total (BOQ × norm), still needed (remaining × norm), per-week need, on hand, on order, the week it runs short; pure maths in `domains/materials/plan.py`; Planning › Material plan page | M |
| **MP-03** | **Order-by:** `vendors.lead_time_days` (nullable, additive) + default 3 days; order-by date per short material; one grouped note a day to PM / storekeeper in the reminder pass, only for materials whose order-by date is within 2 days; "Draft PO" button opens the PO form prefilled | M |
| **MP-04** | **On WhatsApp:** v3 `material_plan` in `ALLOWED` + SOP rule ("what do I need next week?", "is cement enough for the slab?") | S |
| **MP-05** | **Consumption against the work** (rest of CC-08): `material_usage.planned_item_id`; used vs norm per line ("slab used 12% more cement than its norm") | M |
| **MP-06** | **Cash-flow forecast:** plan × last rate + BOQ labour / subcontract rates over the schedule; RA bills in when NXT-02 exists. **Blocked:** who sees it (D-MP3) needs Ilan | M |

## 3a. As built

- **MP-01 (8 Nov, `c62511e`).** Migration **0523** `boq_material_norms` (line, material, quantity per unit, wastage %,
  note; unique per line and material; RLS; downgrade refuses while norms exist). A norm is always in the material's
  **stock unit** (`materials_catalog.default_unit_id`), so the plan compares need with stock without converting; the
  dialog shows that unit. Routes on the BOQ router (same roles as the BOQ): `PUT /projects/{id}/boq/lines/{line}/norms`
  replaces the line's set (empty clears); `POST .../norms/copy` puts them on the project's other current lines with the
  same work (case and spacing ignored) and unit, keeping lines that have their own unless `overwrite`. `GET /boq` lines
  carry `materials`. `revise_quantity` moves norms to the new revision. A material named in a norm counts as in use for
  catalog delete (deactivate instead). Dashboard: materials under each BOQ line; "Materials per <unit>" dialog with
  "use the same for the N other lines with this work". Repository: `repositories/material_norms.py`.

- **MP-02 (8 Nov, `3588edc`).** `GET /projects/{id}/material-plan?weeks=8&site_id=` (`domains/materials/plan_router.py`,
  maths in `plan.py`, 7 unit tests + a contract test). Per material: required, still needed, per-week need (weeks
  from Monday of today's week), unscheduled (lines with no dates), later (after the weeks shown), on hand (closing
  today over the project's sites, or one site), on order (open POs, PRC-27), the short week and `short_by`; the lines
  each need comes from. A late activity (end passed, not finished) needs the rest in the next 7 days. Stock held in
  another unit is not counted and is flagged. Same roles as the BOQ (quantities to storekeeper / engineer later, a
  permissions decision). **Not yet:** the forecast finish (ST-04) instead of planned dates when site is slower.
  Dashboard: Planning › Material plan (`/planning/materials`), table on desktop, cards on phones.

## 4. Implementation plan (Phase 2)

**Objective.** A PM sees, per project, what material is needed each week, which will run short, and the day to order
it, without typing anything except the norms once (or copying them).

**Database.** MP-01: migration `boq_material_norms` (additive; tenant RLS like 0522; unique (planned_item_id,
material_id); quantity_per_unit > 0; wastage 0-100). MP-03: `vendors.lead_time_days` (nullable). MP-05:
`material_usage.planned_item_id` (nullable). Nothing rewritten.

**Maths (MP-02, pure, tested).** For each current BOQ line with norms: remaining = max(planned − done, 0) in the
line's unit; need of material m = remaining × qty_per_unit × (1 + wastage/100). Spread evenly over the activity's
remaining working days: from max(today, planned_start) to planned_end (if planned_end has passed and it is not done,
over the next 7 days: it is late and needs it now). A line with no dates is "unscheduled": counted in the total, not in a
week. Short week: first week where cumulative need > on hand + on order. Order-by = first day of that week −
lead time. Units: a norm is in the material's stock unit; nothing is converted.

**Frontend.** BOQ page: under each line, its materials (name, per unit, wastage) with edit (same roles as BOQ edit).
Planning › Material plan: one row per material (required, still needed, on hand, on order, short from, order by),
weeks as columns with the need, red from the short week. Phone: list of cards. Empty states explain the one thing to
do ("Add materials to your BOQ lines").

**Permissions.** Read and edit like the BOQ (`may_view_expenses`); the plan's quantities (no money) to anyone who sees
the project's stock. Money columns only with `may_view_expenses`.

**Risks.** Wrong norms give a wrong plan: the page shows each material's source lines. Schedules not kept up: the plan
uses forecast dates when site is slower than plan. Reminder noise: one note a day, grouped, only near order-by.

**Testing.** Unit tests for the maths (spread, late, unscheduled, wastage, short week, order-by), route tests with a
seeded BOQ + schedule + stock, migration up/down, dashboard `tsc` / oxlint / build, v3 tool contract test.

**Rollback.** Each item is its own commit; revert removes route, page, note. Columns and table are additive; downgrade
drops them (refuses while norms exist).

**Labour isolation.** Reads no Labour or Attendance data. MP-06 reads BOQ labour rates only. Payroll / Workforce untouched.

**Success criteria.** On a project with BOQ lines, norms, dates and stock: the plan's weekly need matches a hand
calculation, the short week and order-by date are right, the note arrives once on the right day.

## 5. Decisions (defaults used until answered)

| # | Question | Default |
|---|---|---|
| D-MP1 | Where norms come from | Typed or copied per line by the office; a standard-norms library (IS 10262 mixes, brickwork, plaster) later, with the material knowledge work (MK) |
| D-MP2 | Lead time | Per supplier (`vendors.lead_time_days`), 3 days when unknown |
| D-MP3 | Who sees the cash-flow forecast | Owner, admin, finance. *Permissions: needs Ilan* |
