"""Tasks rules (TSK-01): status moves, who may do what, overdue, picking a name from words."""

from __future__ import annotations

import datetime

import pytest

from mesiri.domains.organizations import settings
from mesiri.domains.tasks import logic

TODAY = datetime.date(2026, 11, 9)
GIVER, DOER, OTHER = "u-giver", "u-doer", "u-other"
TASK = {"created_by": GIVER, "assignee_user_id": DOER, "status": "open"}


@pytest.mark.parametrize(("current", "target"), [
    ("open", "doing"), ("open", "blocked"), ("open", "done"), ("open", "cancelled"),
    ("doing", "done"), ("doing", "open"), ("blocked", "doing"), ("blocked", "done"),
    ("done", "open"), ("cancelled", "open"),
])
def test_allowed_moves(current, target):
    assert logic.move_error(current, target, "no shuttering") is None


@pytest.mark.parametrize(("current", "target", "words"), [
    ("done", "doing", "can only be reopened"),
    ("cancelled", "done", "can only be reopened"),
    ("done", "done", "already done"),
    ("open", "finished", "Unknown status"),
])
def test_refused_moves_say_why(current, target, words):
    assert words in logic.move_error(current, target, None)


def test_blocked_needs_a_reason():
    assert logic.move_error("open", "blocked", "  ") == "Say what is blocking it"
    assert logic.move_error("open", "blocked", "no shuttering") is None


def test_who_may_create():
    for role in ("OWNER", "ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "site_engineer"):
        assert logic.may_create(role)
    for role in ("FINANCE", "SUPERVISOR", "", None):
        assert not logic.may_create(role)


def test_the_doer_moves_but_never_cancels_and_never_edits():
    assert logic.may_move("SITE_ENGINEER", DOER, TASK, "done")
    assert logic.may_move("SITE_ENGINEER", DOER, TASK, "blocked")
    assert not logic.may_move("SITE_ENGINEER", DOER, TASK, "cancelled")
    assert not logic.may_edit("SITE_ENGINEER", DOER, TASK)


def test_the_giver_and_managers_edit_and_cancel():
    assert logic.may_edit("SITE_ENGINEER", GIVER, TASK)
    assert logic.may_move("SITE_ENGINEER", GIVER, TASK, "cancelled")
    assert logic.may_edit("PROJECT_MANAGER", OTHER, TASK)
    assert logic.may_move("OWNER", OTHER, TASK, "cancelled")


def test_someone_else_on_the_site_cannot_move_it():
    assert not logic.may_move("SITE_ENGINEER", OTHER, TASK, "done")
    assert logic.may_comment("SITE_ENGINEER", OTHER, TASK)
    assert not logic.may_comment("FINANCE", OTHER, TASK)


def test_overdue_only_while_still_waiting():
    yesterday = TODAY - datetime.timedelta(days=1)
    assert logic.is_overdue("open", yesterday, TODAY)
    assert logic.days_late("blocked", TODAY - datetime.timedelta(days=3), TODAY) == 3
    assert not logic.is_overdue("open", TODAY, TODAY)  # due today is not late yet
    assert not logic.is_overdue("done", yesterday, TODAY)
    assert not logic.is_overdue("open", None, TODAY)
    assert logic.days_late("done", yesterday, TODAY) == 0


def test_sort_puts_late_first_then_due_then_urgent():
    tasks = [
        {"number": 1, "status": "open", "due_date": None, "priority": "urgent"},
        {"number": 2, "status": "open", "due_date": TODAY + datetime.timedelta(days=2), "priority": "normal"},
        {"number": 3, "status": "open", "due_date": TODAY - datetime.timedelta(days=1), "priority": "normal"},
        {"number": 4, "status": "open", "due_date": TODAY + datetime.timedelta(days=2), "priority": "urgent"},
    ]
    assert [t["number"] for t in sorted(tasks, key=lambda t: logic.sort_key(t, TODAY))] == [3, 4, 2, 1]


@pytest.mark.parametrize(("words", "number"), [("T-14", 14), ("t14", 14), ("T 7", 7), ("14", 14), (" t-3 ", 3)])
def test_task_numbers_as_said(words, number):
    assert logic.parse_ref(words) == number


@pytest.mark.parametrize("words", ["", "task", "T-", "grid B"])
def test_not_a_task_number(words):
    assert logic.parse_ref(words) is None


PEOPLE = [{"name": "Arun Kumar"}, {"name": "Arun Das"}, {"name": "Ravi"}, {"name": "Biju Thomas"}]


def test_pick_by_exact_name_first_word_or_surname():
    assert logic.pick("ravi", PEOPLE, lambda p: p["name"]).item["name"] == "Ravi"
    assert logic.pick("arun das", PEOPLE, lambda p: p["name"]).item["name"] == "Arun Das"
    assert logic.pick("Thomas", PEOPLE, lambda p: p["name"]).item["name"] == "Biju Thomas"


def test_pick_offers_choices_when_several_or_none_fit():
    several = logic.pick("arun", PEOPLE, lambda p: p["name"])
    assert several.item is None and several.options == ["Arun Kumar", "Arun Das"]
    none = logic.pick("Suresh", PEOPLE, lambda p: p["name"])
    assert none.item is None and len(none.options) == 4


def test_tasks_is_a_module_on_by_default():
    assert "tasks" in settings.MODULES and "tasks" in settings.MODULE_LABELS
    assert "tasks" in settings.V1_MODULES
    assert "tasks" not in settings.ALWAYS_ON_MODULES  # can be switched off per company
