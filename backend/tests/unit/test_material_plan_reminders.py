"""MP-03: the order-by note (domains/materials/plan_reminders.py)."""

from __future__ import annotations

import datetime

from mesiri.domains.materials.plan_reminders import due, order_message

D = datetime.date
TODAY = D(2026, 11, 10)


def _row(material="Cement", order_by=D(2026, 11, 12), **kw):
    base = {"material": material, "unit": "bags", "short_by": "68.000", "short_day": D(2026, 11, 15),
            "on_hand": "100.000", "on_order": "20.000", "order_by": order_by, "supplier": None,
            "lead_days": 3, "lead_known": False}
    return {**base, **kw}


def test_note_lists_what_to_order_soon_with_the_day_and_supplier():
    note = order_message("Kondotty Commercial", [
        _row(), _row("Steel 12 mm", order_by=D(2026, 11, 10), unit="kg", short_by="420", supplier="Malabar", lead_days=5, lead_known=True),
    ], TODAY)
    assert note.startswith("📦 *Kondotty Commercial*: materials to order")
    first, second = note.split("\n")[1:3]
    assert first.startswith("• *Steel 12 mm*: 420 kg more needed") and "Order by today, Malabar takes 5 days." in first
    assert "*Cement*: 68 bags more needed, short from Sun 15 Nov (120 in stock and ordered). Order by Thu 12 Nov." in second
    assert "Planning › Material plan" in note


def test_nothing_due_soon_means_no_note_and_overdue_says_so():
    assert order_message("P", [_row(order_by=D(2026, 11, 20)), _row(order_by=None)], TODAY) is None
    assert [r["material"] for r in due([_row("A", order_by=D(2026, 11, 13)), _row("B")], TODAY)] == ["B"]
    note = order_message("P", [_row(order_by=D(2026, 11, 7))], TODAY)
    assert "Order by today (it should have gone Sat 7 Nov)." in note
