# Procurement and materials by category: plan for the builder client (Nov 2026)

> **Status:** plan written 5 Nov 2026; tracker items `PRC-00`..`PRC-20` in [V1_TRACKER.md](V1_TRACKER.md).
> **Cost control (6 Nov 2026):** a second builder (GM meeting) asked for these and for budget vs actual; see [cost-control-plan.md](cost-control-plan.md) (tracker CC) for the build order across both.
> **Built:** PRC-01 (categories) and PRC-03 (standard list), 5 Nov 2026 — see §4a. Mockups (sample data): https://claude.ai/artifact/KF8avukxwaXK4Wr7Dq9BXR
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

### 4a. As built: categories (PRC-01, PRC-03)

- Two levels only. A main category has no parent; a sub-category's parent is a main category (the API refuses
  a third level: sizes and types such as "2-way" or "20 mm" stay separate materials).
- Names are unique per parent, ignoring case and spaces; "Pipes & fittings" can sit under Fire protection and
  under Gas.
- A material points at one category, main or sub (`materials_catalog.category_id`). Totals for a main category
  include its sub-categories (the dashboard adds them up).
- A category holding materials or sub-categories is switched off, never deleted; its materials keep it, and it is
  no longer offered for new ones.
- Placing existing materials (D5 default): by starter name ("PVC Pipe" → Plumbing & CP › Pipes) or by an exact old
  group ("Masonry" → Structural › Masonry). Nothing else is guessed.
- Migration 0503's index on `category_id` is named `ix_materials_catalog_category_id`: migration 0180 already owns
  `ix_materials_catalog_category` (on the old text column).

### 4b. As built: category for new items (PRC-02, PRC-02b)

- **The model first** (it reads the whole name: "Stainless steel sink" is Plumbing & CP › Sanitaryware, not steel):
  `add_material` / `update_material` carry `category` in words ("Plumbing & CP > Pipes"); `read_hint` takes main ›
  sub, or a name only one category has.
- **Then the name alone, strictly** (`suggest_path`): sizes and numbers aside, the name IS a starter material
  ("Cement", "PVC Pipes 4 inch") or every word is a word of exactly one category ("MCB 32A"). A known word inside a
  longer name places nothing ("Sand paper", "Cement paint", "Steel door" were wrong before PRC-02b).
- Both through `GET /materials/categories/suggest?name&hint` (`categories.suggest`, one decision for the dashboard
  and the assistant). Only the company's own switched-on categories; a sub the company removed falls back to its
  main; never creates one.
- Not theirs: the model gets the company's own list once (renamed / added categories are only there) and answers
  one of them or "none"; after that, held without a category (no third round). No categories at all: never asked.
- The card line shows "📂 Main › Sub". A waiting material that is renamed gets its category again; a category
  switched off before Save: the material saves without it (never refused with the delivery waiting on it).
- "Put it in Plumbing" on a listed material: `update_material` with `category` in words moves it.
- Not built: prefilling the dashboard's picker with the suggestion.

### 4c. As built: material requests (PRC-22, 7 Nov 2026)

The first step of the process (request → order → delivery/GRN → bill → payment), designed with Ilan on 7 Nov
(the "Material Requests page" canvas: visual language, desktop, phone, new-request dialog).

- **Tables (migration 0509, additive):** `material_requests` (REQ-0001 numbering per company, project, site, who
  asked, `source` dashboard / whatsapp, `needed_by`, `purpose`, `status`, `raised_over_duplicate`, the decision and
  who made it) and `material_request_lines` (material, quantity in its stock unit, `said` when asked in another
  unit). Row-level security as every company table.
- **Statuses:** waiting → ordered | sent (from another site) | rejected (reason required) | cancelled (by the person
  who asked, while waiting); ordered | sent → done. A purchase order (PRC-06) will point at the request later;
  until then "ordered" carries the supplier as a note.
- **Routes** (`domains/procurement/router.py`, Materials module): `GET /procurement/requests` (status, project,
  site, requested_by, category_id, urgency, mine; counts for the tiles), `GET /{id}`, `POST` (several `lines`, or
  one item as `material_id` + `quantity` + `unit_id`, the WhatsApp form), `POST /{id}/decide`, `POST /{id}/cancel`.
- **What a line shows** (`domains/procurement/requests.py`, one place for the dashboard and the assistant): stock at
  the site (the ledger), already on its way (other ordered / sent requests for the same site and material, or this
  one once ordered), still to buy, other sites holding some (within what the caller can see), the last rate (SEC-01
  roles only), and open requests in the same project for the same material (the duplicate warning, D2's default).
- **Who acts:** anyone in the project asks; admin, owner, super admin and project manager decide
  (`may_act_on_material_requests`, the default until PRC-12). The person who asked is told on WhatsApp (the
  notification queue, `material_request_update`).
- **Dashboard:** Materials > Requests (`/materials/requests`): attention tiles (waiting, late, due in 2 days,
  duplicates), status tabs, filter dropdowns with the row cues (project colour, avatar, category icon, urgency dot,
  counts), rows with the cover bar (here / ordered / hazard-striped to buy), the detail panel (a sheet on a phone),
  the new-request dialog (several items, stock hint per line, needed-by chips, the duplicate warning before saving).
  Materials is now a sidebar group (Stock, Movements, Items, Requests) like Finance.
- **WhatsApp (v3):** `material_requests`, `ask_for_material` (one material per request, source fixed to whatsapp),
  `decide_material_request`, `cancel_material_request`; an SOP rule: a need is a request, never a receipt.
- **Since built:** a request turns into a purchase order (4d); "Mark received" does not add stock (the
  delivery is still recorded in Materials; PRC-08 links the two); BOQ quantity left per line (the BOQ holds work
  items, not materials, today); a reminder when a request waits too long; comments on a request.

### 4d. As built: purchase orders (PRC-06, PRC-07, PRC-08 part, PRC-10, 7 Nov 2026)

- **Tables (migration 0511, additive):** `purchase_orders`, `purchase_order_lines` (a line may cover a request line),
  `material_receipts.purchase_order_line_id`. Received and still to come are read from deliveries (one taken back
  no longer counts); only open / closed / cancelled is stored.
- **Routes** (`domains/procurement/orders_router.py`): list, one, create (duplicate check, D2's default), edit,
  cancel, close short, receive (records the deliveries through the Materials delivery path).
- **Loop:** request → Create order (filled with what is still to buy) → request ordered, engineer told → Material
  came (part or all) → stock up → request received, engineer told.
- **Not built:** WhatsApp tools for orders (PRC-09); suggesting the open line when a delivery is recorded elsewhere (since built, PRC-23 / 4f);
  GRN details (challan photo, rejected quantity); sending the PO to the supplier (PDF / WhatsApp); bills matched to
  orders (PRC-11).

### 4f. As built: requests and orders agree (PRC-23, 7 Nov 2026)

Fixes 4e A1–A5, B6, B9 and C13. No migration (reads `purchase_order_lines.request_line_id` and
`material_receipts.purchase_order_line_id`, both from 0511).

- **On order** (`requests.describe`): what is still to come on open order lines at the site (an order placed without a
  request counts; a closed or received one no longer does), plus requests ordered by hand or sent from another site
  that no order covers. A closed-short order leaves its shortfall "to buy" again.
- **A request follows its orders, in one place** (`orders_router.requests_follow`, called on create, edit, receive,
  cancel, close and every delivery put on or taken off an order): ordered while anything is still to come; received
  when what came is what was asked (or every order for it came in full: an order can be for less than asked when some
  was at the site); otherwise waiting again, the asker told on WhatsApp ("↩️ Not coming yet … PO-0003 closed short:
  reason; still to order: 10 bags Cement"). A request ordered by hand or sent, with no order ever behind it, is left alone.
- **Hand decisions** (`decide`) are refused while an open order covers the request (`follows_order`, `may_decide`); the
  dashboard hides Mark received / Sent / Not ordering then and says it moves with PO-0003.
- **A request shows its orders** (`orders`: ref, supplier, status, received of ordered per line; cancelled ones dimmed),
  each linking to Procurement › Purchase orders.
- **Duplicate checks see each other:** a new request is warned of an open order still bringing the material
  ("Already on order … still to come on PO-0001 from Malabar"); a new order is warned of a waiting request it does not
  cover ("Arun asked for 100 bags … for Block A (REQ-0001, waiting). Order it from the request so they are told."). Both
  the existing 409 `possible_duplicate`, confirmed the same way.
- **A delivery recorded anywhere meets its order** (`record_inflow` → `match_delivery`): exactly one open line at the
  site for the material, the quantity within what is still to come, and no other supplier named → it fills that line
  (the code decides; the result says `order`, the dashboard dialog and the WhatsApp saved line say "📦 On PO-0003
  (Malabar): 150 of 160 bags came"). Otherwise nothing is linked and the open lines are offered (`open_orders`):
  the dashboard dialog asks "Is it from one of these orders?", WhatsApp's saved line lists them and "it's PO-0003" is
  the `delivery_order` tool. `no_order` says it is from no order. Opening stock, adjustments and the Excel import never match.
- **Put on / taken off later:** `POST /procurement/orders/deliveries/{receipt_id}/order` (`line_id`, or `order` as said,
  "PO-0003"; null = not this order). Stock never changes. An open order's panel lists "Came here, on no order"
  (deliveries at its site of its materials since it was placed) with "Count on PO-0003", and each delivery on it has
  "Not this order".
- **More than ordered is asked:** receiving, filling a line from Materials, or putting a delivery on a line with more
  than the line still has to come is a 409 `more_than_ordered` ("PO-0001 has 160 bags … still to come; this is 170. Is
  the extra 10 bags meant to come?") unless `confirm_extra`; the dashboard asks "Yes, the extra came".
- **Not built here:** a page link for `delivery_order` on WhatsApp (the saved line names the order); unlinking a
  delivery from a closed order (refused: its deliveries stay); notifications are de-duplicated per request and status,
  so a request that waits again a second time for another reason is not told twice.

### 4g. Both ways: through Mesiri, or done outside and told quickly (decided 7 Nov 2026)

Some companies will run every step through Mesiri; others will phone the vendor, take quotes on paper and only tell
Mesiri afterwards; most will mix the two. Both are first-class ([DECISIONS.md](../DECISIONS.md), 7 Nov). The rules for
every procurement item from here on:

1. **Every step is optional.** No step needs the one before it in Mesiri: an order without a request, a delivery
   without an order, a bill without a delivery. Mesiri links them when it can, offers when unsure, never refuses.
2. **Done outside = one tap or one line.** "Ordered 200 cement from Malabar by phone" is one WhatsApp line or one
   button, not the full order form. Rate, date, supplier and their own reference are filled when said, never required
   beyond what makes the record true.
3. **Their numbers count.** A paper PO, a quote or a Tally voucher has its own number; it is kept beside Mesiri's
   (PO-0003) and searchable, never replaced.
4. **Mesiri never pretends.** Sending the PO to the supplier (PRC-26) is a choice per order; an order recorded after a
   phone call is never shown as "sent by Mesiri".
5. **Nothing waits on Mesiri.** A request is never stuck because its order was handled outside: there is always a
   one-step way to say "bought outside / came / not needed".

**Checked against what is built (7 Nov):**

| Step | Through Mesiri | Done outside: how fast is telling Mesiri? |
|---|---|---|
| Request | Dashboard, WhatsApp | Not needed: orders and deliveries work without one ✓ |
| Quote | Not built | Nothing depends on it ✓ (any quote feature must stay optional) |
| Order | Order form, from a request | Request › "Ordered outside Mesiri? Mark it ordered" (one tap + note) ✓. **Gap:** no place for their own PO / quote number; no WhatsApp line for "ordered X from Y" (office) until PRC-09 |
| Sending the PO | Not built (PRC-26) | Mesiri never claims it was sent ✓; PRC-26 must be optional per order |
| Delivery | "Material came" on the order | Any delivery in Materials or on WhatsApp, no order needed; fills its order when plain (PRC-23) ✓ |
| More than ordered | Asked | Never blocks a delivery recorded without an order ✓ |
| Request covered by an order, rest bought outside | — | **Two steps today:** close the order short, then mark the request. Make it one ("Rest bought outside") — PRC-30 |
| Bill | Bills in Materials | Unbilled lists (PRC-11) must accept "bill handled outside" |

### 4e. Gaps found in the request ↔ order review (7 Nov 2026)

Checked against the code after PRC-22 and PRC-06/07/08/10 went live. Each has a tracker row (PRC-23 to PRC-29) or
points at the one it belongs to.

**A. Wrong numbers or stuck states (PRC-23, fix first)**
1. A request's "already ordered" counts other requests marked ordered, not open purchase order lines: cement ordered
   without a request still shows "to buy". On order must come from open PO lines (what is still to come).
2. A delivery recorded in Materials or on WhatsApp is not linked to an open order for the same site and material:
   the order and its request stay "to come" while the stock already arrived (a second order can follow). Ask
   "is this PO-0003?" and fill the line (the rest of PRC-08).
3. Closing an order short leaves its request "ordered" forever: it should wait again for the rest, or be received.
4. Cancelling an order puts its request back to waiting without telling the engineer.
5. A request's manual "Mark received" still works when an order is linked, and can disagree with it.

**B. The link is not visible or flexible enough**
6. A request does not show its order(s) ("PO-0003 · 150 of 160 came") or link to them (PRC-23).
7. A request cannot be split between suppliers: its lines cannot be taken off the filled-in order (PRC-24).
8. Several requests cannot go into one order (PRC-24).
9. The duplicate checks do not see each other: a new request does not say "already on order", a new order does
   not say "Arun asked for this" (PRC-23).

**C. Missing pieces people will expect**
10. The office is not told of a new request (a WhatsApp request only shows on the dashboard) (PRC-25).
11. No reminder for a request waiting too long or an order that is late (PRC-25).
12. The supplier never gets the order: no PDF, no WhatsApp to the vendor's number (PRC-26).
13. More delivered than ordered is accepted with a small "extra" only; it should be asked (PRC-23).
14. Requests and orders on WhatsApp ("order 200 cement from Malabar", "what is still to come?") (PRC-09).
15. Materials › Stock has no "on order" column, and "running low" ignores what is coming (PRC-27).
16. Finance cannot place orders; only admin, owner and project manager (PRC-12, Alan's decision D1).
17. Changes to an order (date moved, supplier changed) are not in its history (PRC-28).

**D. Planned, listed so nothing is forgotten**
GRN details (challan photo, rejected quantity) (PRC-29), bills matched to orders (PRC-11), rate history and GST
(PRC-14/16), payables, order approval above an amount (D4), PO numbering by financial year (PO/25-26/0001).

**Order of work:** PRC-23 (A, 6, 9, 13; built, see 4f), then PRC-24, PRC-25, then PRC-09.

---

## 5. API work (each route used by the dashboard and, where useful, the assistant)

| Route | Module | Notes |
|---|---|---|
| `GET/POST/PATCH /materials/categories` | Materials | Tree; rename; deactivate (never delete if used) |
| `GET /materials/categories/suggest?name&hint` | Materials | PRC-02 (built): a new material's category, the name against the standard list first, then a hint in words; only the company's own switched-on categories |
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
