"""Stand-in for a real call: an aiortc peer plays Meta and the caller.

Runs the real Pipecat handshake and audio path over loopback, with only the
Graph API faked. Run from this folder with the spike's own environment.
"""

from __future__ import annotations

import asyncio
import fractions
import hashlib
import hmac
import json
import time

import echo
import httpx
import numpy as np
import pytest
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame
from fastapi.testclient import TestClient

SECRET = "test-secret"
NUMBER_ID = "1151164728072345"
CALLER = "919000000001"


class Tone(MediaStreamTrack):
    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self.count = 0
        self.started = time.monotonic()

    async def recv(self) -> AudioFrame:
        await asyncio.sleep(max(0, self.started + self.count * 0.02 - time.monotonic()))
        t = (np.arange(960) + self.count * 960) / 48000
        samples = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16).reshape(1, -1)
        frame = AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = 48000
        frame.pts = self.count * 960
        frame.time_base = fractions.Fraction(1, 48000)
        self.count += 1
        return frame


def connect_payload(sdp: str, *, caller: str = CALLER, age: float = 0, number_id: str = NUMBER_ID) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1",
                "changes": [
                    {
                        "field": "calls",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": number_id, "display_phone_number": "918904034938"},
                            "contacts": [{"wa_id": caller}],
                            "calls": [
                                {
                                    "id": "wacid.1",
                                    "to": "918904034938",
                                    "event": "connect",
                                    "timestamp": str(int(time.time() - age)),
                                    "session": {"sdp_type": "offer", "sdp": sdp},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def signed(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Hub-Signature-256": f"sha256={digest}"}


def test_only_a_fresh_allowed_call_to_our_number_is_answered() -> None:
    allowed = {CALLER}
    now = time.time()
    value = lambda **kw: connect_payload("sdp", **kw)["entry"][0]["changes"][0]["value"]  # noqa: E731
    answer = lambda v: echo.answerable_call(v, phone_number_id=NUMBER_ID, allowed=allowed, now=now)  # noqa: E731

    assert answer(value()) is not None
    assert answer(value(caller="919999999999")) is None
    assert answer(value(number_id="other")) is None
    assert answer(value(age=300)) is None


def test_bad_signature_is_refused() -> None:
    app = echo.build_app(token="t", secret=SECRET, phone_number_id=NUMBER_ID, allowed={CALLER})
    with TestClient(app) as client:
        body, _ = signed(connect_payload("sdp"))
        response = client.post("/calls", content=body, headers={"X-Hub-Signature-256": "sha256=nope"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_udp_ports_stay_in_range() -> None:
    loop = asyncio.get_running_loop()
    echo.pin_udp_ports(loop)
    transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0))
    assert transport.get_extra_info("sockname")[1] in echo.UDP_PORTS
    transport.close()


def test_sarvam_pipeline_builds_for_malayalam() -> None:
    processors = echo.sarvam_processors("key", echo.Language.ML_IN, "shubh")
    names = [type(p).__name__ for p in processors]
    assert names == ["VADProcessor", "SarvamRealtimeSTTService", "RepeatBack", "SarvamTTSService", "FirstAudio"]


@pytest.mark.asyncio
async def test_repeat_back_says_what_it_heard() -> None:
    clock = echo.Clock()
    repeat = echo.RepeatBack(clock)
    pushed: list = []

    async def capture(frame, direction=echo.FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    repeat.push_frame = capture
    frame = echo.TranscriptionFrame(text="സിമന്റ് എത്ര", user_id="u", timestamp="t")
    await repeat.process_frame(frame, echo.FrameDirection.DOWNSTREAM)
    assert isinstance(pushed[-1], echo.TTSSpeakFrame)
    assert pushed[-1].text == "സിമന്റ് എത്ര"
    assert clock.waiting_for_audio


@pytest.mark.asyncio
async def test_the_assistant_answer_is_what_gets_spoken() -> None:
    heard: list[str] = []

    async def ask(text: str) -> str:
        heard.append(text)
        return "ഇന്ന് 12 മേസൺ"

    step = echo.AskAssistant(echo.Clock(), ask)
    pushed: list = []

    async def capture(frame, direction=echo.FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    step.push_frame = capture
    await step.process_frame(echo.TranscriptionFrame(text="ഇന്ന് എത്ര പേർ", user_id="u", timestamp="t"), echo.FrameDirection.DOWNSTREAM)
    assert heard == ["ഇന്ന് എത്ര പേർ"]
    assert pushed[-1].text == "ഇന്ന് 12 മേസൺ"


def test_the_assistant_step_replaces_repeat_back() -> None:
    async def ask(_text: str) -> str:
        return ""

    assert "AskAssistant" in [type(p).__name__ for p in echo.sarvam_processors("key", echo.Language.ML_IN, "shubh", ask)]


async def terminated(actions: list[str]) -> None:
    while "terminate" not in actions:
        await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_a_call_is_answered_and_the_caller_hears_themselves(monkeypatch) -> None:
    actions: list[str] = []
    answers: list[str] = []
    meta = RTCPeerConnection()

    async def fake_graph(self, call_id, action, sdp, from_):
        actions.append(action)
        answers.append(sdp)
        if action == "accept":
            await meta.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="answer"))
        return {"success": True}

    async def fake_terminate(self, call_id):
        actions.append("terminate")
        return {"success": True}

    monkeypatch.setattr(echo.WhatsAppApi, "answer_call_to_whatsapp", fake_graph)
    monkeypatch.setattr(echo.WhatsAppApi, "terminate_call_to_whatsapp", fake_terminate)
    monkeypatch.setattr(echo, "MAX_CALL_SECONDS", 60)

    meta.addTrack(Tone())
    heard = asyncio.get_running_loop().create_future()

    @meta.on("track")
    def on_track(track):
        async def listen():
            loud = 0
            while True:
                frame = await track.recv()
                if np.abs(frame.to_ndarray()).max() > 1000:
                    loud += 1
                    if loud >= 10 and not heard.done():
                        heard.set_result(True)

        asyncio.ensure_future(listen())

    await meta.setLocalDescription(await meta.createOffer())
    body, headers = signed(connect_payload(meta.localDescription.sdp))

    app = echo.build_app(token="t", secret=SECRET, phone_number_id=NUMBER_ID, allowed={CALLER})
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                assert (await client.post("/calls", content=body, headers=headers)).status_code == 200
                assert await asyncio.wait_for(heard, 15)

                # The caller hangs up: Meta says so, and the spike must not sit until its cap.
                hang_up = connect_payload("")
                call = hang_up["entry"][0]["changes"][0]["value"]["calls"][0]
                call.update(event="terminate", status="COMPLETED", duration=9)
                call.pop("session")
                body, headers = signed(hang_up)
                assert (await client.post("/calls", content=body, headers=headers)).status_code == 200
                await asyncio.wait_for(terminated(actions), 8)
    finally:
        await meta.close()

    assert actions[:2] == ["pre_accept", "accept"]
    assert answers[0] == answers[1]
    assert "terminate" in actions
    assert "a=fingerprint:sha-256" in answers[0].lower()
