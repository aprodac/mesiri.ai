# Mobile app, part 1: the site engineer

> Asked 21 Nov 2026 (in session): *"lets start working on the mobile app. lets design in a good ui and
> first focus fully in the site engineer side and for them to reliably navigate also and able to tell in
> voice like malayalam and all and enter data to fields or a specific thing."*
> Follows the 17 Nov decision that Mesiri gets a mobile app alongside WhatsApp ([DECISIONS.md](../DECISIONS.md)).
> Tracker: **MOB** section of [V1_TRACKER.md](V1_TRACKER.md). Screen mockups (six phone screens, clickable):
> the "Mesiri Site Engineer App" design canvas shared in session.
>
> Status: **building (21 Nov).** Done: MOB-01 design, MOB-02 shell, MOB-03 say anything, MOB-04 Today, MOB-05 forms
> filled by voice, MOB-08 sign-in, MOB-10 site and requests. Next: MOB-07 no signal, MOB-06, MOB-12.
> §9's defaults were taken (asked to "go implement" 21 Nov): Android first, phone + WhatsApp code sign-in, replies in
> the app only, English and Malayalam.

## 1. What the app is for

The site engineer's whole day on one phone, the same way WhatsApp works for them now: **speak it, check
it, save it.** Most of the time they say the day in one voice note ("innu 6 mason, 8 helper, 50 chaakku
cement vannu Malabar-il ninnu, randaam nilayil plastering 42 sqm"), look at what Mesiri understood, and
tap Save once. When they want to, they can open a form and fill one thing, by tapping or by speaking into
that one field.

What the app adds over WhatsApp, and why customers asked for it:

| WhatsApp alone | The app |
|---|---|
| A chat: you can't see what's left to tell today | **Today**: the site's day as a checklist (attendance, work, materials in, used, machines, problems, photos, weather). What is missing is plain to see |
| Hard to fix one number in a long message | Each saved line opens as a **form**; change one field, by tap or by voice |
| Stock, requests, deliveries are a question away | **Site**: stock, running low, requests and what is coming, one tap |
| Needs signal at the moment you send | **Works with no signal**: voice notes, photos and forms wait on the phone and send themselves |
| Shared phone numbers, groups, forwarded messages | One person, signed in, on their own sites |

WhatsApp stays. Both are doors into the same Mesiri: an entry saved in the app shows in WhatsApp's "what
did I send today" and on the dashboard, and the other way round.

## 2. Investigation (Phase 1)

What exists, and what it means for the design.

| Found | Where | What it means |
|---|---|---|
| **An Expo app already exists** (Expo 54, expo-router, a theme system, lucide icons) but it is a prototype: mock projects and sites, portfolio and analytics screens for managers, and one field materials screen. Last real change long before 17 Nov | `apps/mobile` | Keep the toolchain (Expo, router, theme tokens, `@mesiri/auth`), **replace the screens**. The manager screens are parked, not deleted, until the owner's side is designed |
| **Tell Mesiri on the dashboard** already sends typed text and voice notes to the **same assistant WhatsApp runs** (same handler, same Save card, same role and module checks), acting as the signed-in user | `POST /assistant/messages`, `POST /assistant/messages/voice` (`apps/whatsapp-assistant/src/web_assistant/router.py`); dashboard `components/tell-mesiri/` | **The app's voice is this, not a new pipeline.** No new parser, no word list, no workflow (CLAUDE.md: v3 only). Malayalam, Manglish, Hindi, Tamil and English are already understood; every fix to the assistant improves the app the same day |
| v3: one model + SOP + the dashboard's own API routes as tools; writes are **prepared, not saved**, until Save | `agent_api/agent.py`, `tools.py` `ALLOWED`, [assistant-v3.md](../architecture/assistant-v3.md) | The app's "check before saving" screen is the existing Save card. The 10 basics (save in English, lose nothing, never "saved" unless saved…) hold for the app unchanged |
| Voice is heard by Sarvam (`saaras:v2.5`, speech + translation to English) | `platform/ai/.../adapters/sarvam/adapter.py` | Malayalam and Indian languages are already covered; transcript and detected language come back |
| The voice route takes **Ogg/Opus only**, up to 62 s / 5 MB | `web_assistant/router.py` `VOICE_MIME` | Android can record Opus; **iPhone records AAC (m4a)**. The route must take m4a too (small, additive) |
| The reply is text + buttons (`AssistantReply`: text, buttons, list rows) and the transcript. **The prepared entries are not in the response as data** | `WebMessageResponse`, dashboard `lib/api.ts` | Enough for the Save card as buttons. To fill a **form** from voice (§5.3) the response must also carry the ready entries (tool + fields), additive |
| Entries record how they came (`whatsapp_text`, `whatsapp_voice`, `whatsapp_image`); the dashboard door marks `source = dashboard` | `agent.py` `CHANNELS`, `web_assistant` `SOURCE` | Add `app` as a door so the inbox and the DPR can tell where an entry came from |
| Every form the app needs already has its API route (the dashboard uses them): attendance, work done, receipts, usage, machines, issues, photos, site conditions, material requests, the site's day, stock | the tools list: `record_attendance`, `record_work`, `record_receipt`, `record_usage`, `log_machines`, `report_issue`, `set_site_conditions`, `ask_for_material`, `site_day`, `day_summary`, `stock_summary`, `material_requests` … | **No new backend modules.** Forms post to the same routes, with the same checks |
| Sign-in: email + password, **and a code on WhatsApp** (found while building: the dashboard already has `/auth/code/request` + `/auth/code/login`, SS-06) | `apps/whatsapp-assistant/src/auth/code_login.py` | The app uses both as they are; no auth change, so no approval needed (MOB-08) |
| Brand: hazard yellow `#facc15` with dark ink, charcoal `#3E3C3D`, warm ground `#f6f3ed` (WEB-76). The mobile app was left on its old colours | [DESIGN.md](../DESIGN.md), `apps/mobile/src/theme` | The app takes the dashboard's brand tokens |
| SS-76b (the playground's site engineer part) waits for the app's shape | [V1_TRACKER.md](V1_TRACKER.md) | This plan gives it: the playground can show the app's Today and mic |

**Regression risks.** The app reuses the assistant; anything that changes `web_assistant` (m4a, ready
entries in the response, the `app` door) is additive, but Tell Mesiri on the dashboard uses the same route
and must keep working byte for byte. Module isolation: nothing in Payroll or Workforce changes; Labour
(attendance) is only called through its existing routes.

## 3. Design principles for the site

1. **The thumb, the sun, the dust.** One hand, often gloves or wet hands, bright sunlight. Every target is
   at least 48 px (main actions 56 px, the mic 72 px), text at least 15 px for content, strong contrast
   (light theme by default, ink on white; yellow only as a fill under dark text, never as text).
2. **Voice first, never voice only.** The mic is in the same place on every screen (the middle of the
   bottom bar). Everything said can also be tapped or typed.
3. **Nothing is saved behind their back.** Speaking prepares; one Save saves. What was heard is shown
   ("You said", in their script) and what will be saved is shown, line by line, before Save.
4. **At most one question.** Mesiri works out the site, the date, the unit, the material, and asks one
   thing with buttons when it truly cannot ("Which cement? OPC 53 / PPC / Not sure").
5. **Reply in their language, save in English.** The app's words follow the person's language (the same
   setting as WhatsApp's `set_reply_language`); saved fields are English so the office reads them.
6. **Always know where you are.** The site you are reporting for is always at the top. Every screen is at
   most two taps from Today. Back always goes back. No hidden gestures, no drawer menus for daily work.
7. **No signal is normal.** Anything recorded is kept on the phone and sent by itself; the app says how
   many are waiting, never loses one, and never sends one twice (the API's idempotency keys).

## 4. Navigation

Five places in the bottom bar, the mic in the middle:

```
  Today      Site      [ MIC ]      Requests      More
```

| Place | What is there | Main actions |
|---|---|---|
| **Today** (home) | The site's day: 8 rows (attendance, work done, materials in, materials used, machines, problems, photos, weather and site), each "done, with what" or "not told yet"; "6 of 8 done"; when today's report goes to the office, and Send now | Tap a row → its form; mic → say anything |
| **Site** | Stock (running low first, days left, on order), Requests, Coming (deliveries due) | Ask for material; mark a delivery received |
| **Mic** | Full-screen listening: the site it is for, the language heard, live words, what you can say | Stop → "Check before saving" |
| **Requests** | Their material requests and the office's answers; problems they raised and their status | New request |
| **More** | Switch site, language, sent and waiting (offline queue), past days, profile, sign out | |

**The site at the top** is a button on every screen. The app picks it for them: the site they reported
from last today, else the only site they belong to; if they say another site's name in a voice note,
Mesiri's existing `decide_site` picks it and the card says so. Later (not V1): nearest site by location.

**Voice can navigate too**, without a new router: Mesiri already answers with links (`web_link`). The app
maps dashboard links to its own screens ("show cement stock" opens Site › Stock on cement). A link the app
has no screen for opens the dashboard page in the browser.

## 5. Voice: three ways to speak

### 5.1 Say anything (the big mic)

The common case. Record → send to `POST /assistant/messages/voice` → show "You said" + Mesiri's line in
their language + the **To save** card (each line: what, how much, where) + Save all / Say a change /
Cancel. Buttons are the assistant's own buttons (`interactive_reply_id`), so Save in the app is exactly
Save on WhatsApp. Up to 60 s per note (the route's limit).

### 5.2 Speak into a form

Each form (Material received, Attendance, Work done…) has "Speak to fill the whole form" at the top. The
voice note goes to the same route, and the prepared entry comes back with its fields; the app puts them in
the form, marked "From your voice", for the person to check and Save. **Needs:** the response to carry the
ready entries (tool + fields) and the app to say which form is open, so Mesiri prepares that kind of entry
(a hint in the message, not a new tool).

### 5.3 Speak into one field

Every field has a small mic. For a text field (a note, a problem's description) the words are heard,
shown in their script, and **put into the field in English** (Sarvam's translation, the same as today),
with their own words above it. For a number, a material or a supplier, the words go through the assistant
like 5.2 but only that field is taken. Nothing new learns Malayalam numbers: the model already does.

## 6. The screens (mockups)

Six screens, drawn at phone size (390 × 844), on the design canvas:

1. **Today** – the site's day as a checklist, report progress, the bottom bar with the mic.
2. **Speak** – Mesiri is listening: the site, "Malayalam" heard, live waveform, what was heard so far, hints.
3. **Check before saving** – "You said" (folded), Mesiri's line in Malayalam, the TO SAVE card with three
   lines, one question with buttons, Save all 3 / Say a change / Cancel.
4. **A form filled by voice** – Material received: fields filled from the voice note; the Note field
   listening, Malayalam above, English that will be saved below; bill photo.
5. **Site** – Stock with "2 running low", days left, on order; Ask for material.
6. **Switch site, language, offline** – the sheet to change site, the reply language, and the "no signal,
   2 waiting" banner.

Look: the dashboard's brand (hazard-stripe top line, yellow fills under dark ink, charcoal, warm ground,
white cards), Inter plus Noto Sans Malayalam / Devanagari / Tamil so every script renders properly.

## 7. Implementation plan (Phase 2)

**Objective.** A site engineer can run their whole day from the app: see what is left, say it in their
language, check it, save it, with or without signal.

**Scope (V1 of the app).** Site engineer only; Android first (most site engineers' phones), iPhone from
the same code once it runs on Android. Out of scope for now: the owner and PM screens, approvals, money,
BOQ, drawings, location-based site choice, calls.

**Business value.** Customers said WhatsApp alone will not work for everyone (17 Nov). Daily reporting is
the habit everything else depends on (DPR, stock, cost); the app makes it faster and visible.

**Files expected to change.**

| Where | Change |
|---|---|
| `apps/mobile/app/**`, `components/**`, `src/**` | New screens (Today, Speak, Check, forms, Site, Requests, More), navigation, theme to brand tokens, real data (no mocks), i18n (en, ml first; hi, ta after), offline queue |
| `apps/mobile/package.json` | `expo-audio` (recording), `expo-image-picker` (photos), `@react-native-community/netinfo`, `expo-sqlite` or AsyncStorage (queue), `@tanstack/react-query` (as the dashboard) |
| `apps/whatsapp-assistant/src/web_assistant/router.py` | Accept `audio/mp4` (m4a) as well as Ogg; add the ready entries to the response (additive field); `source` / channel `app` when the app calls |
| `apps/whatsapp-assistant/src/agent_api/agent.py` | `app_text`, `app_voice` in `CHANNELS` |
| `packages/auth` | Token storage on the phone (`expo-secure-store`) |
| Later, needs approval: `domains/identity` | Phone + WhatsApp code sign-in (MOB-08); push tokens table (MOB-09) |

**Backend work.** Three additive changes to the assistant's web door (m4a, ready entries, the `app`
door). No new routes for data; forms use existing ones.

**Frontend work.** The Expo app as above.

**Database work.** None for MOB-02 to MOB-07. MOB-09 (push) adds one table (additive).

**API work.** `WebMessageResponse` gains `ready: [{tool, summary, fields}]` (optional, so the dashboard is
untouched); `/assistant/messages/voice` takes `audio/mp4`.

**Risks.**
- Voice notes recorded offline are answered later: Mesiri's question may come when they have moved on.
  The answer arrives as a notification and waits on Today ("1 to check").
- Answers take 5–20 s (model + voice). The app shows progress and lets them leave the screen; the card
  waits on Today.
- Sarvam m4a support must be checked before MOB-03 ships (else convert on the server).
- The trial's AI cap and the route's rate limit (20 per 10 min per person) apply to the app too; a heavy
  user could hit the per-person limit. Watch it in the pilot.
- Two doors, one person: an entry prepared on WhatsApp and one in the app at the same time. The ready list
  is per person; the card shows both, and Save saves what is shown.

**Testing strategy.** Backend: unit tests for m4a, the ready field and the `app` channel in
`apps/whatsapp-assistant/tests` (web assistant tests), and the full suite (CLAUDE.md). App: TypeScript
check, a web build of the Expo app to check screens in Chromium at 390 px, then a real Android phone with
Malayalam, Manglish and English voice notes on a sample company, offline (airplane mode) included.

**Rollback strategy.** The backend changes are additive and optional fields: revert the commits; the
dashboard's Tell Mesiri is unaffected. The app is a separate package: an older build keeps working against
the API; a bad build is pulled from the store's testing track.

**Labour isolation.** Attendance is written only through the existing Labour routes the assistant already
uses; nothing in Labour, Payroll or Workforce changes.

**Success criteria.** On a real Android phone, a site engineer: signs in; sees Today for their site; says
a Malayalam voice note with attendance + a delivery + work done and saves all three in one tap; corrects
one quantity by speaking into its field; records a delivery with no signal and sees it sent when signal
returns; all of it shows on the dashboard's day page and in the DPR.

## 8. Build order (tracker MOB)

| ID | What | Needs approval? |
|---|---|---|
| MOB-01 | This design and the mockups | done |
| MOB-02 | App shell: brand theme, bottom bar + mic, site at the top from the real projects and sites, email sign-in, en + ml words, mocks removed | no |
| MOB-03 | Say anything: record, send, You said, the TO SAVE card with its buttons (backend: m4a, `app` door) | no |
| MOB-04 | Today: the site's day from the existing routes | no |
| MOB-05 | Forms for the 8 rows, posting to the existing routes; speak into a form (backend: ready entries in the response) | no |
| MOB-06 | Speak into one field | no |
| MOB-07 | No signal: the queue, "waiting" count, sent by itself, never twice | no |
| MOB-10 | Site: stock, requests, coming; ask for material | no |
| MOB-08 | Sign in with phone number and a code on WhatsApp | no (the existing /auth/code routes) |
| MOB-09 | Notifications (a question waiting, a request answered, report reminder) | **yes: ops (push keys) + a new table** |
| MOB-11 | Android build and the Play Store testing track | **yes: ops (store account)** |

## 9. Decisions needed (proposed default in bold)

1. **Android first, iPhone from the same code after.** (Alternative: both at once.)
2. Sign-in for site engineers: **phone number + a one-time code sent on WhatsApp** (MOB-08); email +
   password until then.
3. Does an app user also get Mesiri's replies on WhatsApp? **No** (as Tell Mesiri on the dashboard: the
   reply comes back in the app only).
4. The app's languages at launch: **English and Malayalam**, Hindi and Tamil next.

## 10. Found while building (21 Nov 2026)

- **Phones can't record Ogg.** expo-audio offers AAC in MP4 only (Android and iPhone). Sarvam reads m4a by its
  content (checked: a Malayalam clip sent as m4a and as Ogg gave the same English), so only the assistant's web
  door changed (it refused anything but Ogg). The shared speech adapter is untouched. Gemini's speech path also
  labels audio as Ogg and was not checked with m4a.
- **A site-scoped person's site filter needs the project.** `stock-summary` and `procurement/requests` answer
  `[]` to a site engineer who sends `site_id` alone; the app always sends `project_id` with it.
- **The prototype could not have run.** It mixed React 19.2.7 with react-dom 19.1.0 (a blank screen); React is
  now pinned to Expo 54's versions.
- **Machines** are not in the site day's data, so Today has 7 rows, not 8; machine hours are taken by voice.
- **How a form is filled by voice without a second pipeline (MOB-05).** The voice note goes to Mesiri as any other;
  the web door's answer carries `ready`, the person's TO SAVE list as data (read from the assistant's own state, never
  changed there). The form takes the newest entry of its kind, keeps its whole body (fields the form doesn't show,
  like a rate, stay), and saves it with the entry's own idempotency key; then it sends the assistant's own Remove
  tap. If the Remove is lost, the assistant's Save of that entry can only answer "already saved". For that,
  `POST /progress/issues` now honours `Idempotency-Key` (it did not; deliveries and use already did). 50 other POST
  routes the assistant uses still ignore it (MOB-12).
- **A voice-filled form left without saving** leaves its entry on Mesiri's list, as on WhatsApp: it shows on Speak
  and is saved or cancelled there.
