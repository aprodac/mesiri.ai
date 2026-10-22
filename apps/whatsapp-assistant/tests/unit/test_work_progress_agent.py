"""Request [84] (22 Oct): the agent says what it saved -- the floor and the
status of work done, a report asked for in a mixed message, and a sentence
that speaks of every item on the card.

Only the agent's own pieces change: the tool adapter, the card renderer fed by
the tool results, the prompt, and the sentence check. The model is scripted;
the save code underneath is the real one in the replay/conversation sets.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from interactions.saved_summary import summarise_draft
from mesiri_ai.models import ToolRunResult
from mesiri_contracts.assistant.draft_action import DraftActionType
from runtime.agent import runner as r
from runtime.agent.gateway import StepResult
from runtime.agent.prompt import SYSTEM_PROMPT, AgentContext
from runtime.agent.sentence import fallback_line, items_of, missing_items
from runtime.agent.tools import ScopeLookup, check_work_done, tool_specs

CTX = AgentContext(
    user_name="Anil",
    role="SUPERVISOR",
    company="Acme Builders",
    now=datetime(2026, 10, 22, 9, 30),
    projects=(("Project Alpha", "Kochi"),),
    sites=(("Site A1", "Project Alpha"),),
)


class Gateway:
    def __init__(self, *results):
        self.results = list(results)
        self.candidates = []

    async def run(self, candidate, *, text):
        self.candidates.append(candidate)
        return self.results.pop(0)

    async def undo_latest_draft(self):
        return self.results.pop(0)

    async def finish(self):
        return None


class Scripted:
    """First call: runs ``calls`` through the handler, answers ``texts[0]``.
    Later calls (the no-tools retry): answer the next text, or fail."""

    provider = "fake"

    def __init__(self, calls, texts):
        self.calls_to_make = calls
        self.texts = list(texts)
        self.runs = 0
        self.asked: list[str] = []

    async def run_tools(self, system_prompt, messages, tools, handler, **kwargs):
        from mesiri_ai.models import ToolCallRecord

        self.runs += 1
        self.asked.append(messages[-1].text)
        records = []
        if self.runs == 1:
            for name, args in self.calls_to_make:
                records.append(ToolCallRecord(name=name, arguments=args, outcome=await handler(name, args)))
        if not self.texts:
            raise RuntimeError("no more model")
        return ToolRunResult(text=self.texts.pop(0), calls=records, steps=1, stop_reason="answered", model="fake")


async def _run(provider, *results, text="x"):
    gateway = Gateway(*results)
    result = await r.AgentRunner(provider).run(ctx=CTX, user_text=text, gateway=gateway, scope=ScopeLookup())
    return result, gateway


def _draft(action, **fields):
    return SimpleNamespace(action_type=action, fields=fields)


# -- 1. work progress: validation and the card ---------------------------------


def test_the_work_done_schema_carries_floor_status_and_percent():
    spec = next(t for t in tool_specs() if t.name == "save_work_done")
    props = spec.parameters["properties"]
    assert {"location", "update_kind", "progress_percent"} <= set(props)
    assert "completed" in props["update_kind"]["enum"] and "progress" in props["update_kind"]["enum"]
    assert "floor" in props["location"]["description"]


def test_the_adapter_accepts_a_percentage_in_range_and_none():
    assert check_work_done({"progress_percent": 70}) is None
    assert check_work_done({"progress_percent": "70%"}) is None
    assert check_work_done({"progress_percent": 0}) is None
    assert check_work_done({"progress_percent": 100, "update_kind": "completed"}) is None
    assert check_work_done({"update_kind": "completed"}) is None
    assert check_work_done({}) is None


def test_the_adapter_refuses_a_percentage_out_of_range_or_not_a_number():
    for bad in (150, -5, "lots", True):
        assert check_work_done({"progress_percent": bad}), bad


async def test_a_bad_percentage_saves_nothing_and_tells_the_model():
    provider = Scripted([("save_work_done", {"narrative": "plastering", "progress_percent": 150})], ["ok"])
    result, gateway = await _run(provider, text="plastering 150%")
    assert gateway.candidates == []
    assert result.toolbox.saved == []
    assert result.run.calls[0].outcome.content["status"] == "error"
    assert "0 to 100" in result.run.calls[0].outcome.content["message"]


def test_the_card_renders_both_formats_from_the_saved_fields():
    create = DraftActionType.CREATE_ACTIVITY
    assert (
        summarise_draft(
            _draft(create, work_type="plastering", location="2nd floor", progress_percent=70, update_kind="progress")
        )
        == "Plastering, 2nd floor: 70%"
    )
    assert (
        summarise_draft(_draft(create, work_type="slab concreting", location="3rd floor", update_kind="completed"))
        == "Slab concreting, 3rd floor (completed)"
    )
    # A stated 100% on finished work is "completed", not "100%".
    assert (
        summarise_draft(
            _draft(create, work_type="slab concreting", location="3rd floor", progress_percent=100, update_kind="completed")
        )
        == "Slab concreting, 3rd floor (completed)"
    )
    assert (
        summarise_draft(_draft(create, work_type="brickwork", location="ground floor", update_kind="started"))
        == "Brickwork, ground floor (started)"
    )
    # Unchanged: a progress update and a plain "progress" activity.
    assert summarise_draft(_draft(DraftActionType.ADD_PROGRESS_UPDATE, work_type="plastering", update_kind="completed")) == (
        "Plastering (completed)"
    )
    assert summarise_draft(_draft(create, work_type="plastering", update_kind="progress")) == "Plastering"


# -- 2. a report asked for in a mixed message ---------------------------------


async def test_a_report_in_a_mixed_message_is_one_card_and_one_report_line():
    provider = Scripted(
        [
            ("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]}),
            ("save_material_usage", {"material": "cement", "quantity": 25, "unit": "bag"}),
            ("request_dpr", {}),
        ],
        ["6 mason, 25 bag cement ok.\nDraft so far: 16 workers, cement 25 used. The items above are added when you tap Save."],
    )
    result, _ = await _run(
        provider,
        StepResult("saved", text="a", summary="6 workers (6 mason)"),
        StepResult("saved", text="b", summary="Cement used: 25 bags"),
        StepResult("answer", text="Today's report so far (draft): 16 workers, cement 25 used"),
        text="6 mason vannu, 25 bag cement use cheythu, innathe report ayakku",
    )
    report = result.run.calls[2].outcome.content
    assert report["status"] == "answer"
    assert report["waiting_for_save"] == ["6 workers (6 mason)", "Cement used: 25 bags"]
    assert "do not list them again" in report["instruction"]
    text = result.reply.text
    assert text.count("✅ Saved:") == 1  # one card
    assert text.count("Cement used: 25 bags") == 1 and text.count("6 workers (6 mason)") == 1  # no duplicate list
    assert "Draft so far: 16 workers" in text and text.count("Draft so far") == 1


async def test_a_report_alone_has_no_waiting_list():
    provider = Scripted([("request_dpr", {})], ["Here is the draft."])
    result, _ = await _run(provider, StepResult("answer", text="draft: 3 workers"), text="report ayakku")
    assert "waiting_for_save" not in result.run.calls[0].outcome.content


# -- 3. the sentence above the card speaks of every item -------------------------


def _labour_call(*lines):
    from mesiri_ai.models import ToolCallRecord, ToolOutcome

    return ToolCallRecord(
        name="save_labour", arguments={"workers": list(lines)}, outcome=ToolOutcome(content={"status": "saved"})
    )


def test_every_item_must_be_spoken_of():
    items = items_of(
        [
            _labour_call(
                {"trade": "mason", "headcount": 5},
                {"trade": "helper", "headcount": 8},
                {"trade": "electrician", "headcount": 2},
            )
        ]
    )
    assert [i.label for i in items] == ["5 mason", "8 helper", "2 electrician"]
    assert [i.label for i in missing_items("5 mason, 8 helper vannu, Save tap cheyyu", items)] == ["2 electrician"]
    assert missing_items("5 mason, 8 helper, 2 electrician. Save tap cheyyu", items) == []
    # A noun is enough when the number is spelled out, and the plural counts.
    assert missing_items("five masons, eight helpers and two electricians", items) == []


def test_a_sentence_in_another_script_is_matched_on_numbers_only():
    items = items_of([_labour_call({"trade": "mason", "headcount": 3})])
    assert missing_items("3 മേസൺ വന്നു", items) == []
    assert [i.label for i in missing_items("ശരി, നോക്കി Save അമർത്തൂ", items)] == ["3 mason"]


def test_failed_and_unspoken_tools_are_not_items():
    from mesiri_ai.models import ToolCallRecord, ToolOutcome

    failed = ToolCallRecord(name="save_labour", arguments={"workers": [{"trade": "mason"}]}, outcome=ToolOutcome(content={"status": "error"}))
    ask = ToolCallRecord(name="ask_user", arguments={"question": "?"}, outcome=ToolOutcome(content={"status": "question_sent"}))
    assert items_of([failed, ask]) == []


async def test_a_sentence_that_leaves_an_item_out_is_asked_again_once():
    provider = Scripted(
        [("save_labour", {"workers": [{"trade": "mason", "headcount": 5}, {"trade": "electrician", "headcount": 2}]})],
        ["5 mason vannu, Save tap cheyyu.", "5 mason, 2 electrician vannu, ok? Save tap cheyyu."],
    )
    result, _ = await _run(
        provider, StepResult("saved", text="a", summary="7 workers (5 mason, 2 electrician)"), text="innu 5 mason, 2 electrician vannu"
    )
    assert provider.runs == 2
    assert "leaves out: 2 electrician" in provider.asked[1]
    assert result.reply.text.startswith("5 mason, 2 electrician vannu, ok? Save tap cheyyu.\n\n✅ Saved: 7 workers")


async def test_a_second_miss_falls_back_to_a_line_from_the_tool_arguments():
    provider = Scripted(
        [("save_labour", {"workers": [{"trade": "mason", "headcount": 5}, {"trade": "electrician", "headcount": 2}]})],
        ["5 mason vannu.", "5 mason vannu, Save tap cheyyu."],
    )
    result, _ = await _run(
        provider, StepResult("saved", text="a", summary="7 workers (5 mason, 2 electrician)"), text="innu 5 mason, 2 electrician vannu"
    )
    assert provider.runs == 2  # one retry, no more
    assert result.reply.text.startswith("Sheri: 5 mason, 2 electrician. Onnu nokki Save tap cheyyu.\n\n✅ Saved:")
    assert "saved" not in result.reply.text.split("\n\n")[0].casefold()


async def test_a_failing_retry_also_falls_back():
    provider = Scripted(
        [("save_labour", {"workers": [{"trade": "mason", "headcount": 5}, {"trade": "electrician", "headcount": 2}]})],
        ["5 mason vannu."],
    )
    result, _ = await _run(provider, StepResult("saved", text="a", summary="7 workers"), text="5 mason, 2 electrician")
    assert result.reply.text.startswith("Got it: 5 mason, 2 electrician. Please check it and tap Save.")


async def test_a_sentence_that_covers_everything_is_left_alone():
    provider = Scripted(
        [("save_labour", {"workers": [{"trade": "mason", "headcount": 3}]})],
        ["3 mason, ok? Save tap cheyyu."],
    )
    result, _ = await _run(provider, StepResult("saved", text="a", summary="3 workers (3 mason)"), text="3 mason vannu")
    assert provider.runs == 1
    assert result.reply.text.startswith("3 mason, ok? Save tap cheyyu.\n\n")


def test_the_fallback_line_is_in_the_senders_language_and_never_says_saved():
    items = items_of([_labour_call({"trade": "mason", "headcount": 3})])
    assert fallback_line(items, "3 mason vannu").startswith("Sheri: 3 mason.")
    assert fallback_line(items, "3 mason came").startswith("Got it: 3 mason.")
    assert fallback_line(items, "ഇന്ന് 3 മേസൺ").startswith("ശരി: 3 mason.")
    assert fallback_line(items, "आज 3 मिस्त्री").startswith("ठीक है: 3 mason.")
    for text in ("3 mason vannu", "3 mason came", "ഇന്ന് 3 മേസൺ", "आज 3 मिस्त्री"):
        assert "saved" not in fallback_line(items, text).casefold()


# -- the prompt ------------------------------------------------------------------


def test_the_prompt_has_the_rules_and_the_tone_examples():
    assert "location" in SYSTEM_PROMPT and "3rd floor" in SYSTEM_PROMPT
    assert "request_dpr" in SYSTEM_PROMPT and "Never list the saved items again" in SYSTEM_PROMPT
    assert "never ask for details" in SYSTEM_PROMPT
    assert "16 per vannu, cement 25 bag use cheythu, ok? Save tap cheyyu." in SYSTEM_PROMPT
    assert SYSTEM_PROMPT.count("-> \"") >= 4  # the sentence examples
