# Tell Mesiri from the dashboard (voice or text) — plan

**Status:** proposed 25 Oct 2026, **waiting for Alan's approval** (tracker WEB-36).
**Why approval:** it adds a way for a signed-in dashboard user to make Mesiri act on their
behalf (a new authenticated entry into the assistant). CLAUDE.md stop rule 5:
security-sensitive (auth, permissions).

## Objective

Let anyone with a WhatsApp number on their account send Mesiri an update **from the web
dashboard**, by speaking or typing, and watch what Mesiri understood and the day's report
appear in the same Swiss conversation layout as the signup intro and the welcome screen
(SS-18). Same brain, same rules, a second door.

## Scope

**In**

- A "Tell Mesiri" panel: on **Today** (all roles with a WhatsApp number) and on the
  **welcome screen** ("Send your first update: on WhatsApp, or speak here").
- **Voice:** hold to record in the browser (live waveform), release to send. **Text:** type
  and send. Both go through the exact path a WhatsApp message takes.
- Mesiri's replies shown on the right: what it understood (facts animating in), its
  Save / Cancel / Yes / No buttons as real buttons, follow-up questions answered in place.
- Messages from the web marked as such (source `dashboard`) in the WhatsApp inbox and logs.

**Out (later)**

- Photos and documents from the web (WhatsApp keeps them for now).
- Replies also being sent to the person's WhatsApp (the web shows them; WhatsApp doesn't
  get a copy).
- Offline recording / retry queues.

## Business value

- **Day 0:** a new owner sees their first report without picking up their phone. Today
  the welcome screen waits for them to switch to WhatsApp, which is where some will stop.
- **Site office:** engineers at a laptop can report without the phone, in their language.
- **Sales demos:** the product can be shown end to end on one screen.

## How it works (reuse first)

| Piece | Exists today | Reused how |
|---|---|---|
| Running a message through the real handler and catching the replies | `POST /admin/system-graph/simulate` (platform admin only): builds a `NormalizedMessage`, runs `container.simulate_handler` (the production `message_journey`), captures text, lists and buttons instead of sending | The new endpoint does the same for **the signed-in user, as themselves** (their own WhatsApp id from the token, never one passed in) |
| Voice → words, language, English | `understanding/pipeline.py` `transcribe_voice` → `SpeechUnderstandingProvider` (Sarvam) reading the audio from object storage by `media.object_key` | The browser's audio is stored the same way (`media/{message_id}/web-...`) and the message points at it; the pipeline can't tell it from a WhatsApp voice note |
| Trial AI spending cap | `guardrails.py` `trial_daily_ai_cost_inr` | Applies unchanged; **verify** the web path is counted (test) |
| The conversation UI | `components/onboarding/conversation.tsx`, `scenes.tsx`, `lib/timeline.ts`, `Waveform`, `Fact`, `Words` | The panel is built from them; the waveform reads the live microphone level |
| The live report | `DprDocument` + `GET /dpr/site-days/{id}/document` (WEB-27) | Shown under the conversation, refreshed after each saved update |

Nothing here writes activities, issues or labour itself: every save goes through the
workflows WhatsApp uses, with their confirmations.

## Backend work

1. **`POST /assistant/messages`** (in the assistant app, beside `simulate`, sharing its code
   by moving the build-message / capture-replies part into one function both call):
   - Auth: the dashboard token. The sender is **the token's user**; their `whatsapp_number`
     is looked up server-side. No number → 409 "Add your WhatsApp number to your profile
     to talk to Mesiri". Suspended/expired company → the same refusal WhatsApp gives.
   - Body: `{ text }` or `{ interactive_reply_id }` (a button tap), or multipart `audio`.
   - Audio: ≤ 60 s, ≤ 5 MB; stored to object storage, message built with
     `modality=VOICE` and `media.object_key`. Formats: browsers record WebM/Opus
     (Chrome, Android) or MP4/AAC (iPhone Safari). **First task: test Sarvam with both;**
     convert to WAV/OGG on the server if one is refused.
   - Response: the captured replies (text, buttons/list options) plus `understood` (the
     ids of anything saved, so the panel can show the facts) and `message_id`.
   - Synchronous, with a 60 s limit. Voice + model usually answers in 5–20 s.
2. **Source marking:** the message is logged with `source="dashboard"` (or the existing
   channel field) so the WhatsApp inbox and logs show it came from the web.
3. **Rate limit:** per user, e.g. 20 messages / 10 min, on top of the trial AI cap.

## Frontend work

1. `components/tell-mesiri/` — the panel:
   - Mic button (hold to record; tap-to-toggle for accessibility), live waveform from
     `AnalyserNode`, a 60 s limit with a countdown; a text box as the alternative.
   - Left column (From you): the transcript arriving word by word (from the reply), with
     the English translation under it, as in the intro.
   - Right column (Mesiri): "Received · reading it" while waiting, then the facts
     (`Fact`, count-ups) and Mesiri's replies; its buttons send `interactive_reply_id`.
   - Below: the day's live report.
   - Microphone refused or unavailable → the text box only, with one line saying why.
2. **Today:** the panel above the sites list, collapsed to one "Tell Mesiri" row until used.
3. **Welcome screen:** step 01 "Send" offers both: WhatsApp (number, QR) and "Speak here".
4. Reduced motion: no animation, everything shown at once (as now).

## Database work

None expected. If the message log has no field for the source, one **additive** nullable
column (`source`, default `whatsapp`): allowed without approval under CLAUDE.md, but listed
here so it isn't a surprise.

## API changes

- **New:** `POST /assistant/messages` (text, button tap, or audio).
- **Unchanged:** every workflow, `simulate` (refactored to share code, same behaviour).

## Risks

| Risk | Mitigation |
|---|---|
| A second door into the assistant = a new way to act as someone | Sender is always the token's own user; no user/number in the body; same role rules and module switches as WhatsApp (they live in the workflows); tests for "can't act as someone else" and "no number → refused" |
| Audio formats from iPhone vs Android | Tested first; server-side conversion if needed |
| Slow replies (voice + model) | 60 s limit; the panel animates "reading it"; on timeout, "Still working, it'll show on Today" |
| AI cost from a new channel | Same trial cap; per-user rate limit |
| Two people in one conversation (web and WhatsApp at once) | Same per-user conversation state as WhatsApp; a pending card answered on either side is answered |
| Microphone permission UX on phones | Clear one-line prompt; text box always there |

## Testing strategy

- **Unit (assistant):** sender is the token user; no number → 409; button taps resume the
  pending workflow; audio stored and sent as `VOICE`; rate limit; trial cap counts web
  messages.
- **Replay tests** (the existing `tests/replay` style): a web text update and a web voice
  update produce the same saved records as the WhatsApp equivalents.
- **Dashboard:** typecheck, lint, build; browser checks with faked API (record → replies →
  buttons), at phone and desktop width, reduced motion.
- **Manual on the test server:** Chrome (Android), Safari (iPhone), Chrome (desktop) voice;
  Malayalam, Hindi, English.
- Full CLAUDE.md verification before each push.

## Rollback strategy

- The panel is behind one switch: hide it (one line in Today and the welcome screen) and
  the endpoint goes unused. Removing the endpoint is a revert of its commit.
- No data to undo: anything saved went through the normal workflows and can be removed the
  normal way. No destructive migration.

## Labour isolation

Labour, Attendance, Payroll and Workforce code is not changed. Workers mentioned in a web
update go through the same labour workflow a WhatsApp message uses, exactly as today.

## Success criteria

- A new owner can send their first update from the welcome screen by voice and see the
  report, without touching their phone, in under 2 minutes.
- A web voice update and the same WhatsApp voice note save the same records.
- No way to send as anyone but yourself (tests).
- Works by voice in Chrome (Android, desktop) and Safari (iPhone).

## Size and order

About **4–6 focused days**, in three pushes, each usable on its own:
1. Endpoint + text (≈ 1.5 days) — usable on Today and the welcome screen as typing.
2. Voice (≈ 1.5–2 days) — record, store, transcribe; the format test first.
3. The full Swiss conversation panel and buttons (≈ 1.5 days).

## Decisions for Alan

1. **Approve the new authenticated endpoint** (`POST /assistant/messages`, acting as the
   signed-in user only).
2. **Who gets it:** everyone with a WhatsApp number on their account (recommended), or
   admins and project managers only.
3. **Replies on WhatsApp too?** Recommended **no** for V1 (the web shows them); yes would
   need the 24 h window or templates.
