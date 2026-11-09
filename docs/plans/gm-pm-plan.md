# GM / Project manager workspace: plan (Nov 2026)

> **Status:** plan written 9 Nov 2026, asked in session ("cover the GM / project manager part first, a very good,
> rich UX"). Tracker items `GM-01`..`GM-10` in [V1_TRACKER.md](V1_TRACKER.md). Absorbs NXT-08 (approvals
> inbox), CC-12 (Project cost and Today screens), CC-23 (over-budget alerts) and NXT-10 / ST-10 (lookahead):
> those rows now point here instead of being built twice.
>
> **Mockup (example data, clickable):** [GM workspace](https://claude.ai/artifact/3TCbPEbJRM5YPFHBV5DPLf).
>
> Product judgment from the code and the module map, not from GM interviews. Show GM-01 and GM-02 to a real GM
> before building past them.

---

## 1. Who the GM / PM is and what they ask

The GM (or a project manager with several sites) does not type into Mesiri. Site engineers do. The GM **reads,
decides and chases**. Their day:

| When | Question | Today in Mesiri | Gap |
|---|---|---|---|
| 8 am, phone | "Is anything on fire? What is waiting for me?" | Nothing in the morning; must open each page | **Morning brief** (GM-08) and **Waiting for you** (GM-01) |
| 9–11 am, office | "Which site is behind, which is losing money?" | Today (reporting only), Cost overview, Schedule: three pages, three projects each | **Command centre**: one row per project, every signal (GM-02) |
| When a site is red | "Why? What do I do about it?" | Must open BOQ, Schedule, Materials, Issues separately | **Project cockpit**: the reasons in one place, each linking to the register (GM-03) |
| Approving all day | "Approve the cement request, the concrete team's bill, the JCB bill" | Each in its own page; yes on WhatsApp for some | **One inbox**, keyboard and swipe, batch where safe (GM-01) |
| Monday meeting | "What is this week's plan per site; what slipped last week?" | Monday note on WhatsApp (ST-06) only | **This week** board (GM-05) and **Review mode** (GM-07) |
| Chasing | "Who is fixing the water problem, since when?" | Issues have no owner or due date | **Issue owner + due + chase** (GM-06) |
| Evening | "How did today go?" | Evening cost card (CC-11), delay note (ST-06) | Kept; linked from the brief |

**The rule for every screen:** lead with the answer, then the reason, then the register. A GM must get the
answer in five seconds and the reason in one tap. The registers stay where they are, one level down.

## 2. Investigation: what already exists (`main` at `9635671`, 9 Nov)

| Need | Exists | Reuse |
|---|---|---|
| Site reporting today | `GET /dpr/site-days` (BE-08), `TodayPage.tsx` | Command centre "reported" column |
| Cost per project | `GET /cost/portfolio` (CC-19), `/cost/projects/{id}/variance`, `/budget`, `/materials` (`domains/costing/router.py`) | Command centre cost column; cockpit cost panel |
| Schedule late / knock-on / forecast | `domains/schedule/logic.py` (`assess`, `forecast_end`, `knock_on`, `critical`); `GET /projects/{id}/schedule`; delay note `reminders.delay_message` | Command centre "days late"; cockpit critical path; This week board |
| Material shortage | `GET /projects/{id}/material-plan`, order-by (MP-02, MP-03) | Cockpit "order by" panel; attention feed |
| Waiting items | `material_requests.status = waiting` (`procurement/requests.py`); `expenses.workflow_status = pending_confirmation`; subcontract bills `check_status in (waiting, flagged)` (`subcontracts/store.py`); hire check flags (NXT-13); RA bill drafts (NXT-02); draft POs (MP-03); stock adjustments (BE-12) | Inbox is a **read model** over these; no new approval table |
| Who may decide | `authorization/roles.py`: `may_act_on_material_requests`, `may_manage_money`, `may_view_expenses` … | Inbox shows only what the caller may decide; the decide button calls the module's existing route |
| Issues | `fetchAllOpenIssues`, Issues page, severity | Add owner + due (additive) |
| WhatsApp | v3 tools `ALLOWED` + `SOP.md`; evening cost card (CC-11); delay note (ST-06) | "What is waiting for me?", morning brief |
| Approvals domain | `domains/approvals/` empty | The inbox read model goes here |

Nothing here needs a second copy of any table, API or workflow.

## 3. The screens

### GM-01 Waiting for you (approvals inbox; was NXT-08)
- One list, newest-urgent first, grouped **Today / Older than 2 days / Flagged**. Each row: kind chip, project and
  site, who asked, what (one line, e.g. "Cement OPC 53 × 250 bags"), the money, age, and **the one fact that
  decides it** (stock on hand for a request; measured vs billed quantity for a subcontract bill; hours on site vs
  hours billed for a hire bill; budget left on the BOQ line).
- Detail panel on the right (sheet on phone) with the photo / bill and the existing decide buttons (Approve,
  Reject with reason, Change quantity). Keyboard: `j`/`k` move, `a` approve, `r` reject, `o` open the source page.
- **Batch approve** only for rows with no flag (e.g. five small requests within budget). Flagged rows one by one.
- Counts in the sidebar badge and the page title. Empty state: "Nothing waiting. 14 decided this week."
- Phone: swipe right approve, left reject (asks the reason). WhatsApp: "what is waiting for me?" lists them with
  buttons (v3 `ALLOWED` + SOP rule); the decision uses the existing decide tools.

**As built (9 Nov 2026).** `domains/approvals/inbox.py` (one pure row builder per source, plus the collector) and
`router.py`: `GET /approvals/inbox` (`project_id`, `kind`) and `GET /approvals/inbox/count`, mounted in all three
apps (backend, the assistant's web app, the agent's API app). Five sources, each kept to what the caller may decide
by **that module's own rule**: material requests waiting with no open order behind them (`may_act_on_material_requests`;
Materials switch), subcontract bills waiting or flagged (`subcontracts.router.waiting_bills`, now the one rule that
`/subcontracts/bills/waiting` also uses), work a subcontractor reported (`proposed` measurements; whoever may record at
that site), RA bill drafts (`may_manage_money`), unit sizes nobody knew (`may_set_unit_conversions`; Materials switch).
Each row: title, where, from, since, amount (money roles only; a request's is an estimate at the last rates), the
deciding `fact` with a tone, and a group: flagged, waiting over 2 days, recent.
**Left out, on purpose:** purchase orders (no draft state), stock adjustments (no approval step), expenses (they wait
only as subcontract bills: one row, not two), hire bills (NXT-13 checks them but they have no approve / reject state
yet, so they could never leave the list; they join when the hire check gets a decision).
Dashboard: Site > **Waiting for you** (`/site/approvals`, `ApprovalsPage.tsx`, `lib/approvals.ts`), in the sidebar
with a yellow count badge; tiles, kind tabs, grouped list, detail panel with the module's own buttons (a reason field
where the module needs one), `j` / `k` / `a` / `r` / `o`, a bottom sheet on phones. Batch (D-GM2, narrowed): only
"Confirm" on unflagged work to confirm; a request's "ordered" and a bill's approval stay one at a time (a bill needs a
reason; "ordered" is a fact about one request). WhatsApp: v3 `waiting_for_me` + SOP rule 22; deciding uses the existing
tools (`decide_material_request`, `approve_subcontract_bill`, `answer_size_request`); work to confirm and RA bills are
sent to the dashboard page, never said done in chat.

### GM-02 Command centre (GM landing; part of CC-12)
- Top strip: **sites reporting today 9/11**, **waiting for you 7**, **red items 4**, **projects late 2**.
- One row per project (expand to its sites), worst first: health dot; schedule (on time / 6 days late, forecast
  handover); cost (earned vs spent, green / amber / red, D-CC6 thresholds); today (reported / not yet / no work);
  open issues (oldest age); waiting count; next order-by date. A 14-day colour strip shows the trend.
- Click a cell to open the cockpit at that panel. Filter: my projects / all; stage (Running only by default).
- Money columns only for `may_view_expenses`; a site engineer never lands here (D-CC4 stays).

### GM-03 Project cockpit (project home; part of CC-12)
- Header: stage, handover date planned vs forecast, % done (BOQ earned), % spent, health.
- **"Why is it red" panel** first: the top three reasons in words, each with the number and a link
  ("Plastering 2nd floor: 18% over labour budget, 3 days late; pushes Painting 4 days").
- Panels: Schedule (critical path, late activities and what they push), Cost (variance by cost centre, top red BOQ
  lines), Materials (order-by in the next 7 days, shortages), Labour and machines (today vs the week's average,
  idle machine hours), Issues (open, owner, age), Waiting for you (this project only).
- Every number links to the register that explains it.

**As built (9 Nov 2026).** Dashboard only, no new API: `/projects/:id/cockpit` (`ProjectCockpitPage.tsx`) reads each
module's own route as the person (schedule, budget vs actual, material plan, site days, open issues, machine logs,
Waiting for you and Attention narrowed to the project), so every figure is the module's own and a panel the role may
not see says so instead of a number. Header: stage, client, Schedule / BOQ / Setup. Tiles: handover (forecast against
the contract date), work done (earned of the BOQ), spent (against the work: "points ahead"), committed. **Why it is
red / amber**: this project's top three attention alerts (GM-04) with their buttons. Panels: schedule (mini Gantt,
today line, critical tag, late outlined), cost by kind (spent against earned, forecast over / under), order in the
next 7 days, today on site (what each site sent, machines' hours, idle and breakdown), open issues (oldest first, who
is on it), waiting on this project. Ways in: **Cockpit** on the project list and the project's setup page (the old
"Open" is now "Setup"), and the project name on each Attention alert. Not done here: the command centre landing
(GM-02, D-GM1).

### GM-04 Attention feed and alerts (was CC-23, widened)
- One feed of things that crossed a line: BOQ line or project over budget, site not reported by 6 pm, issue open
  more than 2 days with no owner, material order-by tomorrow, activity slipped onto the critical path, hire bill
  over the recorded hours. Each says what crossed, by how much, and the action.
- Dashboard: the bell and Command centre's "red items". WhatsApp: only the critical ones, batched, max 3 a day per
  person (no spam). Each alert computed from existing reads; one small table `attention_seen` for read / snoozed.

**As built (9 Nov 2026).** `domains/attention/` (`rules.py` pure, one rule per signal; `feed.py`; `router.py`):
`GET /attention` (`project_id`), `GET /attention/count`, `POST /attention/snooze` (`key`, `days` 1-7),
`DELETE /attention/snooze/{key}`; mounted in all three apps. Each signal is read through **its module's own route
function as the caller**; a route that refuses (role, project) is skipped, so who sees what stays the module's rule
(SEC-01; D-CC4: a site engineer's cost alerts have quantities and man-days, never rupees). Signals: handover forecast
after its target (bad); a project's forecast at completion red against its budget (bad; the cost portfolio, CC-19,
so the dashboard and the alert agree; owner, admin, finance, PM); a late activity (bad on the critical path, else warn); a red BOQ line over the last 7 days
(bad; Cost control switch); a material to order today (bad) or by tomorrow (warn); a working site with nothing by its
project's reporting cut-off (default 18:00, warn); an issue open 2+ days (bad if high / critical; says whether anyone is
on it, from `assigned_user_id`); a hire bill above its log (warn; Equipment switch). At most 3 of one kind per project,
the last saying how many more. Snoozes: migration **0533** `attention_snoozes` (person, key, until; additive, RLS):
"Not today" hides an alert for that person until tomorrow; still true then, it is back; "Show again" undoes it.
Dashboard: Site > **Attention** (`/site/attention`) with a red sidebar badge (act-now count, refreshed every 5 min).
WhatsApp: v3 `attention` + SOP rule 23 for the general question only; one-thing questions keep rules 15, 16, 20, 22.
**No new WhatsApp push**: the order-by note (MP-03), the delay note (ST-06) and the evening cost card (CC-11) already
send these; a fourth push would repeat them. The morning brief (GM-08) will carry the act-now ones.
**Cost:** one call per source per project (schedule always; cost and plan only for projects with a BOQ): ~27 ms for
2 projects locally; not measured at 20+ projects (a risk: cache or batch if it grows).

### GM-05 This week (lookahead; was NXT-10, ST-10)
- Board per site, Mon–Sat columns: activities from the schedule due this week (ST-04) plus free-text tasks.
  Work updates from WhatsApp tick them (planned item / activity link from CC-04). Saturday: what slipped,
  carried to next week with a reason. The Monday note (ST-06) becomes this board's message.

### GM-06 Issue owner, due date, chase
- An issue gets an owner (a team member) and a due date; overdue issues rise in the feed; "remind" sends the owner
  a WhatsApp nudge. Additive columns on issues. Closing from WhatsApp stays as today.

**As built (9 Nov 2026).** The owner is the existing `site_issues.assigned_user_id` (nothing set it before); migration
**0534** adds `due_on`. `PUT /progress/issues/{id}/owner` (`assigned_user_id` or `assigned_user_name` as said, `due_on`;
either may be cleared) and `POST /progress/issues/{id}/remind` (`domains/progress/issue_owner.py`). Anyone who can
reach the issue may put someone on it; the person must work on its project (member, or reaching every project by role
or grant, the shared rule). A name is matched among them (full name, first name, start); several or none: the API says
who. The person is told on WhatsApp once per owner and date; "Remind" once a day per issue; both through the
notification queue, waiting for their 24-hour window (no template). Attention (GM-04): past its date the issue is
**Overdue** (act now) and says who said by when. Dashboard: a "who is on it" chip on each open issue (person, date, red
once overdue) with Remind; the cockpit's issues say who. WhatsApp: v3 `assign_issue`, `remind_issue_owner`, SOP rule 24.

### GM-07 Review mode (Monday meeting)
- Full-screen, one project per page, arrow keys: last week vs plan, cost colour, top three reasons, next week's
  board, decisions taken (typed in the meeting, saved as notes on the project). Export the pack as PDF using the
  DPR renderer.

### GM-08 Morning brief on WhatsApp
- 8 am to GM / PM (company setting): sites expected today, waiting for you (count + top 3 with buttons), anything
  red overnight, what must be ordered today. One message, three languages, same template rules as the DPR.

### GM-09 Compare sites
- Two to four sites side by side: rate of progress per BOQ trade, labour productivity (units per man-day), cost
  per unit. Answers "why is Marina's plastering costing more than Green Villa's?".

### GM-10 Phone layout for the GM screens
- Command centre as stacked cards, inbox with swipe, cockpit panels as an accordion; the bottom bar has
  Today / Waiting / Projects / Alerts.

## 4. Build order

| # | Item | Why this order | Needs approval? |
|---|---|---|---|
| 1 | **GM-01** Waiting for you | Daily pain, reads existing statuses, no blocker | No |
| 2 | **GM-04** Attention feed | Small, reads existing numbers | No (one additive table) |
| 3 | **GM-03** Project cockpit | As a new page under the project, linked from Projects | No, as long as it is not the landing |
| 4 | **GM-02** Command centre as landing + sidebar | The navigation restructure | **Yes: D-CC5 (shared layout)** |
| 5 | **GM-08** Morning brief | Needs GM-01 and GM-04 | Meta template outside 24 h is an ops task |
| 6 | **GM-05** This week | Builds on ST-04 / ST-06 | No |
| 7 | **GM-06** Issue owner | Additive migration | No |
| 8 | GM-07, GM-09, GM-10 | Polish after a GM has used 1–6 | No |

## 5. Backend, API, database, frontend

- **Backend:** `domains/approvals/` gets `inbox.py` (one function per source, each returning the same row shape;
  filtered by the caller's projects and decide rights) and `router.py`. `domains/costing/` and
  `domains/schedule/` gain nothing new except a shared `project_health()` read used by GM-02 and GM-03.
- **API (new, read):** `GET /approvals/inbox?project_id&kind`, `GET /approvals/inbox/count`,
  `GET /gm/command-centre`, `GET /projects/{id}/cockpit`, `GET /attention`, `POST /attention/{key}/seen`.
  Decisions keep calling the existing routes (request decide, expense confirm, subcontract bill check, hire check…).
  Batch approve = the client calls the existing route once per row; no batch route on the server in V1.
- **Database (additive only):** `attention_seen` (user, key, seen / snoozed until); `issues.owner_user_id`,
  `issues.due_on`; `lookahead_tasks` for the free-text lines (GM-05). RLS like 0503 onwards. Check the migration
  head right before writing one.
- **WhatsApp (v3):** `waiting_for_me` read tool in `agent_api/tools.py` `ALLOWED`, one SOP rule; morning brief as a
  reminder-pass message like ST-06. No workflow, router or word list.
- **Frontend:** `ApprovalsPage.tsx` (planned page `/site/approvals` turns built), `CommandCentrePage.tsx`,
  `ProjectCockpitPage.tsx`, `AttentionBell` component; module-map rows updated. Existing tokens and components
  (`StatStrip`, `DprSection`, chips, the Requests page's detail panel and phone sheet). No new UI library.

## 6. Risks

- **Duplicating each module's buttons.** The inbox must call the module's own route and show its own wording;
  a decide rule lives in one place only.
- **Alert spam.** Max per day, batching, snooze; WhatsApp only for critical.
- **Slow landing page.** The command centre reads several sources per project; one SQL per source over all
  projects, not per project; target < 400 ms for 20 projects; cache 60 s.
- **Money shown to the wrong role.** Every money field goes through `may_view_expenses` (SEC-01); a test per page.
- **Navigation change** (GM-02 as landing) affects every user: waits for D-CC5.

## 7. Testing strategy

Unit: each inbox source and alert rule (pure functions). Contract: inbox only lists what the caller may decide;
engineer gets 403 on money; counts match the rows. Dashboard: `tsc`, `oxlint`, `vite build`; Playwright screenshot
at phone and desktop width. WhatsApp: a golden case for "what is waiting for me?" in three languages.

## 8. Rollback

Each item ships behind the page being in `module-map.ts`; reverting the commit removes the page. The new tables are
additive and unused by anything else; a down migration drops them. The landing change (GM-02) is one route default.

## 9. Labour isolation

No change to Labour, Attendance, Payroll or Workforce. GM-09 reads attendance counts only, through the existing
read routes.

## 10. Success criteria

A GM answers "what is waiting for me, which site is behind and why" in under a minute without opening a register;
approvals decided per day rise and their age falls; issues open more than 2 days with no owner go to zero.

## 11. Decisions needed (default in **bold**)

| # | Question | Default |
|---|---|---|
| D-GM1 | Make the Command centre the landing page for owner / admin / PM (this is D-CC5) | **Yes**: needs Ilan |
| D-GM2 | Batch approve allowed? | **Yes for unflagged rows only** |
| D-GM3 | Morning brief time and who gets it | **8:00, owner + admin + PM, off per person** |
| D-GM4 | Alerts on WhatsApp | **Critical only, max 3 a day per person** |
