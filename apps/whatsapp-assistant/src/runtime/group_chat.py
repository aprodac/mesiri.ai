"""Mesiri inside a site's WhatsApp group (WA-87).

Plan: docs/execution/WHATSAPP_GROUPS_PLAN.md. Everything here is off unless
``WHATSAPP_GROUPS_ENABLED`` is set; with it off, ingress drops group messages
before they are claimed (ingress/receiver.py) and nothing below runs.

What it does:

- **Creates a group** for one site (``create_for_site``): from the dashboard
  button, or a company admin / super admin writing "make a group for <site>"
  to Mesiri 1-on-1 (``handle_private``). Meta answers later with the group id
  and invite link (``handle_event``); then Mesiri posts a welcome line in the
  group, sends the link to everyone on the site team, and sends the creator a
  link to forward to the client.
- **Lets people in.** Everyone joins by the invite link with approval required:
  a site team member is approved at once; anyone else waits for an admin's
  Allow / Don't allow tap.
- **Reads the group** (``wrap``): a message from someone on the site's team is
  handled exactly like their 1-on-1 message, with the group's site preselected.
  Anyone else (the client, our own team) is ignored: nothing saved, no reply.
- **Stays quiet in the group** (``GroupReplySender``): the only things posted
  in the group are the ✅ on a saved message, the welcome line and the evening
  DPR (runtime/project_auto_dpr.py). Every reply, card and question goes to the
  sender 1-on-1, so money, wages and anything else private never reach the
  client. If Meta refuses the private reply (no open chat with that person),
  one line in the group asks them to say hi to Mesiri.

Meta's group webhook payloads are parsed defensively (``parse_group_events``):
the field names come from Meta's documentation and are confirmed by the WA-87
spike; anything unrecognised is logged with its payload and ignored.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from channel.whatsapp.outbound import group_target

_log = logging.getLogger("mesiri.group_chat")

def groups_switched_on() -> bool:
    """``WHATSAPP_GROUPS_ENABLED``, for code that runs without the app's
    Settings (the DPR scheduler: runtime/project_auto_dpr.py)."""
    import os

    return os.environ.get("WHATSAPP_GROUPS_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


#: Meta's "This phone number is not eligible to access Groups APIs" (first live
#: try, 29 Oct): the number needs the Official Business Account badge.
NOT_ELIGIBLE_CODE = 131215

ALLOW_PREFIX = "wagroup:allow:"
DENY_PREFIX = "wagroup:deny:"

#: The group sees this on a team member's message at once; ✅ replaces it once saved.
SEEN = "👍"
WELCOME = "Send the day's work, photos and workers here. I'll save them to {site}."
PRIVATE_NUDGE = (
    "{name}, I couldn't reach you in our own chat. Send me a 'hi' there once, "
    "and I'll send you my replies."
)
INVITE_TEXT = (
    "Hi {name}, {company} has a WhatsApp group with Mesiri for {site}. Send the day's work, "
    "photos and workers there and Mesiri saves them to the site. Join: {link}"
)
CREATOR_TEXT = (
    "The {site} WhatsApp group is ready. I've sent the invite to the site team.\n\n"
    "Forward this link to the client and anyone else who should be in it:\n{link}\n\n"
    "I'll ask you before letting in anyone who isn't on the site team."
)
JOIN_ASK_TEXT = "+{number} wants to join the {site} WhatsApp group. They aren't on the site team."
GROUP_LIMIT_NOTE = "WhatsApp allows about 8 people in a business group, Mesiri included."

_CREATE_COMMAND = re.compile(
    r"^\s*(?:please\s+)?(?:make|create|start|open|set\s*up)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:whatsapp\s+)?group\s+(?:for|at|on)\s+(?P<target>.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Meta's group webhooks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GroupEvent:
    #: created | create_failed | deleted | join_request | other
    kind: str
    group_id: str | None = None
    request_id: str | None = None
    invite_link: str | None = None
    join_request_id: str | None = None
    wa_id: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


def _first(item: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _items(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    groups = value.get("groups")
    if isinstance(groups, list):
        return [g for g in groups if isinstance(g, Mapping)]
    return [value]


def _requests(item: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("join_requests", "requests", "participants"):
        entries = item.get(key)
        if isinstance(entries, list):
            return [e for e in entries if isinstance(e, Mapping)]
    return [item]


def parse_group_events(field_name: str, value: Mapping[str, Any]) -> list[GroupEvent]:
    """The events in one ``group_*`` webhook change."""
    events: list[GroupEvent] = []
    for item in _items(value or {}):
        kind_text = str(item.get("type") or item.get("event") or "").lower()
        group_id = _first(item, "group_id", "id")
        request_id = _first(item, "request_id")
        if field_name == "group_lifecycle_update":
            if "delete" in kind_text or "leave" in kind_text:
                kind = "deleted"
            elif item.get("errors") or "fail" in kind_text:
                kind = "create_failed"
            elif "create" in kind_text or item.get("invite_link"):
                kind = "created"
            else:
                kind = "other"
            events.append(
                GroupEvent(
                    kind=kind,
                    group_id=group_id,
                    request_id=request_id,
                    invite_link=_first(item, "invite_link"),
                    raw=item,
                )
            )
        elif field_name == "group_participants_update" and "join_request" in kind_text and not any(
            word in kind_text for word in ("revok", "cancel", "withdr")
        ):
            for entry in _requests(item):
                events.append(
                    GroupEvent(
                        kind="join_request",
                        group_id=group_id or _first(entry, "group_id"),
                        join_request_id=_first(entry, "join_request_id", "request_id", "id"),
                        wa_id=_first(entry, "wa_id", "from", "user", "requester"),
                        raw=item,
                    )
                )
        else:
            events.append(GroupEvent(kind="other", group_id=group_id, raw=item))
    return events


# ---------------------------------------------------------------------------
# Replies during a group message
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GroupTurn:
    group_wa_id: str
    sender_wa_id: str
    message_id: str
    first_name: str
    nudged: bool = False


_turn: contextvars.ContextVar[GroupTurn | None] = contextvars.ContextVar("wa87_group_turn", default=None)


def current_turn() -> GroupTurn | None:
    return _turn.get()


class GroupReplySender:
    """The journey's sender while a group message is handled: the ✅ on the
    group message goes into the group; every other send goes to the person,
    as for a 1-on-1 message. A private send Meta refuses brings one nudge in
    the group. Outside a group message it changes nothing."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def send_reaction(self, to_wa_id: str, message_id: str, emoji: str = "✅") -> bool:
        turn = _turn.get()
        if turn is not None and message_id == turn.message_id:
            return await self._inner.send_reaction(group_target(turn.group_wa_id), message_id, emoji)
        return await self._inner.send_reaction(to_wa_id, message_id, emoji)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not name.startswith("send_") or not callable(attr):
            return attr

        async def _sent_or_nudge(to_wa_id: Any, *args: Any, **kwargs: Any) -> Any:
            result = await attr(to_wa_id, *args, **kwargs)
            turn = _turn.get()
            if turn is not None and not result and to_wa_id == turn.sender_wa_id and not turn.nudged:
                turn.nudged = True
                try:
                    await self._inner.send_text(
                        group_target(turn.group_wa_id), PRIVATE_NUDGE.format(name=turn.first_name)
                    )
                except Exception:  # noqa: BLE001 -- best effort
                    _log.warning("group.nudge_failed group=%s", turn.group_wa_id, exc_info=True)
            return result

        return _sent_or_nudge


# ---------------------------------------------------------------------------
# The group service
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").lower()).split())


def _match(name: str, options: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    """Exact (normalised) name first, else options whose name is in the text
    or the text is in their name."""
    wanted = _norm(name)
    if not wanted:
        return []
    exact = [o for o in options if _norm(o[key]) == wanted]
    if exact:
        return exact
    return [o for o in options if _norm(o[key]) and (_norm(o[key]) in wanted or wanted in _norm(o[key]))]


def _first_name(name: str | None) -> str:
    return (str(name or "").split() or ["there"])[0]


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _is_admin(actor: Any, organization_id: str) -> bool:
    return (
        actor is not None
        and str(getattr(actor, "organization_id", "") or "") == str(organization_id)
        and str(getattr(actor, "role", "") or "").upper() == "ADMIN"
    )


def _on_site_team(actor: Any, group: Mapping[str, Any]) -> bool:
    """The actor belongs to the group's company and reaches its site (the
    actor's sites already follow the company's access rules: actor.py)."""
    if actor is None or not getattr(actor, "org_active", True):
        return False
    if str(getattr(actor, "organization_id", "") or "") != str(group["organization_id"]):
        return False
    return any(str(s.id) == str(group["site_id"]) for s in (getattr(actor, "sites", None) or []))


@dataclass(frozen=True, slots=True)
class CreateResult:
    #: creating | exists | failed | not_eligible | disabled
    status: str
    group: Mapping[str, Any] | None = None


class GroupChat:
    def __init__(
        self,
        *,
        groups: Any,
        client: Any,
        sender: Any,
        actor_reader: Any,
        outbox: Any,
        work_site: Any | None = None,
        enabled: bool = False,
        lookup_retry_seconds: float = 2.0,
    ) -> None:
        self._groups = groups
        self._client = client
        self._sender = sender
        self._actor_reader = actor_reader
        self._outbox = outbox
        self._work_site = work_site
        self.enabled = enabled
        self._retry_seconds = lookup_retry_seconds

    # -- creating a group --------------------------------------------------------

    async def site_group(self, *, organization_id: str, site_id: str) -> dict[str, Any] | None:
        """The site's group being made or in use; None when it has none (a
        failed try counts as none: the dashboard offers to make one)."""
        return await self._groups.live_for_site(organization_id=organization_id, site_id=site_id)

    async def create_for_site(
        self,
        *,
        organization_id: str,
        org_name: str,
        project_id: str | None,
        site_id: str,
        site_name: str,
        created_by_user_id: str | None,
    ) -> CreateResult:
        if not self.enabled:
            return CreateResult("disabled")
        subject = f"{site_name} · Mesiri"
        row = await self._groups.start(
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            subject=subject,
            created_by_user_id=created_by_user_id,
        )
        if row is None:
            return CreateResult(
                "exists", await self._groups.live_for_site(organization_id=organization_id, site_id=site_id)
            )
        answer = await self._client.create_group(
            subject,
            description=(
                f"{org_name}: site updates for {site_name}. Send the day's work, photos and workers "
                "here; Mesiri saves them to the site."
            ),
        )
        refused = (answer or {}).get("refused") if isinstance(answer, dict) else None
        if refused is not None:
            await self._groups.update(row["id"], status="failed")
            if refused.get("code") == NOT_ELIGIBLE_CODE:
                return CreateResult("not_eligible", row)
            return CreateResult("failed", row)
        if answer is None:
            await self._groups.update(row["id"], status="failed")
            return CreateResult("failed", row)
        request_id = _first(answer, "request_id")
        group_id = _first(answer, "group_id")
        if request_id or group_id:
            await self._groups.update(row["id"], create_request_id=request_id, wa_group_id=group_id)
        _log.info("group.create_requested group=%s site=%s request=%s", row["id"], site_id, request_id)
        if group_id:
            # Meta named the group straight away: no need to wait for the webhook.
            await self._activate(
                {**row, "wa_group_id": group_id}, invite_link=_first(answer, "invite_link")
            )
        return CreateResult("creating", row)

    # -- Meta's webhooks ---------------------------------------------------------

    async def handle_event(self, field_name: str, value: Mapping[str, Any]) -> None:
        """One ``group_*`` webhook change. Never raises."""
        for event in parse_group_events(field_name, value):
            try:
                await self._handle_one(event)
            except Exception:  # noqa: BLE001 -- one bad event never stops the rest
                _log.exception("group.event_failed kind=%s group=%s", event.kind, event.group_id)

    async def _handle_one(self, event: GroupEvent) -> None:
        if event.kind == "other":
            _log.info("group.event_ignored raw=%s", str(dict(event.raw))[:500])
            return
        row = await self._row_for(event)
        if row is None:
            _log.info("group.event_unknown_group kind=%s group=%s request=%s", event.kind, event.group_id, event.request_id)
            return
        if event.kind == "created":
            await self._activate({**row, "wa_group_id": event.group_id or row.get("wa_group_id")}, invite_link=event.invite_link)
        elif event.kind == "create_failed":
            await self._groups.update(row["id"], status="failed")
            _log.warning("group.create_failed group=%s raw=%s", row["id"], str(dict(event.raw))[:500])
        elif event.kind == "deleted":
            await self._groups.update(row["id"], status="closed")
        elif event.kind == "join_request":
            await self._join_request(row, event)

    async def _row_for(self, event: GroupEvent) -> dict[str, Any] | None:
        row = await self._lookup(event)
        if row is None and event.kind == "created":
            # Meta's "created" can arrive before create_for_site has stored the
            # request id from Meta's answer: look again shortly, then by name.
            for _ in range(3):
                await asyncio.sleep(self._retry_seconds)
                row = await self._lookup(event)
                if row is not None:
                    break
            subject = _first(event.raw, "subject")
            if row is None and subject:
                row = await self._groups.creating_by_subject(subject)
        return row

    async def _lookup(self, event: GroupEvent) -> dict[str, Any] | None:
        if event.group_id:
            row = await self._groups.by_wa_group_id(event.group_id)
            if row is not None:
                return row
        if event.request_id:
            return await self._groups.by_request_id(event.request_id)
        return None

    async def _activate(self, row: Mapping[str, Any], *, invite_link: str | None) -> None:
        group_id = row.get("wa_group_id")
        if not group_id:
            return
        was_active = row.get("status") == "active" and row.get("invite_link")
        link = invite_link or row.get("invite_link") or await self._client.invite_link(group_id)
        await self._groups.update(row["id"], wa_group_id=group_id, invite_link=link, status="active")
        if was_active:
            return  # the same webhook again: everything below was done once
        _log.info("group.active group=%s wa_group=%s", row["id"], group_id)
        site = row.get("site_name") or "this site"
        await self._sender.send_text(group_target(group_id), WELCOME.format(site=site))
        if not link:
            _log.warning("group.no_invite_link group=%s", row["id"])
            return
        team = await self._groups.site_team(organization_id=row["organization_id"], site_id=row["site_id"])
        messages = [
            {
                "user_id": person["user_id"],
                "subject": f"invite:{person['user_id']}",
                "message": INVITE_TEXT.format(
                    name=_first_name(person["name"]), company=row.get("org_name") or "Your company", site=site, link=link
                ),
                "template": {
                    "name": "mesiri_group_invite",
                    "body_params": [_first_name(person["name"]), row.get("org_name") or "Your company", site, link],
                },
            }
            for person in team
            if person["user_id"] != row.get("created_by_user_id")
        ]
        if row.get("created_by_user_id"):
            messages.append(
                {
                    "user_id": row["created_by_user_id"],
                    "subject": "creator",
                    "message": f"{CREATOR_TEXT.format(site=site, link=link)}\n\n{GROUP_LIMIT_NOTE}",
                }
            )
        await self._outbox.send(row, kind="group_invite", messages=messages)

    async def _join_request(self, row: Mapping[str, Any], event: GroupEvent) -> None:
        if not event.join_request_id or not event.wa_id or not row.get("wa_group_id"):
            _log.info("group.join_request_incomplete raw=%s", str(dict(event.raw))[:500])
            return
        actor = await self._actor_reader.resolve_by_whatsapp_id(event.wa_id)
        if _on_site_team(actor, row):
            if await self._client.approve_join_requests(row["wa_group_id"], [event.join_request_id]):
                await self._groups.record_join_request(
                    group=row, join_request_id=event.join_request_id, wa_id=event.wa_id, status="approved"
                )
            return
        stored = await self._groups.record_join_request(
            group=row, join_request_id=event.join_request_id, wa_id=event.wa_id, status="pending"
        )
        if stored is None:
            return  # asked already
        await self._outbox.send(
            row,
            kind="group_join",
            messages=[
                {
                    "user_id": person["user_id"],
                    "subject": f"{stored['id']}:{person['user_id']}",
                    "message": JOIN_ASK_TEXT.format(number=_digits(event.wa_id), site=row.get("site_name") or "site"),
                    "buttons": [
                        {"id": f"{ALLOW_PREFIX}{stored['id']}", "title": "Allow"},
                        {"id": f"{DENY_PREFIX}{stored['id']}", "title": "Don't allow"},
                    ],
                }
                for person in await self._approvers(row)
            ],
        )

    async def _approvers(self, row: Mapping[str, Any]) -> list[dict[str, str]]:
        """The group's creator, else the company's admins on the site team."""
        team = await self._groups.site_team(organization_id=row["organization_id"], site_id=row["site_id"])
        creator = row.get("created_by_user_id")
        if creator and any(p["user_id"] == creator for p in team):
            return [p for p in team if p["user_id"] == creator]
        if creator:
            return [{"user_id": creator, "name": "", "wa_id": "", "role": "ADMIN"}]
        return [p for p in team if p.get("role") == "ADMIN"]

    # -- a 1-on-1 message: the create command and the Allow taps -----------------

    async def handle_private(self, message: Any, actor: Any) -> str | None:
        """The reply to "make a group for <site>" or an Allow / Don't allow tap;
        None for any other message (the journey carries on as usual)."""
        if not self.enabled or (message.metadata or {}).get("group_id"):
            return None
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if tap.startswith((ALLOW_PREFIX, DENY_PREFIX)):
            return await self._decide(tap, actor, message.sender.wa_id)
        match = _CREATE_COMMAND.match(message.text or "")
        if match is None:
            return None
        return await self._create_command(match.group("target"), actor, message.sender.wa_id)

    async def _create_command(self, target: str, actor: Any, wa_id: str) -> str | None:
        if actor is not None and getattr(actor, "organization_id", None):
            if str(getattr(actor, "role", "") or "").upper() != "ADMIN":
                return "Only the company owner or an admin can make a site's WhatsApp group. Ask them to send me \"make a group for <site>\"."
            return await self._create_named(
                organization_id=str(actor.organization_id),
                org_name=getattr(actor, "org_name", None) or "",
                site_text=target,
                created_by_user_id=str(actor.user_id),
            )
        admin = await self._groups.is_super_admin(wa_id)
        if admin is None:
            return None  # not one of ours: the usual reply for an unknown sender
        companies = await self._groups.companies()
        company_text, comma, site_text = target.partition(",")
        if comma:
            found = _match(company_text, companies, "name")
        else:
            # "Acme Kakkanad site": the company whose name the text starts with
            # (the longest such name), the rest is the site.
            wanted = _norm(target)
            found = sorted(
                (c for c in companies if _norm(c["name"]) and wanted.startswith(_norm(c["name"]))),
                key=lambda c: -len(_norm(c["name"])),
            )[:1]
            if found:
                site_text = wanted[len(_norm(found[0]["name"])):]
            else:
                found = _match(target, companies, "name")
        if len(found) != 1:
            names = ", ".join(sorted(c["name"] for c in found)[:5])
            return (
                f"Which company? {names}" if found else "I couldn't find that company."
            ) + "\nSend it as: make a group for <company>, <site>"
        company = found[0]
        from mesiri.infrastructure.postgres.tenant import tenant_scope

        with tenant_scope(company["organization_id"]):
            return await self._create_named(
                organization_id=company["organization_id"],
                org_name=company["name"],
                site_text=site_text,
                created_by_user_id=admin["user_id"],
            )

    async def _create_named(
        self, *, organization_id: str, org_name: str, site_text: str, created_by_user_id: str
    ) -> str:
        sites = await self._groups.company_sites(organization_id=organization_id)
        found = _match(site_text, sites, "site_name") if site_text.strip() else (sites if len(sites) == 1 else [])
        if not found and site_text.strip():
            # "make a group for hospital project": a project's name. Its only
            # site, or the question which of its sites.
            words = " ".join(w for w in _norm(site_text).split() if w not in {"project", "site"})
            projects = {s["project_id"] for s in _match(words or site_text, sites, "project_name")}
            found = [s for s in sites if s["project_id"] in projects]
            if len(found) > 1:
                names = ", ".join(s["site_name"] for s in found[:8])
                return f"Which site of {found[0]['project_name']}? {names}\nSend: make a group for <site>"
        if len(found) != 1:
            names = ", ".join(s["site_name"] for s in (found or sites)[:8])
            lead = "Which site?" if found or not site_text.strip() else "I couldn't find that site."
            return f"{lead} {org_name}'s sites: {names}\nSend: make a group for <site>"
        site = found[0]
        result = await self.create_for_site(
            organization_id=organization_id,
            org_name=org_name,
            project_id=site["project_id"] or None,
            site_id=site["site_id"],
            site_name=site["site_name"],
            created_by_user_id=created_by_user_id,
        )
        return create_reply(result, site["site_name"])

    async def _decide(self, tap: str, actor: Any, wa_id: str) -> str:
        allow = tap.startswith(ALLOW_PREFIX)
        request_row_id = tap[len(ALLOW_PREFIX if allow else DENY_PREFIX):]
        request = await self._groups.join_request(request_row_id)
        group = await self._groups.by_id(request["group_id"]) if request else None
        if request is None or group is None:
            return "That request isn't there any more."
        admin = None if _is_admin(actor, group["organization_id"]) else await self._groups.is_super_admin(wa_id)
        if not _is_admin(actor, group["organization_id"]) and admin is None:
            return "Only the company owner or an admin can let people into the group."
        if request["status"] != "pending":
            return "That's been answered already."
        decider = str(actor.user_id) if admin is None else admin["user_id"]
        number = _digits(request["wa_id"])
        if allow:
            if not await self._client.approve_join_requests(group["wa_group_id"], [request["join_request_id"]]):
                return f"I couldn't let +{number} in. The group may be full: {GROUP_LIMIT_NOTE}"
            await self._groups.decide_join_request(request_row_id, status="approved", user_id=decider)
            return f"Done: +{number} can join the {group['site_name']} group now."
        await self._client.reject_join_requests(group["wa_group_id"], [request["join_request_id"]])
        await self._groups.decide_join_request(request_row_id, status="rejected", user_id=decider)
        return f"Okay, +{number} won't be let into the group."

    # -- a group message ---------------------------------------------------------

    def wrap(self, on_normalized: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
        """``on_normalized`` for every message; a group message is only
        passed on for someone on the site's team, with the site preselected
        and ``GroupReplySender`` routing the ✅ into the group."""

        async def _on_normalized(message: Any, raw_payload: Any, retry_of_id: Any = None) -> None:
            group_wa_id = (message.metadata or {}).get("group_id")
            if not group_wa_id:
                await on_normalized(message, raw_payload, retry_of_id)
                return
            group = await self._groups.by_wa_group_id(str(group_wa_id))
            if group is None or group.get("status") != "active":
                _log.info("group.message_unknown_group group=%s", group_wa_id)
                return
            actor = await self._actor_reader.resolve_by_whatsapp_id(message.sender.wa_id)
            if not _on_site_team(actor, group):
                # The client, our own team, anyone not on this site: never saved,
                # never answered.
                _log.info("group.message_outsider group=%s", group["id"])
                return
            if self._work_site is not None:
                await self._work_site.preselect(actor, project_id=group.get("project_id"), site_id=group["site_id"])
            # "Got it" in the group at once; the ✅ replaces it when the update
            # is saved (a draft waits for the sender's Save tap, 1-on-1).
            try:
                await self._sender.send_reaction(group_target(str(group_wa_id)), message.message_id, SEEN)
            except Exception:  # noqa: BLE001 -- best effort
                _log.warning("group.seen_reaction_failed group=%s", group["id"], exc_info=True)
            token = _turn.set(
                GroupTurn(
                    group_wa_id=str(group_wa_id),
                    sender_wa_id=message.sender.wa_id,
                    message_id=message.message_id,
                    first_name=_first_name(getattr(actor, "full_name", None)),
                )
            )
            try:
                await on_normalized(message, raw_payload, retry_of_id)
            finally:
                _turn.reset(token)

        return _on_normalized


def create_reply(result: CreateResult, site_name: str) -> str:
    if result.status == "creating":
        return (
            f"Making the WhatsApp group for {site_name}. In a minute I'll send the invite to the "
            f"site team, and you a link to forward to the client. {GROUP_LIMIT_NOTE}"
        )
    if result.status == "exists":
        link = (result.group or {}).get("invite_link")
        return f"{site_name} has a WhatsApp group already." + (f" Invite link: {link}" if link else "")
    if result.status == "disabled":
        return "WhatsApp groups aren't switched on yet."
    if result.status == "not_eligible":
        return (
            "WhatsApp hasn't opened groups to Mesiri's number yet (it needs WhatsApp's "
            "Official Business Account badge). Nothing to do on your side: the Mesiri team is on it."
        )
    return f"WhatsApp didn't let me make the group for {site_name}. Please try again in a while."


# ---------------------------------------------------------------------------
# Sending through the notification queue
# ---------------------------------------------------------------------------


class NotificationOutbox:
    """Messages to people about a group, as notification rows sent at once by
    the queue's own rules (24 h window, templates, opt-outs): the same path as
    runtime/agent/actions.py's ``deliver``."""

    def __init__(
        self,
        *,
        db: Any,
        actor_reader: Any,
        sender: Any,
        approved_templates: frozenset[str] = frozenset(),
    ) -> None:
        self._db = db
        self._actor_reader = actor_reader
        self._sender = sender
        self._approved = approved_templates

    async def send(self, group: Mapping[str, Any], *, kind: str, messages: list[dict[str, Any]]) -> dict[str, str]:
        from mesiri.infrastructure.postgres.repositories.notifications import (
            PostgresNotificationRepository,
        )
        from mesiri.infrastructure.postgres.tenant import tenant_scope
        from runtime.send_pending_notifications import drain_and_send

        if not messages:
            return {}
        ids: set[str] = set()
        with tenant_scope(group["organization_id"]):
            async with self._db.transaction() as conn:
                repo = PostgresNotificationRepository(conn)
                for item in messages:
                    payload: dict[str, Any] = {"message": item["message"]}
                    for key in ("template", "buttons"):
                        if item.get(key):
                            payload[key] = item[key]
                    notification_id = await repo.claim(
                        organization_id=uuid.UUID(str(group["organization_id"])),
                        rule_key=f"{kind}:{group['id']}",
                        subject_id=str(item["subject"]),
                        occurred_on=datetime.now(UTC).date(),
                        recipient_user_id=uuid.UUID(str(item["user_id"])),
                        project_id=uuid.UUID(str(group["project_id"])) if group.get("project_id") else None,
                        site_id=uuid.UUID(str(group["site_id"])),
                        payload=payload,
                    )
                    if notification_id is not None:
                        ids.add(str(notification_id))
            outcomes: dict[str, str] = {}
            if ids:
                await drain_and_send(
                    db=self._db,
                    actor_reader=self._actor_reader,
                    sender=self._sender,
                    approved_templates=self._approved,
                    only_ids=frozenset(ids),
                    outcomes=outcomes,
                )
        _log.info("group.outbox kind=%s group=%s outcomes=%s", kind, group["id"], outcomes)
        return outcomes
