"""WEB-60 (Ilan, 5 Nov 2026: "make sure sent expense bill and all is there saved for an expense if image is there"):
a bill photo stays with its expense whichever order the messages come in.

The photo key was put only on a write made in the photo's own turn (``agent.py``, ``PHOTO_FIELD``), so it was lost when:

1. the photo came first and the expense was prepared in a later message (Mesiri asked for the site or the amount, and
   the answer made the write): the key is carried into the next message while that question is open;
2. the expense was typed first and was still waiting on its card when the photo came: the code puts the photo on that
   one waiting expense;
3. the expense was already saved: the facts name the expense saved a moment ago without a bill, and the model adds the
   photo to it with ``add_bill_photo`` (``POST /expenses/{id}/attachments``, the route the dashboard uses).

The code decides where a photo goes; the model only says which saved expense a photo belongs to (case 3).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from .agent import BILL_TOOL, PHOTO_FIELD, PendingWrite, WriteResult

EXPENSE_TOOL = "record_expense"
#: How long a photo waits for the answer to the question it raised (case 1).
CARRY_S = 15 * 60
#: How long a saved expense with no bill is offered as the one a photo belongs to (case 3).
UNBILLED_S = 30 * 60


def photo_on(writes: Iterable[PendingWrite], key: str) -> bool:
    """True when one of these writes carries the photo."""
    return any(w.body.get(PHOTO_FIELD) == key for w in writes)


def on_waiting_expense(pending: list[PendingWrite], key: str) -> list[PendingWrite] | None:
    """Case 2: the list with the photo on its one waiting expense that has no photo; None when there is not exactly one
    (two waiting expenses: the code cannot tell which bill it is, so it guesses neither)."""
    bare = [i for i, w in enumerate(pending) if w.tool == EXPENSE_TOOL and not w.body.get(PHOTO_FIELD)]
    if len(bare) != 1:
        return None
    out = list(pending)
    out[bare[0]] = replace(out[bare[0]], body={**out[bare[0]].body, PHOTO_FIELD: key})
    return out


def carried(state: dict[str, Any], now: float) -> str | None:
    """Case 1: the photo left waiting for an answer, once, while it is fresh. Always taken off the state."""
    kept = state.pop("photo", None) or {}
    if kept.get("key") and now - float(kept.get("at") or 0) < CARRY_S:
        return str(kept["key"])
    return None


def remember_unbilled(state: dict[str, Any], results: Iterable[WriteResult], now: float) -> None:
    """Case 3: the newest expense saved without a bill (or no such one once its bill is added)."""
    for r in results:
        if not r.ok:
            continue
        if r.pending.tool == BILL_TOOL:
            last = (state.get("unbilled") or {}).get("expense_id")
            if last and r.pending.path == f"/expenses/{last}/attachments":
                state.pop("unbilled", None)
        elif r.pending.tool == EXPENSE_TOOL:
            expense_id = r.body.get("id") if isinstance(r.body, dict) else None
            if r.pending.body.get(PHOTO_FIELD) or not expense_id:
                state.pop("unbilled", None)
            else:
                state["unbilled"] = {"expense_id": str(expense_id), "summary": r.pending.summary, "at": now}


def unbilled_fact(state: dict[str, Any], now: float) -> str:
    """Case 3: the line the model reads with a photo, naming the expense saved a moment ago without its bill."""
    last = state.get("unbilled") or {}
    if not last.get("expense_id") or now - float(last.get("at") or 0) >= UNBILLED_S:
        state.pop("unbilled", None)
        return ""
    minutes = max(1, round((now - float(last["at"])) / 60))
    return (f"Saved {minutes} min ago with no bill photo: {last.get('summary') or 'an expense'} "
            f"(expense_id {last['expense_id']}). If this photo is that expense's bill (same amount or vendor), "
            f"prepare `{BILL_TOOL}` on it, never a second expense.")
