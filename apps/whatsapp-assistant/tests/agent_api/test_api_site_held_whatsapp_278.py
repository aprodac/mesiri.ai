"""WA-278 through WhatsApp: the update, the code's site question with the site buttons, the tap, the card, Save.

The agent-level cases are in ``test_api_site_held_278.py``. This is 12 Nov 02:12-02:13 (Aprodac) as the person sees
it: the model runs once, on the first message, and never again; the tap brings the line back as it was said.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from tests.agent_api.standin import BAG, CEMENT, PROJECT, SITE, receipt_call
from tests.agent_api.test_api_whatsapp_119 import (  # noqa: F401
    CTX,
    Harness,
    _message,
    _stand_in_tools,
)

from mesiri_ai.fakes import FakeToolCallingProvider


class Counting(FakeToolCallingProvider):
    pass


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(**vars(CTX),
                           projects=[SimpleNamespace(id=PROJECT, name="Green Villa")],
                           sites=[SimpleNamespace(id=SITE, name="Annex", project_id=PROJECT),
                                  SimpleNamespace(id=str(uuid.uuid4()), name="Main block", project_id=PROJECT)])


async def test_the_tap_on_the_site_brings_the_line_back_and_save_records_it() -> None:
    ctx = _ctx()
    model = Counting([[receipt_call(CEMENT, BAG, "50 bags cement")], "Cement update cheythu."])
    h = Harness(model)
    await h.service.handle(_message("50 chaakku cement vannu"), ctx)
    asked = h.sent[-1]
    assert "update cheythu" not in asked.text  # nothing is prepared yet, and the reply does not say otherwise
    assert [b.title for b in asked.buttons][:2] == ["Annex", "Main block"]
    assert h.posts() == 0

    await h.service.handle(_message("Annex", tap=asked.buttons[0].id), ctx)
    card = h.sent[-1]
    assert "50 bags cement" in card.text and "Save" in [b.title for b in card.buttons]
    assert model.calls == 1  # the tap ran no model

    await h.service.handle(_message(None, tap=next(b.id for b in card.buttons if b.title == "Save")), ctx)
    assert h.posts() == 1


async def test_cancel_lets_the_held_lines_go() -> None:
    ctx = _ctx()
    h = Harness(Counting([[receipt_call(CEMENT, BAG, "50 bags cement")], "Sheri."]))
    await h.service.handle(_message("50 chaakku cement vannu"), ctx)
    await h.service.handle(_message("cancel"), ctx)
    assert "Cancel" in h.sent[-1].text or "cancel" in h.sent[-1].text.lower()
    h.service._agent._provider = FakeToolCallingProvider(["Sheri."])  # a model that prepares nothing by itself
    await h.service.handle(_message("Annex"), ctx)  # the site said later brings nothing back
    assert h.posts() == 0 and "50 bags cement" not in h.sent[-1].text
