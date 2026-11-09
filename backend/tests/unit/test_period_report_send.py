"""RPT-01 / PRC-20 unit tests: the brief's rows and summary, the WhatsApp message, the schedule's MONTHLY (no database).

- MONTHLY fires on the 1st only (an unknown frequency would fire every day: the guard).
- A brief row is the project's own report: worst first by what needs attention; no money for a role without it.
- The message names the report, carries the headline, the figures, the note and the link, inside WhatsApp's limit.
- The template gets exactly its three parameters; "what changed since sent" lists only moved figures.
"""

from __future__ import annotations

import datetime

from mesiri.application.automations.scheduling import is_due
from mesiri.domains.reports.period import periods, portfolio, send

UTC = datetime.UTC


def _due(freq: str, day: datetime.date, dow: int | None = None) -> bool:
    now = datetime.datetime.combine(day, datetime.time(9, 0), tzinfo=UTC)
    return is_due(frequency=freq, day_of_week=dow, time_of_day="08:00", timezone_name="UTC", last_run_on=None,
                  now_utc=now)


def test_monthly_fires_on_the_first_only_and_weekly_on_its_day():
    assert _due("MONTHLY", datetime.date(2026, 12, 1))
    assert not _due("MONTHLY", datetime.date(2026, 12, 2))
    assert _due("WEEKLY", datetime.date(2026, 11, 16), dow=0) and not _due("WEEKLY", datetime.date(2026, 11, 17), dow=0)


def _report(name, statuses, *, overdue="0.00", facts=("A fact.",), needs=1, money=True):
    keys = ("work", "schedule", "money", "issues")
    areas = [{"key": k, "status": st} for k, st in zip(keys, statuses, strict=True)]
    return {
        "project": {"id": name.lower(), "name": name, "client": None},
        "areas": areas,
        "needs_you": [{"title": f"{name} item"}] * needs,
        "headline": {"lead": "Lead.", "facts": list(facts)},
        "sections": {
            "work": {"progress_to_date": 40, "expected_to_date": "50.0", "done_pct": "5.0", "plan_pct": "6.0",
                     "status": statuses[0]},
            "schedule": {"status": statuses[1], "forecast_finish": "2027-03-01", "slip_days": 3},
            "labour": {"man_days": "120"},
            **({"money": {"status": statuses[2], "labour_colour": "red", "spent": "100000.00", "billed": "50000.00",
                          "received": "20000.00", "owed": "300000.00", "overdue": overdue,
                          "oldest_overdue_days": 40}} if money else {}),
            "issues": {"open": 2, "serious_open": 1},
        },
    }


def test_rows_are_worst_first_and_the_summary_adds_only_what_exists():
    rows = [portfolio.row_of(_report("Aluva", ("good", "good", "good", "good"))),
            portfolio.row_of(_report("Edappally", ("bad", "bad", "bad", "warn"), overdue="80000.00")),
            portfolio.row_of(_report("Kakkanad", ("good", "warn", "good", "good")))]
    rows.sort(key=lambda r: (-r["attention"], r["name"].lower()))
    assert [r["name"] for r in rows] == ["Edappally", "Kakkanad", "Aluva"]
    assert rows[0]["status"] == "bad" and rows[0]["top"] == "Edappally item"
    s = portfolio.summarise(rows, sees_money=True, noun="week")
    assert s["headline"]["lead"] == "3 projects, 2 need you."
    assert s["headline"]["facts"][0] == "Edappally: A fact."
    assert "Clients owe ₹9.0 L, ₹80,000 of it over 30 days." in s["headline"]["facts"]
    assert s["totals"]["man_days"] == "360" and s["totals"]["open_issues"] == 6
    assert {k["key"] for k in s["kpis"]} >= {"spent", "owed", "man_days", "issues"}


def test_a_role_without_money_gets_no_money_in_the_brief():
    rows = [portfolio.row_of(_report("Aluva", ("good", "good", "none", "good"), money=False))]
    s = portfolio.summarise(rows, sees_money=False, noun="month")
    assert all(k["key"] not in ("spent", "billed", "owed") for k in s["kpis"])
    assert rows[0]["spent"] is None and "₹" not in str(s)
    assert portfolio.summarise([], sees_money=True, noun="week")["headline"]["lead"] == "No running projects to report on."


def _sample():
    return {"period": periods.week_of(datetime.date(2026, 11, 4)).as_dict(), "running": False,
            "headline": {"lead": "Work is behind plan.", "facts": ["Finishes is 3 days late.", "1 serious issue."]},
            "kpis": [{"label": "Work done", "value": "7.5%", "note": "plan 17.5%"},
                     {"label": "Man-days", "value": "18", "note": ""}]}


def test_the_message_names_the_report_and_carries_note_and_link():
    p = periods.week_of(datetime.date(2026, 11, 4))
    link = send.page_link("project", p, "p1")
    assert link.endswith("/reports/period?project=p1&period=week&date=2026-11-02")
    text = send.message_text(_sample(), where="Villa Kakkanad", link=link,
                             note={"text": "Rain on Thursday", "by": "Sajan"})
    assert text.startswith("*Weekly report · Villa Kakkanad*\nWeek 45, 2 – 8 Nov 2026")
    assert "Work is behind plan. Finishes is 3 days late." in text
    assert "• Work done: 7.5% (plan 17.5%)" in text and "• Man-days: 18" in text
    assert "Note from Sajan: Rain on Thursday" in text and text.endswith(link)
    long = {**_sample(), "headline": {"lead": "x" * 900, "facts": ["y" * 400]}}
    assert len(send.message_text(long, where="V", link=link, note=None)) <= 1000


def test_template_params_and_file_name():
    params = send.template_params(_sample(), "Villa Kakkanad")
    assert params == ["Weekly", "Villa Kakkanad, Week 45 (2 – 8 Nov 2026)", "Work is behind plan. Finishes is 3 days late."]
    p = periods.month_of(datetime.date(2026, 10, 9))
    assert send.file_name("Villa Kakkanad · Main", p) == "Villa-Kakkanad-Main-2026-10.pdf"
    assert send.file_name("All projects", periods.week_of(datetime.date(2026, 11, 4))) == "All-projects-week-45.pdf"


def test_changed_since_lists_only_moved_figures():
    sent = {"kpis": [{"key": "man_days", "label": "Man-days", "value": "18"},
                     {"key": "spent", "label": "Spent", "value": "₹60,000"}]}
    now = {"kpis": [{"key": "man_days", "label": "Man-days", "value": "24"},
                    {"key": "spent", "label": "Spent", "value": "₹60,000"}]}
    assert send.changed_since(sent, now) == [{"label": "Man-days", "sent": "18", "now": "24"}]


def test_delivery_reasons_read_as_words():
    assert "template is approved" in send.reason_words("template_not_approved:mesiri_period_report")
    assert "template is approved" in send.reason_words("outside_whatsapp_session_window_needs_template")
    assert send.reason_words("opted_out") == "they turned these messages off"
    assert send.reason_words(None) is None
