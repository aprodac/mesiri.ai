# ADR: call Mesiri on WhatsApp (WA-118)

Status: proposed (step 0 of [the plan](../plans/whatsapp-calling-plan.md), 2 Nov 2026). Product decisions are Ilan's
(1 Nov): Sarvam for speech, inbound calls only, read-only, test companies first. The technical choices below are
recommendations; step 1 tests them. Nothing is built.

Everything here comes from Meta's, Sarvam's and Pipecat's docs read on 2 Nov 2026, plus PyPI and this repo. No call has
been answered yet, so none of it is proven on a real call.

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Signalling | Graph API + webhook, not SIP | We already have the webhook, token and signature check |
| Call handling | Try **Pipecat** first in step 1, inside the call service; fall back to `aiortc` directly | Pipecat is built on `aiortc` and already does Meta's handshake, voice detection, interruption and Sarvam. Plain `aiortc` means writing all of that |
| Webhook | Ours stays the owner: `ingress/webhook.py` verifies the signature, then passes `calls` changes on | One verification path. Pipecat's client has no server of its own, so this fits |
| Speech-to-text | `wss://api.sarvam.ai/speech-to-text-realtime/ws`, `saaras:v3-realtime`, 16 kHz `linear16`, `endpointing=vad` | Server sends speech start and end, so no second detector is needed unless it proves weak |
| Text-to-speech | `wss://api.sarvam.ai/text-to-speech/ws`, **`bulbul:v3`**, voices `shubh` / `pooja` for Malayalam | Malayalam is not on `bulbul:v4-flash`. `bulbul:v4-flash` can serve Hindi, Tamil and English later |
| Answers | v2 agent, read tools only, for now | The API agent (WA-121) has no company on it. Revisit before step 3; see Open questions |
| Files in chat | Existing `send_as`, during or after the call | A call opens the 24-hour window, even if we do not accept it |

## Step 1 spike (2 Nov)

Ilan chose the live number over Meta's test number. So the spike must not take over the webhook, which also carries every
customer message. `ingress/calls_forward.py` copies only `calls` events to the spike, with Meta's body and signature,
when `WHATSAPP_CALLS_FORWARD_URL` is set. It does not delay or fail the webhook. The spike answers allow-listed callers
only.

**First real call, 2 Nov 2026 (Ilan's phone to the live number, spike on the VPS): worked; he heard himself.** So `calls`
webhooks do reach an app shown as "In development", the Pipecat path works with Meta, and audio passed the firewall with no
TURN server for that one call. Connect time and CPU per call are not recorded yet. One phone on one network; TURN may still
be needed for other networks.

Found while building it:

- `aioice` binds random UDP ports and has no setting for a range. The spike wraps the event loop's bind to stay in
  40000-40099, so the firewall opens 100 ports, not the whole ephemeral range.
- Pipecat's models require `from` and the profile name, which Meta can omit. The spike fills both from `contacts[]`.
- Pipecat's `WhatsAppApi.BASE_URL` is overridden to `v25.0`.

## How a call runs

1. Meta posts a `calls` change with `event: "connect"`. Call id: `calls[].id`. Caller: `contacts[].wa_id`. Do not use
   `calls[].from`, which can be missing when the user has a username. SDP offer: `calls[].session.sdp`, type `offer`.
2. Same checks as a message: known user, company has `calls_enabled`. If not, send `reject`.
3. Build the SDP answer. Only SHA-256 fingerprints are accepted.
4. `POST <PHONE_NUMBER_ID>/calls` with `action: "pre_accept"`, `session: {sdp_type: "answer", sdp}`.
5. Same call with `action: "accept"` and the **same** SDP. A different one is an error.
6. Start audio only after the `200 OK`, or the caller misses the first words.
7. To end: `action: "terminate"`. Required even if the media path already closed.
8. Meta posts `event: "terminate"`, with `status`, and `duration` in seconds when answered.

## Timing limits

- About 30 to 60 seconds to accept after the connect webhook, or the caller sees "Not Answered".
- Meta hangs up if we send no media for 20 s at the start or 30 s after connecting. Send RTCP during silence.
- Meta retries failed webhooks for 7 days, so an old `connect` must be dropped, never answered.
- Sarvam TTS closes after about a minute idle, so send `ping`. Sarvam STT closes on inactivity (`1008`).
- Sarvam STT rejects a burst of new connections (`1003`), so one call at a time per user also helps here.

## Limits and cost

- Meta: 1,000 concurrent calls per number. No call length limit found. Our own cap stays 10 minutes.
- Sarvam pay-as-you-go: 20 concurrent STT sockets, 60 TTS sockets. So 20 calls at once, which is enough for the test.
- User-initiated calls are free, but Meta needs a valid payment method on the account (error `131044`).
- Sarvam, before GST: STT ₹0.49 a minute, billed per second; `bulbul:v3` ₹3 per 1,000 characters. The realtime STT price
  is not listed separately, so check it on the first bill.

## Things that differ from what the plan assumed

- **Package:** `sarvamai` 0.1.28 (installed, and pinned by Pipecat's `sarvam` extra) has no realtime STT helper. Latest
  is 0.1.41. Check in step 2 how Pipecat's realtime service connects; if it uses its own socket, the pin does not matter.
- **Beta:** one Sarvam page calls `saaras:v3-realtime` beta. The fallback is the older `/speech-to-text/ws` endpoint.
- **Audio rates:** WhatsApp audio is Opus; the 48 kHz figure comes from a summary of Meta's sample SDP, not its text. STT
  needs 16 kHz. TTS at 16 kHz is documented, but no example shows it with `bulbul:v3`, and Sarvam's own schema conflicts
  on whether the socket outputs anything but MP3. Step 2 proves it.
- **Interrupting:** Sarvam TTS has no cancel message. Stop by dropping the queued audio on our side and, if needed,
  closing that socket.
- **Pipecat details:** it hard-codes Graph API `v23.0`, handles one connect per delivery, and its `webrtc` extra brings
  OpenCV, which we do not need. It adds 25 core packages, so it stays in the call service's own environment if possible.

## Open questions, for step 1 and 2

1. Answered 2 Nov: an app in "In development" mode does get `calls` webhooks.
2. Audio passed without TURN on the first call. Test other networks (mobile data, site Wi-Fi) before real users; Pipecat
   recommends TURN for production.
3. Meta's DTLS role rules are not documented. Pipecat's handshake should cover it.
4. Reply speed. Sarvam publishes no latency figures. Goal stays under 2.5 s from end of speech to first audio.
5. Malayalam quality, and Manglish. Sarvam never mentions Manglish; `codemix` is documented with Hindi examples and
   applies only to the final transcript. Team listening test in step 2.
6. CPU per call. No figure anywhere. Measure in step 1.
7. v2 agent or API agent. Choose before step 3, on whichever gives faster read answers.

## Rollback

`calls_enabled` off for the company. Stop the call service. Turn off *Allow voice calls* in WhatsApp Manager if needed.
No migration planned.

## Sources

- Meta: [Calling](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling),
  [user-initiated calls](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/user-initiated-calls),
  [call settings](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-settings),
  [pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing),
  [reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/reference),
  [troubleshooting](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/troubleshooting)
- Sarvam: [realtime STT](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming),
  [Bulbul](https://docs.sarvam.ai/api/api-guides-tutorials/models/bulbul),
  [TTS WebSocket](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api/web-socket),
  [v3 best practices](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/bulbul-v3-best-practices),
  [pricing and limits](https://docs.sarvam.ai/api-reference-docs/getting-started/pricing)
- Pipecat: [WhatsApp transport](https://docs.pipecat.ai/server/services/transport/whatsapp),
  [SmallWebRTC](https://docs.pipecat.ai/server/services/transport/small-webrtc),
  [Sarvam STT](https://docs.pipecat.ai/server/services/stt/sarvam),
  [Sarvam TTS](https://docs.pipecat.ai/server/services/tts/sarvam)
