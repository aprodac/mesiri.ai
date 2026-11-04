"""[225] (4 Nov 00:20-00:22, Ilan, Paraclette, cor ...33e84f, ...035409, ...02a93d): a voice note "one load of M sand
came" -> "which site? Tower A / Mithilash / Rana Mart / Other" -> tapped Tower A -> "1 load = how many bags?" -> "50"
-> the site was asked again. Root cause: ``decide_site`` read only THIS message; the tap was not saved yet and no line
in the list held it. Fix: the code keeps the site picked for the update (``whatsapp._keep_pick``, before the model
runs) and ``working_place`` puts it after the ready list and before today's saved site; ``_named`` reads a Malayalam
ending ("Mithilashil"). Siblings (the bot's review of its own fix, #7669): the model asks before preparing anything;
a typed Manglish pick; another site named later. Guards: a new request with nothing waiting drops the pick ([219]);
Cancel drops it; a single-site sender is never asked; a just-created project is not a pick ([215]).
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

from tests.agent_api.standin import BAG, CEMENT, PROJECT, stand_in_tools  # noqa: F401
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message, _stand_in_tools  # noqa: F401 (autouse)

from agent_api import whatsapp as wa
from agent_api.agent import Place, Places, _named, decide_site, picked_site, working_place
from agent_api.tools import CONFIRM_ARG
from mesiri_ai.fakes import FakeToolCallingProvider

TOWER, MITHILASH, RANA = (str(uuid.uuid4()) for _ in range(3))
SITES = [SimpleNamespace(id=TOWER, name="Tower A", project_id=PROJECT),
         SimpleNamespace(id=MITHILASH, name="Mithilash", project_id=PROJECT),
         SimpleNamespace(id=RANA, name="Rana Mart", project_id=PROJECT)]
SITE_Q = {"question": "Which site is this for?", "options": ["Tower A", "Mithilash", "Rana Mart"]}


def _ctx(sites=SITES):  # noqa: ANN001, ANN202
    return SimpleNamespace(**{**vars(CTX), "projects": [SimpleNamespace(id=PROJECT, name="Paraclette main")],
                              "sites": list(sites)})


def _receipt(qty: int, line: str, site: str | None = None) -> tuple[str, dict]:
    body = {"project_id": PROJECT, "material_id": CEMENT, "unit_id": BAG, "quantity": qty,
            "occurred_date": "2026-11-04", CONFIRM_ARG: line}
    return ("record_receipt", {**body, **({"site_id": site} if site else {})})


async def _state(h: Harness) -> dict:
    return await h.redis.get_json(f"agent_api:{CTX.organization_id}:{CTX.user_id}") or {}


async def _turn(h: Harness, said: str, *script, tap: str | None = None) -> None:
    """One message, with the model's script for that turn only."""
    h.service._agent._provider = FakeToolCallingProvider(list(script) or ["Ok."])
    await h.service.handle(_message(said, tap=tap), _ctx())


async def _ask_site_first(h: Harness) -> None:
    await h.redis.set_json(f"agent_api:{CTX.organization_id}:{CTX.user_id}", {"asked": SITE_Q, "language": "manglish"})


# -- the reported journey, end to end --------------------------------------------------------------------------

async def test_the_tapped_site_holds_through_the_size_answer() -> None:
    """Tap Tower A -> the model asks the size before preparing anything (the review's case 1) -> "50" -> prepared at
    Tower A, with no second site question."""
    h = Harness(FakeToolCallingProvider(["Ok."]))
    await _ask_site_first(h)
    await _turn(h, "Tower A", "1 load ethra bag aanu?")
    assert (await _state(h))["site_pick"]["site_id"] == TOWER
    await _turn(h, "50", [_receipt(50, "50 bags cement")], "Ready.")
    state = await _state(h)
    assert [e["body"].get("site_id") for e in state["pending"]] == [TOWER]
    assert "Which site" not in (h.sent[-1].text or "") and not (state.get("asked") or {}).get("options")


async def test_sibling_a_typed_manglish_pick() -> None:
    h = Harness(FakeToolCallingProvider(["Ok."]))
    await _ask_site_first(h)
    await _turn(h, "Mithilashil aanu", "Ethra bag?")
    await _turn(h, "4 bag", [_receipt(4, "4 bags cement")], "Ready.")
    assert [e["body"].get("site_id") for e in (await _state(h))["pending"]] == [MITHILASH]


async def test_sibling_a_site_named_later_moves_the_next_line() -> None:
    h = Harness(FakeToolCallingProvider(["Ok."]))
    await _ask_site_first(h)
    await _turn(h, "Tower A", [_receipt(50, "50 bags cement")], "Ready.")  # the line at the pick
    await _turn(h, "2 bag Mithilashil", [_receipt(2, "2 bags cement")], "Ready.")  # named: the code moves it
    await _turn(h, "3 bag koodi", [_receipt(3, "3 bags cement")], "Ready.")  # the last line's site
    assert [e["body"].get("site_id") for e in (await _state(h))["pending"]] == [TOWER, MITHILASH, MITHILASH]


# -- guards -----------------------------------------------------------------------------------------------------

async def test_guard_a_new_request_with_nothing_waiting_drops_the_pick() -> None:
    h = Harness(FakeToolCallingProvider(["Ok."]))
    await _ask_site_first(h)
    await _turn(h, "Tower A", "Ethra bag?")
    await _turn(h, "how many sites does the Rana Mart project have in total right now please tell me", "3 sites.")
    assert "site_pick" not in await _state(h)


async def test_guard_cancel_drops_the_pick() -> None:
    h = Harness(FakeToolCallingProvider(["Ok."]))
    await _ask_site_first(h)
    await _turn(h, "Tower A", [_receipt(50, "50 bags cement")], "Ready.")
    batch = (await _state(h))["batch"]
    await _turn(h, "Cancel", tap=f"apiag:cancel:{batch}")
    assert "site_pick" not in await _state(h)


async def test_guard_an_old_pick_is_dropped() -> None:
    state = {"site_pick": {"site_id": TOWER, "project_id": PROJECT, "at": time.time() - wa.PICK_MAX_AGE_S - 1},
             "asked": {"question": "Ethra bag?", "options": []}}
    assert wa._keep_pick("50", state, [], wa.places_of(_ctx())) is None and "site_pick" not in state


def test_guard_a_single_site_is_never_asked_and_a_named_site_wins() -> None:
    one = Places(projects=((PROJECT, "P"),), sites=((TOWER, "Tower A", PROJECT),))
    assert decide_site("50 bag cement", one, None, None, None) == Place(TOWER, PROJECT, "Tower A")
    three = wa.places_of(_ctx())
    picked = Places(three.projects, three.sites, None, (), Place(TOWER, PROJECT, "Tower A"))
    assert working_place(picked, []) == Place(TOWER, PROJECT, "Tower A")
    assert decide_site("4 bag Mithilashil", picked, None, None, working_place(picked, [])).site_id == MITHILASH


def test_guard_a_pick_is_only_an_answer_to_the_site_question() -> None:
    places = wa.places_of(_ctx())
    assert picked_site("Tower A", SITE_Q, places) == Place(TOWER, PROJECT, "Tower A")
    assert picked_site("Tower A", {"question": "Ethra bag?", "options": []}, places) is None  # not the site question
    assert picked_site("Other", {**SITE_Q, "options": [*SITE_Q["options"], "Other"]}, places) is None


def test_unit_named_reads_a_malayalam_ending_but_not_another_word() -> None:
    assert _named("Mithilash", "mithilashil aanu") and _named("Tower A", "tower a-il ethi")
    assert _named("Rana Mart", "rana martinu") and _named("Mithilash", "മിഥിലാഷ്") is False
    assert not _named("Tower", "towers") and not _named("Rana Mart", "rana martha")
