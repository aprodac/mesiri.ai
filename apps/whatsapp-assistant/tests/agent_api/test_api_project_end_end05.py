"""END-05 / END-06 (8 Nov 2026): the end of a project on WhatsApp through the dashboard's own routes.

"Bedroom 2 tile chipped near the door, tiler" is one `raise_snag` held for Save; two snags in one message are two
lines. "What snags are open?" only reads. "Client paid 6 lakh for RA-3" is one `client_payment` held for Save.
Guards: a snag never skips Save; money from the client is never a supplier payment; work stopped today stays an
issue (the SOP); closing a snag is not on the list (the PM checks it on the dashboard).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.receipts import kind_of
from agent_api.record_links import RECORD_PAGES, record_link
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

PROJECT = str(uuid.uuid4())
SNAG = str(uuid.uuid4())
NAMES = {"snags": ("GET", "/snags"), "raise_snag": ("POST", "/projects/{project_id}/snags"),
         "snag_fixed": ("POST", "/snags/{snag_id}/fixed"), "receivables": ("GET", "/billing/receivables"),
         "client_payment": ("POST", "/projects/{project_id}/client-payments")}


class SnagIn(BaseModel):
    description: str | None = None
    place: str | None = None
    trade: str | None = None


class PaymentIn(BaseModel):
    kind: str = "bill"
    bill_ref: str | None = None
    amount: Decimal


def _app(read: list, saved: list) -> FastAPI:
    app = FastAPI()

    @app.get("/snags")
    async def snags(project_id: str | None = None, status: str | None = None, jwt: dict = Depends(get_current_user)):
        read.append(("snags", status))
        return {"snags": [{"id": SNAG, "ref": "SN-004", "place": "Bedroom 2", "description": "Tile chipped",
                           "status": "open"}], "counts": {"open": 1, "fixed": 0, "closed": 3}}

    @app.post("/projects/{project_id}/snags", status_code=201)
    async def raise_snag(project_id: str, body: SnagIn, jwt: dict = Depends(get_current_user)):
        saved.append(body)
        return {"id": SNAG, "ref": "SN-005", "project_id": project_id}

    @app.post("/projects/{project_id}/client-payments", status_code=201)
    async def pay(project_id: str, body: PaymentIn, jwt: dict = Depends(get_current_user)):
        saved.append(body)
        return {"payment": {"amount": str(body.amount)}, "receivable": {"outstanding": "527160.00"}}

    return app


async def _turn(script: list, text: str, names: tuple[str, ...]):  # noqa: ANN202
    read: list = []
    saved: list = []
    app = _app(read, saved)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in names))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), read, saved
    finally:
        await client.close()


def test_the_end_of_project_tools_are_the_dashboards_routes() -> None:
    tools = _real_tools()
    assert {n: (tools[n].method, tools[n].path) for n in NAMES} == NAMES
    assert [n for n in NAMES if tools[n].is_write] == ["raise_snag", "snag_fixed", "client_payment"]
    assert "vendor_id" not in tools["raise_snag"].body_fields and "bill_id" not in tools["client_payment"].body_fields
    assert {"description", "place", "trade"} <= set(tools["raise_snag"].body_fields)
    assert {"amount", "bill_ref", "kind"} <= set(tools["client_payment"].body_fields)
    assert (kind_of("raise_snag"), kind_of("snag_fixed"), kind_of("client_payment")) == ("snag", "snag", "payment")
    assert (RECORD_PAGES["raise_snag"], RECORD_PAGES["client_payment"]) == ("snags", "payments_received")


def test_guard_closing_or_removing_a_snag_or_a_payment_is_not_a_tool() -> None:
    paths = {(a.method, a.path) for a in ALLOWED}
    assert not {("POST", "/snags/{snag_id}/close"), ("POST", "/snags/{snag_id}/reopen"),
                ("DELETE", "/snags/{snag_id}"), ("DELETE", "/billing/payments/{payment_id}")} & paths


def test_a_fixed_snag_links_to_its_projects_snag_list_from_the_answer() -> None:
    link = record_link("snag_fixed", f"/snags/{SNAG}/fixed", {"note": "replaced"},
                       {"id": SNAG, "project_id": PROJECT}, today="2026-11-08")
    assert link and f"/site/snags?project={PROJECT}" in link


async def test_two_snags_in_one_message_are_two_lines_held_for_save() -> None:
    one = ("raise_snag", {"project_id": PROJECT, "description": "Tile chipped near the door", "place": "Bedroom 2",
                          "trade": "tiler", CONFIRM_ARG: "Bedroom 2: tile chipped near the door (tiler)"})
    two = ("raise_snag", {"project_id": PROJECT, "description": "Tap leaking", "place": "First floor toilet",
                          "trade": "plumber", CONFIRM_ARG: "First floor toilet: tap leaking (plumber)"})
    turn, _, saved = await _turn([[one, two], "Ready."],
                                 "bedroom 2 tile chipped near the door, tiler. first floor toilet tap leaking, plumber",
                                 ("raise_snag",))
    assert saved == []  # held until Save
    assert [(p.tool, p.body["place"]) for p in turn.pending] == [("raise_snag", "Bedroom 2"),
                                                                  ("raise_snag", "First floor toilet")]


async def test_guard_what_snags_are_open_only_reads() -> None:
    turn, read, saved = await _turn([[("snags", {"project_id": PROJECT, "status": "pending"})],
                                     "1 open: SN-004 Bedroom 2, tile chipped."], "ethra snag baaki?", ("snags",))
    assert read == [("snags", "pending")] and turn.pending == [] and saved == []


async def test_client_paid_six_lakh_for_ra3_is_one_payment_held_for_save() -> None:
    pay = ("client_payment", {"project_id": PROJECT, "amount": 600000, "bill_ref": "RA-3",
                              CONFIRM_ARG: "Client paid ₹6,00,000 for RA-3"})
    turn, _, saved = await _turn([[pay], "Ready."], "client paid 6 lakh for RA-3", ("client_payment",))
    assert saved == []
    assert [(p.tool, p.body["bill_ref"], p.body["amount"]) for p in turn.pending] == [("client_payment", "RA-3", 600000)]


def test_the_sop_keeps_snags_issues_and_client_money_apart() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
    assert "17. The end of a project." in sop
    assert "stays `report_issue`, never a snag" in sop
    assert "is never `pay_supplier` or\n   an expense: it is `client_payment` (rule 17)" in sop
    assert "never say a snag is closed" in sop
    assert "never that it was recorded" in sop
