"""TM-21: the person who asked closes the loop themselves.

- an "it works now" note carries "Works ✅" / "Still wrong ❌" buttons;
- a tap is answered by the code in every mode (v3 and classic), and traced as ``release_feedback``;
  "Still wrong" is a ``tell_the_team`` call (kind wrong_reply), the shape the production watch reads, so the
  team bot re-plans it;
- a request to the team carries a short reference (#a83836), the same one the team group sees.
Guards: a tap that is not a verdict is untouched; a bad note id is not a verdict.
"""

from __future__ import annotations

import datetime as dt

import pytest
from tests.agent_api.test_api_whatsapp_119 import _journey, _message, _stand_in_tools  # noqa: F401 (autouse)
from tests.unit.test_agent_routing import ASK

from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.release_notes import (
    FEEDBACK_STAGE,
    ReleaseNote,
    parse_verdict,
    queue_release_notes,
    request_ref,
    verdict_buttons,
    verdict_trace,
)


def test_the_buttons_parse_back() -> None:
    works, wrong = verdict_buttons("lookup-as-image")
    assert parse_verdict(works["id"]) == (True, "lookup-as-image")
    assert parse_verdict(wrong["id"]) == (False, "lookup-as-image")
    assert parse_verdict("release_bad:../x") is None and parse_verdict("draft:save:1") is None


def test_still_wrong_is_a_tell_the_team_call() -> None:
    (call,) = verdict_trace(False, "lookup-as-image")["calls"]
    assert call["tool"] == "tell_the_team" and call["args"]["kind"] == "wrong_reply"
    assert "lookup-as-image" in call["args"]["about"]
    assert verdict_trace(True, "x-y-z")["calls"][0]["tool"] == "release_confirmed"


def test_request_ref() -> None:
    assert request_ref("cor_a838368708e5476aa92a8224e25b9038") == "#a83836"
    assert request_ref(None) == "" and request_ref("cor_ab") == ""


async def test_a_note_is_queued_with_the_two_buttons() -> None:
    import uuid
    from types import SimpleNamespace

    claimed: list[dict] = []

    async def claim(**kwargs):  # noqa: ANN003, ANN202
        claimed.append(kwargs)
        return 1

    async def requester(conn, cid):  # noqa: ANN001, ANN202
        return SimpleNamespace(user_id=uuid.uuid4(), organization_id=uuid.uuid4())

    note = ReleaseNote("lookup-as-image", dt.date(2026, 11, 2), ("cor_1",), "Works now 👍")
    assert await queue_release_notes(None, today=dt.date(2026, 11, 2), notes=[note], requester=requester,
                                     claim=claim) == 1
    assert [b["title"] for b in claimed[0]["payload"]["buttons"]] == ["Works ✅", "Still wrong ❌"]


@pytest.mark.parametrize("mode", ["api", "classic"])
@pytest.mark.parametrize(("tap", "words"), [("release_ok:lookup-as-image", "Glad it works"),
                                            ("release_bad:lookup-as-image", "still not right")])
async def test_a_tap_is_answered_and_traced_in_every_mode(monkeypatch, mode, tap, words) -> None:
    on_normalized, deps, harness = _journey(monkeypatch, mode, FakeToolCallingProvider(list(ASK._script)))
    await on_normalized(_message("Works ✅", tap=tap), {})
    texts = [c.args[1] for c in deps["sender"].send_text.await_args_list]
    assert any(words in t for t in texts), texts
    assert harness.seen == []  # no model, no API call
    stages = [c.kwargs.get("stage") for c in deps["trace_logger"].log_stage.await_args_list]
    assert FEEDBACK_STAGE in stages


async def test_a_request_to_the_team_shows_its_reference() -> None:
    from tests.agent_api.test_api_agent_124 import CTX, _service
    from tests.agent_api.test_api_agent_124 import _message as message124

    model = FakeToolCallingProvider([
        [("tell_the_team", {"kind": "missing_feature", "about": "add a member from WhatsApp"})],
        "Passed to the team; I'll message you here when it works.",
    ])
    service, sent = _service(model)
    msg = message124("add Ravi as a member")
    assert await service.handle(msg, CTX)
    assert request_ref(msg.correlation_id) in sent[-1].text
