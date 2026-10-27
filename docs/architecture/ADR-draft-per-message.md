# ADR: one draft per message, written only on the Save tap

**Status:** P0 done (request 123: docs and tests only). **P1 built** (request 124, 27 Oct 2026, approved by
Ilan: "Yeah let's do it"), behind the company setting `draft_v2` (off for everyone; on only for the TEST company
once the Mesiri team sets it). P2-P4 each need their own owner ok.
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
