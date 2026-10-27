# ADR: one draft per message, written only on the Save tap

**Status:** proposed (request 123, phase P0: docs and tests only). Needs owner review before P1.
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

## 9. Open questions for the owners

1. Is one draft per **message** or per **open card** (several messages in a row → one card)? Proposal: per
   open card, closed on Save/Cancel or after the existing card expiry.
2. Should Save with one `needs_answer` item save the `ok` ones and keep the card for the rest (proposal), or
   block until all are answered?
