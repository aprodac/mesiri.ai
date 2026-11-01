# Call Mesiri on WhatsApp: plan (WA-118)

> Asked by Ilan, 1 Nov 2026: *"Sarvam as main. Mesiri gets calls. Users mainly ask questions, or ask it to send a
> PDF in chat: inventory, stock, workforce, anything like that."*
> Tracker: [WA-118](V1_TRACKER.md) (request log [23]). Status: **planned, nothing built.** Pick it up from here.
> Governing process: the root [CLAUDE.md](../../CLAUDE.md) (phases, verification, `main` only, phase reports).

## 1. What the user gets

A site supervisor, engineer or owner taps **Call** on Mesiri's WhatsApp chat and talks:

- *"Innu ethra workers undaayirunnu?"* → Mesiri says the answer in a sentence or two.
- *"Cement stock ethra baakki?"* → spoken answer for their site (or all sites when they have several).
- *"Workforce report PDF aayittu ayakku"* → Mesiri says *"Sending it in chat now"* and the PDF arrives in the WhatsApp
  chat while the call is still on.
- *"Innathe DPR ayakku"* → the DPR goes to the chat, same as asking in text.

Nothing is saved on a call (read-only). When someone tries to report something ("10 bag cement vannu"), Mesiri says
to send it as a message or voice note and it will be put on the card. Writes on calls can come later, behind the same
Save tap as chat.

## 2. Decisions taken

| Decision | Choice |
| --- | --- |
| Speech | **Sarvam**: speech-to-text and text-to-speech (Malayalam, Manglish, Hindi, English) |
| Direction | **Inbound only**: users call Mesiri (Meta does not charge the business for user-initiated calls, to be confirmed in the docs). Mesiri never calls out |
| What a call does | **Read-only**: questions and "send X as PDF / image in chat" |
| Who first | The two test companies (Mesiri Test Builders, Paraclette), then a per-company switch |

## 3. How it works

```
WhatsApp user taps Call
   │
   ▼
Meta Cloud API ──"calls" webhook (SDP offer)──► Mesiri webhook (apps/whatsapp-assistant/src/ingress/webhook.py)
   │                                                │ known user? company allowed? (same checks as a message)
   │◄── accept (SDP answer) ────────────────────── call service
   │
   ╞════ WebRTC audio (Opus, DTLS-SRTP) ═══► call service (new, on the VPS)
   │                                          │  decode → 16 kHz PCM
   │                                          ▼
   │                                    Sarvam streaming speech-to-text (end of speech = one "turn")
   │                                          ▼
   │                                    v2 agent, READ tools only + send_as (pdf/image → the chat)
   │                                          ▼
   │                                    one or two short spoken sentences
   │                                          ▼
   ╞════ audio back ◄═════════════════════ Sarvam text-to-speech (streamed)
   │
   └── PDF / image / text → the user's WhatsApp chat (existing send path, inside the 24 h window: they just called)
```

### Pieces and where they live

| Piece | Where | Reuse or new |
| --- | --- | --- |
| Call webhook handling | `ingress/webhook.py` gets the `calls` field; hands it to the call service | **extend** (same verification, dedupe, user lookup) |
| Call service: SDP answer, WebRTC media, audio in/out | `apps/whatsapp-assistant/src/calls/` (new package), run as its own systemd unit next to `mesiri` | **new**. Python `aiortc` is the first candidate (Opus, DTLS-SRTP, ICE in pure Python); measure its CPU on the VPS before committing |
| Speech-to-text | `platform/ai/src/mesiri_ai/adapters/sarvam/` already wraps `sarvamai` (verified 0.1.28, REST `speech_to_text`) | **extend** with the streaming call |
| Text-to-speech | same Sarvam adapter | **new method** (`speak`), streamed |
| Understanding and answers | the v2 agent (`agent_v2/agents/main.py`) with `GENERAL_READ_TOOLS` + materials `stock_for`; a `voice` flag removes every write tool and asks for short speakable sentences (no lists, no emoji, no "below") | **reuse**, as a v2 skill: `agent_v2/skills/voice/SKILL.md` + `tools.py` + `evals.yaml` (CLAUDE.md: a feature is a skill, never a new workflow) |
| "Send as PDF / image" | `send_as` on every lookup (WA-93, `runtime/agent/tools.py`) already sends text / PDF / image to the chat | **reuse**: the call turn sends to the caller's chat, the spoken line says it is on its way |
| Cost | `platform/ai/src/mesiri_ai/usage.py` + `provider_executions`; Costs page in the control panel | **extend**: Sarvam STT seconds + TTS characters per call, call minutes per company |
| Switch | company setting like `assistant_mode` (`PUT /admin/organizations/{id}/settings`): `calls_enabled` | **extend** the existing settings, no migration if it is a settings key |
| Logs | `inbound_messages` row per call turn (kind `call`), transcript + reply text, so the production watch (TM-16/18) and replay see calls like messages | **reuse** |

### Turn-taking (what makes it feel like a call)

- **End of speech**: Sarvam's streaming end-of-speech signal if it has one; otherwise a local voice-activity detector
  (about 700 ms of silence). To check in the docs.
- **Barge-in**: if the caller speaks while Mesiri is talking, stop the playback and listen.
- **Filler**: if the answer takes more than about 1.5 s (a PDF lookup), say a short "Nokkatte…" / "One second" first.
- **Language**: answer in the caller's language and script, as chat does (`runtime/agent/wording.language_of`).
- **Limits**: 10-minute call cap; hang up politely after 20 s of silence; one call per user at a time.

## 4. Must verify before writing code (docs were unreachable from the cloud session)

The cloud session could not open `developers.facebook.com` or `docs.sarvam.ai`. **Nothing below is confirmed.** Read
the docs on your computer first and correct this section.

**Meta WhatsApp Cloud API: Calling** (developers.facebook.com/docs/whatsapp/cloud-api/calling)
1. Is calling available for **India (+91)** business numbers and users? Any messaging-tier or verification prerequisite?
2. How to switch calling on for the number (call settings endpoint and fields); call icon visibility.
3. The `calls` webhook payload: call id, caller wa_id, where the SDP offer is.
4. Endpoints and order for `pre_accept` / `accept` / `reject` / `terminate`, body fields (`session.sdp_type`, `sdp`),
   and timeouts.
5. Media: Opus? sample rate? ICE candidates in the SDP? who is the offerer? DTLS role?
6. Pricing of user-initiated calls; limits (concurrent calls, duration).
7. Any official sample (Node or Python) to copy the SDP handshake from.

**Sarvam** (docs.sarvam.ai)
1. Streaming speech-to-text: WebSocket URL, auth header, audio format (8 / 16 kHz PCM?), partial / final messages,
   end-of-speech signal, model (`saarika` / `saaras`), `ml-IN` support, translate-to-English option.
2. Text-to-speech: REST and streaming endpoints, model (`bulbul`), `ml-IN` and `hi-IN` voices, sample rate, output
   format (base64 WAV vs PCM chunks), max text length, latency.
3. Prices (per minute STT, per character TTS) and rate limits.
4. Does `sarvamai` (we pin `>=0.1`, verified 0.1.28) cover streaming, or is raw WebSocket needed?

## 5. Owner steps (ops, outside the code)

1. **Meta**: switch calling on for the Mesiri business number in WhatsApp Manager (after checking India eligibility).
2. **VPS**: open the UDP port range the call service uses for WebRTC media (and TURN if the docs need it) in the firewall
   and the cloud provider's security group. Infrastructure / security: approve explicitly.
3. **Sarvam**: confirm the API key's plan covers streaming and the expected minutes; set a spend alert.
4. **Cloud sessions** (optional): allow `developers.facebook.com`, `docs.sarvam.ai`, `api.sarvam.ai` under the
   environment's Network access, so cloud sessions can work on this too.

## 6. Build order (each step: test, commit, push, phase report, as CLAUDE.md says)

| Step | What | Done when |
| --- | --- | --- |
| 0 | Read the docs (section 4), fix this plan, record the facts in an ADR (`docs/architecture/ADR-whatsapp-calling.md`) | every open question answered or marked "not available" |
| 1 | **Spike, off production**: a local script answers a real test call on a test number (SDP handshake + echo the audio back) | you hear yourself on WhatsApp |
| 2 | Sarvam in the loop: speech → text → fixed reply → speech, still on the spike | a Malayalam question gets a spoken Malayalam line, latency measured per stage |
| 3 | The voice skill: v2 agent, read tools only, short speakable answers, `send_as` to the chat; `evals.yaml` with real questions (stock, workers, DPR, workforce PDF) and guards ("10 bag cement vannu" is not saved on a call) | evals pass on fakes; live run on the real model |
| 4 | Webhook + call service in the app, behind `calls_enabled` (off), systemd unit, health check, logs to `inbound_messages` | deploy with the switch off changes nothing |
| 5 | Switch on for **Mesiri Test Builders**; team tests by calling | 10 test calls, each answered; PDF arrives in chat |
| 6 | Costs page: per call minutes, Sarvam spend; production watch reads call turns | numbers match Sarvam's dashboard |
| 7 | Paraclette, then real companies one by one | owner says go |

## 7. Testing

- **Unit (free, CI)**: SDP handling with recorded payloads; the turn loop with fake STT / TTS / agent; the voice skill's
  `evals.yaml` through `V2Runner` with scripted calls (no Gemini, no Sarvam); "no write tool on a call".
- **Live (manual, costs money)**: the voice skill's evals on the real model (`pytest -m live`, like the module skills);
  a scripted test call list run by the team.
- **Measure**: time from end of speech to first audio back (goal under 2.5 s), per stage (STT, agent, TTS).
- The WhatsApp assistant suite (CLAUDE.md, PYTHONPATH command) before every push.

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| India not eligible for the Calling API, or only for some tiers | step 0 decides; if not available, stop here and say so |
| WebRTC behind the VPS firewall / NAT does not connect | step 1 spike on the real VPS; TURN if needed |
| Latency too long for a natural call | streaming STT and TTS, filler line, short answers; measure per stage |
| Malayalam speech quality | step 2 listening test with the team before building more |
| Cost per minute | read-only short calls, 10-minute cap, per-company switch, Costs page, spend alert |
| One CPU-heavy call service on the same VPS as the app | its own systemd unit with CPU / memory limits; one call per user; measure in step 1 |

## 9. Rollback

`calls_enabled` off for the company (instant: calls are then rejected politely or ring out, chat unaffected); stop the
call service unit; revert the commits. No data migration is planned (settings key + `inbound_messages` kind).

## 10. Starting prompt for Claude Code on your computer

> Read `docs/plans/whatsapp-calling-plan.md` and `CLAUDE.md`. Do step 0: read the Meta WhatsApp Cloud API Calling docs
> and the Sarvam speech-to-text streaming and text-to-speech docs, answer every question in section 4, update the plan,
> and write `docs/architecture/ADR-whatsapp-calling.md`. Then stop and show me what you found before step 1.
