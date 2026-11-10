"""WA-265: the real-model run of the saved conversations stops spending when its budget is used.

``MESIRI_EVAL_BUDGET_USD`` (set by the "SOP eval" workflow from the day's ledger) is what this run may spend;
``MESIRI_USAGE_LOG`` is where tests/conftest.py writes each model call. Before every live conversation the spend
so far is read from that log, and once it reaches the budget the rest are skipped (shown in the ``-ra`` summary),
never failed: a conversation that did not run says nothing about the model.
"""

from __future__ import annotations

import os

import pytest
from tests.agent_api.evalbudget import spent_usd

OUT_OF_BUDGET = "eval budget for today is used up"


def budget_left(budget: str | None, log: str | None) -> bool:
    """False once the usage log's spend has reached the budget; no budget (a local run) is never out."""
    if not budget or not log:
        return True
    try:
        limit = float(budget)
    except ValueError:
        return True
    return spent_usd(log) < limit


@pytest.fixture(autouse=True)
def _within_eval_budget(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("live") is None:
        return
    if not budget_left(os.environ.get("MESIRI_EVAL_BUDGET_USD"), os.environ.get("MESIRI_USAGE_LOG")):
        pytest.skip(OUT_OF_BUDGET)
