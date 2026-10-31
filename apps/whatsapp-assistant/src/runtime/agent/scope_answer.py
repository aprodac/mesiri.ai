"""Live 30 Oct (request 160): "which projects am I on?" is answered, not asked back.

A question about the sender's OWN scope (their projects, sites, role) has no project
to settle: the sender's actor already carries the answer. ``my_scope`` builds it
from the actor in code -- the model only puts it in the sender's language -- so
nothing comes from the model's memory and no other company's project can appear
(the actor is already scoped to the sender's company and assignments).

``asks_own_scope`` is the code-side guard for ``query_project``: with no project
named, such a question goes to ``my_scope``, never to the "which project?" clarifier.
"""

from __future__ import annotations

import re
from typing import Any

#: Roles that see the company's projects, not only assigned ones.
_COMPANY_WIDE = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN"})

_PROJ = r"(?:projects?|sites?|prok?jects?|പ്രോജക്ട\w*|സൈറ്റ\w*|പ്രൊജക്ട\w*)"
_OWN = re.compile(
    r"(?:"
    rf"\bmy\s+(?:{_PROJ}|role|assignments?)"
    rf"|\b(?:ente|ende|enta|nte)\s+{_PROJ}"
    rf"|\b(?:which|what|list|show|ethu|ethokke|ethanu)\b[^?.!]*\b{_PROJ}[^?.!]*\b(?:am\s+i|i\s+am|i'?m|do\s+i|i\s+have|njan|ente|ennod)\b"
    rf"|\b(?:am\s+i|i'?m|i\s+am)\s+(?:assigned|working|added|on|in)\b[^?.!]*(?:{_PROJ}|where)"
    r"|\bwhere\s+am\s+i\s+(?:assigned|working|posted|added)"
    r"|\bassigned\s+to\b"
    rf"|\b{_PROJ}\b[^?.!]*\b(?:ethokke|ethanu|ethaanu|undo|ullathu)\b[^?.!]*\b(?:njan|ente)\b"
    rf"|\b(?:{_PROJ})\s+ethokke\b"
    r"|\bdefault\s+site\b"
    r"|\bmy\s+scope\b"
    r"|എന്റെ\s*(?:പ്രോജക്ട|സൈറ്റ|പ്രൊജക്ട)"
    r"|ഏതൊക്കെ\s*(?:പ്രോജക്ട|സൈറ്റ|പ്രൊജക്ട)"
    r"|(?:പ്രോജക്ട|പ്രൊജക്ട)\w*\s*ഏതാ"
    r")",
    re.IGNORECASE,
)

#: "who is on Hospital project": a team question, not the sender's own scope.
_TEAM = re.compile(r"\bwho\b|\bteam\b|\bmembers?\b|ആരൊക്കെ", re.IGNORECASE)


def asks_own_scope(text: str) -> bool:
    """True when the words are about the sender's own projects / sites / role."""
    text = text or ""
    return bool(_OWN.search(text)) and not _TEAM.search(text)


def _role(role: Any) -> str:
    return str(role or "").strip().replace("_", " ").title() or "Member"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def project_names(actor: Any) -> list[str]:
    return [str(p.name) for p in getattr(actor, "projects", None) or []]


def scope_facts(actor: Any) -> str:
    """The sender's role, projects (place, sites) and sites, from the actor only."""
    projects = list(getattr(actor, "projects", None) or [])
    sites = list(getattr(actor, "sites", None) or [])
    role = str(getattr(actor, "role", "") or "").strip().upper()
    wide = role in _COMPANY_WIDE
    lines = [f"Role: {_role(role)}" + (f" at {actor.org_name}" if getattr(actor, "org_name", None) else "") + "."]
    if not projects:
        lines.append(
            "Projects: none. They are not on any project yet; an admin or project manager can add them."
        )
        return "\n".join(lines)
    head = (
        f"The company has {_plural(len(projects), 'project')}:"
        if wide
        else f"They are on {_plural(len(projects), 'project')}:"
    )
    lines.append(head)
    for p in projects:
        mine = [s for s in sites if str(s.project_id) == str(p.id)]
        detail = []
        if getattr(p, "location", None):
            detail.append(str(p.location))
        if mine:
            detail.append(_plural(len(mine), "site"))
        lines.append(f"- {p.name}" + (f" ({' · '.join(detail)})" if detail else ""))
        if len(mine) > 1 or (mine and len(projects) == 1):
            lines.append("  Sites: " + ", ".join(str(s.name) for s in mine))
    orphans = [s for s in sites if s.project_id is None or str(s.project_id) not in {str(p.id) for p in projects}]
    if orphans:
        lines.append("Other sites: " + ", ".join(str(s.name) for s in orphans))
    return "\n".join(lines)
