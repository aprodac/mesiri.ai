# Tasks: who does what, by when (TSK)

**Status:** TSK-01 built 9 Nov 2026 (the module, tables `tasks` / `task_events` in 0533, the API under `/tasks`);
TSK-02 built 9 Nov (`06469c90`): the module on the web (sidebar group, `/tasks`, task panel, new task dialog) and
`GET /tasks/options`. TSK-03 built 9 Nov (`97662f73`): tasks from issues and the schedule, place, BOQ line with
progress from the BOQ's own count (per site; not per place yet), migration 0537. **Web only for now** (Adarsh, 9 Nov 2026: "now only want to be web, dont need in whatsapp"):
TSK-04 (WhatsApp tools) and TSK-05 (WhatsApp morning card and overdue note) are deferred, with TSK-10 and TSK-11
that build on them. TSK-12 built 9 Nov: a photo or PDF from the web, with a comment or by "Done with photo" (the expense-bill
rule: shrunk in the page, 700 KB, checked against its bytes, kept under `org/{org}/tasks/{task}/`). TSK-06 built 9 Nov: sidebar counts (My tasks: mine open,
orange; Overdue: late, red; the closed drawer shows the red one first) and a My tasks card on Today (mine, late first,
and how many are late for others), both from `GET /tasks/summary`, which now takes the picked project. TSK-07 built 9 Nov:
[the walkthrough](../training/tasks/tasks-walkthrough.md) (web only, real screenshots). Every web item is built;
what remains is the deferred WhatsApp work and the Later items (TSK-08..11). Sections 7 and 8 below describe the deferred WhatsApp work and stay as the design for when it comes. **Tasks is its own module** (`tasks` switch, own sidebar group, own
routes under `/tasks`), asked in session by Adarsh on 9 Nov ("want new module proper"), the same way Cost control
became one (CC-17). Tracker section **TSK** in [V1_TRACKER.md](V1_TRACKER.md).
**Why now:** module 05 "Task & Work Management" is the only module in Phase 1 of the Capability Framework with
nothing built (see [capability-framework-gap-analysis.md](capability-framework-gap-analysis.md)). Today
`/planning/tasks` is a placeholder page.

---

## 1. Objective

The PM or site engineer gives work to a person ("Arun: tie steel for grid B by Thursday") on WhatsApp or the web.
The person gets it on WhatsApp in the morning and closes it with a photo. Anything late goes to the PM. Nobody has
to open the dashboard to keep it moving.

## 2. Scope

**In (V1):**

- **A module of its own:** `tasks` in the module catalogue, on by default, switched off per company from the
  control panel; its own sidebar group and pages under `/tasks`; its API refuses with `MODULE_DISABLED` when off,
  and the WhatsApp tools follow the API.
- A task: title, notes, project, site (optional), who it is for, due date, priority, status, and optional links to
  a place (floor or room), a schedule activity (BOQ section), a BOQ line with an expected quantity, or the Issue it
  came from.
- Status: open → doing → done, or blocked (with a reason), or cancelled; reopen a done task.
- History on each task: created, changed, status moves, comments, photos (who, when).
- Web: a Tasks page (replaces the placeholder), a task panel, "Make a task" from an Issue and from a schedule
  activity, my open tasks and overdue counts in the sidebar.
- WhatsApp (v3): create, list, change status and comment, with the message's photo kept on the task.
- Reminders on WhatsApp: a morning card per person (due today, overdue, this week) and a daily overdue note to the
  person who gave the task and the project's PM.
- Progress for a task linked to a BOQ line: worked out from the work site recorded on that line (and place) since
  the task started. Never typed, the same rule as the schedule.

**Out (later, tracked as TSK-08..TSK-11):** subtasks, recurring tasks, checklist templates (the base for Quality,
module 16), tasks from meeting minutes (module 20), tasks for a subcontractor's own contacts on WhatsApp, task
dependencies, time spent.

## 3. Business value

- The supervisor has a list every morning, so less time is lost waiting to be told what to do.
- The PM sees what is late without calling anyone; late tasks find them.
- An Issue becomes someone's job, with a date, instead of staying open.
- Closing a task with a photo is a record for the client and for disputes.
- Later: quality checklists, snags, RFIs and meeting action items are all "a task of a kind", so modules 16, 17, 20,
  26 and 28 become smaller.

## 4. Decisions (my recommendations, not yet confirmed)

| # | Question | Recommendation | Why |
|---|---|---|---|
| D-T1 | A new module switch `tasks`? | **Yes** (decided by Adarsh, 9 Nov): its own module, **on by default** for every company (in `V1_MODULES`, like Equipment and Cost control) | The module catalogue in `organizations/settings.py` is a shared component. Same path as CC-17: done on the session's request and **named in the phase report for Alan to review** |
| D-T2 | Who may create and assign? | Owner, Admin, PM and Site Engineer on the project. Anyone on the project may read. The assignee, the creator and managers may change status and comment. Only the creator and managers may cancel | Same project scope as the rest (`auth.project_scope`). No new roles and no change to `authorization/` |
| D-T3 | Who can a task be for? | A person in the company (a user), or a subcontractor (a vendor of kind subcontractor), or a team named in words ("bar bending team") | Workers are not users. A vendor or team task shows on the web; only a user gets WhatsApp in V1 |
| D-T4 | Does closing a task record work done? | **No.** It reads progress from work site already recorded | Recording work twice would double the BOQ progress. "Plastering R2 done" stays a work report, and the agent offers to close the matching task |
| D-T5 | Morning card time | 08:00 company time, with the other morning reminders | No new setting. Held until the WhatsApp window opens, like the schedule notes |
| D-T6 | Task number | `T-1`, `T-2`, … per project | Short enough to say on WhatsApp ("T-14 done") |

## 5. Database work (one additive migration, `0533_tasks_module`)

Check the head right before writing it. Today it is `0532_accounting_settings`; confirm there is no fork.

```sql
CREATE TABLE tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
  number integer NOT NULL,                       -- T-<number>, per project
  title text NOT NULL,
  notes text,
  status text NOT NULL DEFAULT 'open',           -- open, doing, blocked, done, cancelled
  priority text NOT NULL DEFAULT 'normal',       -- normal, high, urgent
  due_date date,
  assignee_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  assignee_vendor_id uuid REFERENCES vendors(id) ON DELETE SET NULL,
  assignee_team text,
  place_id uuid REFERENCES location_nodes(id) ON DELETE SET NULL,
  work_package_id uuid REFERENCES work_packages(id) ON DELETE SET NULL,
  planned_item_id uuid REFERENCES work_package_planned_items(id) ON DELETE SET NULL,
  expected_quantity numeric(14, 3),
  site_issue_id uuid REFERENCES site_issues(id) ON DELETE SET NULL,
  blocked_reason text,
  started_at timestamptz,
  done_at timestamptz,
  done_by uuid REFERENCES users(id) ON DELETE SET NULL,
  source text NOT NULL DEFAULT 'web',            -- web, whatsapp
  created_by uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECKs: status, priority, source; expected_quantity > 0; at most one of assignee_user_id / assignee_vendor_id;
          expected_quantity only with planned_item_id
);
UNIQUE (project_id, number);
INDEX (organization_id, project_id, status); INDEX (assignee_user_id, status, due_date);

CREATE TABLE task_events (            -- the history: never updated, never deleted
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind text NOT NULL,                 -- created, changed, status, comment, photo
  from_status text, to_status text,
  text text,                          -- comment, blocked reason or what changed
  media_object_key text,              -- a photo, in the same store as issue photos
  changes jsonb,                      -- for kind 'changed': {field: [old, new]}
  actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  source text NOT NULL DEFAULT 'web',
  created_at timestamptz NOT NULL DEFAULT now()
);
INDEX (task_id, created_at);
```

Both tables get tenant row-level security (`mesiri_tenant()`), the same as 0527.

The same migration switches the module on: `tasks` is added to `organization_settings.enabled_modules` wherever
that list is stored, and those companies are recorded in `tasks_switched_on_0533`, so the downgrade takes it off
exactly there (as 0518 did for Equipment and 0521 for Cost control). Companies with no stored list get it from
`V1_MODULES`.

Downgrade refuses while tasks exist. Additive only, so it needs no approval (CLAUDE.md, rule 2).

## 6. API work (`backend/src/mesiri/domains/tasks/`)

`router.py` behind `require_module("tasks")`, mounted in **all three apps** like `schedule`: `backend/http/app.py`,
the production app `apps/whatsapp-assistant/src/runtime/lifecycle.py` (forgetting it gives 404 in production, as
happened on 7 Nov; `test_production_app_router_mounting.py` checks it), and the agent API
`apps/whatsapp-assistant/src/agent_api/app.py` (so the WhatsApp tools reach it). `store.py` holds the SQL (takes
the connection, never commits). `logic.py` is pure: allowed status moves, overdue, progress, and the card text.

| Method | Path | What |
|---|---|---|
| GET | `/tasks` | List. Filters: `project_id`, `site_id`, `assignee` (`me` / user id / vendor id), `status` (default: not done or cancelled), `due` (`overdue` / `today` / `week`), `q`. Sorted overdue → due date → priority |
| GET | `/tasks/summary` | Counts for the sidebar and Today: mine open, mine overdue, project overdue |
| POST | `/tasks` | Create. Takes the site, place and assignee by id **or in words** (as `/progress/activities` does for places: "Arun", "FF R2"); refused with the choices when the words match none or several. Optional `site_issue_id`, `work_package_id`, `planned_item_id` + `expected_quantity`. Hidden `media_object_key` for a WhatsApp photo |
| GET | `/tasks/{id}` | One task with its history and progress |
| PATCH | `/tasks/{id}` | Title, notes, due, priority, assignee, place, links. Writes a `changed` event |
| POST | `/tasks/{id}/status` | `{status, note?, media_object_key?, file?}`: start, block (reason required), done, reopen, cancel. Only the allowed moves (logic.py) |
| POST | `/tasks/{id}/comments` | `{text?, media_object_key?, file?}`. `file` is a web photo or PDF (`{data_base64, content_type}`, 700 KB, `expenses/bill_file.py`); a WhatsApp key or a file, never both. History says `photo_is_pdf` |

Task numbers are given out under a lock on the project row, so two tasks at the same moment do not get the same
number. A task on another company's project returns 404, and one out of the person's scope returns 403, both
through `auth.project_scope` as in `schedule/router.py`.

**Progress** (`logic.progress`): for a task with `planned_item_id`, the quantity recorded on that line (at that place,
when set) since `started_at` (else `created_at`), against `expected_quantity`. It reuses
`schedule/store.measured_by_line`, widened to take a date and a place. When it reaches 100%, the morning card
suggests closing the task; it never closes it alone.

## 7. WhatsApp (v3): `agent_api/tools.py` `ALLOWED` and `SOP.md`

| Tool | Route | Notes |
|---|---|---|
| `tasks` | GET `/tasks` | "my tasks", "what is pending for Arun", "overdue at Kakkanad" |
| `give_task` | POST `/tasks` | Write (confirmed). `hide=("media_object_key", "source")`, `fixed=(("source", "whatsapp"),)` |
| `task_status` | POST `/tasks/{task_id}/status` | Write. "T-14 done" with a photo; "T-9 blocked, no shuttering" |
| `task_comment` | POST `/tasks/{task_id}/comments` | Write |

SOP rules to add (one short section):

- Someone telling a person to do something by a day ("Arun tie steel grid B by Thursday") → `give_task`, not a work
  report and not an issue.
- Work reported as done ("plastering R2 done 120 sqft") stays `record_activity`. If an open task matches that line
  and place, offer `task_status` done as well, in the same confirmation.
- "Make it a task" after an issue → `give_task` with `site_issue_id`.
- "T-14 done" + photo → `task_status` (the photo is kept).

No new workflow, router or word list (assistant v3 rule).

## 8. Reminders

In `domains/tasks/reminders.py`, called from `application/procurement/alerts.queue_reminders` next to
`queue_schedule_reminders` (one more line there; the same pattern ST-06 used):

- `tasks_morning`: once a day per person with open tasks: due today, overdue, and how many are due this week, with
  `T-` numbers to reply to. Nothing when they have none.
- `tasks_overdue`: once a day to the creator and the project's PM: tasks one day or more late, and who has them.

Only companies with the `tasks` module on are visited. Both use `PostgresNotificationRepository.claim` (at most once per day per person, held until the window opens).
Languages: the three the other alerts use (`alerts.words`).

## 9. Frontend work (`apps/dashboard`)

- `src/lib/tasks.ts`: types, query hooks, mutations (the same shape as `lib/schedule.ts`).
- Built on the page kit in `components/page/` (UX-05: PageHeader, FilterBar, ListDetail, EmptyState) and placed
  in its own sidebar group (placed by the UX-04 story order, next to Planning), so it matches the pages being
  moved onto the kit.
- **The module on the web:** `tasks` in `lib/modules.ts` (`ModuleKey`, `MODULE_NAMES`: "Tasks"); a `tsk()` guard
  in `App.tsx` (`RequireModule module="tasks"`, like `cst()`); its own **Tasks** group in `lib/module-map.ts` with
  `module: 'tasks'`, hidden when the module is off. `/planning/tasks` redirects to `/tasks` and the Planning
  placeholder entry goes.
- Pages in the group: **My tasks** (`/tasks`), **All tasks** (`/tasks?view=all`), **Overdue**
  (`/tasks?view=overdue`), **Done** (`/tasks?view=done`), and later **Templates** (TSK-09, planned).
- `src/pages/TasksPage.tsx` at `/tasks`:
  - Views: **Mine**, **All**, **Overdue**, **Done**. Filters: project, site, person.
  - A quick-add row: title, person, due, then Enter (the rest in the panel).
  - Each row: `T-14`, title, person, place, due (red when late), priority, status, progress bar when linked to a
    BOQ line.
  - The task panel: details you can edit, status buttons (Start, Blocked…, Done with photo, Reopen), history,
    comments and photos.
- Issues: a "Make a task" button on an issue. Schedule: "Make a task" on an activity. Both open the panel filled in.
- `nav-counts.ts`: overdue count on Tasks. Today: a "My tasks" card with a link to Tasks.

## 10. Files expected to change

| New | Changed |
|---|---|
| `backend/migrations/versions/0533_tasks_module.py` | `backend/src/mesiri/http/app.py` (mount the router) |
| | `backend/src/mesiri/domains/organizations/settings.py` (`MODULES`, `MODULE_LABELS`, `V1_MODULES`): **shared** |
| | `apps/whatsapp-assistant/src/runtime/lifecycle.py`, `src/agent_api/app.py` (mount the router) |
| | `apps/dashboard/src/lib/modules.ts` (`ModuleKey`) |
| `backend/src/mesiri/domains/tasks/{__init__,router,store,logic,reminders}.py` | `backend/src/mesiri/application/procurement/alerts.py` (one call) |
| `backend/tests/unit/test_tasks_logic.py` | `backend/src/mesiri/domains/schedule/store.py` (`measured_by_line` takes a date and a place, defaults unchanged) |
| `backend/tests/contract/test_tasks_contract.py` | `apps/whatsapp-assistant/src/agent_api/tools.py`, `SOP.md` |
| `apps/dashboard/src/lib/tasks.ts`, `src/pages/TasksPage.tsx` | `apps/dashboard/src/App.tsx`, `lib/module-map.ts`, `lib/nav-counts.ts` |
| `apps/whatsapp-assistant/tests/...` (tool and SOP cases) | Issues page, `SchedulePage.tsx`, `TodayPage.tsx` (a button or card each) |
| | `docs/plans/V1_TRACKER.md`, `docs/architecture/module-boundaries.md` |

## 11. Risks

| Risk | Mitigation |
|---|---|
| The agent makes a task when the person reported work or an issue | SOP examples for all three; golden cases in the assistant tests; every write is confirmed first |
| Double-counting progress | D-T4: tasks only read measured work |
| Too many WhatsApp messages | One morning card and one overdue note a day at most, none when empty |
| Task numbers clash under load | Numbering under a row lock; unique index `(project_id, number)` as the backstop |
| A site-scoped person sees tasks of other sites | The same scope check the BE-42 fix uses; a contract test for it |
| Overlap with NXT-10 (weekly lookahead) | NXT-10 becomes a view of tasks due this week. Mark it as depending on TSK |
| Adding a module touches the shared module catalogue | Same change shape as CC-17 (three lines in `settings.py`); the module-settings tests and the control panel's switch list cover it; named in the report for Alan |
| The router is forgotten in one of the three apps | `test_production_app_router_mounting.py` and the agent tool drift test fail if it is |
| `measured_by_line` change breaks the schedule | New arguments are optional with today's behaviour as the default; schedule contract tests run unchanged |

## 12. Testing strategy

- **Unit** (`logic.py`): every allowed and refused status move, overdue at the day boundary (company time zone),
  progress with and without a place, the card text (empty, overdue only, three languages).
- **Contract** (Postgres): create / list / filter / patch / status / comment; numbering per project and under two
  concurrent creates; another company's task is 404; out-of-scope project is 403; a site engineer limited to one
  site; an engineer can't cancel someone else's task; a finance user can't create; progress from a recorded work
  update; with the module off every route answers `MODULE_DISABLED`.
- **Module**: the migration adds `tasks` where a list is stored and the downgrade takes it off exactly there
  (down / up checked, as for 0521); the control panel lists the switch; the production-app mounting test includes
  the router.
- **Reminders**: none for a company with the module off; queued once per day per person; nothing for a person with no open tasks; closed and tender
  projects skipped.
- **WhatsApp**: tool drift test (`build_tools` finds every route); SOP cases for give / done with photo / work
  report that matches a task / issue to task.
- **Regression**: the full backend, dashboard and WhatsApp suites from CLAUDE.md; schedule contract tests unchanged.
- **In the app**: the Tasks page in the browser (create, close with photo, overdue colour), Issue → task, Schedule
  → task.

## 13. Rollback strategy

- **Fastest, per company:** switch the `tasks` module off in the control panel. The pages, API, WhatsApp tools and
  reminders stop for that company at once; nothing is deleted.
- **Code:** each TSK item is its own commit; `git revert` it. The router is mounted inside a `try` like the others,
  so the API keeps running without it.
- **Reminders:** reverting the one call in `alerts.py` stops both messages at once.
- **Database:** the migration only adds tables. Rolling back code leaves them unused and harmless. `alembic
  downgrade` refuses while tasks exist (no silent data loss). Drop them only by hand after export, if ever.
- **WhatsApp:** removing the four `ALLOWED` lines takes the tools away; the routes stay for the web.

## 14. Labour isolation

Nothing in Labour, Attendance, Workforce or Payroll changes. A task is for a *user* or a *vendor* or a team in
words, never a `workers` row, and it never reads or writes attendance or wages. Shared code touched: the module catalogue
in `organizations/settings.py` (one new module), `schedule/store.measured_by_line` (optional arguments) and one
call in `alerts.py`.

## 15. Success criteria

1. A PM creates a task on WhatsApp in one message, and it shows on the Tasks page with the right person, site and
   due date.
2. That person gets it in the next morning card and closes it with a photo from WhatsApp; the photo and who closed
   it show in the history.
3. A task one day late is in the overdue note to the creator and the PM, once that day.
4. An Issue becomes a task in two clicks, and the task links back to the issue.
5. A task linked to a BOQ line shows progress that matches BOQ progress for the same line and place.
6. With the module switched off for a company, its Tasks pages are hidden, the API answers `MODULE_DISABLED`,
   WhatsApp says Tasks is not on, and no reminders go out.
7. No reminder goes to someone with nothing open; all verification checks in CLAUDE.md pass before each push.

## 16. Build order (tracker items)

| ID | Item | Size | Depends on |
|---|---|---|---|
| TSK-01 | The `tasks` module (catalogue, switch on by default, mounted in all three apps), tables (0533), `domains/tasks` with list, summary, create, get, patch, status, comments; unit + contract tests | M | — |
| TSK-02 | The Tasks module on the web: own sidebar group, `/tasks` pages (views, quick add, panel, history, photo), module guard, redirect from `/planning/tasks` | M | TSK-01 |
| TSK-03 | Links: from an Issue, from a schedule activity, a place, a BOQ line with progress | M | TSK-01, TSK-02 |
| TSK-04 | WhatsApp v3 tools and SOP section, with assistant tests | S | TSK-01 |
| TSK-05 | Morning card and overdue note | S | TSK-01 |
| TSK-06 | Sidebar counts and the Today card | S | TSK-02 |
| TSK-07 | Walkthrough for the team (what to tell site) | S | TSK-02..05 |
| TSK-08..11 | Later: subtasks and recurring; checklist templates (Quality); meeting action items; subcontractor contacts | — | — |
