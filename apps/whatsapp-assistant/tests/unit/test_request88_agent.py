"""Request 88 (22 Oct live test): undo takes the entries of the latest card, an
open card can be changed, the day summary leaves out what was cancelled, a past
day's report is one rule, and the reply's words are checked (abbreviations,
Save prompts, done-words, scripts)."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from channel.replies import ReplySpec
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import cards as c
from runtime.agent import reply_text as rt
from runtime.agent import runner as r
from runtime.agent import save_button as sb
from runtime.agent import toolbox as tb
from runtime.agent.gateway import StepResult
from runtime.agent.journey_gateway import JourneyGateway
from runtime.agent.prompt import AgentContext
from runtime.agent.query_entry import _one_name_per_trade
from runtime.agent.tools import ScopeLookup, day_argument, to_candidate
from runtime.dpr_request_query import only_kept

# -- helpers -------------------------------------------------------------------


class _Redis:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self.data[key] = value

    async def get_json(self, key: str) -> Any | None:
        return self.data.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)


ACTOR = SimpleNamespace(organization_id="org-1", user_id="user-1")


def _item(summary: str, tool: str = "save_labour", args: dict | None = None, fact_type: str = "labour_report") -> c.CardItem:
    return c.CardItem(tool, args or {}, fact_type, str(uuid.uuid4()), summary)


class _Undone:
    def __init__(self, done=(), refused=()) -> None:
        self.done, self.refused, self.already = list(done), list(refused), 0


def _gateway(store: c.CardStore | None, undone: Any = None, calls: list | None = None) -> JourneyGateway:
    async def undo_facts(facts):  # noqa: ANN001
        if calls is not None:
            calls.append(list(facts))
        return undone if undone is not None else _Undone(done=facts)

    async def old_undo():  # noqa: ANN202
        return "Done. I've removed the issue."

    async def noop(*a, **k):  # noqa: ANN002, ANN003, ANN202
        return None

    return JourneyGateway(
        message=SimpleNamespace(correlation_id="cor", modality=None, text=""),  # type: ignore[arg-type]
        save_now=noop,
        undo=old_undo,
        followups=noop,
        held_prompt=lambda journey: ReplySpec(text=""),
        cards=store,
        actor=ACTOR,
        undo_facts=undo_facts,
    )


# -- 1. undo takes the latest card's entries -----------------------------------


async def test_undo_removes_the_painters_not_an_unrelated_issue():
    store = c.CardStore(_Redis())
    painters = _item("2 workers (2 painter)")
    await store.put(ACTOR, c.new_card(c.SAVED, [painters]))
    calls: list = []
    step = await _gateway(store, calls=calls).undo_card([])
    assert calls == [[painters.fact]]
    assert (step.status, step.text) == ("undone", "Removed: 2 workers (2 painter) (today)")
    assert await store.get(ACTOR) is None  # nothing left on the card


async def test_a_forged_id_is_rejected_and_nothing_is_removed():
    store = c.CardStore(_Redis())
    await store.put(ACTOR, c.new_card(c.SAVED, [_item("2 painters")]))
    calls: list = []
    step = await _gateway(store, calls=calls).undo_card([uuid.uuid4().hex[:8]])
    assert step.status == "error" and calls == []


async def test_a_card_of_several_entries_asks_which_one_with_a_list():
    store = c.CardStore(_Redis())
    first, second = _item("2 painters"), _item("30 bags cement", "save_material_receipt", fact_type="material_receipt")
    await store.put(ACTOR, c.new_card(c.SAVED, [first, second]))
    calls: list = []
    step = await _gateway(store, calls=calls).undo_card([])
    assert step.status == "choose" and calls == []
    rows = step.reply.list_rows
    taps = [sb.parse_tap(row.id) for row in rows]
    assert taps[0] == (sb.UNDO, [first.fact]) and taps[1] == (sb.UNDO, [second.fact])
    assert taps[2] == (sb.UNDO, [first.fact, second.fact]) and rows[2].title == "All of them"


async def test_naming_one_entry_removes_only_that_one():
    store = c.CardStore(_Redis())
    first, second = _item("2 painters"), _item("30 bags cement")
    await store.put(ACTOR, c.new_card(c.SAVED, [first, second]))
    calls: list = []
    step = await _gateway(store, calls=calls).undo_card([second.ref])
    assert calls == [[second.fact]] and step.text == "Removed: 30 bags cement (today)"
    left = await store.get(ACTOR)
    assert [i.fact for i in left.items] == [first.fact]


async def test_nothing_on_a_card_says_so_and_a_refused_undo_says_why():
    store = c.CardStore(_Redis())
    assert (await _gateway(store).undo_card([])).status == "info"
    item = _item("2 painters")
    await store.put(ACTOR, c.new_card(c.SAVED, [item]))
    step = await _gateway(store, undone=_Undone(refused=["this day's DPR is already confirmed; revise it instead"])).undo_card([])
    assert step.status == "error" and "already confirmed" in step.text
    assert (await store.get(ACTOR)).items == [item]  # still there


async def test_a_reply_without_save_buttons_keeps_the_old_undo():
    store = c.CardStore(_Redis())
    await store.put(ACTOR, c.new_card(c.LEGACY, []))
    step = await _gateway(store).undo_card([])
    assert (step.status, step.text) == ("undone", "Done. I've removed the issue.")


# -- the toolbox: undo_last and update_pending_card ----------------------------


class _Gateway:
    """The card parts of a gateway, scripted."""

    def __init__(self, *results: StepResult, card: c.Card | None = None, withdraw: bool = True) -> None:
        self.results = list(results)
        self.card = card
        self.withdraw = withdraw
        self.runs: list[Any] = []
        self.calls: list[tuple] = []
        self.withdrawn: list[c.CardItem] = []
        self.carried: tuple | None = None
        self.undo_args: list | None = None

    async def run(self, candidate, *, text):  # noqa: ANN001
        self.runs.append(candidate)
        self.calls.append(self.current_call)
        return self.results.pop(0)

    async def undo_card(self, refs):  # noqa: ANN001
        self.undo_args = refs
        return self.results.pop(0)

    async def undo_latest_draft(self):  # noqa: ANN202
        raise AssertionError("the old undo must not run")

    async def open_card(self):  # noqa: ANN202
        return self.card

    async def withdraw_card_item(self, item):  # noqa: ANN001
        self.withdrawn.append(item)
        return self.withdraw

    def carry_card_items(self, before, after):  # noqa: ANN001
        self.carried = (before, after)

    async def finish(self):  # noqa: ANN202
        return None


def _box(gateway: _Gateway) -> tb.AgentToolbox:
    return tb.AgentToolbox(gateway, ScopeLookup(), "alla, 8 mason aanu")


async def test_undo_last_passes_the_ids_and_the_reply_names_what_was_removed():
    gateway = _Gateway(StepResult("undone", text="Removed: 2 workers (2 painter) (today)"))
    box = _box(gateway)
    out = await box.handle("undo_last", {"targets": ["ab12cd34"]})
    assert out.content["status"] == "undone" and gateway.undo_args == ["ab12cd34"]
    assert box.system_lines == ["Removed: 2 workers (2 painter) (today)"]


LABOUR_ARGS = {"workers": [{"trade": "mason", "headcount": 7}, {"trade": "helper", "headcount": 12}]}


def _open_card() -> c.Card:
    return c.new_card(c.OPEN, [_item("19 workers (7 mason, 12 helper)", args=LABOUR_ARGS)])


async def test_update_pending_card_changes_one_trade_and_keeps_the_rest():
    card = _open_card()
    gateway = _Gateway(StepResult("saved", text="ok", summary="20 workers (8 mason, 12 helper)"), card=card)
    box = _box(gateway)
    out = await box.handle(
        "update_pending_card",
        {"card_id": card.id, "item_index": 1, "changes": {"workers": [{"trade": "mason", "headcount": 8}]}},
    )
    assert out.content["status"] == "saved"
    assert gateway.withdrawn == [card.items[0]]
    tool, args = gateway.calls[0]
    assert tool == "save_labour"
    assert {(w["trade"], w["headcount"]) for w in args["workers"]} == {("mason", 8), ("helper", 12)}
    assert [i.summary for i in box.saved] == ["20 workers (8 mason, 12 helper)"]
    assert gateway.carried == ([], [])


async def test_the_other_items_of_the_card_stay_on_it():
    first = _item("19 workers (7 mason, 12 helper)", args=LABOUR_ARGS)
    second = _item("30 bags cement received", "save_material_receipt", {"material": "cement", "quantity": 30, "unit": "bag"})
    card = c.new_card(c.OPEN, [first, second])
    gateway = _Gateway(StepResult("saved", text="ok", summary="Cement received: 20 bags"), card=card)
    box = _box(gateway)
    await box.handle(
        "update_pending_card", {"card_id": card.id, "item_index": 2, "changes": {"quantity": 20}}
    )
    assert gateway.calls[0][1]["quantity"] == 20 and gateway.calls[0][1]["material"] == "cement"
    assert [i.summary for i in box.saved] == ["19 workers (7 mason, 12 helper)", "Cement received: 20 bags"]
    assert box.saved[0].carried and not box.saved[1].carried
    assert gateway.carried == ([first], [])


@pytest.mark.parametrize(
    "args",
    [
        {"card_id": "nope", "item_index": 1, "changes": {"quantity": 1}},  # not the open card
        {"item_index": 5, "changes": {"quantity": 1}},  # no such item
        {"item_index": 1, "changes": {"nonsense": 1}},  # not a field of the item's tool
        {"item_index": 1, "changes": {}},  # nothing to change
    ],
)
async def test_a_bad_card_change_changes_nothing(args):
    card = _open_card()
    gateway = _Gateway(card=card)
    args.setdefault("card_id", card.id)
    out = await _box(gateway).handle("update_pending_card", args)
    assert out.content["status"] == "error"
    assert gateway.withdrawn == [] and gateway.runs == []


async def test_a_card_that_is_already_saved_is_not_edited():
    gateway = _Gateway(card=None)
    out = await _box(gateway).handle(
        "update_pending_card", {"card_id": "x", "item_index": 1, "changes": {"quantity": 1}}
    )
    assert out.content["status"] == "info" and gateway.withdrawn == []


async def test_a_change_that_is_refused_puts_the_old_entry_back():
    card = _open_card()
    gateway = _Gateway(
        StepResult("error", text="Not saved: that is not allowed."),
        StepResult("saved", text="ok", summary="19 workers (7 mason, 12 helper)"),
        card=card,
    )
    box = _box(gateway)
    out = await box.handle(
        "update_pending_card",
        {"card_id": card.id, "item_index": 1, "changes": {"workers": [{"trade": "mason", "headcount": 8}]}},
    )
    assert out.content["status"] == "error" and "as it was" in out.content["message"]
    assert len(gateway.runs) == 2 and gateway.calls[1][1] == LABOUR_ARGS
    assert [i.summary for i in box.saved] == ["19 workers (7 mason, 12 helper)"]


async def test_an_entry_that_cannot_be_taken_back_is_not_replaced():
    card = _open_card()
    gateway = _Gateway(card=card, withdraw=False)
    out = await _box(gateway).handle(
        "update_pending_card", {"card_id": card.id, "item_index": 1, "changes": {"workers": [{"trade": "mason", "headcount": 8}]}}
    )
    assert out.content["status"] == "error" and gateway.runs == []


def test_worker_lines_merge_by_trade_or_name():
    merged = c.merge_changes("save_labour", LABOUR_ARGS, {"workers": [{"trade": "Masons", "headcount": 8}, {"trade": "painter", "headcount": 2}]})
    assert [(w["trade"], w["headcount"]) for w in merged["workers"]] == [("mason", 8), ("helper", 12), ("painter", 2)]
    named = c.merge_changes("save_labour", {"workers": [{"name": "Ravi", "trade": "mason", "headcount": 1}]}, {"workers": [{"name": "ravi", "attendance_status": "half_day"}]})
    assert named["workers"] == [{"name": "Ravi", "trade": "mason", "headcount": 1, "attendance_status": "half_day"}]
    assert c.merge_changes("save_material_receipt", {"quantity": 30, "unit": "bag"}, {"quantity": 20}) == {"quantity": 20, "unit": "bag"}


async def test_the_card_and_what_the_model_may_name_are_in_its_context():
    saved = _item("2 workers (2 painter)")
    line = c.context_line(c.new_card(c.SAVED, [saved]))
    assert f"[{saved.ref}] 2 workers (2 painter)" in line and "undo_last" in line
    card = _open_card()
    open_line = c.context_line(card)
    assert card.id in open_line and "1. 19 workers" in open_line and "update_pending_card" in open_line
    assert c.context_line(c.new_card(c.LEGACY, [])) is None and c.context_line(None) is None


async def test_the_save_tap_marks_the_card_saved_and_cancel_drops_it():
    store = c.CardStore(_Redis())
    item = _item("2 painters")
    await store.put(ACTOR, c.new_card(c.OPEN, [item]))
    assert await store.settle(ACTOR, [item.fact], keep=True) is not None
    assert (await store.get(ACTOR)).state == c.SAVED
    assert await store.settle(ACTOR, [_item("other").fact], keep=True) is None  # some other card's tap
    await store.settle(ACTOR, [item.fact], keep=False)
    assert await store.get(ACTOR) is None


async def test_a_remove_row_tap_withdraws_exactly_that_entry():
    store = c.CardStore(_Redis())
    first, second = _item("2 painters"), _item("30 bags cement")
    await store.put(ACTOR, c.new_card(c.SAVED, [first, second]))
    asked: list = []

    class Handler:
        async def undo_facts(self, *, organization_id, user_id, facts):  # noqa: ANN001
            asked.append(facts)
            return _Undone(done=facts)

    message = SimpleNamespace(metadata={"interactive_reply_id": sb.tap_id(sb.UNDO, [second.fact])})
    reply = await sb.handle_tap(message, ACTOR, Handler(), store)
    assert asked == [[second.fact]] and reply.text == "Removed: 30 bags cement (today)"
    assert [i.fact for i in (await store.get(ACTOR)).items] == [first.fact]


# -- 3. the summary leaves out what was cancelled ------------------------------


def test_a_cancelled_steel_and_cement_card_is_not_listed_as_materials():
    payload = {
        "materials": [{"material_name": "Steel"}, {"material_name": "Cement"}, {"material_name": "Sand"}],
        "activity_count": 2,
        "open_issue_count": 1,
        "labour": {"headcount": 19},
    }
    items = [
        {"section": "materials", "title": "Steel", "review": "rejected"},
        {"section": "materials", "title": "Cement", "review": "rejected"},
        {"section": "materials", "title": "Cement", "review": "rejected"},
        {"section": "materials", "title": "Sand", "review": "draft"},
        {"section": "work", "title": "Plastering", "review": "rejected"},
        {"section": "issues", "title": "Delay", "review": "rejected", "status": "OPEN"},
        {"section": "labour", "title": "7 workers", "review": "rejected"},
    ]
    kept = only_kept(payload, items)
    assert [m["material_name"] for m in kept["materials"]] == ["Sand"]
    assert (kept["activity_count"], kept["open_issue_count"], kept["labour"]["headcount"]) == (1, 0, 12)
    assert payload["materials"][0]["material_name"] == "Steel"  # the original is untouched
    # one cancelled and one kept entry of the same material: it stays listed
    both = only_kept(payload, [{"section": "materials", "title": "Steel", "review": "rejected"},
                               {"section": "materials", "title": "Steel", "review": "confirmed"}])
    assert [m["material_name"] for m in both["materials"]] == ["Steel"]


# -- 4. one rule for the past day's report -------------------------------------


@pytest.mark.parametrize(
    "said, expected",
    [("innale", "yesterday"), ("ഇന്നലെ", "yesterday"), ("innaleത്തെ", "yesterday"), ("Innalathe", "yesterday"),
     ("yesterday", "yesterday"), ("2026-10-21", "2026-10-21"), (None, None)],
)
def test_every_wording_of_yesterday_reaches_the_pipeline_as_yesterday(said, expected):
    assert day_argument(said) == expected
    candidate = to_candidate("request_dpr", {"date": said} if said else {}, ScopeLookup())
    assert candidate.fields.get("report_date") == expected or (expected is None and "report_date" not in candidate.fields)


async def test_a_past_day_with_entries_but_no_pdf_is_a_draft_marked_not_confirmed():
    from runtime.agent.query_entry import QueryEntry

    class Query:
        def __init__(self, lines):  # noqa: ANN001
            self.lines, self.asked = lines, None

        async def preview_lines(self, **kw):  # noqa: ANN003
            self.asked = kw
            return self.lines

    site = SimpleNamespace(id="s1", name="Site A1", project_id="p1")
    actor = SimpleNamespace(organization_id="org", projects=[SimpleNamespace(id="p1")], sites=[site])

    def ready(status, day="21 Oct 2026"):  # noqa: ANN001, ANN202
        event = SimpleNamespace(
            project_id=None, site_id=None,
            fields={"dpr_day": day, "dpr_status": status, "report_date": "yesterday", "dpr_site_name": "Site A1"},
        )
        return SimpleNamespace(event=event)

    entry = QueryEntry(None, None, actor, dpr_request_query=Query(["• Labour: 19 workers"]))
    say = await entry._past_day_draft(ready("pending_confirmation"), timezone="Asia/Kolkata")
    assert say.status == "answer" and "isn't confirmed yet" in say.text and "• Labour: 19 workers" in say.text
    assert "21 Oct 2026" in say.text and "not sent to anyone" in say.text
    from datetime import timedelta

    from canonicalization.occurred_date import today_for

    assert entry.dpr_request_query.asked["report_date"] == today_for("Asia/Kolkata") - timedelta(days=1)
    # no entries: the workflow's own "no DPR for that day" stands; today and a ready PDF are left alone
    assert await QueryEntry(None, None, actor, dpr_request_query=Query([]))._past_day_draft(ready("not_generated"), timezone="Asia/Kolkata") is None
    assert await entry._past_day_draft(ready("ready"), timezone="Asia/Kolkata") is None
    assert await entry._past_day_draft(ready("pending_confirmation", day=""), timezone="Asia/Kolkata") is None


def test_the_labour_answer_names_each_trade_once():
    results = {"trades": ["mason", "masons", "bar_bending", "bar_bender", "helper", "Helpers", "tile_layer"]}
    _one_name_per_trade(results)
    assert results["trades"] == ["mason", "bar_bender", "helper", "tile_layer"]
    _one_name_per_trade(None)
    _one_name_per_trade({"trades": []})


# -- 5. the words of the reply -------------------------------------------------


def test_an_abbreviation_does_not_end_a_sentence():
    text = "I can note a payment you made, e.g. paid to a vendor. Tell me more!"
    assert rt.sentences(text) == ["I can note a payment you made, e.g. paid to a vendor.", " Tell me more!"]
    assert "".join(rt.sentences("Rs. 500 for sand, i.e. 5 bags, etc. Then 12.5 kg.\nOk")) == "Rs. 500 for sand, i.e. 5 bags, etc. Then 12.5 kg.\nOk"
    assert len(rt.sentences("Rs. 500 for sand, i.e. 5 bags, etc. Then 12.5 kg.")) == 1
    assert rt.sentences("Approx. 5 bags. Done.") == ["Approx. 5 bags.", " Done."]
    assert rt.sentences("Wait... then go. Yes?") == ["Wait...", " then go.", " Yes?"]


def test_a_reply_is_trimmed_only_over_the_cap_and_at_a_sentence_end():
    short = "Sure. I can note a payment, e.g. paid to a vendor."
    assert rt.trim_at_sentence(short, 1000) == short
    long = "First sentence here. " + "Second one, e.g. a payment you made. " * 40
    cut = rt.trim_at_sentence(long, 120)
    assert len(cut) <= 120 and cut.endswith(".") and not cut.endswith("e.g.")
    assert rt.trim_at_sentence("x" * 50 + " " + "y" * 200, 60).endswith("…")


def test_the_number_guard_no_longer_cuts_a_reply_after_e_g():
    reply = "I can note a payment you made, e.g. 500 to the electrician. Tell me the amount and who it was for."
    kept = r.without_numbers(reply, {"500"})
    assert kept == " Tell me the amount and who it was for." or kept == "Tell me the amount and who it was for."
    assert "e.g." not in kept


def test_a_save_prompt_goes_unless_there_is_a_card():
    text = "Cement stock 140 bags. Save tap cheyyu. Anything else?"
    assert rt.without_save_prompt(text) == "Cement stock 140 bags. Anything else?"
    assert rt.without_save_prompt("Stock is fine. Please tap Save to keep it.") == "Stock is fine."
    assert rt.without_save_prompt("Please save some water. Done.") == "Please save some water. Done."


def test_words_in_two_scripts_are_found():
    assert rt.mixed_script_words("innaleത്തെ report ayakkam, Save അമർത്തുക") == ["innaleത്തെ"]
    assert rt.mixed_script_words("plain english and മലയാളം") == []


def test_script_problems_name_what_is_wrong():
    assert r.script_problems("innaleത്തെ report ayakkam", "innale report ayakku")
    assert r.script_problems("ശരി, 8 mason", "I need eight masons today ok")  # native script for English letters
    assert r.script_problems("Sheri, ningal innu cement vannu, nokki Save cheyyu", "Please send the report for today")
    assert not r.script_problems("Sheri, 8 mason aakki.", "alla, 8 mason aanu")
    assert not r.script_problems("Reply UNDO if it is wrong", "please check the cement stock today")
    assert not r.script_problems("ശരി", "ok")  # a message with no words of its own follows the earlier language


CTX = AgentContext(
    user_name="Anil", role="SUPERVISOR", company="Acme", now=datetime(2026, 10, 22, 9, 30),
    projects=(("Project Alpha", None),), sites=(("Site A1", "Project Alpha"),),
)


async def _run(provider, *results, text="the note", gateway=None):  # noqa: ANN001, ANN202
    gateway = gateway or _Gateway(*results)
    return await r.AgentRunner(provider).run(ctx=CTX, user_text=text, gateway=gateway, scope=ScopeLookup())


async def test_a_stock_answer_has_no_save_footer():
    provider = FakeToolCallingProvider([[("query_materials", {"material": "cement"})], "Cement stock 140 bag und. Save tap cheyyu."])
    result = await _run(provider, StepResult("answer", text="Cement: 140 bags"), text="cement ethra und")
    assert "Save" not in result.reply.text and "140" in result.reply.text


async def test_a_card_reply_keeps_the_save_request():
    provider = FakeToolCallingProvider([[("save_labour", {"workers": LABOUR_ARGS["workers"]})], "Sheri, 7 mason, 12 helper. Nokki Save tap cheyyu."])
    gateway = _Gateway(StepResult("saved", text="ok", summary="19 workers (7 mason, 12 helper)"))
    result = await _run(provider, text="7 mason 12 helper vannu", gateway=gateway)
    assert "Save tap cheyyu" in result.reply.text


async def test_a_done_word_before_save_is_asked_again_then_replaced():
    provider = FakeToolCallingProvider(
        [[("report_issue", {"narrative": "mixer kedayi"})], "Ayyo, mixer machine kedayi, issue aayi ezhuthiyittund. Save tap cheyyu."]
    )
    gateway = _Gateway(StepResult("saved", text="ok", summary="Machine breakdown: mixer kedayi"))
    result = await _run(provider, text="mixer machine kedayi", gateway=gateway)
    assert provider.calls == 2  # asked again once
    assert "ezhuthiyittund" not in result.reply.text
    assert "Machine breakdown" in result.reply.text  # the system's own sentence names the card


async def test_a_mixed_script_word_is_asked_again_and_cut_if_it_comes_back():
    provider = FakeToolCallingProvider(["innaleത്തെ report ayakkam. Ethu site?"])
    result = await _run(provider, text="innale report ayakku")
    assert provider.calls == 2
    assert "innaleത്തെ" not in result.reply.text


async def test_a_long_reply_is_cut_at_a_sentence_end_not_in_the_middle():
    body = "Cement stock is fine, e.g. plenty of bags are there. " * 40
    provider = FakeToolCallingProvider([f"{body}"])
    result = await _run(provider, text="cement ethra und")
    text = result.reply.text
    assert len(text) <= r.REPLY_CAP and text.endswith(".") and "e.g.…" not in text


def test_the_removed_line_is_added_under_the_models_words():
    box = _box(_Gateway())
    box.system_lines.append("Removed: 2 workers (2 painter) (today)")
    result = r.AgentRunner(FakeToolCallingProvider([]))._compose(
        SimpleNamespace(text="Ok, painters-ne mattiyittund.", stop_reason="answered"), box, [], None
    )
    assert result.text.endswith("Removed: 2 workers (2 painter) (today)")
