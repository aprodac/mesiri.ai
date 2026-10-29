"""WA-52 (live 23 Oct): a stock question is answered from the stock records.

"nale slab-inu cement mathiyo?" got "I'll ask your engineer", and "nale 10
bagcement venm ath stock undo?" was filed as a Material Shortage card. A
question goes to the engineer only when the sender asks for that; a stock
question is never a problem on site.
"""

from __future__ import annotations

import datetime as dt

import pytest

from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import SemanticType
from runtime.agent import runner as r
from runtime.agent import toolbox as tb
from runtime.agent.gateway import StepResult
from runtime.agent.prompt import AgentContext
from runtime.agent.reply_text import promises_engineer, without_engineer_promise
from runtime.agent.tools import ScopeLookup

STOCK = "Cement: 368 bags in stock (received 870, used 502)."
SCREENSHOT = "nale 10 bagcement venm ath stock undo?"


class Gateway:
    """Answers a stock lookup; saves anything else."""

    def __init__(self) -> None:
        self.runs: list = []

    async def run(self, candidate, *, text):  # noqa: ANN001, ANN202
        self.runs.append(candidate)
        if candidate.semantic_type is SemanticType.INVENTORY_QUERY:
            return StepResult("answer", text=STOCK)
        return StepResult("saved", text="noted", summary="Issue (material shortage): x")

    def lookups(self) -> list:
        return [c for c in self.runs if c.semantic_type is SemanticType.INVENTORY_QUERY]

    def saves(self) -> list:
        return [c for c in self.runs if c.semantic_type is not SemanticType.INVENTORY_QUERY]


def _box(text: str, gateway: Gateway | None = None) -> tuple[tb.AgentToolbox, Gateway]:
    gateway = gateway or Gateway()
    return tb.AgentToolbox(gateway=gateway, scope=ScopeLookup(), user_text=text), gateway


# -- what counts as a stock question -------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "nale slab-inu cement mathiyo?",
        SCREENSHOT,
        "is there enough cement for tomorrow's slab?",
        "cement stock ethra",
        "നാളെ സ്ലാബിന് സിമന്റ് മതിയോ?",
        "cement stock hai kya",
    ],
)
def test_stock_questions(text):
    assert tb.asks_about_stock(text)


@pytest.mark.parametrize(
    "text",
    [
        "10 bag cement balance und, kooduthal venam",
        "cement not enough, work stopped",
        "engineer-inodu chodikku, nale slab concrete cheyyamo?",
        "how many workers today?",
        "50 bags cement vannu",
    ],
)
def test_not_stock_questions(text):
    assert not tb.asks_about_stock(text)


def test_the_material_is_taken_from_the_message():
    assert tb.material_named(SCREENSHOT) == "cement"
    assert tb.material_named("നാളെ സിമന്റ് മതിയോ?") == "cement"
    assert tb.material_named("cement and sand enough?") is None  # several: all stock


# -- the engineer note ---------------------------------------------------------


async def test_a_stock_question_sent_to_the_engineer_gets_the_stock_instead():
    box, gateway = _box("nale slab-inu cement mathiyo?")
    out = await box.handle("note_for_engineer", {"question": "nale slab-inu cement mathiyo?"})
    assert out.content["status"] == "not_asked_to_pass_on"
    assert out.content["stock"] == STOCK
    assert [c.fields.get("material_name") for c in gateway.lookups()] == ["cement"]
    assert gateway.saves() == [] and box.saved == []
    assert box.answers == [STOCK]


async def test_a_stock_answer_already_given_is_not_looked_up_twice():
    box, gateway = _box("nale slab-inu cement mathiyo?")
    await box.handle("query_materials", {"material": "cement"})
    out = await box.handle("note_for_engineer", {"question": "x"})
    assert out.content["stock"] == STOCK
    assert len(gateway.lookups()) == 1


async def test_asked_for_the_engineer_it_still_goes_to_the_engineer():
    box, gateway = _box("engineer-inodu chodikku, nale slab-inu cement mathiyo?")
    out = await box.handle("note_for_engineer", {"question": "nale slab-inu cement mathiyo?"})
    assert out.content["status"] == "saved"  # request 104: a Send card, sent on the tap
    assert gateway.lookups() == []


# -- a stock question is not a shortage ----------------------------------------


async def test_the_screenshot_question_is_not_filed_as_a_shortage():
    box, gateway = _box(SCREENSHOT)
    out = await box.handle(
        "report_issue", {"issue_type": "MATERIAL_SHORTAGE", "narrative": "10 bag cement needed for tomorrow. Is it in stock?"}
    )
    assert out.content["status"] == "not_saved"
    assert out.content["stock"] == STOCK
    assert gateway.saves() == [] and box.saved == [] and box.attempted_writes == 0


@pytest.mark.parametrize(
    "text",
    ["cement theernnu, stock undo?", "cement ran out, is there stock?", "cement theernnu, pani ninnu, 50 bag venam"],
)
async def test_a_real_shortage_is_still_reported(text):
    box, gateway = _box(text)
    out = await box.handle("report_issue", {"issue_type": "MATERIAL_SHORTAGE", "narrative": text})
    assert out.content["status"] == "saved"
    assert len(gateway.saves()) == 1


@pytest.mark.parametrize(
    "text,quantity", [("nale 50 bag cement order cheyyanam", 50), ("order 100 bags cement", 100)]
)
async def test_an_order_is_never_an_issue(text, quantity):
    """Request 143 (E): material to order is a material request, not a site issue. Live 29
    Oct (runtime/agent/reroute.py): the code makes the request from their words in the same
    turn; it no longer tells the model to, which it did not always do."""
    box, gateway = _box(text)
    await box.handle("report_issue", {"issue_type": "MATERIAL_SHORTAGE", "narrative": text})
    (saved,) = gateway.saves()
    assert saved.fields["_action"] == "material_request"
    assert (saved.fields["material"].lower(), saved.fields["quantity"]) == ("cement", quantity)


async def test_an_order_whose_figure_is_the_stock_left_goes_back_to_the_model():
    """"10 bag cement balance und, kooduthal venam": 10 is what is left, not the order."""
    text = "10 bag cement balance und, kooduthal venam"
    box, gateway = _box(text)
    out = await box.handle("report_issue", {"issue_type": "MATERIAL_SHORTAGE", "narrative": text})
    assert out.content["status"] == "not_saved" and "request_material" in out.content["instruction"]
    assert gateway.saves() == []


# -- the reply -----------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    ["I'll ask your engineer.", "I have passed this to your engineer.", "Engineer-inodu chodikkam.", "എഞ്ചിനീയറോട് ചോദിക്കാം."],
)
def test_promises_to_ask_the_engineer(sentence):
    assert promises_engineer(sentence)


@pytest.mark.parametrize("sentence", ["Shall I ask your engineer?", "Cement: 368 bags in stock."])
def test_not_promises(sentence):
    assert not promises_engineer(sentence)


def test_the_promise_goes_and_the_answer_stays():
    text = "Cement 368 bags in stock. I'll ask your engineer about the slab."
    assert without_engineer_promise(text) == "Cement 368 bags in stock."


def test_only_an_offer_makes_a_yes_pass_it_on():
    assert tb.offers_engineer("The records don't show that. Shall I ask your engineer?")
    assert not tb.offers_engineer("Saved.\n📨 Question for your engineer: nale slab cheyyamo?")
    assert not tb.offers_engineer("Your engineer closed that issue.")


CTX = AgentContext(
    user_name="Adarsh", role="SUPERVISOR", company="Acme", now=dt.datetime(2026, 10, 23, 5, 30),
    projects=(("Hospital Project", None),), sites=(("Tower A", "Hospital Project"),),
)


async def test_end_to_end_the_engineer_promise_never_goes_out():
    """The model tries the engineer note, then says it will ask: the reply
    carries the stock and no promise."""
    provider = FakeToolCallingProvider(
        [
            [("note_for_engineer", {"question": "is there enough cement for tomorrow's slab?"})],
            "I'll ask your engineer and get back to you.",
        ]
    )
    gateway = Gateway()
    result = await r.AgentRunner(provider).run(
        ctx=CTX, user_text="is there enough cement for tomorrow's slab?", gateway=gateway, scope=ScopeLookup()
    )
    text = result.reply.text
    assert "368" in text
    assert "ask your engineer" not in text
    assert gateway.saves() == []


async def test_end_to_end_the_screenshot_message_gets_no_card():
    provider = FakeToolCallingProvider(
        [
            [("report_issue", {"issue_type": "MATERIAL_SHORTAGE", "narrative": "10 bag cement needed for tomorrow"})],
            "Cement: 368 bags in stock, enough for 10 bags.",
        ]
    )
    gateway = Gateway()
    result = await r.AgentRunner(provider).run(ctx=CTX, user_text=SCREENSHOT, gateway=gateway, scope=ScopeLookup())
    assert gateway.saves() == []
    assert not result.reply.buttons
    assert "368" in result.reply.text
