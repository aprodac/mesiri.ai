"""WA-118 steps 1 and 2: answer a WhatsApp call, then echo it or repeat it through Sarvam.

CALL_SPIKE_MODE=echo plays the caller's voice back. CALL_SPIKE_MODE=sarvam listens with
Sarvam and says back what it heard, timing each stage. No assistant and no company data.

A spike, not product code: it answers only the numbers in CALL_SPIKE_ALLOWED, one
call at a time, for two minutes at most. Everyone else is left alone, so their
call rings out as it does today. The live webhook forwards `calls` events here
(ingress/calls_forward.py); nothing else about the live number changes.

What it is here to show (docs/architecture/ADR-whatsapp-calling.md): do `calls`
webhooks arrive, does audio pass the firewall without TURN, CPU per call.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiohttp
import psutil
import uvicorn
from fastapi import FastAPI, Request, Response
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.sarvam.stt import SarvamRealtimeSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.whatsapp.api import WhatsAppApi, WhatsAppWebhookRequest
from pipecat.transports.whatsapp.client import WhatsAppClient

logger = logging.getLogger("call_echo")

MAX_CALL_SECONDS = 120
# Meta retries a failed webhook for 7 days, and the caller stops ringing after a
# minute: an older `connect` is a call nobody is waiting on.
MAX_CONNECT_AGE_SECONDS = 60
UDP_PORTS = range(40000, 40100)
SAMPLE_RATE = 16000
GREETING = "നമസ്കാരം, പറയൂ."
NOT_NOW = "ഇപ്പോൾ നോക്കാൻ പറ്റിയില്ല. ഒന്നുകൂടി പറയൂ."
ANSWER_TIMEOUT_SECONDS = 25

# Pipecat hard-codes v23.0; use the version the app's webhooks are on.
WhatsAppApi.BASE_URL = "https://graph.facebook.com/v25.0/"


def allowed_callers() -> set[str]:
    return {n.strip().lstrip("+") for n in os.environ.get("CALL_SPIKE_ALLOWED", "").split(",") if n.strip()}


def signature_ok(body: bytes, header: str | None, secret: str) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def answerable_call(value: dict[str, Any], *, phone_number_id: str, allowed: set[str], now: float) -> dict[str, Any] | None:
    """The `connect` to answer in this change, or None to leave it alone."""
    if (value.get("metadata") or {}).get("phone_number_id") != phone_number_id:
        return None
    contacts = value.get("contacts") or []
    wa_id = contacts[0].get("wa_id") if contacts else None
    if wa_id not in allowed:
        return None
    for call in value.get("calls") or []:
        if call.get("event") != "connect":
            continue
        if now - float(call.get("timestamp") or 0) > MAX_CONNECT_AGE_SECONDS:
            logger.info("skipped a stale connect")
            continue
        return call
    return None


def as_pipecat_request(payload: dict[str, Any], change: dict[str, Any], call: dict[str, Any]) -> WhatsAppWebhookRequest:
    """Meta can leave out `from` and the profile name; Pipecat's model requires both."""
    value = change["value"]
    contact = value["contacts"][0]
    contact.setdefault("profile", {}).setdefault("name", "caller")
    call.setdefault("from", contact["wa_id"])
    call.setdefault("direction", "USER_INITIATED")
    entry = {"id": payload["entry"][0]["id"], "changes": [{"value": {**value, "calls": [call]}, "field": "calls"}]}
    return WhatsAppWebhookRequest.model_validate({"object": payload["object"], "entry": [entry]})


def pin_udp_ports(loop: asyncio.AbstractEventLoop) -> None:
    """aioice binds a random port, which would mean opening the whole ephemeral
    range. Keep call audio inside the range the firewall opens."""
    original = loop.create_datagram_endpoint

    async def bounded(factory: Any, local_addr: Any = None, **kwargs: Any) -> Any:
        if local_addr is None or local_addr[1] != 0:
            return await original(factory, local_addr=local_addr, **kwargs)
        for port in UDP_PORTS:
            try:
                return await original(factory, local_addr=(local_addr[0], port), **kwargs)
            except OSError:
                continue
        raise OSError("no free UDP port in the call range")

    loop.create_datagram_endpoint = bounded  # type: ignore[method-assign]


class Echo(FrameProcessor):
    """Turn what the caller said into what the caller hears."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            await self.push_frame(
                OutputAudioRawFrame(audio=frame.audio, sample_rate=frame.sample_rate, num_channels=frame.num_channels),
                direction,
            )
        else:
            await self.push_frame(frame, direction)


class Clock:
    """Times one turn: end of speech, then the text, then the first audio back."""

    def __init__(self) -> None:
        self.stopped_speaking: float | None = None
        self.waiting_for_audio = False


class AskAssistant(FrameProcessor):
    """Say what the assistant answers to what Sarvam heard."""

    def __init__(self, clock: Clock, ask: Any) -> None:
        super().__init__()
        self._clock = clock
        self._ask = ask

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            self._clock.stopped_speaking = time.monotonic()
        if isinstance(frame, TranscriptionFrame):
            asked = time.monotonic()
            answer = await self._ask(frame.text)
            logger.info("assistant answered in %.2fs: %d characters", time.monotonic() - asked, len(answer))
            self._clock.waiting_for_audio = True
            await self.push_frame(TTSSpeakFrame(answer), direction)
        else:
            await self.push_frame(frame, direction)


def assistant_ask(session: aiohttp.ClientSession, url: str, secret: str, wa_id: str) -> Any:
    """Ask the app, signed the way `ingress/call_answer.py` checks it."""

    async def ask(text: str) -> str:
        body = json.dumps({"wa_id": wa_id, "text": text, "at": time.time()}, ensure_ascii=False).encode()
        digest = hmac.new(secret.encode(), b"call-answer:" + body, hashlib.sha256).hexdigest()
        try:
            async with session.post(url, data=body, headers={"X-Hub-Signature-256": f"sha256={digest}"},
                                    timeout=aiohttp.ClientTimeout(total=ANSWER_TIMEOUT_SECONDS)) as response:
                response.raise_for_status()
                return (await response.json())["text"]
        except Exception:
            logger.exception("the assistant did not answer")
            return NOT_NOW

    return ask


class RepeatBack(FrameProcessor):
    """Stand-in for the assistant: say back what Sarvam heard."""

    def __init__(self, clock: Clock) -> None:
        super().__init__()
        self._clock = clock

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            self._clock.stopped_speaking = time.monotonic()
        if isinstance(frame, TranscriptionFrame):
            if self._clock.stopped_speaking is not None:
                logger.info("heard after %.2fs: %d characters", time.monotonic() - self._clock.stopped_speaking, len(frame.text))
            self._clock.waiting_for_audio = True
            await self.push_frame(TTSSpeakFrame(frame.text), direction)
        else:
            await self.push_frame(frame, direction)


class FirstAudio(FrameProcessor):
    def __init__(self, clock: Clock) -> None:
        super().__init__()
        self._clock = clock

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame) and self._clock.waiting_for_audio:
            self._clock.waiting_for_audio = False
            if self._clock.stopped_speaking is not None:
                logger.info("first audio back after %.2fs", time.monotonic() - self._clock.stopped_speaking)
        await self.push_frame(frame, direction)


def sarvam_processors(api_key: str, language: Language, voice: str, ask: Any = None) -> list[FrameProcessor]:
    clock = Clock()
    return [
        VADProcessor(vad_analyzer=SileroVADAnalyzer()),
        SarvamRealtimeSTTService(api_key=api_key, settings=SarvamRealtimeSTTService.Settings(language=language)),
        AskAssistant(clock, ask) if ask else RepeatBack(clock),
        SarvamTTSService(
            api_key=api_key,
            sample_rate=SAMPLE_RATE,
            settings=SarvamTTSService.Settings(model="bulbul:v3", voice=voice, language=language),
        ),
        FirstAudio(clock),
    ]


async def run_call(connection: Any, call_id: str, started: float, ended: asyncio.Event, processors: list[FrameProcessor], greeting: str = "") -> None:
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True, audio_in_sample_rate=SAMPLE_RATE, audio_out_sample_rate=SAMPLE_RATE),
    )
    task = PipelineTask(
        Pipeline([transport.input(), *processors, transport.output()]),
        params=PipelineParams(audio_in_sample_rate=SAMPLE_RATE, audio_out_sample_rate=SAMPLE_RATE),
    )

    @transport.event_handler("on_client_connected")
    async def on_connected(_transport: Any, _client: Any) -> None:
        logger.info("audio connected after %.2fs", time.monotonic() - started)
        if greeting:
            await task.queue_frames([TTSSpeakFrame(greeting)])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(_transport: Any, _client: Any) -> None:
        await task.cancel()

    runner = asyncio.create_task(PipelineRunner(handle_sigint=False).run(task))
    samples = []
    process = psutil.Process()
    process.cpu_percent()
    try:
        deadline = time.monotonic() + MAX_CALL_SECONDS
        while not runner.done() and not ended.is_set() and time.monotonic() < deadline:
            await asyncio.wait([runner], timeout=1)
            samples.append(process.cpu_percent())
    finally:
        if not runner.done():
            await task.cancel()
            await runner
        if samples:
            logger.info("call %s cpu%% one core: avg %.1f max %.1f", call_id, sum(samples) / len(samples), max(samples))


def build_app(*, token: str, secret: str, phone_number_id: str, allowed: set[str], sarvam_key: str = "", language: Language = Language.ML_IN, voice: str = "shubh", answer_url: str = "") -> FastAPI:
    state: dict[str, Any] = {"busy": False}

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        pin_udp_ports(asyncio.get_running_loop())
        state["session"] = aiohttp.ClientSession()
        state["client"] = WhatsAppClient(token, phone_number_id, state["session"], whatsapp_secret=secret)
        yield
        await state["client"].terminate_all_calls()
        await state["session"].close()

    app = FastAPI(lifespan=lifespan)

    async def answer(request: WhatsAppWebhookRequest, body: bytes, signature: str, call_id: str) -> None:
        client: WhatsAppClient = state["client"]
        started = time.monotonic()

        async def on_connection(connection: Any, _call: Any) -> None:
            logger.info("accepted after %.2fs", time.monotonic() - started)
            ask = assistant_ask(state["session"], answer_url, secret, state["caller"]) if answer_url else None
            processors = sarvam_processors(sarvam_key, language, voice, ask) if sarvam_key else [Echo()]
            await run_call(connection, call_id, started, state["ended"], processors, GREETING if sarvam_key else "")

        try:
            await client.handle_webhook_request(request, on_connection, raw_body=body, sha256_signature=signature)
        except Exception:
            logger.exception("could not answer the call")
        finally:
            # Meta asks for this even when the media path already closed.
            try:
                await client._whatsapp_api.terminate_call_to_whatsapp(call_id)
            except Exception:
                logger.info("terminate after the call failed (the caller may have hung up first)")
            state["busy"] = False

    @app.post("/calls")
    async def calls(request: Request) -> Response:
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")
        if not signature_ok(body, signature, secret):
            return Response(status_code=403)
        payload = json.loads(body)
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                if change.get("field") != "calls":
                    continue
                value = change.get("value") or {}
                logger.info("calls webhook arrived: %s", [c.get("event") for c in value.get("calls") or []])
                for ended in value.get("calls") or []:
                    if ended.get("event") == "terminate":
                        logger.info("call ended status=%s duration=%s errors=%s", ended.get("status"), ended.get("duration"), ended.get("errors"))
                        if state.get("ended") and ended.get("id") == state.get("call_id"):
                            state["ended"].set()
                call = answerable_call(value, phone_number_id=phone_number_id, allowed=allowed, now=time.time())
                if call is None or state["busy"]:
                    continue
                state.update(busy=True, ended=asyncio.Event(), call_id=call["id"], caller=value["contacts"][0]["wa_id"])
                pipecat_request = as_pipecat_request(payload, change, call)
                asyncio.create_task(answer(pipecat_request, body, signature, call["id"]))
        return Response(status_code=200)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    application = build_app(
        token=os.environ["WHATSAPP_ACCESS_TOKEN"],
        secret=os.environ["WHATSAPP_APP_SECRET"],
        phone_number_id=os.environ["WHATSAPP_PHONE_NUMBER_ID"],
        allowed=allowed_callers(),
        sarvam_key=os.environ["MESIRI_SARVAM__API_KEY"] if os.environ.get("CALL_SPIKE_MODE") in ("sarvam", "assistant") else "",
        answer_url=f"http://127.0.0.1:{os.environ.get('MESIRI_APP_PORT', '8000')}/webhook/call-answer" if os.environ.get("CALL_SPIKE_MODE") == "assistant" else "",
        language=Language(os.environ.get("CALL_SPIKE_LANGUAGE", "ml-IN")),
        voice=os.environ.get("CALL_SPIKE_VOICE", "shubh"),
    )
    uvicorn.run(application, host="127.0.0.1", port=int(os.environ.get("CALL_SPIKE_PORT", "8795")))
