# ADR: one draft per message, written only on the Save tap

**Status:** P0 done (request 123: docs and tests only). **P1 built** (request 124, 27 Oct 2026, approved by
Ilan: "Yeah let's do it"), behind the company setting `draft_v2` (off for everyone; on only for the TEST company
once the Mesiri team sets it). **P2 built** (request 127, 27 Oct 2026, approved by Ilan in WhatsApp; section 11),
same flag. P3-P4 each need their own owner ok.
**Supersedes:** the patch approach of request 122. **Completes:** the promises of
[ADR-assistant-agent-wrap-not-rebuild](ADR-assistant-agent-wrap-not-rebuild.md) §10, §10b and the
request-90 addendum ("nothing is kept until they tap Save", "one write path").

## 1. Problem

The documents say a worker's message is kept only when they tap Save. The code does not do that:

| | What happens today (`apps/whatsapp-assistant/src`) | Seen as |
|---|---|---|
| a | Agent tools start the old workflow graphs (`journey_gateway.py` ~424 → `workflow_runtime.start`); `_after_run` calls `save_now()` straight away (~449-479). The "card" is Save/Cancel on rows **already written**; Cancel deletes them. | Labour counted before Save; Cancel "undoes" real data |
| b | `workflows/runtime.py` ~281-333 allows ONE pending confirmation per user (`BLOCKED_PENDING_CONFIRMATION`). Work on an open activity waits behind it (`journey_gateway.py` ~508-537, `parked_by="gate"`), so every later write in the turn is "held" (`toolbox.py` ~428-442, ~962-969) and returns one at a time, or never. | Items of one message dropped |
| c | Pending state lives in five places: `workflow_instances`, `fact_reviews` drafts, Redis cards / later / actions / site_wait, and ids inside button taps. | Cards and taps disagree |
| d | Slot answers and `card_plan` "legacy" write without a real card (`save_button.py` ~159-171); a record with no review row counts as confirmed (`fact_review.py` ~83). | Labour auto-saved; Cancel lies |
| e | Card items are stored with empty tool/args (`message_journey.py` ~1720), so `toolbox._update_card` refuses, but the model still says it changed. | "aakki" answered "changed", nothing changed |
| f | The DPR reads through `dpr.py` assembly; "today's labour?" goes through `seeding._seed_labour_query` with its own date resolver and `labour_query_service`. The resolver answers "yesterday" with today. | 8 vs 13 |
| g | Old "Reply YES" prompts still come from `workflows/*/nodes.py` via `held_prompt`. | Mixed Yes/No and Save/Cancel |

Root cause: there are two models of "pending" (write-then-label, and graph-gate) glued together. Patching
a symptom moves the bug. The fix is one model.

## 2. Decision

**One `MessageDraft` per inbound message (or per open card). Tools only add or edit items on it. One card
shows it. Save writes it, once, through the existing domain services. Cancel throws it away, so nothing was
ever written.**

### 2.1 The draft

A draft is an ordered list of typed items:
`labour`, `work`, `material_in`, `material_out`, `issue_open`, `issue_close`, `photo`, `member`, `site`, …
(the types of today's `DraftActionType`s the agent can produce; new types are added the same way).

Each item has: its fields; a **validation state** `ok | needs_answer | unreadable`; and, when
`needs_answer`, the question and its answer options.

### 2.2 Tools add, never write

`save_labour`, `save_work_done`, `save_material_receipt`, `report_issue` … keep their names and arguments
(the model prompt does not change) but become `draft.add(item)` / `draft.edit(index, changes)`. No domain
row is created and no graph runs. The checks the workflows do today (units, site, duplicate labour, open
activity) become **pure validators** the draft calls: `validate(item, scope, lookups) -> ok | needs_answer(question, options) | unreadable(reason)`.
Lookups (open activities, today's labour list) are read-only. No single-active gate exists, so (b) cannot occur.

### 2.3 One card

The card renders the whole draft: one line per item. A question is a **button on the card**
("Replace 13 or add?", "Which unit?"), not a separate Yes/No message. Save is enabled for the items that are
`ok`; an item that is `needs_answer` stays on the card until answered or removed.

### 2.4 Save = one transaction through the existing services

Save tap → for every `ok` item call the domain service that writes it today (labour service, materials,
site log, issues) inside one DB transaction; on any failure nothing is written and the card says which item
failed. **The Labour/Attendance/Payroll/Workforce rules and code are unchanged**: only *when* they are
called changes (on the tap, not on the message). Idempotency key = `draft_id + item_index`, so a double tap
writes once. Cancel marks the draft `discarded`; it never touches a domain table.

### 2.5 Corrections

- Draft not yet saved: edit the item in place; the card is redrawn.
- Draft already saved: create a new draft with a `change` item referencing the saved record; it is saved
  by tap like anything else (existing change/undo services do the write).
- The reply text is **generated from the draft operation's result** (`added`, `edited`, `rejected: reason`),
  never free model text claiming a change. This removes (e) at the root.

### 2.6 Coverage check

After the model's tool calls, code compares *items the model extracted* (its own list of what it understood,
from the tool calls) with *lines on the card*. Anything missing or `unreadable` is listed on the card as
"Couldn't read: …". Nothing is dropped silently.

### 2.7 One read path

Every day or period figure (today, yesterday, this week, DPR, `today_context`, "today's labour?") comes
from `runtime/agent/project_day.py` (project timezone, same site scope) plus the DPR assembly. The
`seeding._seed_labour_query` resolver and `labour_query_service`'s `resolve_date_range` are removed from the
answer path. Counted-sql rules (`fact_review.counted_sql`, `workforce.COUNTED_LINE_SQL`) stay the
definition of "saved".

## 3. Storage decision

**New table `message_drafts`** (additive migration, P1), not an extension of `fact_reviews`.

- `fact_reviews` is an append-only log of the review state of facts that **already exist** (migration 0470);
  its contract is "no row = confirmed". A draft whose facts do not exist yet does not fit, and loosening
  "no row = confirmed" is exactly what causes (d).
- `message_drafts(id, organization_id, user_id, project_id, site_id, source_message_id, status
  [open|saved|discarded], items JSONB, created_at, updated_at, saved_at)`, RLS like the other tenant tables
  (migration 0484). One open draft per user per card; items are one JSONB array (≤ 7 items per card today,
  kept as the cap).
- After Save the saved domain rows carry `source_draft_id` only if a later phase needs it; P1 does not add
  columns to Labour tables.
- Redis cards / later / actions / site_wait and `workflow_instances` for agent turns are replaced by this
  row. They stay for the legacy path until P4.
- Rejected alternative: keep Redis as the store. Lost on restart, not queryable by the control panel, and is
  the "five places" problem again.

## 4. Rollout, flag and rollback

Per-company flag `draft_v2` (company setting, default off). Off = today's behaviour byte-for-byte.
Each phase is its own owner approval and deployable alone:

| Phase | Scope | Rollback |
|---|---|---|
| **P0** (this change) | This ADR and the golden-conversation tests (strict expected failures). No behaviour change. | `git revert` |
| P1 | `MessageDraft`, one card, Save in one transaction for labour, materials, work, issues. Flag on for the TEST company only. Ilan Pro re-tests live. Additive migration. | flag off |
| P2 | Corrections/undo on drafts; the one read helper (fixes 8 vs 13). | flag off |
| P3 | Setup/team/site flows onto drafts (3-Yes add-person, wrong-role card); request 116 catalogue/language work lands on the new card. Security-sensitive (user creation, roles): own explicit ok. | flag off |
| P4 | Flag on for everyone, then delete legacy paths. | `git revert` |

P4 deletes: workflow confirm nodes, the YES/NO fast path, `plan_executor`, `later.py`, `save_first`
auto-save, the legacy `card_plan`, and their tests.

## 5. Risks

- **Labour is on the save path.** P1 touches *how and when* labour is saved, so it needs owner approval at P1
  and a data-identity proof: the same message, saved by tap, must produce the same labour rows as today's
  flow (golden diff of `labour_*` rows).
- Save-in-one-transaction across services: each domain service must accept a caller-owned transaction; where
  one commits internally P1 must add the parameter (a shared-component change, flagged then).
- Report timing changes by design: unsaved drafts no longer count anywhere (already true for readers after
  WA-77); sites whose workers never tap Save report empty.
- Prompt drift: the model still sees today's tool schemas; only the toolbox implementation changes.
- Expected-failure tests are a debt: each phase must flip its tests to passing, or CI (strict) turns red.

## 6. Out of scope

Dashboard behaviour, the DPR layout, the stock model, and any data rewrite. No existing row is changed.

## 7. Acceptance: the golden conversations

`apps/whatsapp-assistant/tests/replay/test_golden_draft_per_message.py` (strict expected failures today):

| Test | Rule | Fixed by |
|---|---|---|
| g1 nothing written before Save (four-part note → one card) | 2.1-2.4, root a | P1 |
| g2 labour alone is a draft that Cancel really discards | 2.4, root d | P1 |
| g3 work on an open activity does not hold the rest of the message | 2.2, root b | P1 |
| g4 a correction never claims a change the draft did not make (placeholder, needs a card store in the replay world) | 2.5, root e | P2 |
| g5 "yesterday" on the labour read path is yesterday (fails today: returns today) | 2.7, root f | P2 |

When a phase makes a test pass, strict xfail fails CI; remove the marker for that test in the same commit.

## 8. Not done in P0

- The tests run the real journey with a **scripted** model; they were **not** run against live Gemini in CI.
  A live variant (marker `provider`, as in `test_agent_replay`) is for P1.
- Request 122's repro list (1-6) was not in the repository, so the tests above come from request 123's
  root-cause map. Map each of 122's repros onto a test (or add one) before P1 starts.
- No implementation, migration or flag exists yet.

## 9. Open questions for the owners (answered, recorded by Ilan Pro on 27 Oct 2026; Ilan can correct them)

1. Is one draft per **message** or per **open card** (several messages in a row → one card)? Proposal: per
   open card, closed on Save/Cancel or after the existing card expiry.
2. Should Save with one `needs_answer` item save the `ok` ones and keep the card for the rest (proposal), or
   block until all are answered?

Answers used by P1:

1. **One draft per open card**: several messages in a row add to the same card until Save, Cancel or the existing
   card expiry (6 hours without a new item).
2. **Save with a `needs_answer` item saves the `ok` items and keeps the card for the rest**
   ("✅ Saved 3 · still need: 6 workers (6 mason)", then the card with its question).
3. Plus: an unsaved draft gets **one** reminder before the report time ("You have 1 card not saved: tap Save or
   Cancel."), so a site does not report empty because nobody tapped.

## 10. P1 as built (request 124)

### 10.1 What exists

| Piece | Where |
|---|---|
| Company setting `draft_v2` (default off; superadmin only) | `backend/.../domains/organizations/settings.py` |
| Table `message_drafts` (additive, RLS, one open row per sender by a partial unique index) | migration `0491` |
| Draft, items, card text/buttons, tap ids, labour "replace or add?" | `runtime/agent/draft.py` (no I/O) |
| Stores: Postgres, and in-memory for tests | `runtime/agent/draft_store.py` |
| Add / Save / Cancel / answer | `runtime/agent/draft_flow.py`, called from `JourneyGateway` |
| One transaction for the Save | `PostgresDatabase.shared_transaction()` |
| Confirm a waiting draft like a Yes (work on an open activity) | `InteractionHandler.confirm_now` |
| The one reminder | `runtime/draft_reminder.py`, a step of the scheduler tick (`automation_runner.py`) |
| "<equipment> breakdown / X problem" is an issue | `runtime/agent/equipment.py` `is_problem_only`, `AgentRunner._problem_only` |

### 10.2 Behaviour with the flag on

- `save_labour`, `save_work_done`, `save_material_receipt`, `save_material_usage`, `report_issue` keep their names
  and arguments. Each call runs the entry's `prepare` (all its lookups and questions, unchanged) and then **adds an
  item** to the sender's open draft. No workflow is started, nothing is written, no `save_now`.
- The pending actions of request 104 (engineer question, the day's conditions, issues to close) are lines of the
  same card; the Save tap runs them **after** the transaction has committed (a message that was sent cannot be
  rolled back); Cancel drops them.
- One card renders the whole draft. A call that cannot become a line is kept on the draft as `unreadable` and shows
  as "Couldn't read: ..." (this covers the call limit, a failed tool, a refusal by `prepare`, a full card). The
  property test `test_property_no_extracted_item_is_missing_from_the_card` checks it.
- A second labour count for the same site and day, when the day already has a count that it repeats, is a question
  on the card ("Today already 13 workers (8 mason, 5 helper). Replace it with 6 workers (6 mason), or add to
  it?") with the buttons Replace / Add. Replace keeps BE-10's rule (latest figure per trade replaces); Add raises
  the repeated trade by today's figure. A second crew that repeats nothing needs no question.
- Labour sent again while a labour item for the same site and day is still on the card merges into it (the same
  trade replaces, another trade adds) -- the rule a card edit always had.
- Save: one `shared_transaction()`: claim the draft (`open -> saved`, once), then for each ready item start its
  workflow, `save_now` (save-first) or, for work on an open activity, `confirm_now`, then `settle_drafts(keep)`.
  Any failure rolls everything back, says which item failed ("Nothing was saved. Couldn't save X: reason"), marks
  that item on the card and leaves the draft open. A second tap finds the draft taken and writes nothing.
- Cancel marks the draft `discarded`. It never touches a domain table, and its words ("nothing saved") are true.
- `update_pending_card` answers that a line cannot be changed yet (P2) and changes nothing; `undo_last` while a
  draft is open cancels the whole draft. After a Save the saved card is kept as before, so "undo that" still works.

### 10.3 What is a "validator" in P1 (and what is not)

The checks the workflow graphs make at save time are **not** re-implemented as pure functions. P1 validates when
the item is added with what already ran before the graph: the entry's `prepare` (context, module switch, site,
material, unit, open activity, worker candidates, the day's existing count) plus two pure checks (the card line can
be worded; the labour day-count question). The graphs themselves still run at Save, inside the transaction. If a
graph then asks something it did not ask at add time, the Save rolls back, names the item and the card keeps it
marked; the answer is to send it again. Moving those graph questions onto the card is later work (P2/P3).

### 10.4 Shared components touched (Module Isolation)

No Labour, Attendance, Payroll or Workforce code changed; no domain service signature changed. Instead of a
caller-owned transaction parameter on each service, one shared mechanism: `PostgresDatabase.shared_transaction()`
makes every `transaction()` opened inside the block (by this database object, in this task or one it starts) join
one connection in a savepoint, taking turns on it; outside the block `transaction()` is byte-for-byte what it was.
Services that join it today, all unchanged: the labour, material, activity / progress update and site issue
handlers and their repositories, `SaveFirstService` (`record_draft`, `settle_drafts`). Not in the transaction (own
engine): the workflow instance store (`workflow_instances`), so a rolled-back Save leaves its instances in state
CONFIRMED / completed with no domain row -- harmless (no sweep runs them; every save mints new instances) but visible.

Other shared changes, all additive: setting `draft_v2`; `InteractionHandler.confirm_now`; one reminder step in the
scheduler tick; `JourneyGateway`, `AgentToolbox` and `AgentRunner` branches that exist only when the setting is on.

### 10.5 Rollout, flag and rollback

Turn on for one company: `PUT /admin/organizations/{org_id}/settings` with `{"key": "draft_v2", "value": true}` as a
platform admin (the control panel's Settings tab shows the value but does not edit it). Turn off the same way with
`false`. Off = today's behaviour; a test proves it (`test_with_the_flag_off_nothing_changes_even_with_a_store_attached`,
and the whole existing replay suite is unchanged). A draft left open when the flag goes off can still be saved or
cancelled by its buttons; it expires after 6 hours. The migration is additive; rollback is the flag.

### 10.6 Known limits of P1

- Report timing changes by design for a company with the flag on: an unsaved card counts nowhere (the reminder is
  the mitigation). The reminder goes out only for projects with `auto_generate_dpr` on, and, outside the 24-hour
  WhatsApp window, is skipped by the existing send rules (no approved template).
- The receipt picture (the combined card image) is not drawn for a draft card.
- The new card lines ("Couldn't read", the replace/add question) are English; the existing label swap for
  Malayalam / Hindi senders does not know them yet.
- A pending Yes/No of a confirm-first flow (expense, transfer) blocks a Save that needs to start a workflow
  ("an earlier question is still waiting"): the item is marked and the card stays.
- The reminder goes out in the half hour before the project's reporting cutoff (until the send deadline); a card
  that would expire before that (6 hours without a new item) is reminded an hour before it expires, in the
  daytime. One reminder per card (`reminded_at`).
- Not verified: a live-model run (the live golden variant is written, marker `provider`, not run); the Save tap
  through WhatsApp itself; delivery of the reminder message (its queueing is tested against a local Postgres, its
  sending reuses the existing notification path). The real-database tests (`tests/integration/test_draft_save_postgres.py`,
  `backend/tests/integration/test_shared_transaction_postgres.py`) were run on a local Postgres 16 and are not run in CI.


## 11. P2 as built (request 127)

From Ilan Pro's live re-test on 27 Oct (draft_v2 on). Ilan chose the proper solution over patches for every
item ("do the proper solution"), so each item below says how its root cause is removed and what is still a limit.
Flag-gated: with `draft_v2` off nothing below runs (item 2's read path and item 5's site rule apply to everyone,
see 11.6).

### 11.1 Corrections (ADR 2.5)

- **Open card:** `update_pending_card` edits the line in place (`draft_flow.edit_item`): the change is merged into
  the item's own tool arguments (`cards.merge_changes`), the entry's `prepare` runs again with every check, and the
  line is redone. Nothing is written.
- **Saved card:** the correction is a new item of kind `change` on the open card (made if there is none):
  "Change today's labour at Green Villa: mason 6 → 5 (total 7)" (`draft.change_line`). It holds the saved entry it
  replaces (`target`: fact type and id, the saved arguments). The Save tap, inside the one transaction, takes the
  saved entry back through the undo "undo that" uses (`save_first.undo_facts`) and writes the corrected entry
  through the entry's own workflow, exactly as an edit of today's open card does (withdraw, then save). If the
  take-back is refused (the day is confirmed) or the write fails, nothing changes and the card says why. A second
  correction before that Save edits the same change line. After the Save the saved card holds the corrected entry
  (and the rest of the card it corrected), so another correction starts from the new figures.
- **The reply comes from the result:** the tool returns `drafted` with the new line, or says "nothing was changed"
  and why; the model is told about the open card (`draft.context_line`) and the latest saved card
  (`draft.saved_context_line`), each with its id. The P1 answer "can't change a line, tap Cancel" is gone.
- A change line asks no "replace or add?": a correction is the sender's explicit replacement.

### 11.2 One read path for day and period figures (ADR 2.7)

- `project_day.period_for(bucket, today)` is the one definition of today / yesterday / this week / last week /
  this month; `resolve_period` (a stated day wins) and `labour_query_service.resolve_date_range` both use it.
- `project_day.read_period(...)` reads a period's work log (with its open issues) and its labour headcount for one
  scope and the same dates. Used by "how many workers?" (`_seed_labour_query`), "what was done today?"
  (`_seed_activity_search`, which now lists the day's workers), and the "today so far" line (`build_today_line`,
  now with the day's saved headcount).
- `query_labour` takes `date` and `date_range` with "yesterday" / "last week" (it only knew today / this week /
  this month, so "yesterday" was answered with today: g5).
- **Open issues: one rule** in the backend, `mesiri/application/dpr/open_issues.py`: open or being handled, a real
  site issue (not an old "Question for your engineer" note), and saved. The "open issues?" answer
  (`activity_search_service`) and the DPR assembly (its day query, its carried-issues query and its
  `open_issue_count`) all use it, and the DPR draft line (`site_day_review.day_lines`) shows the assembly's count
  (the day's own and those still open from earlier days). On 27 Oct the draft said 1 while the list said 2.
  The DPR's carried issues now leave out an earlier day's issue nobody saved, as every other count does.

### 11.3 A question is said once

The card shows a waiting question (❓ ...); the model is told not to write it, and a copy in its words is dropped
(`runner._without_echoed_questions`).

### 11.4 A line waiting on a question is on the card, and its buttons answer it (ADR 2.3)

When an entry's `prepare` asks before the call can become a line (which material, add it as new, 1 load = how many
cum?), the call is still a line of the card: `DraftItem` in state `needs_answer` with the question, its options as
the card's buttons, and what the answer fills in (`awaiting`: `material`, `new_material`, `unit`; the entry sets
it on its `Say`). "Steel used: 20 rod (❓ 1 rod = how many kg?)". A tap answers it (`draft_flow._answer_waiting`):
the answer goes into the line's own tool arguments (a unit answer sets the company's conversion first, as the typed
answer does, for those allowed to), `prepare` runs again, and the line becomes the entry, or carries the next
question. A typed answer reaches the same tool again and replaces the waiting line (`draft.waiting_for`). Save
saves the ready lines and keeps the waiting ones on the card (ADR section 9, answer 2). Questions about WHERE (site,
project, the other site of a transfer) keep the [111] site queue, as before.

### 11.5 Site carry-over and the old Yes / No

- Only a report from a site makes it today's site: `work_site.SITE_UPDATE_WORKFLOWS` / `SITE_UPDATE_ACTIONS`
  (labour, material, a transfer, work, an issue, a site expense), checked by both writers of today's site
  (`EntryScope.remember` and `JourneyGateway._remember_site`). Adding a team member, creating a site or project,
  correcting an old record and closing an issue no longer move it. Live: "Site B-il Rajesh-ine supervisor aakku"
  then "ഇന്ന് 4 മേസൺ വന്നു" went to Site B without asking.
- A new card made while an old-style Yes / No question still waits says so under the reply (`PENDING_YES_NO`,
  from `WorkflowRuntime.get_awaiting_confirmation`). The Yes / No flows themselves move onto drafts in P3.

### 11.6 Shared components touched (Module Isolation)

No Labour, Attendance, Payroll or Workforce rule changed: labour is read through the same counted-line rule and
written through the same workflow, undo and confirmation as before; only the order (take back, then write, on the
tap) is new, and it is the order today's edit uses. Shared code changed, as the approved plan names it: the DPR
assembly and its repository (the open-issue rule), the activity search, the labour date resolver (now the shared
one), the "today so far" line, and the rule for today's site. These apply to every company, not only with the flag:
"yesterday" on the labour question, the workers in "what was done today?", the draft line's open-issue count, and a
team-member message no longer moving today's site.

### 11.7 Tests

- Golden g4 and g5 pass (markers removed); repro 4 of P1 now asserts the edit.
- `tests/replay/test_draft_per_message_p2.py`: one or more per item 1-5.
- Real Postgres (`tests/integration/test_draft_change_postgres.py`, run on a local Postgres 16, not in CI): the change
  writes the labour rows an edit in today's flow writes and the labour answer counts the same; a failed change rolls
  the take-back back too; "open issues?" and the DPR count the same issues (an earlier day's open one, today's,
  not a resolved one, not an engineer note, not an unsaved one).

### 11.8 Known limits of P2

- The saved card a correction targets is still the Redis card (`cards.py`, 6 hours), as P1 keeps it for "undo
  that"; it moves to `message_drafts` with P4.
- "Other" / "Something else" on a waiting line's question cannot be answered by a tap: the sender types it.
- The Today page of the dashboard counts open issues by its own query (out of scope: dashboard behaviour); it does
  not leave out unsaved issues or engineer notes.
- Card words are English (as in P1).
- Not verified: a live-model run; the taps through real WhatsApp. Ilan Pro re-tests items 1-5 live.
- Rollback: flag off (items 1, 3, 4 and the Yes / No note), or `git revert` (items 2 and 5 apply to everyone).

## 12. P2 follow-up as built (request 129, replaces 128)

Live re-test of P2 (27 Oct) left four items; Ilan questioned the "remember the last saved site" fix in 128, so 129
replaces it. Applies to **all companies** (site resolution); no Labour rule changes.

### 12.1 The site of an update that names none (rule, in order)

1. The sender is on exactly one site: that site (unchanged).
2. The message names a site (alias or unique part of its name): that site (unchanged, `entry_base._named_site`).
3. A **site update was SAVED in the last 3 hours, on one site**: that site is preselected. The card's first line
   shows it ("📍 To save · Site B:") and every card of a sender with several sites carries a "📍 Change site" button.
4. Otherwise: "Which site?" with buttons, before any card (the morning list of WA-45, or `settle`'s question).

Never taken from a cancelled card (nothing is remembered before Save), a team / setup message or a question (only
`SITE_UPDATE_WORKFLOWS` / `SITE_UPDATE_ACTIONS` remember, as in P2).

Built as: `work_site.remember_saved_site` writes the active context with a **3 hour** TTL (`SAVE_WINDOW_SECONDS`)
instead of "until midnight". Used by both writers of the slot (`EntryScope.remember`, `JourneyGateway._remember_site`
through `WorkSite.remember_saved`). A slot set by the sender (the morning list, "now at Site B") still lasts the day
and is recognised by its length (`from_a_save`); a save at another site does not move it (SIT-05). A save at a
**different** site while a save-made slot is open clears it, so two sites inside the window ask instead of guess.
Single-site senders are not affected (they have one site).

"📍 Change site" (`draft.CHANGE_SITE` / `MOVE_SITE` taps) lists the sender's sites; a pick re-prepares **every** item
of the card for that site (`draft_flow.move_site`: same lookups and checks, e.g. the day's labour count is that
site's), all or none. Corrections of saved entries and pending actions stay where they are. Nothing is written
before Save.

### 12.2 Steel unit (128 A)

When no conversion can be asked for (a unit we do not know such as "rod", or a sender who may not set conversions)
the material entry now returns the question "How many kg is 20 rod?" (`AWAIT_AMOUNT`), so the line is on the card as
"• Steel used: 20 rod (❓ How many kg is 20 rod?)". Save writes the ready lines and keeps the card for steel
(section 9, answer 2); a typed amount in the stock unit turns the line into the entry. The classic (non-draft) path
is unchanged (status stays `info`).

### 12.3 Wording (128 C)

- A correction is told to the model as pending ("maattanam: mason 6 → 5. Save tap cheyyu"), never in the past tense.
- The Yes / No note is in the sender's language and second person ("Mukalil oru Yes / No question baakiyundu…").
- A card with no Save button (labour Replace / Add only) says "Replace or Add tap cheyyu", not "Save tap cheyyu".
- Typed "cancel" / "venda" / "വേണ്ട" is the card's Cancel button (`reply_composer.resolve_choice`).

### 12.4 Known limits

- The morning question ("Where are you working today?") is still asked, wording unchanged, when no site is known;
  a site chosen from it lasts the day (the sender said it).
- The save window is 3 hours from the **last** save (each save at the same site restarts it).
- "Change site" lists at most ten sites; no "Something else".
- Not verified: a live-model run; the taps through real WhatsApp (Ilan Pro re-tests live).
- Rollback: `git revert`.


## 13. P2.5 as built: the understanding side follows the draft (request 132, replaces 131)

P1/P2 moved the WRITE path onto `MessageDraft`. The 27 Oct re-test ([129]) showed the UNDERSTANDING side still kept its
own state outside the draft, and the model still wrote card-like text. This section is what changed. The flag
`draft_v2` gates the history, the reply filter and the "now at" rule; the site-name rule, `sheets = nos`, the
"Not saved" fix, Hinglish, the holiday card, the help and "since <date>" apply to every company (a shared component:
the agent prompt, the site context store and the history are also used by legacy paths, which keep their behaviour
until P4). No Labour rule changed.

### 13.1 The site is a field of the draft, set by one resolver (A)

`agent/draft_site.py`: one order, in one place -- one site -> the site the message names (whole words, the matcher
the site question uses, so "Green Villa ground floor wall putty 200 sqft" is Green Villa even when the model passed
no site) -> the site of the last SAVED site update for 3 h (`work_site.SAVE_WINDOW_SECONDS`) -> ask.

- Naming: `draft_flow.add` puts the one site the message names into the candidate as `site_name` when the model passed
  none, so the entry treats the site as named and neither today's site nor the last save overrides it.
- Nothing is pinned by a mention. The model's `set_work_site` ("Site B-il Rajesh-ine supervisor aakku") is refused on a
  draft card (`not_a_move`) unless the message only says where the sender is (`is_location_statement`: the site's name,
  filler such as "now at", and at most one other word). An accepted "now at Site B" preselects the site for the save
  window (`WorkSite.preselect`), not until midnight. The morning list a sender taps still lasts the day.
- A team / setup / question message never writes site context (unchanged from [127]; the entry only remembers after a
  save of a site update).

### 13.2 Questions are items (B)

Already true since [127]/[129] for the unit question ("Steel used: 20 rod (❓ How many kg is 20 rod?)") and the
labour Replace / Add: a `needs_answer` line with its own buttons, answered by tap (keyed to the item id) or by typing
the answer. New here: the open questions are part of the state block the model is shown (13.4), so it never re-asks one
from a past reply. `sheets / pcs / pieces / nos / numbers / rod` (`material_units.COUNT_WORDS`) against a material
stocked in nos or pcs are the same count: no question, the line is on the card. A stored conversion is applied at once
(unchanged, [103]). **Not done:** the "which site" question is still the [111] site queue, not an item of the draft.

### 13.3 The code renders every card; the model's text is filtered (C)

`agent/reply_clean.py`. In draft mode the model's words lose the card's headers and bullets ("📝 To save",
"📝 To close", "✅ Saved"), "Reply YES / NO" lines, `[options: ...]` and parenthesised system notes; every mode loses
`[options: ...]` and the "(closed: ...)" note. Above a draft card the model's words are its first sentence, at most 200
characters. `leaks()` names what is left of a prompt or annotation constant. Tests: a leak guard (a reply never carries
text of `stale_questions.CLOSED` etc.) and a property test (any reply with "To save" has the card's buttons).

### 13.4 What the model is shown (D)

`agent/history.py`. In draft mode the earlier turns are the sender's words plus a one-sentence gist of the answer (no
card, no options, no note, no question); the state is one block (`draft.context_line`: the open card's lines and
"Waiting for their answer (item n): ...", and the last saved card). Without the flag the turns are as before, with
`stale_questions.CLOSED` on a question nobody answered.

### 13.5 The polish of [130] (E)

1. The site named at the start of a Manglish message is found (13.1).
2. The stray "Not saved (<message>):" after a site pick is gone: a released call that became a draft line is a line.
3. Sheets / pcs = nos (13.2).
4. Hinglish ("aaj Green Villa mein 3 mistri aur 2 labour aaye") is its own reply language (`reply_language` ->
   `hinglish`): the reply is Hindi in English letters, not English or Manglish; the prompt maps mistri -> mason and
   majdoor / labour -> helper and forbids telling the sender to select a trade. The site question has Hinglish wording.
5. The holiday card reads "Site B: Holiday, no work today".
6. "enikku enthokke cheyyan pattum? help" is the fixed help; it lists only the company's enabled modules with up to three
   examples to copy (English, Manglish, Malayalam; Hinglish and others get the English examples).
7. An open issue from before the period's last day carries `since` ("24 Oct") for the model, which is told to say
   "since 24 Oct", not "today".

### 13.6 Known limits

- Hindi (Devanagari) and Hinglish get the English help examples and wording in the fixed lines that have no Hinglish text.
- The 200-character first sentence above a card can drop a useful second sentence; the card carries the facts.
- The "which site" question is not yet an item (13.2).
- Not verified: a live-model run; the taps through real WhatsApp (Ilan Pro re-tests live).
- Rollback: flag `draft_v2` off (history, filter, "now at" rule) or `git revert`.


## 14. Phase 2 of the 27 Oct plan: one pending record, code answers the card (WA-81)

From the review of the 27 Oct live rounds (58 marks, [`docs/qa/live-scenarios.md`](../qa/live-scenarios.md)):
most failures were two stores disagreeing about what is pending, and the model being asked to do the record
keeping. This section removes the store that disagreed most (the [111] site queue, for draft lines) and moves
answering the card's questions into code. Draft mode only (`draft_v2`); no Labour rule changed.

### 14.1 "Which site?" is a question of the card (W1)

- A draft tool whose entry asks WHERE (`site`, `project`: `draft.WHERE_QUESTIONS`) is a line of the card in state
  `needs_answer` with `awaiting = site` (`DraftItem.needs_site`). The card shows the lines and, once, "📍 Which
  site is this for?" with the sites as buttons (`card_rows` puts the site question first). Closes 13.2's "not done".
- One answer (a tap, or the site's name typed) settles **every** line waiting for it (`draft_flow._answer_where`);
  a labour line then joins the card's labour line of that site and day (the merge rule of `add`) and keeps the
  "replace or add?" question when the day already has a count.
- A card that is already for one site gives that site to a new line that names none (`_on_card_site`): the
  "which site?" inside a card that said Green Villa (live 27 Oct, screenshot 18) cannot happen.
- A site the message names stays in the line's arguments, also while it waits on another question (the steel
  line kept no site, so its answer asked "which site?").
- The [111] queue (`site_wait`) holds no draft-tool call in draft mode (`turn.py` clears such items), and the
  WA-45 morning question does not hold the message: so no reply can say "not saved, send it again" about a line
  the card still holds, and nothing comes back later (live #4314, #4322, #4331). Calls a card cannot hold (a
  transfer) keep the queue.
- A "next update of the same kind" never replaces a line waiting for its site (`waiting_for`); and the same call
  asked again after its site is answered is the same line, not a second one (`_bare`: live, steel shown twice).

### 14.2 Code reads a typed answer to the card (W2)

`draft_answer.py` (pure) and `draft_flow.answer_typed`, run by `message_journey._run_agent` **before** the model
for a text message while the sender has an open card; anything that is not such an answer goes to the model.

- "Which site?": the site's name alone ("Green Villa", "Site B-il"), not an update that names it ("Green Villa 2
  helper vannu").
- "How many kg is 20 rod?": "oru rod 12 kg" / "1 rod = 12 kg" / "per rod 12 kg" -> 240 kg; "240 kg" / "240" ->
  240 kg. The stock unit comes from the entry (`Say.answer_unit`). The line is prepared again with the amount in
  the stock unit (every check of the entry runs) and the card shows Save.
- An apology above a card ("Sorry, couldn't record it") is dropped when no line of this message failed: the card
  has the line, waiting on its question (live #4338).

### 14.3 Tests and limits

- `tests/replay/test_wa81_one_pending_record.py`: the live sequences of rounds 7-8 (9 of its tests fail on the code
  before this change). Tests that asserted "nothing on the card, ask the site" now assert "the line waits on the
  card for its site".
- Not verified here: the live run (`bot-scenarios`, WA-80) is the gate; see the tracker for its result.
- A sender's message held by the morning question before this change is not replayed (TEST company only).
- The `to_site` question of a transfer is still the [111] queue.
- Rollback: `git revert`, or flag `draft_v2` off.


## 15. Phase 3 of the 27 Oct plan: the model extracts, code decides where it goes (WA-82)

Draft mode only. The model still calls the save tools (its extraction); these rules decide in code what the call
does to the card, so the model's choice between "new" and "correction" cannot lose a fact.

- **Nothing to correct is new information.** `update_pending_card` with no open and no saved card, or a line that
  is not on the card, returns `not_a_correction` (`toolbox.NOT_A_CORRECTION`): nothing is changed, and the model is
  told in the same turn to save the fact with its tool. Live 27 Oct (#4335): "tiling 70% aayi" after a cancelled
  card got "angane oru card ippol open aayitilla" and nothing was saved.
- **A new percentage for the same work and place replaces its line** (`draft.same_work`): "Tiling, ground floor:
  60%" on the open card from an earlier message becomes 70%, not a second line. Amounts of work done add up as
  before; two parts of one message never replace each other (the property test of P1 holds).
- **A breakdown inside a longer site note is on the card** (`runner._problem_part`, `equipment.problem_clause`):
  when the model saved the other parts and called no `report_issue`, the issue line is made from the message's
  own words ("mixer breakdown aayi pani 2 hour ninnu", 120 minutes lost). Not for a clause said to be fine or over,
  or a question. Live 27 Oct (round 7): the card lost the breakdown.
- Tests: `tests/replay/test_wa82_code_reconciles.py`. Not verified here: the live run (WA-80) is the gate.
- Rollback: `git revert`, or flag `draft_v2` off.


## 16. Phase 4 of the 27 Oct plan: one way in for "help" and the menu (WA-83)

- **The menu follows the company's modules, for every company** (`render_greeting_menu` builds its rows when it
  is sent). It used `CATEGORY_ROWS`, built at import before any company is known, so "hi" offered Money and
  Reminders to a company that has them switched off, though the WA-07 filter existed (live 27 Oct, screenshot 19).
- **"help" is the one help** in draft mode: a bare "help" / "what can you do?" skips the category menu and gets
  the fixed help of [132] (the company's modules, three examples to copy, in their language). "hi" / "menu" still
  open the menu.
- **"I couldn't understand that" carries the help** in draft mode: the same fixed help follows it (M25).
- **Not done here: the wording catalogue (W5).** The language marks of 27 Oct (M07 "Nooki", M16 "Inn ... innu",
  M21 / M27 English replies to Manglish) are the model's wording; a fixed catalogue in Malayalam and Manglish is
  WA-76, which is blocked on the owners reviewing the wording. These marks are measured by the live suite (WA-80)
  and reported, not fixed by invented translations.
- Tests: `tests/unit/test_wa83_one_way_in.py`, two journey tests in `tests/unit/test_draft_tap_journey.py`.
- Rollback: `git revert` (the menu rows apply to every company), or flag `draft_v2` off for the rest.


## 17. Team and setup on WhatsApp (WA-84, W8 of the 27 Oct plan)

Approved by Ilan on 27 Oct ("do the rest"). Draft mode routes the first two; the wording changes apply to everyone.

- **Report time:** "report time 7 pm aakku" (`team_setup.report_time_asked`) asks SS-14's report-time question now
  (`SetupQuestions.offer_report_time`): its 7 / 8 / 9 pm buttons, and the existing tap handler changes the send
  deadline (one project or all). Nothing changes without the tap. **Only the owner (ADMIN)**, the dashboard's rule;
  anyone else is told who can.
- **Team list:** "ente team-il aarokke und?" lists who is on the sender's own projects
  (`ProjectDetailQueryService.list_members`: the sender's company, their projects, removed users left out), the
  rows the dashboard's Members tab shows any member. Read only.
- **"Supervisor":** Mesiri has **no Supervisor role** (WA-67: the roles are Admin, Project Manager, Site Engineer,
  Finance), and adding a person gives access to **every site** of the project (`site_access_mode = all_sites`).
  Neither is changed here: a new role or a site-limited membership is a permission-model change (needs Alan's
  approval). The card now says so: it names the project, says "Mesiri has no Supervisor role; Site Engineer is
  the nearest", and "They will see every site of <project>, not only Site B".
- **Yes / No cards:** every workflow's "Reply YES to confirm or NO to cancel." reads "Tap *Yes* to confirm, or
  *No* to cancel." under its buttons (`render_workflow_run_reply_spec`, all companies); the model's own Manglish
  echo ("Confirm cheyyan YES ennu reply cheyyuka") is filtered in draft mode. Moving these flows onto the draft
  card (Save / Cancel) is still P3 of this ADR.
- **Module switched off:** when nothing else was saved, the reply is the code's one line (not the model's English
  retelling), swapped into Manglish for a Manglish sender.
- **Wording:** the new Manglish / Malayalam lines in `reply_language.py` were drafted by Claude and are marked
  PENDING the native review of WA-76.
- Tests: `tests/unit/test_wa84_team_setup.py`. Rollback: `git revert` (wording), flag `draft_v2` off (routing).


## 18. One pipeline for site updates (request 136, replaces [135]'s patches)

Approved by Ilan in WhatsApp on 28 Oct (#4797: "I need them sorted, not patched"). Draft mode (`draft_v2`) only;
legacy is unchanged for every other company until P4. No Labour rule changed (labour is saved through the same
services). No migration. Phases of the plan: **A+B** (this section, one push), **C** (wiring proof: the recording
part is in this push, see 18.4), **D** (the live gate, not built: 18.6), **E** (deleting what B made unreachable,
needs its own ok once P4 flips everyone).

### 18.1 Why the same bugs came back (code facts of 28 Oct)

1. Two systems ran side by side. [132]'s resolver `draft_site.resolve()` was never called; the "Ee update ethu
   site-inte aanu?" question came from the entry's old site path (`EntryScope.settle`: today's site, the context
   layer's default site, `_named_site`). Fixes landed in the new code while the old code kept answering.
2. `named_in()` matched whole names only, so "Green Villa" did not name "Green Villa, Kakkanad".
3. The model's sentence went out above the code's card and could contradict it. One contradiction was the code's
   own: `_choice_line` named only the options of 12 characters or less, so a card asking between "Green Villa,
   Kakkanad" and "Site B" said "Site B tap cheyyu."
4. "innu enthokke cheythu?" took its site from the context layer (another site than the one just saved to) and
   listed no materials.
5. Scripted-model tests passed while the resolver was dead code.

### 18.2 A: one pipeline per site message

- **The site** of every draft line is decided by `draft_site.resolve` in `draft_flow.add`, **before** the entry
  runs, in one order: the sender's only site -> the site the model's call names (whole words, a part such as
  "Green Villa" counts) or the message names (`site_match.mentioned_sites`: the full name, or its head before the
  comma; two hits ask between those two) -> a name that is none of theirs asks among all (never a fallback) -> the
  open card's one site (WA-81, now a step of the resolver) -> the site saved to within 3 h (`work_site.today`) ->
  the card asks. The entry gets the decided site as an explicit pick, so its own fallbacks never decide a draft
  line. `with_named_site` and `_on_card_site` are gone (folded into the resolver).
- **The words above a draft card are the code's** (`runner._code_card`, `card_sentence`): "Card nokki shariyenkil
  Save tap cheyyu." / "Card-ile chodyathinu answer cheyyu." / both, in the sender's language (English, Manglish,
  Malayalam, Hindi, Hinglish), then the card, its questions and the system's own lines. The model's text is not
  used. Exception (limit): a turn that also answered a lookup ("5 mason vannu, cement stock ethra?") keeps the
  model's filtered sentence for the answer, as before.
- **The "tap X" line** names the options only when every option is short (Replace / Add); otherwise the card asks.
- **Readers**: in draft mode a question about the day's figures (`query_work_log`, `query_labour`,
  `query_materials`) takes its site from the same resolver (named -> saved within 3 h), else **every site of the
  project** (`entry_base.ALL_SITES`), never the context layer's default site. "What was done" also lists the
  period's materials (`period_totals`, counted as the DPR's assembly counts them) under "🧱 Materials". The reads
  stay on `project_day.read_period` over the same tables the DPR reads.

### 18.3 B: the old paths are not reachable for draft_v2 senders

One guard in `message_journey._run_journey_steps`: `pipeline_v2` is read once per message and logged
(`journey.pipeline pipeline=draft_v2|legacy`). For a draft_v2 sender:

- a labour / material / work / issue workflow still waiting for a Yes / No or a slot answer (only possible from
  before the switch: a Save writes in one transaction) is **not resumed** by the message
  (`journey.legacy_site_update_routed_out`); the message goes to the draft pipeline. Other workflows (add a member,
  expenses, accounts) keep their Yes / No until P3.
- the morning "where are you working today?" question (already off since WA-81) uses the same guard;
- the WA-57 "later" list is neither shown to the model nor kept, and a draft Save does not ask from it (a card
  keeps what is still to do as its own waiting lines);
- the [111] site queue already holds no draft-tool call (WA-81); save-first and the legacy `card_plan` never see a
  draft tool call (nothing is written before the Save tap).

### 18.4 C: wiring proof (recording part)

Every draft turn records who decided what (`JourneyGateway.decisions`, written as the trace stage
**`draft_decisions`**, names only): `site` by `draft_site.resolve` with its kind (single / named / card / saved /
ask), `item` by `tool_call` (+ `item_source` `code:problem_part` etc. for a line the code made from the message),
`reply` by `template` (or `model_filtered` for the lookup exception), `read_site` for the readers.
`tests/replay/test_request136_one_pipeline.py` fails if a draft turn's site came from anything but the resolver
(a spy proves it runs once per line), or if the words above a card are not the template's.

### 18.5 Tests

`tests/replay/test_request136_one_pipeline.py` (19 tests: the matcher, the resolver order, Green Villa by its
head, the model's part name, saved within / after 3 h, two Green Villas, a site that is not theirs, the spy, the
template in Manglish and English, never "Site B tap cheyyu", a golden 4-part note + a line on the same card + Save,
the reader's site and the materials). Changed: the P1/P2 data-identity tests now expect the one-site sender's site
on the record (the fixture's legacy path places none because its context-layer project id is not the canonical
one; in production they are the same). The replay World now wires `get_today_site` as production does.

### 18.6 Not done here (needs the owner)

- ~~D, the live gate in CI~~: built on 28 Oct once Ilan approved everything (18.8).
- **The live test-chat run**: not possible from this session (no teammate token here). Ilan Pro re-tests live.
- [135]'s own repros are not in the repo (the bot's request log was not readable here); the 27 Oct transcripts and
  the plan's listed cases are the acceptance tests instead.
- Button titles are cut at 20 characters ("Green Villa, Kakkana"), not at a word (`site_match.short_title` is not
  used by the draft card's buttons). Small, separate.
- Rollback: flag `draft_v2` off for the TEST company, or `git revert`. The template wording (Malayalam, Hindi,
  Hinglish, and the new Manglish "answer the question" line) is PENDING the native review of WA-76.


### 18.7 P4: on for every company (28 Oct)

Approved by Ilan on 28 Oct ("I approve everything, make it live for everything"). `draft_v2` now defaults to
**true** (`settings.draft_v2_enabled`: anything but an explicit `false` is on), so every company takes the one
pipeline. An explicit `false`, set by the Mesiri team on the control panel, is the per-company off switch and the
rollback (no deploy needed); `git revert` of `a093789` puts the old default back. No data changed, no migration.
Phase E (deleting the old paths) waits for a burn-in with no company switched off, because it removes that switch.


### 18.8 D: the live gate (28 Oct)

`tests/conversation/draft_golden.yaml` holds the draft pipeline's golden conversations (the 4-part note, Green
Villa by its head, Site B named, saved within 3 h, no site -> the card asks, steel in rods, a correction of the
open card, "innu enthokke cheythu?", a two-part note). `test_draft_golden.py` runs them twice:

- **scripted, in every CI run**: the card must be exactly the case (site or question, kinds of lines, their words,
  the template sentence, every site decided by `draft_site.resolve`); the model's scripted words are deliberately
  wrong ("Site B tap cheyyu. Saved!") and must never show;
- **live, as the deploy gate**: `deploy.yml` job `live-gate` runs `-m live` with `TEAMMATE_GEMINI_API_KEY`
  (gemini-2.5-flash, the settings default) before `deploy`; a case that fails twice in a row stops the deploy; a
  miss followed by a pass is printed as flaky. Fails closed without the key.

Limits: production chooses its model at runtime (`DynamicAIProviderResolver`); the gate tests the default Gemini
model. Each deploy spends a few model calls (about 20).

## 19. Day facts: one rule for saved work (request 137, 28 Oct)

Live re-test of section 18 (test chat, 28 Oct). **F1:** "Green Villa ground floor tiling 80% aayi" after 70% was saved
got the model's "Sorry, ... maattan kazhinjilla" and no card. **F2:** "innu Green Villa-il enthokke cheythu?" said nothing was
recorded though 70% and 80% were saved. Cause (code reading; not confirmed on live data): the correction lookup
(`find_correction_target`) wants a quantity and a percentage has none; Save of work continuing an open activity
(`confirm_now`) records no fact, so `_remember_saved` paired lines with the wrong facts by position; `find_open_activity`
ignored review state, so an update could hang off a draft or cancelled parent that the readers hide.

### 19.1 What is built (`runtime/day_facts.py`)

- `counted(state)`: one definition of "saved" (not a draft), delegated to `fact_review.counts`.
- `WorkFact`: a saved work item with its fact id, site, work key (work + place) and value (percent or quantity), read
  from the saved card items (each carries its fact id). No new table, no migration.
- `resolve_percent`: a newer percent for the same work is a **new line**; only an explicit correction ("alla, 75%")
  edits the saved line, found **by fact id**; with several works saved nothing is guessed.
- `open_work_sql`: open-work matching (`find_open_activity`, `list_open_activities`, by-id lookup) skips activities
  whose latest review is a draft or rejected.
- Toolbox: in draft mode `correct_work_quantity` with a percent, and `update_pending_card` with only `progress_percent`
  on a saved card, go through `resolve_percent`. A quantity correction runs the old path unchanged.
- `_remember_saved` keeps one fact slot per saved item (no positional shift).
- Replies (E): a draft-mode turn whose write failed (or that ends in the model's apology) with no card, saved line,
  answer or question is answered by `runner._FAILED`, in the sender's language. Prompt: a percentage is progress.

### 19.2 Second part: B, C, D and the old lookup (28 Oct, same request)

Built and tested against a real Postgres (local cluster at head 0491; `tests/integration/test_day_facts_postgres.py`).

- **D, readers.** `DayFactsReader.work` is the one query for a period's work: every activity and every progress
  update on it, each with its own fact id, oldest first, saved-only unless asked. `latest_note_sql` makes every day
  reader say what the work says now: "what was done today" showed "Tiling, ground floor: 70%" after 80% was saved
  (reproduced on the real database: the reader printed the activity's first note, never its updates). The
  "today so far" prompt line lists saved and waiting-for-Save work separately ("Saved today: tiling 80%. Waiting for
  Save: ...").
- **B, the write path.** A Save that continues open work still confirms through the workflow (`confirm_now`: a
  progress update has no review of its own), but it now records a fact like every other line:
  `("progress_update", update id)`, read in the Save's transaction. The card keeps it, so "undo" and a correction
  take back that one update (`SaveFirstService` voids it through the progress module's `void_progress_update`),
  never the whole activity. The positional pairing is gone.
- **F2's draft parent.** An activity the old flow saved first (still a draft) stays continuable (skipping drafts, as
  section 19.1 first did, made a second activity in the save-first flow: caught by the WRK-04/WRK-01 real-database
  tests and reverted to "skip only cancelled"). The draft_v2 Save that continues the sender's own draft activity
  confirms it, so the update counts in every reader.
- **C, corrections from the day.** `correct_work_quantity` for draft_v2 senders resolves against the day's facts from
  the database with the saved card on top (`day_facts.merged`), not the last card only: a newer percent is a new
  line; "alla, 75%" or "it was 40 not 50" becomes a "Change ..." line for the newest saved entry of the work it names
  (or the only one), found by fact id. A correction of an activity's first entry no longer continues the activity
  it replaces (the corrected amount was written onto the removed activity: fixed in `draft_flow.change_saved`).
- **The old lookup is gone.** `ActivityQueryService.find_correction_target` and `get_latest_quantity_update` are
  deleted. The classic Yes / No correction (companies with `draft_v2` switched off) reads the same `DayFactsReader`
  (`day_facts.correction_target`, the last two project days, drafts included), so the off switch still works.

### 19.3 Not done

- `confirm_now` stays as the mechanism that writes a continuation: removing it needs a review type for progress
  updates (a migration widening `ck_fact_reviews_fact_type` and the backend's locate / undo / DPR rules for it).
  Every line now leaves the Save with a fact id, which was the point of B.
- The DPR assembly (backend) is unchanged: it already reads progress updates through their activity.
- Golden conversations for the live gate are not added: they need the live model, and a failing case stops the
  deploy. The same messages are covered by replay tests and the real-database tests above.
- Not checked against production data (no access from this session).

### 19.4 Third part: the project's date of an update (29 Oct re-test)

Root cause of "innale enthokke cheythu" missing the corrected tiling: a progress update was placed on a day by
`CAST(occurred_at AS date)`, the **UTC** date, while its activity is dated in the **project's** zone. Anything
saved between 00:00 and 05:30 IST sat on the day before for the readers, so a day read for the new day (or for
"yesterday" the next morning) left it out and the work-log line fell back to the activity's first note. The fix is
at the Day Facts level: `day_facts.project_date_sql` (company zone, India when unset or "UTC") is the one date rule
used by `DayFactsReader.work`, `latest_note_sql` and `ActivitySearchService`. Regression test:
`test_save_continue_continue_correct_then_the_day_reads_the_last_figure` (70 -> 80 -> 85 -> "alla, 82%", saved at
00:30 IST; fails before, passes after). No migration.

Not changed (shared, backend): the DPR assembly (`dpr.py`) still uses `pu.occurred_at::date = :report_date`, the same
UTC rule; a DPR for a day would miss an update made 00:00-05:30 IST. Needs approval to touch (shared component).

Rollback: revert the commits; no migration, no data change.


## 20. Request 142, phase 1: one Save gate for the money tools, and the save journal (A + B)

Approved by Ilan in WhatsApp (29 Oct, "AI decides, software guarantees"). Same switch as before: the company
`draft_v2` setting. Off = the old flow, byte for byte.

### 20.1 A: more tools wait for Save

`save_expense`, `transfer_material`, `transfer_money`, `save_opening_stock` and `update_issue` (acknowledge, won't fix,
withdraw, reopen) now add a line to the card instead of starting a confirm-first workflow. Nothing is started or
written when the message arrives; the Save tap starts the workflow and confirms it inside the one transaction
(`draft_flow._write`, which already did so for work on an open activity). A money transfer belongs to no site, so
the site resolver does not ask for one (`draft.SITELESS_TOOLS`). Resolving issues and the engineer question and the
day's conditions were already pending actions behind the same tap; `correct_work_quantity` is a "Change" line.

Test: `tests/replay/test_write_gate_142.py`. A spy on `runtime.start` and the dispatcher fails any write before Save
for each gated tool, Save writes, Cancel writes nothing, and `test_every_write_tool_is_behind_the_card_or_listed_as_not_yet`
fails when a new write tool is added without saying how it waits.

**Not behind Save yet** (listed in that test with the reason, each needs the owner's ok first): `add_member`
(grants access: security-sensitive), `create_site` and `create_project` (role-gated creation), `set_unit_conversion`
(a company-wide setting answered on the spot).

### 20.2 B: the journal

Migration `0493_save_journal` (additive, RLS like every company table): one row per Save with company, sender,
site, day, time and `facts` (type and id of each record written, the tool and arguments that made it, its card line).
`draft_flow.save` writes it in the Save's transaction; a journal failure rolls the Save back. `runtime/agent/journal.py`
holds the entry, the matching of the sender's words ("last", an id, "the cement") and the two stores; every query
names company AND sender, so a sender can only ever reach their own entries.

`change_or_undo(target, changes?)` (tool; `undo_last` now routes to it) never removes at once: it shows
"Remove this? • line · site" with `Yes, remove` / `Keep it` (typed yes/no, Manglish and Malayalam words work), and the
Yes tap (`agj:undo:<entry>:<fact numbers>`) removes exactly those facts through each module's own undo
(`undo_facts`) and marks them undone. Several matches become a pick list. A change (`changes`) is the existing
"Change ..." line, started from the arguments the journal kept (`undo_flow.py`).

Not done in this phase: the old per-card store (`cards.py`, Redis) still exists and is still written beside the
journal (a saved card from before the deploy has no journal entry, so undo falls back to it); it goes in phase 5.

### 20.3 Closing an issue (live 29 Oct)

"Which issue is fixed?" rows carry ids (`agc:grp:<8-hex refs>`): the tap makes the "Close: <issue> · <site>" line of
the card without asking a model to match a cut title again. The same report made twice is one row that closes both;
a row "All N of these" closes every listed issue (up to 7); the model can say `all_matching` for "ellam mixer
issues-um"; "Something else" asks for words instead of listing ten options. Titles are cut between words and the full
line is the row description. Test: `tests/replay/test_close_issue_pick_142.py`.

### 20.4 Verified

Replay tests (scripted model, real journey) and, on a local Postgres 16 with `alembic upgrade head` to 0493,
`tests/integration/test_save_journal_postgres.py` (record, read, undo, company and sender isolation) and the draft
integration tests: a Save writes one entry with the real fact ids, an asked undo removes nothing, the Yes tap removes
exactly the named fact through the module's own undo, and a Save that fails part-way leaves no journal row. The
real-database tests run locally only (not in CI), as for P1. Not verified: a live model; the tap through WhatsApp itself;
the tenant row-level-security policy under a non-superuser role (the queries name company and sender regardless).

### 20.5 Rollback

Flag off, or revert the commit. The migration is additive; the table stays empty for companies without `draft_v2`.

## 21. Request 143, phase 2 (C): Day Facts is the one reader of a site's day; the report is always a PDF

Approved by Ilan in WhatsApp (29 Oct, request 143, continuing [142]). Repro: "innathe report ayakku" came back as
"Today's report ready aayittilla, ithu oru draft aanu..." with no content and no PDF. Cause: `request_dpr` ran the
`dpr.request` workflow, whose answer was a status line ("made this evening. So far today: ..."), and the model retold
it, keeping the status and dropping the day. A site that was not resolved (several sites) got no PDF at all.

### 21.1 One date rule (backend, shared)

`mesiri.application.dpr.project_day.local_date_sql` is the one way to put a `timestamptz` on a site's day: the
company's zone (India when unset or the untouched "UTC"). It replaces every UTC `::date` of the DPR family: the
assembly (`assemble_site_day_with_drafts`: continued work, photos, issues, carried issues, materials, stock), the
Today page's counts, late entries, the review log's issue date, the auto-DPR scans and the generation script. Day
Facts' `project_date_sql` (section 19.4) now calls it, so the assistant and the report can no longer put one entry on
two days. Columns that already hold the project's date (`activity_date`, `occurred_date`) are unchanged.

### 21.2 Day Facts reads the whole day (`runtime/day_facts.py`)

`SiteDay` is what a site's day holds (work with percents and amounts, labour, materials, issues, conditions,
photos), from the one assembly, saved entries only, cancelled ones left out (`only_kept`/`for_document` moved here).
`DayFacts` is the process's one reader (it replaces the `DayFactsReader` wiring; `work` and `latest_update` are
unchanged); each message works on `for_turn()`, which reads each site day once however many parts of the turn ask.
The dashboard's live document (`dpr_preview`) reads through `read_site_day` too.

### 21.3 The report entry (`runtime/agent/report_entry.py`)

`request_dpr` no longer starts a workflow. `ReportEntry` settles the scope (no site question), takes the project's
day (today, or the day named; an unreadable day is asked about), and for each site in scope (the one named or worked
at; with several and none named, every site of the sender's in the project that has entries, up to 5):

1. the site's confirmed DPR when its PDF can be fetched; else
2. the project's confirmed DPR (it holds every site), once; else
3. the day from Day Facts printed by the DPR template as a draft (`channel/dpr_document/day_document.py`, the same
   renderer as the dashboard's download), with the company letterhead by project (`load_project_letterhead`).

A stored PDF nobody confirmed is not sent: the day's facts are. The PDFs go right after the tool call (one retry
each). The sentence is the code's, from `runtime/agent/wording.py` in the sender's language ("Innathe draft report ·
Green Villa ithaa, ..."); a report-only turn is that line exactly (`runner._report_only`), and a turn that also saved
entries gets one line under the card (`report.with_card`). The model is told the system sent it and writes nothing
about it; `dpr_caption`, `draft_report_line` and the DPR branch of `_answer_in_language` are gone.

`wording.py` is the catalog for the code's fixed sentences (every key in English, Manglish, Malayalam, Hindi and
Hinglish, checked by a test), with `language_of(text, usual)`: a message that cannot tell ("ok", "20") takes the
sender's usual language. Phase 3 moves the other fixed lines into it.

### 21.4 Removed

`seeding._seed_dpr_request`, `_dpr_scope`, `_project_preview`; `QueryEntry`'s DPR route, `_past_day_draft`,
`_project_pdf` and DPR delivery; `DprRequestQueryService.preview_lines` and `draft_pdf` (it keeps `find_report`).
The `dpr.request` workflow graph is no longer reached and goes with the other workflow nodes in phase 5.

### 21.5 Verified

Unit and replay tests (`tests/unit/test_request143_report.py`: the repro, confirmed vs draft, project PDF, nothing
saved, several sites, a named site, bad day, render and send failures, the reply is the code's line, one read per
turn, wording for every language). Golden cases 10 and 11 (`draft_golden.yaml`) are in the deploy's live gate. On a
local Postgres 16 at head 0493: `test_report_day_postgres.py` (an update and an issue saved 00:30 IST are on the IST
day; fails on the old assembly, passes now) and the existing DPR and Day Facts integration tests. Not verified: the
live model (the live gate runs on deploy), a real Chromium render inside this session, production data.

### 21.6 Rollback

Revert the phase commit. No migration, no data change. The date rule moves an entry saved 00:00-05:30 IST from the
day before to its own day in every DPR read; reverting moves it back.

## 22. Request 143, phase 3 (D + E): the check layer, true card facts, one language per turn

Approved by Ilan in WhatsApp (29 Oct, request 143). Repros: "Site B 500 mason vannu" saved with no question;
"Green Villa ground floor tiling 40% aayi" after a saved 88% had no "went down, sure?"; "Saved 6 workers (6 helper)"
while the day had 13; a late entry's card did not say its day; the module-off line, "ok thanks" and "Received or
used?" were English for a Manglish sender; a cement order became an issue; a week summary carried the Stock card.

### 22.1 D: the check layer (`runtime/agent/checks.py`)

`checks.doubt(kind, args, fields, history)` is pure. `draft_flow.add` runs it (`_checked`) on every line that is
ready, before it joins the card; a doubt makes the line wait on a question with `Yes, it's right` / `Change`, in the
turn's language. The rules are few so a normal day is never asked about:

- labour: the day's workers above both three times the site's usual day and the usual day + 30, or above 150 at a
  site with no history (fewer than three days with a count);
- work: a percent above 100, or below the newest saved percent of the same work and place;
- material used: more than the site's stock, when its stock is known (the entry's `available_stock`).

The history is Day Facts': `DayFacts.site_history` (`SiteHistory`: workers per day over 30 days by the workforce
module's own live-report and counted-line rules, and the newest saved percent per work over 120 days from
`DayFactsReader.work`), read once per turn. Answers: the `Yes` tap or a typed yes-word makes the line ready;
`Change` takes it off the card ("send the right figure"); a typed figure ("50") replaces the one asked about and the
line is checked again. Save already carries a waiting line over to a new card, so nothing is dropped.

### 22.2 E: card facts

- A labour line says the day's true total once saved (`draft.day_total_note`: " · day total 13 workers"), by the
  save's own BE-10 rule; the saved reply keeps the card's labour line (the saved record's summary does not know the
  day's other lines). Display only: labour rules unchanged.
- Every record for another day says which ("(yesterday, 28 Oct)"), not only an issue (`summarise_draft`).
- "Closed" is the saved-lines layout (`actions.closed_lines`): one line, or a header and bullets.
- A material order is a material request: tool `request_material`, a pending action (`material_request`) whose Send
  tap messages the site's engineer(s), else the project's manager(s), through the notification queue, as the
  engineer question does. The toolbox refuses `report_issue` for an order (unless it ran out and held work up) and
  tells the model to make the request. No new table, no migration.
- A picture belongs to its answer: the Stock card goes only on a reply whose answers are the stock answer alone
  (`AgentToolbox.answers_only_stock`).

### 22.3 One language decision per turn (`wording.decide`)

The message's own language when it tells; otherwise (no words of its own: "ok thanks", "👍", "20", a tap) the
sender's usual language from their profile (`UserLanguageStore` -> `wording.usual_from`). The runner decides once
(`AgentToolbox.language`, `JourneyGateway.wording_language`) and everything follows it: the prompt's language rule
(`reply_letters_rule(text, usual)`), the card sentence, the covering and failure templates, the check questions, the
module-off line (an entry now returns its `wording` key, `Say.line_key`, and the toolbox words it) and the
"Received or used?" question, which is the code's own with `Cancel` (a Cancel is answered by code, no model). The
older after-the-fact replacement tables in `reply_language.py` stay for lines not moved yet.

### 22.4 Verified

`tests/unit/test_request143_checks.py`, golden cases 12-14 (the live gate: 500 masons asked, 40% after 88% asked,
an order is a Send card), materials golden 24-25, and on a fresh local Postgres 16 at head 0493
`test_report_day_postgres.py::test_the_site_history_the_check_layer_reads` plus every integration test. Not
verified: the live model (it runs in the deploy's live gate), production data.

### 22.5 Rollback

Revert the phase commit. No migration, no data change.

## 23. Swipe-replies, what the model remembers, "today" vs earlier days, a set reply language (WA-89, live 29 Oct)

Live chat of 29 Oct (screenshots): the sender swiped Mesiri's own site-log reply and asked "what is this message
then?"; Mesiri answered "I did not send any message about rain or cement" and "I can only see what you type". The
same log had listed an issue open since an earlier day as one of today's. The sender also asked to set the reply
language ("I type Manglish, answer in Malayalam") whatever they type in.

### 23.1 Causes found

1. **A swipe-reply was never seen.** `MessageNormalizer._resolve_reply_context` read `context.message_id`; Meta's
   inbound webhook names the quoted message `context.id` (`message_id` is the outbound field). `reply_context` was
   always None in production, and even when set it carried only an id: nothing kept the words of what Mesiri sent
   (`inbound_messages.reply_wamid` exists but `set_reply_wamid` is never called).
2. **The model forgot what it said.** In draft mode (`history.for_model`) each earlier reply was shown as its FIRST
   sentence only: of "No work saved today. Materials: 10 bags cement in. 2 issues: ..." the model saw "No work saved
   today." and then denied the rest.
3. **Earlier days read as today.** `query_work_log` lists every open issue in scope; `project_day.mark_carried_over`
   marks the old ones with `since`, but the code's site-log text (`workflows/activity_query/nodes.py`) did not print
   it, so the model retold a 24 Oct issue as today's.
4. **No reply language setting.** The language was always the message's own (`prompt.reply_language`).

### 23.2 Decisions

- `channel/whatsapp/sent_text.py`: the sender records the words of every message it sends (text, interactive
  header + body, caption) under its wamid, beside `usage.report_sent`; the agent turn records the sender's own words
  under their message id. Redis, 7 days, fire-and-forget. Not a table: it is a reading aid for one week, like
  `recent_turns`, and adds no migration.
- The normalizer reads `context.id` (falls back to `message_id`); a button / list tap is never a swipe-reply.
- `turn.py` reads the quoted words and passes them as `AgentContext.replying_to`; `build_messages` puts
  `[They are replying to your earlier message: "..."]` before the sender's message. The language rule is still
  decided from their own words only.
- `history.gist` keeps every plain sentence of an earlier reply (400 characters), still never a card line, an
  option list, a note or a question. System prompt: never deny one of its own messages; ask them to swipe it.
- The site log prints `(open since 24 Oct)` on a carried-over issue; prompt rule: a fact open since an earlier day
  is not today's.
- `set_reply_language` tool (english / manglish / malayalam / hindi / hinglish / auto), kept with no expiry in
  `UserLanguageStore` (`set_preference` / `get_preference`); `get_profile` returns it, so the composer and the
  localized fixed texts follow it. Per turn it is the `prompt.preferred_language` context variable, read by every
  language decision in code (`reply_language`, `reply_letters_rule`, `wording.language_of`, the runner's wording
  and script checks), so the very reply that sets it is already in it.

### 23.3 Not changed

The scope rule of a reply (`MainReplyContextProvider`) is unchanged: it still looks up `dedup_key` / `reply_wamid`,
so quoting Mesiri's message resolves no scope, as before; quoting one's own earlier message now resolves to that
message's project / site (the M4 design, which never ran because the id was never read). `recent_turns` keeps its
30-minute window. No migration, no Labour / Attendance / Payroll / Workforce change.

### 23.4 Verified / not verified

`tests/unit/test_live29_reply_memory_language.py` (19 tests) and the full assistant suite. Not verified: the live
model with a real swipe-reply payload (the `context.id` key is Meta's documented inbound shape), production data
(no ops token in this session), the Malayalam wording of the model's language-set confirmation.

### 23.5 Rollback

Revert the commit. Redis keys `sent_text:*` expire in 7 days; `reply_language_pref:*` keys are ignored by the old
code.

### 23.6 Follow-up audit (same day)

- **What Mesiri sends on its own was not in the conversation.** Reminders, setup questions, the evening DPR and
  the follow-ups after a reply never entered `recent_turns`, so a bare "yes" to one meant nothing to the model.
  `sent_text` keeps the latest message per recipient (`last_sent_to`, 24 h); the turn adds it as a note when it was
  sent after the last recorded reply and before this message (so the "listening now..." ack never counts).
- **The voice / photo ack was English only.** `processing_ack_text` writes it in the sender's profile language
  (the one they set, else the one they last spoke).
- **The conversation was forgotten after 30 minutes.** `RECENT_TURNS` keeps 2 hours (still 10 turns at most).
- **Checked, no change needed:** a sender's messages run in order (one FIFO lane per sender in the receiver; one ARQ
  worker process); reactions are ignored on purpose.
- **Found, not changed (product decisions, WA-90):** a PDF is always declined ("can't read documents") although
  the agent reads documents through the vision path, because ingress maps `document` to UNKNOWN and never
  downloads it; a sticker gets the "can't read stickers" reply where a thumbs-up sticker usually means "ok".

## 24. Request 143, phase 4 (F): fewer and smaller model calls per message

Approved by Ilan in WhatsApp (29 Oct, request 143). Live before: taps 2.5-7.9 s, messages 6-11 s (a transfer
10.8-11.4 s). Targets: <= 3 s per tap, <= 5 s per message.

### 24.1 What a message cost

The tool loop's model calls (one per round: the calls, then the words), then up to four more model calls after it:
`_in_manglish` (say it again in Manglish), `_one_script` (say it again in one script), `_answer_in_language` (say the
lookup's answer in their language) and `_covering` (say it again naming every card item). Each sent every tool spec
(31 tools, ~30K characters) and the ~23K-character prompt. In draft mode the words above a card are the code's
(`runner._code_card`), so the last round and every re-say were thrown away.

### 24.2 What changed

- **One language pass.** The language is decided once (`wording.decide`, section 22.3) and given to the model as a
  hard rule; what breaks it is cut in code (`_one_script` keeps only its code fallback), a sentence that misses a
  card item or claims a save is the code's covering sentence (`_covering`). `_in_manglish` and
  `_answer_in_language` are gone. No second model call for language or coverage.
- **A round of card lines ends the run.** The tool contract (platform/ai) gets `ToolOutcome.done`: the call needs
  no words from the model. When every call of a round is done, the Gemini adapter (and the fake) ends the run
  (`stop_reason="done_by_tools"`). The toolbox marks a draft-card line done when the turn has no answer, question or
  module line for the model to word. The prompt asks for every call in the first step.
- **A tool subset per turn** (`runtime/agent/tool_choice.py`). The families a message's words name (labour, work,
  material, money, site problems, equipment, reports, team, language) plus the core (a question, still-to-do, the
  card, undo / change, the work site). Every tool when the words name no family, when the message is in Malayalam or
  Devanagari script (their words take endings), and when it answers the assistant's own question. Two tests guard
  it: every golden message's good calls are within its subset, and every tool is in the core or a family.
- **Context.** The sender's site for today is read once per message (it was read by four context lines). The
  turn's Day Facts (section 21.2) is shared by the report and the check layer.

### 24.3 Measured (scripted, the golden sets: 68 messages)

| | before (`3148cdc`) | after |
|---|---:|---:|
| model round-trips per message | 4.04 | 1.82 |
| `run_tools` calls per message | 2.03 | 1.00 |
| tool-spec characters per model call | 30,054 | 16,804 |

At 1.5-2.5 s a round on gemini-2.5-flash that is roughly 6-10 s down to 3-4.5 s a message. **Not measured live:**
`test_assistant` (the bot's live timing tool) needs the teammate listener's token, and production timings
(`journey_traces`) need the ops token; neither was in this session. Taps run no model call; their time is the Save
transaction and the receipt card, untouched here.

### 24.4 Not done

- The "today so far" context line still reads `project_day.read_period` (the shared read helper, saved and waiting
  lines). Moving it onto the Day Facts assembly would change its saved / waiting wording for no latency gain (the
  context lines are read in parallel, under a 0.5-1 s timeout); left for when a reader needs it.
- Tap latency (no model): not changed.

### 24.5 Rollback

Revert the phase commit. No migration. `ToolOutcome.done` defaults to False, so any other caller is unchanged.
