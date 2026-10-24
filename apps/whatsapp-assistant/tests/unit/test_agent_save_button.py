"""WA-35: nothing the agent saves is kept until the sender taps Save.

The agent's records are save-first drafts; its reply lists them (written by
code) under "To save:" with Save / Cancel, and the tap confirms or rejects
exactly those drafts -- only the tapper's own, in their own company, and only
while they are still drafts.
"""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from channel.replies import ListRow, ReplySpec
from mesiri_contracts.assistant.draft_action import DraftActionType
from runtime.agent import save_button
from runtime.agent.save_button import (
    CANCEL,
    CANCEL_TITLE,
    MAX_ITEMS,
    SAVE,
    SAVE_TITLE,
    TO_SAVE_HEADER,
    facts_of,
    parse_tap,
    tap_id,
    with_save_buttons,
)
from runtime.reply_composer import PHOTO_ROW, UNDO_ROW
from runtime.save_first import DraftsSettled, SaveFirstService

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
OTHER = "55555555-5555-4555-8555-555555555555"
LABOUR = uuid.UUID("33333333-3333-4333-8333-333333333333")
CEMENT = uuid.UUID("44444444-4444-4444-8444-444444444444")


def _handled(action=DraftActionType.RECORD_LABOUR_ATTENDANCE, row=LABOUR, draft=True):
    return SimpleNamespace(
        saved_draft=draft,
        execution_result=SimpleNamespace(material_row_id=str(row)),
        result=SimpleNamespace(
            confirmed_action=SimpleNamespace(draft_action=SimpleNamespace(action_type=action, fields={}))
        ),
    )


# -- the tap id ---------------------------------------------------------------


def test_the_tap_names_exactly_the_records_on_the_card():
    facts = [("labour_report", LABOUR), ("material_usage", CEMENT)]
    assert parse_tap(tap_id(SAVE, facts)) == (SAVE, facts)
    assert parse_tap(tap_id(CANCEL, facts)) == (CANCEL, facts)


def test_the_most_records_still_fit_a_whatsapp_button_id():
    facts = [("material_receipt", uuid.uuid4()) for _ in range(MAX_ITEMS)]
    assert len(tap_id(CANCEL, facts)) <= 256


@pytest.mark.parametrize(
    "value",
    [
        "agt:",
        "agt:save:",
        "agt:delete:l" + LABOUR.hex,
        "agt:save:z" + LABOUR.hex,
        "agt:save:lnothex",
    ],
)
def test_a_malformed_tap_is_refused(value):
    assert parse_tap(value) is None


def test_someone_elses_tap_is_not_ours():
    assert parse_tap("sdr:confirm:abc:20261021") is None


# -- which replies get the buttons ----------------------------------------------


def test_every_saved_draft_goes_on_the_card():
    facts = facts_of([_handled(), _handled(DraftActionType.RECORD_MATERIAL_USAGE, CEMENT)])
    assert facts == [("labour_report", LABOUR), ("material_usage", CEMENT)]


def test_a_record_the_review_log_does_not_cover_keeps_the_undo_button():
    progress = _handled(DraftActionType.ADD_PROGRESS_UPDATE)
    assert facts_of([_handled(), progress]) is None
    assert facts_of([_handled(draft=False)]) is None
    assert facts_of([]) is None


def test_too_many_records_for_one_tap_keep_the_undo_button():
    assert facts_of([_handled(row=uuid.uuid4()) for _ in range(MAX_ITEMS + 1)]) is None


def test_the_reply_says_to_save_and_offers_save_and_cancel_instead_of_undo():
    facts = [("labour_report", LABOUR)]
    composed = ReplySpec(text="✅ Saved: 16 workers (6 mason, 10 helper)", buttons=(UNDO_ROW,))

    out = with_save_buttons(composed, facts)

    assert out.text == f"{TO_SAVE_HEADER} 16 workers (6 mason, 10 helper)"
    assert [b.title for b in out.buttons] == [SAVE_TITLE, CANCEL_TITLE]
    assert out.buttons[0].id == tap_id(SAVE, facts)


def test_the_team_photo_offer_stays_after_save_and_cancel():
    composed = ReplySpec(
        text="✅ Saved:\n• 16 workers\n• 20 bags cement used\n\n📷 Add a team photo?",
        buttons=(PHOTO_ROW, UNDO_ROW),
        header_image=b"png",
    )
    out = with_save_buttons(composed, [("labour_report", LABOUR)])
    assert out.text.startswith(f"{TO_SAVE_HEADER}\n• 16 workers")
    assert [b.title for b in out.buttons] == [SAVE_TITLE, CANCEL_TITLE, PHOTO_ROW.title]
    assert out.header_image == b"png"


# -- what a tap does --------------------------------------------------------------


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, latest):
        self.latest = latest  # fact_id -> {"state", "actor_user_id"}

    async def execute(self, statement, params=None):
        if "FROM fact_reviews" in str(statement):
            row = self.latest.get(params["fact_id"])
            return _Result([row] if row else [])
        return _Result()


class _Db:
    def __init__(self, conn):
        self.conn = conn

    @contextlib.asynccontextmanager
    async def transaction(self):
        yield self.conn


@pytest.fixture
def reviews(monkeypatch):
    calls: dict[str, list] = {"confirm": [], "reject": [], "refuse": []}
    from mesiri.application.dpr.fact_review import FactReviewError
    from mesiri.infrastructure.postgres.repositories import fact_reviews

    class _Repo:
        def __init__(self, conn):
            pass

        async def confirm(self, **kwargs):
            calls["confirm"].append(kwargs)
            return True

        async def reject(self, **kwargs):
            if kwargs["fact_id"] in calls["refuse"]:
                raise FactReviewError("this day's DPR is already confirmed; revise it instead")
            calls["reject"].append(kwargs)

    monkeypatch.setattr(fact_reviews, "PostgresFactReviewRepository", _Repo)
    return calls


def _draft(actor=USR):
    return {"state": "draft", "actor_user_id": uuid.UUID(actor)}


async def test_save_confirms_the_senders_own_drafts(reviews):
    service = SaveFirstService(db=_Db(_Conn({LABOUR: _draft(), CEMENT: _draft()})))
    settled = await service.settle_drafts(
        organization_id=ORG,
        actor_user_id=f"ctx_user_{USR}",
        facts=[("labour_report", LABOUR), ("material_usage", CEMENT)],
        keep=True,
    )
    assert (settled.done, settled.already, settled.refused) == (2, 0, [])
    assert [c["fact_id"] for c in reviews["confirm"]] == [LABOUR, CEMENT]
    assert all(c["organization_id"] == uuid.UUID(ORG) for c in reviews["confirm"])
    assert reviews["reject"] == []


async def test_cancel_removes_them_through_each_modules_undo(reviews):
    service = SaveFirstService(db=_Db(_Conn({LABOUR: _draft()})))
    settled = await service.settle_drafts(
        organization_id=ORG, actor_user_id=USR, facts=[("labour_report", LABOUR)], keep=False
    )
    assert settled.done == 1
    [call] = reviews["reject"]
    assert call["fact_type"] == "labour_report" and call["reason"]


async def test_a_record_already_confirmed_or_removed_is_left_alone(reviews):
    conn = _Conn({LABOUR: {"state": "confirmed", "actor_user_id": uuid.UUID(USR)}})
    service = SaveFirstService(db=_Db(conn))
    settled = await service.settle_drafts(
        organization_id=ORG,
        actor_user_id=USR,
        facts=[("labour_report", LABOUR), ("material_usage", CEMENT)],
        keep=True,
    )
    assert (settled.done, settled.already) == (0, 2)
    assert reviews["confirm"] == []


async def test_cancel_after_save_says_it_is_kept_not_done(reviews):
    conn = _Conn({LABOUR: {"state": "confirmed", "actor_user_id": uuid.UUID(USR)}})
    service = SaveFirstService(db=_Db(conn))
    settled = await service.settle_drafts(
        organization_id=ORG, actor_user_id=USR, facts=[("labour_report", LABOUR)], keep=False
    )
    assert settled.done == 0 and settled.already == 0
    assert settled.refused == ["it was already saved; fix it on the dashboard"]
    assert reviews["reject"] == []


async def test_save_after_cancel_says_send_it_again(reviews):
    conn = _Conn({LABOUR: {"state": "rejected", "actor_user_id": uuid.UUID(USR)}})
    service = SaveFirstService(db=_Db(conn))
    settled = await service.settle_drafts(
        organization_id=ORG, actor_user_id=USR, facts=[("labour_report", LABOUR)], keep=True
    )
    assert settled.refused == ["it was already cancelled; send it again"]
    assert reviews["confirm"] == []


async def test_nobody_can_tap_someone_elses_drafts(reviews):
    service = SaveFirstService(db=_Db(_Conn({LABOUR: _draft(actor=OTHER)})))
    settled = await service.settle_drafts(
        organization_id=ORG, actor_user_id=USR, facts=[("labour_report", LABOUR)], keep=False
    )
    assert settled.done == 0 and settled.refused == ["not your entry"]
    assert reviews["reject"] == []


async def test_a_sender_with_no_company_settles_nothing(reviews):
    service = SaveFirstService(db=_Db(_Conn({LABOUR: _draft()})))
    settled = await service.settle_drafts(
        organization_id=None, actor_user_id=USR, facts=[("labour_report", LABOUR)], keep=True
    )
    assert settled.done == 0 and settled.refused
    assert reviews["confirm"] == []


async def test_one_refused_item_leaves_the_rest_done(reviews):
    reviews["refuse"].append(LABOUR)
    service = SaveFirstService(db=_Db(_Conn({LABOUR: _draft(), CEMENT: _draft()})))
    settled = await service.settle_drafts(
        organization_id=ORG,
        actor_user_id=USR,
        facts=[("labour_report", LABOUR), ("material_usage", CEMENT)],
        keep=False,
    )
    assert settled.done == 1
    assert settled.refused == ["this day's DPR is already confirmed; revise it instead"]


# -- the tap, end to end through the handler -----------------------------------


def _tap(reply_id):
    return SimpleNamespace(metadata={"interactive_reply_id": reply_id})


ACTOR = SimpleNamespace(organization_id=ORG, user_id=USR)


async def test_a_message_that_is_not_our_tap_is_left_for_the_rest_of_the_journey():
    handler = AsyncMock()
    assert await save_button.handle_tap(SimpleNamespace(metadata=None), ACTOR, handler) is None
    assert await save_button.handle_tap(_tap("sdr:confirm:x:20261021"), ACTOR, handler) is None
    handler.settle_drafts.assert_not_awaited()


async def test_a_save_tap_says_saved():
    handler = AsyncMock()
    handler.settle_drafts.return_value = DraftsSettled(done=2)
    facts = [("labour_report", LABOUR), ("material_usage", CEMENT)]

    reply = await save_button.handle_tap(_tap(tap_id(SAVE, facts)), ACTOR, handler)

    assert reply.text == save_button.SAVED_DONE
    kwargs = handler.settle_drafts.await_args.kwargs
    assert kwargs["facts"] == facts and kwargs["keep"] is True and kwargs["user_id"] == USR


async def test_a_cancel_tap_says_nothing_was_kept():
    handler = AsyncMock()
    handler.settle_drafts.return_value = DraftsSettled(done=1)
    reply = await save_button.handle_tap(
        _tap(tap_id(CANCEL, [("labour_report", LABOUR)])), ACTOR, handler
    )
    assert reply.text == save_button.CANCELLED_DONE
    assert handler.settle_drafts.await_args.kwargs["keep"] is False


async def test_a_second_tap_says_it_is_already_done():
    handler = AsyncMock()
    handler.settle_drafts.return_value = DraftsSettled(already=1)
    reply = await save_button.handle_tap(
        _tap(tap_id(SAVE, [("labour_report", LABOUR)])), ACTOR, handler
    )
    assert reply.text == save_button.ALREADY_DONE


async def test_a_refusal_is_said_plainly():
    handler = AsyncMock()
    handler.settle_drafts.return_value = DraftsSettled(done=1, refused=["the day is confirmed"])
    reply = await save_button.handle_tap(
        _tap(tap_id(CANCEL, [("labour_report", LABOUR), ("material_usage", CEMENT)])),
        ACTOR,
        handler,
    )
    assert (
        reply.text
        == f"{save_button.CANCELLED_DONE}\nCouldn't cancel 1 of them: the day is confirmed."
    )


async def test_a_broken_tap_has_expired():
    reply = await save_button.handle_tap(_tap("agt:save:zzz"), ACTOR, AsyncMock())
    assert reply.text == save_button.EXPIRED


def test_a_typed_save_is_the_tap():
    """A worker who types "save" instead of tapping gets the same thing
    (request [45]'s typed choices match the button title)."""
    from runtime.reply_composer import resolve_choice

    rows = [
        ListRow(tap_id(SAVE, [("labour_report", LABOUR)]), SAVE_TITLE),
        ListRow("x", CANCEL_TITLE),
    ]
    assert resolve_choice("save", rows) is rows[0]
    assert resolve_choice("Cancel", rows) is rows[1]


# -- WA-37: a question passed to the engineer is no entry to save ---------------


def _question(row=CEMENT):
    handled = _handled(DraftActionType.RECORD_SITE_ISSUE, row)
    handled.result.confirmed_action.draft_action.fields = {
        "narrative": "Question for your engineer: can we remove the props today?"
    }
    return handled


def test_a_question_for_the_engineer_is_left_off_the_card():
    assert save_button.is_engineer_question(_question())
    assert not save_button.is_engineer_question(_handled())
    assert facts_of([_handled(), _question()]) == [("labour_report", LABOUR)]


def test_a_reply_that_only_passed_a_question_on_gets_no_save_card():
    assert facts_of([_question()]) is None
