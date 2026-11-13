"""WA-270 step 3: the state block, built by the code from the chat state and the day's records (plan section 11.3).

Unit tests of the one function. Step 4 puts the block in place of the replay; the conversation tests
(``test_conversation_state_270.py``) then hold what the model is given end to end.
"""

from __future__ import annotations

import datetime as dt

from agent_api import state_block as sb

NOW = 1_800_000_000.0
DAY = dt.date(2026, 11, 13)
MAIN, ANNEX, OTHER = "s-main", "s-annex", "s-other"
SITES = {MAIN: "Main Block", ANNEX: "Annex"}


def _entry(summary: str, tool: str = "record_material_receipt") -> dict:
    return {"tool": tool, "method": "POST", "path": "/x", "params": {}, "body": {}, "summary": summary,
            "idempotency_key": summary}


def _block(state: dict, message: str = "athu 25 aakku", **kw) -> str:
    return sb.state_block(state, message=message, now=NOW, today=kw.pop("today", []), **kw)


# --- the card -------------------------------------------------------------------------------------------------

def test_the_card_is_numbered_as_the_person_sees_it_without_ids() -> None:
    """WA-293: "athu 25 aakku" is read against numbered lines, not an old conversation."""
    block = _block({"pending": [_entry("50 bags cement, Green Villa (material_id 1a2b3c4d-0000-4000-8000-000000000000)"),
                                _entry("50 TMT bars, Green Villa")]})
    card = block.split(sb.CARD)[1]
    assert "1. 50 bags cement, Green Villa\n2. 50 TMT bars, Green Villa" in card
    assert "material_id" not in block and "1a2b3c4d" not in block


def test_no_card_is_said_so_the_model_never_takes_an_old_one_as_waiting() -> None:
    block = _block({})
    assert "On the card now: nothing is waiting for Save." in block
    assert sb.CARD not in block


# --- cancelled ------------------------------------------------------------------------------------------------

def test_every_cancel_of_the_day_is_kept_and_named() -> None:
    """WA-294: the lines of two cancelled messages came back on a third. Both cancels are named, not only the last."""
    state: dict = {}
    sb.remember_cancelled(state, ["10 bags cement, Main Block", "2 masons, Main Block"], now=NOW - 600)
    sb.remember_cancelled(state, ["25 bags cement, Main Block"], now=NOW - 60)
    cancelled = _block(state).split(sb.CANCELLED)[1]
    for line in ("10 bags cement", "2 masons", "25 bags cement"):
        assert line in cancelled


def test_a_cancel_from_a_working_day_ago_is_let_go_and_the_list_stays_small() -> None:
    state: dict = {}
    sb.remember_cancelled(state, ["old cement"], now=NOW - sb.CANCELLED_SECONDS - 1)
    sb.remember_cancelled(state, [f"line {i}" for i in range(sb.CANCELLED_KEPT + 5)], now=NOW)
    sb.remember_cancelled(state, ["", "  "], now=NOW)  # nothing said is nothing kept
    block = _block(state)
    assert "old cement" not in block
    assert len(state["cancel_log"]) == sb.CANCELLED_KEPT and "line 24" in block and "line 4\n" not in block


def test_guard_the_wa146_cancelled_key_is_not_read_as_the_days_cancels() -> None:
    """The reason tap takes ``cancelled`` (the last Cancel only); the block reads its own log."""
    assert sb.CANCELLED not in _block({"cancelled": [{"tool": "x", "summary": "50 bags cement"}]})


# --- held lines and the open question -------------------------------------------------------------------------

def test_held_lines_are_named_with_what_they_wait_for_until_they_age_out() -> None:
    hold = {"tool": "record_material_receipt", "arguments": {"summary": "60 bags cement"}, "gap": "site"}
    fresh = _block({"held": {"lines": [hold], "at": NOW - 60}})
    assert "- 60 bags cement (waiting for: site)" in fresh.split(sb.HELD)[1]
    assert sb.HELD not in _block({"held": {"lines": [hold], "at": NOW - sb.HELD_SECONDS - 1}})
    # WA-278's older key is read the same way while it lives
    assert "60 bags cement" in _block({"site_held": {"lines": [hold], "at": NOW - 60}})


def test_held_lines_have_one_owner_and_whatsapp_reads_them_from_it() -> None:
    from agent_api import whatsapp as wa

    assert wa._held is sb.held_lines and wa.HELD_SECONDS == sb.HELD_SECONDS


def test_the_open_question_is_said_once_with_its_options() -> None:
    block = _block({"asked": {"question": "Which site? (site_id 11116a12-47aa-436c-89ba-207cfcd1b926)",
                              "options": ["Main Block", "Annex"]}})
    assert f'{sb.ASKED}: "Which site?" (options: Main Block / Annex)' in block
    assert sb.ASKED not in _block({"asked": None}) and sb.ASKED not in _block({"asked": {"question": " "}})


# --- saved ----------------------------------------------------------------------------------------------------

def test_saved_records_carry_their_ids_and_age_out_with_the_repeat_window() -> None:
    from agent_api.agent import REPEAT_WINDOW_S

    state = {"recent_saves": [
        {"fp": "a", "summary": "Water tank leak, Main Block", "at": NOW - 300, "tool": "report_issue", "id": "i-1"},
        {"fp": "b", "summary": "12 bags cement", "at": NOW - 200},
        {"fp": "c", "summary": "yesterday's sand", "at": NOW - REPEAT_WINDOW_S - 1, "tool": "x", "id": "i-0"},
    ]}
    saved = _block(state).split(sb.SAVED)[1]
    assert "- Water tank leak, Main Block (report_issue, id i-1)" in saved
    assert "- 12 bags cement\n" in saved
    assert "yesterday's sand" not in saved


# --- the day per site -----------------------------------------------------------------------------------------

def _total(site: str, workers: int, trades: dict[str, int], day: dt.date = DAY) -> dict:
    return {"project_id": "p", "site_id": site, "occurred_date": day.isoformat(), "workers": workers,
            "trades": [{"trade": t, "workers": n} for t, n in trades.items()]}


def test_the_day_counts_workers_as_the_today_page_does_and_lists_the_rest() -> None:
    """WA-287: 16 in the morning, a correction to 10 masons, 2 carpenters still count: 12, never 26 or 10."""
    totals = [_total(MAIN, 12, {"mason": 10, "carpenter": 2, "helper": 0}),
              _total(OTHER, 40, {"mason": 40}),  # a site this person cannot see
              _total(ANNEX, 5, {"mason": 5}, DAY - dt.timedelta(days=1))]  # another day
    rows = [
        {"occurred_at": "2026-11-13T05:00:00Z", "site_id": MAIN, "event_type": "labour_attendance", "summary": "16 workers"},
        {"occurred_at": "2026-11-13T06:00:00Z", "site_id": MAIN, "event_type": "material_receipt",
         "summary": "95 bags cement (receipt_id 1a2b3c4d-0000-4000-8000-000000000000)"},
        {"occurred_at": "2026-11-13T04:00:00Z", "site_id": ANNEX, "event_type": "issue", "summary": "Water tank leak"},
        {"occurred_at": "2026-11-13T04:30:00Z", "site_id": OTHER, "event_type": "issue", "summary": "not theirs"},
    ]
    days = sb.today_by_site(totals, rows, SITES, DAY)
    assert days == [
        sb.SiteDay("Main Block", 12, (("mason", 10), ("carpenter", 2)), ("material_receipt: 95 bags cement",)),
        sb.SiteDay("Annex", None, (), ("issue: Water tank leak",)),
    ]
    today = _block({}, today=days).split(sb.CARD)[0]
    assert "- Main Block: 12 workers counted (10 mason, 2 carpenter)" in today
    assert "- Annex: no attendance yet\n  - issue: Water tank leak" in today
    assert "16 workers" not in today and "not theirs" not in today and "40" not in today


def test_a_long_day_shows_its_latest_records() -> None:
    day = sb.SiteDay("Main Block", recorded=tuple(f"delivery {i}" for i in range(sb.RECORDED_SHOWN + 3)))
    block = _block({}, today=[day])
    assert "(3 earlier records not shown)" in block and f"delivery {sb.RECORDED_SHOWN + 2}" in block
    assert "delivery 2\n" not in block


def test_a_day_not_read_is_never_said_as_nothing_recorded() -> None:
    assert "could not be read now" in sb.state_block({}, message="x", now=NOW, today=None)
    assert f"{sb.TODAY}: nothing recorded yet." in _block({}, today=[])


# --- the shape --------------------------------------------------------------------------------------------------

def test_the_message_to_act_on_is_last_and_marked_and_earlier_days_are_one_line_each() -> None:
    state = {"pending": [_entry("50 bags cement")], "recent_saves": [{"fp": "a", "summary": "3 masons", "at": NOW}]}
    sb.remember_cancelled(state, ["10 bags sand"], now=NOW)
    block = _block(state, message="  athu 25 aakku ",
                   earlier=[(DAY - dt.timedelta(days=2), "40 bags cement came"), (DAY - dt.timedelta(days=1), "12 workers")])
    order = [block.index(h) for h in (sb.TODAY, sb.CARD, sb.CANCELLED, sb.SAVED, sb.EARLIER, sb.ACT_ON)]
    assert order == sorted(order)
    assert "- Wed 11 Nov: 40 bags cement came\n- Thu 12 Nov: 12 workers" in block
    assert block.endswith('"athu 25 aakku"')


def test_a_quiet_chat_gives_a_small_block() -> None:
    """The block replaces a replay of up to 120 messages; with nothing going on it is a few lines."""
    block = _block({}, message="20 bag cement vannu")
    assert block.count("\n") <= 5 and len(block) < 400


def test_a_record_with_no_site_is_kept_under_its_project_and_another_sites_never() -> None:
    """A project with no site yet takes reports ("Save adds its site"); its records are its project's."""
    rows = [{"occurred_at": "2026-11-13T06:00:00Z", "site_id": None, "project_id": "p-omega",
             "event_type": "material_receipt", "summary": "20 bags cement"},
            {"occurred_at": "2026-11-13T06:00:00Z", "site_id": OTHER, "project_id": "p-omega",
             "event_type": "issue", "summary": "not theirs"}]
    days = sb.today_by_site([], rows, {**SITES, "p-omega": "Omega Towers"}, DAY)
    assert days == [sb.SiteDay("Omega Towers", None, (), ("material_receipt: 20 bags cement",))]


def test_earlier_days_are_one_short_line_each_oldest_first() -> None:
    before, older = DAY - dt.timedelta(days=1), DAY - dt.timedelta(days=2)
    totals = [_total(MAIN, 9, {"mason": 9}, before)]
    rows = [{"occurred_at": f"{before}T0{i}:00:00Z", "site_id": MAIN, "event_type": "material_receipt",
             "summary": f"delivery {i}"} for i in range(5)]
    rows.append({"occurred_at": f"{older}T05:00:00Z", "site_id": ANNEX, "event_type": "issue", "summary": "leak"})
    lines = sb.earlier_days(totals, rows, SITES, [before, older])
    assert lines == [(older, "Annex: 1 records: leak"),
                     (before, "Main Block: 9 workers; 5 records: delivery 0; delivery 1; delivery 2, ...")]
    assert sb.earlier_days([], [], SITES, [before]) == []
    long = [{"occurred_at": f"{before}T05:00:00Z", "site_id": MAIN, "event_type": "x", "summary": "w" * 500}]
    assert len(sb.earlier_days([], long, SITES, [before])[0][1]) == sb.EARLIER_CHARS


# --- from live round 2 (14 Nov 05:08 IST): the block as production logged it --------------------------------------

def test_live_a_cancel_is_listed_once_and_a_line_back_on_the_card_is_not_listed_as_cancelled() -> None:
    from agent_api.agent import line_key

    sand = {"project_id": "p", "site_id": MAIN, "material_id": "m-sand", "quantity": 10}
    carpenters = {"project_id": "p", "site_id": MAIN, "lines": [{"trade": "Carpenter", "headcount": 3}]}
    state: dict = {"pending": [{**_entry("3 carpenter, Main Block", "record_attendance"), "body": carpenters}]}
    for at in (NOW - 900, NOW - 600, NOW - 60):  # cancelled three times, the carpenters once
        sb.remember_cancelled(state, [{"summary": "10 bags sand, Main Block", "key": line_key("record_receipt", sand)}],
                              now=at)
    sb.remember_cancelled(state, [{"summary": "3 carpenter, Main Block",
                                   "key": line_key("record_attendance", carpenters)}], now=NOW - 300)
    cancelled = _block(state).split(sb.CANCELLED)[1].split("\n\n")[0]
    assert cancelled.count("10 bags sand") == 1
    assert "3 carpenter" not in cancelled  # said again: it is on the card, not cancelled


def test_live_saved_in_this_chat_is_the_working_days_only() -> None:
    state = {"recent_saves": [{"fp": "a", "summary": "50 bags cement", "at": NOW - 7200, "tool": "x", "id": "1"},
                              {"fp": "b", "summary": "3 masons", "at": NOW - 60, "tool": "y", "id": "2"}]}
    block = sb.state_block(state, message="x", now=NOW, today=[], since=NOW - 3600)
    assert "3 masons" in block and "50 bags cement" not in block


def test_live_labour_rows_of_the_timeline_are_left_out_whatever_their_case() -> None:
    rows = [{"occurred_at": "2026-11-13T05:00:00Z", "site_id": MAIN, "event_type": "LabourAttendanceRecorded",
             "summary": "10 workers recorded"},
            {"occurred_at": "2026-11-13T06:00:00Z", "site_id": MAIN, "event_type": "MaterialReceived",
             "summary": "45 bags of Cement received"}]
    days = sb.today_by_site([_total(MAIN, 12, {"mason": 12})], rows, SITES, DAY)
    assert days == [sb.SiteDay("Main Block", 12, (("mason", 12),), ("MaterialReceived: 45 bags of Cement received",))]
