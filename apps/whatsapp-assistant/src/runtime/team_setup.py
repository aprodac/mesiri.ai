"""Team and setup questions answered without the model (WA-84, plan of 27 Oct, W8).

Live 27 Oct (docs/qa/runs/2026-10-27-whatsapp-live-tests, screenshots 07 and 11):

- "report time 7 pm aakku" -> "I can't change the report time" (English, and the
  setup card lists "Report time set" as a step): the existing setup question of
  SS-14 (runtime/setup_questions.py) is now offered for it, with its 7 / 8 / 9 pm
  buttons; the tap changes it, as before;
- "ente team-il aarokke und?" -> "I only give join codes": the sender's own
  projects and who is on them, read only.

Pure detection and wording here; the reads are ``ProjectDetailQueryService`` and
``SetupQuestions``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

#: "report time 7 pm aakku", "report 8 manikku ayakkanam", "change report timing", "റിപ്പോർട്ട് സമയം".
_REPORT_TIME = re.compile(
    r"\breport\w*\s+(?:time|timing|samayam)\b|\b(?:time|timing|samayam)\s+(?:of|for)?\s*(?:the\s+)?report\b"
    r"|റിപ്പോർട്ട്\s*സമയം|\breport\w*\b[^?]{0,20}\b\d{1,2}\s*(?:pm|p\.m\.|mani\w*)",
    re.IGNORECASE,
)
_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(?:pm|p\.m\.|mani\w*|o'?clock)?", re.IGNORECASE)

#: "ente team-il aarokke und?", "who is in my team", "team members", "ടീമിൽ ആരൊക്കെ".
_TEAM = re.compile(
    r"\bteam\w*\b.{0,20}\b(?:aar\w*|who|members?|list)\b|\b(?:who|aar\w*)\b.{0,25}\bteam\w*\b"
    r"|\bteam\s+members?\b|ടീമിൽ\s*ആര",
    re.IGNORECASE,
)

ROLE_WORDS = {"ADMIN": "Admin", "PROJECT_MANAGER": "Project Manager", "SITE_ENGINEER": "Site Engineer",
              "FINANCE": "Finance"}


def report_time_asked(text: str) -> tuple[bool, str | None]:
    """(asked, "HH:MM") for a request to change the daily report time; the time is
    None when none is said. "25 Oct report ayakku" is not one."""
    text = text or ""
    if not _REPORT_TIME.search(text):
        return False, None
    for hour, minute in _CLOCK.findall(text):
        h = int(hour)
        if 1 <= h <= 12:
            h = h + 12 if h < 12 else h  # a report goes out in the evening
        if 13 <= h <= 23:
            return True, f"{h:02d}:{int(minute or 0):02d}"
    return True, None


def is_team_question(text: str) -> bool:
    """A question about who is on the sender's team (not a request to add someone)."""
    text = text or ""
    if re.search(r"\b(?:add|aakk\w*|cherkk\w*|join|remove|maatt\w*)\b", text, re.IGNORECASE):
        return False
    return bool(_TEAM.search(text))


def team_text(rows: Iterable[tuple[str, str, str]], projects: dict[str, str]) -> str:
    """"Project Alpha: Ravi (Site Engineer), Anil (Admin)" per project, from
    (project_id, name, role) rows. Says so when nobody else is on them."""
    by_project: dict[str, list[str]] = {}
    for project_id, name, role in rows:
        by_project.setdefault(str(project_id), []).append(f"{name} ({ROLE_WORDS.get(str(role), str(role).title())})")
    lines = [f"*{projects[p]}*: {', '.join(sorted(names))}" for p, names in by_project.items() if p in projects]
    if not lines:
        return "Nobody is added to your projects yet. To add someone, send their name and role, e.g. “add Ravi as site engineer”."
    return "Your team:\n" + "\n".join(lines)


def project_names(actor: Any) -> dict[str, str]:
    return {str(p.id): str(p.name) for p in getattr(actor, "projects", None) or []}
