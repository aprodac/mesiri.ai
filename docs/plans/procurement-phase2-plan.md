# Procurement phase 2: quotations, returns, stock control, supplier performance (plan, 9 Nov 2026)

> **Status:** plan written 9 Nov 2026. Built: PRC-34 (step 0, GST on deliveries and orders), PRC-45 (Pending deliveries), PRC-40..44 (Quotations; as built: the quote's terms sit on `rfq_vendors`, no separate `quotations` table; no RFQ PDF, the WhatsApp text is the RFQ; quote photos read on WhatsApp only; no quotes-due reminder yet), PRC-47
> (Minimum stock and reorder, 10 Nov; as built: see §5.4), PRC-46 (Returns, 10 Nov), PRC-48 (Stock count) and PRC-49
> (Stock value), 10 Nov: as built in the tracker rows. Tracker items `PRC-40`..`PRC-52` in
> [V1_TRACKER.md](V1_TRACKER.md) (PRC section).
> **Follows:** [procurement-plan.md](procurement-plan.md) (PRC-00..37, built 5–9 Nov) and the gaps listed in
> [capability-framework-gap-analysis.md](capability-framework-gap-analysis.md) modules 07, 08, 09.
> **Asked by:** the user in session, 9 Nov: "create plan to build these ... in rich UI/UX and features and everything".

---

## 1. Objective

Close the gaps in procurement, inventory and suppliers so a builder can run the whole buying cycle in Mesiri:

```
Site asks (request) → office asks 3 shops (RFQ) → quotes come back → compare side by side → award → PO
   → delivery + GRN → return what was bad (debit note) → bill matched → paid
Stock: minimum levels → reorder alert → draft request/RFQ;  monthly count → differences approved → stock value
Supplier: on-time %, quality %, price vs others → a score used when choosing the next supplier
```

## 2. Business value

| Gap today | What the builder gets |
|---|---|
| Prices are compared after buying (Rates page), never before | 3 quotes before a big order, the cheapest flagged, the reason recorded when it is not picked. Typical saving on steel/cement: 2–5% of the order. |
| Damaged / short / wrong-size material is "used up" (WASTAGE) or forgotten | A return with a debit note; the supplier's balance goes down by itself; no paying for bent steel. |
| "Running low" is a guess from 3 days of use | A minimum per site and material that the PM sets; an alert and a one-tap draft order. |
| Book stock and real stock drift apart for months | A count sheet; differences shown in ₹; approved by the owner; the ledger stays true. |
| Nobody knows what stock is worth | Stock value per site and category (quantity × average rate) in the dashboard, the period report and Excel. |
| The same late supplier keeps getting orders | On-time %, rejected %, price index per supplier, shown on the comparison sheet and the supplier page. |

## 3. Investigation (Phase 1 findings)

| Area | Exists | Reuse for phase 2 |
|---|---|---|
| Requests | `material_requests` / `_lines`, `domains/procurement/router.py`, decide / outside / reopen | An RFQ is started from a request (its lines); award moves the request on exactly as an order does today (`requests_follow`) |
| Orders | `purchase_orders` / `_lines` (0511), `orders_router.py` create / change / receive, `purchase_order_events` (0513), duplicate check | Award = `create_order` per winning supplier, same duplicate check, `request_line_id` kept |
| PO document + send | `PurchaseOrderDocumentPage.tsx` (letterhead, print/PDF), `whatsappUrl(vendor_phone, orderMessage(...))` (the person sends) | Same pattern for the RFQ document and "Send on WhatsApp" |
| GRN | `goods_receipts` (0514), `grn.py`, rejected quantity + reason + challan photo | Returns start from a GRN's rejected quantity; on-time and quality scores read GRNs |
| Stock ledger | `post_material_movement` (RECEIPT / ISSUE); reasons `RETURN_TO_VENDOR`, `ADJUSTMENT_IN/OUT` already exist (`materials/validation.py`); `role_can_adjust` | Returns post `RETURN_TO_VENDOR`; count differences post `ADJUSTMENT_IN/OUT`. **No new movement type.** |
| Running low | `stock_summary.py` (`LOW_DAYS = 3`, `on_order`) | Minimum level becomes a second rule in the same function |
| Reminders | `plan_reminders.py` (order-by, one grouped note a day), `application/procurement/alerts.py` | Reorder alerts and quote-due reminders join the same daily pass |
| Rates | `rates.py` (history per stock unit), PRC-34 (GST on deliveries, todo) | Comparison sheet shows last rate and the Rates page's "cheaper elsewhere" |
| Supplier ledger | `vendors/ledger.py` (opening, delivery, bill, payment kinds) | New kind `debit_note` |
| Supplier record | `vendors` (phone, gstin, address, kind, credit_days, lead_time_days) | Performance is computed, no new column |
| Documents | `project_documents` (0527) is per project, folders fixed | Supplier certificates need their own small table (per supplier, not per project) |
| Photo reading | bill photo pipeline (PRC-11/36) | A quote photo read the same way (supplier, lines, rates, GST, validity) |
| Assistant | v3: `agent_api/tools.py` `ALLOWED` + `SOP.md` | Every feature below = a route + an `ALLOWED` line (+ SOP rule). No workflow, router or word list. |
| Module map | `module-map.ts`: Quotations (V1.5), Returns (Later), Pending deliveries (V1, planned) | Flip to `built` as each lands |
| Permissions | `may_act_on_material_requests` (admin, owner, PM) guards orders; PRC-12 (who may order / see rates) **blocked** on Ilan | Phase 2 uses the same guard as orders until PRC-12 is decided; rates and ₹ follow D-CC4 (money roles) |
| Migration head | `0538_report_snapshots` | New migrations 0539+ (check head right before writing each) |

## 4. Scope

**In:** quotations / RFQ (PRC-40..44), pending deliveries page (PRC-45), returns and debit notes (PRC-46),
minimum stock and reorder (PRC-47), physical stock count (PRC-48), stock valuation (PRC-49), supplier performance
(PRC-50), supplier price list from quotes (PRC-51), supplier documents and certificates (PRC-52).

**Out (stay Later, said plainly):** batch / lot / serial numbers (not how site materials are tracked; mill test
certificates are covered by PRC-52 on the GRN), reserved stock (comes with Central store), rate contracts, a
supplier portal, tenders, consumption-vs-theoretical checks.

**Prerequisite:** PRC-34 (GST on deliveries) before PRC-43, so quotes and past rates compare like with like.

---

## 5. The features, with the UX

Design language: the Requests / Purchase orders design already in use (tiles on top, tabs, a list, a right-hand
detail sheet, hazard-yellow primary, Site pill, empty states that teach). Every page works at phone width (cards
instead of table rows under 640 px, sticky action bar at the bottom). Money hidden from roles outside D-CC4.

### 5.1 Quotations / RFQ — `Procurement › Quotations` (PRC-40..44)

**Flow**
1. *Ask for quotes* — from a request ("Get quotes" next to "Order"), from the Rates page ("Ask for quotes" on a
   material), from the reorder alert, or blank. Pick lines (material, quantity, unit, needed by, site), pick
   suppliers (picker shows each supplier's **score chip**, last rate for these materials, and "supplies this
   category" first), set **quotes due by** and terms wanted (delivery to site, payment days).
2. *Send* — RFQ-0001 document (letterhead, lines, site address, due date, "please quote rate per unit incl. /
   excl. GST, delivery days, validity"); per supplier: **Send on WhatsApp** (pre-written message + link to the
   PDF, the person sends, as PO today) and **Copy / Print**. Each supplier row shows Sent ✓ / Not sent.
3. *Record quotes* — three ways, all landing in the same quote form:
   - type it (grid: one row per line, rate, GST %, incl./excl. toggle, delivery days, brand/remark);
   - **drop a photo or PDF of the quote**: read like a bill photo, the grid fills, the person checks and saves;
   - WhatsApp: "Malabar quoted cement 395 incl GST, delivery 2 days" or a forwarded quote photo → Save card.
   A supplier that will not quote: "Declined" with a reason.
4. *Compare* — the **comparison sheet** (heart of the feature):
   - columns = suppliers, rows = lines; each cell: rate per stock unit **with GST, normalised**, line total,
     delivery days; the lowest per line in green, the highest in muted red; "last paid ₹x on 12 Oct" under each
     line; "+₹14 vs last time" chips;
   - a footer per supplier: total, GST, delivery, payment terms, validity, **score** (on-time %, rejected %);
   - toggles: *lowest per line* (split award) vs *lowest total* (one supplier); the sheet shows what each choice
     costs ("splitting saves ₹6,240 but means 2 deliveries");
   - phone: one card per line with suppliers stacked, swipe between lines.
5. *Award* — choose per line or all to one supplier; when the chosen one is not the lowest, a **reason** is asked
   (quality, delivery, credit, brand) and stored. Award creates the PO(s) through the existing order route
   (duplicate check, request moved on, requester told). Losing suppliers can be thanked from a ready message.

**Page:** tiles (*waiting for quotes*, *quotes due today*, *ready to compare*, *saved this month ₹* = lowest
rejected-average minus awarded), tabs *Open · Ready to compare · Awarded · Closed*, list rows with RFQ number,
site, lines summary, "2 of 3 quoted" progress dots, due date chip. Detail sheet: Lines · Suppliers (status per
supplier) · Comparison · History. Empty state: "Ask three shops before a big order" with one example.

**WhatsApp (v3 tools):** `rfqs`, `ask_for_quotes`, `record_quote`, `compare_quotes`, `award_quotes`. Examples:
"get quotes for 500 bags cement for Villa from Malabar, KSL and Sree" · "Malabar quoted 395" · "who is cheapest
for the cement quotes?" (answers with the comparison as a card PNG) · "give it to KSL" (Save card → PO).
Reminders: "Quotes for RFQ-0004 due today: 2 of 3 in. Sree has not quoted."

**Data (migration, additive, RLS):** `rfqs` (number RFQ-0001 per company, project, site, status
open/awarded/closed/cancelled, due_date, terms, request_id, created_by), `rfq_lines` (material, unit, quantity,
needed_by, request_line_id), `rfq_vendors` (rfq, vendor, sent_at, status invited/quoted/declined, decline_reason),
`quotations` (rfq_vendor, received_at, valid_until, delivery_days, payment_days, notes, photo key, source
typed/photo/whatsapp), `quotation_lines` (rfq_line, rate, gst_percent, rate_includes_gst, brand, remark),
`purchase_orders.rfq_id` + `purchase_order_lines.quotation_line_id` (nullable) and an award reason.

**API:** `GET/POST /procurement/rfqs`, `GET/PATCH /procurement/rfqs/{id}`, `POST …/{id}/vendors`,
`POST …/{id}/quotes` (+ `/photo` read), `GET …/{id}/comparison`, `POST …/{id}/award`, `POST …/{id}/cancel`,
`GET …/{id}/document`.

### 5.2 Pending deliveries — `Procurement › Pending deliveries` (PRC-45)

The module map already promises it. A board, not a new system: open order lines still to come, grouped
**Late · Today · This week · Later · No date**, each card: material, qty left, supplier (tap to call /
WhatsApp "where is it?" message), site, PO, days late. Filters: site, supplier, category. Actions on the card:
*Material came* (the existing receive sheet), *Move date*, *Close short*. Reads `GET /procurement/orders` lines;
one new read route `GET /procurement/pending` only if the list needs line-level paging.

### 5.3 Returns and debit notes — `Procurement › Returns` (PRC-46)

**Flow:** start from a GRN with rejected quantity ("Return 12 bent bars"), from a delivery in Movements, or from
the supplier page. Lines (material, qty, rate defaulting to the delivery's rate, reason: damaged / short / wrong
size / excess / quality failed), photos, collected by / sent back on. Saving: stock goes down
(`RETURN_TO_VENDOR`, existing reason), **DN-0001** debit note document (letterhead, PDF, Send on WhatsApp), the
supplier ledger shows a `debit_note` line that lowers what is owed. Status: *Waiting for pickup → Sent back →
Settled* (replacement came: linked to a new delivery, or credit given: linked to the next bill / payment).

**Page:** tiles (*waiting for pickup*, *₹ owed to you by suppliers*, *returns this month*), list, detail sheet
with the timeline. Supplier page gets a "Returns" tab. WhatsApp: "12 steel bars bent, returning to KSL" → Save
card; `returns`, `return_to_supplier`, `settle_return`.

**Data:** `material_returns`, `material_return_lines` (link to receipt / GRN line), `vendors` ledger reads them.
Additive.

### 5.4 Minimum stock and reorder — inside `Materials › Stock` (PRC-47)

- Per site + material: **minimum** and **reorder quantity** (set inline in Stock, in bulk from Excel import, or
  "suggest from use": 7 days of average use + lead time).
- Stock rows get a bar (closing vs minimum) and a *Below minimum* chip; tile "Below minimum: 6".
- Daily reminder pass: one grouped note to the PM/storekeeper ("3 items below minimum at Villa: cement 40 bags
  (min 100) …") with buttons **Make request** / **Get quotes** → a draft request or RFQ pre-filled with the reorder
  quantities. No duplicate alert when an open order or RFQ already covers it.
- WhatsApp: "set minimum cement at Villa 100 bags", "what is below minimum?".
- Data: `stock_levels` (site, material, min_qty, reorder_qty). Additive.

**As built (PRC-47, 10 Nov 2026).** Migration 0541 (`stock_levels`, RLS). Routes `domains/materials/stock_levels_router.py`
(`/materials/stock-levels`: list, PUT one (min 0 removes), bulk, DELETE, `/suggest`, `/below`), rules in
`stock_levels.py` and `stock_summary.py` (`finish_row` takes the minimum: `below_min` is what the site holds now under
it; `running_low` also when held + on order is under it; no minimum, no change). "Covered" = enough on open orders,
or a live RFQ, or a **waiting material request** for that site and material (requests added to the plan's "order or
RFQ": a request is already "someone is buying it", and the draft request would otherwise be refused as a duplicate).
Draft quantity = the reorder quantity, else back to twice the minimum. Suggest = (7 + supplier lead days, 2 when not
set) days of the last week's average use; reorder two weeks' use. Excel: a fourth sheet "Minimum stock". The daily
note (`stock_below_minimum`, one per project and person a day, admin / owner / PM, through the existing reminder pass)
carries **two links** ("Make request: …", "Get quotes: …") to Materials › Stock `?reorder=<site>&make=request|rfq`,
which opens the draft request / RFQ with the reorder quantities. Links, not WhatsApp quick-reply buttons: a
quick-reply tap reaches v3 only as its title ("Make request") without the site or items, so it could not open the
right draft (the "a tap carries less than the message" class). v3 tools: `below_minimum`, `minimum_stock`,
`suggest_minimum_stock`, `set_minimum_stock` + SOP rule 24. Who sets: admin, owner, PM (`may_act_on_material_requests`,
as orders, PRC-12 may change it).

### 5.5 Physical stock count — `Materials › Stock count` (PRC-48)

- *Start a count* for a site (all items, one category, or a cycle list of the 20 most valuable). Book quantity is
  frozen at the start.
- Count sheet built for the site: big inputs, grouped by category, works on a phone, partial save, "not counted"
  allowed. WhatsApp: "count: cement 92 bags, sand 3 loads" fills the open count.
- Review: book vs counted, difference in units and **₹**, sorted by ₹; reason per line (wastage, theft,
  wrong entry, not recorded usage).
- *Approve* (owner/admin; `role_can_adjust`): posts `ADJUSTMENT_IN/OUT` (existing reasons) per difference with the
  count as reference. Counts are never edited after approval; a new count corrects.
- History: last counted date per site; reminder when a site has not been counted in 30 days (setting).
- Data: `stock_counts`, `stock_count_lines`. Additive.

### 5.6 Stock valuation — `Materials › Stock value` (PRC-49)

Quantity on hand × **weighted average rate** (from receipts, GST per D-CC8 rule), per site, category and
material; totals tile, a bar by category, top 10 items by value, slow-moving (no use in 30 days) flagged. Excel
export. A "Stock value" line in the period report (PRC-19 sections). Money roles only. Read only, no table.

### 5.7 Supplier performance — supplier page + comparison sheet (PRC-50)

Computed from what already exists, no typing:
- **On time %**: GRN date vs order's expected date (late if after).
- **Complete %**: delivered vs ordered on closed orders (closed short counts against).
- **Rejected %**: GRN rejected qty / received.
- **Price index**: their rates vs the company's average for the same materials (from Rates).
- **Quote response**: quoted / invited.
A 0–5 score (weights in code, shown on hover), a trend sparkline by month, and the last 5 problems listed.
Shown: supplier page header, supplier list column (sortable), supplier picker chips, comparison sheet footer.
Optional manual rating (1–5 + note) after an order is closed, asked once on the order sheet. Data: one additive
table for the manual ratings only.

### 5.8 Supplier price list from quotes (PRC-51)

Supplier page › *Price list*: last quoted and last paid rate per material, valid until, from which RFQ/PO;
expired quotes greyed. The new-order dialog shows "Malabar quoted ₹395, valid till 20 Nov" next to the rate box
(this also delivers PRC-15, rate on the order card). Read only over `quotation_lines` + `rates.py`.

### 5.9 Supplier documents and certificates (PRC-52)

Supplier page › *Documents*: GST certificate, PAN, cancelled cheque, agreement, ISO / BIS, with expiry date and a
reminder 15 days before. On a GRN: attach **mill test / cube / batch certificates** (steel, cement, RMC) so quality
proof sits with the delivery. Data: `vendor_documents` (vendor, kind, file key, expires_on) and
`goods_receipt_documents`; storage as the challan photo. Additive.

---

## 6. Files expected to change

| Layer | Files |
|---|---|
| Migrations | `0539_rfqs_quotations.py`, `0540_material_returns.py`, `0541_stock_levels.py`, `0542_stock_counts.py`, `0543_vendor_ratings_documents.py` (numbers re-checked before each) |
| Backend | new `domains/procurement/rfqs.py`, `rfqs_router.py`, `returns.py`, `returns_router.py`; `domains/materials/stock_levels.py`, `stock_count.py`, `valuation.py`; `domains/vendors/performance.py`, `documents.py`; changes in `orders_router.py` (award → order), `stock_summary.py` (minimum rule), `vendors/ledger.py` (debit note kind), `plan_reminders.py` / `application/procurement/alerts.py` (reorder, quotes due), `reports/period/sections.py` (stock value); routers mounted in the app production runs (lesson of PRC-33) |
| Dashboard | pages `QuotationsPage`, `RfqDocumentPage`, `PendingDeliveriesPage`, `ReturnsPage`, `DebitNoteDocumentPage`, `StockCountPage`, `StockValuePage`; components `components/quotations/*` (comparison sheet, quote form, supplier picker with score), `components/returns/*`, `components/stock/*`; changes in `RequestsPage` / `request-detail` (Get quotes), `new-order-dialog` (quoted rate), `VendorPage` (Performance, Price list, Returns, Documents tabs), Stock view (minimum), `module-map.ts`, `App.tsx` routes, `lib/*.ts` clients |
| Assistant | `agent_api/tools.py` `ALLOWED` lines, `agent_api/SOP.md` rules (three languages via the text catalogue), Save card shapes, comparison card PNG in `channel/cards/` |
| Docs | this plan, `procurement-plan.md` status, tracker, `capability-framework-gap-analysis.md`, DECISIONS (D-P2-*) |

## 7. Database, API, risks

- **Database:** five additive migrations, every table with `organization_id` + RLS `tenant_isolation`, nothing
  dropped or rewritten; two nullable columns on `purchase_orders` / `purchase_order_lines`.
- **API:** new routes listed per feature; existing routes unchanged except the order create accepting
  `rfq_id` / `quotation_line_id` (optional).
- **Risks:**
  1. GST comparisons are wrong without PRC-34 → PRC-34 first.
  2. Permissions: who may award, approve counts, see ₹ — PRC-12 is blocked; default = same guard as orders
     (admin, owner, PM) and D-CC4 for money; count approval admin/owner only. Changing these is an approval item.
  3. Ledger correctness: returns and count adjustments must use the one posting path (`post_material_movement`)
     so stock, orders and the period report agree; tests check all three.
  4. Supplier ledger is Finance (not Payroll/Workforce) but shared by Cost control: the debit note kind is added
     without changing existing kinds; balance tests before/after.
  5. Reminder fatigue: reorder + quotes due + order-by grouped into the one daily note.
  6. WhatsApp sends to suppliers outside the 24-hour window need Meta templates (RFQ, debit note) → add to PRC-13
     (ops).
  7. Routers must be mounted in the production app (PRC-33 happened once).

## 8. Testing strategy

- Unit: comparison maths (GST normalisation, unit conversion to stock unit, lowest per line vs total, savings),
  weighted average rate, performance score, count differences, reorder suggestion.
- Route tests with seeded company: RFQ → quotes → award creates POs (duplicate check, request moved on); return →
  stock down, ledger down; count approve → adjustments; tenant isolation on every new table (other company 404).
- Regression: existing procurement, materials, vendors, reports suites; period report snapshots.
- Dashboard: `tsc`, `oxlint`, `vite build`; Playwright screenshots of each new page at desktop and 390 px.
- Assistant: v3 tool tests + live messages from the test chat (as PRC-32) in English, Manglish, Malayalam.

## 9. Rollback strategy

Each item ships alone, behind its own pages and routes; nothing existing changes behaviour unless the new data
exists (no RFQ → orders as today; no minimum → running low as today). Rollback = revert the item's commits; the
additive tables stay unused (no data lost), or a down-migration drops only the new tables. Award, returns and
counts write through existing posting paths, so reverting the code leaves consistent stock.

## 10. Module isolation

No change to Payroll, Workforce, Labour or Attendance. Shared pieces touched: supplier ledger (new kind only),
stock summary (new optional rule), reminder pass (new grouped section), period report (new section). Each is an
extension, stated in the phase report.

## 11. Build order

| Step | Items | Why this order |
|---|---|---|
| 0 | PRC-34 (existing todo) | Like-for-like GST |
| 1 | PRC-45 Pending deliveries | Small, already promised in the module map |
| 2 | PRC-40 → 44 Quotations | Biggest value, asked first |
| 3 | PRC-51 Price list (+ PRC-15) | Falls out of quotations |
| 4 | PRC-46 Returns | Uses GRN rejected quantities |
| 5 | PRC-47 Minimum / reorder | Feeds RFQ drafts |
| 6 | PRC-48 Stock count, PRC-49 Stock value | Inventory control |
| 7 | PRC-50 Performance, PRC-52 Documents | Needs GRN/quote history to mean something |

## 12. Decisions (default used until answered)

| ID | Question | Default |
|---|---|---|
| D-P2-1 | Minimum quotes before an order above an amount? | Not enforced; a hint "only 1 quote" on orders above ₹50,000 |
| D-P2-2 | Who may award quotes and approve stock counts? | Award: admin, owner, PM (as orders). Count approval: admin, owner. (PRC-12 may change it) |
| D-P2-3 | Debit note lowers the supplier balance at once or when they accept? | At once; "Settled" records how |
| D-P2-4 | Stock value rate | Weighted average of receipts, GST per D-CC8 |
| D-P2-5 | Performance weights | On time 35, complete 20, quality 25, price 20 |

## 13. Success criteria

- An RFQ to 3 suppliers, quotes recorded (one from a photo, one from WhatsApp), compared and awarded into POs in
  under 3 minutes, with the request moved on and the asker told.
- A rejected GRN line becomes a return and a debit note; the supplier balance drops by that amount.
- Below-minimum items produce one daily note with a working "Make request" button.
- A count with differences, approved, leaves book stock equal to the count.
- Every new page has tiles, filters, an empty state, works at 390 px, and every money figure is hidden from
  non-money roles.
- All verification checks pass; tenant isolation tested on every new table.
