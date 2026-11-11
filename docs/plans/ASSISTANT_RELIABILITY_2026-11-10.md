# WhatsApp assistant reliability: where we are (10 Nov 2026)

Handover from the session of 10 Nov 2026. It holds what was found, what was changed, what is blocked and what
to do next, so the next session can carry on without the conversation. Tracker rows: WA-265 to WA-272 in
[V1_TRACKER.md](V1_TRACKER.md).

## 1. The question and the answer

**Question (Ilan):** is the assistant's unreliability an architecture problem, gaps in the architecture, or an
upgrade that is needed?

**Answer:** the v3 design is right and should not be replaced again (one model, one SOP, the dashboard's API as
tools, nothing saved before the Save tap). What makes it unreliable is gaps inside v3, a missing gate between a
change and its users, and a prompt that has grown too large and too dear. A third rewrite would repeat the loop
Ilan named on 31 Oct and 1 Nov ("are we still in the same loop?", team group #6376, #6784).

## 2. What was read

- The team group "Mesiri group with ai", 28 Oct to 10 Nov (about 1,600 messages), and the request log [15] to [286].
- The v3 code in `apps/whatsapp-assistant/src/agent_api/`.
- Production, read-only, counts only (companies by engine, model call sizes, tools called).

Not read: the assistant-test chat (3,141 messages), the unlabelled APRODAC group, most untranslated voice notes of
31 Oct. There are no customer groups in the inbox: every complaint came from the team (Ilan, midhlaj, Adarsh,
Sahal, asus) on test or own companies.

## 3. Findings

### 3.1 Complaints by pattern (request log, 29 Oct on; approximate counts)

| Pattern | Items | Examples |
|---|---|---|
| Card and Save state: "nothing waiting to save", old buttons, a waiting question swallowing the next message | ~22 | #7688, #8317, #8417, #8731 |
| Materials, units, names: not matched, size asked backwards, Malayalam vs English | ~25 | #5576, #7068, #8001, #8324 |
| Reply untrue, invented or internal | ~14 | #5345, #7717, #8082, #8092 |
| Wrong site, project or earlier context | ~12 | #7487, #7654, #8410 |
| Missing features answered "can't" | ~15 | #5324, #6953, #8425 |
| Language (English lines, mixed or unreadable Manglish, misheard voice) | ~8 | #7663, #8048, #8084 |
| AI down: six outages 31 Oct to 3 Nov | 4 | #5858, #6377, #7074 |

### 3.2 The gaps, checked against the messages and the code

1. **The model's sentence is trusted, then corrected by word patterns** (`reply_guard.py`; up to nine corrective
   re-asks in `agent.py`). Confirmed by the "untrue reply" group. Not fixed yet (step 3).
2. **Taps carried less than the message that made them.** Older-card Save / Cancel was fixed on 8 Nov (WA-263);
   question buttons were fixed on 10 Nov (WA-266).
3. **Materials and units.** Most of it was already fixed between 5 and 8 Nov (sizes bigger unit first, standard
   measures never asked, impossible sizes refused, trade names, new material prepared with its line). The gap left,
   "I don't know" in the person's own words, was fixed on 10 Nov (WA-268).
4. **The card's meaning is not checked before Save.** `card_review.py` exists in shadow (logs only). Not blocking yet.
5. **Memory is the raw chat replayed** (up to 120 messages of today, 30 earlier). Old requests get answered again;
   facts told in passing are not kept. Not fixed yet (step 6).
6. **No gate between a change and its users.** See 3.3.
7. **The prompt is too large.** See 3.4. Found on 10 Nov; not on the first list.

### 3.3 The real-model eval ("SOP eval")

- It could not run from 3 Nov to 10 Nov: the CI key was refused (404, then 429).
- First run after the quota was raised, 10 Nov: **10 of 15 saved conversations right, 5 wrong.**
  - 2 were wrong expectations (the entries were held; the test compared the model's exact sentence). Corrected.
  - 2 cannot be judged from one message (the question before it is not in the trace). Traces now keep the six
    messages before a turn, so new saved conversations carry their context.
  - 1 is open: `716730f2`, three updates in one voice note; the model did not record the cement as a delivery.
    The eval now reports what the model called and said, but no run has happened since.
- ~~It runs `gemini-flash-latest`; production runs `gemini-2.5-flash`.~~ Since 10 Nov both run
  `gemini-3.5-flash-lite` (section 3.7).
- The test company's trial ended on 4 Nov ([262]), so live checks get "trial ended".
- The daily digests of 5 to 9 Nov: 0 fixes confirmed by a real use; 25 to 29% right first time.

### 3.4 Cost and prompt size (the newest finding)

- One full eval run: 36 model calls, **1,398,918 input tokens (about 39,000 a call)**, 8,202 output. The team
  bot's cost line: 95 rupees. The eval's own first estimate said 20 (wrong: too low). The key's 40 and 50 rupee
  top-ups were used up. The true bill is only in the Google console.
- **Production pays the same size on every message.** Average input per model call (`run_tools`): about 16,000
  tokens on 4 Nov, 26,000 on 8 Nov, about 43,000 on 10 Nov. Cost per call by our price table: 0.22 to 0.71 rupees.
  About 50 to 60% of input is already billed at the cached rate.
- What fills a call (estimated from characters, 4 per token):

| Part | About |
|---|---|
| Tool definitions, 121 tools | 22,000 tokens (70% of it parameter schemas) |
| SOP.md | 9,700 tokens |
| "What Mesiri does" block | 2,400 tokens |
| Facts, history, the message | the rest |

- **Use in production, last 10 days:** 558 turns; only 38 of the 121 tools were called at all; about 20 carry
  nearly every call (`record_receipt` 74, `tell_the_team` 45, `record_usage` 24, `record_attendance` 22,
  `add_material` 18, `set_unit_conversion` 16, `create_project` 15, ...); 297 turns called no tool.

### 3.7 The model (decided and changed later on 10 Nov, WA-273)

- **Why now:** Google shuts `gemini-2.5-flash` on 1 Dec 2026 and routes it to `gemini-3.5-flash-lite` from that day.
- **Choice:** `gemini-3.5-flash-lite` for production and the eval. Same price as 2.5 Flash (input 0.30, output
  2.50, cached 0.03 USD per 1M). The step up, `gemini-3.6-flash` / `gemini-3.8-flash`, is 0.75 / 3.75 / 0.075 and
  doubles on 1 Jan 2027: to be compared on the saved conversations once the prompt is smaller (WA-140).
- **Changed in production** (control panel, 03:29 UTC): agent, api_agent, extraction, translation, vision, voice.
- **It broke first.** Every adapter call sent 2.x's `thinking_budget=0`, which 3.x refuses (400 INVALID_ARGUMENT):
  5 of 5 saved conversations failed. Fixed in `8501ced` (`_least_thinking`: a thinking level for 3.x). No customer
  message arrived between the switch and the fix's deploy.
- **First run on it (5 conversations, 9 calls, about 40,000 input tokens a call):** 3 right; `434a6325` did the
  right thing and failed on a word in the expectation (corrected); `716730f2` got a 503 from Google, so it is
  still not judged.
- **The eval's 95 rupees:** `gemini-flash-latest` was almost certainly billing at the 3.8 Flash rate (1.4M input
  x 0.75 USD is the 95 rupees). The same run on 3.5 Flash-Lite is about 37. The eval no longer uses an alias.
- **Not verified:** voice, vision, translation and extraction on the new model with a real call; whether
  Flash-Lite answers as well as 2.5 Flash (5 conversations is too few).

### 3.8 The first prompt cut (10 Nov, WA-272)

- The "What Mesiri does" block (9,400 characters) left the system prompt; `explain_mesiri` returns it. The
  `confirm_line` description, repeated on 66 write tools (13,300 characters), is one short line.
- Measured on the eval: about 8% less input a call (the estimate fell from 2.62 to 2.42 rupees a call). Small:
  tool parameter structure (about 38,000 characters) and the SOP are untouched. The large cut is still tools on
  demand, which waits for Ilan's answer.
- Eval after the cut, `gemini-3.5-flash-lite`: 4 of 5 right. `716730f2` still fails, differently: all three
  updates are now held and the masons are counted right (6, "aaru"), but "20 bag cement" with no verb was held
  as used, and the test wants received. The words do not say which; whether to ask is a product question.

### 3.9 Model comparison and the card check's record (10 Nov, WA-140, WA-264)

- All 15 saved conversations on both models, same code: `gemini-3.5-flash-lite` 13 right (wrong: `716730f2`),
  32 calls, 52 s; `gemini-3.6-flash` 13 right (wrong: `83168ef0`, "what can Mesiri do" also sent to the team),
  39 calls, 82 s, 2.5 times the price. No gain shown: production stays on Flash-Lite. The set is too small and too
  easy to separate two models; it needs the failed chats of 29 Oct to 8 Nov.
- The card check (shadow since 8 Nov) has written no verdict: production had 2 assistant turns on 9 Nov and 2 on
  10 Nov, none with a card (65 to 105 turns a day on 4 to 8 Nov). There is nothing yet to decide "blocking" on.
- The routing table has a fallback provider for voice only; the assistant's own route (`api_agent`) has none.

### 3.5 Classic (the old engine)

- **All 6 companies are on v3** (`assistant_mode = api`); new companies start on v3. WA-137 can be closed.
- Classic handled 2 turns in 8 days. It still matters in three ways: it answers when v3 hits a bug that is not an
  outage (`FallBackToClassic`); the old journey takes what v3 declines (sign-up, trial, other taps); and v3 imports
  shared pieces from `runtime/` (fixed lines, reply clean-up, unit words, outage handling: about 23 imports).
- Ilan (10 Nov): removal is parked until the upgrade is complete. Proposed then: stage 1, a v3 bug keeps the
  message and says so instead of falling back; stage 2, move the shared pieces out and delete the old engine.

### 3.6 Decisions and directions said by Ilan

- No patching: fix the architecture (#4797, #4878, #5094). The one defence that must hold: nothing is entered
  until Save is confirmed (#5096).
- Build on a strong model rather than compete with it; what matters is time until the job is done (#5890, #5901).
- One module at a time (#6054). "Basics first" (#7100).
- Site engineers can add materials (#5572). Everything is saved in English (#5779, #7921).
- 10 Nov, in session: keep the eval's cost low ("this is actually costly for us"); finish the upgrade before
  removing classic.

## 4. What was changed on 10 Nov (all on `main`)

| Commit | Tracker | What |
|---|---|---|
| `98d3c0c` | WA-265 | Eval: daily cap, a 1-token key check before spending, a "refused" message once a day, push and nightly sets |
| `1d5366b` | WA-266 | A question's buttons carry its id; a tap on an earlier question is answered by the code and changes nothing |
| `5b83f66` | WA-268 | "I don't know the size" in any words takes the same way out as the button (`size_not_known`) |
| `269a34a` | WA-271 | Eval failures say what the model did; traces keep the six messages before a turn; four expectations corrected |
| `aa1e002` | WA-272 | Eval runs by hand only; its cost estimate uses the high figure |
| `8501ced` | WA-273 | Gemini 3.x: thinking asked by level; new models priced; the eval pinned to production's model |

Tests: the assistant suite passed after each code change (5,053 at the last full run); ruff clean.

**Not verified:** none of WA-266 or WA-268 was checked on a phone; whether the real model calls `size_not_known`
is unknown (no eval run since); requests [276], [273] (rest) and [278] were not reproduced.

## 5. What is blocked, and on whom

- **CI Gemini key (Ilan):** refused again right after the first run. It needs a budget that fits the eval, or
  billing on that Google project. Until then nothing is checked on the real model.
- **Production read of message text (session permission):** needed to write the ~40 saved conversations from the
  failed chats of 29 Oct to 8 Nov, and to find the cause of [276], [273], [278]. Counts are allowed; a bulk read of
  messages was refused.
- **Test company trial (Ilan):** Mesiri Test Builders expired on 4 Nov ([262]).
- **19 items wait on Ilan** in the team group (#8851), most asking "done, still a problem, or drop?".

## 6. What to do next, in order

1. **Cut the prompt (WA-272).** It lowers the eval's cost and every production reply.
   - Safe cuts first (the model sees the same things): trim the tool parameter schemas; send the "What Mesiri
     does" block only when it is asked for.
   - Then **tools on demand**, if Ilan agrees (asked 10 Nov, not answered): a core set of about 25 tools always
     sent (every tool called in the last 10 days stays in it), the rest grouped by area with one line each, opened
     by the model with one call. Expected: a call of about 43,000 tokens becomes about 26,000 (an estimate).
     Risk: the model not opening a group and saying "can't". Guards: specific group lines, one code-driven second
     try when it says "can't" with no group opened, a per-company switch, and saved conversations for the rarer areas.
2. **One eval run by hand** (5 conversations) after the cut: confirm behaviour, measure the new size, and read
   what the model did with `716730f2`.
3. **Step 3 (WA-267):** the model's turn ends in a structured result and the code writes every "ready / saved /
   not saved / passed to the team" sentence; the corrective re-asks and most of `reply_guard.py` go.
4. **Saved conversations for the open complaints** (needs the production read), and the causes of [276], [273], [278].
5. **Card check from shadow to blocking (WA-264)** once a few days of shadow verdicts show how often it is right.
6. **Step 5 (WA-269):** a spend alert on the production key, a test that the fallback provider takes over, then
   the current model against a stronger one on the saved conversations (WA-140).
7. **Step 6 (WA-270):** memory as today's cards, saved records and a short recent window; facts told in passing kept.
8. **Then classic:** stage 1 and stage 2 of 3.5 (WA-138, needs Ilan's go).
9. **On a phone, any time:** the two checks in section 7.

## 7. Two checks to do on a phone

- Get a question with buttons, send a different message so a new question or card appears, then tap the old
  button. Expected: "That question is closed now" in your language, and what is waiting now.
- When Mesiri asks a size, answer by voice that you don't know. Expected: the two choices (tell the size later /
  save in the unit said), not the same question again.

## 8. How to run the eval by hand

Actions > SOP eval > Run workflow. `set` = `everyday` (5 conversations) or `all` (15). Budget:
`SOP_EVAL_NIGHTLY_CAP_INR` (default 40 rupees, counted at high prices). Model: `SOP_EVAL_MODEL`.

## 9. 11 Nov: the upgrade inside 200 rupees (WA-277)

Ilan, in session, 11 Nov: after the New India conversation (12:56 to 12:59, WA-276) he asked for one big upgrade
"so it acts as a smart assistant", then set the limit: **200 rupees in all for real-model calls; other models may
be tried inside it.** This section is the plan for that. It does not replace sections 1 to 8: it orders what is
left of them around the money.

### 9.1 What 11 Nov added to the findings (production, read-only)

- **The size of a call doubled again.** `gemini-3.5-flash-lite`, last 36 hours: 37,700 input tokens a call,
  0.48 rupees a call with the cached rate (17,600 and 0.27 over the ten days before). A turn is 2.2 calls.
- **The code's own refusals trap the model.** In 10 days, 64 of 587 turns had a tool call refused by a check in
  `agent.py`. In the New India chat one check refused `material_said` and the next turn another demanded it
  (fixed in `4c6ccec`); the class is still there: two checks can ask for opposite things.
- **The card check has a record now** (section 3.9 had none): 13 verdicts, 7 ok, 6 wrong. Three of the wrong ones
  are the New India card, and all three were right: line 3 said Steel after the person said TMT steel.
- **A route that fails in the worker is not seen by any test.** `period_report` had never worked in production
  (no object storage in the worker's API app, about a dozen routes; fixed in `a10d147`).
- **The waiting card is written above every answer.** Four replies in a row began with the same three lines,
  the last one above a stock answer. Open.
- **Thinking is at its lowest** on every call (`_least_thinking`: minimal). It has never been compared.
- **The production read of message text works in this session** (section 5 had it blocked), so the saved
  conversations for the failed chats can be written.

### 9.1b The other days, read in production (22 Oct to 11 Nov)

Read on 11 Nov, after Ilan asked whether the plan rests on one day. Read: every message and reply of the five
companies that are not the test company (161 messages, 5 to 11 Nov), and the day counts of all companies.
**Not read:** the test company's 1,225 messages (80% of all traffic; known through the request log and section
3.1), and traces before 2 Nov (none are kept).

- **Use is small and fell away.** About 1,530 messages in three weeks, 65 to 200 a day until 8 Nov, then 2, 24
  and 7. Outside the test company: about four people. The saved conversations are the evidence there is; live
  traffic will not prove a fix this month.
- **What repeats across days and companies** (each must have saved conversations among the 12 hardest):

| Pattern | Seen | Covered by |
|---|---|---|
| A correction is not taken the first time ("change six masons to five" said twice; "6 rods" became "5 kg", then "I had said 6"; TMT steel) | Aprodac 8 Nov, New India 11 Nov | C, F; [281] [284] |
| Save answers "nothing waiting to save", or the card has another flow's buttons | Aprodac 7 and 8 Nov, cd 6 Nov | WA-263, WA-266 (unchecked live); a saved conversation each |
| "Ready aanu" read as "done" or as nothing ("what is this 'it's ready'?", "Saved?") | Aprodac 7 and 8 Nov | F: the code's line says "not saved yet: tap Save" |
| The site asked again minutes after it was given | Aprodac 6, 7, 8 Nov | C: the site check uses the last site reported to |
| A size question that traps (rods to kg, a load of sand) | Aprodac 8 Nov, cd 6 Nov, New India 5 Nov | WA-268 (unchecked live) |
| English system lines to a Malayalam speaker; Malayalam spelt out letter by letter in Latin | Aprodac 8 Nov, cd 5 Nov | F: state lines are the code's, in five languages |
| Asked for and not there: orders still to come (twice), report as PDF, a week's report | New India 7 and 11 Nov | [275] [279]; out of scope here, listed in the report |
| The AI paused for hours, then "couldn't process" for every kept message | 1 Nov (30 messages), 8 Nov (31) | WA-269: the key, an alert, a fallback |

### 9.2 Objective, scope, value

- **Objective:** the assistant gets a real person's message right the first time far more often, and a fault
  once fixed stays fixed, proven on saved conversations before it reaches anyone.
- **Scope:** `apps/whatsapp-assistant/src/agent_api/` and its tests, `sop-eval.yml`. No new engine, no new
  workflow, router or word list (assistant-v3.md stays the architecture).
- **Out of scope:** new modules on WhatsApp ([222], [275], [169]), deleting classic (WA-138), dashboard work.
- **Business value:** the testers are the only users today and 0 to 29% of fixes were right first time. No
  company can be moved onto it until that changes. A smaller prompt also lowers the cost of every message.

### 9.3 The work, in the order that keeps the money for last

| Step | What | Money |
|---|---|---|
| A | **Saved conversations: about 40**, from the failed chats of 29 Oct to 11 Nov, with `scripts/replay_to_test.py`. Each open complaint in the request log gets one where its turn is in the traces. Expectations compare what was held and asked, never the model's sentence (WA-271). This is the measure for everything after. | 0 |
| B | **Route check with no model:** every route on `ALLOWED` is called once through the worker's own API app on Postgres (`tests/integration/`), so a route that answers 500 fails the build. | 0 |
| C | **One answer per refusal:** the checks a write passes through (`agent.py`, `materials.py`, `fill.py`, `units.py`) run in one fixed order and return one instruction that the same checks accept. A test feeds each refusal's own instruction back and it must pass. | 0 |
| D | **The card is not repeated:** an answer to a question while a card waits ends with one short line ("3 lines still waiting: Save?") and the buttons, never the list again. | 0 |
| E | **Cut the call (WA-272):** parameter schemas trimmed; then **tools on demand** (section 6.1: about 25 core tools always sent, the rest opened by area); SOP rules that belong to one area move into that area's tool notes. Target: about 15,000 tokens a call. Scripted tests and the 19 saved conversations in scripted mode guard it. | 0 |
| F | **Finish WA-267:** the turn ends in a structured result; the code writes every state sentence; card check from shadow to asking its one question before a card it calls wrong goes out. | 0 |
| G | **The paid rounds** (9.4): five small ones, each read and fixed for free before the next. | 200 |

A to D need nothing from anyone. E needs Ilan's yes on tools on demand (asked 10 Nov). F changes what people
see (a question before some cards), so its switch stays per company and is turned on for the test companies first.

### 9.4 How the 200 rupees are spent: in rounds, never in one go

Ilan, 11 Nov: "spending all 200 in one go is stupid, you won't get it all right the first time." So the money is
five small rounds with a reserve. Each round answers one question; its result is read and the faults it shows are
fixed with free work before the next round is paid for.

Prices per 1M tokens (prices.py, 10 Nov): Flash-Lite 0.30 in / 2.50 out; 3.6 and 3.8 Flash 0.75 / 3.75. Counted
with no cached discount and 90 rupees a dollar, as `evalbudget.py` does. A saved conversation is about 2.4 calls.

| Round | Limit | What runs | The question it answers | Free work after it |
|---|---|---|---|---|
| 1. Probe | 15 | 5 conversations, Flash-Lite, after step E | Does the key work? Does the cut still behave? **What does one conversation really cost?** | Every later limit is worked out again from the measured figure |
| 2. First look | 35 | The 12 hardest conversations, Flash-Lite, thinking minimal (production today) | Where does it fail now? | Read each failure; fix code, tool notes or SOP; scripted tests |
| 3. Did the fixes work | 35 | The same 12, same setting | Did round 2's fixes hold, and did they break another? | Fix what is left; if nothing moved, stop and rethink before spending more |
| 4. Settings and model | 45 | The same 12 on Flash-Lite thinking low, and on `gemini-3.6-flash` thinking minimal | Does more thinking or a dearer model get more right, and at what price a message? | Choose the setting; write the price per message beside the score |
| 5. The final score | 40 | As many of the 40 as the limit buys, on the chosen setting (all 40 on Flash-Lite at 15,000 tokens; fewer on a dearer model) | The number that goes in the report | — |
| Reserve | 30 | Not planned | A repeat after a 503, or one more "did the fix work" round | — |
| **Total** | **200** | | | |

The rules of spending:

1. **One round, then stop and read.** No round starts until the one before is written up in section 9.10
   (what ran, right / wrong, the workflow's figure in rupees, what was changed after it).
2. **Each round's limit is passed to the workflow as `cap_inr`,** so a run cannot go past it; conversations the
   limit no longer covers are skipped, not failed.
3. **The limits hold even if step E's cut fails:** 12 conversations on Flash-Lite at today's 40,000 tokens a call
   are about 31 rupees, inside rounds 2 and 3. Only round 4's dearer model and round 5 shrink (fewer conversations).
4. **Money not used in a round goes to the reserve;** a round never borrows from a later one.
5. **Stop early when the question is answered.** If round 3 shows 11 or 12 of 12, round 4 still runs (it answers
   a different question), but a second fix round is not bought.
6. **If round 3 shows no gain over round 2,** nothing more is spent until Ilan has seen why.
7. The estimate is ours; the true bill is only in the Google console. A key whose own limit is 200 rupees is the
   real guard. The workflow uses the repository's CI key; this session has no key and needs none.

Why the 12 hardest and not all 40 each time: a fix is judged on the conversations that fail, and 12 cost a third
of 40. The other 28 still run free in scripted mode on every push (they catch a fix that breaks old behaviour in
the code), and all 40 meet the real model once, in round 5.

Other providers (`platform/ai` has OpenAI and DeepSeek adapters): not in this budget. The assistant's tool-calling
path has only run on Gemini; proving another adapter would eat the money before any comparison.

**If nothing beats production's setting,** production stays as it is and the gain is steps A to F. That is a
result, not a failure.

### 9.5 Files expected to change

`agent_api/agent.py`, `whatsapp.py`, `tools.py`, `SOP.md`, `card_review.py`, `reply_guard.py`, `materials.py`,
`fill.py`, `units.py`; `tests/agent_api/` (new replays and tests), `tests/integration/` (route check);
`.github/workflows/sop-eval.yml` (thinking level as an input); `platform/ai` Gemini adapter only if the thinking
level must be passed through it: that is a shared component, so it stops for approval first.

Backend, dashboard, database, API routes: **no change planned.** No migration.

### 9.6 Risks

- **Tools on demand:** the model does not open an area and says "can't". Guards in section 6.1; every tool
  called in the last 10 days stays in the core set; switch per company.
- **Forty conversations is still a small set.** A two-conversation difference between models is noise; a model
  is changed only for a clear gap, and price per message is put beside it.
- **Saved conversations come from testers,** not customers: they lean to hard and odd messages.
- **The card check asking before the card** adds a question when it is wrong about being wrong. Its record so
  far is 13 verdicts; too few. It goes on for the test companies first.
- **Other sessions and the team bot edit the same files** (ten items in progress on 11 Nov). Small commits, pull
  before each.

### 9.7 Testing, rollback, Labour

- **Testing:** the assistant suite and ruff before every push (CLAUDE.md); every step lands with tests that fail
  before it; the saved conversations in scripted mode on every push (free), on the real model only in step G.
- **Rollback:** each step is its own commit, reverted alone. Tools on demand and the blocking card check are
  company settings: off is instant. A model change is one row in the control panel.
- **Labour, Attendance, Payroll, Workforce:** no change. Attendance is touched only as saved conversations.

### 9.8 Success criteria

1. About 40 saved conversations exist and run free on every push.
2. Round 5 scores at least 85% of what it runs (34 of 40), round 3 beats round 2 on the same 12, and every open "still broken" request ([235] [239] [269] [272] [280]) has a
   conversation that passes or a written reason why not.
3. A production call is at most 20,000 input tokens (37,700 today).
4. No turn in the saved set is refused by a check twice for opposite reasons.
5. Real-model spend for the whole plan is at most 200 rupees by the workflow's ledger, with each round's figure
   written in section 9.10.
6. The team group's "first time right" is above 60% over the 7 days after step F (25% and 0% this week).

### 9.9 Not verified at the time of writing

- Whether WA-276's three fixes are deployed and work on a phone.
- The 15,000-token target: an estimate from section 3.4's table, not a measurement.
- That the CI key accepts a run today (it was refused on most days from 3 Nov).

### 9.11 Steps A to D, done on 11 Nov (no model call, nothing spent)

| Step | What was built | Where |
|---|---|---|
| A | **46 saved conversations** (18 before, 28 new from production turns of 5 to 11 Nov), all free on every push in scripted mode. 12 are marked `hard` (the paid rounds 2 to 4); the everyday set stays at 5. `check()` takes two more kinds of expectation: `must_call_any` and `pending_has`. | `tests/agent_api/replays/`, `replaykit.py`, `pyproject.toml` (marker `hard`), `sop-eval.yml` (`set: hard`) |
| B | **Every route on `ALLOWED` is called once** (131 tools) through the worker's API app on Postgres, with values made from each tool's own schema. A 5xx or a route that raises fails the build; a refusal (404, 409, 422) is an answer. A second test puts the 11 Nov fault back and sees it caught. | `tests/integration/test_api_routes_answer_postgres.py`, last step of the `integration` job in `ci-python.yml` |
| C | **One answer per refusal** (below). | `agent_api/agent.py`, `whatsapp.py`, `tests/agent_api/test_api_refusals_277c.py` |
| D | **The card is not repeated.** An answer given while the same list waits ends with one line ("⏳ 3 still waiting to save (the list above). Tap *Save* to record.", five languages) over the same Save / Edit / Cancel; no list, no picture. | `whatsapp.py` (`_reply(listed=)`, `_with_preview`), `wording.py` (`api.still_waiting`), `tests/agent_api/test_api_card_not_repeated_277d.py` |

**Step C, what the 64 refused turns showed and what changed:**

- *A refusal whose instruction the next check refused.* `change_ready_entry` given the new summary line as a change
  was refused ("cannot change confirm_line", 5 Nov, seven calls and the list dropped): the line is now taken as the
  line. "Pass material_said" for a change now says where it goes in that tool. A change of the line alone is still
  refused (the card must show what is saved) and says which field to send.
- *A list tool called with nothing in the list* answered "no tool named change_ready_entry" (7 Nov, "alla, 6 mason
  aanu": the person was asked for the whole line again). It now says nothing is waiting and to prepare the corrected
  figure as a new line. "There is no waiting entry 3" now says which numbers are waiting.
- *The same refusal round after round* ("material_said is not in English" three times, 5 Nov; each round is a whole
  model call of about 38,000 tokens). A line refused twice for the same reason, or three times for any, is now told
  to stop and ask the person one plain question (`REFUSALS_PER_LINE`). Three different lines refused once each are
  not stopped.
- *"Which site?" asked again* (Aprodac, 7 Nov: saved at Main block in the afternoon, asked again at 01:56 for "6
  masons came today"). The remembered site followed the calendar day while entries follow the working day. Both
  follow the working day now. The next working day still asks ([215] is unchanged).

**Not done in step C (said plainly):** the checks in `agent.py` are still one long function in their old order;
they were not rebuilt as one table. What changed is the contradictions found in production, the list tools, and the
stop after a repeat. A new pair of checks can still disagree: the test file holds one test per refusal that was
fed back, not a proof for every pair.

**What the route check found:** 130 of 131 routes answered; `my_requests` answers 503 when the request log is not
connected (a test database has none): a worded answer, listed as such in the test. No new crash.

**Not verified:** nothing here ran on the real model or on a phone. 13 of the 28 new conversations replay
differently from production because traces before 10 Nov do not keep the site state and the catalogue reads: their
scripted test pins what today's code does with the same calls (said in each file), and two are skipped in scripted
mode; their live tests are the guard. Two chosen turns (`5c2bd4db` "metal", `8d61c9e6` "my requests") could not be
read back whole from the trace and have no saved conversation yet.

**Next:** E (needs Ilan's yes on tools on demand; trimming parameter schemas does not), F, then the paid rounds.

### 9.12 Steps E and F, 11 Nov (no model call, nothing spent)

**E, measured before cutting (all 131 tools, characters):** tool definitions 84,800 in all: tool descriptions
28,700, parameter descriptions 13,900, and about 42,000 of names, types and structure; `enum`, `format`, `minimum`
and `maximum` together are under 2,000. The SOP is 41,700. So trimming the schemas without taking a field or a
description away from the model saves about 2% of a call: not worth a change. Filtering by the company's modules
saves little too (the default has nearly every module on). **The cut that matters is still tools on demand, and it
still waits for Ilan's yes (asked 10 Nov).** E is blocked on that; nothing was changed for E.

**F, two parts done, one left:**

| Part | What | Where |
|---|---|---|
| The code says what was saved | A save made by words ("save cheythoo") gets the code's ✅ / ❌ lines, the same ones the Save button gives, every time (before: only when a line was refused, WA-260). The model's words follow only when they say something else, with any "saved" taken out. | `whatsapp.py` `_on_words` |
| The card check can ask before the card | `card_review` takes a third value, `ask`. The check then runs before the card goes out (at most 6 seconds); a finding the code itself checked puts its one question above the card, and that question is the open one for the next message. The card and Save still go out: the check was wrong on 3 of its 6 "wrong" verdicts so far, and a card held back for a false alarm would be a new dead end. Default stays `shadow`: **no company has it until someone sets `card_review` to `ask` in the control panel** (test companies first). | `whatsapp.py` `_ask_before_card`, `organizations/settings.py` |
| Not done | "The turn ends in a structured result" and removing the corrective re-asks and most of `reply_guard.py`. They guard real faults today and cannot be judged without the real model: to be done after round 2 shows where the model still fails. | — |

Tests: `tests/agent_api/test_api_code_says_state_277f.py` (10).

**Not verified:** not on the real model, not on a phone. `ask` mode adds a second model call to every reply with a
card where it is on (time and cost): measure both on the test company before any customer gets it.

### 9.13 Step E built, 11 Nov (no model call, nothing spent)

Ilan approved tools on demand in session on 11 Nov ("Okay approved"), after asking what it is.

- **Built:** `agent_api/tool_areas.py` (11 areas, 91 tools; 40 stay core), `open_tools`, the run going on in the
  same turn with the area's tools, the area's own SOP rules travelling with it, the chat keeping an opened area for
  12 hours, the company setting `tools_on_demand` (off by default), and the `SOP eval` workflow's
  `tools_on_demand` input (default on). Details: assistant-v3.md, "Tools on demand".
- **Measured from the definitions, not on the model** (4 characters a token): tool list 22,100 -> 7,800 tokens;
  SOP 10,400 -> 7,600. A call that opens nothing should fall from about 37,700 to about 20,500 tokens.
  **The 15,000 target of 9.3 is not reached:** what is left is the SOP's shared rules (2, 6 and 14 alone are
  3,500 tokens), the facts and the replayed history (WA-270). The limits of 9.4 already allow for this (rule 3).
- **What a message in an area costs:** one more model call (the small one that opens the area), then a call with
  that area's tools: 900 to 1,900 tokens more than the core.
- **Not done:** no company has it on. It goes on for the test company after round 1 shows the real model opens
  areas; thinking level as a workflow input (it needs a change in `platform/ai`, a shared component: to be asked
  before round 4).
- **Not verified:** that the real model calls `open_tools` when it should, and does not say "can't" instead. That
  is exactly what round 1 is for; the hard set needs at least two conversations in a closed area before round 2.

Tests: `tests/agent_api/test_api_tools_on_demand_277e.py` (21).

### 9.10 The rounds as they happen

| Round | Date | Ran | Right / wrong | Rupees (workflow) | Spent so far | Changed after it |
|---|---|---|---|---|---|---|
| 1 (first part) | 11 Nov 18:16 UTC | `SOP eval` run 149, set `areas`, `gemini-3.5-flash-lite`, tools on demand on, `cap_inr` 8. 3 of the 5 cases ran (10 model calls, about 19,800 input tokens a call); the 2 guards (a delivery and an attendance question open nothing) were skipped when the cap was reached | **3 right, 0 wrong**: payments, machines and wages each opened by the real model, and a tool of that area used | 13.07 by the workflow (it counts every token at 0.75 USD per 1M); about 5.3 at Flash-Lite's list price (0.30) | 13.07 of 200 by the workflow's figure | Nothing yet. Found: (1) the cap is checked before a conversation, not during, so a run can pass it by one conversation (8 asked, 13.07 used); (2) the workflow's figure is 2.5 times Flash-Lite's list price, so 200 "workflow rupees" are about 80 at list price: Ilan to say which figure the 200 is counted in; (3) an area message took 3.3 calls, not 2.4 |
| 2 | 11 Nov 18:22 UTC | Run 150, set `hard` (the 12 hardest), `gemini-3.5-flash-lite`, thinking minimal, tools on demand on, `cap_inr` 60. All 12 ran (33 model calls) | **11 right, 1 wrong**: `cement_and_hollow_bricks_used_276`, "30 hollow bricks used" held as "30 nos Solid Blocks" | 47.33 by the workflow; about 19 at list price | 60.40 by the workflow; **about 24 of 200 at list price** (Ilan, 11 Nov: "do whatever you want, just make it reliable"; the 200 is counted at list price, both figures kept here) | **Two faults found behind the one failure, both fixed with no model call:** (1) the replay answered the code's own read of the material list with nothing, which switches the material check off, so the model was judged without the check production runs: a live replay now answers it from the turn's facts (`replaykit.facts_catalogue`); (2) a real one, in production too: when the code moves a line to the material the person named (new or listed), the line's text stayed the model's, so the 7 Nov card read "New material: Hollow Bricks" above "30 nos Solid Blocks": the text now follows the material (`agent.line_on`, `test_api_line_follows_material_277.py`, 10 tests). Not closed: a model that writes its own guess into `material_said` is believed (no cheap code check across scripts; this is what the card check in `ask` mode is for). No tool area was opened wrongly in the 12. |
| 3 | 11 Nov 18:29 UTC | Run 151, the same 12, same setting, after round 2's two fixes (44 model calls: the code's material check now runs, and it translates a word it cannot match) | **12 right, 0 wrong** | 44.00 by the workflow; about 18 at list price | 104.40 by the workflow; **about 42 of 200 at list price** | Round 4 changed: with 12 of 12 on the cheapest model, the 12 cannot tell a dearer model or more thinking apart (the same thing 10 Nov found with 13 of 15), so its money goes to the conversations never run on the real model (`rest`, 91 cases), where the next faults are. A dearer model is only worth a run on the cases the cheap one still fails. |
| 4 | 11 Nov 18:32 UTC | Run 152, set `rest` (every conversation not in `hard` or `areas`: 36 cases, none run on the real model since the cut), same setting, `cap_inr` 125 (86 model calls) | **32 right, 3 wrong, 1 expected failure.** Wrong: `give_daily_reports` (opened the reports_out area and answered with a link: caused by tools on demand); `new_project_277` (the cement held at Green villa, no project made: [277] again); `two_work_updates` (two work updates held as one line) | 112.45 by the workflow; about 45 at list price | 216.85 by the workflow; **about 87 of 200 at list price** | (1) fixed, free: `open_tools` now says what never needs an area (the daily report, a project's week or month, everyday records) and reports_out says what it is not. (2) and (3) are the model's reading, with the right tools in front of it: these two are what a dearer model is tried on next (the `only` input runs chosen cases). So far on the real model, all sets: **47 of 50 judged cases right.** |
| 5 (not run) | 11 Nov 18:38 UTC | Runs 153 and 154: the three failed cases again after the reports_out fix, on `gemini-3.5-flash-lite` and on `gemini-3.6-flash` (`only` input) | **Nothing ran: the CI key was refused before any conversation (HTTP 429 RESOURCE_EXHAUSTED)**, 4 minutes after round 4. The key's own limit is reached (or its per-day quota): the session cannot see which | 0 | 216.85 by the workflow; about 87 of 200 at list price. The true bill is in the Google console | Spending stopped by the key itself. Open until it accepts a run: is `give_daily_reports` right after the fix; do `new_project_277` and `two_work_updates` pass on a dearer model. The workflow told the team group once ("Needs you"). |
| 5 | 11 Nov 18:45 UTC (quota raised by Ilan) | Runs 155 and 156: the three failed cases, on `gemini-3.5-flash-lite` (11 calls) and on `gemini-3.6-flash` (14 calls) | Flash-Lite **0 of 3**; 3.6 Flash **2 of 3** (`give_daily_reports` and `two_work_updates` right; `new_project_277` wrong on both) | 12.62 and 16.94 by the workflow; about 5 and 17 at list price | 246.41 by the workflow; **about 109 of 200 at list price** | (1) `new_project_277` could not be answered by any model: the message names no project and the trace kept nothing before it. The four turns before it are written in from production's conversation. (2) `give_daily_reports`: no area is opened any more, but Flash-Lite answers with a link; SOP rule 6 now names the ways people ask for the report and says a link alone is never the answer. (3) `two_work_updates`: SOP rule 1 says two works are two entries. **On the model:** 3.6 Flash got 2 cases right that Flash-Lite did not, at 2.5 times the price, out of 50; Flash-Lite stays unless the two rule fixes do not hold. |
| 5b | 11 Nov 18:51 UTC | Run 157: the same three on `gemini-3.5-flash-lite` after the two SOP lines and the added context (11 calls) | **1 of 3.** `two_work_updates` right now. `give_daily_reports` still answered with a link (the SOP line did not move it). `new_project_277` now makes the project and puts the cement on it, but prepared the project twice and held both "50" and "100" bags (the person said "about 50, now 100": a correction inside one sentence) | 12.79 by the workflow; about 5 at list price | 259.20 by the workflow; **about 114 of 200 at list price** | Fixed, free: a thing made by name (project, material, site) is prepared once a turn (`agent.same_named`). **Open, not fixed:** (a) a report asked for in plain words gets a link on Flash-Lite: a written rule did not hold, so it needs a code decision (a report request with no report tool called is sent back once, as "can't" is); (b) a number corrected inside one sentence ("50, now 100") held twice. **Where it stands:** of 50 judged cases Flash-Lite gets 48 (47, plus `two_work_updates`); 3.6 Flash got `give_daily_reports` right where Flash-Lite did not. No more is spent today. |
| after 5b (free) | 11 Nov, late | No run. `give_daily_reports`: the reports link's own result now says which tool gives the report in the chat (`links.IN_CHAT`: `reports` -> `day_summary` / `send_dpr`, `period_reports` -> `period_report`), the place the model reads mid-turn, as WA-275 did for a new project | Not run on the real model | 0 | 259.20 by the workflow; about 114 of 200 at list price | Next paid step: the one case (`only: give_daily_reports`, small `cap_inr`). The corrected number ("50, now 100") is left to the card check in `ask` mode: the code cannot tell a correction from two deliveries. |
| 6 | 11 Nov 20:11 UTC | Run 158: `give_daily_reports` alone, `gemini-3.5-flash-lite`, `cap_inr` 8 (2 calls) | **0 of 1**: the note beside the link was passed over, the reply was the link again | 2.73 by the workflow; about 1 at list price | 261.93 by the workflow; about 115 of 200 at list price | The link is now held back once: `web_link` for a page a tool gives in the chat returns no address until that tool was called in the turn, or the link is asked a second time (`agent.py`, `link_held`). |
