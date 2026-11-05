# The WhatsApp assistant, v3: one model, one SOP, the dashboard's own API

> The one document for v3 (the "API agent"). Asked by Ilan, 1 Nov 2026: *"one base prompted
> model, and just that. The rest is the same backend API calls the web dashboard uses, opened to
> the AI so it understands which to use when."* Tracker WA-119 … WA-132 (and [203], [204]).
> Code: `apps/whatsapp-assistant/src/agent_api/`. v2 (removed): [assistant-v2.md](assistant-v2.md).
>
> **Locked 2 Nov 2026: v3 is the assistant's architecture** (Alan and Ilan approved). v2 is removed
> (WA-134); classic serves real customers until they are moved (WA-137), then it is deleted (WA-138).

## In one picture

```
WhatsApp message (text, voice note, photo, button tap)
   -> journey: sender known? company active? trial cap? assistant_mode = "api"?
   -> v3
        facts up front (read through the API as the sender, in parallel):
            projects + sites, materials + aliases, units, what is recorded today,
            entries waiting for Save, the message's language, today + 2 days of conversation
        one model + SOP.md + 43 tools = the dashboard's API routes (+ web_link, ask, feedback)
            GET  -> runs at once (answers questions)
            POST / PATCH -> prepared, NOT saved: goes into the ready list
        reply = the model's words + the ready list (drawn by code) + ONE Save button
   -> person taps Save (or says "save it")
        -> the entries go to the API as that person (same checks as the dashboard)
        -> "Saved" line, then the green SAVED card
```

## The basics (WA-192)

Agreed with Ilan, 4 Nov 2026. Ten things that must always hold, whatever the person sends. A new
feature does not ship if it breaks one. Taken from the SOP, the code and the inbox complaints.

**How to hold them:** in code wherever code can decide; the SOP only backs it up. The ones that keep
breaking are the ones resting on the model following a written rule ([235], [236] and [238] all came
after [230] was marked done).

| # | Basic | Held by, 4 Nov 2026 | Open or recent |
|---|---|---|---|
| 1 | **Save in English, reply in their language.** Every saved field is English; the reply and card line stay in theirs | Code (`fill.py`: non-English body text is refused back to the model). Manglish in Latin letters rests on the SOP | [243] landed `5dd2fef2` |
| 2 | **Lose nothing.** Every part of a message is saved or asked about | SOP rules 1 and 4, some code ([229]) | [237], [234], [232] |
| 3 | **Say "saved" only when it saved.** Prepared is not saved | Code (`reply_guard.py`, WA-193): the claim is cut from the model's words; "saved" with no tool gets one more try | |
| 4 | **Never change their data.** Same number, same unit, no swapped material | Materials in code; quantities in a reply mostly rule | |
| 5 | **Never create a duplicate.** Recognise what already exists | Repeat saves in code (idempotency key, "Already saved at"); an add for a listed material is not caught | [242] |
| 6 | **Right site, right person, right day** | Code (`decide_site`, missing date filled with today) | |
| 7 | **Work it out first.** At most one question, with buttons and a way out | SOP rules 2 and 3; code since 5 Nov: an unknown material is held as new (WA-194), an unknown size or a missing unit never blocks a line (WA-197) | [232] |
| 8 | **One reply language.** No mixing, in their script | Decided by code; the wording is the model's, with some code-side checks ([231]) | [239] |
| 9 | **Never show internal things.** Ids, error messages, memory notes | Code (`reply_guard.py`, WA-193): ids and API-error sentences are cut; links keep theirs | [242] for the root cause ([226] fixed) |
| 10 | **Never a dead end.** Always an answer or a next step; check the tools before "I can't" | SOP rule 10; outage handling in code | [227], [235], [236], [238], [204] |

Already covered, so not on the list: **access**. The agent works through the dashboard's API as the
person, with their permissions. These basics cover v3 only: companies made before 4 Nov stay on
classic until they are moved (WA-137).

## Status

- **The locked direction** (2 Nov 2026). Every new assistant feature is built here; classic gets
  only fixes for live breakage; v2's code is gone.
- **Live on the two test companies** (Mesiri Test Builders, Paraclette): `assistant_mode = "api"`,
  set by migration 0497 (deployed 1 Nov). **Every company created since 4 Nov starts on v3**
  (WA-176: `create_company` stores `assistant_mode = "api"`, so every door, WhatsApp signup, web
  signup and the control panel, gives the same answer). Companies made before keep classic until moved.
- Model: the `api_agent` row in the control panel (Providers page, "WhatsApp API agent"); unset,
  it uses the `agent` row (gemini-2.5-flash today).
- Not yet measured on real traffic beyond a few days of tester messages and two side-by-side
  runs (below). The real proof is the testers' messages.

## Classic vs v2 vs v3

| | **Classic** | **v2** | **v3 (API agent)** |
|---|---|---|---|
| Who understands the message | Code: classifier, planner, word lists; the model fills slots | One agent reads the whole message | One agent reads the whole message |
| Instructions | Spread through code and prompts | Skill files per module (`agent_v2/skills/*/SKILL.md`, ~270 lines) | One page, `agent_api/SOP.md` (principles) |
| What it calls | Workflows | Tools on the assistant's own toolbox | **The dashboard's API routes** (43) |
| How it saves | Its own workflows -> draft card -> Save | Draft card (classic's save path) -> Save | API request held -> Save -> the API |
| Business rules live in | The assistant | The assistant (shared with classic) | **The backend only** (same as the dashboard) |
| Code around the model | A lot (composer, templates, word lists) | Reply guards, number guard, early stop | Almost none: ready list, buttons, language line, feedback command |
| A new feature | Workflow + prompt + card | Skill + tools + evals | Add the API route to `ALLOWED` (the dashboard gets it too) |
| What it starts with | Today's records, card | Sites, card, catalog, last turns | Sites, materials + aliases, units, today's records, waiting list, 3 days of conversation |
| Memory | Last turns (2 h) | Last 10 turns (v2) / the day (v2_adk) | **Today + the 2 days before** (ADK day store) |
| Taps to save | Save (+ questions per field) | Save (+ card questions) | **One Save**; a needed question comes with buttons |
| Bill photo | Is it a bill? -> confirm -> account -> vendor | As classic (photos stay classic) | Read by vision -> one expense, photo attached -> **one Save** |
| Attendance sheet photo | Rows read -> labour card | As classic | Rows read by vision -> **one attendance report**, every row a line, recorded as a photo -> **one Save** (WA-135) |
| Status | Real customers (until moved) | **Removed** (WA-134) | **Locked direction** |
| Feedback "mesiri bad ux" | — | `tell_the_team` -> team bot | Same tool, and the explicit command is passed on by code too |
| Receipt card after Save | Yes | Yes | Yes (same builder) |
| When the model fails | Retry, queue | Falls back to classic | Retry + queue on an outage; any other error falls back to **classic** (v2 until WA-134) |

**Why v3 does better on mixed messages** (the WA-123 runs): nothing between the model and the
reply cuts the message up, its tools are general reads ("what was reported", "the site's day")
rather than one tool per scenario, and it starts from the facts. **Where it is weaker:** it is
slower (about 2-5 s against 1-2 s), and it depends more on the model following the SOP.

## What the model starts with (`whatsapp._facts`)

- The person's projects and sites with ids (from the resolved sender). One site: "use it; never
  ask which site".
- The company's materials with their default unit and **aliases** ("Steel … also called: kambi,
  TMT"), and the units with ids: read through the API, cached 5 minutes per company.
- **What is already recorded today**: the newest 40 timeline entries, shown oldest first (who,
  what, when, which site). "Did anyone report labour?" needs no lookup; a repeated delivery is
  pointed out before it is prepared. Never cached.
- The entries **waiting for Save** (numbered), so "save it", "cancel the second one" and
  corrections work.
- The **language and script** of the message, decided by the code (the shared detector,
  `runtime.agent.wording.language_of`): Manglish stays in Latin letters. **A language the person
  chose wins** (WA-169): `users.reply_language` (migration 0501; english / manglish / malayalam /
  hindi / hinglish, NULL = follow each message), read each turn with `GET /me/preferences` beside the
  facts (0.8 s cap; unreadable = the last one known). One decision, `whatsapp._turn_language`. Set with
  `PUT /me/reply-language` (tool `set_reply_language`, a normal Save; `auto` clears it).
- The **conversation of today and the two days before** (`memory.DayMemory`): the same Postgres day
  store (`day_store.py`; `assistant_sessions`, migration 0496), app name `mesiri_api`. Today in full
  (120 messages), the two days before their last 30, each marked with its day. Read in parallel
  before the model; written after the reply is sent (never on the wait). The ready list is kept
  as a short note, not its format (the model used to copy it). Without google-adk: Redis per day.

## The tools (`tools.py`, `ALLOWED`)

Each tool is one route the dashboard calls, built from the app's OpenAPI document (path, query and
body fields; `$ref` inlined; valid values shown as enums). A route missing from the API fails the
build and the test. Every write also takes `confirm_line`: the line the person confirms.

| Area | Reads (run at once) | Writes (held until Save) |
|---|---|---|
| Projects / sites | `list_projects`, `list_sites` | — |
| What happened | `day_summary`, `timeline` | — |
| Materials | `search_materials` (name or alias), `list_units`, `stock_levels`, `stock_check`, `list_receipts`, `list_usage` | `record_receipt`, `record_usage`, `record_transfer` |
| Labour | `labour_attendance`, `list_workers` | `record_attendance` |
| Work and issues | `work_progress`, `list_issues` | `record_work`, `report_issue`, `resolve_issue` |
| Money | `list_expenses`, `expense_categories`, `money_accounts` | `record_expense` (bill photo attached by code) |
| Site day, DPR | `site_day` | `set_site_conditions`, `send_dpr` (only when asked, this turn only) |

Plus three tools of v3 itself: `ask` (one question, 2-3 options as buttons),
`save_ready_entries` / `drop_ready_entries` (only offered when entries wait), and `tell_the_team`
(`feedback.py`; v2's tool until WA-134, one definition).

## Saving

1. A write tool prepares an entry (`PendingWrite`: route, body, confirm line, idempotency key) and
   tells the model "ready, NOT saved". The SOP forbids "saved / recorded / njan record cheythu"
   until it is.
2. The reply shows the model's words, then **Ready to save:** with the entries, and one **Save /
   Cancel** button row. A question asked with `ask` shows its options as buttons instead.
3. **Save** (or "save it" in words) sends each entry to the API as the person, with its
   idempotency key (a repeated tap records once). The API's own checks decide; a refused entry
   stays in the list with a plain reason in their language, the saved ones go.
4. The **"Saved" line, then the green SAVED card** (`receipts.py` -> the same
   `RecordReceiptBuilder` classic uses; within 4 s, never blocking the Save). Material in /
   used / transfer, expense, labour, work done and issues have a card.
5. Units: a unit the model names ("bags", "chaakku", "nos", "rod") is turned into the active
   unit id in code (`units.py`, the shared `runtime.unit_words` table), when prepared and when
   saved; an unknown unit gets unit buttons before Save.

Entries wait per person in Redis for a day (an older list's buttons do nothing).

## Fewest taps (SOP rule 1)

- Work it out instead of asking: the only site, the site used most recently, today's date,
  vendor / category / work item as their words (the API matches or creates them: no "new vendor"
  step).
- One question at most, with buttons. Never ask to confirm what the ready list already shows.
- A bill photo: no "is this a bill?"; the expense is prepared from what the photo shows and the
  photo is attached: one Save.

## Photos, voice notes, calls

- **Voice notes**: transcribed first (the existing pipeline), then handled as text.
- **Attendance sheets** (WA-135): the vision step transcribes every row (`workers`); `SOP.md` rule 2
  makes it ONE `record_attendance` with every row a line; a row it could not read ("?") becomes a
  headcount line of its trade, never a person named "?". Entries record how the message came:
  `whatsapp_image` for a photo or document, `whatsapp_voice` for a voice note (the tools' fixed
  `whatsapp_text` is replaced by the code: `whatsapp._channel` -> `agent.run(channel=...)`).
- **Photos / documents**: read by the existing vision step (`pipeline.describe_media`), then
  handled as words; the photo's key is attached to an expense by the code.
- **Calls** (WA-118, `call.py`): the same checks as a message; on a call v3 gets **read tools
  only** (4 rounds, 10 s), so a call never writes; anything to record goes to the chat as the
  usual Save list. Off until a number is listed in `WHATSAPP_CALL_ANSWERS_ALLOWED`. No real call
  tested yet.

## Feedback goes straight to the team bot

- "mesiri bad ux", "this is confusing", a wrong reply, something Mesiri cannot do yet: the model
  calls `tell_the_team` (`feedback.py`), then does the rest of the message.
- **Why a Cancel (WA-146):** "Cancelled" comes with *Wrong site · Wrong amount · Something else*; the tap goes to
  the team bot as feedback naming the cancelled entries and tools. Every Cancel is traced (`cancelled`), and the
  production watch flags cancels and take-backs / corrections (`undo_*`, `correct_work`) as quiet failures (WA-147).
- **Saved conversations on the real model (WA-148):** a complaint becomes a replay test
  (`scripts/replay_to_test.py`); its live half runs the real model on today's `SOP.md` with the same words, facts
  (kept in the trace, 6,000 characters) and API answers. The `SOP eval` workflow runs them all whenever
  `agent_api/` or a replay changes, and posts a failure in the team group (not a deploy gate).
- **"Is this how you want it?" (TM-33, on since 2 Nov, Alan approved; `MESIRI_PREVIEWS`):** for a UX or feature request the team bot
  sends a picture of the planned reply with *Confirm* / *Change it* through `runtime/previews.py` (only to the person
  who asked, v3 companies, 24-hour window, once); the taps are answered by code in every mode (`preview_feedback`).
- **Reference and verdict (TM-21):** a reply that passed something on ends with its reference (`#a83836`),
  the same one the team group sees; for an unclear request Mesiri asks one question with buttons first.
  The "it works now" note has **Works ✅ / Still wrong ❌**; "Still wrong" goes back to the team bot.
- **The explicit command** "mesiri bad ux / bad ui / fix this / fix it" (+ the reason after it) is
  passed on by the code too, when the model did not (approved by Ilan 2 Nov as the one word-list
  exception, a command like "undo"): kind bad_ux / wrong_reply, about = Mesiri's previous reply.
- The turn's trace (`agent_api_turn`, calls with `args`) is read by the team bot's production
  watch (`teammate/brain/src/prod_watch.js`), then TM-18 Autobuild: plan -> build -> push -> the
  person is told in their chat when it works.

## When something fails

- A **provider outage** (quota, auth, timeout): one quick retry, then the queued reply in their
  language and a worker retry (the shared outage handling, `runtime.ai_outage`).
- **Any other error** (a bug in v3 or a tool): `FallBackToClassic`: the message is answered by classic
  (traced `handled: classic_fallback`; v2 answered it until WA-134).
- The AI account's **spending budget used up** (WA-143): no quick retries; the sender is told plainly
  that Mesiri's AI is paused and the message is kept; the team is alerted at once with what to do;
  the worker retries after 20 and 40 minutes.
- A **greeting** is answered by the code (the greeting menu): never needs the model.
- A model error before anything was prepared: one more try; no words after a lookup: asked once
  for the answer.

## Safety

- **Nothing is saved without the person's Save** (or their clear "save it").
- **Same access as the dashboard**: every call carries a 5-minute token for the sender
  (`create_access_token`, the login's claims); the API reloads the user, checks role, project and
  site access and binds the company, as for a dashboard request. Calls run in-process
  (`httpx.ASGITransport`) in their own task, so the company binding never leaks.
- **Only allowed routes**; a tool name not on the list is refused without a call.
- **Idempotency keys per company** on the new endpoints (a key from one company never meets
  another's).
- **A bill photo** is accepted only if that company's own WhatsApp received it.

## Links, corrections and set-up (WA-141, WA-142)

- **`web_link`** (`links.py`): a link to a dashboard page (today, a site's or project's day, issues,
  labour, workers, materials, projects, a project, team, company, expenses, an expense, accounts,
  vendors, analytics, photos). The model names the page and ids; the **code** builds the address from
  a fixed table (`MESIRI_DASHBOARD_URL`, default `https://app.whatsapp.mesiri.ai`), refuses an unknown
  page, a bad id or date, and adds the link to the reply if the model left it out. The dashboard
  still asks for login and shows only what the role allows.
- **Corrections and set-up**, all held for Save and run as the person: correct a work entry, see /
  acknowledge / won't-fix an issue, take back a receipt, usage, transfer or expense, add or change a
  material (and its aliases), add an expense category, create or change a project, add or change a
  site (project and site edits: admins, as on the dashboard). A project name the company already
  has is refused ("Rana Mart already exists", [207]).
- **Add a person to a project** ([207], owner-approved): `add_project_member`. The code matches the
  name said against the company's active people (`GET /projects/{id}/member-candidates`; buttons
  when two could be meant; never a new person) and the role words (classic's `role_words`); the API
  lets an admin or that project's manager add, with a role they may give.
- **Not on the list on purpose:** users and roles (they grant access), removing members, Workforce /
  Attendance deletes, and company modules (platform admins only today: WA-144 is the decision).

## API changes made for v3 (the dashboard benefits too)

| Change | Item |
|---|---|
| Valid values in the schema: issue type / severity, weather, site working, hours lost, movement reason | WA-121 |
| `POST /labour/attendance` and `POST /progress/activities` (same save handlers as WhatsApp) | WA-122 |
| `POST /expenses` takes the bill photo (`media_object_key`, own company only) | WA-124 |
| `GET /materials` lists `aliases`; `search` matches an alias | WA-127 |
| `GET /me/preferences`, `PUT /me/reply-language`: the caller's own reply language (`users.reply_language`) | WA-169 |

## Measured so far

Two side-by-side runs on the real model, 8 site messages, same company for all three
(`Compare agents` workflow; a run costs model calls: start it only when needed):

- **gemini-2.5-flash, 1 Nov** (before the WA-124 fixes): classic 7 good / 1 partly, v2 6 / 1 / 1
  missed, v3 5 good / 3 partly; average reply 1.2 s / 1.6 s / 3.5 s.
- **gemini-3.6-flash, 1 Nov 19:41** (after WA-124): v3 7 of 8 right, the only one that answered
  every part of the mixed message; one miss ("OK." to a stock question, fixed since);
  2-5 s per reply.
- **Production, 2 Nov**: a units bug (fixed, WA-125), a list printed twice and "mesiri bad ux" not
  passed on (fixed, WA-130).

## Switching and rollback

Per company: `PUT /admin/organizations/{org_id}/settings` (platform admin) with `assistant_mode`
= `classic` | `api`. The retired v2 values can no longer be set; stored ones read as `api` (`v2`,
`v2_materials`, `v2_adk`) or `classic` (`v2_shadow`). Instant; no data changes; records saved
through v3 are ordinary dashboard records. Migration 0497's downgrade puts the two test companies
back on `v2`. Code rollback: revert.

## Code map

| File | What it does |
|---|---|
| `agent_api/SOP.md` | The whole prompt |
| `agent_api/tools.py` | `ALLOWED` routes -> tools from OpenAPI |
| `agent_api/app.py` | The API inside the worker: the routers the live app mounts, on the worker's pool |
| `agent_api/client.py` | Calls the API as the sender (token, in-process, own task) |
| `agent_api/agent.py` | One model run: tools, waiting list, ask, feedback, retries |
| `agent_api/whatsapp.py` | WhatsApp side: facts, reply, buttons, Save, memory, card, failures, feedback command |
| `agent_api/memory.py` | Today + 2 days in the ADK day store |
| `agent_api/day_store.py` | The Postgres day store (ADK session service; moved from v2 by WA-134) |
| `agent_api/feedback.py` | `tell_the_team`: feedback to the team bot (moved from v2 by WA-134) |
| `agent_api/units.py` | Unit words -> unit ids |
| `agent_api/receipts.py` | Saved entries -> the SAVED card |
| `agent_api/call.py` | WhatsApp calls (read-only) |
| `runtime/message_journey.py` | Routes a company on `api` to v3 after the sender checks |
| `scripts/api_agent_chat.py` | Try v3 from a terminal (dashboard login + Gemini key) |

## Testing

- `tests/agent_api/` (scripted model, no cost): tools from the real OpenAPI, the WhatsApp flow,
  facts, memory, receipts, feedback, units, outages. `tests/integration/test_api_agent_119_postgres.py`:
  the real routers on Postgres.
- Real model: `Compare agents` workflow (manual). (The deploy's live gate was taken off 2 Nov: the Gemini key's monthly cap, WA-111.)
  Both use the same Gemini key: mind its monthly cap (WA-111).

## Not done / next

Tracked in [V1_TRACKER.md](../plans/V1_TRACKER.md):

- **WA-136 Speed** (2-5 s against classic's 1-2 s): v3 now records its steps (`v3_before`,
  `v3_facts_memory`, `v3_model_tools`, `v3_send`, `v3_saved_card`, `v3_memory_write`, ...) on the
  journey timer, so `vps-perf` shows where the seconds go; cut the largest next. Production, 2 Nov
  (72 h): v3 turn p50 2.8 s, model round p50 1.7 s; the 10 failed of 16 v3 turns were all the Gemini
  monthly spending cap (WA-143).
- **WA-137 Move real customers**, one company at a time, after a few days of the testers' messages
  and a `Compare agents` run (ops: Alan / Ilan choose the first company; rollback is the setting).
- **WA-138 Delete classic** once no company is on it (needs approval: it holds the Labour and
  Attendance save paths classic customers use today).
- **WA-139 Roles on real data**: a non-admin tester (site supervisor on one site) through v3 in
  production. Scripted tests already check the token carries their role and a refused write is
  said plainly.
- **WA-140 Model**: `gemini-3.6-flash` looked better in the one run; price to check before switching
  (the `api_agent` row in the control panel).

## History

| Item | What |
|---|---|
| WA-119 | Pilot: tools from OpenAPI, API as the sender, writes held (materials) |
| WA-121 | On WhatsApp (`api` mode), all modules the API can write, schema enums |
| WA-122 | Attendance and work-done endpoints; both test companies switched (0497) |
| WA-123 | `Compare agents` workflow |
| WA-124 | Facts up front, one-tap questions, bill photos, 3-day memory, wording, language |
| WA-125, WA-128 [203] | Units from `items`, unit words in code, list printed once |
| WA-126, WA-130 | Feedback to the team bot; the explicit command; memory without list format |
| WA-127 | Aliases and today's records up front |
| WA-129 [204] | Outages queued, other errors fall back to v2, greetings by code |
| WA-131 [203] | `send_dpr` only when asked, one turn |
| WA-132 | The SAVED card after a Save |
| WA-118 | Calls (read-only) |
| WA-134 | **v3 locked** (Alan and Ilan, 2 Nov); v2 removed, failures fall back to classic |
| WA-135 | Attendance-sheet photos; entries record photo / voice / text |
| WA-169 | A chosen reply language is kept in the database and always wins |
| WA-192 | The ten basics written down |
| WA-193 | Basics 3 and 9 held by code (`reply_guard.py`) |
