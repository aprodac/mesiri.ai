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
| 2 Nov 2026 | Every request that is construction work gets built. A company's request is built **for that company** behind a feature switch and switched on for others from the control panel. | Ilan (relayed by the team) | [request-triage.md](architecture/request-triage.md) (TM-34) |
| 2 Nov 2026 | **No owner's ok is needed to switch a feature on** for a company, attendance, payroll, workforce and money included. | Ilan | TM-34 |
| 2 Nov 2026 | Requests that are not construction work are **declined politely**, with what Mesiri does instead. | Ilan | TM-34 |
| 2 Nov 2026 | A demo company can be reset in one tap (control panel, platform admins, demo companies only). | Ilan | SA-30 |
| 2 Nov 2026 | "Is this how you want it?" previews are **on** in production. | Alan (relayed) | TM-33 |
| 2 Nov 2026 | The team bot builds on its own server (warm build copy), not only in cloud sessions. | Ilan | TM-29 |
| 2 Nov 2026 | "mesiri bad ux" / "mesiri fix this / fix it" is an explicit command: the code always passes it to the team. | Ilan | WA-130, TM-35 |

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
