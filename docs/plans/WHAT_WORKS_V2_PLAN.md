# What works, version 2: plan (SA-39)

> Written 15 Nov 2026 for the session that will build it. **Phases 1-3 are built (15 Nov)**: see sections
> 12-14 and [what-works.md](../backend/what-works.md). Phases 4-5 are not. D1, D2 and D4 confirmed (15 Nov).
> Version 1 (SA-38) is live: [what-works.md](../backend/what-works.md). Read that first, it is short.
> Process: root `CLAUDE.md` governs (five phases, work on `main`, verify before every push, phase report).

## 1. Why version 2

The person who asked for the page (15 Nov) said of version 1: *"the UI/UX of this page is bad. We should
be able to find the working, not working, how working, messages, categorising everything, easily
understandable. Or a page also showcasing how each module's messages should work, and multi messages,
memory related, everything: a preview of the best-case scenario. And between this find connections too, to
improve the product easily and fast."*

That is three asks:

1. **Understand at a glance** what works and what does not, per module, in plain words.
2. **See how it should work**: for each module, the best-case conversation, including messages that carry
   several things, follow-ups that lean on memory, corrections.
3. **See connections**: which failures share a cause, where a flow leaks, so the next fix is obvious.

They did not say which parts of version 1 felt bad. The list below is the builder's reading of it, to be
confirmed (decision D1):

| Version 1 does | Why it reads badly |
| --- | --- |
| Titles are tool names ("Record receipt", "Set unit conversion") | Developer words. A product person thinks "material arrived", "set bag size". |
| Judges one message at a time | "Ready on the card" counts as works even when nobody ever tapped Save. The truth is at the conversation level. |
| Three tabs hide each other | You cannot see a module's good and bad side by side. |
| 20% of messages land in "Not sure" as one flat pile | The pile is unreadable; it needs to be split or shrunk. |
| Groups open to a long list of near-identical cards | No ranking, no "start here". |
| No picture of what good looks like | You see what happened, never what should happen. |
| No link between failures | The same refusal under four tools shows as four unrelated rows. |

## 2. What to build

Keep one address, `/what-works`, with three views on a segmented control. The view, window, company and
selection stay in the address (as now).

### View 1: Health (the default; replaces today's page)

One row per **module** (the existing sections), each showing a bar: finished / needed a question /
abandoned / failed, with the count and the change against the previous window of the same length.
Above the rows, one list: **"Fix these first"**, the five largest problems of the window across all
modules, each one line in plain words with its count ("35 messages got no reply: AI unavailable").

A module opens to its **capabilities**: one card per thing a person can ask for, named in plain words,
with: how often it was asked, the share that finished, how people send it (typed / voice / photo), three
real phrasings, and its top two failure reasons. A card opens the detail panel on the right: the
conversations, newest first, failures first, each shown as the WhatsApp chat (the chat component of
version 1 is kept).

Rules for this view:

- Plain words first; the tool name is small grey text beside it, for the builder.
- Works and broken are side by side on every row. No tabs.
- Two clicks from the page to a real conversation, never more.
- Works on a phone (the detail panel goes below, as now).

### View 2: Playbook (how it should work)

Per module, per capability, the **best case as a WhatsApp preview**, one preview per *journey type* that
the capability has really been used in:

| Journey type | How it is recognised in the record (all fields exist in the `agent_api_turn` trace) |
| --- | --- |
| One message, one thing, Save | one write call `ready`, next message a Save tap with `save_results` all ok |
| One message, several things | two or more write calls or lines in one turn, then Save |
| Mesiri asks, person answers | `asked` set or a `held:` status, then a tap/answer, then ready |
| Changed before saving | a later turn calls `change_ready_entry` / `drop_ready_entries` while a card waits |
| Corrected after saving | `correct_saved_entry` or an `undo_*` tool |
| Follow-up that needs memory | a turn that acts on the card or on "Saved earlier" without restating it (the three rows above, plus a message while `pending` is non-empty) |
| A question answered from records | read calls only, status 200 |
| Voice note / photo | `message_type` voice / image on the first message |
| Cancelled | `cancelled` |

The preview is a **real conversation from production**, chosen by a score (finished, no question beyond
the needed one, no correction, no complaint, fast, short), not written by hand. Reason: it shows the real
reply wording and the real card text, it costs nothing to keep current, and it cannot drift from the
product. A journey type with no clean example yet says so ("no clean run of this in the window"), which
is itself a finding. Beside each preview: how often real conversations of that type end the same way.

A later step lets an admin **pin** a conversation as the model example (decision D3).

### View 3: Patterns (the connections)

1. **Same cause, many places.** Failure reasons grouped across capabilities (the normalised reason of
   version 1), so "… is not in the company's material list" is one row listing every capability it hit.
2. **Where each flow leaks.** Per capability, a funnel: asked -> a tool was called -> ready on the card
   -> saved. The widest drop is named.
3. **What makes it worse.** Finish rate split by how it was sent (typed / voice / photo), by language
   script of the message, by role of the sender, by company. Show a split only when both sides have
   enough conversations to mean something (say 10+).
4. **What people do after a failure.** Repeat the message, give up, complain. `admin/friction.py`
   already computes these signals per conversation: reuse it, do not rewrite it.
5. **New, growing, gone.** Each pattern against the previous window.

Every pattern row carries the **actions that make a fix fast**: copy its correlation ids, the command
`python3 scripts/replay_to_test.py <correlation id>` (the start of every fix, per
`docs/engineering/FIX_APPROACH.md`), and, if one exists, the request in the team's request log that is already about it (see section 5,
"not yet known").

## 3. The one change underneath: judge conversations, not messages

Version 1 files each message alone. Version 2 files each **conversation** (one person, no silence longer
than 30 minutes: `review_export.CONVERSATION_GAP`, already used by `build_thread`), split into
**intents**: a message that starts something, plus the taps, answers and corrections that continue it.

An intent ends as: **finished** (saved, sent, or answered), **finished after a question**, **abandoned**
(a card left without Save or Cancel when the conversation ended), **cancelled**, **failed**
(no reply, outage, refusal, save refused), or **complained** (`tell_the_team` bad_ux / wrong_reply /
missing_feature). This is what removes the false "works" of a card nobody saved, and it is what the
journey types and the funnel are counted from.

How to link a tap to the message it continues: the trace has `pending`/`ready` (what waits) and
`save_results` (what the tap saved, with tool and summary). Start with "a Save/Cancel/choice tap belongs
to the nearest earlier intent of the same person with something waiting"; check on real data how often
that is ambiguous before adding anything cleverer. Message-level filing (`classify`) stays as the input
to this step; do not delete it.

## 4. Files expected to change

| File | Change |
| --- | --- |
| `apps/whatsapp-assistant/src/admin/message_map.py` | keep `classify`; add intents, journey type, capability names, funnel, patterns, best-case score. Split into a second module if it passes ~500 lines. |
| `apps/whatsapp-assistant/src/admin/message_map_router.py` | the map answer gains the new shape (version the route or add `view=`; the panel is the only caller, so replacing is allowed) |
| `apps/whatsapp-assistant/src/backend/postgres/{message_logger,trace_logger}.py` | only if a read needs another column; all SQL for a table stays in its one file |
| `apps/whatsapp-assistant/tests/unit/test_message_map.py` | tests for every rule added |
| `apps/control-panel/src/WhatWorks.tsx` | rebuilt as three views; split into `WhatWorks*.tsx` files (the panel's own pages run 200-500 lines each) |
| `apps/control-panel/src/index.css` | layout classes (`.ww-*` exist) |
| `docs/backend/what-works.md`, `AGENTS.md` (placement log), `docs/plans/V1_TRACKER.md` (SA-39) | kept in step |

Database: none for phases 1-4. Pinning (phase 5) needs one small additive table.
Payroll, Workforce, the assistant's reply path, `SOP.md`, `ALLOWED`: not touched. This is read-only.

**Capability names.** Do not hand-write a table of 131 titles. `agent_api/tools.py`
`what_mesiri_does()` already turns each tool's description into a plain line (first sentence, tool names
removed); reuse that for the capability name and keep the tool name as the small grey text.

## 5. What is known about the data (checked on production, 15 Nov)

- `inbound_messages`: about 1,900 messages in 30 days; types text 1,220, interactive (taps) 531,
  voice 158, image 7. Almost all from the team's own test companies, a handful of people.
- `journey_traces`, stage `agent_api_turn` (v3 only, from 2 Nov): keys `calls` (tool, args, result),
  `asked`, `saved`, `save_results`, `pending`, `ready`, `cancelled`, `typed_cancel`,
  `nothing_to_cancel`, `reply_fixed`, `dropped_question`, `feedback_only`, `error`, `outage`,
  `stop_reason`, `before` (the last messages before the turn, on newer turns only), plus large `facts`
  and `state_block` text that `get_turns` leaves in the database.
- A tool result is `{"error": ...}` (refused), `{"status": <int>}` (an API read or write), or
  `{"status": "<words>"}` (`ready, NOT saved`, `held: ...`, `sent ...`, `opened`, ...). Version 1's
  `_call_verdict` reads these; the wording comes from `agent_api/agent.py`.
- On the newest 500 messages version 1 filed 311 works, 87 broken, 102 not sure. Most of "not sure" is
  a reply with no tool call.
- Look at live data with the `control-plane` skill (`python3 scripts/control_plane.py traces --hours 48`,
  `sql "..."`): read-only, 500 rows per query. Keep customer text out of commits and the tracker.

**Not yet known; find out in phase 1, do not assume:**

- Whether a request in the team's request log (`/admin/requests`, TM-19) or a nightly review finding
  (`/admin/review/findings`) can be matched to a message. If no id links them, show nothing rather
  than guess by text.
- Whether "follow-up that needs memory" can be told apart from a plain new message well enough to
  count. If not, show those conversations as examples without a rate.
- How often a tap cannot be tied to one intent.
- Whether the scripted tests in `tests/agent_api/` (167 files) hold whole expected conversations that
  could be shown as a second "as designed" preview. Only worth doing if they do, and only after D2.

## 6. Phases (each one ships by itself)

1. **Intents and capabilities (backend).** Conversation -> intents -> journey type and ending;
   capability names; the funnel. Unit tests on turns shaped like production. Check the numbers against
   a hand count of one day of real conversations and write the comparison in the phase report.
2. **Health view.** Replaces today's page. Screenshots at desktop and phone width in the report.
3. **Playbook view.** Best-case choice by score, one preview per journey type, the rate beside it.
4. **Patterns view.** Shared causes, leaks, splits, after-failure behaviour, trend, the fix actions.
5. **Pinning** (only if D3 says yes): one additive table, a pin button, audited like other admin writes.

## 7. Risks

- **Small numbers.** A few people on test companies produce most messages; a percentage over 6
  conversations misleads. Always show the count beside a rate and hide splits under the floor.
- **A reading, not a verdict.** "Finished" means the record shows a save or an answer, not that the
  answer was right. Say so on the page, as version 1's doc does.
- **Load.** The route reads up to 5,000 messages and their turns on every open. Measure it at 30 days;
  if it is slow, cache the answer for a minute before changing the queries.
- **Customer text.** Platform admins only, same guard as Assistant logs (`require_platform_admin`).
  A new route must have the 401 / 403 tests version 1 has.
- **Drift.** A new tool path or a new status wording in `agent.py` can fall through. Version 1 has a
  test that fails when a route prefix has no section; add the same kind of guard for anything new.

## 8. Testing

- Unit tests for every filing rule, in the style of `tests/unit/test_message_map.py` (the reported
  shape, a sibling, and the case that must not change).
- The full checks before each push, as in root `CLAUDE.md`. Two notes from building version 1 in a
  fresh container: the assistant suite needs `jinja2` and `langgraph` installed or 55 unrelated tests
  fail on import; `git checkout main` in a fresh clone can leave a stale local `main`, so compare with
  `origin/main` before committing.
- The page checked in a real browser on real data: version 1 did this with Playwright and a stand-in
  API fed by a production sample; the live panel was never opened. Say plainly which of the two was done.

## 9. Rollback

Each phase is its own commits; reverting them restores the phase before. No data is written until
phase 5; that table is additive and can stay unused.

## 10. Success

- From the page alone, someone who has never read the code can name the three things most worth fixing
  this week and open a real conversation for each, in under a minute.
- Every module shows what good looks like, or says it has no clean example.
- A card nobody saved no longer counts as working.
- "Not sure" is under 10% of intents, or the page explains what is in it.

## 11. Decisions needed from the person who asked

| | Question | Recommendation |
| --- | --- | --- |
| D1 | Is section 1's list what felt bad, or was it something else (look, colours, density)? | Confirm before phase 2; phase 1 is needed either way. |
| D2 | Best case = the best real conversation, or one written by hand per module? | Real, picked by score: always current, shows the true replies. |
| D3 | Should an admin be able to pin the model example? | Later, after the scored pick has been seen in use. |
| D4 | One page with three views, or three pages in the menu? | One page: the three views share the filters and the chat panel. |

## 12. Phase 1 findings (15 Nov 2026)

Built: `admin/intents.py`, `GET /admin/message-map/intents`, `agent_api/tools.py` `plain_line` (taken out of
`what_mesiri_does`, same output). Answers to section 5's "not yet known":

- **A tap tied to one intent:** always possible on 11 days of data (0 unlinked). What *is* shared is the card:
  14 of 122 Saves/Cancels closed lines from more than one intent, so a Save ends every intent waiting on it,
  and a save line is matched to its intent by tool.
- **Memory follow-ups:** told apart well enough to count when defined as typed words that change the card or
  answer the question (20 intents in 11 days). A message that only leans on context without touching the
  card (e.g. "what did I just correct?") cannot be told apart and is not counted.
- **Requests log / nightly findings matched to a message:** not checked yet; it belongs with the Patterns
  view (phase 4). Nothing is shown until an id links them.
- **Scripted tests as "as designed" previews:** not looked at; waits on D2.
- **"Not sure":** 26% of intents, every one carries its reason from the record. The biggest piece is
  "replied with a question of its own, no tool" (a test script's typed "cancel" asked back again and again):
  it is a finding for phase 4, not noise.
- **Built differently from the plan:** none of the rules needed more than the plan's "nearest earlier intent
  with something waiting", except that one Save ends all of them (shared card).

## 13. Phase 2 (15 Nov 2026)

D1 (section 1's list is what felt bad) and D4 (one page, several views) were confirmed by the person who asked.

Built: the Health view as the page's default (`WhatWorksHealth.tsx`), "Fix these first" in the route's answer
(`admin/intents_summary.py` `fix_first`; the summary moved there to keep `intents.py` under 500 lines), the
first words and the sender of each request in the answer, error codes in words ("AI unavailable").

**One difference from the plan:** version 1's list stays as a second view, "Every message", because it has the
only search over messages and replies. It can go once the Patterns view (phase 4) covers search; the segmented
control gets Playbook and Patterns as those phases land.

Checked in a real browser (Playwright) against a stand-in API that ran the real route on 11 days of production
data, names replaced: desktop 1440 px and iPhone 13; no console error; no sideways scroll on the phone; a
module and a capability (two clicks) open a conversation; the selection survives a reload. Not opened on the
live control panel.

## 14. Phase 3 (15 Nov 2026)

D2 confirmed: the best case is a real conversation picked by a score. Built: `admin/intents_playbook.py`
(`clean`, `score`, `best_case`, `playbook`), the route's `playbook`, the Playbook view (`WhatWorksPlaybook.tsx`).

On 11 days of production data: 96 journey rows across the modules, 8 with no clean run. Reading the picked
examples changed three rules underneath (all with tests):

- **"One message, one thing / several things"** now count only what the first message put on the card; before,
  a request that started with "ys" could be the example.
- **A question asked in words** (a reply ending in "?" with no card waiting, no `asked` in the trace) links the
  next message as its answer (rule 3). Intents 395 -> 372 on the 11 days, "not sure" 104 -> 86; the 13 Nov hand
  count moves from 41 to 40 intents ("cancel all" after "...Kilograms undu?" is now part of that request).
- **A card change sent after Save** marks the saved request as corrected later, not "changed before saving".

Known limit: nothing in the record says a message was rude, so a best case can be one nobody would pick by hand
(seen once on the sample). Pinning (phase 5, D3) is the override.

Checked with Playwright on the stand-in API (real route, production sample, names replaced), desktop and
iPhone 13: no console error, no sideways scroll, selection kept on reload. Not opened on the live panel.

**Feedback during phase 3 (15 Nov): "too much descriptions ... the page look bad and unreadable".** Both views
were cut to labels and numbers: the explaining paragraphs became tooltips (ⓘ), capability cards show the name,
tool, bar, finished share and top reason only (no phrasings, no how-sent line), the request list shows ending,
time and first words, the change against the window before is "+N pts" (hidden when there was no window
before), a Playbook row is its label and "41% of 17" or "No example yet". Later phases follow the same rule:
a number or a label on the page, anything longer in a tooltip.
