"""WA-141 / WA-142: v3 sends dashboard links (built by the code) and offers the dashboard's
corrections and set-up as writes held for Save.

Guards: a link is never written by the model (an unknown page or a bad id is refused, the address
comes from the table); a link the code built reaches the person even if the model left it out; the
new routes are all writes (held for Save); nothing that grants access is on the list.
"""

from __future__ import annotations

import uuid

import pytest
from tests.agent_api.standin import ACTOR, PROJECT, SITE, stand_in_api

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.links import PAGES, build_link
from agent_api.tools import ALLOWED
from mesiri_ai.fakes import FakeToolCallingProvider

TODAY = "2026-11-02"


def test_a_site_day_link_defaults_to_today(monkeypatch) -> None:
    monkeypatch.delenv("MESIRI_DASHBOARD_URL", raising=False)
    got = build_link({"page": "site_day", "site_id": SITE}, today=TODAY)
    assert got["url"] == f"https://app.whatsapp.mesiri.ai/reports/{TODAY}/sites/{uuid.UUID(SITE)}"


@pytest.mark.parametrize("arguments", [
    {"page": "admin"},                                        # not a page
    {"page": "project", "project_id": "../../etc"},           # not an id
    {"page": "site_day", "site_id": SITE, "date": "today"},   # not a date
    {"page": "expense"},                                      # id missing
])
def test_guard_the_model_cannot_shape_the_address(arguments) -> None:
    assert "error" in build_link(arguments, today=TODAY)


def test_every_page_without_ids_builds(monkeypatch) -> None:
    monkeypatch.setenv("MESIRI_DASHBOARD_URL", "https://staging.example/")
    for page, (path, _) in PAGES.items():
        if "{" not in path:
            assert build_link({"page": page}, today=TODAY)["url"] == "https://staging.example" + path


async def test_the_link_reaches_the_person_even_when_the_model_leaves_it_out() -> None:
    app = stand_in_api([])
    model = FakeToolCallingProvider([
        [("web_link", {"page": "project", "project_id": PROJECT})],
        "Here is the project page.",
    ])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(model, {}).run(client, "send me the project link")
    finally:
        await client.close()
    assert turn.reply.startswith("Here is the project page.")
    assert f"/projects/{uuid.UUID(PROJECT)}" in turn.reply and turn.pending == []


NEW = {"work_item", "correct_work", "acknowledge_issue", "wont_fix_issue", "undo_receipt", "undo_usage",
       "undo_transfer", "undo_expense", "add_material", "update_material", "add_expense_category",
       "create_project", "update_project", "add_site", "update_site"}


def test_the_new_routes_are_on_the_list_and_writes_wait_for_save() -> None:
    by_name = {a.name: a for a in ALLOWED}
    assert NEW <= set(by_name)
    assert all(by_name[n].method != "GET" for n in NEW - {"work_item"})


def test_guard_nothing_that_grants_access_is_on_the_list() -> None:
    # [207]: the owner-approved exceptions, adding a person to a project (POST only): someone already in the
    # company, and (WEB-71, Ilan 6 Nov) someone new by name and WhatsApp number.
    approved = {("POST", "/projects/{project_id}/members"), ("POST", "/projects/{project_id}/members/by-number")}
    paths = {a.path for a in ALLOWED if (a.method, a.path) not in approved}
    assert not any(p.startswith("/users") or p.endswith("/members") or "/members/" in p for p in paths)
    assert not any(a.method == "DELETE" for a in ALLOWED)
    assert "/organizations/settings" not in paths  # modules: platform admins only (WA-144)
