"""UX-22: a fifth start mode, ``new_to_construction``: stored like the others, kept in step with migration 0555's
check, and given the step-by-step tips on WhatsApp."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
from pydantic import ValidationError

from mesiri.application.organizations.trials_funnel import START_MODE_LABELS
from mesiri.domains.identity import preferences_router as me
from mesiri.domains.organizations import setup_questions as rules

MIGRATION = pathlib.Path(__file__).parents[2] / "migrations" / "versions" / "0555_users_start_mode_new_to_construction.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0555", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_mode_is_an_answer_and_the_check_allows_every_answer() -> None:
    assert "new_to_construction" in me.START_MODES
    assert set(_migration()._VALUES) == set(me.START_MODES)
    assert me.StartModeIn(start_mode="new_to_construction").start_mode == "new_to_construction"


def test_unknown_mode_still_refused() -> None:
    with pytest.raises(ValidationError):
        me.StartModeIn(start_mode="expert")


def test_stored_new_mode_stands() -> None:
    import datetime as dt
    now = dt.datetime(2026, 11, 17, tzinfo=dt.UTC)
    assert me.start_mode_for("new_to_construction", now - dt.timedelta(days=90), now) == ("new_to_construction", False)


def test_every_mode_has_a_label_and_new_gets_the_guided_tips() -> None:
    assert set(me.START_MODES) <= set(START_MODE_LABELS)
    assert rules.TIPS["new_to_construction"] == rules.TIPS["guided"]
