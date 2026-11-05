# Procurement and materials by category: plan for the builder client (Nov 2026)

> **Status:** Phase 2 plan, written 5 Nov 2026, waiting for review. Not started. Tracker items
> `PRC-00`..`PRC-20` go into [V1_TRACKER.md](V1_TRACKER.md) once the plan is agreed. Mockups (sample data): https://claude.ai/artifact/KF8avukxwaXK4Wr7Dq9BXR
>
> **Source:** the sales meeting with a builder (onboarding through Riyas, ₹4,000/month plus onboarding fee,
> 1–2 weeks to go live). The builder does whole projects, structure to finishing, with 4–5 engineers per site
> and several projects running at once.

---

## 1. What the client asked for, and what he will expect without saying it

| # | He said | What he will expect once it exists (unsaid) |
|---|---|---|
| A | Every item sits under a **main category** (Structural, Electrical, Plumbing, Fire, Gas, Lift…), with sub-categories (Switches, Pipes, CP fittings) and sizes/types (1-module, 2-way, 20 mm, 1 inch) | Totals per category, per project and for the company. New items land in the right category without him sorting them. His own item list loaded on day one. |
| B | **What was bought, at what price**; compare two shops, compare across dates | The rate shows when someone orders ("₹14 more than last time"). Rates compare per the same unit, with GST handled the same way. Rates come from the bill without anyone typing them. |
| C | **Who ordered it**, which vendor, who reported it from site | Orders can be changed or cancelled. One order can hold several items. A delivery can come in parts. Each order shows when it is due and whether it is late. |
| D | **Material came, no bill yet**: accounts must trace it | A "delivered, not billed" list, with reminders to the person who ordered. Bill photo → matched to the delivery. Bill and delivery that disagree (quantity or rate) are flagged. Paid / unpaid per bill. |
| E | **Duplicate orders**: warn when the same item was ordered today | The warning names who ordered, how much, from whom. "Yes, order anyway" is recorded. The first orderer is told. |
| F | **Weekly and monthly reports** | PDF with letterhead, sent to his WhatsApp on a schedule; Excel for accounts. |
| G | **Petty cash separate from direct project expenses** | Each total shown both ways in every report. |
| H | **Stock at a glance from anywhere**: previous stock, used, balance | Per site and all sites, per category. Running-low warnings. What is on order but not yet here. |
| I | Many projects at once | Every list filters by project; one company-wide view. |

Things the system needs underneath so the above works (supporting work):

- **Vendors become real records**: deliveries store the shop as free text, so "compare shops" cannot work
  until each delivery points at a vendor. Vendors also need phone and GSTIN.
- **Item identity is exact**: a rate comparison is only as good as "same item". Sizes/types must be
  separate items (they already are: one catalog row per variant, per
  [units-and-sizes.md](../architecture/units-and-sizes.md)); the category tree only groups them.
- **Onboarding import**: item list by category, vendors, opening stock per site, users and roles, from Excel.
- **Permissions**: who may order, who may confirm a duplicate, who sees rates and bills.
- **WhatsApp templates** (Meta-approved) for messages sent outside the 24-hour window: bill reminders,
  "Arun also needed cement", the weekly report.
- **Three languages** for every new message: English, Manglish, Malayalam (the existing text catalogue).
- **[202]** must be fixed first: a multi-site company is told "no recorded stock" for cement, which is this
  client's exact setup. It is in progress in another session; we depend on it, we don't take it over.

---

## 2. Investigation: what exists (Phase 1 findings)

| Area | Exists today | Reuse |
|---|---|---|
| Catalog | `materials_catalog` (name, default unit, **free-text `category`**, sku), aliases, unit conversions, size requests, starter catalog (`application/materials/starter_catalog.py`) | Keep every row; add a category link |
| Deliveries | `material_receipts`: quantity, unit, `unit_cost`, `total_cost`, **`supplier` (text)**, `created_by` (who reported), `invoice_id` | Add order-line link and vendor link |
| Usage, ledger, transfers | `material_usage`, movements ledger, transfers between sites, opening stock, reversals | Period summary reads the ledger |
| Stock | `GET /materials/inventory` (received, used, current), `/stock-check`, `/ledger/{site}/{material}` | Add a date-range summary |
| Rates | `GET /materials/last-purchase` (one price) | Generalise to history |
| Bills | `material_invoices` (+ attachments, `vendor_id`, `expense_id`), `POST /materials/invoices` | Procurement reads them; no move |
| Vendors | `vendors` (name, code, status), `/vendors` CRUD | Add phone, GSTIN, address |
| Expenses / petty cash | `expenses` with `category_id`, `vendor_id`, payment status; money accounts incl. petty cash accounts, vouchers, transfers; finance summary and statement (no date range) | Classify by paying account |
| Reports | Daily DPR PDF with letterhead (HTML → Chromium); automations `DAILY / WEEKDAYS / WEEKLY` with `SEND_DPR`, `COMPLIANCE_SUMMARY`, `REMINDER` | Add `MONTHLY` and a period report action |
| Orders | **Nothing stored.** The old assistant's `request_material` sent a "📦 Material request" message and `runtime/open_needs.py` reads it back out of chat text. v3 has no order tool. | New |
| Procurement module | `domains/procurement/` and `application/procurement/` exist, empty | Home for the new code |
| Assistant (v3) | `agent_api/tools.py` `ALLOWED` routes + `SOP.md`; Save card; text header/footer/buttons; card PNGs (`channel/cards/`) | Every feature = route + `ALLOWED` line (+ SOP rule) |
| Roles | `ADMIN`, `OWNER`, `PROJECT_MANAGER`, `SITE_ENGINEER`, `FINANCE`, `SUPER_ADMIN` | Use as is |
| DB | Migration head `0502`; tenant row-level security (`0484`) on tenant tables | New tables get RLS |

---

## 3. Objective, scope, business value

**Objective.** Give a full-project builder one place to see every material by category, every order
with who placed it, every delivery with or without its bill, every rate by shop and date, and stock and
spend per week or month, from WhatsApp and the dashboard.

**In scope.** Items A–I above and the supporting work. **Out of scope for now** (listed in §9 as Later):
purchase approval chains, budgets per category, vendor payment ledger, stock valuation, vendor portal.

**Business value.** Stops double orders (500 bags ≈ ₹1.9 L each time). Lets accounts close unbilled
deliveries without chasing engineers. Shows the owner rates paid vs cheapest. It is the core of what this
client is paying for, and the same features fit every builder customer.

**Least work for the worker.** Engineers keep typing or speaking one line in Manglish. Mesiri fills the
category, vendor, rate and order link itself; the only new tap is the duplicate warning.

---

## 4. Database work (all additive; head is `0502`, next numbers checked again before writing)

| Migration | Change |
|---|---|
| `0503_material_categories` | New `material_categories` (id, organization_id, parent_id null, name, sort_order, is_active, created/updated by/at). Unique (org, parent, lower(name)). RLS. `materials_catalog.category_id` nullable FK. The old text `category` column stays and is not rewritten. |
| `0504_vendor_details` | `vendors` + phone, gstin, address (nullable). `material_receipts.vendor_id` nullable FK (the `supplier` text stays). |
| `0505_material_orders` | New `material_orders` (id, org, project_id, site_id, order_number per company, vendor_id null, supplier_name, needed_date, status `ordered / part_delivered / delivered / cancelled`, ordered_by, source, correlation_id, notes, duplicate_of_order_id null, duplicate_confirmed_by/at, cancelled_by/at/reason, timestamps). New `material_order_lines` (id, order_id, org, material_id, quantity, unit_id, quoted_rate null). RLS on both. `material_receipts.order_line_id` nullable FK. |
| `0506_low_stock_level` | `materials_catalog.reorder_level` nullable (per material; per site later if asked). |
| `0507_automation_monthly` | Allow `MONTHLY` frequency (`day_of_month`) and action `SEND_PERIOD_REPORT`. |

A delivery's "billed" state is not stored; it is `material_receipts.invoice_id IS NOT NULL`. An order's
received quantity is the sum of its receipts, never a copy. Filling in vendor links and categories for
existing rows is a separate job that can be run again safely and fills only empty fields: nothing existing
is overwritten.

---

## 5. API work (each route used by the dashboard and, where useful, the assistant)

| Route | Module | Notes |
|---|---|---|
| `GET/POST/PATCH /materials/categories` | Materials | Tree; rename; deactivate (never delete if used) |
| `PATCH /materials/{id}` gains `category_id`, `reorder_level` | Materials | |
| `GET /materials/inventory?group=category` | Materials | Totals per category, project, company |
| `GET /materials/stock-summary?from&to&site&category` | Materials | Opening, received, used, closing, from the ledger |
| `POST /materials/import` (preview, then commit) | Materials | Excel: items + categories + opening stock |
| `GET/POST/PATCH /procurement/orders`, `POST /procurement/orders/{id}/cancel` | Procurement | Several lines per order |
| `GET /procurement/orders/duplicates-check` (also run inside POST) | Procurement | Same material, same site or project, same day or still open; returns who, how much, vendor |
| `GET /procurement/unbilled` | Procurement | Receipts with no invoice, with order and people |
| `GET /procurement/unordered` | Procurement | Deliveries matching no order (to be claimed) |
| `POST /materials/inflows` gains `order_line_id` (suggested by the code) | Materials | |
| `GET /procurement/rates?material&from&to` | Procurement | Per vendor and date, per stock unit, GST shown the same way |
| `PATCH /vendors/{id}`, `POST /vendors/import` | Vendors | Phone, GSTIN |
| `GET /reports/period?kind=weekly|monthly&project` (+ `.pdf`, `.xlsx`) | Reports | Category spend, direct vs petty cash, stock summary, orders and unbilled |

v3 assistant: new `ALLOWED` lines `place_order`, `list_orders`, `cancel_order`, `unbilled_deliveries`,
`rate_history`, `stock_summary`, `material_categories`; SOP rules for "order X" vs "X came", the duplicate
question, and "who ordered". No new workflow, router or word list.

---

## 6. Frontend work

| Screen | Change |
|---|---|
| Materials (`MaterialsPage`, `catalogue-view`, `inventory-view`) | Category tree, totals per category, size/type column, import from Excel, reorder level |
| **Orders** (new page, sidebar) | Tabs: open, delivered not billed, duplicate alerts, no order; new order dialog with several lines |
| **Rates** (new page) | Item picker, chart per shop, every purchase with bill link |
| Vendors (`VendorsPage`) | Phone, GSTIN, items supplied, last rates |
| Reports (`FinanceReportsPage` or new) | Weekly / monthly, PDF, Excel, send to WhatsApp, schedule |
| Delivery dialog (`record-inflow-dialog`) | Pick the order; vendor from list |

WhatsApp messages: order card with duplicate warning, delivery against order, stock by category, rate
comparison, who ordered, bill reminder, weekly report caption. Text first (header, body, footer, up to 3
buttons of ≤20 letters); card picture only where already used. All three languages.

---

## 7. Build order (tracker items)

| ID | Item | Size | Needs approval? |
|---|---|---|---|
| **Phase 0** | | | |
| PRC-00 | Wait on [202] (multi-site stock), verify on a multi-site test company | — | No |
| **Phase 1 — foundations** | | | |
| PRC-01 | Category tree: table, routes, catalog link, dashboard tree, totals per category | M | No |
| PRC-02 | Category for new items: suggested from the name (starter list match first, model second), shown on the Save card | S | No |
| PRC-03 | Starter category lists for a full builder (Structural, Electrical, Plumbing & CP, Fire, Gas, Lift, Finishing) | S | No |
| PRC-04 | Vendors: phone, GSTIN; `vendor_id` on deliveries; fill in from the supplier names; vendor picker | M | No |
| PRC-05 | Excel import: items + categories, vendors, opening stock (preview, then commit) | M | No |
| **Phase 2 — orders** | | | |
| PRC-06 | Orders and order lines: tables, routes, numbering, cancel, edit | L | No |
| PRC-07 | Duplicate-order check and confirmation, first orderer told | S | No |
| PRC-08 | Delivery against order: code suggests the open order line; part deliveries; "not this order" | M | No |
| PRC-09 | v3 tools + SOP: place, list, cancel orders; "who ordered X"; all three languages | M | No |
| PRC-10 | Orders page on the dashboard | M | No |
| PRC-11 | Not-billed and no-order lists; bill reminder to whoever ordered; bill photo matched to deliveries; quantity/rate mismatch flag | M | No |
| PRC-12 | Who may order, confirm duplicates, see rates and bills | S | **Yes: permissions** |
| PRC-13 | Meta templates for bill reminder, duplicate notice, period report | S | **Ops task** |
| **Phase 3 — rates** | | | |
| PRC-14 | Rate history route, per stock unit, GST shown the same way | M | No |
| PRC-15 | Rate on the order card ("₹14 more than last time at Malabar Pipes") | S | No |
| PRC-16 | Rates page; vendor page shows last rates | M | No |
| **Phase 4 — stock and reports** | | | |
| PRC-17 | Stock summary for a period, per category, per site / all sites, on WhatsApp and dashboard; running low | M | No |
| PRC-18 | Direct vs petty cash in every total (by paying account, see decision D3) | S | No |
| PRC-19 | Weekly / monthly report: PDF (DPR letterhead pipeline), Excel, dashboard page | L | No |
| PRC-20 | Scheduled report on WhatsApp: `MONTHLY` frequency, `SEND_PERIOD_REPORT` action | S | No |

Onboarding for this client can start after Phase 1 (their item list, vendors, opening stock, users). Orders
(Phase 2) are what they will judge us on; Phases 3–4 follow within the same weeks.

---

## 8. Decisions needed before or during the build

| # | Question | Default if nobody answers |
|---|---|---|
| D1 | May site engineers see rates and bill amounts? | Yes for their own projects (matches SEC-01 expense view rule); hide behind a role later if asked |
| D2 | Is "duplicate" same item at the **same site**, or anywhere in the **project**, same day or still-open orders too? | Same project, same day **or** still open with an overlapping needed date |
| D3 | Petty cash vs direct: decided by the account it was paid from (petty cash account = petty cash), or by a flag on each expense? | By paying account (reuses money accounts, no new field) |
| D4 | Do orders need an approval above some amount? | No approval in this round (Later item) |
| D5 | Existing materials' free-text category: map automatically to the tree, or leave for the customer? | Map exact matches automatically; the rest shows "No category" for the customer to sort |
| D6 | Does "Call Rahul" (phone link) and "first orderer told" fit how they work, or is it noise? | Keep both, measure |

---

## 9. The procurement module map: building now, likely next, not building

**Building now:** item list by category · vendor list · material order (the engineer's request is the
order) · duplicate-order alert · due date and late orders · delivery against the order (part deliveries,
shortfall) · deliveries with no order · bill matched to deliveries, mismatch flag · not-billed list and
reminders · rate history and shop comparison · stock per category and period · direct vs petty cash ·
weekly / monthly reports (PDF, Excel, WhatsApp).

**Likely next (when he asks, each its own tracker row):** order approval above an amount · separate
request → purchase step (if a purchase person places orders for the engineers) · purchase order PDF sent to
the vendor · quotes from several shops before ordering · vendor outstanding and payments (billed, paid, owed,
credit days) · budget per category vs spend · returns to the vendor (damaged, short, wrong size) · Tally
export · vendor performance (late, short supply) · stock value (quantity × average rate) · reorder level per
site.

**Not building:** quantity take-off from the estimate (BOQ) vs used · rate contracts with vendors · vendor
portal or vendors messaging Mesiri · tenders · equipment hire and subcontractor work orders · consumption vs
theoretical (wastage / theft) checks · GST filing.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Reply time: duplicate check and rate lookup on the reply path | One indexed query each, run in parallel with the draft; card pictures stay within the existing 4 s cap or are sent without the picture |
| The model calls a delivery an order or the reverse ("cement vannu" vs "cement venam") | Code decides from the route the model picked + SOP rule + golden cases in both directions, in all three languages |
| A delivery is matched to the wrong order | Code suggests, the Save card shows the order number, "Not this order" button; never matched silently when two open orders fit |
| Stock figures change when receipts gain order links | Links never change quantities; the ledger is the only stock source; regression tests on inventory and ledger |
| Wrong vendor when filling in old deliveries from supplier names | Fill only exact or alias matches; leave the rest unlinked; can be run again |
| Migrations run on deploy | Additive only, one per item, chain checked for forks right before push |
| Bills stay in Materials while orders live in Procurement | Procurement reads `material_invoices`; one owner per table; revisit only if approvals arrive |
| Scope creep from the "Later" list | Each Later item becomes its own tracker row only when asked |

---

## 11. Testing strategy

- **Backend unit and integration tests per route**: category tree rules, duplicate check (same day, open
  order, other site, cancelled orders ignored), part deliveries, unbilled list, rates per stock unit, period
  stock summary (opening + received − used = closing, matched against the ledger), RLS on the new tables.
- **Assistant (`tests/agent_api/`)**: scripted tests for order vs delivery, the duplicate question and both
  answers, "who ordered", stock by category, rate question, each in English, Manglish and Malayalam, plus the
  guards: an ordinary delivery with no order still saves as today; "cement vannu" never becomes an order.
- **Regression**: the full backend, dashboard (`tsc`, `oxlint`, `vite build`) and WhatsApp suites before
  every push, as `CLAUDE.md` requires.
- **Live check** on a test company with two sites, after each phase: the four WhatsApp mockup conversations
  replayed for real.

## 12. Rollback strategy

Each item is its own commits on `main`. Code: revert the commits. Database: every migration has a working
`downgrade()` (drops only the new tables and columns); no existing data is rewritten, so a rollback loses
only orders and categories entered since. Dashboard pages and assistant tools are each one entry
(sidebar link, `ALLOWED` line) and can be switched off by removing it.

## 13. Labour isolation

Nothing here touches Labour, Attendance, Payroll or Workforce. Material usage keeps its `work_item` link
untouched.

## 14. Success criteria

- An engineer orders in one WhatsApp line; a second engineer ordering the same item that day is warned and
  the warning names the first order.
- Every delivery shows who ordered it, the vendor and who reported it; accounts sees every delivery without a
  bill in one list.
- The owner sees any item's rate by shop and date, and stock (opening, received, used, closing) per category
  and site, from WhatsApp, in under the current reply time.
- A monthly PDF and Excel splits direct project expenses from petty cash and spend by category.
- This client's item list, vendors and opening stock are loaded from their Excel in the onboarding week.
