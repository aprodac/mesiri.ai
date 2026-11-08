# Project end: from "work is nearly done" to "project closed" (Nov 2026)

> **Status:** planned 8 Nov 2026; first round built the same day (END-01..END-03, END-05, END-06: `254731a`,
> `3c1453f`, `e6bc0d7`, `c5ae533`). Asked in session ("modules that are
> pending, and the modules that are needed at the end of a project for the users"). The start of a project is
> [project-start-plan.md](project-start-plan.md), whose last line said "the ending (billing, handover, closeout,
> defect period) is the next plan". Tracker items `END-01`..`END-14` in [V1_TRACKER.md](V1_TRACKER.md).

---

## 1. The problem, in the contractor's words

| Who | Says today | What it costs them |
|---|---|---|
| **Owner / MD** | "The client still owes us something on RA-4 and the retention. I'll ask the accountant." | Money stuck at the end of a job is the margin. Retention (5% of everything billed) is often forgotten for a year, and sometimes never collected |
| **Project manager** | "The client's list of defects is on a paper they gave us at the walk-round." | Snags get fixed twice or not at all. Handover slips, the client withholds payment, and the defect period starts late |
| **Site engineer** | "Sir said the bedroom tiles. Which bedroom?" | Rework without a record; nobody can show what was fixed and when |
| **Accounts** | "Has the client paid RA-3 in full? What is the TDS on it?" | Receivables live in a bank statement and memory; nobody chases the oldest bill first |
| **Client** | "When will you fix the leak? I told your engineer twice." | The relationship and the retention suffer in the defect period |

**Mesiri's answer:** the end of a project is a checklist read from what Mesiri already holds. The BOQ says how
much work is done, the bills say what is billed, the snag list says what is still wrong, payments say what the
client still owes, and the contract says when retention falls due. **Nothing is typed twice:** the site reports a
snag on WhatsApp as they walk the rooms, accounts says "client paid 6 lakh for RA-3", and the page works out
the rest.

## 2. What the "end" of a project contains

| Stage | Module | Status |
|---|---|---|
| Finishing | **Snag list**: defects to put right, room by room, open → fixed → closed by the PM; from WhatsApp | **END-01, END-05: built** |
| Getting paid | **Payments received and receivables**: against a bill, advance, retention; what each client owes, oldest first | **END-02, END-06: built** (was NXT-03) |
| Handover | **Handover checklist**: work done, snags, subcontractors, final bill, client paid, handover day, defect period, retention | **END-03: built** |
| Extra work | **Variations**: work outside the BOQ, approved by the client, billed like a BOQ line | END-04 (was NXT-04) |
| Defect period | **Defect liability period**: runs from the handover day for the contract's months; client complaints are snags in the `defects` phase | END-03 (dates, counts: built); END-07 reminders |
| Retention back | **Retention reminder**: "₹1.2 L retention due from Mr. Thomas on 15 Jan" to owner / finance; a retention bill | END-07 |
| Subcontractors | **Final account of a work order** (agreed, measured, billed, deducted, held, paid, due) and their retention released after their defect days | END-08 (was NXT-22; waits for NXT-19) |
| Leftovers | **Leftover stock and returnables**: what is still on the site's books (cement, steel, shuttering) moved to another site, returned to the supplier or written off | END-09 (reuses BE-32 transfers, NXT-14 returnables) |
| Papers | **Handover pack**: as-built drawings, warranties, test reports, room photos for the client | END-10 (was DOC-07; waits for DOC-01) |
| Numbers | **Closeout report**: BOQ planned vs done, budget vs actual by cost centre, material reconciliation, supplier and client balances, profit | END-11 (was CC-14; waits for CC-07, CC-08) |
| Closing | **Close the project**: stage `closed` only when the checklist is clear (or with a reason); WhatsApp stops asking its team for DPRs | END-12 |
| Client side | **Snag photos** before / after, and a link the client opens to see their defects and their status | END-13, END-14 |

## 3. Investigation (Phase 1, `main` at `bb0bf88`)

| Area | Exists | Reuse |
|---|---|---|
| Project stage | `projects.stage` (0522: tender → won → running → handover → defects → closed), `PATCH /projects/{id}/start` | The handover day moves the stage to `defects`; the snag's phase is read from the stage |
| Contract | `project_contracts.defect_liability_months`, `mobilisation_advance`, `retention_pct` (0522, NXT-01) | Defect period end = handover day + months; advance to receive |
| Bills | `ra_bills` (0525): `net`, `retention`, `certified_amount`, status | What is due per bill; retention held = sum of retention on submitted bills |
| Measured work | `boq_router.done_by_line` (CC-04), `bills.previous_by_line` | "Final bill" step: priced lines with measured work not on a bill |
| Schedule | `schedule.store.load` summary `progress` | "Work done" step |
| Subcontracts | `work_orders.status`, `work_order_bills.check_status` (0519) | "Subcontractors settled" step |
| Places | `location_nodes` (0410) has no API yet (LP-01) | A snag's place is words for now; `location_id` is added when LP-01 lands |
| Photos | `progress_attachments` (activities) | Snag photos later (END-13), not a second photo store |
| Money roles | `may_manage_money` (D-N3 default: owner, admin, finance) | Payments, receivables and the checklist's money steps |
| Module map | Snag list, Payments received, Receivables, Closeout report: `planned` | Become built pages |
| Assistant | v3: route + `ALLOWED` + SOP rule | Snags and payments on WhatsApp are four routes on `ALLOWED` and rule 17 |

## 4. Implementation plan (Phase 2, first round)

**Objective.** A contractor finishing a job can list what is still wrong, see what the client still owes, and see
in one page what stands between today and a closed project.

**Scope (this round).** END-01 snag list, END-02 payments received and receivables, END-03 handover checklist,
END-05 snags on WhatsApp, END-06 "client paid" on WhatsApp. **Not in scope:** variations, retention reminders,
final accounts, leftover stock, handover pack, closeout report, snag photos (END-04, END-07..END-14).

**Business value.** Retention and the last bill are the contractor's profit on most jobs; the snag list is what
the client judges them on.

**Database (migration 0526, additive).** `projects.handed_over_on`; `project_snags` (numbered SN-001 per project,
place in words, trade, optional subcontractor, found by us / client, phase before handover / defects, status
open / fixed / closed, due day, fix note, reopen reason); `client_payments` (kind bill / advance / retention /
other, the bill when kind is bill (a check constraint), day, amount, mode, reference). Tenant RLS like 0525.
A payment holds its bill (`ON DELETE RESTRICT`), and a bill with payments can't be withdrawn. Downgrade refuses
while rows exist.

**API.**

| Route | Who |
|---|---|
| `GET /snags?project_id=&status=&site_id=` (status `pending` = not closed) | anyone on the project |
| `POST /projects/{id}/snags`, `PATCH /snags/{id}`, `POST /snags/{id}/fixed` | anyone on the project |
| `POST /snags/{id}/close`, `/reopen` (reason), `DELETE /snags/{id}` (open only) | owner, admin, finance, PM |
| `GET /projects/{id}/handover`, `PATCH` (handover day; moves the stage to defects) | read: on the project; set: owner, admin, finance, PM |
| `GET /billing/receivables`, `GET /billing/payments`, `POST /projects/{id}/client-payments`, `DELETE /billing/payments/{id}` | owner, admin, finance (D-N3 default) |

**Money rules** (`domains/billing/receivables.py`, pure). A bill's due amount is the certified amount once
certified, else the net worked out at submit. Outstanding = due − payments on it. A payment never takes a bill
below zero, never releases more retention than is held, and never takes more advance than the contract's advance
still to come (when the contract has one). A payment that names no bill goes on the only bill still owed, or asks
which. The bill can be said as people say it ("RA-03", "3").

**Dashboard.** Site › Snag list (`/site/snags`), Client billing › Payments received (`/billing/receipts`, with
receivables), Planning › Handover (`/planning/handover`). Module map entries become built; Receivables
(`/accounts/receivables`) points to the same page.

**WhatsApp (v3).** `snags`, `raise_snag`, `snag_fixed` (anyone on the project), `client_payment` (money roles; the
API refuses others). SOP rule 17.

**Risks.** (1) Who sees client money is still decision D-N3 (default used, as for NXT-01/02). (2) A place in words
can't yet be grouped by floor (LP-01 adds `location_id`). (3) Receivables are worked out on every read: fine for a
contractor's tens of bills; a cache is not needed now. (4) A payment against a bill that is later re-certified
lower can leave it over-paid: the receivables list shows a negative outstanding on that bill (it is not added to
the total owed).

**Testing.** Unit (`tests/unit/test_project_end.py`: money worked example, months arithmetic, checklist steps per
role), contract (`tests/contract/test_project_end_contract.py` on a live Postgres: snag lifecycle and roles,
handover and the defect phase, payments and their refusals, certified amount, handover checklist), v3
(`tests/agent_api/test_api_project_end.py`: the four tools are the dashboard's routes; snag saves are held for
Save; the SOP rule).

**Rollback.** Revert the commits; `alembic downgrade 0525` (refuses while snags or payments exist: export first).
The new routes and pages are additive; nothing existing changes behaviour except that a bill with payments can no
longer be withdrawn.

**Labour isolation.** Nothing in Labour, Attendance, Workforce or Payroll is touched.

**Success criteria.** A project's snags can be raised from WhatsApp and closed on the dashboard; "client paid 6
lakh for RA-3" records a payment and answers what is still owed; the handover page shows the next step.

## 5. Decisions

| # | Question | Default used |
|---|---|---|
| D-E1 | Who closes a snag: the PM only, or also the engineer who fixed it? | Owner, admin, finance, PM (the person who fixed it does not check their own work) |
| D-E2 | Does the client see snags (client link)? | Not yet (END-14) |
| D-E3 | Who sees client payments and receivables (D-N3) | Owner, admin, finance |
| D-E4 | Can a project close with open snags? | Yes, but the checklist shows it is not ready (END-12 will ask for a reason) |
