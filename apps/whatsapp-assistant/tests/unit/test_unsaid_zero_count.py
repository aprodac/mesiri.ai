"""Request 192: "cement finished" must never become a stock count of 0."""

from __future__ import annotations

import pytest

from runtime.agent.toolbox import unsaid_zero_count


@pytest.mark.parametrize(
    "text",
    [
        "cement stock kazhinjittundu, nale venam",
        "cement theernnu",
        "cement is finished",
        "सीमेंट खतम हो गया",
        "സിമൻറ് തീർന്നു",
        "Cement in: 50 bag, cement running out",
        "used all 10 bags",
    ],
)
def test_a_finish_is_not_a_zero_count(text):
    assert unsaid_zero_count(text, {"material": "cement", "counted": 0}) is True


@pytest.mark.parametrize(
    "text", ["cement count 0 bag", "cement stock zero", "Set cement stock to 0", "സിമൻറ് പൂജ്യം", "cement 0.0"]
)
def test_a_said_zero_still_counts(text):
    assert unsaid_zero_count(text, {"material": "cement", "counted": 0}) is False


def test_other_counts_and_no_figure_are_untouched():
    assert unsaid_zero_count("cement theernnu", {"material": "cement", "counted": 20}) is False
    assert unsaid_zero_count("cement theernnu", {"material": "cement"}) is False
    assert unsaid_zero_count("cement theernnu", {"material": "cement", "counted": None}) is False
