"""WEB-68 (6 Nov, Ilan: "the expected workflow for expenses, asking the account to save it under, if there are multi
accounts for that user"): an expense says which money account paid it. The code decides, not the model:

- the accounts this person can pay from: active, held by them or by nobody (company accounts), and not tied to
  another project (someone else's petty cash is never offered);
- one such account: it goes on the expense, and the card line names it (Edit can change it);
- several: the expense is held as usual and Mesiri asks "Paid from which account?" with the accounts as buttons; the
  answer changes the held entry's account;
- none, or the accounts cannot be read (a role without finance access): the expense stays without an account, as
  before.
"""

from __future__ import annotations

from typing import Any

EXPENSE_TOOL = "record_expense"
#: At most this many accounts as buttons (WhatsApp shows three); more are named in the question.
BUTTONS = 3

ACCOUNT_QUESTION: dict[str, str] = {
    "english": "Paid from which account?",
    "manglish": "Ethu account-il ninnaanu paisa koduthathu?",
    "malayalam": "ഏത് അക്കൗണ്ടിൽ നിന്നാണ് പണം കൊടുത്തത്?",
    "hindi": "किस अकाउंट से पैसे दिए?",
    "hinglish": "Kis account se pay kiya?",
}


def account_question(language: str | None, accounts: list[dict[str, str]]) -> str:
    question = ACCOUNT_QUESTION.get(language or "", ACCOUNT_QUESTION["english"])
    if len(accounts) > BUTTONS:  # the rest have no button: name them
        question += " (" + ", ".join(a["name"] for a in accounts) + ")"
    return question


async def paying_accounts(client: Any, user_id: str | None, project_id: Any) -> list[dict[str, str]]:
    """The money accounts this person can pay an expense from (see the module note). Never raises."""
    try:
        response = await client.call("GET", "/finance/accounts", params={"status": "active"})
    except Exception:  # noqa: BLE001 -- no account question rather than no reply
        return []
    if not getattr(response, "ok", False) or not isinstance(response.body, list):
        return []
    out: list[dict[str, str]] = []
    for account in response.body:
        if not isinstance(account, dict) or not account.get("id"):
            continue
        owner = account.get("owner_user_id")
        if owner and user_id and str(owner) != str(user_id):
            continue  # someone else's account (their petty cash)
        tied = account.get("project_id")
        if tied and project_id and str(tied) != str(project_id):
            continue  # another project's account
        out.append({"id": str(account["id"]), "name": str(account.get("name") or "Account").strip()})
    return out
