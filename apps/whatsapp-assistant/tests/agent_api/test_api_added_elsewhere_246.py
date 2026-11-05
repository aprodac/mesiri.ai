"""[246] (4 Nov 20:59, a test company: Save of a card with "Add Cement" + "50 bags Cement" refused both, because Cement
had been added to the list elsewhere while the card waited: the API's 409 carried no id, so the line could not go on
it). The 409 now carries the existing material's id beside its message, and Save puts the line on that material.

Guards: a 409 without an id (an older API) still fails the add and its line, as before; another refusal of an add is
unchanged; the message of the 409 is unchanged (the dashboard shows it).
"""

from __future__ import annotations

from fastapi import Depends
from fastapi.responses import JSONResponse
from tests.agent_api.standin import ACTOR, BAG, CEMENT, PROJECT, SITE, stand_in_api

from agent_api.agent import NEW, PendingWrite, confirm
from agent_api.client import ApiClient, new_idempotency_key
from mesiri.domains.shared.auth import get_current_user

DETAIL = "A Material named 'Cement' already exists. Use that one instead."


def _app(seen: list, *, with_id: bool = True, status: int = 409):  # noqa: ANN202
    app = stand_in_api(seen)

    @app.post("/materials")
    async def add(body: dict, jwt: dict = Depends(get_current_user)):
        content = {"detail": DETAIL if status == 409 else "Only an admin can add materials"}
        if with_id and status == 409:
            content["existing_id"] = CEMENT
        return JSONResponse(status_code=status, content=content)

    return app


def _card() -> list[PendingWrite]:
    add = PendingWrite("add_material", "POST", "/materials", {}, {"name": "Cement", "default_unit_id": BAG},
                       "➕ Add Cement", new_idempotency_key())
    line = PendingWrite("record_receipt", "POST", "/materials/inflows", {},
                        {"project_id": PROJECT, "site_id": SITE, "material_id": f"{NEW}Cement", "unit_id": BAG,
                         "quantity": 50, "occurred_date": "2026-11-04"},
                        "50 bags Cement", new_idempotency_key())
    return [add, line]


async def _save(app) -> list:  # noqa: ANN001
    client = ApiClient(ACTOR, app=app)
    try:
        return await confirm(client, _card())
    finally:
        await client.close()


async def test_a_material_added_elsewhere_takes_the_cards_line() -> None:
    seen: list = []
    added, line = await _save(_app(seen))
    assert added.ok and added.body["id"] == CEMENT
    assert line.ok and line.status == 201
    assert ("POST", "/materials/inflows") in [(m, p) for m, p, *_ in seen]


async def test_guard_a_409_with_no_id_fails_as_before() -> None:
    added, line = await _save(_app([], with_id=False))
    assert added.status == 409 and not line.ok and line.status == 424


async def test_guard_another_refusal_of_the_add_is_unchanged() -> None:
    added, line = await _save(_app([], status=403))
    assert added.status == 403 and not line.ok



def test_the_saved_line_says_it_was_already_listed() -> None:
    from agent_api.agent import WriteResult
    from agent_api.whatsapp import _saved_text

    add, line = _card()
    text = _saved_text([WriteResult(add, 200, {"id": CEMENT, "already_listed": True}),
                        WriteResult(line, 201, {"id": "x"})])
    assert "✅ ➕ Add Cement (already in your list)" in text and "✅ 50 bags Cement" in text
