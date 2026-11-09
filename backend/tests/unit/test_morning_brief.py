"""GM-08 with TSK-05: one morning message -- act now, waiting for you, my tasks -- or none."""

from __future__ import annotations

import datetime

from mesiri.domains.attention.brief import compose

MON = datetime.date(2026, 11, 9)


def _t(ref, title, due, status="open"):
    return {"ref": ref, "title": title, "due_date": due, "status": status}


def test_all_three_parts_worst_first_in_the_persons_language():
    alerts = [{"title": "Handover forecast 6 days late", "project_name": "Marina"}, {"title": "Order steel today", "project_name": "Marina"},
              {"title": "x", "project_name": None}, {"title": "y", "project_name": None}]
    waiting = {"items": [{"title": "Ajay Tiling: bill B-3", "urgent": True, "project_name": "Villa"}]}
    tasks = [_t("T-1", "Tie steel grid B", MON), _t("T-2", "Water line", MON - datetime.timedelta(days=2)),
             _t("T-3", "Pump", MON + datetime.timedelta(days=3)), _t("T-4", "Old", MON - datetime.timedelta(days=5), "done")]
    msg = compose("Ilan Usman", "english", MON, alerts=alerts, waiting=waiting, tasks=tasks)
    assert msg.startswith("☀️ *Good morning, Ilan* · Mon 9 Nov")
    assert "🔴 *Act now (4)*\n• Handover forecast 6 days late (Marina)" in msg and "and 1 more" in msg
    assert "📥 *Waiting for you (1)*\n• ⚠️ Ajay Tiling: bill B-3 (Villa)" in msg
    assert "✅ *Your tasks*: 1 due today, 1 overdue, 1 more this week" in msg
    assert msg.index("T-2 Water line") < msg.index("T-1 Tie steel grid B") and "Old" not in msg
    assert msg.rstrip().endswith('Say "stop the morning message" to turn this off.')
    assert "Suprabhatham, Ilan" in compose("Ilan", None, MON, alerts=alerts, waiting=None, tasks=[])  # Manglish default


def test_nothing_to_say_sends_nothing():
    assert compose("Ilan", "english", MON, alerts=[], waiting={"items": []}, tasks=[_t("T-9", "Done", MON, "done")]) is None
