"""PRC-19 unit tests: the period report's dates, rules, engine and outputs (no database).

- periods: a week is Monday to Sunday, a month is a calendar month, the default is the last finished one, custom is
  capped, the previous period has the same length.
- work numbers: done and planned in the period weighted the Gantt's way; no plan is "none", never "good".
- headline / kpis / areas / needs you: made only from section figures; the worst first.
- engine: a failing section is named and hides nothing; a 403 section is left out quietly; money is never read for
  a role that does not see spending; a switched-off module's section is not read.
- outputs: the PDF and the Excel render the same report (rupees as "Rs" in the PDF's core fonts).
"""

from __future__ import annotations

import contextlib
import datetime
import io
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from mesiri.domains.reports.period import engine, headline, periods, sections

D = datetime.date


# -- periods ----------------------------------------------------------------------------------------------------------

def test_week_is_monday_to_sunday_and_defaults_to_the_last_finished_week():
    today = D(2026, 11, 9)  # a Monday
    p = periods.resolve("week", today)
    assert (p.start, p.end) == (D(2026, 11, 2), D(2026, 11, 8))
    assert p.label == "Week 45" and p.range_text == "2 – 8 Nov 2026"
    anchored = periods.resolve("week", today, anchor=D(2026, 11, 11))
    assert (anchored.start, anchored.end) == (D(2026, 11, 9), D(2026, 11, 15))


def test_month_defaults_to_last_month_and_previous_steps_a_calendar_month():
    p = periods.resolve("month", D(2026, 11, 1))
    assert (p.start, p.end, p.label) == (D(2026, 10, 1), D(2026, 10, 31), "October 2026")
    prev = periods.previous(p)
    assert (prev.start, prev.end) == (D(2026, 9, 1), D(2026, 9, 30))
    assert periods.following(periods.resolve("month", D(2026, 1, 15), anchor=D(2026, 1, 3))).start == D(2026, 2, 1)


def test_custom_needs_both_dates_and_is_capped():
    with pytest.raises(ValueError, match="both dates"):
        periods.resolve("custom", D(2026, 11, 9), date_from=D(2026, 11, 1))
    with pytest.raises(ValueError, match="before"):
        periods.resolve("custom", D(2026, 11, 9), date_from=D(2026, 11, 5), date_to=D(2026, 11, 1))
    with pytest.raises(ValueError, match="at most"):
        periods.resolve("custom", D(2026, 11, 9), date_from=D(2026, 1, 1), date_to=D(2026, 11, 1))
    p = periods.resolve("custom", D(2026, 11, 9), date_from=D(2026, 11, 3), date_to=D(2026, 11, 12))
    prev = periods.previous(p)
    assert prev.days == p.days == 10 and prev.end == D(2026, 11, 2)


def test_trend_is_oldest_first_and_ends_with_the_period():
    p = periods.week_of(D(2026, 11, 4))
    t = periods.trend(p, 8)
    assert len(t) == 8 and t[-1] == p and t[0].start == D(2026, 9, 14)
    assert periods.range_text(D(2025, 12, 29), D(2026, 1, 4)) == "29 Dec 2025 – 4 Jan 2026"


# -- work numbers -----------------------------------------------------------------------------------------------------

def _line(id_, planned, rate):
    return {"id": id_, "planned_quantity": Decimal(planned), "client_rate": Decimal(rate) if rate else None,
            "work_type": "w", "unit": "m3"}


def test_done_and_planned_in_the_period_are_weighted_by_contract_value():
    a, b = uuid.uuid4(), uuid.uuid4()
    lines = [_line(a, 100, 300), _line(b, 100, 100)]  # a weighs 3, b weighs 1
    acts = [{"id": 1, "site_id": None, "start": D(2026, 11, 1), "end": D(2026, 11, 10), "milestone": False,
             "lines": [{"id": a}]},
            {"id": 2, "site_id": None, "start": None, "end": None, "lines": [{"id": b}]}]
    work = [{"line_id": a, "work_date": D(2026, 11, 3), "site_id": None, "quantity": Decimal(20)},
            {"line_id": b, "work_date": D(2026, 11, 4), "site_id": None, "quantity": Decimal(40)},
            {"line_id": a, "work_date": D(2026, 10, 30), "site_id": None, "quantity": Decimal(50)},  # before
            {"line_id": b, "work_date": D(2026, 11, 5), "site_id": None, "quantity": None}]  # other unit
    n = sections.work_numbers(acts, lines, work, periods.week_of(D(2026, 11, 4)), D(2026, 11, 9), lambda s: True)
    # (3 * 0.2 + 1 * 0.4) / 4 = 25%
    assert n["done_pct"] == Decimal(25) and n["other_unit"] == 1
    # activity 1: 10 days from 1 Nov; the week 2-8 Nov holds 7 of them -> 3/4 * 0.7 = 52.5%
    assert n["plan_pct"].quantize(Decimal("0.1")) == Decimal("52.5")
    assert sections.work_status(n["done_pct"], n["plan_pct"]) == "bad"


def test_no_plan_is_none_never_good():
    assert sections.work_status(Decimal(5), None) == "none"
    assert sections.work_status(None, Decimal(5)) == "none"
    assert sections.work_status(Decimal(5), Decimal(5)) == "good"
    assert sections.work_status(Decimal(4), Decimal(5)) == "warn"


def test_photos_are_spread_over_the_period_keeping_the_first_and_last():
    items = [{"n": i} for i in range(20)]
    picked = sections.spread(items, 6)
    assert len(picked) == 6 and picked[0]["n"] == 0 and picked[-1]["n"] == 19
    assert sections.spread(items[:3], 6) == items[:3]


# -- rules ------------------------------------------------------------------------------------------------------------

def _sections():
    return {
        "work": {"key": "work", "title": "Work", "status": "good", "done_pct": "6.4", "plan_pct": "5.5",
                 "progress_to_date": 58, "expected_to_date": "55.0", "has_plan": True, "lines_worked": 4,
                 "work_in_other_unit": 0, "rows": []},
        "schedule": {"key": "schedule", "title": "Schedule", "status": "warn", "forecast_finish": "2027-03-12",
                     "planned_finish": "2027-03-09", "slip_days": 3, "scheduled": 5, "counts": {},
                     "rows": [{"activity": "Internal plastering", "site": None, "state": "behind", "days_late": 0,
                               "slip_days": 3, "critical": True, "forecast_end": "2026-11-20", "end": "2026-11-17",
                               "assigned_to": "Sajan", "open_issues": 0, "progress": 31, "expected": 40}]},
        "labour": {"key": "labour", "title": "Labour", "status": "good", "man_days": "412", "prev_man_days": "438",
                   "change_pct": "-5.9", "wages": "186000.00",
                   "by_trade": [{"label": "Mason", "man_days": "180"}], "by_day": [],
                   "by_site": [], "trend": [{"man_days": "400"}, {"man_days": "412"}]},
        "stock_value": {"key": "stock_value", "title": "Stock value", "status": "good", "total": "120000.00", "items": 4,
                        "unpriced": 0, "slow_moving": 0, "slow_moving_value": "0.00", "by_category": [], "top": [],
                        "link": "/materials/value"},
        "materials": {"key": "materials", "title": "Materials", "status": "warn", "received_items": 3,
                      "used_items": 5, "running_low": 1,
                      "rows": [{"material": "Cement", "unit": "bag", "category": "Cement", "running_low": True,
                                "days_left": 3, "opening": "100", "received": "200", "used": "260",
                                "closing": "40", "site": "Site B", "spend": "84000.00"}]},
        "money": {"key": "money", "title": "Money", "status": "bad", "spent": "980000.00", "prev_spent": "900000.00",
                  "change_pct": "8.9", "labour_colour": "red", "centres": [],
                  "worst_lines": [{"work": "Plastering", "colour": "red", "difference": "-6400.00",
                                   "labour_cost": "12800.00", "earned_labour": "6400.00", "done_quantity": "180",
                                   "unit": "sqft", "section": "Finishes", "reason": None}],
                  "billed": "620000.00", "received": "210000.00", "owed": "400000.00", "overdue": "400000.00",
                  "oldest_overdue_days": 47,
                  "overdue_bills": [{"ref": "RA-3", "left": "400000.00", "days": 47, "bill_date": "2026-09-23"}],
                  "bills_link": "/billing/receivables", "link": "/cost"},
        "issues": {"key": "issues", "title": "Issues", "status": "warn", "raised": 2, "closed": 1, "open": 1,
                   "serious_open": 0, "rows": [{"id": "i1", "type": "quality", "severity": "medium", "what": "Crack",
                                                "site": None, "since": "2026-11-07", "days_open": 2}]},
        "completeness": {"key": "completeness", "title": "Is the data complete?", "status": "warn",
                         "days_total": 7, "days_full": 6, "days_missing": ["2026-11-05"],
                         "days_no_attendance": ["2026-11-05"], "sites": 1, "days": [], "link": "/reports"},
    }


def test_headline_uses_only_section_figures_worst_first():
    h = headline.headline(_sections(), "week")
    assert h["lead"] == "Good progress on site; money needs a look."
    assert h["facts"][0] == "Internal plastering is on pace to finish 3 days late (on the critical path)."
    assert "₹4.0 L of RA-3 unpaid for 47 days." in h["facts"] + h["more"]
    assert "6.4% of the job done against 5.5% planned." in h["facts"] + h["more"]
    assert len(h["facts"]) == headline.MAX_FACTS


def test_lead_without_a_plan_never_says_good():
    s = {"work": {"status": "none", "has_plan": False}}
    assert headline.lead(s["work"], None, "week") == "Here is the week."


def test_kpis_compare_with_plan_and_last_period():
    k = {x["key"]: x for x in headline.kpis(_sections())}
    assert k["work"]["value"] == "6.4%" and k["work"]["note"] == "plan 5.5%" and k["work"]["tone"] == "good"
    assert k["man_days"]["note"] == "▼ 5.9% vs last period" and k["man_days"]["trend"] == ["400", "412"]
    assert k["spent"]["value"] == "₹9.8 L" and k["spent"]["tone"] == "bad"
    assert k["finish"]["note"] == "+3 days"
    assert len(k) == 5


def test_kpis_for_a_role_without_money_fill_with_materials_and_issues():
    s = _sections()
    del s["money"]
    keys = [x["key"] for x in headline.kpis(s)]
    assert "spent" not in keys and "billed" not in keys and "low" in keys


def test_needs_you_puts_the_worst_first_and_keeps_inbox_items():
    waiting = [{"kind": "wage_sheet", "title": "Wages 2–8 Nov", "detail": "Draft", "urgent": False}]
    items = headline.needs_you(_sections(), waiting)
    assert items[0]["level"] in ("bad", "warn") and items[-1]["kind"] in ("wage_sheet", "missing_days")
    kinds = [i["kind"] for i in items]
    assert {"overdue_bill", "red_line", "late_activity", "running_low", "missing_days", "wage_sheet"} <= set(kinds)


def test_areas_have_one_line_each():
    a = {x["key"]: x for x in headline.areas(_sections())}
    assert a["work"]["note"].startswith("6.4% of the job done against 5.5% planned")
    assert "₹4.0 L unpaid over 30 days" in a["money"]["note"]
    assert a["completeness"]["note"].startswith("6 of 7 days")


def test_inr_reads_like_a_builder():
    assert headline.inr("12400") == "₹12,400"
    assert headline.inr("420000") == "₹4.2 L"
    assert headline.inr("23100000") == "₹2.31 Cr"
    assert headline.inr(None) == "—"


# -- engine -----------------------------------------------------------------------------------------------------------

class _Conn:
    def begin_nested(self):
        @contextlib.asynccontextmanager
        async def nested():
            yield

        return nested()


class _Auth:
    def __init__(self, role="ADMIN"):
        self.organization_id = uuid.uuid4()
        self.user_id = uuid.uuid4()
        self.role = role


@pytest.fixture
def stubbed(monkeypatch):
    pid = uuid.uuid4()
    read: list[str] = []

    async def project(conn, auth, project_id):
        return {"id": pid, "name": "Villa Kakkanad", "client": "Thomas"}

    async def sites(conn, auth, project_id):
        return {"s1": "Main"}

    async def waiting(conn, auth, enabled, project_id, site_id):
        return []

    monkeypatch.setattr("mesiri.domains.schedule.router._project", project)
    monkeypatch.setattr(engine, "_site_names", sites)
    monkeypatch.setattr(engine, "_waiting", waiting)
    base = _sections()

    def make(key):
        async def run(ctx):
            read.append(key)
            if key == "photos":
                return {"key": "photos", "title": "Photos", "status": "none", "available": 0, "rows": []}
            return base[key]

        return run

    monkeypatch.setattr(engine, "SECTIONS", {k: make(k) for k in engine.ORDER})
    return pid, read


async def _build(pid, role="ADMIN", enabled=lambda m: True):
    return await engine.build(_Conn(), _Auth(role), project_id=pid, site_id=None,
                              period=periods.week_of(D(2026, 11, 4)), enabled=enabled, today=D(2026, 11, 9))


async def test_engine_names_a_failing_section_and_hides_nothing_else(stubbed, monkeypatch):
    pid, read = stubbed

    async def boom(ctx):
        raise RuntimeError("db fell over")

    async def forbidden(ctx):
        raise HTTPException(status_code=403)

    monkeypatch.setitem(engine.SECTIONS, "materials", boom)
    monkeypatch.setitem(engine.SECTIONS, "issues", forbidden)
    r = await _build(pid)
    assert r["unavailable"] == ["materials"]
    assert "issues" not in r["sections"] and "materials" not in r["sections"]
    assert r["order"] == ["work", "schedule", "labour", "stock_value", "money", "photos", "completeness"]
    assert r["headline"]["lead"] and r["kpis"] and r["areas"]


async def test_money_is_never_read_for_a_role_that_does_not_see_spending(stubbed):
    pid, read = stubbed
    r = await _build(pid, role="SITE_ENGINEER")
    assert "money" not in read and "money" not in r["sections"] and r["sees_money"] is False
    assert "stock_value" not in read and "stock_value" not in r["sections"]  # PRC-49: money roles only
    assert all(k["key"] not in ("spent", "billed") for k in r["kpis"])


async def test_a_switched_off_module_is_not_read(stubbed):
    pid, read = stubbed
    await _build(pid, enabled=lambda m: m != "labour")
    assert "labour" not in read


async def test_photo_keys_never_reach_the_page():
    report = {"sections": {"photos": {"rows": [{"url": "u", "_key": "org/x.jpg"}]}}}
    assert engine.public(report)["sections"]["photos"]["rows"] == [{"url": "u"}]


# -- outputs ----------------------------------------------------------------------------------------------------------

async def test_pdf_and_excel_render_the_same_report(stubbed):
    pytest.importorskip("fpdf")
    pytest.importorskip("openpyxl")
    from openpyxl import load_workbook

    from mesiri.domains.reports.period import pdf, xlsx

    pid, _ = stubbed
    r = await _build(pid)
    data = pdf.render(r, {"company_name": "Periyar Builders", "gstin": "32ABCDE1234F1Z5", "phone": "0484 2400000"})
    assert data.startswith(b"%PDF")
    book = load_workbook(io.BytesIO(xlsx.workbook(r)))
    assert book.sheetnames[0] == "Summary"
    assert {"Work", "Schedule", "Labour", "Materials", "Money", "Issues", "Data check", "Needs you"} <= set(
        book.sheetnames)
    assert book["Summary"]["A1"].value.startswith("Villa Kakkanad: Week 45")


def test_pdf_text_uses_rs_for_rupees():
    from mesiri.domains.reports.period.pdf import t

    assert t("₹4.0 L · ▲ 6%") == "Rs 4.0 L - up 6%"


async def test_pdf_prints_photos_and_skips_one_it_cannot_read(stubbed):
    pytest.importorskip("fpdf")
    PIL = pytest.importorskip("PIL.Image")
    from mesiri.domains.reports.period import pdf

    pid, _ = stubbed
    r = await _build(pid)
    buf = io.BytesIO()
    PIL.new("RGB", (400, 300), (180, 170, 150)).save(buf, format="JPEG")
    images = [({"caption": "Slab 2 pour", "date": "2026-11-04"}, buf.getvalue()),
              ({"caption": "broken", "date": "2026-11-05"}, b"not an image")]
    with_photos = pdf.render(r, {"company_name": "Periyar Builders"}, images)
    without = pdf.render(r, {"company_name": "Periyar Builders"}, [])
    assert with_photos.startswith(b"%PDF") and len(with_photos) > len(without)
