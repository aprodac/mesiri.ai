"""WA-09: an outside DPR contact's YES / STOP to the opt-in invite, on the
WhatsApp side (the database rules are tested in backend/tests)."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

from channel.whatsapp.templates import DPR_OPT_IN, choose_template
from mesiri.application.dpr import opt_in_invite
from mesiri.application.dpr.opt_in_invite import Answered, invite_payload
from mesiri.application.dpr.recipients import OPTED_IN, OPTED_OUT
from runtime.opt_in_journey import OptInJourney


class _Db:
    @contextlib.asynccontextmanager
    async def transaction(self):
        yield object()


def _message(text=None, tap=None, wa_id="919876500399"):
    return SimpleNamespace(
        text=text,
        metadata={"interactive_reply_id": tap} if tap else {},
        sender=SimpleNamespace(wa_id=wa_id),
    )


def _answers(monkeypatch, result):
    calls = []

    async def record(conn, *, phone, answer):
        calls.append((phone, answer))
        return result

    monkeypatch.setattr(opt_in_invite, "record_answer", record)
    return calls


async def test_yes_is_recorded_and_thanked(monkeypatch):
    calls = _answers(monkeypatch, Answered(OPTED_IN, ["Suresh Builders"]))
    reply = await OptInJourney(db=_Db()).handle(_message("Yes"))
    assert calls == [("919876500399", "yes")]
    assert reply == "Thanks. You'll get the daily progress report from Suresh Builders here."


async def test_stop_button_tap(monkeypatch):
    calls = _answers(monkeypatch, Answered(OPTED_OUT, ["Suresh Builders"]))
    reply = await OptInJourney(db=_Db()).handle(_message(tap="optin:stop"))
    assert calls == [("919876500399", "stop")]
    assert reply.startswith("Done. Suresh Builders won't message you here again.")


async def test_anything_else_falls_through(monkeypatch):
    calls = _answers(monkeypatch, None)
    journey = OptInJourney(db=_Db())
    assert await journey.handle(_message("hi, I want to try Mesiri")) is None
    assert calls == []  # not even looked up
    assert await journey.handle(_message("YES")) is None  # nobody invited this number


def test_invite_template_is_chosen_with_its_buttons():
    payload = invite_payload(phone="919876500399", company="Suresh Builders", project="Green Towers")
    choice = choose_template(payload, frozenset({DPR_OPT_IN.name}))
    assert choice.spec is DPR_OPT_IN
    assert choice.body_params == ("Suresh Builders", "Green Towers")
    assert choice.button_payloads == ("optin:yes", "optin:stop")
