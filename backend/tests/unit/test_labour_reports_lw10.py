"""LW-10: labour by project / site / trade / payee, earned by the wage sheet's rule, paid from the wage sheets."""

import datetime
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mesiri.domains.workforce.pay import build_rows, report_rows  # noqa: E402

D1, D2 = datetime.date(2026, 11, 16), datetime.date(2026, 11, 17)
TEAMS = {"by_id": {"v1": "Rahim"}, "by_name": {"rahim": "v1"}}


def _ln(day, trade, heads=1, wage=1000, worker=None, contractor=None, site="s1", status="present", ot=0):
    return {"date": day, "project_id": "p1", "project_name": "Green Villa", "site_id": site,
            "site_name": {"s1": "Main block", "s2": "Annex"}[site], "worker_id": None, "worker_name": worker,
            "trade": trade, "headcount": heads, "daily_wage": wage, "contractor": contractor, "vendor_id": None,
            "attendance_status": status, "overtime_hours": ot}


LINES = [
    _ln(D1, "mason", worker="Suresh", wage=1100), _ln(D2, "mason", worker="Suresh", wage=1100, status="half_day"),
    _ln(D1, "helper", heads=3, wage=700, contractor="Rahim", site="s2"),
    _ln(D2, "helper", heads=3, wage=700, contractor="Rahim", site="s2", ot=2),
    _ln(D2, "plumber", wage=None, worker="Vinod", site="s2"),
]


def test_by_payee_matches_the_wage_sheet_rows_exactly():
    rows = {r["key"]: r for r in report_rows(LINES, [], "payee", {}, TEAMS)}
    sheet = build_rows(LINES, {}, TEAMS)
    for key, s in sheet.items():
        assert rows[key]["earned"] == s["gross"] + s["overtime_amount"]
        assert rows[key]["man_days"] == s["man_days"]
    assert rows["vendor:v1"]["label"] == "Rahim" and rows["vendor:v1"]["man_days"] == 6
    assert rows["name:suresh"]["days"] == 2 and rows["name:suresh"]["man_days"] == Decimal("1.5")


def test_by_site_and_trade_add_up_to_the_same_total_and_trade_has_no_pay():
    total = sum(r["earned"] for r in report_rows(LINES, [], "payee", {}, TEAMS))
    for by in ("project", "site", "trade"):
        assert sum(r["earned"] for r in report_rows(LINES, [], by, {}, TEAMS)) == total
    trade = {r["label"]: r for r in report_rows(LINES, [], "trade", {}, TEAMS)}
    assert trade["Plumber"]["unpriced_man_days"] == 1 and trade["Plumber"]["earned"] == 0  # no wage: no rupees
    assert trade["Helper"]["paid"] is None  # a sheet pays people, not trades: never guessed


def test_paid_owed_and_waiting_come_from_the_sheets():
    sheets = [
        {"project_id": "p1", "site_id": "s2", "payee_key": "vendor:v1", "status": "approved", "net": "4375", "paid": "3000"},
        {"project_id": "p1", "site_id": "s1", "payee_key": "name:suresh", "status": "draft", "net": "1650", "paid": "0"},
        {"project_id": "p1", "site_id": "s1", "payee_key": "name:joseph", "payee_name": "Joseph", "status": "approved",
         "net": "500", "paid": "500"},  # a carry-forward with no attendance this period: still shown
    ]
    by = {r["key"]: r for r in report_rows(LINES, sheets, "payee", {}, TEAMS)}
    assert (by["vendor:v1"]["to_pay"], by["vendor:v1"]["paid"], by["vendor:v1"]["owed"]) == (4375, 3000, 1375)
    assert by["name:suresh"]["waiting"] == 1650 and by["name:suresh"]["owed"] == 0
    assert by["name:joseph"]["label"] == "Joseph" and by["name:joseph"]["paid"] == 500
    site = {r["key"]: r for r in report_rows(LINES, sheets, "site", {}, TEAMS)}
    assert site["s2"]["owed"] == 1375 and site["s1"]["to_pay"] == 500


def test_a_whole_project_sheet_is_its_own_row_by_site_and_trades_read_as_words():
    sheets = [{"project_id": "p1", "site_id": None, "payee_key": "vendor:v1", "status": "approved", "net": "100",
               "paid": "0", "label": "Green Villa · whole-project sheet"}]
    site = {r["key"]: r for r in report_rows(LINES, sheets, "site", {}, TEAMS)}
    assert site["project:p1"]["label"] == "Green Villa · whole-project sheet" and site["project:p1"]["owed"] == 100
    bender = [_ln(D1, "bar_bender")]
    assert report_rows(bender, [], "trade", {}, TEAMS)[0]["label"] == "Bar bender"
