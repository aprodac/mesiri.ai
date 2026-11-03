"""[213] (re-opens [209]; 3 Nov 09:26, Mesiri Test Builders): "Puthiya project undaakku, peru Zeta Plaza" -> Save ->
"20 bag cement vannu" was prepared at Zeta Plaza, the new and empty project; every earlier update went to Green Villa.
The model picked the site. Now the code does: the site named in this message, else the one they last reported to,
else their only site, else ask with buttons. A site other than the last one is shown on the ready line."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from tests.agent_api.standin import (
    ACTOR,
    BAG,
    CEMENT,
    ORG,
    PROJECT,
    SITE,
    USER,
    stand_in_api,
    stand_in_tools,
)

from agent_api.agent import (
    OTHER_SITE,
    ApiAgent,
    PendingWrite,
    Place,
    Places,
    WriteResult,
    decide_site,
    last_reported,
)
from agent_api.client import ApiClient
from agent_api.tools import CONFIRM_ARG
from mesiri_ai.fakes import FakeToolCallingProvider

ZETA = str(uuid.uuid4())
TOWER = str(uuid.uuid4())
GREEN = Place(SITE, PROJECT, "Green Villa main")
PLACES = Places(projects=((PROJECT, "Green Villa, Kakkanad"), (ZETA, "Zeta Plaza")),
                sites=((SITE, "Green Villa main", PROJECT),), working=GREEN)


def _receipt(project: str, line: str, site: str | None = None, quantity: int = 20) -> tuple[str, dict]:
    args = {"project_id": project, "material_id": CEMENT, "unit_id": BAG, "quantity": quantity,
            "occurred_date": "2026-11-03", CONFIRM_ARG: line}
    return ("record_receipt", {**args, **({"site_id": site} if site else {})})


async def _run(text: str, call: tuple[str, dict], places: Places | None):  # noqa: ANN202
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider([[call], "Ready."]), stand_in_tools(app)).run(
            client, text, places=places)
    finally:
        await client.close()


async def test_reported_an_update_after_creating_a_project_goes_to_the_working_site() -> None:
    turn = await _run("20 bag cement vannu", _receipt(ZETA, "20 bags Cement received at Zeta Plaza"), PLACES)
    [entry] = turn.pending
    assert entry.body["project_id"] == PROJECT and entry.body["site_id"] == SITE
    assert "📍" not in entry.summary  # the usual site: nothing extra on the line


async def test_guard_the_site_named_in_the_message_wins_and_is_shown_on_the_line() -> None:
    turn = await _run("20 bag cement vannu, Zeta Plaza site", _receipt(ZETA, "20 bags cement, Zeta Plaza", SITE), PLACES)
    [entry] = turn.pending
    assert entry.body["project_id"] == ZETA and "site_id" not in entry.body  # Zeta Plaza has no site yet
    assert entry.summary.endswith("📍 *Zeta Plaza* (not Green Villa main)")


async def test_guard_a_single_site_sender_is_unchanged() -> None:
    one = Places(projects=((PROJECT, "Green Villa"),), sites=((SITE, "Green Villa main", PROJECT),))
    call = _receipt(PROJECT, "20 bags cement", SITE)
    turn = await _run("20 bag cement vannu", call, one)
    assert turn.pending[0].body["site_id"] == SITE and turn.pending[0].summary == "20 bags cement"


async def test_several_sites_and_nothing_to_go_by_asks_with_buttons() -> None:
    two = Places(projects=((PROJECT, "Green Villa"),),
                 sites=((SITE, "Green Villa main", PROJECT), (TOWER, "Tower A", PROJECT)))
    turn = await _run("20 bag cement vannu", _receipt(PROJECT, "20 bags cement", TOWER), two)
    assert turn.pending == []
    assert turn.options == ["Green Villa main", "Tower A"]
    assert "Which site" in turn.calls[0]["result"]["error"]


def test_sibling_the_decision_and_what_counts_as_reported() -> None:
    # A status question about Zeta Plaza, then an update: no name in the update -> the working site.
    assert decide_site("20 bag cement vannu", PLACES, SITE, ZETA, GREEN) == GREEN
    assert decide_site("ZETA PLAZA il 20 bag", PLACES, None, PROJECT, GREEN) == Place(None, ZETA, "Zeta Plaza")
    assert decide_site("green villa-il 20 bag", PLACES, None, ZETA, None) == GREEN
    created = PendingWrite("create_project", "POST", "/projects", {}, {"name": "Zeta Plaza"}, "New project", "k")
    old = {"site_id": SITE, "project_id": PROJECT}
    assert last_reported([WriteResult(created, 201, {"id": ZETA})], old) == old  # creating never moves it
    receipt = PendingWrite("record_receipt", "POST", "/materials/inflows", {}, {"project_id": ZETA}, "20 bags", "k2")
    assert last_reported([WriteResult(receipt, 201, {})], old, "2026-11-03") == {
        "site_id": None, "project_id": ZETA, "date": "2026-11-03", "recent": [ZETA]}
    assert last_reported([WriteResult(receipt, 422, {})], old) == old  # refused: not reported


@pytest.fixture
def _stand_in_wa(monkeypatch):  # noqa: ANN001, ANN202
    from tests.agent_api.standin import STAND_IN_TOOLS

    from agent_api import tools as tools_mod
    from agent_api import whatsapp as wa

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


# End to end: an update at Green Villa saved, then (after Zeta Plaza was created) "20 bag cement vannu".
@pytest.mark.usefixtures("_stand_in_wa")
async def test_through_whatsapp_the_saved_site_stays_the_site_after_a_new_project() -> None:
    from tests.agent_api.test_api_agent_124 import _message, _service

    ctx = SimpleNamespace(
        user_id=USER, organization_id=ORG, role="SITE_SUPERVISOR", full_name="Ravi", timezone="Asia/Kolkata",
        projects=[SimpleNamespace(id=PROJECT, name="Green Villa, Kakkanad"), SimpleNamespace(id=ZETA, name="Zeta Plaza")],
        sites=[SimpleNamespace(id=SITE, name="Green Villa main", project_id=PROJECT)])
    service, sent = _service(FakeToolCallingProvider([[_receipt(PROJECT, "50 bags cement, Green Villa", SITE, 50)], "Ready."]))
    await service.handle(_message("50 bag cement vannu Green Villa"), ctx)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), ctx)
    working = (await service._state(ctx))["working_site"]
    assert (working["site_id"], working["project_id"], working["recent"]) == (SITE, PROJECT, [SITE])

    service._agent._provider = FakeToolCallingProvider([[_receipt(ZETA, "20 bags Cement received at Zeta Plaza")], "Ready."])
    await service.handle(_message("20 bag cement vannu"), ctx)
    [entry] = (await service._state(ctx))["pending"]
    assert entry["body"]["project_id"] == PROJECT and entry["body"]["site_id"] == SITE
    assert [b.title for b in sent[-1].buttons] == ["Save", "Cancel"]


# [215] (re-opens [209]/[212]/[213]; the [213] build never reached main). Live, 3 Nov ~09:45 IST, Mesiri Test Builders,
# asus ADMIN: material saved at Green Villa, Kakkanad at 09:04 and 09:18; "Puthiya project undaakku, peru Omega Towers"
# -> Save; "20 bag cement vannu" -> "Which project is this for? You have: Green Villa, Kakkanad / Live Check Garden /
# Live Mart B / Omega Towers / Rana Mart / Zeta Plaza" as plain text.
LIVE_IDS = {n: str(uuid.uuid4()) for n in ("Live Check Garden", "Live Mart B", "Omega Towers", "Rana Mart", "Zeta Plaza")}
LIVE = Places(projects=((PROJECT, "Green Villa, Kakkanad"), *((i, n) for n, i in LIVE_IDS.items())),
              sites=((SITE, "Green Villa, Kakkanad", PROJECT),))
GREEN_LIVE = Place(SITE, PROJECT, "Green Villa, Kakkanad")
LIVE_TODAY = Places(LIVE.projects, LIVE.sites, GREEN_LIVE, (SITE,))


async def test_live_0945_after_creating_omega_towers_the_update_goes_to_green_villa() -> None:
    turn = await _run("20 bag cement vannu", _receipt(LIVE_IDS["Omega Towers"], "20 bags cement, Omega Towers"), LIVE_TODAY)
    [entry] = turn.pending
    assert entry.body["project_id"] == PROJECT and entry.body["site_id"] == SITE and "📍" not in entry.summary


async def test_sibling_a_question_about_live_mart_b_then_an_update_goes_to_green_villa() -> None:
    # "how is Live Mart B?" was the last place mentioned; the update names no site.
    turn = await _run("20 bag cement vannu", _receipt(LIVE_IDS["Live Mart B"], "20 bags cement"), LIVE_TODAY)
    assert turn.pending[0].body["project_id"] == PROJECT and turn.pending[0].body["site_id"] == SITE


async def test_guard_omega_towers_named_in_the_message_goes_there_with_the_pin() -> None:
    turn = await _run("20 bag cement vannu, Omega Towers site", _receipt(PROJECT, "20 bags cement", SITE), LIVE_TODAY)
    [entry] = turn.pending
    assert entry.body["project_id"] == LIVE_IDS["Omega Towers"] and "site_id" not in entry.body
    assert "📍 *Omega Towers*" in entry.summary


async def test_no_site_today_asks_with_three_buttons_recent_first_and_other() -> None:
    places = Places(LIVE.projects, LIVE.sites, None, (LIVE_IDS["Rana Mart"], SITE))
    turn = await _run("20 bag cement vannu", _receipt(LIVE_IDS["Omega Towers"], "20 bags cement"), places)
    assert turn.pending == []
    assert turn.options == ["Rana Mart", "Green Villa, Kakkanad", "Live Check Garden", OTHER_SITE]


def test_adding_a_site_or_a_member_never_moves_the_working_site() -> None:
    old = {"site_id": SITE, "project_id": PROJECT, "date": "2026-11-03", "recent": [SITE]}
    add_site = PendingWrite("add_site", "POST", f"/projects/{ZETA}/sites", {}, {"name": "Block A", "site_id": "x"},
                            "New site", "k")
    member = PendingWrite("add_project_member", "POST", f"/projects/{ZETA}/members", {}, {"project_id": ZETA},
                          "Sahal", "k2")
    assert last_reported([WriteResult(add_site, 201, {}), WriteResult(member, 201, {})], old, "2026-11-03") == old


def test_only_todays_site_is_the_default_and_the_model_is_told_it() -> None:
    from agent_api import whatsapp as wa

    ctx = SimpleNamespace(timezone="Asia/Kolkata", projects=[SimpleNamespace(id=p, name=n) for p, n in LIVE.projects],
                          sites=[SimpleNamespace(id=SITE, name="Green Villa, Kakkanad", project_id=PROJECT)])
    today = {"site_id": SITE, "project_id": PROJECT, "date": wa._today(ctx), "recent": [SITE]}
    places = wa._places(ctx, today)
    assert places.working == GREEN_LIVE and places.recent == (SITE,)
    assert "Their site today: Green Villa, Kakkanad" in wa._working_fact(places)
    yesterday = wa._places(ctx, {**today, "date": "2026-11-02"})
    assert yesterday.working is None and wa._working_fact(yesterday) == ""
