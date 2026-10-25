"""WA-77: stock shown on WhatsApp is what is saved, but the over-stock hint
while capturing still counts what was reported and not saved yet."""

from __future__ import annotations

import inspect

from runtime.agent.material_entry import MaterialEntry
from runtime.inbound_journey import seeding
from runtime.inventory_query import MaterialInventoryQueryService


def test_stock_answers_leave_out_unsaved_by_default():
    assert inspect.signature(MaterialInventoryQueryService.query).parameters["include_unsaved"].default is False


def test_the_over_stock_hint_counts_unsaved_entries():
    assert "include_unsaved=True" in inspect.getsource(MaterialEntry)
    assert "include_unsaved=True" in inspect.getsource(seeding)
