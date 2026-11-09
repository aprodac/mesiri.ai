"""GM-06: who is on an issue, by when, and a reminder.

The owner is ``site_issues.assigned_user_id`` (it was always there; nothing set it); ``due_on`` is migration 0534.
Anyone who can reach the issue's project and site may put someone on it, someone who can reach it too. The person put
on it is told on WhatsApp once; "remind" tells them again, at most once a day per issue. Both go through the
notification queue: outside the 24-hour window the note waits for their next message (no template needed), as the
material request notes do (PRC-25).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_WORDS = {
    "assigned": {
        "english": "🛠️ You are on this issue{by}: {what} ({where}){due}. Reply when it is sorted.",
        "manglish": "🛠️ Ee issue ningalude perilaanu{by}: {what} ({where}){due}. Theernnaal ariyikkuka.",
        "malayalam": "🛠️ ഈ പ്രശ്നം നിങ്ങളുടെ ചുമതലയിലാണ്{by}: {what} ({where}){due}. തീർന്നാൽ അറിയിക്കുക.",
    },
    "remind": {
        "english": "⏰ Reminder{by}: {what} ({where}) is still open, {age}{due}. Reply when it is sorted.",
        "manglish": "⏰ Orma{by}: {what} ({where}) ippozhum open aanu, {age}{due}. Theernnaal ariyikkuka.",
        "malayalam": "⏰ ഓർമ്മപ്പെടുത്തൽ{by}: {what} ({where}) ഇപ്പോഴും തീർന്നിട്ടില്ല, {age}{due}. തീർന്നാൽ അറിയിക്കുക.",
    },
}
_DUE = {"english": ", due {d}", "manglish": ", {d}-inu munpu", "malayalam": ", {d}-ന് മുമ്പ്"}
_AGE = {"english": "{n} days", "manglish": "{n} divasamaayi", "malayalam": "{n} ദിവസമായി"}


def _lang(language: str | None) -> str:
    if language in ("english", "manglish", "malayalam"):
        return language
    return "english" if language in ("hindi", "hinglish") else "manglish"


def message(kind: str, issue: dict[str, Any], *, where: str, by: str | None, language: str | None,
            today: datetime.date) -> str:
    """What the person on the issue is told: ``assigned`` or ``remind``, in their language, one line."""
    lang = _lang(language)
    what = (issue.get("narrative") or str(issue.get("issue_type") or "issue").replace("_", " ").lower()).strip()
    what = what if len(what) <= 80 else what[:77].rstrip() + "…"
    due = _DUE[lang].format(d=f"{issue['due_on']:%a} {issue['due_on'].day} {issue['due_on']:%b}") if issue.get("due_on") else ""
    occurred = issue["occurred_at"]
    age_days = (today - (occurred.date() if isinstance(occurred, datetime.datetime) else occurred)).days
    by_words = "" if not by else (f" from {by}" if lang == "english" else f" ({by})")
    return _WORDS[kind][lang].format(what=what, where=where, due=due, by=by_words,
                                     age=_AGE[lang].format(n=max(age_days, 0)))


async def assignee_may_reach(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
    """An active person of the company who works on this project: a member, or someone who reaches every project
    (the shared rule, ``roles.role_is_org_wide`` by role or an all-projects grant)."""
    from mesiri.authorization.roles import role_is_org_wide

    row = (await conn.execute(text(
        "SELECT u.role, u.access_policy->>'mode' AS mode, EXISTS (SELECT 1 FROM project_members m WHERE "
        "m.user_id = u.id AND m.project_id = :p) AS member FROM users u WHERE u.id = :u AND u.organization_id = :org "
        "AND u.status = 'active'"), {"u": user_id, "org": org, "p": project_id})).mappings().first()
    if row is None:
        return False
    return bool(row["member"]) or role_is_org_wide(str(row["role"]).upper()) or str(row["mode"] or "") == "all_projects"


async def person_named(conn: AsyncConnection, org: uuid.UUID, said: str, project_id: uuid.UUID) -> tuple[uuid.UUID | None, str]:
    """The one person who works on this project called ``said`` (WhatsApp: "Anil will fix it"): the full name, else
    the first name, else a name that starts with it. Returns (id, "") or (None, what to tell them)."""
    rows = (await conn.execute(text(
        "SELECT id, full_name FROM users WHERE organization_id = :org AND status = 'active' AND full_name IS NOT NULL"),
        {"org": org})).mappings().all()
    people = [r for r in rows if await assignee_may_reach(conn, org, r["id"], project_id)]
    word = said.strip().casefold()
    for test in (lambda n: n == word, lambda n: n.split()[0] == word, lambda n: n.startswith(word)):
        found = [p for p in people if p["full_name"].strip() and test(p["full_name"].strip().casefold())]
        if len(found) == 1:
            return found[0]["id"], ""
        if len(found) > 1:
            return None, f"More than one person is called {said}: {', '.join(p['full_name'] for p in found[:4])}. Which one?"
    return None, f"No one called {said} works on this project."


async def set_owner(conn: AsyncConnection, issue_id: uuid.UUID, user_id: uuid.UUID | None,
                    due_on: datetime.date | None) -> None:
    await conn.execute(text("UPDATE site_issues SET assigned_user_id = :u, due_on = :d, updated_at = now() WHERE id = :id"),
                       {"u": user_id, "d": due_on, "id": issue_id})


async def tell(conn: AsyncConnection, org: uuid.UUID, issue: dict[str, Any], kind: str, recipient: uuid.UUID,
               by: str | None, today: datetime.date) -> bool:
    """Queue the note to the person on the issue. False when the same note was already queued (today, for a
    reminder; for this owner and due date, for an assignment)."""
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    names = (await conn.execute(text(
        "SELECT (SELECT name FROM projects WHERE id = :p) AS project, (SELECT name FROM sites WHERE id = :s) AS site, "
        "(SELECT reply_language FROM users WHERE id = :u) AS language"),
        {"p": issue["project_id"], "s": issue["site_id"], "u": recipient})).mappings().first()
    where = ", ".join(x for x in (names["site"], names["project"]) if x)
    subject = f"{issue['id']}:{today}" if kind == "remind" else f"{issue['id']}:{recipient}:{issue.get('due_on') or ''}"
    claimed = await PostgresNotificationRepository(conn).claim(
        organization_id=org, rule_key=f"issue_{kind}", subject_id=subject, occurred_on=today,
        recipient_user_id=recipient, project_id=issue["project_id"], site_id=issue["site_id"],
        payload={"message": message(kind, issue, where=where, by=by, language=names["language"], today=today),
                 "hold_until_window": True, "hold_days": 2})
    return bool(claimed)
