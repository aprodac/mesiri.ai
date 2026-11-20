# Green Villa: the project bible

> Asked 20 Nov 2026 (Ilan): "let's look and plan the data we need, the documents or drawings or data that should be
> entered or will be entered along the way ... so that everything is understood. For that we need to plan a proper
> project." This page is that plan: one project, every document and record in it, who makes each, when, and where it
> goes in Mesiri. The series ([SERIES_PLAN.md](SERIES_PLAN.md)), the starter kit, the sample company's seed and its
> 62-day plan all follow this page; where they disagree today, section 2 says so. Status: **agreed** (Ilan, 20 Nov 2026: "Yes" to D1 to D5 as recommended). Progress in section 8.

## 1. What already exists (20 Nov 2026)

| Source | What it holds | File |
|---|---|---|
| The starter kit | 11 files: estimate (Excel), materials and suppliers (Excel), contract summary, ground floor plan A-101, three quotations, Malabar's challan and bill, Joy Tiling's measurement sheet and bill. Each has its page and a "catch" | `scripts/learn_kit/make_kit.py` → `public/learn/kit` |
| The seed (two weeks before day 1) | 2 projects, 4 sites, 7 suppliers, 1 subcontractor, 15 workers, 14 days of site records, 6 issues, 2 open orders, Lake View's BOQ (8 lines) and contract, 3 advances | `backend/.../organizations/sample_story.py` |
| The 62-day plan | 1,477 entries by four people, to Green Villa's handover | `backend/.../learn/sample_plan.py` |
| The guided project | "Set up Green Villa" (Project start) and "The BOQ" (the estimate imported) | `apps/dashboard/src/lib/walkthroughs.ts` |

## 2. Where they disagree today, and the decision each needs

| # | What | Today | Decided (20 Nov 2026) |
|---|---|---|---|
| D1 | **Green Villa's timeline** | The contract says work starts 2 Nov 2026 and handover is 31 Jul 2027 (9 months); the plan hands over on day 62 | **The 62 days are Green Villa's last two months** (finishing: plastering, tiling, painting at the Main block; the Annex from plinth to paint) and Lake View's middle (floors 3 to 6). Day 62 = 31 Jul 2027. Months 1 to 7 (foundation, frame, block work) are told as the backstory, from the seed's two weeks and the guided project |
| D2 | **Green Villa is never billed** | Only Lake View gets running bills (days 23, 51); Green Villa is handed over unbilled | Green Villa gets its monthly RA bills (per its contract: 10% advance recovery, 5% retention), its final bill at handover, and the retention release after the defects period |
| D3 | **Two Ravis, two Anils** | Ravi is the site engineer and a mason in the worker register; Anil is the project manager and, in the cost video's seed, the owner | The cast keeps **Ravi** (site engineer) and **Anil** (project manager); the mason becomes **Rajan**; the owner gets one name everywhere: **Ramesh Nair** |
| D4 | **Calendar** | The contract has fixed dates; the sample company's days start from the day it is opened | The film's local copy plays on the contract's calendar (day 62 = 31 Jul 2027). The sample company keeps its own relative days (no product change) |
| D5 | **Money accounts** | The sample company has no bank or petty-cash account ("No accounts yet"), so payments have nowhere to come from on the Money page | The seed adds the company's bank account (Federal Bank current account) and a petty-cash box per site |

## 3. The company and its people

| Who | Role in Mesiri | Does |
|---|---|---|
| **Ramesh Nair** | Owner (ADMIN) | Wins the work, approves wages and big orders, sends running bills, signs the handover |
| **Anil** | Project manager | Plans, buys, counts work on the BOQ, closes problems, runs subcontracts |
| **Ravi** | Site engineer | Runs the sites day to day on WhatsApp: attendance, work, material, problems, deliveries |
| **Meera** | Accounts (FINANCE) | Bills, payments, wages, advances, the client's money, GST, TDS, month end |
| Suresh | Labour contractor (Suresh's team) | Supplies helpers by the day; paid weekly |
| 15 named workers | Worker register | Masons, carpenters, bar benders, electrician, plumber, helpers (rename the mason Ravi → Rajan) |

**Outside:** Dr. Anand Krishnan (Green Villa's client); Lake View Builders, Mr. Varghese (Lake View's client); the
architect and structural consultant (named on drawings only); suppliers: Malabar Cements Agency, Kerala Steels,
Periyar Sand & Aggregates, Thrissur Blocks, Sri Hardwares, Hi-Tech Electricals, City Plywood, Colour World Paints,
Kerala Tiles and Sanitary; subcontractor: Joy Tiling Works.

## 4. The two projects

| | Green Villa | Lake View Apartments |
|---|---|---|
| What | A two-storey villa (Main block) with a single-storey Annex | A residential block, Towers A and B |
| Client | Dr. Anand Krishnan, Puthur Road, Thrissur | Lake View Builders (Mr. Varghese), Kakkanad, Kochi |
| Agreement | GV/2026/007, signed 20 Oct 2026 | LVB/2026/014 |
| Value | ₹82,06,050 + 18% GST (the estimate's 34 lines) | ₹4,20,00,000 + 18% GST |
| Dates | Starts 2 Nov 2026; handover 31 Jul 2027 (9 months) | Running; frame of floors 3 to 6 in the 62 days |
| Advance | 10% on signing, recovered at 10% of each RA bill | (to state) |
| Retention | 5% of each RA bill, released after the defects period | 5% |
| Defects period | 12 months from handover | (to state) |
| Billing | Monthly RA bills on measured work at BOQ rates; paid in 15 days | Running bills (days 23, 51 in the plan) |
| Delay | ₹25,000 a week beyond handover, at most 5% of the value | (to state) |

## 5. Documents and drawings: the register

Each document: who makes it, when it comes in, where it goes in Mesiri, and whether it exists. "Generated" = Mesiri
makes it from the records; nobody types it.

### Before day 1: winning and setting up (episodes 1 and 2)

| Document | From | When | In Mesiri | Exists? |
|---|---|---|---|---|
| Estimate / BOQ (34 lines, rates, labour and material cost) | Owner, from the drawings | Tender | BOQ & budget: Import from Excel | **Yes** (kit) |
| Contract summary (client, value, dates, advance, retention, defects, delay) | Owner and client | Signing, 20 Oct 2026 | Project start: the contract step | **Yes** (kit) |
| Architectural drawings: A-101 ground floor plan | Architect | Before start | Drawing check, Documents | **Yes** (kit) |
| A-102 first floor plan, A-201 elevations, A-301 section | Architect | Before start | Documents (and Drawing check for plans) | Made: the kit's drawing set |
| Structural drawings: S-101 footing layout, S-102 column schedule, S-201 slab reinforcement | Structural consultant | Before start; revisions on site | Documents | Made: S-101, S-102 in the set (S-201 with the revision, batch 3) |
| Services: E-101 electrical layout, P-101 plumbing layout | Consultants | Before the services stage | Documents | Made: in the set |
| Building permit | Municipality | Before start | Documents | Made: the kit's permit |
| Materials and suppliers (items, shops, opening stock, minimums) | Anil | Setup | Bring your data | **Yes** (kit) |
| Supplier rate list | Suppliers | Setup, then as quoted | Rates | Made: Periyar's rate card (catch: M sand later 1,750 against 1,650) |
| Schedule (stages per site, from the BOQ) | Anil | Setup | Schedule | Generated from BOQ + dates; to check |
| Material plan (what to buy when) | Mesiri | Setup | Material plan | Generated |
| Team and their WhatsApp numbers | Owner | Setup | Team, WhatsApp | Seeded |
| Places (blocks, floors, rooms) | Anil | Setup | Places | From the drawing set (Track reads its rooms and footings): no paper |

### Along the way: days 1 to 62 (episodes 3 to 10)

| Document or record | From | How often | In Mesiri | Exists? |
|---|---|---|---|---|
| Site day: attendance, work done, material used, small spends, weather | Ravi, on WhatsApp | Daily, each site | Today, Site log, Attendance, Stock, Expenses | Plan |
| Daily progress report (DPR, PDF) | Mesiri | Every evening | Daily reports; to owner and client on WhatsApp | Generated |
| Material request | Ravi | When stock will run short | Material requests | Plan |
| Quotations (three suppliers) | Suppliers, asked by Anil | Before a big order | Quotations | **Yes** (kit: cement and steel) |
| Purchase order (PDF) | Anil | Per request | Purchase orders | Generated; plan |
| Delivery challan | Supplier, with the lorry | Each delivery | Record delivery (a photo of the challan) | **Yes** (kit: one) |
| Return note (damaged or extra) | Ravi | When a load is wrong | Returns | Made: Malabar note GV/RN/014, 6 torn bags; played in batch 2 |
| Supplier bill | Supplier | After deliveries | Suppliers: bills, checked against order and delivery | **Yes** (kit: one); plan |
| Payment advice | Meera | On the due date | Suppliers: payments, Money | Plan |
| Stock count sheet | Ravi | Month end | Stock count | No paper: counted on the phone (batch 2) |
| Machine log (hours, diesel, breakdown) | Ravi | Daily, each machine | Equipment: Daily log | To make (batch 2) |
| Hire bill (a hired mixer, a JCB) | Hire company | Monthly | Equipment: Hire check | Made: KEE/2027/0118, 42 h billed against 36 logged; played in batch 2 |
| Wage sheet (weekly) | Mesiri, from attendance | Weekly | Wages: approve, pay | Generated; plan |
| Advance slip | Meera | When given | Advances | Plan |
| Problem (with a photo) | Ravi, on WhatsApp | When it happens | Issues; a task for whoever fixes it | Plan; tasks batch 3 |
| Revised drawing (e.g. slab steel) | Structural consultant | When it changes | Documents | To make (batch 3) |
| Subcontract work order (PDF) | Anil | Once (tiling) | Work orders | Generated; plan |
| Measurement sheet | Anil with the subcontractor | Weekly | Work orders: measure | **Yes** (kit); plan |
| Subcontractor bill | Joy Tiling Works | After measurement | Bills & checks | **Yes** (kit); plan |
| Running (RA) bill, PDF | Owner | Monthly | RA bills | Generated; plan (Lake View only: D2) |
| Variation (extra work the client asks for) | Client asks; Anil prices; owner sends | When asked | Variations | To make (batch 3) |
| Client's payment advice | Client | After each bill | Receivables | Plan |
| GST and TDS working | Meera | Monthly | GST, TDS | Generated from records (batch 1) |
| Month close and Tally export | Meera | Monthly | Months, Tally export | Batch 1 |
| Weekly and monthly report (PDF, Excel) | Mesiri | Weekly, monthly | Weekly & monthly | Generated |

### At handover and after (episode 11)

| Document | From | When | In Mesiri | Exists? |
|---|---|---|---|---|
| Snag list | Owner and client walk-through | Days 55 to 60 | Tasks (one per snag) | To make (batch 3) |
| Final bill | Owner | Handover | RA bills (final) | Generated; plan day 62 (D2) |
| Handover certificate | Owner and client | Day 62 | Documents; project stage "handed over" | Made: the kit's certificate |
| Retention release request | Owner | After the 12-month defects period | Receivables | To make |
| Defect complaints | Client | During the defects period | Issues | To make |

## 6. Master data: what Mesiri holds before the story starts

| Data | Today | To add |
|---|---|---|
| Items and units | Catalogue + kit items (tiles, granite, CPVC, wire, emulsion) | Machines' diesel; anything the drawings name |
| Suppliers | 7 seeded + 3 in the kit | Rate list per supplier (batch 2) |
| Subcontractor | Joy Tiling Works | — |
| Workers | 15 with trade, wage and site | Rename mason Ravi → Rajan (D3); teams: Suresh's team (batch 3) |
| Machines | None | A mixer and a vibrator per site; a hired JCB for the Annex; a tipper (batch 2) |
| Money accounts | None | Federal Bank current account; petty cash per site (D5) |
| Clients | Lake View Builders | Dr. Anand Krishnan (Green Villa) |
| BOQ | Green Villa: imported in the guided project; Lake View: 8 seeded lines | Lake View's full estimate, so its RA bills read right |
| Cost centres, chart of accounts | Made by Mesiri | — |

## 7. The rules that keep it true

1. **One number, one source.** A figure said in an episode is read off the sample company on that day; a figure in a
   document comes from the same data the seed and the plan use (the kit's estimate is the BOQ; the contract's value is
   the estimate's total).
2. **Work names match the BOQ.** Every work the site reports is a BOQ line with the same unit (the kit's `SITE_WORK`
   check), so every day's work can be counted.
3. **Material follows the norms.** What a stage uses comes from the BOQ's materials per unit; deliveries keep each site
   stocked; a short site does less work.
4. **Money adds up.** An RA bill = measured quantity × BOQ rate, less 10% advance recovery, less 5% retention, plus GST;
   a supplier bill matches its order and delivery unless it is a catch on purpose; wages = attendance × wage.
5. **Catches are on purpose and named.** Each deliberate mistake (the short lorry, the bill above the order, the
   mislabelled bedroom, the bill above the measurement) is listed with the episode that shows it.
6. **Nothing from production.** Names are invented; no phone numbers or GSTINs that could be a real business's.

## 8. Work this plan needs, in order

1. **Decisions D1 to D5** (Ilan): agreed 20 Nov 2026.
   - Done: D3 (the mason is Rajan; the owner is Ramesh Nair in the demo seed) and D5 (the seed opens the Federal Bank
     account and a petty-cash box per site; the player uses the same definition), checked through the API.
   - Done: **D2**, Green Villa billed by its contract. Its estimate, contract and stage-to-line map are one source,
     `backend/.../learn/green_villa.py` (the starter kit's files and the plan both read it). Day 2: the owner sets the
     contract, Anil puts the estimate in as the BOQ (both skip themselves when the person did the guided chapters 2
     and 3). Its work is counted on the estimate's lines; a running bill on day 30 and the final bill at handover, each
     less 10% advance and 5% retention plus GST; the client pays 15 days later. Played through the API for all 62 days
     with no failure: bill 1 net Rs 11,92,169 (paid day 45), final bill net Rs 9,41,008.
2. **Done (LRN-F5): the documents to make:** the drawing set (A-102, A-201, A-301, S-101, S-102, S-201, E-101, P-101), the building
   permit, the supplier rate list, the places, the return note, the stock count sheet, the hire bill, the handover
   certificate: added to the starter kit's generator (`make_kit.py`), each with its page and, where it fits, a catch.
   Six new files (one source, `green_villa.py`): the eight-sheet drawing set rev A (Drawing check finds exactly its
   three catches: a copied BEDROOM-2 label, the roof at +660 on the elevation and +655 on the section, the first-floor
   toilet drawn 210 x 150 over a 240 x 150 one; 6 footings counted), the permit, Periyar's rate card, Malabar's return
   note, Kerala Earthmovers' hire bill and the handover certificate. Places come from the drawing set; the stock count
   is done on the phone, so neither is paper. S-201 comes with the slab revision (batch 3).
3. **The seed:** names (D3), money accounts (D5), Green Villa's client, Lake View's full estimate and terms.
4. **The 62-day plan:** Green Villa's RA bills, final bill and retention (D2), then story batches 1 to 3
   ([SERIES_PLAN.md](SERIES_PLAN.md) section 7).
5. **A consistency check** (a test): the rules in section 7, so a change to the seed, the kit or the plan that breaks
   the story fails the build.
