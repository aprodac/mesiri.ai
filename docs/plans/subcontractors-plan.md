# Subcontractors: work orders, measurement, bill check, payments, and the subcontractor on WhatsApp

> Plan, 8 Nov 2026. **Built the same day (S1–S7, see V1_TRACKER NXT-05..07, CC-04, NXT-16..18); what was left out is listed there.** Asked in session ("what we going to start on subcontractors"; "alan approves lets do B ... make all of
> it a plan"). Tracker rows: NXT-05, CC-04, NXT-06 (with CC-06), NXT-07, NXT-16, NXT-17, NXT-18 in
> [V1_TRACKER.md](V1_TRACKER.md). Builds on the supplier ledger (CC-09/CC-10) and PRC-11 bill matching, built 8 Nov.
> Decisions: section 10.

## 1. Objective

A builder can give work to a subcontractor (concrete team, plastering crew, electrician), know how much of it was done,
check every bill against the work done and the agreed rate before paying, hold retention and recover advances, and see
what each subcontractor is owed, from the dashboard and WhatsApp. The subcontractor sees their own work orders, bills,
payments and balance on WhatsApp, sends their bill there, and nothing else of the company.

## 2. Business value

- The most common money leak on an Indian site is paying a subcontractor for more than was done ("₹15,000 to the
  concrete team: was the work done?"). The bill check answers it before the money goes.
- Retention and advances are tracked in notebooks today; disputes at the end of a job come from that.
- The subcontractor stops calling the office to ask what is pending: they ask Mesiri.
- Feeds cost control: subcontract cost per BOQ line, and measured quantities for "budget vs actual" (CC-07).

## 3. What exists and is reused (no parallel systems)

| Need | Reuse | Gap |
|---|---|---|
| The subcontractor | `vendors` with `kind = 'subcontractor'` (0516), phone, GSTIN, credit days, contact | Contacts who may message Mesiri (B) |
| What was agreed | BOQ lines `work_package_planned_items` (unit, `subcontract_rate`, `boq_code`) | Work orders |
| Work done | `activities` (`contractor` text, `work_type`, site, date) + `activity_quantities` (quantity, unit) | Link to a BOQ / work order line (CC-04) |
| Their bill | `expenses` with `vendor_id` (+ `material_invoices` pattern for "bill for these") | Work order + quantity per line on the bill, check status |
| Paying them | Supplier ledger + `POST /finance/vendors/{id}/payments` (oldest bills first, advance) | Retention, advance recovery, TDS on a bill |
| Sending documents | PO document page + WhatsApp send (PRC-26) | Work order document, statement |
| Asking a person | Notifications queue (held for the 24-hour window), v3 assistant | A second kind of WhatsApp sender (B) |
| Team on site | `labour_attendance_lines` (trade, headcount) | Optional link of a team to the subcontractor |

## 4. Scope, in phases (each pushed and reported on its own)

### Phase S1 — Work orders (NXT-05) · M
- A work order (WO-0001…): subcontractor, project, site (optional: whole project), start / end dates, retention %,
  advance agreed, notes, their reference; lines: a BOQ line (its unit and `subcontract_rate` offered) or free text with a
  unit; quantity; agreed rate; amount.
- Status: draft → issued → completed → closed (cancel from draft/issued). Edit while draft; after issue, changes are
  recorded as history (the purchase-order events pattern, PRC-28).
- Progress per line: measured / billed / remaining quantity and amount (from S2 and S3).
- Document: the PO document page reused (letterhead, lines, terms, retention, signature line) and "Send on WhatsApp"
  (opens the sender's WhatsApp with the text, as PRC-26).
- Dashboard: Procurement › Work orders (list with tiles: open, over the agreed quantity, bills to check, retention held),
  a work order page, and a Work orders tab on the subcontractor's supplier page. A subcontractor can be added with
  kind preset from here.
- WhatsApp (v3, staff): "Ravi's team: plastering 18,000 sq ft at ₹42 on Block A" prepares a work order, waits for Save.
- Advance given against a work order: the existing on-account supplier payment, tagged with the work order.

### Phase S2 — Measurement: work done counts against the agreed line (CC-04) · M
- `activity_quantities.planned_item_id` (BOQ line) and `work_order_line_id` (nullable, additive). The DPR / work
  update already records "40 m³ concreting on Block A"; the code links it to the one open line it can only be (same site,
  same work type / unit, the activity's contractor = the subcontractor). When two lines fit, the engineer is asked once
  with buttons (D-CC2: never guessed); unanswered stays "not linked".
- Measurement on a work order page: add a measurement directly (date, line, quantity, by whom, photo), for work measured
  at the end rather than reported daily (the "measurement book").
- BOQ progress route: planned / done / remaining quantity and budget per BOQ line (CC-04 as in the cost plan).
- Labour (allowed since 3 Nov, said in the report): an attendance line can name the team's subcontractor
  (`labour_attendance_lines.vendor_id`, nullable), so "whose workers were on site" is known. Wages stay out (NXT-09).

### Phase S3 — Bill check (NXT-06, extends CC-06) · M
- A subcontractor's bill: an expense with the subcontractor, linked to a work order, with quantity per line
  (`work_order_bill_lines`: line, quantity billed, rate billed). Its own status beside the expense's:
  `check_status` = waiting / passed / flagged / approved / rejected, and `submitted_by` (staff user or subcontractor
  contact, for B).
- The check (one rule, `domains/subcontracts/check.py`), per line:
  - quantity billed to date vs measured to date → over by N flagged;
  - rate billed vs agreed rate → higher flagged;
  - total billed vs the work order's amount → over flagged.
  Passed bills are payable; flagged ones wait for a person (owner / admin / finance / PM of the project) to approve with
  a reason or reject. Approve is recorded (who, when, why).
- Bills from WhatsApp ("concrete team bill 15,000 for 40 m³", or a photo): staff prepare it, the check runs on save and
  the reply says the result ("40 m³ billed, 34 m³ measured: 6 m³ over. Approve anyway?").
- Running bills (RA style): each bill states this bill's quantity; previous bills are counted from the record, so a
  second bill for the same work is caught.

### Phase S4 — Payments, retention, advance, TDS (NXT-07) · M
- On each approved bill: retention held (work order %), advance recovered (an amount or a % of the bill, never more
  than outstanding advance), TDS (decision D-S1), and net payable.
- The supplier ledger shows them as their own lines: bill (gross), retention held, advance recovered, TDS deducted,
  payments; balance = what is payable now; retention held shown apart as "held, due at completion".
- Release retention (all or part) when the work order is completed or the defect period ends: a payable line, paid as
  any other.
- Paying a subcontractor uses the existing pay flow (oldest approved bills first); unapproved bills are never paid by
  "oldest first".
- WhatsApp (staff): "paid Ravi's team 12,000", "release Ravi's retention for Block A".

### Phase S5 — The subcontractor kept informed (option A) · S
- Their statement (work orders, measured, billed, approved, retention held, advance left, paid, due): a document page and
  a PDF, built once and reused by B.
- "Send to subcontractor" on a work order, a checked bill (result and reason), a payment (amount, what it paid, what was
  held): the text written, opened in the sender's WhatsApp (as purchase orders).

### Phase S6 — The subcontractor on Mesiri's WhatsApp (option B, NXT-16) · L · approved by Alan (relayed 8 Nov)
- **Who:** contacts of a subcontractor (`vendor_contacts`: vendor, name, phone, status, invited by, invited at), added
  by owner / admin / PM from the subcontractor's page. Never a row in `users`: a contact is not company staff.
- **Isolation (deny by default):**
  - A contact's token is its own kind (`kind = "vendor_contact"`, `sub` = contact id, `vendor`, `org`). `get_auth_context`
    refuses it, so every existing route answers 401 to a contact without being changed one by one.
  - A contact can reach only `/partner/...` routes (`domains/partner/router.py`), each scoped by the token's vendor and
    company, reading through the same stores (statement, work orders, bills, payments) and returning only their fields:
    never the company's other suppliers, BOQ client / budget rates, margins, other projects' names beyond the ones on
    their work orders, staff phone numbers.
  - Row-level security already isolates companies (0484); the partner routes bind the tenant the same way.
- **On WhatsApp:** the sender is resolved as staff first, then as a contact. A contact gets the partner tool list (a
  separate `PARTNER_ALLOWED` in `agent_api/tools.py`, only `/partner/...` routes) and a short partner section of the SOP.
  They can:
  - ask "how much is pending?", "what was paid?", "show my work orders" → their statement;
  - send a bill (photo or words) → a bill on the work order, `check_status = waiting`, `submitted_by` = the contact;
    staff are told; never approved or paid by the contact;
  - report work done ("40 m³ done on Block A") → a measurement proposal waiting for the site engineer's confirmation;
    counted only once confirmed;
  - get the work order, the check result and payments sent to them by Mesiri (notifications to the contact's number).
- **Staff side:** a contact's bill or reported work shows "from Ravi (subcontractor)" and waits in the approvals list
  (NXT-08 when built; until then on the work order page and a WhatsApp note to the PM).
- **Off switch:** deactivating a contact or the subcontractor stops access at once (resolution checks status each
  message); every partner request is audited (who, what, when).
- **Language:** the reply language of the contact (English / Malayalam / Manglish / Tamil, as staff).
- No web login in this phase (option C, later if asked).

### Phase S7 — Connections · S
- Supplier page of a subcontractor: Work orders, Bills to check, Retention tabs.
- Cost (CC-01): subcontract bills counted once, by work order and BOQ line; Today: bills waiting for a check.
- DPR: work done by each subcontractor team (from S2).
- Approvals inbox (NXT-08) reads `check_status` when it is built.

## 5. Database work (all additive; one migration per phase, numbered at the time; chain checked before push)

| Phase | Tables / columns |
|---|---|
| S1 | `work_orders` (org, number, vendor_id, project_id, site_id, status, start/end, retention_pct, advance_agreed, notes, their_ref, created_by, timestamps), `work_order_lines` (work_order_id, planned_item_id null, description, unit_id, quantity, rate, sort), `work_order_events` (history); `expense_payments.work_order_id` (advance against it); RLS policies as 0484 |
| S2 | `activity_quantities.planned_item_id`, `work_order_line_id`; `work_order_measurements` (line, date, quantity, photo key, recorded_by, source, status confirmed/proposed, confirmed_by); `labour_attendance_lines.vendor_id` |
| S3 | `work_order_bills` (expense_id, work_order_id, check_status, flags json, decided_by, decided_at, reason, submitted_by_user_id / submitted_by_contact_id), `work_order_bill_lines` (bill, line, quantity, rate) |
| S4 | `work_order_bills`: retention_amount, advance_recovered, tds_rate, tds_amount, net_payable; `retention_releases` (work_order, amount, date, by); vendor `tds_rate` default |
| S6 | `vendor_contacts` (org, vendor_id, name, phone, language, status, invited_by, timestamps), `partner_audit` (contact, route, at) |

## 6. API work

- S1: `GET/POST /subcontracts/work-orders`, `GET/PATCH /subcontracts/work-orders/{id}`, `POST .../{id}/issue|complete|close|cancel`,
  `GET .../{id}/document`.
- S2: `POST/GET /subcontracts/work-orders/{id}/measurements`, `POST /progress/quantities/{id}/link`,
  `GET /projects/{id}/boq/progress`.
- S3: `POST /subcontracts/work-orders/{id}/bills`, `GET .../bills`, `POST /subcontracts/bills/{id}/approve|reject`.
- S4: `POST /subcontracts/work-orders/{id}/retention/release`; ledger lines extended; pay flow skips unapproved bills.
- S5: `GET /subcontracts/vendors/{id}/statement` (+ PDF).
- S6: `/partner/me`, `/partner/statement`, `/partner/work-orders`, `/partner/bills` (POST: waiting), `/partner/work-done`
  (POST: proposed), `/finance/vendors/{id}/contacts` (staff manage contacts).
- WhatsApp v3: staff `ALLOWED` lines for each write above (wait for Save) + SOP rules; partner `PARTNER_ALLOWED` + SOP
  section.

## 7. Frontend work

Procurement › Work orders (list, page, new/edit dialog, measurement dialog, bill dialog with the check shown before
save, approve / reject), supplier page tabs for subcontractors, retention release dialog, statement page (print / PDF),
contacts on the subcontractor's page (invite, switch off), module map entries turned built.

## 8. Risks

| Risk | Mitigation |
|---|---|
| B leaks company data to an outsider | Deny by default (a contact's token fails every existing route); partner routes return whitelisted fields; tests that call every existing route with a contact token and expect 401; audit log; off switch |
| Measurement linking guesses wrong | Code links only when one line fits; otherwise asks once; unlinked stays visible, never forced |
| A contact's bill or work counts without a check | Contact writes are always "waiting" / "proposed"; only staff approve or confirm |
| Retention / TDS rules differ per company | Per work order / per vendor, with a company default; TDS can be switched off (D-S1) |
| Two places decide "payable" | One rule: ledger + `check.py`; pay flow reads `check_status` |
| Labour module change (S2 attendance link) | Additive nullable column; Workforce / Payroll untouched; stated in the report |

## 9. Testing, rollback, isolation, success

- **Testing:** unit tests for every rule (check, retention, advance recovery, TDS, measurement linking); contract tests on
  Postgres per route with tenant and role isolation; for S6 a sweep that calls every mounted route with a contact token
  (expect 401 outside `/partner`), and partner routes with another vendor's id (expect 404); assistant tests in
  `tests/agent_api/` (staff writes wait for Save; partner tool list contains only `/partner` routes; SOP rules);
  dashboard type check, lint, build, browser checks.
- **Rollback:** every migration additive with a downgrade (refusing when it would lose recorded work orders / bills);
  each phase is its own commits, revertable alone; S6 has a company setting `partner_access` (off by default per
  company until the owner turns it on), so it can be switched off without a deploy.
- **Labour isolation:** only S2 touches Labour (one nullable column); Workforce and Payroll unchanged; wages (NXT-09)
  still blocked on Alan.
- **Success:** a bill over the measured quantity or the agreed rate is flagged before payment; retention held and
  advance left are right on the ledger; a subcontractor asking "how much is pending?" on WhatsApp gets their figure and
  cannot reach anything else (sweep test green).

## 10. Decisions

| # | Question | Decided / proposed |
|---|---|---|
| D-S0 | Subcontractor on Mesiri's WhatsApp (option B) | **Approved: Alan, relayed in session 8 Nov.** Deny-by-default design above; per-company switch, off until the owner turns it on |
| D-S1 | TDS on subcontract bills | **Approved 8 Nov (owner):** off per company until set; when on, 194C 1% individual / HUF, 2% others, per subcontractor, changeable per bill. |
| D-S2 | Retention default | **Approved 8 Nov:** 5% per work order, changeable; released on completion or after the defect period the work order states |
| D-S3 | Who approves a flagged bill | **Approved 8 Nov:** owner, admin, finance, and the project's PM (a PM within their projects) |
| D-S4 | Labour contractor teams paid by attendance | Stay in Labour; attendance can name the subcontractor (S2); wages are NXT-09 (blocked on Alan) |
| D-S5 | Web login for subcontractors (option C) | Not now |
