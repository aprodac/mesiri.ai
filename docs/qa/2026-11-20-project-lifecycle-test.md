# Project lifecycle test, production test company (20 Nov 2026)

One new project taken from start to handover on the live site
(`app.whatsapp.mesiri.ai`), in a test company, as the people who would really do each step.
Test records are named `QA-2011 …` so they are easy to find and remove.

## Script

| # | Stage | Role | Pages | What must hold |
|---|---|---|---|---|
| 1 | Company ready | Owner | Settings, Team, Users | Invite PM, site engineer, accountant; each sees only their pages |
| 2 | New project | Owner | Projects → new, Planning › Project start | Project + sites + client + contract value saved; appears in the project picker everywhere |
| 3 | Estimate | PM | BOQ, Planning › Places | BOQ lines with qty/rate; total matches contract; materials per unit |
| 4 | Plan | PM | Schedule, Tasks, Material plan, Documents | Activities linked to BOQ; material plan derived from BOQ |
| 5 | Buy | PM / owner | Requests, Quotations, Purchase orders, Approvals | Request → quote → PO → approved; PO PDF |
| 6 | Receive | Site engineer | Pending deliveries, GRN, Stock | Partial delivery; stock goes up; rate over PO flagged |
| 7 | Daily work | Site engineer | Today, Site log, Labour, Issues, Gallery | Work done on a BOQ line, attendance, an issue raised and resolved, DPR |
| 8 | Subcontract | PM | Subcontract › Work orders, Bills | Work order, measured bill, approval |
| 9 | Spend | Accountant | Expenses, Petty cash, Vendor bills | Expense in a category with a cost centre; vendor bill against PO |
| 10 | Client billing | PM / accountant | RA bills, Variations, Receivables | RA bill from work done; a variation; payment received |
| 11 | Books | Accountant | Accounts (Day book, Ledgers, TB, P&L, GST, TDS, Tally) | Every step above posted once; TB balances; project P&L matches |
| 12 | Control | Owner | Cost control, Cash flow, Home, Approvals | Budget vs actual, margin, cash ahead are consistent with 3–11 |
| 13 | Handover | PM / owner | Project close, final bill, retention | Project can be finished; final figures; nothing left open |

## Problems found

| # | Step | Role | Page | What happened | Expected | Severity | Status |
|---|---|---|---|---|---|---|---|
| 1 | 2 | Owner | Projects → New project | QA-2011 Sunrise Residency created in "cd" (Asia/Kolkata, Green Villa's DPR on) got **UTC, DPR off**: "Day closes 6:00 pm" = 11:30 pm IST, "send by 9 pm" = 2:30 am. Lake View also UTC. Root cause: production serves the assistant app's `/projects` (`apps/whatsapp-assistant/src/projects/router.py`); [259] fixed only the backend router, which production does not mount | Company zone, report as the company has it | High | Fixed (code); existing UTC projects need a data fix (approval) |
| 2 | 2 | Owner | Projects vs Home | Lake View Apartments: "On Track" on Projects & Sites, "Over budget / 69% over" on Home | One status for a project everywhere | Medium | Open |
| 3 | 2 | Owner | Project page | A brand-new project with no data is "On Track" | No status until there is something to judge ("Not started") | Low | Open |
| 4 | 3 | PM | BOQ → Add line | First "Save line" failed, second took 10 s. Cause: another deploy (daa0ac6c) restarted the API at 06:23 UTC; the page did show "Could not save the line". Same deploy was marked failed only because its smoke test hit /health/live 5 s after restart | — | Info (deploy smoke-test race, not this test) | Noted |

## Step-by-step run (asked 20 Nov: practical test, one step at a time, every problem logged)

Project: **QA-2011 Palm Grove Villas** (code QPG-004, client "QA-2011 Client Meera Nair", Kakkanad, Kochi), company "cd".

### Step 1: create the project (owner)

Result: created. Time zone Asia/Kolkata, DPR on, cut-off 18:00, send by 21:00 (the QA-05 fix, live since dc34f3c3's
deploy). Duplicate name blocked ("Green Villa already exists", any case). Empty name refused.

| # | Kind | Where | What happened | Expected | Severity |
|---|---|---|---|---|---|
| 1.1 | Data / UX | New project → Client | The client typed here is only text on the project: not in Clients (`/billing/clients` has only Lake View Builders), no contract. Billing will ask for the client again | One client: typing it here creates (or picks) the client record the contract and RA bills use | High |
| 1.2 | UX | New project → Project name | Placeholder is "Green Villa", a real project in this company; after "Project Name is required." the grey "Green Villa" still sits in the box, so it looks filled | A neutral example ("e.g. Rose Garden Villas") | Medium |
| 1.3 | UX | New project | "Create and open Today" is clickable with no name ("Create project" is correctly disabled) | Both disabled until there is a name | Low |
| 1.4 | UX | New project | An error stays after the cause is fixed ("Green Villa already exists" above the new, valid name) | Clear the error when the name changes | Low |
| 1.5 | Wording | New project | "Project Name is required." (capital N, error at the top, field not marked) | "Give the project a name", on the field | Low |
| 1.6 | UX | Projects & Sites | Top bar shows a picked project (QA-2011 Sunrise Re…) while the page says "Company-wide: every project" | One scope at a time, or the page says why | Medium |
| 1.7 | UX | Projects & Sites cards | Cards show different facts: Green Villa "Daily cutoff 6:00 pm", the others "Automatic DPR off"; "Admins only" is unclear (means: no one else added yet) | Same fields on every card; "Only admins can see it" | Low |
| 1.8 | Logic | Projects & Sites, project page | Every project is "On Track": the new empty one, and Lake View, which Home calls 69 % over budget | One status rule everywhere; "Not started" with no data | Medium |
| 1.9 | Speed | Every full page load | Blank "Checking session…" for ~1.4 s before anything shows | Show the page frame at once | Low |
| 1.10 | Heads-up | New project | DPR came on by itself (copied from Green Villa): at 9 pm the DPR for this test project goes to the admins and project managers on WhatsApp | Intended rule; for a test project turn it off | Info |

### Step 2: add the sites (owner)

Result: Villa 1, Villa 2, Villa 3, Villa 4, all active. Rename works. Today shows 0/4, "5h 27m to 18:00" (India time,
right), "report goes at 9:00 pm".

| # | Kind | Where | What happened | Expected | Severity |
|---|---|---|---|---|---|
| 2.1 | Bug / data | Project → Add site | "villa 1" was saved beside "Villa 1": duplicate site names are allowed. Production's `create_project_site` (`apps/whatsapp-assistant/src/projects/router.py`) only checks the name is not empty; rename has no check either. Projects block duplicates ([207]), sites do not: on WhatsApp "villa 1" then matches two sites | "Villa 1 is already a site of this project", on add and on rename, any case or spacing | High |
| 2.2 | Logic / UX | Today | Four warnings "Villa N hasn't reported today" one minute after the sites were made, and nobody is assigned to report from them | "No one reports from Villa 1–4 yet: add a site engineer" (an action, not a warning) | Medium |
| 2.3 | UX / setup gap | Add site | A site is only a name: no site engineer, no address, no start date. Who reports from the site is never asked during setup | Ask "Who reports from this site?" (pick a person or share a WhatsApp contact) | Medium |
| 2.4 | UX | Add site | One site per dialog: 4 villas took 4 dialogs | "Villa 1-4" or one name per line adds several at once | Medium |
| 2.5 | UX | Add site | Empty name + Add site: nothing happens, no message | Button disabled until a name, or "Give the site a name" | Low |
| 2.6 | UX | Add site | After adding with Enter, the page jumped back to the top | Stay at the Sites list and light up the new site | Low |
| 2.7 | UX | Site menu | Only Rename and Archive: a site added by mistake a minute ago can only be archived, and stays in the data | Delete while it has no records; archive after | Low |
| 2.8 | UX | Projects, BOQ, Today | A page tour opens by itself on the first visit to every page (3 so far) | Fine for new people; one "Don't show tours" for people who know the app | Low |
| 2.9 | Heads-up | Today | "0 of 4 sites confirmed · report goes at 9:00 pm" with no one reporting: to check at 9 pm what the DPR sends for a project with no updates | An empty DPR is not sent, or says plainly that no site reported | Info |

### Step 3: BOQ and budget (project manager)

Done: imported Mesiri's own sample estimate (`public/learn/kit/Green Villa - estimate.xlsx`): 9 sections, 34 lines, 8
materials-per-unit rows. **Every line matched the Excel** (codes, work, units, quantities, client, labour and material
rates; "rmt" became "rm"). Totals right: contract ₹82,06,050, cost ₹61,31,500. Added subcontract rates to 5.1-5.3
(₹1,300 / ₹1,150 / ₹3,500): cost ₹67,34,500, margin ₹14,71,550 (18 %), as worked out by hand. Added cement 8 bags/cum
+3 % to 2.4. Project page shows "₹0 spent of ₹67 L budget"; the 9 sections became 9 schedule activities.

| # | Kind | Where | What happened | Expected | Severity |
|---|---|---|---|---|---|
| 3.1 | Data / setup gap | BOQ → contract | The BOQ's contract value (₹82,06,050) does not reach the project's contract (`/projects/{id}/contract` is still null), which RA bills need: it must be typed again in billing | When there is no contract yet, offer "Use the BOQ total ₹82,06,050 as the contract value" | High |
| 3.2 | Logic | BOQ strip, `/boq` totals | Margin shows "—" (API `margin: null`) while 3 of 34 lines have no cost rate, though contract and cost are known (cost 75 % of contract) | Show the margin on the priced lines, "on 31 of 34 lines", and point at the 3 | Medium |
| 3.3 | UI | BOQ strip at ~800 px (half-screen laptop, tablet) | Figures and labels cut off: "₹82,06,…", "₹61,31,…", "Contr…", "Budg…", "Earn…" (full on a phone and at 1280 px) | Wrap to two rows or shorten to ₹82.1 L at mid widths | Medium |
| 3.4 | UX | Excel import, after "Import 34 lines" | The dialog stays scrolled where the button was: the success message ("34 BOQ lines are in", "Plan the schedule") is off screen and the visible part still says "34 to add", no buttons left. Looks like nothing happened | Close and show the BOQ with a toast, or scroll the message into view and drop "to add" | Medium |
| 3.5 | UX / data | Excel import | The file says "Green Villa … Client: Dr. Anand Krishnan, 3,200 sq ft"; importing it into Palm Grove Villas gave no warning | "This file names Green Villa: import into Palm Grove Villas anyway?" | Medium |
| 3.6 | UX | Edit line; Materials per unit | Empty fields show grey example numbers that read as values: labour "14", material "22" on a tiling line with no rates; "Per cum 8" before a material is picked | Leave empty fields empty, or "e.g. 14" in muted text | Medium |
| 3.7 | UX | BOQ lines with no cost rate | Only a quiet "—" and "cost —"; the section header drops its margin | Mark the line "needs a cost rate" with an Add rate action | Low |
| 3.8 | UX | Materials per unit | No total shown (26 cum × 8 bags + 3 % ≈ 214 bags), unlike Add line's live "₹1,150 × 160 = ₹1,84,000"; the line then shows "Cement 8 bags per cum" without the 3 % | Live total in the dialog; show wastage on the line | Low |
| 3.9 | Logic | Project stage | A new project with no start date is "Running" | "Not started" (or "Won") until it has a start date or the first update | Low |

### Step 7: drawings and documents (project manager) — tested and fixed 23 Nov

Done on localhost (Palm Grove Villas): uploaded the A-101 ground floor plan, the contract summary and the building
permit from the sample kit. Each filed itself (Drawings › Architectural with "1 to ask the architect"; Contract,
locked; Approvals & permits). Uploading the same file twice is refused.

| # | Kind | Where | What happened | Fixed (23 Nov, branch Ad) | Severity |
|---|---|---|---|---|---|
| 7.1 | Data | Upload new revision | A changed drawing whose title block still said "A" was kept as rev A again: two "rev A" | One letter per revision: the button asks for the letter; empty = read from the drawing, the next letter when it repeats one (said in a note); a repeated letter typed, re-uploaded or edited in is refused (409). `next_revision` on GET /documents/{id} | High |
| 7.2 | UX | Revisions list | Plain text: an old revision could not be opened to compare | Rows open that revision; an old one says "Old revision: rev X is the one to build from" with a button to it; "superseded" shown as "out of date" | Medium |
| 7.3 | UX | "Full drawing check" link | Opened an empty upload page on All projects, asking for the same PDF again | Opens `?document=` and checks the kept drawing at once, with "Back to Documents" | Medium |
| 7.4 | UX | Preview | A failed preview showed `{"detail":"Not Found"}` (locally the plain backend app has no /media route; production does) | Preview and download through `GET /documents/{id}/file`; a failure says "The preview did not load" with Try again | Low |
| 7.5 | UX | Same file again | Red error toast | Calm note; the kept one opens (409 now carries `reason: same_file`) | Low |
| 7.6 | Data | Permits | "Valid until" left empty: no expiry warning without typing | Read from a permit PDF's words ("valid up to 31/03/2029", "3 years from the date of issue" + the issue date); shown with how it was read; nothing made up when the paper does not say | Medium |

Not covered: expiry from a photo or scan (no text); no WhatsApp reminder exists for expiring papers (only the banner on
Documents, 30 days before); production's upload size limit for normal routes is not in the repo (Documents says
25 MB, the drawing check 8 MB).
