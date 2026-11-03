# Decisions

> **Read before starting any task.** One line per decision the owners took, newest first, with who and when.
> A session (Claude Code, the team bot, a person) never re-asks or contradicts a decision here; to change one, an
> owner says so and a new line replaces it (the old line is struck through, not deleted). Details live in the linked
> doc; this file only says *what was decided*.
>
> Add a line whenever Alan or Ilan decides something in chat, in the team group or in a review. Relayed decisions say
> who relayed them.

## Product

| Date | Decision | Who | Details |
|---|---|---|---|
| 3 Nov 2026 | **Labour and Attendance need no approval** from now on: plans that change them build like any other (autobuild and Claude Code sessions); the change is said plainly in the report. Still held for an owner: Payroll, Workforce, migrations that change existing data, secrets/tokens, tenant isolation, login, CI/deploy files and the bot itself. | Alan and Ilan (relayed in session) | CLAUDE.md, `teammate/brain/src/autobuild.js` |
| 3 Nov 2026 | Alan and Ilan **approved the plans waiting for an owner** on 3 Nov: [218], [221], [222], [223], [224]. | Alan and Ilan (relayed in session) | request log |
| 3 Nov 2026 | **The person who asked feels understood:** the team bot may send them, through Mesiri, ONE line of its own words (their problem said back in their language, or what a re-fix found), wrapped in Mesiri's fixed wording, plus one honest "taking longer" note; previews also for bug fixes; "Still wrong" is never answered with a question (the team finds out and tells them). Same locks as previews (switch, token, the request's own sender, v3, 24 h, once per stage); no links, phone numbers or @names in the line. | Owner, in session | TM-69 |
| 3 Nov 2026 | Every build is reviewed by a second Opus session before it is pushed; builds and reviews always run on Opus 5.5; example lines in a plan don't hold it. | Owner, in session | TM-63 to TM-67 |
| 2 Nov 2026 | Every request that is construction work gets built. A company's request is built **for that company** behind a feature switch and switched on for others from the control panel. | Ilan (relayed by the team) | [request-triage.md](architecture/request-triage.md) (TM-34) |
| 2 Nov 2026 | **No owner's ok is needed to switch a feature on** for a company, attendance, payroll, workforce and money included. | Ilan | TM-34 |
| 2 Nov 2026 | Requests that are not construction work are **declined politely**, with what Mesiri does instead. | Ilan | TM-34 |
| 2 Nov 2026 | A demo company can be reset in one tap (control panel, platform admins, demo companies only). | Ilan | SA-30 |
| 2 Nov 2026 | "Is this how you want it?" previews are **on** in production. | Alan (relayed) | TM-33 |
| 2 Nov 2026 | The team bot builds on its own server (warm build copy), not only in cloud sessions. | Ilan | TM-29 |
| 2 Nov 2026 | The team bot's planning turns may run read-only viewing commands without asking (`cat`, `sed -n`, `find`, `diff` …); writing forms stay refused. | Ilan | TM-44 |
| 2 Nov 2026 | The request reference stays in Mesiri's reply when something is passed to the team, shown as "Ref #xxxxxx" (the same reference the team group sees). Never remove it as "internal text". | Ilan (relayed) | TM-21, [205] |
| 2 Nov 2026 | "mesiri bad ux" / "mesiri fix this / fix it" is an explicit command: the code always passes it to the team. | Ilan | WA-130, TM-35 |
| 1 Nov 2026 | ~~Plans build by themselves (autobuild), no "@bot ok". Held for an owner only: Attendance, Payroll, Workforce, migrations that change existing data, secrets/tokens, tenant isolation, login, CI/deploy files and the bot itself.~~ Replaced 3 Nov (Attendance no longer held). | Ilan | TM-18, `teammate/brain/src/autobuild.js` |
| 1 Nov 2026 | **Roles and permissions inside the product** (who may create a project, add a project member, admin vs site engineer) are not held: "those you can do; report it". | Ilan | TM-18 |
| 1 Nov 2026 | Labour is a normal module: changed without asking. | Ilan | TM-18 |
| 3 Nov 2026 | A plan whose planner says it needs an owner's ok is held by the code until "@bot ok <n>"; what the group reads and what the bot does always match. | the team (relayed in session) | TM-48 |

## Architecture

| Date | Decision | Who | Details |
|---|---|---|---|
| 2 Nov 2026 | The assistant is **v3** (one model + one SOP + the dashboard's API as tools). v2 is removed; classic stays only until every customer has moved, then is deleted. | Alan and Ilan (relayed) | [assistant-v3.md](architecture/assistant-v3.md) |
| 29 Oct 2026 | Fix the class of failure at its root, never a one-off patch. | Ilan | [FIX_APPROACH.md](engineering/FIX_APPROACH.md) |

## Process and access

| Date | Decision | Who | Details |
|---|---|---|---|
| 2 Nov 2026 | Claude Code may read **customer photos, screenshots and voice notes** sent to Mesiri, read-only and audited like the SQL reads, to understand and fix requests. Never quoted outside the team. | Ilan | TM-39 |
| 2 Nov 2026 | Staging may hold a **copy of production with names and numbers removed**, to reproduce customer bugs on real-shaped data. | Ilan | TM-40 |
| 2 Nov 2026 | Development tooling approved: a whole-day conversation view, a daily test of the feedback loop, a not-deployed alarm, ops tools kept current with v3, and this decisions log. | Ilan | TM-36 to TM-38, TM-41, TM-42 |
| 19 Oct 2026 | **Autonomous mode**: Claude does not wait for approval between phases; it stops only for the cases listed in CLAUDE.md. | Alan | [CLAUDE.md](../CLAUDE.md) |
| 31 Jul 2026 | Work directly on `main`; verify, pull, combine, push. No feature branches. | Alan | CLAUDE.md |
| 13 Oct 2026 | Work is tracked in V1_TRACKER.md, not Linear. | Alan | [V1_TRACKER.md](plans/V1_TRACKER.md) |
