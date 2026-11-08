# Subcontracts, next: material given to the team, and deductions on a bill

> Phase 2 plan (CLAUDE.md). Asked 8 Nov 2026 after the subcontract module (NXT-05…07, 16…18) shipped:
> "so is that it in the subcontractor module?" → gaps found, these two first. Tracker: **NXT-19**, **NXT-20**.
> Builds on [subcontractors-plan.md](subcontractors-plan.md). Not started: waiting for the decisions in §10.

## 1. Objective

1. **Deductions on a bill (NXT-19).** Take an amount off a subcontractor's bill, with a reason: material bought for
   them, rework, damage, a delay penalty, anything agreed. Today this happens outside Mesiri, so the ledger, the
   statement and the "money caught" box are wrong by that amount.
2. **Material given to the team (free-issue) checked against the work (NXT-20).** The builder often supplies cement,
   steel or blocks ("shuttering material and concrete by us"). Mesiri compares what was given to the team with what the
   measured work should have used (plus an agreed wastage allowance) and puts the excess on the next bill as a
   deduction, at an agreed recovery rate.

## 2. Scope

In: deductions (manual and from the material check) on subcontract bills; materials agreed per work order (norm,
wastage allowance, recovery rate); issuing stock to a work order; a material reconciliation per work order; the
ledger, statement, partner WhatsApp and value strip showing deductions; WhatsApp v3 tools.
Out (later items): GST on subcontract bills (NXT-21, own plan); the final account / closing view (NXT-22); deductions
on supplier (non-subcontract) bills; returns of unused material back to the store beyond the existing
`RETURN_IN` movement.

## 3. Business value

- The most common leak after over-billing: cement and steel given to a team and used beyond the norm, never recovered.
  A 10% overuse of 400 bags of cement at ₹400 is ₹16,000 on one slab.
- Everything taken off a bill has a reason, a person and a date; the subcontractor sees the same reason on WhatsApp,
  so fewer disputes.
- Sales: a second rupee figure in the green box ("Material over-use recovered"), next to over-billing caught.

## 4. Existing architecture reused (investigation)

| Need | Already there | Use |
|---|---|---|
| Money split of a bill | `subcontracts/rules.py` `deductions()` (retention, advance, TDS → net), the one rule | Extend with `other`: a list of deductions; net = gross − retention − advance − TDS − deductions |
| Bill check shown before save | `POST /subcontracts/work-orders/{id}/bills/check`, the bill dialog's red box | The material check adds a suggested deduction to the same response and dialog |
| Stock leaving the store | `material_usage` outflows, `POST /materials/outflows` (reasons `CONSUMED`, `WASTAGE`, `TRANSFER_OUT`…) | An issue to a team is a normal outflow with a new nullable `work_order_id`; stock and site cost stay as today |
| Work measured | `work_order_measurements` (confirmed) | "Should have used" = measured to date × norm |
| Supplier ledger, statement, partner | `vendors/ledger.py` read model, `GET /subcontracts/vendors/{id}/statement`, `/partner/statement` | A deduction is a ledger line that lowers what is owed; statement and partner read the same store |
| Value strip | `GET /subcontracts/value`, `rules.caught` | New figure `recovered` (deductions), material part shown separately |
| WhatsApp | v3 `ALLOWED` in `agent_api/tools.py`, `SOP.md` | Two writes (wait for Save) and one read; SOP rules |

No new pipeline, no parallel "payable" rule, no second stock movement kind.

## 5. Database work (additive, one migration, number taken at the time; head today 0520)

| Table / column | Purpose |
|---|---|
| `work_order_bill_deductions` (id, org, bill_id, kind `material` / `rework` / `damage` / `delay` / `bought_for_them` / `other`, amount, reason, material_id null, quantity null, source `check` / `person`, created_by, created_at, removed_by/at/reason null) | Each amount taken off a bill. Soft-removed, never deleted (audit) |
| `work_order_materials` (id, org, work_order_id, line_id null, material_id, unit_id, norm_per_unit, wastage_pct, recovery_rate, notes) | What the builder gives for this work: e.g. Cement, 8 bags per cum of Concreting M20, 3% wastage, recovered at ₹420 a bag |
| `material_usage.work_order_id` null (FK, indexed; RLS as 0484) | This outflow was given to that team |

Downgrade refuses when deductions exist (would lose recorded money).

## 6. API work

- `POST /subcontracts/bills/{id}/deductions` (kind, amount, reason; money roles, D-S3 approvers) ·
  `DELETE /subcontracts/deductions/{id}` (reason required; soft) · bill responses carry `deductions[]` and the new net.
- `PUT /subcontracts/work-orders/{id}/materials` (the agreed list) · `GET /subcontracts/work-orders/{id}/materials`
  → per material: given, should have used, allowance, excess, already recovered, to recover now.
- `POST /materials/outflows` accepts `work_order_id` (checked: same project/site, issued work order).
- `bills/check` and `POST .../bills`: the response adds `suggested_deductions` (material excess × recovery rate, less
  what earlier bills already recovered); saved with the bill unless the person removes it with a reason.
- Payment caps (`store.payable_caps`), ledger, statement, partner statement and `/subcontracts/value` read deductions.
- WhatsApp v3: `give_material_to_team` (outflow with `work_order_id`), `deduct_from_subcontract_bill`,
  `work_order_materials` (read). SOP: "50 bags cement given to Ravi's team" is an outflow to the work order, never a
  consumption at the site; a deduction always has the reason the person gave.

## 7. Frontend work

- Bill dialog: suggested deductions listed in the money row ("− ₹4,200 cement over-use: 10 bags over the allowance"),
  each removable with a reason; "Add deduction" for the manual kinds.
- Work order page: **Materials** tab (agreed materials; given · should have used · allowance · excess · recovered),
  "Give material" dialog (reuses the outflow dialog with the work order filled in).
- Bills tab / statement / partner chat: each deduction with its reason.
- Value strip: a "Material over-use recovered" cell; biggest catches include deductions.

## 8. Risks

| Risk | Mitigation |
|---|---|
| A wrong norm recovers money the team doesn't owe | Norm per work order, set by the builder and shown on the work order the team signed; the suggestion is shown before save and can be removed with a reason |
| Stock counted twice (issue + consumption) | The issue is the outflow; the team's use is not recorded again. SOP rule + test |
| TDS base changes the tax figure | Decision D-M2 before build; one rule in `deductions()` |
| Materials module touched | One nullable column and one optional field on an existing route; existing callers unchanged; stated in the report |
| Payable falls below zero | Deductions capped at what is left after retention/advance/TDS; the rest carries to the next bill, shown |

## 9. Testing, rollback, isolation, success

- **Tests:** unit tests for the reconciliation rule (given, norm, wastage, already recovered, partial measurement,
  zero measured) and the net with deductions; contract tests on Postgres for every route, tenant isolation, roles
  (only money roles deduct), the ledger closing figure, payment caps, partner statement shows deductions and nothing
  else; v3 tests in `tests/agent_api/` (issue words → outflow with work order; deduction keeps the reason; guard:
  "50 bags cement used at Block A" stays a consumption); dashboard tsc, oxlint, build; a browser check.
- **Rollback:** revert the commits; migration downgrade refuses only if deductions were recorded.
- **Labour isolation:** Labour, Attendance, Payroll and Workforce are not touched.
- **Success:** issuing 410 bags for 50 cum at 8 bags + 3% (412 allowed) suggests nothing; 450 bags suggests
  38 × ₹420 = ₹15,960 on the next bill; a manual "rework ₹5,000" lowers the net, the ledger, the statement and the
  partner's answer by ₹5,000, with its reason everywhere.

## 10. Decisions needed before build

| # | Question | Proposed |
|---|---|---|
| D-M1 | Who may add or remove a deduction | The bill approvers (D-S3: owner, admin, finance, the project's PM) |
| D-M2 | TDS on the bill before or after deductions | Before (on the bill amount), like today; the accountant can change it per company later |
| D-M3 | Standard norms offered (e.g. cement per cum of M20) | Offer a short editable list of common norms as suggestions only; the work order's own figure always wins |
| D-M4 | Recovery rate default | The material's last purchase rate at that site, editable per work order |

## 11. Phases

1. **M1 deductions (NXT-19):** table, rule, routes, bill dialog, ledger/statement/partner, value strip, v3 tool. S.
2. **M2 materials on the work order (NXT-20):** agreed list, issue with `work_order_id`, Materials tab, v3 tools. M.
3. **M3 material check on the bill:** suggested deduction in check + save, recovered-to-date, value strip cell. S.
4. **M4 demo and training:** demo company gets cement given to Ravi's team; the training video gets a chapter.
