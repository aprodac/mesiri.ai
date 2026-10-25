"""Request 88: the 22 Oct live-test sequence (Test Builders) through the real
journey -- entries, cards, taps, undo -- with the model scripted the way the live
one answered. What is checked is what the sender reads and which record each tool
call reached: the painters undo removes the painters, "alla, 8 mason aanu" changes
the open card, a stock question has no Save footer."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from tests.replay.test_agent_replay import world  # noqa: F401,F811  (fixture)

from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from runtime.agent import cards as c
from runtime.agent import save_button as sb
from runtime.agent.runner import AgentRunner


class _Redis:
    def __init__(self) -> None:
        self.data: dict = {}

    def namespaced(self, *parts):  # noqa: ANN002, ANN201
        return ":".join(parts)

    async def set_json(self, key, value, *, ttl_seconds=None):  # noqa: ANN001, ANN201
        self.data[key] = value

    async def get_json(self, key):  # noqa: ANN001, ANN201
        return self.data.get(key)

    async def delete(self, *keys):  # noqa: ANN002, ANN201
        for key in keys:
            self.data.pop(key, None)


class Day:
    """One sender's day: each record gets its own id, taps and withdrawals are
    recorded, and the card store is the real one."""

    def __init__(self, world) -> None:  # noqa: ANN001, F811
        self.world = world
        self.cards = c.CardStore(_Redis())
        self.withdrawn: list = []
        self.saved_ids: list[str] = []
        outer = self

        async def dispatch(confirmed):  # noqa: ANN001, ANN202
            world.dispatcher.dispatched.append(confirmed)
            row = str(uuid.uuid4())
            outer.saved_ids.append(row)
            return ExecutionResult(
                status=ExecutionStatus.SUCCEEDED, idempotency_key=f"idem_{row}", material_row_id=row
            )

        world.dispatcher.dispatch = dispatch

    async def undo_facts(self, facts):  # noqa: ANN001, ANN201
        self.withdrawn.extend(facts)
        return SimpleNamespace(done=list(facts), refused=[], already=0)

    async def say(self, provider, text, *, card_line=True):  # noqa: ANN001, ANN201
        gateway = self.world.gateway(text)
        gateway.cards, gateway.actor, gateway.undo_facts = self.cards, self.world.actor, self.undo_facts
        line = c.context_line(await self.cards.get(self.world.actor)) if card_line else None
        result = await AgentRunner(provider).run(
            ctx=self.world.context(card_line=line),
            user_text=text,
            gateway=gateway,
            scope=self.world.scope(),
            correlation_id="cor_agent_replay",
        )
        self.world.last_gateway = gateway
        # What the journey does when it sends the reply: the card it shows.
        facts = sb.facts_of(
            gateway.handled,
            before=[i.fact for i in gateway.carry_before],
            after=[i.fact for i in gateway.carry_after],
        )
        if facts is not None:
            await self.cards.put(
                self.world.actor,
                c.new_card(c.OPEN, [*gateway.carry_before, *gateway.card_items, *gateway.carry_after]),
            )
        return result, gateway, facts

    async def tap(self, action, facts):  # noqa: ANN001, ANN201
        class Handler:
            async def settle_drafts(self, *, organization_id, user_id, facts, keep):  # noqa: ANN001, ANN201
                return SimpleNamespace(done=len(facts), already=0, refused=[])

            undo_facts = None

        message = SimpleNamespace(metadata={"interactive_reply_id": sb.tap_id(action, facts)})
        return await sb.handle_tap(message, self.world.actor, Handler(), self.cards)


def _lines(result) -> list[str]:  # noqa: ANN001
    return result.reply.text.split("\n")


LABOUR = [{"trade": "mason", "headcount": 7}, {"trade": "helper", "headcount": 12}]


async def test_the_open_card_is_changed_not_saved_twice(world):  # noqa: F811
    day = Day(world)
    first = FakeToolCallingProvider(
        [[("save_labour", {"workers": LABOUR})], "Sheri, 7 mason, 12 helper. Nokki Save tap cheyyu."]
    )
    result, gateway, facts = await day.say(first, "innu 7 mason 12 helper vannu")
    assert "Saved: 19 workers (7 mason, 12 helper)" in result.reply.text
    card = await day.cards.get(world.actor)
    assert card.state == c.OPEN and [i.summary for i in card.items] == ["19 workers (7 mason, 12 helper)"]

    edit = FakeToolCallingProvider(
        [
            [("update_pending_card", {"card_id": card.id, "item_index": 1, "changes": {"workers": [{"trade": "mason", "headcount": 8}]}})],
            "Sheri, 8 mason, 12 helper aakki. Nokki shariyenkil Save tap cheyyu.",
        ]
    )
    result, gateway, facts = await day.say(edit, "alla, 8 mason aanu")
    assert result.outcome == "ok", result.reply
    assert "Saved: 20 workers (8 mason, 12 helper)" in result.reply.text, result.reply.text
    assert result.reply.text.count("workers (") == 1  # one card line, not the old one as well
    assert day.withdrawn == [card.items[0].fact]  # the old draft was taken back
    assert len(facts) == 1 and facts != [card.items[0].fact]
    again = await day.cards.get(world.actor)
    assert again.state == c.OPEN and again.id != card.id
    assert [i.summary for i in again.items] == ["20 workers (8 mason, 12 helper)"]
    assert again.items[0].args["workers"][0]["headcount"] == 8


async def test_the_painters_undo_removes_the_painters_not_another_entry(world):  # noqa: F811
    day = Day(world)
    issue = FakeToolCallingProvider(
        [[("report_issue", {"issue_type": "OTHER", "narrative": "tap leaking in store room"})], "Sheri, issue note cheythu nokki Save tap cheyyu."]
    )
    _, _, issue_facts = await day.say(issue, "store room tap leaking")
    await day.tap(sb.SAVE, issue_facts)

    painters = FakeToolCallingProvider(
        [[("save_labour", {"workers": [{"trade": "painter", "headcount": 2}]})], "Sheri, 2 painter vannu. Nokki Save tap cheyyu."]
    )
    result, _, facts = await day.say(painters, "2 painter vannu")
    assert "Saved: 2 workers (2 painter)" in result.reply.text
    reply = await day.tap(sb.SAVE, facts)
    assert reply.text == "✅ Saved · 2 workers (2 painter)"
    card = await day.cards.get(world.actor)
    assert card.state == c.SAVED

    undo = FakeToolCallingProvider([[("undo_last", {})], "Sheri, painters-ne mattiyittund."])
    result, _, _ = await day.say(undo, "undo that")
    assert day.withdrawn == [facts[0]], "the painters, and nothing else"
    assert issue_facts[0] not in day.withdrawn
    assert result.reply.text.endswith("Removed: 2 workers (2 painter) (today)")
    assert await day.cards.get(world.actor) is None
    # and again: nothing is left to undo, said plainly
    nothing = FakeToolCallingProvider([[("undo_last", {})], "Ippo undo cheyyan onnumilla."])
    result, _, _ = await day.say(nothing, "undo")
    assert result.toolbox.system_lines == []
    assert day.withdrawn == [facts[0]]


async def test_a_forged_target_removes_nothing(world):  # noqa: F811
    day = Day(world)
    labour = FakeToolCallingProvider([[("save_labour", {"workers": LABOUR})], "Sheri, nokki Save tap cheyyu."])
    _, _, facts = await day.say(labour, "7 mason 12 helper vannu")
    await day.tap(sb.SAVE, facts)
    forged = FakeToolCallingProvider([[("undo_last", {"targets": ["deadbeef"]})], "Athu cheyyan pattilla."])
    result, _, _ = await day.say(forged, "undo that")
    assert day.withdrawn == []
    assert [c_.outcome.content["status"] for c_ in result.run.calls] == ["error"]


async def test_a_card_of_two_entries_asks_which_one(world):  # noqa: F811
    day = Day(world)
    both = FakeToolCallingProvider(
        [
            [
                ("save_labour", {"workers": [{"trade": "painter", "headcount": 2}]}),
                ("save_material_receipt", {"material": "cement", "quantity": 30, "unit": "bags"}),
            ],
            "Sheri, 2 painter, 30 bag cement. Nokki Save tap cheyyu.",
        ]
    )
    _, _, facts = await day.say(both, "2 painter vannu, 30 bag cement vannu")
    await day.tap(sb.SAVE, facts)
    undo = FakeToolCallingProvider([[("undo_last", {})], "Ethu venam?"])
    result, _, _ = await day.say(undo, "undo that")
    assert day.withdrawn == []
    rows = result.reply.list_rows
    assert rows and len(rows) == 3, result.reply
    assert [sb.parse_tap(r.id)[1] for r in rows[:2]] == [[facts[0]], [facts[1]]]
    # (the tap on a row is covered in the unit tests)


async def test_a_stock_question_has_no_save_footer(world):  # noqa: F811
    day = Day(world)
    provider = FakeToolCallingProvider(
        [[("query_materials", {"material": "cement"})], "Cement ippo und, nokkiyal mathi. Save tap cheyyu."]
    )
    result, _, _ = await day.say(provider, "cement ethra und")
    assert "Save" not in result.reply.text
    assert result.reply.buttons is None and result.reply.list_rows is None


async def test_both_report_phrasings_reach_the_pipeline_the_same_way(world):  # noqa: F811
    day = Day(world)
    seen = []
    for wording, date in (("send yesterday's report", "yesterday"), ("innale report ayakku", "innale"), ("innaleത്തെ report ayakku", "innaleത്തെ")):
        provider = FakeToolCallingProvider([[("request_dpr", {"date": date})], "Sheri, nokkaam."])
        result, gateway, _ = await day.say(provider, wording)
        seen.append(result.run.calls[0].outcome.content.get("text") or result.run.calls[0].outcome.content.get("message"))
    assert len(set(seen)) == 1, seen
