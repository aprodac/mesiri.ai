"""WEB-36: Tell Mesiri from the dashboard -- the same handler as WhatsApp,
always as the signed-in user, replies captured instead of sent."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

import web_assistant.router as web
from mesiri.infrastructure.redis.client import FakeRedis, RedisClient
from mesiri_contracts.assistant.enums import InputModality
from runtime.reply_capture import ReplyCapture

ORG = uuid.UUID("11111111-1111-4111-8111-111111111111")
USR = uuid.UUID("22222222-2222-4222-8222-222222222222")
NUMBER = "919876543210"


class _Handler:
    """Stands in for the production message handler: records the message and
    answers through whatever sender it was built with."""

    def __init__(self, *, delay: float = 0.0) -> None:
        self.messages: list[Any] = []
        self.payloads: list[dict] = []
        self.delay = delay

    def __call__(self, sender: Any):
        async def handle(message: Any, raw_payload: dict) -> None:
            self.messages.append(message)
            self.payloads.append(raw_payload)
            if self.delay:
                await asyncio.sleep(self.delay)
            await sender.send_text(NUMBER, "Got it. 10 workers on site today.")
            await sender.send_button(
                NUMBER,
                body="Save this?",
                buttons=[
                    SimpleNamespace(id="save_1", title="Save"),
                    SimpleNamespace(id="cancel_1", title="Cancel"),
                ],
            )

        return handle


class _Redis(FakeRedis):
    """The app's own Redis stand-in (UX-26: a hand-made double with incr/expire hid that the real client had neither,
    so every Tell Mesiri message answered 500 where Redis is set up), recording each window's expiry."""

    def __init__(self) -> None:
        super().__init__()
        self.expiries: dict[str, int] = {}

    async def count(self, key: str, *, ttl_seconds: int) -> int:
        self.expiries.setdefault(key, ttl_seconds)
        return await super().count(key, ttl_seconds=ttl_seconds)


def _container(handler: _Handler | None = None, redis: Any = None) -> Any:
    return SimpleNamespace(
        simulate_handler=handler or _Handler(), redis_client=redis, actor_reader=None
    )


def _request(container: Any) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))


@pytest.fixture(autouse=True)
def _known_sender(monkeypatch):
    """By default the sender is registered and their company active."""

    async def no_refusal(container: Any, wa_id: str) -> None:
        return None

    monkeypatch.setattr(web, "identity_refusal", no_refusal)


def _token(**overrides: Any) -> dict:
    return {"sub": str(USR), "org": str(ORG), "role": "SITE_ENGINEER", **overrides}


def _numbers(monkeypatch, number: str | None = NUMBER, *, seen: list | None = None) -> None:
    async def lookup(org_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
        if seen is not None:
            seen.append((org_id, user_id))
        return number

    monkeypatch.setattr(web, "user_whatsapp_number", lookup)


async def test_a_typed_update_runs_through_the_handler_as_the_signed_in_user(monkeypatch) -> None:
    seen: list = []
    _numbers(monkeypatch, seen=seen)
    handler = _Handler()

    response = await web.send_message(
        web.WebMessageRequest(text="  6 masons, 4 helpers. Slab shuttering done.  "),
        _request(_container(handler)),
        _token(),
    )

    # Acted as the token's own user, by their own number -- nothing in the body says who.
    assert seen == [(ORG, USR)]
    [message] = handler.messages
    assert message.sender.wa_id == NUMBER
    assert message.modality is InputModality.TEXT
    assert message.text == "6 masons, 4 helpers. Slab shuttering done."
    # Marked as from the dashboard in what gets logged.
    assert message.metadata["source"] == "dashboard"
    assert handler.payloads == [{"source": "dashboard"}]
    assert message.message_id == response.message_id and response.message_id.startswith("web")
    # Replies come back instead of going to WhatsApp, buttons and all.
    assert [r.type for r in response.replies] == ["text", "buttons"]
    assert [b.id for b in response.replies[1].buttons] == ["save_1", "cancel_1"]


async def test_a_button_tap_is_sent_as_the_tap(monkeypatch) -> None:
    _numbers(monkeypatch)
    handler = _Handler()

    await web.send_message(
        web.WebMessageRequest(interactive_reply_id="save_1"),
        _request(_container(handler)),
        _token(),
    )

    [message] = handler.messages
    assert message.modality is InputModality.INTERACTIVE
    assert message.text == "save_1"
    assert message.metadata["interactive_reply_id"] == "save_1"


async def test_someone_without_a_whatsapp_number_is_told_to_add_one(monkeypatch) -> None:
    _numbers(monkeypatch, None)
    handler = _Handler()

    with pytest.raises(HTTPException) as refused:
        await web.send_message(
            web.WebMessageRequest(text="hi"), _request(_container(handler)), _token()
        )

    assert refused.value.status_code == 409
    assert "WhatsApp number" in refused.value.detail
    assert handler.messages == []


@pytest.mark.parametrize("token", [{"sub": "not-a-uuid", "org": str(ORG)}, {"org": str(ORG)}, {}])
async def test_a_token_without_a_proper_user_is_refused(monkeypatch, token) -> None:
    _numbers(monkeypatch)

    with pytest.raises(HTTPException) as refused:
        await web.send_message(web.WebMessageRequest(text="hi"), _request(_container()), token)

    assert refused.value.status_code == 401


async def test_a_user_not_in_their_company_is_refused(monkeypatch) -> None:
    async def missing(org_id: uuid.UUID, user_id: uuid.UUID) -> str:
        raise web.UserNotFound(str(user_id))

    monkeypatch.setattr(web, "user_whatsapp_number", missing)

    with pytest.raises(HTTPException) as refused:
        await web.send_message(web.WebMessageRequest(text="hi"), _request(_container()), _token())

    assert refused.value.status_code == 401


async def test_a_suspended_company_gets_whatsapps_answer_and_nothing_runs(monkeypatch) -> None:
    _numbers(monkeypatch)

    async def suspended(container: Any, wa_id: str) -> str:
        return "Your company's Mesiri account is paused."

    monkeypatch.setattr(web, "identity_refusal", suspended)
    handler = _Handler()

    response = await web.send_message(
        web.WebMessageRequest(text="hi"), _request(_container(handler)), _token()
    )

    assert [r.text for r in response.replies] == ["Your company's Mesiri account is paused."]
    assert handler.messages == []


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (web.WebMessageRequest(text="   "), 400),
        (web.WebMessageRequest(text="x" * (web.MAX_TEXT + 1)), 413),
    ],
)
async def test_empty_or_too_long_is_refused_before_anything_runs(monkeypatch, body, status) -> None:
    _numbers(monkeypatch)
    handler = _Handler()

    with pytest.raises(HTTPException) as refused:
        await web.send_message(body, _request(_container(handler)), _token())

    assert refused.value.status_code == status
    assert handler.messages == []


async def test_too_many_messages_at_once_are_refused(monkeypatch) -> None:
    _numbers(monkeypatch)
    redis = _Redis()
    container = _container(redis=redis)

    for _ in range(web.RATE_LIMIT):
        await web.send_message(web.WebMessageRequest(text="update"), _request(container), _token())
    with pytest.raises(HTTPException) as refused:
        await web.send_message(
            web.WebMessageRequest(text="one more"), _request(container), _token()
        )

    assert refused.value.status_code == 429
    assert redis.expiries == {f"web_assistant:rate:{USR}": web.RATE_WINDOW_S}


async def test_a_slow_answer_says_it_is_still_working(monkeypatch) -> None:
    _numbers(monkeypatch)
    monkeypatch.setattr(web, "REPLY_TIMEOUT_S", 0.01)

    response = await web.send_message(
        web.WebMessageRequest(text="update"), _request(_container(_Handler(delay=1))), _token()
    )

    assert response.replies[-1].text == web.STILL_WORKING


async def test_not_wired_yet_is_a_503(monkeypatch) -> None:
    _numbers(monkeypatch)
    container = SimpleNamespace(simulate_handler=None, redis_client=None)

    with pytest.raises(HTTPException) as refused:
        await web.send_message(web.WebMessageRequest(text="hi"), _request(container), _token())

    assert refused.value.status_code == 503


async def test_the_shared_capture_keeps_the_control_panels_text_view() -> None:
    """simulate (control panel) reads `texts`; the same strings as before."""
    capture = ReplyCapture()
    sender = capture.sender()
    await sender.send_text(NUMBER, "Hello")
    await sender.send_list(
        NUMBER,
        body="Which site?",
        button_label="Sites",
        rows=[SimpleNamespace(id="s1", title="Green Villa")],
    )
    await sender.send_button(NUMBER, body="Save?", buttons=[SimpleNamespace(id="y", title="Yes")])
    assert await sender.mark_as_read(NUMBER) is True

    assert capture.texts == ["Hello", "Which site?\n  • Green Villa", "Save?\n\nReply Yes"]
    assert [r.type for r in capture.replies] == ["text", "list", "buttons"]
    assert capture.replies[1].list_rows[0].id == "s1"


# --- Voice (push 2) --------------------------------------------------------


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str | None]] = {}

    async def put_object(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        self.objects[key] = (data, content_type)


class _Database:
    """The log row the agent wrote the voice note's words to."""

    def __init__(self, body_text: str | None) -> None:
        self.body_text = body_text
        self.asked: list[dict] = []

    def transaction(self):
        database = self

        class _Tx:
            async def __aenter__(self):
                class _Conn:
                    async def execute(self, statement: Any, params: dict) -> Any:
                        database.asked.append(params)
                        row = SimpleNamespace(body_text=database.body_text)
                        return SimpleNamespace(first=lambda: row)

                return _Conn()

            async def __aexit__(self, *exc: object) -> None:
                return None

        return _Tx()


def _voice_request(container: Any, audio: bytes, headers: dict | None = None) -> Any:
    async def body() -> bytes:
        return audio

    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(container=container)), body=body, headers=headers or {}
    )


def _box(kind: bytes, body: bytes) -> bytes:
    return (8 + len(body)).to_bytes(4, "big") + kind + body


def _m4a(*, seconds: float, version: int = 0) -> bytes:
    """A phone's AAC recording as the door sees it: ftyp, the sound (mdat), then the movie header (moov/mvhd)."""
    scale = 1000
    length = int(seconds * scale)
    if version == 1:
        mvhd = bytes([1, 0, 0, 0]) + b"\x00" * 16 + scale.to_bytes(4, "big") + length.to_bytes(8, "big")
    else:
        mvhd = bytes([0, 0, 0, 0]) + b"\x00" * 8 + scale.to_bytes(4, "big") + length.to_bytes(4, "big")
    return _box(b"ftyp", b"M4A \x00\x00\x02\x00isomiso2") + _box(b"mdat", b"\x21" * 300) + _box(
        b"moov", _box(b"mvhd", mvhd + b"\x00" * 80)
    )


OGG = b"OggS" + b"\x00" * 200  # starts like an Ogg file; length unknown to the reader


async def test_a_voice_note_is_stored_and_sent_as_one_and_its_words_come_back(monkeypatch) -> None:
    _numbers(monkeypatch)
    handler = _Handler()
    storage = _Storage()
    database = _Database("ഇന്ന് 6 മേസൺമാരും 4 ഹെൽപ്പർമാരും")
    container = SimpleNamespace(
        simulate_handler=handler, redis_client=None, object_storage=storage, material_db=database
    )

    response = await web.send_voice(_voice_request(container, OGG), _token())

    [message] = handler.messages
    assert message.modality is InputModality.VOICE
    assert message.metadata["source"] == "dashboard"
    # Stored where WhatsApp's voice notes go, as Ogg, and pointed at.
    [(key, (data, content_type))] = storage.objects.items()
    assert key == f"media/{message.message_id}/web-voice.ogg"
    assert (data, content_type) == (OGG, "audio/ogg")
    assert message.media.object_key == key and message.media.mime_type == "audio/ogg"
    # The words are read back from the message's log row, not transcribed twice.
    assert database.asked == [{"c": message.correlation_id}]
    assert response.transcript == "ഇന്ന് 6 മേസൺമാരും 4 ഹെൽപ്പർമാരും"
    assert [r.type for r in response.replies] == ["text", "buttons"]


@pytest.mark.parametrize(
    ("audio", "status"),
    [
        (b"", 400),
        (b"RIFF....WAVEfmt ", 415),  # neither Ogg nor MP4: the door takes only what the phones and browsers record
        (_m4a(seconds=75), 413),  # MOB-03: an app recording over a minute, read from its own header
        (b"OggS" + b"\x00" * (web.MAX_VOICE_BYTES), 413),
    ],
)
async def test_a_recording_that_cannot_be_heard_is_refused_before_anything_runs(
    monkeypatch, audio, status
) -> None:
    _numbers(monkeypatch)
    handler = _Handler()
    storage = _Storage()
    container = SimpleNamespace(
        simulate_handler=handler, redis_client=None, object_storage=storage, material_db=None
    )

    with pytest.raises(HTTPException) as refused:
        await web.send_voice(_voice_request(container, audio), _token())

    assert refused.value.status_code == status
    assert handler.messages == [] and storage.objects == {}


async def test_typing_has_no_transcript(monkeypatch) -> None:
    _numbers(monkeypatch)

    response = await web.send_message(
        web.WebMessageRequest(text="hi"), _request(_container()), _token()
    )

    assert response.transcript is None


def test_the_rate_limit_uses_what_the_apps_redis_client_has() -> None:
    """The class guard: the limiter calls only what the real client and its stand-in both offer."""
    assert callable(getattr(RedisClient, "count", None)) and callable(getattr(FakeRedis, "count", None))


# --- The mobile app (MOB-03) -------------------------------------------------


async def test_a_phone_recording_m4a_is_stored_and_sent_as_a_voice_note_from_the_app(monkeypatch) -> None:
    _numbers(monkeypatch)
    handler = _Handler()
    storage = _Storage()
    container = SimpleNamespace(
        simulate_handler=handler, redis_client=None, object_storage=storage, material_db=_Database("innu 6 mason")
    )
    audio = _m4a(seconds=12.5)

    response = await web.send_voice(_voice_request(container, audio, {"X-Mesiri-Client": "app"}), _token())

    [message] = handler.messages
    assert message.modality is InputModality.VOICE
    assert message.metadata["source"] == "app"
    [(key, (data, content_type))] = storage.objects.items()
    assert key == f"media/{message.message_id}/web-voice.m4a"
    assert (data, content_type) == (audio, "audio/mp4")
    assert message.media.mime_type == "audio/mp4" and message.media.duration_seconds == 12.5
    assert response.transcript == "innu 6 mason"


async def test_the_dashboards_ogg_note_is_unchanged_and_an_unknown_client_is_the_dashboard(monkeypatch) -> None:
    """The guard: the dashboard's Tell Mesiri sends no header (or anything else) and stays the dashboard, as Ogg."""
    _numbers(monkeypatch)
    handler = _Handler()
    storage = _Storage()
    container = SimpleNamespace(
        simulate_handler=handler, redis_client=None, object_storage=storage, material_db=None
    )

    await web.send_voice(_voice_request(container, OGG, {"X-Mesiri-Client": "something"}), _token())

    [message] = handler.messages
    assert message.metadata["source"] == "dashboard"
    assert message.media.mime_type == "audio/ogg"


async def test_typing_from_the_app_is_marked_as_the_app(monkeypatch) -> None:
    _numbers(monkeypatch)
    handler = _Handler()
    request = _request(_container(handler))
    request.headers = {"x-mesiri-client": "App"}

    await web.send_message(web.WebMessageRequest(text="innu 4 helper"), request, _token())

    [message] = handler.messages
    assert message.metadata["source"] == "app"


@pytest.mark.parametrize("version", [0, 1])
def test_an_m4a_recordings_length_is_read_from_its_movie_header(version) -> None:
    assert web.m4a_duration_seconds(_m4a(seconds=42.0, version=version)) == 42.0
    assert web.voice_seconds(_m4a(seconds=3.5, version=version)) == 3.5


def test_a_broken_m4a_has_no_length_and_never_raises() -> None:
    assert web.m4a_duration_seconds(b"\x00\x00\x00\x18ftypM4A ") is None
    assert web.m4a_duration_seconds(_m4a(seconds=5)[:-40]) is None
    assert web.m4a_duration_seconds(b"\xff\xff\xff\xffmoov") is None


# --- The list waiting for Save, as data (MOB-05) ---------------------------------


def _pending(tool: str, key: str, summary: str, body: dict) -> dict:
    return {"tool": tool, "method": "POST", "path": "/materials/inflows", "params": {}, "body": body,
            "summary": summary, "idempotency_key": key}


async def test_the_reply_carries_the_list_waiting_for_save_as_the_assistant_keeps_it(monkeypatch) -> None:
    from agent_api.whatsapp import state_key

    _numbers(monkeypatch)
    redis = FakeRedis()
    material = str(uuid.uuid4())
    body = {"material_id": material, "unit_id": str(uuid.uuid4()), "quantity": 50, "supplier": "Malabar Traders"}
    state = {"batch": "b7", "pending": [_pending("record_receipt", "k-1", f"50 bags cement ({material}), Annex", body)]}
    await redis.set_json(state_key(ORG, USR), state)
    handler = _Handler()

    response = await web.send_message(
        web.WebMessageRequest(text="50 chaakku cement vannu"), _request(_container(handler, redis)), _token()
    )

    [entry] = response.ready
    assert (entry.line, entry.tool, entry.path, entry.key) == (1, "record_receipt", "/materials/inflows", "k-1")
    assert entry.body == body and entry.remove_id == "apiag:remove:b7:1"
    assert material not in entry.summary and entry.summary.startswith("50 bags cement")  # never an id in words
    # Read only: the assistant's list is exactly as it was.
    assert await redis.get_json(state_key(ORG, USR)) == state


async def test_nothing_waiting_is_an_empty_list_and_no_redis_is_none(monkeypatch) -> None:
    _numbers(monkeypatch)

    with_redis = await web.send_message(
        web.WebMessageRequest(text="hi"), _request(_container(redis=FakeRedis())), _token()
    )
    without = await web.send_message(web.WebMessageRequest(text="hi"), _request(_container()), _token())

    assert with_redis.ready == [] and without.ready is None


async def test_an_unreadable_or_odd_list_never_breaks_the_reply(monkeypatch) -> None:
    from agent_api.whatsapp import state_key

    _numbers(monkeypatch)

    class _Broken(FakeRedis):
        async def get_json(self, key: str) -> Any:
            raise RuntimeError("redis down")

    broken = await web.send_message(
        web.WebMessageRequest(text="hi"), _request(_container(redis=_Broken())), _token()
    )
    redis = FakeRedis()
    await redis.set_json(state_key(ORG, USR), {"batch": None, "pending": ["junk", {"tool": "x"},
                                                                          _pending("record_usage", "k-2", "3 bags", {})]})
    odd = await web.send_message(web.WebMessageRequest(text="hi"), _request(_container(redis=redis)), _token())

    assert broken.ready is None and [r.text for r in broken.replies]
    [entry] = odd.ready
    assert entry.line == 3 and entry.key == "k-2" and entry.remove_id is None  # no card, no Remove tap
