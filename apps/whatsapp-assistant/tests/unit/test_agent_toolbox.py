"""Request [40]: running tool calls -- results, parking, limits, in-flight saves."""

from __future__ import annotations

import asyncio

import pytest

from channel.replies import ReplySpec
from runtime.agent import toolbox as tb
from runtime.agent.gateway import StepResult
from runtime.agent.tools import ScopeLookup

WORKERS = [{"trade": "mason", "headcount": 3}]


class FakeGateway:
    def __init__(self, *results: StepResult, delay: float = 0.0) -> None:
        self.results = list(results)
        self.runs: list = []
        self.undo_calls = 0
        self.delay = delay

    async def run(self, candidate, *, text):
        self.runs.append(candidate)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.results.pop(0)

    async def undo_latest_draft(self):
        self.undo_calls += 1
        return self.results.pop(0)

    async def finish(self):
        return None


def _box(*results, delay=0.0, user_text="the note"):
    gateway = FakeGateway(*results, delay=delay)
    return tb.AgentToolbox(gateway, ScopeLookup(), user_text), gateway


async def test_a_saved_record_is_remembered_and_reported_to_the_model():
    box, _ = _box(StepResult("saved", text="Labour recorded"))
    out = await box.handle("save_labour", {"workers": WORKERS})
    assert out.content == {"status": "saved", "note": "Labour recorded"}
    assert [i.text for i in box.saved] == ["Labour recorded"]
    assert box.attempted_writes == 1


async def test_the_bare_recorded_line_is_not_given_to_the_model():
    """B-9: the model copied "Recorded. Thank you." onto every line, or sent it
    alone; only what else the pipeline said (the draft note) reaches it."""
    box, _ = _box(
        StepResult("saved", text="✅ Recorded. Thank you.\n\nSaved as a draft for tonight's report.")
    )
    out = await box.handle("save_labour", {"workers": WORKERS})
    assert out.content == {"status": "saved", "note": "Saved as a draft for tonight's report."}
    box, _ = _box(StepResult("saved", text="✅ Recorded. Thank you."))
    assert (await box.handle("save_labour", {"workers": WORKERS})).content == {"status": "saved"}
    # The fallback reply still has the pipeline's full words.
    assert box.saved[0].text == "✅ Recorded. Thank you."


async def test_the_same_save_twice_in_one_message_runs_once():
    box, gateway = _box(StepResult("saved", text="ok"))
    await box.handle("save_labour", {"workers": WORKERS})
    again = await box.handle("save_labour", {"workers": WORKERS})
    assert again.content["status"] == "duplicate_ignored"
    assert len(gateway.runs) == 1
    assert len(box.saved) == 1


async def test_a_gate_question_parks_the_turn_and_holds_the_rest():
    gate = ReplySpec(text="Which material?", list_rows=())
    box, gateway = _box(StepResult("needs_answer", text="Which material?", reply=gate))
    first = await box.handle("save_material_usage", {"material": "x", "quantity": 1, "unit": "u"})
    assert first.content["status"] == "waiting_for_user"
    assert box.parked is gate and box.parked_by == "gate"
    later = await box.handle("save_labour", {"workers": WORKERS})
    assert later.content["status"] == "held"
    assert len(gateway.runs) == 1  # the second never reached the pipeline
    assert box.held == ["save_labour"]


async def test_the_models_own_question_does_not_stop_the_other_parts():
    box, gateway = _box(StepResult("saved", text="Labour recorded"))
    asked = await box.handle("ask_user", {"question": "Which site?", "options": ["A", "B"]})
    assert asked.content["status"] == "question_sent"
    assert box.parked_by == "ask"
    saved = await box.handle("save_labour", {"workers": WORKERS})
    assert saved.content["status"] == "saved"
    assert len(gateway.runs) == 1


async def test_only_one_question_per_message():
    box, _ = _box()
    await box.handle("ask_user", {"question": "One?"})
    second = await box.handle("ask_user", {"question": "Two?"})
    assert second.content["status"] == "skipped"
    assert box.parked.text == "One?"


def test_up_to_three_options_become_buttons_more_become_a_list():
    three = tb.question_reply("Which?", ["A", "B", "C"])
    assert [b.title for b in three.buttons] == ["A", "B", "C"] and not three.list_rows
    five = tb.question_reply("Which?", list("ABCDE"))
    assert len(five.list_rows) == 5 and not five.buttons
    assert tb.question_reply("Which?", []).buttons is None


def test_long_option_titles_fit_whatsapp():
    reply = tb.question_reply("Which?", ["A very long site name that WhatsApp would refuse"])
    assert not reply.buttons  # too long for a button: a list row, title cut between words
    assert len(reply.list_rows[0].title) <= 24
    assert reply.list_rows[0].description.startswith("A very long site name")


def test_mat_stale_button_a_long_answer_is_never_cut_in_the_middle():
    """Live 24 Oct: the option "The amount in cubic meters" came out as the button
    "The amount in cubic". Short options stay buttons; the rest become a list
    that keeps the whole option."""
    short = tb.question_reply("Which?", ["2", "3", "Other"])
    assert [b.title for b in short.buttons] == ["2", "3", "Other"]
    long_ = tb.question_reply("How much?", ["The amount in cubic meters", "1 load = how many cum"])
    assert not long_.buttons and len(long_.list_rows) == 2
    assert long_.list_rows[0].description == "The amount in cubic meters"
    assert all(len(row.title) <= 24 for row in long_.list_rows)


async def test_a_query_answer_is_kept_for_the_reply():
    box, _ = _box(StepResult("answer", text="12 workers today"))
    out = await box.handle("query_labour", {})
    assert out.content == {"status": "answer", "text": "12 workers today"}
    assert box.answers == ["12 workers today"]
    assert box.attempted_writes == 0


async def test_a_failing_tool_is_reported_to_the_model_not_raised():
    class Boom(FakeGateway):
        async def run(self, candidate, *, text):
            raise RuntimeError("db down")

    box = tb.AgentToolbox(Boom(), ScopeLookup(), "x")
    out = await box.handle("save_labour", {"workers": WORKERS})
    assert out.content["status"] == "error"
    assert box.saved == []


async def test_undo_without_a_card_never_falls_back_to_the_latest_record():
    # Request 90: "undo that" only ever names the entries of the sender's latest
    # card; a gateway with no card to go by removes nothing.
    box, gateway = _box(StepResult("undone", text="Removed your last update"))
    out = await box.handle("undo_last", {})
    assert gateway.undo_calls == 0
    assert out.content["status"] == "info"
    assert box.saved == []  # an undo is not a saved record


async def test_a_call_flood_is_cut_off():
    results = [StepResult("saved", text=str(i)) for i in range(tb.MAX_CALLS)]
    box, _ = _box(*results)
    for i in range(tb.MAX_CALLS):
        await box.handle("save_work_done", {"narrative": f"n{i}"})
    over = await box.handle("save_work_done", {"narrative": "one too many"})
    assert over.content["status"] == "skipped"


async def test_a_save_in_flight_when_the_loop_is_cut_off_still_finishes():
    box, _ = _box(StepResult("saved", text="Labour recorded"), delay=0.05)
    caller = asyncio.ensure_future(box.handle("save_labour", {"workers": WORKERS}))
    await asyncio.sleep(0.01)
    caller.cancel()  # the model loop's deadline
    try:
        await caller
    except asyncio.CancelledError:
        pass
    await box.settle()
    assert [i.text for i in box.saved] == ["Labour recorded"]


async def test_laps_split_the_models_time_from_the_tools():
    """B-7: before a call is the model's time, inside it the tool's."""
    laps: list[str] = []
    box, _ = _box(StepResult("saved", text="ok"))
    box.lap = laps.append
    await box.handle("save_labour", {"workers": WORKERS})
    assert laps == ["agent_model", "agent_tools"]


# -- Ilan, 21 Oct: a question goes to the engineer only when they ask for it ---


@pytest.mark.parametrize(
    "text",
    ["nale slab-inu cement mathiyo?", "is there enough cement for tomorrow's slab?", "10 bag balance und"],
)
async def test_a_question_they_did_not_ask_to_pass_on_is_answered_not_passed(text):
    # WA-52: a stock question gets the stock looked up with the refusal.
    gateway = FakeGateway(StepResult("answer", text="Cement: 368 bags in stock"))
    box = tb.AgentToolbox(gateway=gateway, scope=ScopeLookup(), user_text=text)
    out = await box.handle("note_for_engineer", {"question": text})
    assert out.content["status"] == "not_asked_to_pass_on"
    assert box.saved == []
    assert all(run.semantic_type.value == "inventory_query" for run in gateway.runs)


@pytest.mark.parametrize(
    "text",
    [
        "engineer-inodu chodikku: nale slab cheyyamo?",
        "ask the engineer if we can remove the props",
        "എഞ്ചിനീയറോട് ചോദിക്കൂ, നാളെ സ്ലാബ് ചെയ്യാമോ?",
    ],
)
async def test_a_question_they_asked_to_pass_on_goes_to_the_engineer(text):
    gateway = FakeGateway(StepResult("saved", text="noted", summary="Question for your engineer: x"))
    box = tb.AgentToolbox(gateway=gateway, scope=ScopeLookup(), user_text=text)
    out = await box.handle("note_for_engineer", {"question": "nale slab cheyyamo?"})
    # Request 104: a Send card is prepared; nothing has gone yet.
    assert out.content["status"] == "saved" and "Nothing is sent yet" in out.content["instruction"]
    assert len(gateway.runs) == 1


async def test_a_yes_to_the_offer_to_ask_the_engineer_passes_it_on():
    gateway = FakeGateway(StepResult("saved", text="noted", summary="Question for your engineer: x"))
    box = tb.AgentToolbox(gateway=gateway, scope=ScopeLookup(), user_text="yes", engineer_offered=True)
    out = await box.handle("note_for_engineer", {"question": "nale slab cheyyamo?"})
    assert out.content["status"] == "saved" and "Nothing is sent yet" in out.content["instruction"]


async def test_mat07_a_message_that_says_it_arrived_is_never_asked_received_or_used():
    box, _ = _box(StepResult("saved", text="Saved"), user_text="50 bags cement arrived")
    out = await box.handle("ask_user", {"question": "Received or used?", "options": ["Received", "Used"]})
    # Live 29 Oct (runtime/agent/reroute.py): the receipt is made from their words, in the
    # same turn, instead of telling the model to make it.
    assert out.content["status"] == "saved" and "save_material_receipt" in box.called
    assert box.parked is None and box.attempted_writes == 1
    # a "used" save for the same words goes to the receipt tool: the same receipt, not a second
    out = await box.handle("save_material_usage", {"material": "cement", "quantity": 50, "unit": "bags"})
    assert out.content["status"] == "duplicate_ignored"
    assert box.attempted_writes == 1


async def test_mat07_a_used_save_for_arrived_material_is_saved_as_received():
    box, _ = _box(StepResult("saved", text="Saved"), user_text="cement vannu 50 bag")
    out = await box.handle("save_material_usage", {"material": "cement", "quantity": 50, "unit": "bags"})
    assert out.content["status"] == "saved"
    assert "save_material_receipt" in box.called and box.attempted_writes == 1


@pytest.mark.parametrize(
    "text,received,used",
    [
        ("50 bags cement arrived", True, False),
        ("cement vannu 50 bag", True, False),
        ("50 bag cement came", True, False),
        ("20 bags cement used for slab", False, True),
        ("cement 20 bag use aayi", False, True),
        ("sand came, 2 loads used already", False, False),
        ("50 bags cement", False, False),
    ],
)
def test_mat07_the_words_that_settle_the_direction(text, received, used):
    from runtime.agent.material_direction import says_received, says_used

    assert (says_received(text), says_used(text)) == (received, used)


async def test_mat07_a_message_with_no_direction_word_is_still_asked():
    box, _ = _box(StepResult("saved", text="Saved"), user_text="50 bags cement")
    out = await box.handle("ask_user", {"question": "Received or used?", "options": ["Received", "Used"]})
    assert out.content["status"] != "not_asked"


async def test_mat08_a_material_question_without_options_gets_buttons():
    box, _ = _box(user_text="cement vannu")
    await box.handle("ask_user", {"question": "How many bags of cement came?"})
    assert [r.title for r in box.parked.list_rows] == ["10", "25", "50", "Other"]
    box, _ = _box(user_text="50 bags cement")
    await box.handle("ask_user", {"question": "Received or used?"})
    assert [b.title for b in box.parked.buttons] == ["Received", "Used", "Cancel"]
    # the model's own options are kept; a question that is not about material gets none
    box, _ = _box(user_text="cement vannu")
    await box.handle("ask_user", {"question": "How many?", "options": ["5", "6"]})
    assert [b.title for b in box.parked.buttons] == ["5", "6"]
    box, _ = _box(user_text="5 workers today")
    await box.handle("ask_user", {"question": "How many were masons?"})
    assert not box.parked.buttons and not box.parked.list_rows
