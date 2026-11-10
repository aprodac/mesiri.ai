"""[277] (7 Nov, New India, a Manglish voice note: "add it, and 100 bags of cement have been unloaded there, add that to
the stock"; again on the test company, 10 Nov: only the project was held and Mesiri asked which site): an update said
in the same message as a new project is about that project. The code holds it on the project being created
(``new-project:<name>``); Save creates the project and its first site, then the update, with the real ids.
"""

from __future__ import annotations

import uuid

from tests.agent_api.standin import PROJECT, SITE
from tests.agent_api.test_api_understood_265 import ADMIN, KERALA, PLACES, _api, _tools

from agent_api.agent import NEW_PROJECT, SITE_OF, ApiAgent, confirm
from agent_api.client import ApiClient
from agent_api.tools import CONFIRM_ARG
from mesiri_ai.fakes import FakeToolCallingProvider

_NEW = ("create_project", {"name": "Hospital", CONFIRM_ARG: "New project Hospital"})


def _issue(title: str, line: str) -> tuple[str, dict]:
    # The model picks the site it knows (the one that got the cement on 7 Nov): the code decides, not the model.
    return ("report_issue", {"project_id": PROJECT, "site_id": SITE, "title": title, CONFIRM_ARG: line})


async def _run(text: str, *calls: tuple[str, dict]):  # noqa: ANN202
    seen: list[tuple[str, str, dict]] = []
    app = _api(seen)
    client = ApiClient(ADMIN, app=app)
    turn = await ApiAgent(FakeToolCallingProvider([list(calls), "Ready."]), _tools(app)).run(client, text, places=PLACES)
    return turn, client, seen


async def test_the_reported_update_goes_on_the_project_made_in_the_same_message() -> None:
    turn, client, seen = await _run("puthiya project add cheyyu, peru Hospital. athil drawings kittiyittilla",
                                    _NEW, _issue("Drawings not received", "Drawings not received"))
    try:
        project, issue = turn.pending
        assert issue.body["site_id"] == f"{SITE_OF}{NEW_PROJECT}Hospital"
        assert issue.body["project_id"] == f"{NEW_PROJECT}Hospital"
        assert issue.summary.endswith("📍 *Hospital* (new project)")
        results = await confirm(client, [issue, project])  # whatever the order on the card, the project comes first
    finally:
        await client.close()
    assert all(r.ok for r in results)
    assert [p for _m, p, _b in seen] == ["/projects", f"/projects/{KERALA}/sites", "/progress/issues"]
    saved = seen[-1][2]
    assert saved["project_id"] == KERALA and uuid.UUID(saved["site_id"]) and saved["site_id"] != SITE


async def test_sibling_two_updates_for_the_new_project_both_go_on_it() -> None:
    turn, client, seen = await _run("New project Hospital. No drawings there, and the road to it is blocked",
                                    _NEW, _issue("Drawings not received", "Drawings not received"),
                                    _issue("Road blocked", "Road blocked"))
    try:
        results = await confirm(client, turn.pending)
    finally:
        await client.close()
    assert all(r.ok for r in results)
    issues = [b for _m, p, b in seen if p == "/progress/issues"]
    assert len(issues) == 2 and {i["project_id"] for i in issues} == {KERALA}
    assert [p for _m, p, _b in seen].count(f"/projects/{KERALA}/sites") == 1  # one first site, not one a line


async def test_guard_an_update_that_names_a_site_that_exists_stays_there() -> None:
    turn, client, _seen = await _run("New project Hospital. Banglore: drawings not received",
                                     _NEW, _issue("Drawings not received", "Drawings not received, Banglore"))
    await client.close()
    issue = turn.pending[1]
    assert issue.body["site_id"] == SITE and issue.body["project_id"] == PROJECT


async def test_guard_a_later_message_never_goes_to_a_project_made_earlier() -> None:
    # [215]: with no project made in THIS message, the old rule decides (their site today, or the question).
    turn, client, _seen = await _run("drawings not received", _issue("Drawings not received", "Drawings not received"))
    await client.close()
    assert not any(NEW_PROJECT in str(e.body.get("site_id")) for e in turn.pending)


async def test_the_line_says_so_when_the_project_could_not_be_made() -> None:
    turn, client, seen = await _run("New project Hospital. No drawings there",
                                    _NEW, _issue("Drawings not received", "Drawings not received"))
    try:
        [result] = await confirm(client, [turn.pending[1]])  # the project's own line is gone (cancelled / refused)
    finally:
        await client.close()
    assert not result.ok and result.status == 424 and "Hospital" in str(result.body)
    assert not [p for _m, p, _b in seen if p == "/progress/issues"]  # never saved somewhere else instead


async def test_the_model_is_told_with_the_project_that_its_update_goes_on_it() -> None:
    # Live, 10 Nov: with only the SOP line the model held the project and asked which site the cement went to.
    turn, client, _seen = await _run("New project Hospital. No drawings there", _NEW)
    await client.close()
    note = turn.calls[0]["result"]["note"]
    assert "prepared now, in this turn" in note and "Hospital" in note and "Never ask which site" in note
