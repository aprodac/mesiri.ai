"""Request 171: a stock count / a shortage for a material the books still show is an
adjustment for the difference (never a fake "used"), asked on the card, written only on Save;
inventory replies flag a negative balance; "what to get" lists the open needs."""

from __future__ import annotations

from typing import Any

from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.agent.material_entry import AWAIT_COUNT, Ready, Say
from runtime.open_needs import needs_reply, request_text
from workflows.material_inventory_query.nodes import generate_inventory_reply

from .test_material_entry import SAND, _actor, _Catalog, _entry, _prepare


class _Books:
    """The saved stock: Cement 176 bags, as in the Paraclette report."""

    def __init__(self, stock: float | None = 176.0, unit: str = "bag") -> None:
        self.stock, self.unit = stock, unit
        self.calls: list[dict] = []

    async def query(self, **kwargs: Any) -> list[dict]:
        self.calls.append(kwargs)
        if self.stock is None:
            return []
        return [{"current_stock": self.stock, "unit": self.unit, "material_name": "Cement"}]


def _manager():
    return _actor("44444444-4444-4444-8444-444444444444", role="PROJECT_MANAGER")


async def test_a_count_below_the_books_is_an_adjustment_out_for_the_difference():
    books = _Books(176)
    ready = await _prepare(_entry(stock=books, actor=_manager()), direction="stock_count", quantity=20)
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.MATERIAL_USAGE
    f = ready.event.fields
    assert (f["quantity"], f["movement_reason"], f["counted"], f["book_stock"]) == (156.0, "ADJUSTMENT_OUT", 20.0, 176.0)
    assert f["notes"] == "Stock count: records 176, counted 20 bags"
    # saved figures only: an unsaved card line is not stock yet
    assert books.calls[0].get("include_unsaved", False) is False


async def test_finished_sets_the_books_to_zero():
    ready = await _prepare(_entry(stock=_Books(176), actor=_manager()), direction="stock_count", quantity=0)
    assert isinstance(ready, Ready)
    assert ready.event.fields["quantity"] == 176.0 and ready.event.fields["movement_reason"] == "ADJUSTMENT_OUT"


async def test_a_count_above_the_books_is_an_adjustment_in():
    ready = await _prepare(_entry(stock=_Books(10), actor=_manager()), direction="stock_count", quantity=25)
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.MATERIAL_RECEIPT
    assert (ready.event.fields["quantity"], ready.event.fields["movement_reason"]) == (15.0, "ADJUSTMENT_IN")


async def test_a_negative_book_is_brought_up_to_the_count():
    ready = await _prepare(_entry(stock=_Books(-10), actor=_manager()), direction="stock_count", quantity=0)
    assert isinstance(ready, Ready)
    assert (ready.event.fields["quantity"], ready.event.fields["movement_reason"]) == (10.0, "ADJUSTMENT_IN")


async def test_a_count_equal_to_the_books_changes_nothing():
    said = await _prepare(_entry(stock=_Books(20), actor=_manager()), direction="stock_count", quantity=20)
    assert isinstance(said, Say) and said.text.startswith("Nothing to change")


async def test_only_an_admin_or_project_manager_may_count():
    said = await _prepare(_entry(stock=_Books(176)), direction="stock_count", quantity=0)  # a site engineer
    assert isinstance(said, Say) and "only an admin or project manager" in said.text


async def test_a_shortage_for_a_material_with_stock_asks_with_the_records():
    said = await _prepare(_entry(stock=_Books(176), actor=_manager()), direction="stock_count", quantity=None, reconcile=True)
    assert isinstance(said, Say)
    assert said.question == "Records show 176 bag Cement. Set stock to 0?"
    assert list(said.options) == ["Set to 0", "Enter count", "Keep"] and said.awaiting == AWAIT_COUNT


async def test_a_shortage_for_a_material_the_books_show_empty_asks_nothing():
    said = await _prepare(_entry(stock=_Books(0), actor=_manager()), direction="stock_count", quantity=None, reconcile=True)
    assert isinstance(said, Say) and not said.question and said.text == ""
    negative = await _prepare(_entry(stock=_Books(-20), actor=_manager()), direction="stock_count", quantity=None, reconcile=True)
    assert isinstance(negative, Say) and not negative.question


async def test_a_shortage_for_an_unlisted_material_asks_nothing():
    said = await _prepare(
        _entry(catalog=_Catalog([SAND]), stock=_Books(5), actor=_manager()),
        material_name="cement",
        direction="stock_count",
        quantity=None,
        reconcile=True,
    )
    assert isinstance(said, Say) and not said.question and said.text == ""


async def test_an_ordinary_receipt_is_untouched_by_the_count_path():
    ready = await _prepare(_entry(stock=_Books(176)), quantity=50)
    assert isinstance(ready, Ready)
    assert "movement_reason" not in ready.event.fields and "counted" not in ready.event.fields


# -- negative balances are flagged ---------------------------------------------------


def _reply(levels: list[dict], **fields: Any) -> str:
    out = generate_inventory_reply({"collected_fields": {"inventory_levels": levels, **fields}})
    return out["pending_prompt"]


def test_the_stock_list_flags_a_negative_balance_never_a_bare_minus():
    levels = [
        {"material_name": "cement", "unit": "bag", "received": 176, "used": 0, "current_stock": 176},
        {"material_name": "m sand", "unit": "cum", "received": 0, "used": 20, "current_stock": -20},
    ]
    text = _reply(levels)
    assert "Cement — 176 bag" in text
    assert "⚠️ M Sand −20 cum (used more than received: record a delivery?)" in text
    assert "— -20" not in text


def test_one_material_with_a_negative_balance_is_flagged():
    text = _reply(
        [{"material_name": "bricks", "unit": "nos", "received": 0, "used": 500, "current_stock": -500}], material_name="bricks"
    )
    assert "⚠️ Bricks −500 nos" in text and "In stock: -500" not in text


# -- what to get ---------------------------------------------------------------------


def test_the_request_is_read_from_the_engineers_message():
    message = "📦 Material request from Adarsh for Tower A:\n50 nails (needed tomorrow)\n\nPlease reply to Adarsh directly."
    assert request_text(message) == "50 nails (needed tomorrow)"


def test_open_needs_lists_requests_and_what_is_out_without_the_whole_inventory():
    text = needs_reply(
        requests=[{"request": "50 nails (needed tomorrow)"}, {"request": "ladder"}],
        shortages=[{"narrative": "Cement stock kazhinju"}],
        levels=[
            {"material_name": "cement", "unit": "bag", "current_stock": 176},
            {"material_name": "laterite stone", "unit": "nos", "current_stock": 0},
            {"material_name": "m sand", "unit": "cum", "current_stock": -20},
        ],
    )
    assert "50 nails (needed tomorrow)" in text and "ladder" in text
    assert "Laterite Stone" in text
    assert "⚠️ M Sand −20 cum" in text
    assert "Cement stock kazhinju" in text  # reported, and the books still show 176
    assert "176" not in text  # not an inventory dump


def test_open_needs_does_not_repeat_a_shortage_for_a_material_already_out():
    text = needs_reply(
        requests=[],
        shortages=[{"narrative": "Laterite stone theernnu"}],
        levels=[{"material_name": "laterite stone", "unit": "nos", "current_stock": 0}],
    )
    assert text.count("Laterite") == 1 and "Shortages reported" not in text


def test_open_needs_with_nothing_open_says_so():
    assert needs_reply(requests=[], shortages=[], levels=[{"material_name": "cement", "unit": "bag", "current_stock": 5}]).startswith(
        "Nothing is open"
    )


def test_the_inventory_workflow_answers_open_needs_even_with_no_stock_rows():
    text = _reply([], view="open_needs", open_requests=[{"request": "ladder"}])
    assert "ladder" in text


def test_a_material_asked_not_delivered_is_dropped_once_received():
    from datetime import date

    from runtime.open_needs import _delivered

    asked = date(2026, 10, 30)
    receipts = [{"material_name": "Nails", "site_id": "s1", "occurred_date": date(2026, 10, 31)}]
    assert _delivered("50 nails (needed tomorrow)", "s1", asked, receipts) is True
    assert _delivered("50 nails", "s2", asked, receipts) is False  # another site
    assert _delivered("ladder", "s1", asked, receipts) is False
    assert _delivered("50 nails", "s1", date(2026, 11, 2), receipts) is False  # received before it was asked
