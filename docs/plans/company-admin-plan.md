# Company admin: activity log and handover (ADM-01..03)

> Module 22 (User Management & Administration) of the capability framework, Adarsh's #2
> ([gap analysis](capability-framework-gap-analysis.md)). Decided in session by Ilan, 9 Nov 2026.

## Decisions

| # | Decision |
| --- | --- |
| D-A1 | **Every change is recorded in one place, at the API** (not in each module): who, web or WhatsApp, the action, the record, when. No request bodies (amounts, numbers, notes stay in their own tables); no before / after values in V1. |
| D-A2 | **The owner and admins read it** (`may_read_activity_log`), for the whole company. Nobody edits or deletes an entry. |
| D-A3 | **Handing over moves open tasks and schedule activities**, only where the new person reaches the project. Deactivating stays the Team page's own action. |

## Activity log (ADM-01, ADM-02)

- **Recorder** `backend/src/mesiri/http/activity.py`: a pure ASGI layer on the three apps that serve the
  dashboard's API: `http/app.py` (backend), `runtime/lifecycle.py` (production), `agent_api/app.py` (WhatsApp v3,
  source `whatsapp`). It logs a POST / PUT / PATCH / DELETE that returned 2xx with a company login; not public
  routes, platform admins (their log is `admin_audit_log`, BE-05), sign-in, the webhook (`SKIPPED`).
- **What a row says:** the action from the route's function name (`submit_ra_bill` → "Submit RA bill"; a bare verb
  takes the record kind: "Create client link"; `put_` reads "Save"), the record kind from the path segment before
  an id, the record id from the path or the reply, its ref / code / number / title / name from the reply.
- **Not a change:** a route that never saves (`@saves_nothing`: import previews, the drawing reader, the subcontract
  bill check) or a reply that says it saved nothing (`mark_saved_nothing`: schedule and handover previews). A new
  preview route must use one of them.
- **Never fails a request:** the row is written after the reply, in its own transaction; an error is a log warning.
- **Table** `activity_log` (migration 0536, additive, tenant RLS).
- **Read** `GET /activity` (`domains/audit/activity_router.py`): person, days (company calendar), web / WhatsApp,
  kind, words, `before` cursor. **Page** Settings › Activity log (`/settings/activity`).

Not covered: classic WhatsApp (the old pipeline writes without the API) until every customer is on v3; changes a
super admin makes in the control panel (BE-05's own log); before / after values.

## Handover (ADM-03)

`POST /users/{user_id}/handover` `{to_user_id, preview}` (`domains/users/handover.py`), owner and admins
(`may_hand_over_work`). Each task moves through the tasks module's own reassign (`update_task`), so its rules and
its history apply; schedule activities (`work_packages.assigned_user_id`) move in one update. The new person's real
access (`AuthorizationService`) decides what moves; the rest is listed as staying, with the project. Inactive,
self or another company's person are refused. Web: "Hand over open work" on the person's page.

Note: nothing in the app sets `work_packages.assigned_user_id` today (it is shown on the schedule when set), so the
activities half usually moves nothing until assigning activities to a person is built.

## Rollback

Revert the commits; `alembic downgrade 0535` drops the log table (nothing depends on it). The handover changed task
assignees through the normal edit, recorded in each task's history, so it can be reversed by handing back.
