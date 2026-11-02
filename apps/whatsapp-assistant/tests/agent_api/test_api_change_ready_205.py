"""[205] (Paraclette, 2 Nov): a project prepared by voice ("Maatt") was renamed by the next voice note ("Rana Mart");
the model dropped the waiting entry, never prepared it again, and still said "ready": Save created nothing. Its
replies also showed the memory's own note "(under this reply, waiting for the Save button: ...)".

A correction to a waiting entry is now one step the code applies in place (``change_ready_entry``), and the note
never reaches WhatsApp.
"""

from __future__ import annotations

from tests.agent_api.standin import ACTOR, NOS, stand_in_api, stand_in_tools
from tests.agent_api.test_api_agent_119 import _two_waiting

from agent_api import whatsapp as wa
from agent_api.agent import CHANGE_READY, ApiAgent
from agent_api.client import ApiClient
from mesiri_ai.fakes import FakeToolCallingProvider


async def _run(model, ready, app, text="alla, 40 bag"):  # noqa: ANN001, ANN202
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(model, stand_in_tools(app)).run(client, text, ready=ready)
    finally:
        await client.close()


async def test_a_correction_changes_the_waiting_entry_in_place() -> None:
    seen: list = []
    app = stand_in_api(seen)
    ready = await _two_waiting(app)
    model = FakeToolCallingProvider([
        [(CHANGE_READY, {"number": 1, "changes": {"quantity": 40}, "confirm_line": "40 bags cement, Green Villa"})],
        "Changed to 40 bags.",
    ])
    turn = await _run(model, ready, app)
    assert [e.summary for e in turn.pending] == ["40 bags cement, Green Villa", "50 TMT bars, Green Villa"]
    assert turn.pending[0].body["quantity"] == 40 and turn.pending[0].body["material_id"] == ready[0].body["material_id"]
    assert turn.pending[0].idempotency_key != ready[0].idempotency_key  # a changed entry is a new write
    assert turn.saved == [] and [m for m, *_ in seen].count("POST") == 0
    # The model sees each waiting entry's fields, so it can name the one that changes.
    assert '"quantity": 50' in model.last_system_prompt


async def test_sibling_a_new_unit_is_settled_like_a_new_entry() -> None:
    app = stand_in_api([])
    ready = await _two_waiting(app)
    model = FakeToolCallingProvider([
        [(CHANGE_READY, {"number": 2, "changes": {"unit_id": "bars"}, "confirm_line": "50 TMT bars (nos), Green Villa"})],
        "Changed.",
    ])
    turn = await _run(model, ready, app, "unit is nos")
    assert turn.pending[1].body["unit_id"] in (NOS, str(NOS))


async def test_guard_an_unknown_field_or_entry_changes_nothing() -> None:
    app = stand_in_api([])
    ready = await _two_waiting(app)
    model = FakeToolCallingProvider([
        [(CHANGE_READY, {"number": 1, "changes": {"colour": "red"}, "confirm_line": "x"}),
         (CHANGE_READY, {"number": 9, "changes": {"quantity": 1}, "confirm_line": "y"})],
        "Sorry.",
    ])
    turn = await _run(model, ready, app)
    assert [e.summary for e in turn.pending] == [e.summary for e in ready]
    errors = [c["result"]["error"] for c in turn.calls]
    assert "cannot change colour" in errors[0] and "no waiting entry 9" in errors[1]


def test_the_memory_note_never_reaches_whatsapp() -> None:
    copied = ("Rana Mart project is ready to create.\n(under this reply, waiting for the Save button: "
              "Create project Rana Mart; 10 TMT steel bars used at Tower A)")
    assert wa.without_ready_block(copied) == "Rana Mart project is ready to create."
    # The memory still keeps the list as its short note (WA-130), from a drawn list.
    kept = wa.for_memory("Ready.\n\n*Ready to save:*\n1. 50 bags cement")
    assert kept.endswith("(under this reply, waiting for the Save button: 50 bags cement)")
    assert wa.for_memory("Hello.") == "Hello."


def test_the_drop_tool_is_for_cancelling_only() -> None:
    from agent_api.agent import _READY_TOOLS

    specs = {s.name: s.description for s in _READY_TOOLS}
    assert "only when the person cancels" in specs["drop_ready_entries"]
    assert "never drop it to correct it" in specs[CHANGE_READY]
