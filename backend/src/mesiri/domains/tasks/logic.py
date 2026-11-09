"""Tasks (TSK-01): the rules, pure, no I/O.

A task is work given to someone by a day: "Arun: tie steel for grid B by Thursday". It is for a person in the
company (a user), a subcontractor (a vendor) or a team named in words, and it moves through

    open -> doing -> done        blocked (with a reason) from open or doing     cancelled from any open state

A done or cancelled task can be reopened. Closing a task never records work done (D-T4): work is reported as work,
and the task only reads it, so the BOQ never counts the same work twice.

Who may do what (D-T2), on top of the project and site scope the router checks:

- create and assign: owner, admin, project manager, site engineer;
- change the details or cancel: the person who gave it and the managers;
- move the status or comment: also the person it is for.

Plan: docs/plans/tasks-plan.md.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

OPEN, DOING, BLOCKED, DONE, CANCELLED = "open", "doing", "blocked", "done", "cancelled"
STATUSES = (OPEN, DOING, BLOCKED, DONE, CANCELLED)
#: Statuses still waiting on someone (shown by default, counted as overdue when late).
LIVE = frozenset({OPEN, DOING, BLOCKED})
PRIORITIES = ("normal", "high", "urgent")

#: Every move allowed, from -> to. Anything else is refused with the words from ``move_error``.
MOVES: dict[str, frozenset[str]] = {
    OPEN: frozenset({DOING, BLOCKED, DONE, CANCELLED}),
    DOING: frozenset({OPEN, BLOCKED, DONE, CANCELLED}),
    BLOCKED: frozenset({OPEN, DOING, DONE, CANCELLED}),
    DONE: frozenset({OPEN}),
    CANCELLED: frozenset({OPEN}),
}

MANAGER_ROLES = frozenset({"OWNER", "ADMIN", "SUPER_ADMIN", "PROJECT_MANAGER"})
CREATE_ROLES = MANAGER_ROLES | {"SITE_ENGINEER"}

_WORDS = {OPEN: "open", DOING: "in progress", BLOCKED: "blocked", DONE: "done", CANCELLED: "cancelled"}


def ref(number: int) -> str:
    """How a task is named and said: T-14."""
    return f"T-{number}"


def parse_ref(words: str) -> int | None:
    """The number in "T-14", "t14", "T 14" or "14"; None when the words are not a task number."""
    m = re.fullmatch(r"\s*(?:t\s*-?\s*)?(\d{1,7})\s*", words or "", flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


def move_error(current: str, target: str, reason: str | None) -> str | None:
    """Why the move from ``current`` to ``target`` is refused, or None when it is allowed."""
    if target not in STATUSES:
        return f"Unknown status {target!r}: use one of {', '.join(STATUSES)}"
    if target == current:
        return f"The task is already {_WORDS[current]}"
    if target not in MOVES[current]:
        return f"A {_WORDS[current]} task can only be reopened" if current in (DONE, CANCELLED) else \
            f"A {_WORDS[current]} task cannot be moved to {_WORDS[target]}"
    if target == BLOCKED and not (reason or "").strip():
        return "Say what is blocking it"
    return None


def may_create(role: str) -> bool:
    return (role or "").upper() in CREATE_ROLES


def is_manager(role: str) -> bool:
    return (role or "").upper() in MANAGER_ROLES


def may_edit(role: str, user_id: Any, task: dict[str, Any]) -> bool:
    """Change the details, reassign or cancel: the person who gave it, or a manager."""
    return is_manager(role) or (task.get("created_by") is not None and str(task["created_by"]) == str(user_id))


def may_move(role: str, user_id: Any, task: dict[str, Any], target: str) -> bool:
    """Move the status: also the person it is for, except cancelling (that is the giver's call)."""
    if may_edit(role, user_id, task):
        return True
    mine = task.get("assignee_user_id") is not None and str(task["assignee_user_id"]) == str(user_id)
    return mine and target != CANCELLED


def may_comment(role: str, user_id: Any, task: dict[str, Any]) -> bool:
    """Anyone who may see the task on a project they work on, except finance (it does not run the site)."""
    return (role or "").upper() != "FINANCE" or may_edit(role, user_id, task)


def is_overdue(status: str, due: datetime.date | None, today: datetime.date) -> bool:
    return status in LIVE and due is not None and due < today


def days_late(status: str, due: datetime.date | None, today: datetime.date) -> int:
    return (today - due).days if is_overdue(status, due, today) and due is not None else 0


T = TypeVar("T")


@dataclass
class Pick:
    """``item``: the one meant. ``options``: the names to choose from when the words fit several or none."""

    item: Any = None
    options: list[str] = field(default_factory=list)


def _norm(words: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (words or "").lower()).split())


def pick(words: str, items: Sequence[T], name_of: Callable[[T], str]) -> Pick:
    """The one item the words name: the exact name, else the only name that starts with the words or has a word
    starting with them ("arun" -> "Arun Kumar"). Several or none: the options to choose from (every name, when
    nothing fits)."""
    said = _norm(words)
    if not said:
        return Pick(options=[name_of(i) for i in items])
    exact = [i for i in items if _norm(name_of(i)) == said]
    if len(exact) == 1:
        return Pick(item=exact[0])
    starts = [i for i in items if _norm(name_of(i)).startswith(said)
              or any(w.startswith(said) for w in _norm(name_of(i)).split())]
    if len(starts) == 1:
        return Pick(item=starts[0])
    return Pick(options=[name_of(i) for i in (starts or exact or items)])


def sort_key(task: dict[str, Any], today: datetime.date) -> tuple:
    """Late first, then by due day (none last), then urgent before normal, then the oldest."""
    due = task.get("due_date")
    return (0 if is_overdue(task["status"], due, today) else 1,
            due or datetime.date.max,
            -PRIORITIES.index(task.get("priority") or "normal"),
            task.get("number") or 0)
