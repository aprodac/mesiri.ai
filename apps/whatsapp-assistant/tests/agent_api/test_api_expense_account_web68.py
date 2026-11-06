"""WEB-68 (6 Nov, Ilan: an expense should say which account paid it, asked when he has several): the code reads the
accounts this person can pay from and decides: one account goes on the expense and its line; several: Mesiri asks
"Paid from which account?" with the accounts as buttons, the question always in the reply; none, or no finance access:
the expense is held as before. Someone else's petty cash and another project's account are never offered.
"""

from __future__ import annotations

from typing import Any

from tests.agent_api.replaykit import RecordedApi, _real_tools
from tests.agent_api.test_api_lose_nothing_198 import Runs

from agent_api.agent import SOP, ApiAgent
from agent_api.client import ApiResponse

ME, OTHER = "u-me", "u-other"
P, Q = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
EXPENSE = ("record_expense", {"project_id": P, "amount": 140, "occurred_date": "2026-11-06",
                              "vendor_text": "Irani Cafe NIBM", "confirm_line": "₹140 food, Irani Cafe NIBM"})


class Accounts(RecordedApi):
    """The accounts list as /finance/accounts gives it; anything else as RecordedApi."""

    def __init__(self, accounts: Any, *, status: int = 200) -> None:
        super().__init__({})
        self.accounts = accounts
        self.status = status
        self.user_id = ME

    async def call(self, method: str, path: str, **kw: Any) -> ApiResponse:
        if path == "/finance/accounts":
            self.seen.append((method, path))
            return ApiResponse(status=self.status, body=self.accounts)
        return await super().call(method, path, **kw)


def _acc(i: str, name: str, owner: str | None = None, project: str | None = None) -> dict:
    return {"id": i, "name": name, "owner_user_id": owner, "project_id": project, "status": "active"}


async def _turn(api: Accounts, reply: str = "₹140 for food from Irani Cafe NIBM, 30 Dec. Tap Save to keep it.") -> Any:
    return await ApiAgent(Runs([[EXPENSE], reply]), _real_tools()).run(api, "(sent a photo)")  # type: ignore[arg-type]


async def test_several_accounts_ask_which_with_buttons_and_the_question_is_in_the_reply() -> None:
    api = Accounts([_acc("a1", "Site Cash", ME), _acc("a2", "HDFC Main"), _acc("a3", "Petty cash Anu", OTHER)])
    turn = await _turn(api)
    assert turn.pending and "account_id" not in turn.pending[0].body
    assert turn.question == "Paid from which account?" and turn.options == ["Site Cash", "HDFC Main"]
    assert "Paid from which account?" in turn.reply  # the model left it out; the code put it in


async def test_one_account_goes_on_the_expense_and_its_line() -> None:
    api = Accounts([_acc("a1", "Site Cash", ME), _acc("a3", "Petty cash Anu", OTHER), _acc("a4", "Mall cash", None, Q)])
    turn = await _turn(api)
    assert turn.pending[0].body["account_id"] == "a1" and turn.pending[0].summary.endswith("· Site Cash")
    assert not turn.question


async def test_more_than_three_accounts_are_named_in_the_question() -> None:
    api = Accounts([_acc(f"a{i}", f"Acc {i}") for i in range(5)])
    turn = await _turn(api)
    assert turn.options == ["Acc 0", "Acc 1", "Acc 2"] and "Acc 4" in turn.question


async def test_guard_no_accounts_or_no_finance_access_hold_it_as_before() -> None:
    for api in (Accounts([]), Accounts({"detail": "Forbidden"}, status=403)):
        turn = await _turn(api)
        assert turn.pending and "account_id" not in turn.pending[0].body and not turn.question


async def test_guard_an_account_they_named_is_kept() -> None:
    named = ("record_expense", {**EXPENSE[1], "account_id": "a2"})
    api = Accounts([_acc("a1", "Site Cash"), _acc("a2", "HDFC Main")])
    turn = await ApiAgent(Runs([[named], "₹140 from HDFC Main. Tap Save."]), _real_tools()).run(api, "140 food, HDFC-il ninnu")  # type: ignore[arg-type]
    assert turn.pending[0].body["account_id"] == "a2" and not turn.question and ("GET", "/finance/accounts") not in api.seen


def test_the_sop_says_the_expense_in_the_reply_and_who_asks_the_account() -> None:
    assert 'never only "tap Save"' in SOP and "Which account paid it is the code's" in SOP
