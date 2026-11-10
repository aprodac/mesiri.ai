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
