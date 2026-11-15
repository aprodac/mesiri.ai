# How a site message reaches the BOQ, the schedule and the plan

> As built 15 Nov 2026 (BOQ-01..04). Tracker: [V1_TRACKER.md](../plans/V1_TRACKER.md) section BOQ.
> One page for anyone asking "if a supervisor sends X on WhatsApp, what moves?"

## The chain

```
WhatsApp / dashboard
  "400 sqft plastering done, Green Villa"
        │  record_work  →  POST /progress/activities
        ▼
  activity + activity_quantities                                   (progress/router.py)
        │  BOQ-01  place_new_work: clear line → linked;            (progress/boq_router.py)
        │          unclear → "Which BOQ line?" list → one tap
        ▼          PUT /progress/activities/{id}/quantities/{qid}/boq-line
  BOQ line "done"  (counted_work / done_by_line: one count)
        ├──► Schedule (Gantt) progress per section, late / behind, forecast finish   (schedule/store.py)
        ├──► Cost: earned = done × budget rate; variance green / amber / red        (costing/router.py)
        ├──► Material plan: work left × materials per unit, over the schedule dates (materials/plan.py)
        └──► Reports: done against plan in the weekly / monthly report and the owner's brief

  "6 masons, 4 helpers today"  → attendance → site-day-trade groups
        │  BOQ-02  auto_split: a group nobody split goes on the lines that site's   (costing/labour.py)
        │          work went to that day (the trade's own work first, else evenly)
        ▼
  labour cost per BOQ line (`auto` until a person splits it)

  "shuttering not ready, slab delayed" → POST /progress/issues
        │  BOQ-03  activity_for_issue: placed on the section its words name         (schedule/logic.py)
        ▼
  schedule activity: open_issues + the newest 3 (`issues`); never moves a date

  Office, Planning › Material plan › "Fill N lines"
        │  BOQ-04  standard_norms.suggest: usual materials per unit for M20,       (progress/standard_norms.py)
        │          brickwork, plaster, steel, tiles, paint, in the company's units
        ▼
  boq_material_norms → the material plan fills itself in
```

## The rules, in one place each

| Decision | Where | Rule |
| --- | --- | --- |
| Which BOQ line a work quantity is on | `progress/boq.py` `suggest_line`, `line_choices` | Same unit only. Most shared words wins, own section breaks a tie; a remaining tie is never guessed. Up to 3 lines offered to tap. |
| Who may put work on a line, or see where it went | `boq_router.set_work_line_checked`, `progress/router.boq_seen_by` | Only the roles that see the BOQ page (owner, admin, finance, PM: `may_view_expenses`), on the BOQ page or by a WhatsApp tap. A site role's clear work is still put on its line, but the reply names no line and asks nothing (BOQ-01b). |
| When a clear line is NOT used | `boq_router.place_new_work`, `AUTO_LIMIT` | The quantity would take the line past 110% of planned: asked instead, saying why. Filler words ("for", "done", "work") never decide a match (`boq.FILLER`). A line put on by itself offers "Change BOQ line" (the other lines that fit, and "Not on the BOQ"). |
| A day's labour on lines | `costing/labour.py` `auto_split` + `costing/router.py` `_allocations` | A known trade (masons, bar benders, carpenters…) goes only to lines it does; none worked that day: stays "not on a BOQ line". Helpers share every line worked. No line takes more than 2× the labour budget its work earned that day (`EARNED_CAP`); the rest stays off. Worked out on read for the current week; a closed week's split is stored (`source = 'auto'`, migration 0554) so it never moves. A person's split always wins; "on no line" is remembered (`labour_boq_day_marks`). |
| Which activity an issue holds up | `schedule/logic.py` `activity_for_issue` | Words of the issue vs the section's name and its lines; its own site or no site; not done; a tie goes to the one running today, else no guess. Issues saved with no activity are placed on read (nothing written); those still on none are counted (`issues_on_no_activity`) and linked from the Gantt. |
| Confirming the automatic labour split | `approvals/inbox.labour_splits`, `GET /cost/projects/{id}/labour?to_confirm=true` | The last 7 days' auto splits and labour on no line, per project, in "waiting for you" (BOQ roles); the Budget page's "Labour to check" has Confirm; on WhatsApp "yes" is `put_labour_on_boq` with the same lines. |
| Several unclear quantities in one message | `whatsapp.boq_follow_up` (`boq_asks` in state) | Asked one after another; each answer or "Skip (office)" brings the next. |
| Standard materials | `progress/standard_norms.py` | Nominal mixes only; plain "RCC" or M25+ never guessed; a unit that can't be converted is said missing. |

## What WhatsApp can and cannot do here

- It records work, labour and issues, and answers the schedule, the material plan and cost (read).
- It puts saved work on a BOQ line (one tap). That is a work-entry change, not a BOQ change.
- It never writes the BOQ itself: rates, lines, norms, imports (CC-11 guard,
  `test_guard_rates_centres_and_categories_are_not_changed_on_whatsapp`). So BOQ-05 (an Excel BOQ sent on
  WhatsApp) is blocked on Ilan's decision.

## Known limits

- A retried save is told the same BOQ answer and links nothing (BOQ-01c). The dashboard's Tell Mesiri shows the same
  "Which BOQ line?" / "Change BOQ line" lists (it runs the same assistant).

- Work recorded before 15 Nov is not linked by itself: it stays on the BOQ page's "work not on a line" list.
- Standard norms are textbook figures; a civil engineer should look them over for each company.
