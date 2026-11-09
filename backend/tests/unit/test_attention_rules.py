"""GM-04: the attention rules -- what crosses a line, the words, the severity, and what must not alert."""

from __future__ import annotations

import datetime

from mesiri.domains.attention import rules

P = {"id": "p1", "name": "Marina Heights"}
TODAY = datetime.date(2026, 11, 9)


def _line(**over):
    base = {"line_id": "l1", "work": "Plastering", "unit": "sqm", "colour": "red", "reason": "over_budget",
            "done_quantity": "120", "labour_man_days": "14", "difference": "-74000.00", "labour_cost": "484000.00",
            "earned_labour": "410000.00"}
    return {**base, **over}


def test_red_line_says_by_how_much_in_rupees_for_money_roles():
    a = rules.cost_alerts(P, {"lines": [_line(), _line(line_id="l2", colour="green")]})
    assert len(a) == 1 and a[0]["key"] == "cost:l1" and a[0]["severity"] == "bad"
    assert a[0]["title"] == "Plastering is ₹74,000 over its labour budget"
    assert a[0]["detail"] == "₹4,84,000 of labour for 120 sqm in the last 7 days; the work earned ₹4,10,000"
    assert a[0]["action"]["link"] == "/cost/green-red?project=p1"


def test_engineer_cost_alert_never_shows_a_rupee():
    a = rules.cost_alerts(P, {"money_hidden": True, "lines": [{k: v for k, v in _line().items()
                                                              if k not in ("difference", "labour_cost", "earned_labour")}]})
    assert a[0]["title"] == "Plastering is over its labour budget"
    assert "₹" not in a[0]["title"] + a[0]["detail"]


def test_labour_with_no_work_and_the_cap_per_project():
    a = rules.cost_alerts(P, {"lines": [_line(line_id=f"l{i}", reason="labour_no_work") for i in range(5)]})
    assert len(a) == rules.PER_PROJECT and a[0]["title"] == "Labour on Plastering, but no work recorded"
    assert a[-1]["detail"].endswith("(and 2 more like this)")


def test_schedule_handover_and_late_critical_first():
    sched = {"summary": {"slip_days": 9, "forecast_finish": "2027-06-23", "contract_finish": "2027-06-14"},
             "activities": [
                 {"id": "a1", "name": "Painting", "state": "late", "days_late": 6, "critical": False, "progress": 40,
                  "end": "2026-11-03", "forecast_end": None, "pushed_days": 0},
                 {"id": "a2", "name": "Slab 6F", "state": "late", "days_late": 2, "critical": True, "progress": None,
                  "end": "2026-11-07", "forecast_end": "2026-11-12", "pushed_days": 4},
                 {"id": "a3", "name": "Footings", "state": "on_track", "days_late": 0, "critical": True}]}
    a = rules.schedule_alerts(P, sched)
    assert [x["key"] for x in a] == ["handover:p1", "late:a2", "late:a1"]
    assert a[0]["title"] == "Handover forecast 9 days late" and "the contract date is Mon 14 Jun" in a[0]["detail"]
    assert a[1]["severity"] == "bad" and a[1]["title"] == "Slab 6F is 2 days late"
    assert a[1]["detail"] == ("Not started, planned to finish Sat 7 Nov; forecast Thu 12 Nov; it pushes the work after it "
                              "by 4 days. On the critical path: each day late moves the handover")
    assert a[2]["severity"] == "warn"


def test_schedule_on_time_says_nothing():
    assert rules.schedule_alerts(P, {"summary": {"slip_days": 0}, "activities": [{"id": "a", "state": "on_track"}]}) == []


def test_order_today_tomorrow_and_later():
    plan = {"materials": [
        {"material_id": "m1", "material": "Steel 12 mm", "unit": "kg", "short_by": "3200.4", "short_day": TODAY + datetime.timedelta(days=3),
         "order_by": TODAY, "supplier": "Kerala Steels", "lead_days": 2},
        {"material_id": "m2", "material": "Cement", "unit": "bags", "short_by": "600", "short_day": "2026-11-13",
         "order_by": "2026-11-10", "supplier": None, "lead_days": None},
        {"material_id": "m3", "material": "Sand", "unit": "cft", "short_by": "10", "short_day": "2026-11-30", "order_by": "2026-11-20"},
        {"material_id": "m4", "material": "Tiles", "unit": "nos", "short_by": None, "short_day": None, "order_by": None}]}
    a = rules.order_alerts(P, plan, TODAY)
    assert [(x["key"], x["severity"], x["title"]) for x in a] == [
        ("order:p1:m1", "bad", "Order Steel 12 mm today"), ("order:p1:m2", "warn", "Order Cement by tomorrow")]
    assert a[0]["detail"] == "3200 kg short from Thu 12 Nov; Kerala Steels takes 2 days"


def _site(**over):
    base = {"site_id": "s1", "site_name": "Podium", "project_id": "p1", "project_name": "Marina", "work_items": 0,
            "workers": 0, "materials": 0, "issues_today": 0, "progress_updates": 0, "drafts": 0, "site_working": None,
            "last_update_at": None}
    return {**base, **over}


def test_unreported_only_after_the_cutoff_and_never_for_a_site_that_sent_anything():
    days = {"date": "2026-11-09", "projects": [{"project_id": "p1", "reporting_cutoff_time": "17:00:00"}],
            "items": [_site(), _site(site_id="s2", site_name="Tower A", workers=12),
                      _site(site_id="s3", site_name="Yard", site_working="none")]}
    before = rules.report_alerts(days, datetime.datetime(2026, 11, 9, 16, 59))
    after = rules.report_alerts(days, datetime.datetime(2026, 11, 9, 17, 0))
    assert before == [] and [x["key"] for x in after] == ["unreported:s1:2026-11-09"]
    assert after[0]["detail"] == "Nothing from the site by 17:00"
    # No cut-off of its own: 6 pm.
    days["projects"][0]["reporting_cutoff_time"] = None
    assert rules.report_alerts(days, datetime.datetime(2026, 11, 9, 17, 30)) == []


def test_issue_open_two_days_high_is_bad_and_says_no_owner():
    now = datetime.datetime(2026, 11, 9, 9, tzinfo=datetime.UTC)
    issues = [{"id": "i1", "project_id": "p1", "site_id": "s1", "severity": "HIGH", "issue_type": "OTHER",
               "narrative": "No water at Podium since morning", "occurred_at": "2026-11-05T08:00:00+00:00",
               "assigned_user_id": None},
              {"id": "i2", "project_id": "p1", "site_id": "s1", "severity": "LOW", "issue_type": "MATERIAL_SHORTAGE",
               "narrative": None, "occurred_at": "2026-11-06T08:00:00+00:00", "assigned_user_id": "u1"},
              {"id": "i3", "project_id": "p1", "site_id": "s1", "severity": "CRITICAL", "issue_type": "SAFETY",
               "narrative": "Fresh", "occurred_at": "2026-11-08T12:00:00+00:00", "assigned_user_id": None}]
    a = rules.issue_alerts(issues, now, {"p1": "Marina", "s1": "Podium"})
    assert [(x["key"], x["severity"]) for x in a] == [("issue:i1", "bad"), ("issue:i2", "warn")]
    assert a[0]["title"] == "Open 4 days: No water at Podium since morning" and a[0]["detail"] == "High · no one is on it"
    assert a[1]["title"] == "Open 3 days: Material shortage" and a[1]["site_name"] == "Podium"


def test_hire_bill_over_its_log_only():
    hire = {"items": [{"name": "JCB 3DX", "project_name": "Al Noor", "site_name": "Block 2", "bills": [
        {"id": "b1", "check": {"status": "over", "flags": ["Bill says 208 hours; 176 recorded on site."]}},
        {"id": "b2", "check": {"status": "check", "flags": ["2 days in the period with no log."]}}]}]}
    a = rules.hire_alerts(hire)
    assert [x["key"] for x in a] == ["hire:b1"] and a[0]["detail"] == "Bill says 208 hours; 176 recorded on site"


def test_arrange_bad_first_and_snoozed_counted_apart():
    a = [rules._alert("x", "issue", "warn", "t", "d", project_name="B", action="a", link="/"),
         rules._alert("y", "late", "bad", "t", "d", project_name="A", action="a", link="/"),
         rules._alert("z", "handover", "bad", "t", "d", project_name="A", action="a", link="/")]
    out = rules.arrange(a, {"x"})
    assert [x["key"] for x in out["items"]] == ["z", "y"]
    assert out["counts"] == {"total": 2, "bad": 2, "warn": 0, "snoozed": 1}
    assert [x["key"] for x in out["snoozed"]] == ["x"]


def test_project_forecast_over_budget_only_when_red_and_over():
    book = {"projects": [
        {"project_id": "p1", "name": "Marina", "colour": "red", "forecast_difference": "-1240000.00", "forecast": "33240000.00",
         "forecast_budget": "32000000.00", "forecast_kinds": ["labour", "material"], "percent_done": "41.0", "percent_spent": "52.3"},
        {"project_id": "p2", "name": "Green Villa", "colour": "green", "forecast_difference": "50000.00"},
        {"project_id": "p3", "name": "New", "colour": "grey", "forecast_difference": None}]}
    a = rules.budget_alerts(book)
    assert [x["key"] for x in a] == ["budget:p1"] and a[0]["title"] == "Forecast ₹12,40,000 over budget"
    assert a[0]["detail"] == ("At this rate labour, material will cost ₹3,32,40,000 against a budget of ₹3,20,00,000; "
                              "41.0% done, 52.3% spent")
