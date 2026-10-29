"""Request 83 (22 Oct live test): work done keeps its floor and status on the
card, "send the report" in a message that saves gets ONE draft line, and the
sentence above the card names every item on it."""

from __future__ import annotations

from datetime import datetime

from canonicalization.progress import apply_progress, settle_place_and_status
from interactions.saved_summary import summarise_draft
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_ai.models import ToolRunResult
from mesiri_contracts.assistant.draft_action import DraftActionType
from runtime.agent import runner as r
from runtime.agent.gateway import StepResult
from runtime.agent.prompt import AgentContext
from runtime.agent.tools import ScopeLookup
from runtime.agent.wording import say

CTX = AgentContext(
    user_name="Anil",
    role="SUPERVISOR",
    company="Acme Builders",
    now=datetime(2026, 10, 22, 9, 30),
    projects=(("Project Alpha", "Kochi"),),
    sites=(("Site A1", "Project Alpha"),),
)


class _Draft:
    def __init__(self, action_type, fields):
        self.action_type = action_type
        self.fields = fields


def _card(fields):
    """The To-save line of a new activity, from the fields the entry settled."""
    settled = settle_place_and_status(apply_progress(dict(fields), None))
    return summarise_draft(_Draft(DraftActionType.CREATE_ACTIVITY, settled)), settled


def test_a_floor_in_the_work_name_and_finished_reach_the_card():
    line, fields = _card({"narrative": "3rd floor slab concreting finished", "work_type": "3rd floor slab concreting"})
    assert line == "Slab concreting, 3rd floor (completed)"
    assert (fields["location"], fields["update_kind"]) == ("3rd floor", "completed")
    assert fields["narrative"] == "Slab concreting, 3rd floor (completed)"


def test_the_floor_the_model_gave_and_a_percentage_reach_the_card():
    line, fields = _card(
        {"narrative": "2nd floor plastering 70%", "work_type": "plastering", "location": "2nd floor", "update_kind": "completed"}
    )
    assert line == "Plastering, 2nd floor: 70%"
    assert fields["update_kind"] == "progress" and fields["progress_percent"] == 70


def test_a_floor_only_in_the_words_is_found_and_done_alone_is_not_finished():
    line, fields = _card({"narrative": "180 sqm plastering done on second floor", "work_type": "plastering",
                          "quantities": [{"quantity": 180, "unit": "sqm"}]})
    assert fields["location"] == "2nd floor"
    assert line == "Plastering, 2nd floor: 180 sqm"
    assert "update_kind" not in fields


def test_finished_words_in_the_senders_languages_count():
    for words in ("plastering theernnu", "plastering കഴിഞ്ഞു", "plastering ho gaya", "plastering completed"):
        assert settle_place_and_status({"narrative": words, "work_type": "plastering"})["update_kind"] == "completed"


# -- the sentence above the card -------------------------------------------

LABOUR = "15 workers (5 mason, 8 helper, 2 electrician)"


def test_a_sentence_that_drops_a_trade_is_not_covered():
    assert r.uncovered_items("Innu 5 mason, 8 helper vannu. Save cheyyuka.", [LABOUR]) == [LABOUR]
    assert r.uncovered_items("Innu 5 mason, 8 helper, 2 electrician vannu.", [LABOUR]) == []


def test_a_floor_or_the_labour_total_is_not_asked_for():
    assert r.uncovered_items("Slab concreting theernnu, plastering 70%.", [
        "Slab concreting, 3rd floor (completed)", "Plastering, 2nd floor: 70%"]) == []
    assert r.uncovered_items("5 mason, 8 helper", ["13 workers (5 mason, 8 helper)"]) == []


def test_an_item_without_a_figure_needs_one_of_its_words():
    item = "Slab concreting, 3rd floor (completed)"
    assert r.uncovered_items("Ok, 5 mason vannu.", [item]) == [item]
    assert r.uncovered_items("Ok, slab concreting theernnu.", [item]) == []


def test_the_system_sentence_is_in_the_senders_language_and_never_says_saved():
    items = [LABOUR, "Cement used: 25 bags"]
    manglish = r.covering_sentence(items, "innu 5 mason, 8 helper, 2 electrician vannu")
    assert manglish.startswith("15 workers (5 mason, 8 helper, 2 electrician); Cement used: 25 bags. *✅ Save* tap cheyyu, record aakum.")
    assert r.covering_sentence(items, "12 masons today").endswith("Tap *✅ Save* to record it.")
    assert "അമർത്തിയാൽ" in r.covering_sentence(items, "ഇന്ന് 12 മേസൺ")
    assert "दबाते" in r.covering_sentence(items, "आज 12 मिस्त्री")
    for text in (manglish, r.covering_sentence(items, "hello")):
        assert not r._SAVED_CLAIM.search(text)
        assert uncovered_after(text, items) == []


def uncovered_after(text, items):
    return r.uncovered_items(text, items)


class _Provider(FakeToolCallingProvider):
    """The scripted tool turn, then scripted answers to the no-tools retries."""

    def __init__(self, script, retries):
        super().__init__(script)
        self.retries = list(retries)
        self.retried = 0

    async def run_tools(self, system_prompt, messages, tools, handler, **kwargs):
        if tools:
            return await super().run_tools(system_prompt, messages, tools, handler, **kwargs)
        self.retried += 1
        return ToolRunResult(text=self.retries.pop(0), calls=[], steps=1, stop_reason="answered", model="fake")


class _Gateway:
    def __init__(self, *results):
        self.results = list(results)

    async def run(self, candidate, *, text):
        return self.results.pop(0)

    async def undo_latest_draft(self):
        return self.results.pop(0)

    async def finish(self):
        return None


async def _say(provider, text, *results):
    return await r.AgentRunner(provider).run(
        ctx=CTX, user_text=text, gateway=_Gateway(*results), scope=ScopeLookup()
    )


WORKERS = [{"trade": "mason", "headcount": 5}, {"trade": "helper", "headcount": 8}, {"trade": "electrician", "headcount": 2}]
SAID = "innu 5 mason, 8 helper, 2 electrician vannu"


async def test_a_sentence_that_leaves_an_item_out_is_the_systems_own_at_once():
    """Request 143 (speed): no second model call; the system's sentence names every item."""
    provider = _Provider(
        [[("save_labour", {"workers": WORKERS})], "Innu 5 mason, 8 helper vannu. Nokki Save tap cheyyu."],
        ["Sheri, innu 5 mason, 8 helper, 2 electrician vannu. Nokki Save tap cheyyu."],
    )
    result = await _say(provider, SAID, StepResult("saved", text="x", summary=LABOUR))
    assert provider.retried == 0
    assert result.reply.text.startswith(f"{LABOUR}. *✅ Save* tap cheyyu, record aakum.")


async def test_a_sentence_that_names_everything_costs_no_second_call():
    provider = _Provider(
        [[("save_labour", {"workers": WORKERS})], "Sheri, 5 mason, 8 helper, 2 electrician. Nokki Save tap cheyyu."], []
    )
    await _say(provider, SAID, StepResult("saved", text="x", summary=LABOUR))
    assert provider.retried == 0 and provider.calls == 1


# -- the report in a mixed message (request 143: the PDF went, one line) ------

SENT = "Innathe draft report · Site A1 ithaa, ithuvare save cheythathil ninnu. Confirm aayittilla."
MIXED = "6 mason vannu, 25 bag cement use cheythu, nale steel venam. innathe report ayakku"


async def test_a_report_request_with_saves_is_one_card_and_one_report_line():
    provider = FakeToolCallingProvider(
        [
            [
                ("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]}),
                ("save_material_usage", {"material": "cement", "quantity": 25, "unit": "bags"}),
                ("request_dpr", {}),
            ],
            "Sheri, 6 mason, 25 bag cement. Nokki Save tap cheyyu.",
        ]
    )
    result = await _say(
        provider,
        MIXED,
        StepResult("saved", text="a", summary="6 workers (6 mason)"),
        StepResult("saved", text="b", summary="Cement used: 25 bags"),
        StepResult("answer", text=SENT, documents=1),
    )
    text = result.reply.text
    assert text.count("✅ Saved:") == 1 and text.count("6 workers (6 mason)") == 1
    line = say("report.with_card", "manglish")
    assert text.count(line) == 1 and text.index("Cement used: 25 bags") < text.index(line)
    assert SENT not in text


async def test_a_report_request_alone_is_the_codes_line_not_the_models():
    provider = FakeToolCallingProvider([[("request_dpr", {})], "Today's report ready aayittilla, ithu oru draft aanu."])
    result = await _say(provider, "innathe report ayakku", StepResult("answer", text=SENT, documents=1))
    assert result.reply.text == SENT


async def test_the_work_done_entry_hands_the_workflow_the_floor_and_the_status():
    from tests.unit.test_site_entry import _entry, _prepare

    from mesiri_contracts.assistant.enums import SemanticType

    done = await _prepare(
        _entry(), SemanticType.GENERAL_SITE_UPDATE,
        narrative="3rd floor slab concreting finished", work_type="3rd floor slab concreting",
    )
    assert (done.event.fields["location"], done.event.fields["update_kind"]) == ("3rd floor", "completed")
    assert done.event.fields["work_type"] == "slab concreting"
    part = await _prepare(
        _entry(), SemanticType.GENERAL_SITE_UPDATE,
        narrative="2nd floor plastering 70%", work_type="plastering", progress_percent=70,
    )
    assert (part.event.fields["location"], part.event.fields["update_kind"]) == ("2nd floor", "progress")
    assert part.event.fields["narrative"] == "Plastering, 2nd floor: 70%"
