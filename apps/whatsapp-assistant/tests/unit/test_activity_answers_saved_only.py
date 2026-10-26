"""WA-77: "what work was done?" answers from saved entries; the agent's own
picture of today still sees unsaved ones, so it never logs a thing twice."""

from __future__ import annotations

import inspect

from runtime import today_context
from runtime.activity_search_service import ActivitySearchService


def test_answers_leave_out_unsaved_by_default():
    params = inspect.signature(ActivitySearchService.search).parameters
    assert params["include_unsaved"].default is False
    assert "counted_sql(fact_review.ACTIVITY" in inspect.getsource(ActivitySearchService.search)


def test_the_agents_today_sees_unsaved_entries():
    assert "include_unsaved=True" in inspect.getsource(today_context)
