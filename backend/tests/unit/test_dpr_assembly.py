"""build_site_report_payload -- #16 Daily Report Generation's pure shaping.

Protects the payload shape the assistant-side PDF renderer and the future
manager-review UI both depend on: activities carry their quantities and
evidence counts, issues carry severity/status, and the summary counts
(activity_count/open_issue_count/evidence_count) are derived correctly
rather than trusted from the caller.
"""

from __future__ import annotations

import datetime
import uuid

from mesiri.application.dpr.assembly import build_project_report_payload, build_site_report_payload

ACTIVITY_1 = uuid.uuid4()
ACTIVITY_2 = uuid.uuid4()


def test_empty_day_produces_a_zeroed_payload():
    payload = build_site_report_payload(
        project_name="Skyline Towers",
        site_name="Block A",
        report_date=datetime.date(2026, 7, 27),
        activity_rows=[],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[],
    )
    assert payload["activity_count"] == 0
    assert payload["open_issue_count"] == 0
    assert payload["evidence_count"] == 0
    assert payload["activities"] == []
    assert payload["issues"] == []


def test_activity_carries_its_own_quantities_and_evidence_count():
    payload = build_site_report_payload(
        project_name="Skyline Towers",
        site_name="Block A",
        report_date=datetime.date(2026, 7, 27),
        activity_rows=[
            {
                "id": ACTIVITY_1,
                "work_type": "plastering",
                "narrative": "180 sqm done",
                "status": "IN_PROGRESS",
                "contractor": "ABC Contractors",
            }
        ],
        quantities_by_activity={
            ACTIVITY_1: [{"work_type": "plastering", "quantity": "180", "unit": "sqm"}]
        },
        evidence_count_by_activity={ACTIVITY_1: 3},
        issue_rows=[],
    )
    assert payload["activity_count"] == 1
    activity = payload["activities"][0]
    assert activity["quantities"] == [{"work_type": "plastering", "quantity": "180", "unit": "sqm"}]
    assert activity["evidence_count"] == 3
    assert payload["evidence_count"] == 3


def test_activity_with_no_quantities_or_evidence_defaults_to_empty_not_missing():
    payload = build_site_report_payload(
        project_name="Skyline Towers",
        site_name="Block A",
        report_date=datetime.date(2026, 7, 27),
        activity_rows=[{"id": ACTIVITY_2, "work_type": "excavation", "narrative": None,
                         "status": "PLANNED", "contractor": None}],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[],
    )
    activity = payload["activities"][0]
    assert activity["quantities"] == []
    assert activity["evidence_count"] == 0


def test_open_issue_count_only_counts_open_not_resolved():
    payload = build_site_report_payload(
        project_name="Skyline Towers",
        site_name="Block A",
        report_date=datetime.date(2026, 7, 27),
        activity_rows=[],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[
            {"issue_type": "MATERIAL_SHORTAGE", "severity": "HIGH", "narrative": "cement short",
             "status": "OPEN", "delay_duration_minutes": 60},
            {"issue_type": "WEATHER", "severity": "LOW", "narrative": "rain earlier",
             "status": "RESOLVED", "delay_duration_minutes": 30},
        ],
    )
    assert len(payload["issues"]) == 2
    assert payload["open_issue_count"] == 1


def test_evidence_count_sums_across_all_activities():
    payload = build_site_report_payload(
        project_name="Skyline Towers",
        site_name="Block A",
        report_date=datetime.date(2026, 7, 27),
        activity_rows=[
            {"id": ACTIVITY_1, "work_type": "plastering", "narrative": None,
             "status": "COMPLETED", "contractor": None},
            {"id": ACTIVITY_2, "work_type": "excavation", "narrative": None,
             "status": "COMPLETED", "contractor": None},
        ],
        quantities_by_activity={},
        evidence_count_by_activity={ACTIVITY_1: 2, ACTIVITY_2: 5},
        issue_rows=[],
    )
    assert payload["evidence_count"] == 7


def test_report_date_is_serialized_as_iso_string():
    payload = build_site_report_payload(
        project_name="X", site_name="Y", report_date=datetime.date(2026, 7, 27),
        activity_rows=[], quantities_by_activity={}, evidence_count_by_activity={}, issue_rows=[],
    )
    assert payload["report_date"] == "2026-07-27"


def _base_payload(**overrides):
    base = dict(
        project_name="Skyline Towers",
        site_name="Block A",
        report_date=datetime.date(2026, 7, 27),
        activity_rows=[],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[],
    )
    base.update(overrides)
    return build_site_report_payload(**base)


def test_missing_labour_and_material_args_default_to_zeroed_sections():
    """Every existing caller (this test file's own calls above) never passed
    labour_lines/material_movement_rows -- must still shape a valid,
    honestly-empty section rather than raising or omitting the key."""
    payload = _base_payload()
    assert payload["labour"] == {"headcount": 0, "named_count": 0, "trades": [], "total_cost": "0"}
    assert payload["materials"] == []


def test_labour_headcount_sums_named_and_group_lines():
    payload = _base_payload(
        labour_lines=[
            {"worker_name": "Ravi", "trade": "mason", "headcount": 1, "daily_wage": "800"},
            {"worker_name": None, "trade": "helper", "headcount": 12, "daily_wage": "600"},
        ]
    )
    labour = payload["labour"]
    assert labour["headcount"] == 13
    assert labour["named_count"] == 1
    assert {"trade": "mason", "headcount": 1} in labour["trades"]
    assert {"trade": "helper", "headcount": 12} in labour["trades"]


def test_labour_cost_multiplies_daily_wage_by_headcount():
    payload = _base_payload(
        labour_lines=[
            {"worker_name": "Ravi", "trade": "mason", "headcount": 1, "daily_wage": "800"},
            {"worker_name": None, "trade": "helper", "headcount": 12, "daily_wage": "600"},
        ]
    )
    assert payload["labour"]["total_cost"] == "8000"


def test_labour_line_with_no_wage_contributes_zero_cost_not_an_error():
    payload = _base_payload(
        labour_lines=[{"worker_name": "Ravi", "trade": "mason", "headcount": 1, "daily_wage": None}]
    )
    assert payload["labour"]["total_cost"] == "0"


def test_labour_line_with_no_trade_is_excluded_from_trades_breakdown_but_still_counted():
    payload = _base_payload(
        labour_lines=[{"worker_name": "Ravi", "trade": None, "headcount": 1, "daily_wage": "800"}]
    )
    labour = payload["labour"]
    assert labour["headcount"] == 1
    assert labour["trades"] == []


def test_material_received_and_used_are_summed_separately_per_material():
    payload = _base_payload(
        material_movement_rows=[
            {"material_id": "m1", "material_name": "Cement", "unit": "bags",
             "movement_type": "RECEIPT", "quantity": "50"},
            {"material_id": "m1", "material_name": "Cement", "unit": "bags",
             "movement_type": "ISSUE", "quantity": "20"},
        ]
    )
    materials = payload["materials"]
    assert len(materials) == 1
    assert materials[0]["material_name"] == "Cement"
    assert materials[0]["received"] == "50"
    assert materials[0]["used"] == "20"


def test_material_movements_for_different_materials_stay_separate():
    payload = _base_payload(
        material_movement_rows=[
            {"material_id": "m1", "material_name": "Cement", "unit": "bags",
             "movement_type": "RECEIPT", "quantity": "50"},
            {"material_id": "m2", "material_name": "Steel", "unit": "kg",
             "movement_type": "ISSUE", "quantity": "120"},
        ]
    )
    materials = {m["material_name"]: m for m in payload["materials"]}
    assert materials["Cement"]["received"] == "50"
    assert materials["Cement"]["used"] == "0"
    assert materials["Steel"]["used"] == "120"
    assert materials["Steel"]["received"] == "0"


# --- build_project_report_payload (ADR-D9/P8) ------------------------------


def _site_payload(**overrides) -> dict:
    base = build_site_report_payload(
        project_name="Skyline Towers",
        site_name="Block A",
        report_date=datetime.date(2026, 7, 27),
        activity_rows=[],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[],
    )
    base.update(overrides)
    return base


def test_project_payload_level_and_report_date():
    payload = build_project_report_payload(
        project_name="Skyline Towers", report_date=datetime.date(2026, 7, 27), site_payloads=[]
    )
    assert payload["level"] == "PROJECT"
    assert payload["report_date"] == "2026-07-27"
    assert payload["sites"] == []
    assert payload["reported_site_count"] == 0
    assert payload["total_site_count"] == 0


def test_project_payload_marks_a_site_with_no_version_as_not_reported():
    payload = build_project_report_payload(
        project_name="Skyline Towers",
        report_date=datetime.date(2026, 7, 27),
        site_payloads=[("Block A", None)],
    )
    site = payload["sites"][0]
    assert site["site_name"] == "Block A"
    assert site["reported"] is False
    assert payload["reported_site_count"] == 0
    assert payload["total_site_count"] == 1


def test_project_payload_aggregates_activity_and_issue_counts_across_sites():
    payload = build_project_report_payload(
        project_name="Skyline Towers",
        report_date=datetime.date(2026, 7, 27),
        site_payloads=[
            ("Block A", _site_payload(activity_count=3, open_issue_count=1, evidence_count=2)),
            ("Block B", _site_payload(activity_count=5, open_issue_count=0, evidence_count=1)),
            ("Block C", None),
        ],
    )
    assert payload["activity_count"] == 8
    assert payload["open_issue_count"] == 1
    assert payload["evidence_count"] == 3
    assert payload["reported_site_count"] == 2
    assert payload["total_site_count"] == 3


def test_project_payload_aggregates_labour_headcount_and_cost_across_sites():
    site_a = _site_payload(labour={"headcount": 10, "total_cost": "5000", "trades": []})
    site_b = _site_payload(labour={"headcount": 4, "total_cost": "2000", "trades": []})
    payload = build_project_report_payload(
        project_name="X",
        report_date=datetime.date(2026, 7, 27),
        site_payloads=[("Block A", site_a), ("Block B", site_b)],
    )
    assert payload["labour"]["headcount"] == 14
    assert payload["labour"]["total_cost"] == "7000"


def test_project_payload_sums_material_movements_across_sites_by_name_and_unit():
    site_a = _site_payload(
        materials=[{"material_name": "Cement", "unit": "bags", "received": "50", "used": "20"}]
    )
    site_b = _site_payload(
        materials=[{"material_name": "Cement", "unit": "bags", "received": "30", "used": "10"}]
    )
    payload = build_project_report_payload(
        project_name="X",
        report_date=datetime.date(2026, 7, 27),
        site_payloads=[("Block A", site_a), ("Block B", site_b)],
    )
    assert len(payload["materials"]) == 1
    assert payload["materials"][0]["received"] == "80"
    assert payload["materials"][0]["used"] == "30"


def test_project_payload_tags_each_issue_with_its_source_site():
    site_a = _site_payload(
        issues=[{"issue_type": "MATERIAL_SHORTAGE", "severity": "HIGH", "narrative": "x", "status": "OPEN"}]
    )
    payload = build_project_report_payload(
        project_name="X",
        report_date=datetime.date(2026, 7, 27),
        site_payloads=[("Block A", site_a)],
    )
    assert payload["issues"][0]["site_name"] == "Block A"
    assert payload["issues"][0]["issue_type"] == "MATERIAL_SHORTAGE"


def test_project_payload_site_breakdown_reflects_each_sites_own_figures():
    site_a = _site_payload(
        activity_count=3, open_issue_count=1, labour={"headcount": 10, "total_cost": "5000", "trades": []}
    )
    payload = build_project_report_payload(
        project_name="X",
        report_date=datetime.date(2026, 7, 27),
        site_payloads=[("Block A", site_a)],
    )
    site = payload["sites"][0]
    assert site["reported"] is True
    assert site["activity_count"] == 3
    assert site["open_issue_count"] == 1
    assert site["headcount"] == 10
    assert site["labour_cost"] == "5000"


# ---------------------------------------------------------------------------
# BE-12: stock corrections are not deliveries; usage beyond stock is flagged
# ---------------------------------------------------------------------------

CEMENT = uuid.uuid4()


def _be12_payload(movement_rows, stock_rows=None):
    return build_site_report_payload(
        project_name="Skyline Towers",
        site_name="Block A",
        report_date=datetime.date(2026, 10, 15),
        activity_rows=[],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[],
        material_movement_rows=movement_rows,
        material_stock_rows=stock_rows,
    )


def _move(movement_type, quantity, reason):
    return {"material_id": CEMENT, "material_name": "Cement", "unit": "bags",
            "movement_type": movement_type, "quantity": quantity, "movement_reason": reason}


def test_opening_stock_and_adjustments_are_not_received_or_used():
    payload = _be12_payload([
        _move("RECEIPT", "50", "RECEIVED"),
        _move("RECEIPT", "30", "OPENING_STOCK"),
        _move("ISSUE", "20", "CONSUMED"),
        _move("ISSUE", "4", "ADJUSTMENT_OUT"),
    ])
    [cement] = payload["materials"]
    assert cement["received"] == "50"
    assert cement["used"] == "20"
    assert cement["adjusted"] == "26"
    assert cement["closing"] is None  # no stock rows: no flag either way
    assert cement["beyond_stock"] is False
    assert payload["stock_flags"] == 0


def test_rows_without_a_reason_count_by_direction_as_before():
    [cement] = _be12_payload([_move("RECEIPT", "50", None), _move("ISSUE", "20", None)])["materials"]
    assert (cement["received"], cement["used"], cement["adjusted"]) == ("50", "20", "0")


def test_stock_rows_balance_the_day_and_flag_negative_closing():
    payload = _be12_payload(
        [_move("RECEIPT", "10", "RECEIVED"), _move("ISSUE", "50", "CONSUMED")],
        [{"material_id": CEMENT, "material_name": "Cement", "unit": "bags",
          "opening": "20", "closing": "-15"}],
    )
    [cement] = payload["materials"]
    assert cement["opening"] == "20"
    assert cement["closing"] == "-15"
    # 20 + 10 + adjusted - 50 = -15 -> adjusted = 5 (e.g. opening stock entered today)
    assert cement["adjusted"] == "5"
    assert cement["beyond_stock"] is True
    assert payload["stock_flags"] == 1


def test_correction_of_an_earlier_day_shows_as_adjusted():
    # Today's only movements were a correction pair excluded from the day rows,
    # but stock moved: yesterday's 10-bag receipt was reversed today.
    [cement] = _be12_payload(
        [], [{"material_id": CEMENT, "material_name": "Cement", "unit": "bags",
              "opening": "30", "closing": "20"}],
    )["materials"]
    assert cement["adjusted"] == "-10"
    assert cement["beyond_stock"] is False


def test_same_day_move_and_correction_is_not_listed():
    payload = _be12_payload(
        [], [{"material_id": CEMENT, "material_name": "Cement", "unit": "bags",
              "opening": "30", "closing": "30"}],
    )
    assert payload["materials"] == []


def test_project_rollup_counts_stock_flags_per_site():
    flagged = _be12_payload(
        [_move("ISSUE", "50", "CONSUMED")],
        [{"material_id": CEMENT, "material_name": "Cement", "unit": "bags",
          "opening": "0", "closing": "-50"}],
    )
    project = build_project_report_payload(
        project_name="Skyline Towers",
        report_date=datetime.date(2026, 10, 15),
        site_payloads=[("Block A", flagged), ("Block B", None)],
    )
    assert project["stock_flags"] == 1
    assert [s["stock_flags"] for s in project["sites"]] == [1, 0]


# ---------------------------------------------------------------------------
# BE-11: a work item reported twice is flagged as a possible duplicate
# ---------------------------------------------------------------------------


def _be11_payload(activities, quantities=None, project=False):
    rows = [
        {"id": uuid.uuid4(), "work_type": a[0], "narrative": a[1], "status": "COMPLETED",
         "contractor": None, "location_id": a[2] if len(a) > 2 else None}
        for a in activities
    ]
    return build_site_report_payload(
        project_name="Skyline Towers",
        site_name="Block A",
        report_date=datetime.date(2026, 10, 15),
        activity_rows=rows,
        quantities_by_activity={
            row["id"]: q for row, q in zip(rows, quantities or [[]] * len(rows), strict=True)
        },
        evidence_count_by_activity={},
        issue_rows=[],
    )


def _flags(payload):
    return [a["possible_duplicate"] for a in payload["activities"]]


def test_same_work_and_same_quantities_is_a_possible_duplicate():
    sqm = [{"quantity": "120", "unit": "sqm"}]
    payload = _be11_payload(
        [("Plastering", "2nd floor east"), ("plastering", "east side 2nd floor")],
        [sqm, [{"quantity": "120.00", "unit": "sqm"}]],
    )
    assert _flags(payload) == [False, True]  # the first stays, the repeat is flagged
    assert payload["possible_duplicates"] == 1


def test_same_work_with_different_quantities_is_two_pieces_of_work():
    payload = _be11_payload(
        [("Plastering", "east wing"), ("Plastering", "west wing")],
        [[{"quantity": "120", "unit": "sqm"}], [{"quantity": "80", "unit": "sqm"}]],
    )
    assert _flags(payload) == [False, False]


def test_without_quantities_the_same_description_is_a_possible_duplicate():
    payload = _be11_payload(
        [("Shuttering", "Columns C1-C4, ground floor."), ("Shuttering", "columns c1 c4 ground floor"),
         ("Shuttering", "Beams, first floor")]
    )
    assert _flags(payload) == [False, True, False]


def test_different_locations_are_not_duplicates():
    loc_a, loc_b = uuid.uuid4(), uuid.uuid4()
    payload = _be11_payload([("Brickwork", "wall", loc_a), ("Brickwork", "wall", loc_b)])
    assert _flags(payload) == [False, False]


def test_activities_with_nothing_to_compare_are_not_flagged():
    payload = _be11_payload([("Plastering", None), ("Plastering", "")])
    assert _flags(payload) == [False, False]


def test_project_rollup_counts_possible_duplicates():
    site = _be11_payload([("Shuttering", "beams"), ("Shuttering", "beams")])
    project = build_project_report_payload(
        project_name="Skyline Towers",
        report_date=datetime.date(2026, 10, 15),
        site_payloads=[("Block A", site), ("Block B", None)],
    )
    assert project["possible_duplicates"] == 1
    assert [s["possible_duplicates"] for s in project["sites"]] == [1, 0]


def _update(activity_id, kind, words, quantity=None, unit=None, started=datetime.date(2026, 10, 22)):
    return {
        "id": activity_id,
        "work_type": "brickwork",
        "narrative": "started brickwork ground floor",
        "status": "COMPLETED",
        "contractor": None,
        "location_id": None,
        "activity_date": started,
        "update_kind": kind,
        "update_narrative": words,
        "quantity": quantity,
        "unit_code": unit,
    }


def test_work_updated_on_a_later_day_shows_that_days_update():
    """V1 audit WRK-01: day 2's DPR had no brickwork at all."""
    from mesiri.application.dpr.assembly import build_review_items, carried_activity_rows

    carried = carried_activity_rows(
        [
            _update(ACTIVITY_1, "PROGRESS", "brickwork 60% done", "12", "cum"),
            _update(ACTIVITY_1, "COMPLETED", "brickwork finished"),
        ]
    )
    assert len(carried) == 1
    payload = build_site_report_payload(
        project_name="Skyline Towers",
        site_name="Block A",
        report_date=datetime.date(2026, 10, 23),
        activity_rows=carried,
        quantities_by_activity={ACTIVITY_1: [{"work_type": "x", "quantity": "999", "unit": "sqm"}]},
        evidence_count_by_activity={ACTIVITY_1: 4},
        issue_rows=[],
    )
    activity = payload["activities"][0]
    assert activity["work_type"] == "brickwork"
    assert activity["narrative"] == "brickwork 60% done; brickwork finished (started 22 Oct)"
    assert activity["status"] == "COMPLETED"
    assert activity["quantities"] == [{"work_type": "brickwork", "quantity": "12", "unit": "cum"}]
    assert activity["evidence_count"] == 0  # the photos belong to the day it started
    assert activity["carried_from"] == "2026-10-22"
    assert payload["activity_count"] == 1

    # Not offered for confirm/remove on day 2: removing it would remove day 1's work.
    items = build_review_items(
        payload=payload,
        activity_rows=carried,
        issue_rows=[],
        labour_lines=[],
        material_movement_rows=[],
        review_states={},
    )
    assert items == []


def test_a_progress_update_without_words_names_the_start_day():
    from mesiri.application.dpr.assembly import carried_activity_rows

    (row,) = carried_activity_rows([_update(ACTIVITY_2, "PAUSED", None)])
    assert row["status"] == "STOPPED"
    assert row["narrative"] == "started brickwork ground floor (started 22 Oct)"


def test_same_day_activities_have_no_carried_from():
    payload = build_site_report_payload(
        project_name="P",
        site_name="S",
        report_date=datetime.date(2026, 10, 23),
        activity_rows=[{"id": ACTIVITY_1, "work_type": "plastering", "narrative": "x", "status": "IN_PROGRESS"}],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[],
    )
    assert "carried_from" not in payload["activities"][0]
