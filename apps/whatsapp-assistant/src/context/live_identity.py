"""Live WhatsApp sender identity bridge.

This module orchestrates identity resolution for inbound WhatsApp messages
and formats user-facing replies. It depends only on the ActorReader port —
it knows nothing about tables, SQL, or database connections.

All schema/persistence knowledge lives in postgres_actor.PostgresActorReader.
"""

from __future__ import annotations

import re

from backend.ports import ActorIdentity, ActorReader, ProjectSummary

# ---------------------------------------------------------------------------
# Utility (pure, no I/O)
# ---------------------------------------------------------------------------


def _digits(s: str | None) -> str:
    """Strip all non-digit characters, normalising phone / WhatsApp IDs."""
    if s is None:
        return ""
    return re.sub(r"\D", "", str(s))


# ---------------------------------------------------------------------------
# Resolve sender (pure orchestration — no SQL)
# ---------------------------------------------------------------------------


async def resolve_sender(reader: ActorReader, wa_id: str) -> ActorIdentity | None:
    """Resolve the WhatsApp sender to their ActorIdentity, or None if unknown.

    The reader owns all SQL; this function owns nothing about persistence.
    """
    return await reader.resolve_by_whatsapp_id(wa_id)


# ---------------------------------------------------------------------------
# Project selection helper (pure logic — no I/O)
# ---------------------------------------------------------------------------

_PROJECT_KEYS = ("project", "project_name", "project_reference")


def pick_project(understanding, projects: list[ProjectSummary]) -> ProjectSummary | None:
    """Deterministically choose the sender's project for this message.

    Precedence: an explicit project *named in the message* that matches an
    authorized project → that project; else if the user has exactly one project
    → that one; else unresolved (``None``) — never guess between several.
    """
    if not projects:
        return None

    by_name = {p.name.strip().casefold(): p for p in projects}
    candidates = getattr(understanding, "candidates", []) or []
    for cand in candidates:
        merged = {**getattr(cand, "fields", {}), **getattr(cand, "unknown_fields", {})}
        for key in _PROJECT_KEYS:
            val = merged.get(key)
            if val and str(val).strip().casefold() in by_name:
                return by_name[str(val).strip().casefold()]

    if len(projects) == 1:
        return projects[0]
    return None


# ---------------------------------------------------------------------------
# User-facing messages
# ---------------------------------------------------------------------------

SIGNUP_URL = "https://app.whatsapp.mesiri.ai/signup"

UNREGISTERED_MESSAGE = (
    "👋 Hi! This number (+{number}) isn't registered on Mesiri yet.\n\n"
    "• Joining a company? Ask your admin for their *join code* and send it here, "
    "e.g. *JOIN ACME-4821*. Or ask them to add this number.\n"
    "• Starting for your own company? Sign up at {signup_url}"
)

NO_ORG_MESSAGE = (
    "👋 Hi {name}! You have a Mesiri account, but you're not part of any "
    "organization yet.\n\n"
    "Please ask your administrator to add you to an organization, then message again."
)

ORG_SUSPENDED_MESSAGE = (
    "⚠️ Your organization's Mesiri account is not active right now. "
    "Please contact your administrator."
)


# ---------------------------------------------------------------------------
# Reply formatters (assistant-visible data only)
# ---------------------------------------------------------------------------

_STATUS_EMOJI = {
    "on_track": "🟢",
    "at_risk": "🟡",
    "critical": "🔴",
}


def _role_label(role: str) -> str:
    return role.replace("_", " ").title() if role else "—"


def context_header(actor: ActorIdentity, project: ProjectSummary | None) -> str:
    """Short identity/context banner prepended to assistant replies."""
    line = f"👤 {actor.full_name} · 🏢 {actor.org_name}"
    if project is not None:
        line += f" · 🏗 {project.name}"
    elif len(actor.projects) > 1:
        line += " · 🏗 (project unspecified)"
    return line


def whoami_reply(actor: ActorIdentity) -> str:
    """Full whoami summary sent in response to a "who am I" / "my role" query."""
    lines: list[str] = [
        "*Mesiri — whoami*",
        "",
        f"👤 Name: {actor.full_name}",
        f"🔑 Role: {_role_label(actor.role)}",
        f"🏢 Organization: {actor.org_name}",
    ]

    if actor.projects:
        lines += ["", f"🏗 Projects ({len(actor.projects)}):"]
        for p in actor.projects:
            emoji = _STATUS_EMOJI.get((p.status or "").lower(), "▪️")
            parts: list[str] = []
            if p.location:
                parts.append(f"📍 {p.location}")
            if p.code:
                parts.append(f"🏷 {p.code}")
            if p.status:
                parts.append(f"{emoji} {p.status.replace('_', ' ')}")
            if p.progress is not None:
                parts.append(f"📈 {p.progress}%")
            if p.open_issues:
                parts.append(f"⚠️ {p.open_issues} open")
            detail = " · ".join(parts) if parts else "—"
            lines.append(f"   • {p.name} — {detail}")
    else:
        lines += [
            "",
            "🏗 Projects: none assigned to you yet — ask your administrator "
            "to give you project access.",
        ]

    if actor.sites:
        lines += ["", f"📍 Sites ({len(actor.sites)}):"]
        for s in actor.sites:
            lines.append(f"   • {s.name}")

    return "\n".join(lines)


def unregistered_message(wa_id: str) -> str:
    """The "not registered" reply with this sender's number and the real ways in."""
    return UNREGISTERED_MESSAGE.format(number=wa_id, signup_url=SIGNUP_URL)
