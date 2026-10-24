"""Where the sender is working today (WA-45).

Engineers move between projects and sites: Site A of Project A today, Site A
of Project B tomorrow. Three things keep the assistant on the right one:

- The first message of the day, from someone with two or more sites, gets one
  question, "Where are you working today?", with their sites as a list. The
  message itself waits (parked here), with any more sent before the answer,
  and they run in order as soon as they tap or type one of the site names.
- "Now at Site B" in the middle of the day switches (the agent's
  ``set_work_site`` tool).
- Every save remembers the site it went to.

Today's site is the context resolver's *active context* (Redis, revalidated
against the sender's access on every read -- context/resolver.py), so every
module's saves follow it without knowing about it: a site the message names
still wins, then today's site, then the person's default. It lasts until
midnight in the company's time zone, so tomorrow starts with the question
again rather than yesterday's site.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from channel.replies import ListRow, ReplySpec
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage

from .project_day import project_zone

_log = logging.getLogger("mesiri.agent")

#: Tap ids of the morning list: ``today_site:<site id>``.
TAP_PREFIX = "today_site:"
#: Most messages kept waiting for the answer (V1 audit SIT-02); they wait
#: until midnight (SIT-04: a 2-hour limit lost a late tap's message).
_MAX_PARKED = 10
#: The site picked last time is offered first (kept a month).
LAST_SITE_TTL_SECONDS = 30 * 24 * 60 * 60
_MAX_ROWS = 10  # WhatsApp list limit
_TITLE_MAX = 24  # WhatsApp row title limit
_DESC_MAX = 72  # WhatsApp row description limit
#: Not asked every morning: the company's admins (owners) see all its sites.
_NOT_ASKED_ROLES = frozenset({"ADMIN"})


def _now() -> datetime:
    return datetime.now(UTC)


def _cut(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def seconds_until_midnight(now: datetime, timezone: str | None) -> int:
    """Seconds left in the company's day (at least one minute)."""
    zone = project_zone(timezone)  # request 90: the project's day, never UTC's
    local = now.astimezone(zone)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((midnight - local).total_seconds()))


def _ids(actor: Any) -> tuple[str, str] | None:
    org = getattr(actor, "organization_id", None)
    user = getattr(actor, "user_id", None)
    return (str(org), str(user)) if org and user else None


def _sites(actor: Any) -> list[Any]:
    return list(getattr(actor, "sites", None) or [])


def _project_names(actor: Any) -> dict[str, str]:
    return {str(p.id): p.name for p in (getattr(actor, "projects", None) or [])}


def site_label(actor: Any, site_id: str | None) -> str | None:
    """"Site B (Project B)" for one of the sender's sites, else None."""
    for site in _sites(actor):
        if str(site.id) == str(site_id):
            project = _project_names(actor).get(str(site.project_id or ""))
            return f"{site.name} ({project})" if project else site.name
    return None


def names_a_site(actor: Any, text: str) -> bool:
    """Whether the message names one of the sender's sites ("cement at site B"):
    the message says where, so the morning question is not needed."""
    words = " ".join((text or "").casefold().split())
    return any(
        len(name) >= 3 and name in words
        for name in (" ".join(str(s.name).casefold().split()) for s in _sites(actor))
    )


_TYPED_PREFIXES = ("now at ", "i am at ", "i'm at ", "im at ", "at ")


def typed_site(actor: Any, text: str) -> Any | None:
    """V1 audit SIT-03: the one site a message that is only a site name
    ("Site B", "at site b") names, or None (not only a name, or a name two
    of their sites share)."""
    words = " ".join((text or "").casefold().split()).rstrip(".!")
    for prefix in _TYPED_PREFIXES:
        if words.startswith(prefix):
            words = words[len(prefix):]
            break
    hits = [s for s in _sites(actor) if " ".join(str(s.name).casefold().split()) == words]
    return hits[0] if len(hits) == 1 else None


def created_site(handled: Any) -> tuple[str | None, str] | None:
    """``(project_id, new site id)`` when ``handled`` is a confirmed, saved
    CREATE_SITE (the execution's ``material_row_id`` is the new row's id, as
    inbound_journey/seeding.py reads it for the setup offers)."""
    from mesiri_contracts.application.results.execution_result import ExecutionStatus
    from mesiri_contracts.assistant.draft_action import DraftActionType

    confirmed = getattr(getattr(handled, "result", None), "confirmed_action", None)
    execution = getattr(handled, "execution_result", None)
    if confirmed is None or execution is None or execution.status is not ExecutionStatus.SUCCEEDED:
        return None
    draft = confirmed.draft_action
    if draft.action_type is not DraftActionType.CREATE_SITE or not execution.material_row_id:
        return None
    return (str(draft.project_id) if draft.project_id else None), str(execution.material_row_id)


class WorkSite:
    """Today's project/site per sender, and the morning question."""

    def __init__(
        self,
        *,
        active_context: Any,
        redis: Any,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._active = active_context
        self._redis = redis
        self._clock = clock

    @staticmethod
    def _key(org: str, user: str, what: str) -> str:
        return f"{org}:user:{user}:work_site:{what}"

    async def today(self, actor: Any) -> tuple[str | None, str] | None:
        """``(project_id, site_id)`` the sender is working at today, if set and
        still one of their sites."""
        ids = _ids(actor)
        if ids is None:
            return None
        active = await self._active.get_active_context(organization_id=ids[0], user_id=ids[1])
        if active is None or not active.site_id:
            return None
        if not any(str(s.id) == str(active.site_id) for s in _sites(actor)):
            return None
        return active.project_id, str(active.site_id)

    async def set_today(self, actor: Any, *, project_id: str | None, site_id: str) -> None:
        """This is where they work for the rest of today. Never raises."""
        ids = _ids(actor)
        if ids is None or not site_id:
            return
        if project_id is None:
            project_id = next(
                (str(s.project_id) for s in _sites(actor) if str(s.id) == str(site_id) and s.project_id),
                None,
            )
        try:
            await self._active.set_active_context(
                organization_id=ids[0],
                user_id=ids[1],
                project_id=project_id,
                site_id=site_id,
                ttl_seconds=seconds_until_midnight(self._clock(), getattr(actor, "timezone", None)),
            )
            await self._redis.set_json(
                self._key(*ids, "last"), {"site_id": site_id}, ttl_seconds=LAST_SITE_TTL_SECONDS
            )
        except Exception:  # noqa: BLE001 -- a missed hint only costs one question
            _log.warning("work_site.set_failed user=%s", ids[1], exc_info=True)

    async def morning_question(self, message: NormalizedMessage, actor: Any) -> ReplySpec | None:
        """The question to send instead of handling ``message`` now, or None to
        go on. Asked only of someone with 2+ sites who has no site for today and
        did not name one; the message waits for their tap."""
        sites = _sites(actor)
        ids = _ids(actor)
        if ids is None or len(sites) < 2:
            return None
        if str(getattr(actor, "role", "") or "").upper() in _NOT_ASKED_ROLES:
            # Owners see every site and are rarely at one; they can still say
            # "now at Site B" (set_work_site).
            return None
        if message.modality not in (InputModality.TEXT, InputModality.VOICE):
            return None
        if message.modality is InputModality.TEXT and names_a_site(actor, message.text or ""):
            return None
        try:
            if await self.today(actor) is not None:
                return None
            last = await self._redis.get_json(self._key(*ids, "last"))
            waiting = await self._parked(ids)
            # SIT-02: a second message before the answer waits too, after the first.
            await self._redis.set_json(
                self._key(*ids, "parked"),
                {"messages": [*waiting, message.model_dump(mode="json")][-_MAX_PARKED:]},
                ttl_seconds=seconds_until_midnight(self._clock(), getattr(actor, "timezone", None)),
            )
        except Exception:  # noqa: BLE001 -- never block a message on the hint store
            _log.warning("work_site.morning_check_failed user=%s", ids[1], exc_info=True)
            return None
        last_id = str((last or {}).get("site_id") or "")
        ordered = sorted(sites, key=lambda s: (str(s.id) != last_id, str(s.name).casefold()))
        projects = _project_names(actor)
        rows = tuple(
            ListRow(
                f"{TAP_PREFIX}{s.id}",
                _cut(s.name, _TITLE_MAX),
                _cut(
                    ("Last time · " if str(s.id) == last_id else "") + projects.get(str(s.project_id or ""), ""),
                    _DESC_MAX,
                ),
            )
            for s in ordered[:_MAX_ROWS]
        )
        first = (getattr(actor, "full_name", "") or "").split(" ")[0]
        hello = f"Good morning{', ' + first if first else ''}! 👷"
        if waiting:
            hello = "Got it, that waits too until you pick the site."
        more = "" if len(sites) <= _MAX_ROWS else "\n\nNot in the list? Type the site name."
        return ReplySpec(
            text=f"{hello}\nWhere are you working today?{more}",
            list_button_label="Choose site",
            list_rows=rows,
        )

    async def _parked(self, ids: tuple[str, str]) -> list[dict[str, Any]]:
        raw = await self._redis.get_json(self._key(*ids, "parked"))
        if not raw:
            return []
        if isinstance(raw, dict) and "messages" in raw:
            return list(raw["messages"] or [])
        return [raw]  # one message, as parked before SIT-02

    async def handle_tap(
        self, message: NormalizedMessage, actor: Any
    ) -> tuple[ReplySpec, list[NormalizedMessage]] | None:
        """A tap on the morning list: ``(confirmation, the parked messages to
        run now, oldest first)``, or None when it is not that tap."""
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if not tap.startswith(TAP_PREFIX):
            return None
        return await self._answer(actor, tap[len(TAP_PREFIX):])

    async def handle_typed(
        self, message: NormalizedMessage, actor: Any
    ) -> tuple[ReplySpec, list[NormalizedMessage]] | None:
        """V1 audit SIT-03: a typed site name answers the morning question
        like a tap, when messages are waiting for it; None otherwise."""
        ids = _ids(actor)
        if ids is None or message.modality is not InputModality.TEXT:
            return None
        site = typed_site(actor, message.text or "")
        if site is None:
            return None
        try:
            if not await self._parked(ids):
                return None
        except Exception:  # noqa: BLE001 -- the message goes on as usual
            _log.warning("work_site.parked_check_failed user=%s", ids[1], exc_info=True)
            return None
        return await self._answer(actor, str(site.id))

    async def _answer(self, actor: Any, site_id: str) -> tuple[ReplySpec, list[NormalizedMessage]]:
        label = site_label(actor, site_id)
        if label is None:
            return ReplySpec(text="That site isn't one of yours any more. Tell me where you are working today."), []
        await self.set_today(actor, project_id=None, site_id=site_id)
        parked: list[NormalizedMessage] = []
        ids = _ids(actor)
        if ids is not None:
            try:
                waiting = await self._parked(ids)
                # delete() takes the raw key; the *_json calls namespace it.
                await self._redis.delete(self._redis.namespaced(self._key(*ids, "parked")))
                parked = [NormalizedMessage.model_validate(raw) for raw in waiting]
            except Exception:  # noqa: BLE001 -- the switch itself still worked
                _log.warning("work_site.parked_read_failed user=%s", ids[1], exc_info=True)
        line = f"👍 {label} for today. Moving to another site? Just tell me, like \"now at Site A\"."
        return ReplySpec(text=line), parked
