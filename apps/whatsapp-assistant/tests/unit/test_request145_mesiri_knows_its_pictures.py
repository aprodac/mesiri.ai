"""Request 145 (live 29 Oct, Ilan @ Paraclette): Mesiri sent a picture, then said three
times "I didn't send an image" -- it kept only the WORDS of what it sent, and a card has
none. Now every picture / PDF is kept under its wamid with what it shows."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from channel.replies import ListRow, ReplySpec
from channel.whatsapp import sent_text
from channel.whatsapp.outbound import WhatsAppSender
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    NormalizedMessage,
    ReplyContext,
    SenderInfo,
)
from runtime.agent import runner as r
from runtime.agent.turn import AgentTurnDeps, run_agent_turn
from runtime.reply_dispatch import send_reply_spec

from .test_photo_journey import USER, _build, _photo, _sent_texts

WA = "919000000001"
CARD = "[picture: Workers list card, 29 Oct, 30 workers]"


@pytest.fixture
def store(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(sent_text, "_store", redis)
    return redis


# -- the label ------------------------------------------------------------------------------------


def test_the_label_of_each_kind_of_media():
    image = {"type": "image", "image": {"id": "m"}}
    assert sent_text.media_label_of_fields(image, "Workers list card") == "[picture: Workers list card]"
    assert sent_text.media_label_of_fields(image) == "[picture]"
    document = {"type": "document", "document": {"id": "m", "filename": "workers.pdf"}}
    assert sent_text.media_label_of_fields(document, "Workers list") == "[PDF: Workers list]"
    assert sent_text.media_label_of_fields(document) == "[PDF: workers.pdf]"  # names its file
    header = {"type": "interactive", "interactive": {"header": {"type": "image"}, "body": {"text": "Saved"}}}
    assert sent_text.media_label_of_fields(header, "Saved card") == "[picture: Saved card]"
    # GUARD: words only -> no media
    assert sent_text.media_label_of_fields({"type": "text", "text": {"body": "hi"}}, "x") == ""
    plain = {"type": "interactive", "interactive": {"body": {"text": "Yes?"}}}
    assert sent_text.media_label_of_fields(plain) == ""


async def test_a_captionless_card_is_kept_and_read_back_by_its_id(store):
    fields = {"type": "image", "image": {"id": "m"}}
    sent_text.report_sent(wamid="wamid.card", message_fields=fields, recipient=WA, shows="Workers list card, 29 Oct, 30 workers")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert await sent_text.text_of("wamid.card") == (CARD, "mesiri")
    media = await sent_text.recent_media_to(WA)
    assert [label for label, _ in media] == [CARD]


async def test_a_caption_is_kept_beside_the_label(store):
    fields = {"type": "image", "image": {"id": "m", "caption": "Stock today"}}
    sent_text.report_sent(wamid="wamid.s", message_fields=fields, recipient=WA, shows="Stock card")
    await asyncio.sleep(0)
    assert await sent_text.text_of("wamid.s") == ("[picture: Stock card]\nStock today", "mesiri")


async def test_text_only_messages_keep_no_media(store):
    sent_text.report_sent(wamid="w", message_fields={"type": "text", "text": {"body": "hi"}}, recipient=WA)
    await asyncio.sleep(0)
    assert await sent_text.text_of("w") == ("hi", "mesiri")
    assert await sent_text.recent_media_to(WA) == []


async def test_only_the_latest_pictures_are_kept(store):
    for n in range(sent_text.MEDIA_KEPT + 3):
        await sent_text._remember_media(WA, f"[picture: {n}]")
    kept = await sent_text.recent_media_to(WA)
    assert len(kept) == sent_text.MEDIA_KEPT and kept[-1][0] == f"[picture: {sent_text.MEDIA_KEPT + 2}]"


# -- the sender passes `shows` on --------------------------------------------------------------------


async def test_the_sender_hands_shows_to_the_record(store, monkeypatch):
    sender = WhatsAppSender(client=None, access_token="t", phone_number_id="p")  # type: ignore[arg-type]
    seen = {}
    sender._upload_media = AsyncMock(return_value="mid")

    async def fake_send(to, fields, *, shows=None):
        seen.update(fields=fields, shows=shows)
        return "wamid.x"

    sender._send = fake_send
    assert await sender.send_image(WA, b"png", shows="Workers list card") is True
    assert seen["shows"] == "Workers list card"
    assert await sender.send_document(WA, b"pdf", filename="w.pdf", shows="Workers list") is True
    assert seen["shows"] == "Workers list"
    assert await sender.send_button(WA, body="Saved", buttons=[ListRow("a", "OK")], header_image=b"p", shows="Saved card")
    assert seen["shows"] == "Saved card"


# -- the dispatch always labels a card -------------------------------------------------------------


async def test_a_card_that_rides_a_reply_is_labelled_even_without_shows():
    send_button = AsyncMock(return_value=True)
    reply = ReplySpec(text="Saved 5 masons\nBuilding A", buttons=(SimpleNamespace(id="a", title="OK"),), header_image=b"png")
    await send_reply_spec(reply, WA, send_text=AsyncMock(), send_button=send_button)
    assert send_button.await_args.kwargs["shows"] == 'card sent with the reply "Saved 5 masons"'
    send_image = AsyncMock(return_value=True)
    stock = dataclasses.replace(reply, buttons=None, caption_image=True, shows="Stock card")
    await send_reply_spec(stock, WA, send_text=AsyncMock(), send_image=send_image)
    assert send_image.await_args.kwargs["shows"] == "Stock card"
    send_image.reset_mock()
    await send_reply_spec(ReplySpec(text="Hello", header_image=b"png"), WA, send_text=AsyncMock(), send_image=send_image)
    assert send_image.await_args.kwargs["shows"] == 'card sent with the reply "Hello"'


def test_every_media_send_in_the_runtime_says_what_it_shows():
    """The class guard: a new send_image / send_document / header_image send without
    `shows=` fails here."""
    root = Path(__file__).resolve().parents[2] / "src" / "runtime"
    missing = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            keywords = {k.arg for k in node.keywords}
            sends_media = name in {"send_image", "send_document", "_send_image"} or (
                name == "send_button" and "header_image" in keywords
            )
            if sends_media and "shows" not in keywords and None not in keywords:
                missing.append(f"{path.relative_to(root.parent)}:{node.lineno} {name}")
    assert missing == []


# -- the turn ------------------------------------------------------------------------------------------


def _message(text, *, quoted=None):
    return NormalizedMessage(
        message_id="wamid.in",
        sender=SenderInfo(wa_id=WA, profile_name="A"),
        timestamp=dt.datetime(2026, 10, 29, 8, 0),
        modality=InputModality.TEXT,
        text=text,
        reply_context=ReplyContext(replied_to_message_id=quoted) if quoted else None,
    )


def _deps(seen):
    async def run(**kw):
        seen.append(kw)
        return r.AgentResult("degraded", r.ReplySpec(text="ok"), SimpleNamespace(parked=None, saved=[]))

    return AgentTurnDeps(
        runner=SimpleNamespace(run=run),
        make_gateway=lambda m, lang: SimpleNamespace(handled=[], finish=AsyncMock()),
        send_spec=AsyncMock(),
        transcribe=None,
        message_logger=AsyncMock(),
    )


_ACTOR = SimpleNamespace(user_id="u", full_name="A", role="S", org_name="O", projects=[], sites=[], organization_id="o")


async def test_a_swipe_reply_to_a_captionless_card_shows_its_label(store):
    sent_text.report_sent(wamid="wamid.card", message_fields={"type": "image", "image": {"id": "m"}}, recipient=WA,
                          shows="Workers list card, 29 Oct, 30 workers")
    await asyncio.sleep(0)
    seen: list = []
    await run_agent_turn(_message("Ith photo elle?", quoted="wamid.card"), _ACTOR, _deps(seen))
    assert seen[0]["ctx"].replying_to == (CARD, "mesiri")  # not UNKNOWN


async def test_a_swipe_reply_to_a_pdf_shows_its_label(store):
    sent_text.report_sent(wamid="wamid.pdf", message_fields={"type": "document", "document": {"id": "m", "filename": "dpr.pdf"}},
                          recipient=WA, shows="Daily progress report (DPR) PDF")
    await asyncio.sleep(0)
    seen: list = []
    await run_agent_turn(_message("This .", quoted="wamid.pdf"), _ACTOR, _deps(seen))
    assert seen[0]["ctx"].replying_to == ("[PDF: Daily progress report (DPR) PDF]", "mesiri")


async def test_a_text_swipe_reply_is_unchanged(store):
    await sent_text.remember(wamid="wamid.t", text="Saved 5 masons")
    seen: list = []
    await run_agent_turn(_message("ok", quoted="wamid.t"), _ACTOR, _deps(seen))
    assert seen[0]["ctx"].replying_to == ("Saved 5 masons", "mesiri")
    assert not any("DID go out" in n for n in seen[0]["ctx"].notes)


async def test_the_next_message_knows_the_picture_was_sent(store):
    sent_text.report_sent(wamid="wamid.card", message_fields={"type": "image", "image": {"id": "m"}}, recipient=WA,
                          shows="Workers list card, 29 Oct, 30 workers")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    seen: list = []
    await run_agent_turn(_message("njan image ayachilla? pinne ith?"), _ACTOR, _deps(seen))
    notes = [n for n in seen[0]["ctx"].notes if "DID go out" in n]
    assert len(notes) == 1 and CARD in notes[0]


async def test_no_picture_sent_no_note(store):
    seen: list = []
    await run_agent_turn(_message("hello"), _ACTOR, _deps(seen))
    assert not any("DID go out" in n for n in seen[0]["ctx"].notes)


# -- a photo with words ---------------------------------------------------------------------------------


async def test_a_photo_with_manglish_words_is_not_asked_what_it_is_for(monkeypatch):
    on_normalized, deps = _build(monkeypatch)
    await on_normalized(_photo("wamid.1", "Pinne ithenentha Manda?"), {})
    assert not any("What is this photo for" in t for t in _sent_texts(deps))
    assert await deps["pending_media_store"].has_pending(user_id=USER) is False  # not held for the picker


async def test_a_photo_with_a_stray_mark_is_still_asked(monkeypatch):
    on_normalized, deps = _build(monkeypatch)
    await on_normalized(_photo("wamid.1", "."), {})
    assert any("What is this photo for" in t for t in _sent_texts(deps))
