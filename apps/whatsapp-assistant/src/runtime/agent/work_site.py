"""Where the sender is working today (WA-45).

Engineers move between projects and sites: Site A of Project A today, Site A
of Project B tomorrow. Three things keep the assistant on the right one:

- The first message of the day, from someone with two or more sites, gets one
  question, "Where are you working today?", with their sites as a list. The
  message waits (parked here) and runs as soon as they answer. Every message
  sent while the question is open waits too, in order, and all of them run
  at the site they pick -- by tap, by typing its name, or by a late tap.
  Nothing is dropped silently: a message that outlives its day is named in
  the next reply (V1 audit, SIT-02/03/04).
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

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from channel.replies import ListRow, ReplySpec
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage

from . import site_match
from .project_day import project_now, project_zone

_log = logging.getLogger("mesiri.agent")

#: Tap ids of the morning list: ``today_site:<site id>``.
TAP_PREFIX = "today_site:"
#: The waiting messages are kept for the day (a late tap still runs them) and a
#: little more, so the day after can say they were not saved (SIT-04).
PARK_TTL_SECONDS = 2 * 24 * 60 * 60
#: A second tap on the same list, just after it ran, has nothing left to run.
RELEASED_TTL_SECONDS = 10 * 60
#: Most waiting messages held per sender; the (N+1)th is told to wait.
MAX_WAITING = 20
#: The site picked last time is offered first (kept a month).
LAST_SITE_TTL_SECONDS = 30 * 24 * 60 * 60
_TITLE_MAX = 24  # WhatsApp row title limit
_DESC_MAX = 72  # WhatsApp row description limit
#: Not asked every morning (SIT-14): owners/admins see all the company's sites,
#: and a PM or finance user is asked "which site?" only when a site entry needs
#: one (entry_base.settle), not on every first message of the day.
_NOT_ASKED_ROLES = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER", "FINANCE"})


def _now() -> datetime:
    return datetime.now(UTC)


def _cut(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


#: A night shift runs past midnight: today's site is kept until this hour of
#: the next morning, so "night shift done, 4 masons" at 00:30 is not asked
#: again (SIT-15). The morning list returns after it.
NIGHT_GRACE_HOURS = 4


def seconds_until_midnight(now: datetime, timezone: str | None, *, grace_hours: int = 0) -> int:
    """Seconds left in the company's day (at least one minute), plus
    ``grace_hours`` of the next one."""
    zone = project_zone(timezone)  # request 90: the project's day, never UTC's
    local = now.astimezone(zone)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((midnight - local).total_seconds()) + grace_hours * 3600)


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
    the message says where, so the morning question is not needed. Whole words
    only (SIT-13: "main" is not in "maintenance")."""
    return site_match.names_a_site(_sites(actor), text)


def short_site_label(actor: Any, site_id: str | None) -> str | None:
    """The site's name for a card line (SIT-11): "Green Villa", or "Site A ·
    Project B" when two of the sender's sites share the name."""
    sites = _sites(actor)
    for site, label in site_match.labelled(sites, _project_names(actor)):
        if str(site.id) == str(site_id):
            return label
    return None


# --- Words (SIT-07, SIT-08) -----------------------------------------------------

#: What the sender hears, in the language of their message. Languages without
#: wording here (and plain English) get the English line.
_WORDS: dict[str, dict[str, str]] = {
    "english": {
        "question": "Where are you working today?",
        "button": "Choose site",
        "hold": "Got it 👍 I'm holding {n} message(s) until you pick the site.",
        "set": "👍 {label} for today.",
        "tip": ' Moving to another site? Just tell me, like "now at {example}".',
        "ran": " Now saving your {n} waiting message(s).",
        "unknown": "That site isn't one of yours any more. Tell me where you are working today.",
        "nothing": " I no longer have your earlier message, so please send it again.",
        "expired": (
            "These messages from an earlier day were not saved, because no site was chosen: {items}. "
            "Please send them again."
        ),
        "more": "I'm already holding {n} messages. Please pick the site first, then send the rest.",
        "typed": "Not in the list? Type the site name.",
        "morning": "Good morning",
        "afternoon": "Good afternoon",
        "evening": "Good evening",
        "hello": "Hello",
    },
    "manglish": {
        "question": "Innu ethu site-il aanu work cheyyunnath?",
        "button": "Site select cheyyuka",
        "hold": "Sheri 👍 site select cheyyunnath vare {n} message njan pidichu vachittund.",
        "set": "👍 Innu {label}.",
        "tip": ' Vere site-il aanengil parayuka, ex: "now at {example}".',
        "ran": " Ippo ningalude {n} message save cheyyunnu.",
        "unknown": "Aa site ippo ningalude site alla. Innu evideya work cheyyunnath ennu parayuka.",
        "nothing": " Ningalude mumbathe message ente kayyil illa, onnu koodi ayakkuka.",
        "expired": "Site select cheyyaathathu kondu ee message save cheythilla: {items}. Onnu koodi ayakkuka.",
        "more": "{n} message ippo thanne pidichittund. Aadyam site select cheyyuka, ennit baakki ayakkuka.",
        "typed": "List-il illenkil site-inte peru type cheyyuka.",
        "morning": "Good morning",
        "afternoon": "Good afternoon",
        "evening": "Good evening",
        "hello": "Hello",
    },
    "malayalam": {
        "question": "ഇന്ന് ഏത് സൈറ്റിലാണ് ജോലി ചെയ്യുന്നത്?",
        "button": "സൈറ്റ് തിരഞ്ഞെടുക്കൂ",
        "hold": "ശരി 👍 സൈറ്റ് തിരഞ്ഞെടുക്കുന്നതുവരെ {n} സന്ദേശം ഞാൻ സൂക്ഷിക്കുന്നു.",
        "set": "👍 ഇന്ന് {label}.",
        "tip": ' മറ്റൊരു സൈറ്റിലേക്ക് മാറണമെങ്കിൽ പറയൂ, ഉദാ. "now at {example}".',
        "ran": " ഇപ്പോൾ നിങ്ങളുടെ {n} സന്ദേശം സേവ് ചെയ്യുന്നു.",
        "unknown": "ആ സൈറ്റ് ഇപ്പോൾ നിങ്ങളുടേതല്ല. ഇന്ന് എവിടെയാണ് ജോലി എന്ന് പറയൂ.",
        "nothing": " നിങ്ങളുടെ മുൻ സന്ദേശം എന്റെ കൈവശമില്ല, വീണ്ടും അയയ്ക്കൂ.",
        "expired": "സൈറ്റ് തിരഞ്ഞെടുക്കാത്തതിനാൽ ഈ സന്ദേശങ്ങൾ സേവ് ചെയ്തില്ല: {items}. വീണ്ടും അയയ്ക്കൂ.",
        "more": "ഇപ്പോൾ തന്നെ {n} സന്ദേശം സൂക്ഷിച്ചിട്ടുണ്ട്. ആദ്യം സൈറ്റ് തിരഞ്ഞെടുക്കൂ, ബാക്കി പിന്നെ അയയ്ക്കൂ.",
        "typed": "ലിസ്റ്റിൽ ഇല്ലെങ്കിൽ സൈറ്റിന്റെ പേര് ടൈപ്പ് ചെയ്യൂ.",
        "morning": "സുപ്രഭാതം",
        "afternoon": "നമസ്കാരം",
        "evening": "നമസ്കാരം",
        "hello": "നമസ്കാരം",
    },
    "hindi": {
        "question": "आज आप किस साइट पर काम कर रहे हैं?",
        "button": "साइट चुनें",
        "hold": "ठीक है 👍 साइट चुनने तक मैं {n} संदेश रोककर रख रहा हूँ।",
        "set": "👍 आज {label}।",
        "tip": ' दूसरी साइट पर जाना हो तो बताएँ, जैसे "now at {example}"।',
        "ran": " अब आपके {n} संदेश सेव कर रहा हूँ।",
        "unknown": "वह साइट अब आपकी नहीं है। बताएँ आज आप कहाँ काम कर रहे हैं।",
        "nothing": " आपका पिछला संदेश मेरे पास नहीं है, कृपया फिर से भेजें।",
        "expired": "साइट न चुनने के कारण ये संदेश सेव नहीं हुए: {items}. कृपया फिर से भेजें।",
        "more": "मैं पहले से {n} संदेश रोके हुए हूँ। पहले साइट चुनें, फिर बाकी भेजें।",
        "typed": "लिस्ट में नहीं है? साइट का नाम लिखें।",
        "morning": "सुप्रभात",
        "afternoon": "नमस्ते",
        "evening": "नमस्ते",
        "hello": "नमस्ते",
    },
}


def _language_of(text: str | None) -> str:
    """The wording to use for a message: its own language (prompt.reply_language,
    decided in code), English when it has no words of its own."""
    from .prompt import reply_language

    language = reply_language(text or "")
    return language if language in _WORDS else "english"


def _say(language: str, key: str, **fields: Any) -> str:
    return _WORDS.get(language, _WORDS["english"])[key].format(**fields)


def greeting(now: datetime, timezone: str | None, language: str = "english") -> str | None:
    """A greeting that fits the project's local hour, or None in the small
    hours and late night, where any greeting is wrong (SIT-07)."""
    hour = project_now(timezone, now).hour
    if 5 <= hour < 12:
        key = "morning"
    elif 12 <= hour < 17:
        key = "afternoon"
    elif 17 <= hour < 21:
        key = "evening"
    else:
        return None
    return _say(language, key)


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
        #: Messages from one sender are read and written one at a time.
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    @staticmethod
    def _key(org: str, user: str, what: str) -> str:
        return f"{org}:user:{user}:work_site:{what}"

    def _lock(self, ids: tuple[str, str]) -> asyncio.Lock:
        return self._locks.setdefault(ids, asyncio.Lock())

    def _day(self, actor: Any) -> str:
        """The project's working day (SIT-15): it turns over in the project's
        time zone, not UTC's, and after the night-shift grace."""
        local = project_now(getattr(actor, "timezone", None), self._clock())
        return (local - timedelta(hours=NIGHT_GRACE_HOURS)).date().isoformat()

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
                ttl_seconds=seconds_until_midnight(
                    self._clock(), getattr(actor, "timezone", None), grace_hours=NIGHT_GRACE_HOURS
                ),
            )
            await self._redis.set_json(
                self._key(*ids, "last"), {"site_id": site_id}, ttl_seconds=LAST_SITE_TTL_SECONDS
            )
        except Exception:  # noqa: BLE001 -- a missed hint only costs one question
            _log.warning("work_site.set_failed user=%s", ids[1], exc_info=True)

    # --- the waiting messages (SIT-02/03/04) ------------------------------------

    async def _waiting(self, ids: tuple[str, str]) -> dict[str, Any]:
        """``{"day": ..., "items": [message dicts, oldest first]}``, empty when
        nothing waits. An older single-message record is read as a queue of one."""
        raw = await self._redis.get_json(self._key(*ids, "parked"))
        if not raw:
            return {"day": None, "items": []}
        if "items" not in raw:
            return {"day": None, "items": [raw]}
        return {"day": raw.get("day"), "items": list(raw.get("items") or [])}

    async def _store(self, ids: tuple[str, str], day: str, items: list[dict[str, Any]]) -> None:
        if items:
            await self._redis.set_json(
                self._key(*ids, "parked"), {"day": day, "items": items}, ttl_seconds=PARK_TTL_SECONDS
            )
        else:
            await self._redis.delete(self._redis.namespaced(self._key(*ids, "parked")))

    @staticmethod
    def _preview(item: dict[str, Any]) -> str:
        text = " ".join(str(item.get("text") or "").split())
        return f"“{_cut(text, 40)}”" if text else "(a voice note or photo)"

    async def _take(self, ids: tuple[str, str], actor: Any) -> tuple[list[NormalizedMessage], str | None]:
        """Every message waiting for today's answer, in the order they came,
        and a line naming those from an earlier day that can no longer be
        saved (said, never dropped silently). Empties the queue."""
        async with self._lock(ids):
            waiting = await self._waiting(ids)
            today = self._day(actor)
            items = waiting["items"]
            await self._store(ids, today, [])
        stale = bool(items) and waiting["day"] not in (None, today)
        if stale:
            language = _language_of(" ".join(str(i.get("text") or "") for i in items))
            return [], _say(language, "expired", items=", ".join(self._preview(i) for i in items))
        out: list[NormalizedMessage] = []
        for item in items:
            try:
                out.append(NormalizedMessage.model_validate(item))
            except Exception:  # noqa: BLE001 -- one unreadable message must not lose the others
                _log.warning("work_site.waiting_unreadable user=%s", ids[1], exc_info=True)
        return out, None

    async def _release(
        self, actor: Any, ids: tuple[str, str], site_id: str, *, typed: bool
    ) -> tuple[ReplySpec, list[NormalizedMessage]]:
        """Today is this site; every waiting message runs there, in order."""
        label = site_label(actor, site_id) or "that site"
        await self.set_today(actor, project_id=None, site_id=site_id)
        waiting, expired = await self._take(ids, actor)
        language = _language_of(" ".join(m.text or "" for m in waiting))
        line = _say(language, "set", label=label)
        if waiting:
            line += _say(language, "ran", n=len(waiting)) if len(waiting) > 1 else ""
        if not waiting and expired:
            line += "\n" + expired
        if not waiting and not expired:
            released = await self._redis.get_json(self._key(*ids, "released"))
            if not released and not typed:
                line += _say(language, "nothing")
        await self._redis.set_json(
            self._key(*ids, "released"), {"site_id": site_id}, ttl_seconds=RELEASED_TTL_SECONDS
        )
        other = next((s for s in _sites(actor) if str(s.id) != str(site_id)), None)
        if other is not None:  # SIT-12: only a site they have
            line += _say(language, "tip", example=other.name)
        return ReplySpec(text=line), waiting

    async def morning_question(self, message: NormalizedMessage, actor: Any) -> ReplySpec | None:
        """The question to send instead of handling ``message`` now, or None to
        go on. Asked only of someone with 2+ sites who has no site for today and
        did not name one; the message waits, with any that follow, for the
        answer."""
        sites = _sites(actor)
        ids = _ids(actor)
        if ids is None or len(sites) < 2:
            return None
        if str(getattr(actor, "role", "") or "").upper() in _NOT_ASKED_ROLES:
            # Owners see every site and are rarely at one; a PM or finance user
            # is asked only when an entry needs a site. They can still say
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
            async with self._lock(ids):
                waiting = await self._waiting(ids)
                today = self._day(actor)
                stale = []
                if waiting["items"] and waiting["day"] not in (None, today):
                    stale, waiting = waiting["items"], {"day": today, "items": []}
                items = waiting["items"]
                dump = message.model_dump(mode="json")
                known = any(i.get("message_id") == dump.get("message_id") for i in items)
                full = len(items) >= MAX_WAITING and not known
                if not known and not full:
                    items = [*items, dump]
                await self._store(ids, today, items)
        except Exception:  # noqa: BLE001 -- never block a message on the hint store
            _log.warning("work_site.morning_check_failed user=%s", ids[1], exc_info=True)
            return None
        language = _language_of(message.text)
        if full:
            return ReplySpec(text=_say(language, "more", n=len(items)))
        last_id = str((last or {}).get("site_id") or "")
        projects = _project_names(actor)
        labels, cut = site_match.options(sites, projects, first_id=last_id)
        by_label = {label: s for s, label in site_match.labelled(sites, projects)}
        rows = []
        for label in labels:
            site = by_label.get(label)
            if site is None:  # "Something else": they type the name
                rows.append(ListRow(f"{TAP_PREFIX}else", site_match.SOMETHING_ELSE, _cut(_say(language, "typed"), _DESC_MAX)))
                continue
            project = projects.get(str(site.project_id or ""), "")
            rows.append(
                ListRow(
                    f"{TAP_PREFIX}{site.id}",
                    _cut(label, _TITLE_MAX),
                    _cut(("Last time · " if str(site.id) == last_id else "") + project, _DESC_MAX),
                )
            )
        first = (getattr(actor, "full_name", "") or "").split(" ")[0]
        hello = greeting(self._clock(), getattr(actor, "timezone", None), language)
        opening = f"{hello}{', ' + first if first else ''}! 👷\n" if hello else ""
        parts = [f"{opening}{_say(language, 'question')}"]
        if len(items) > 1:
            parts.append(_say(language, "hold", n=len(items)))
        if stale:
            parts.append(_say(language, "expired", items=", ".join(self._preview(i) for i in stale)))
        if cut:
            parts.append(_say(language, "typed"))
        return ReplySpec(text="\n\n".join(parts), list_button_label=_say(language, "button")[:20], list_rows=tuple(rows))

    async def answer_by_name(
        self, message: NormalizedMessage, actor: Any
    ) -> tuple[ReplySpec, list[NormalizedMessage]] | None:
        """While the question is open, a message that is just a site's name
        answers it like the tap would (SIT-03). None when nothing waits, the
        message is about something else, or the name is not one site."""
        ids = _ids(actor)
        if ids is None or message.modality is not InputModality.TEXT:
            return None
        text = " ".join((message.text or "").split())
        if not text or len(text.split()) > 6:
            return None
        try:
            if not (await self._waiting(ids))["items"]:
                return None
        except Exception:  # noqa: BLE001
            _log.warning("work_site.answer_check_failed user=%s", ids[1], exc_info=True)
            return None
        # "Site B", "at Site B", "now at Site B": the name and nothing else.
        said = " ".join(w for w in text.split() if w.casefold().strip(".,!") not in _FILLER)
        hits = site_match.find_sites(_sites(actor), said, _project_names(actor), part=False)
        hits = [s for s in hits if site_match.words(s.name) == site_match.words(said)] or (
            hits if len(hits) == 1 and len(site_match.words(said)) >= len(site_match.words(hits[0].name)) else []
        )
        if len(hits) != 1:
            return None
        return await self._release(actor, ids, str(hits[0].id), typed=True)

    async def handle_tap(
        self, message: NormalizedMessage, actor: Any
    ) -> tuple[ReplySpec, list[NormalizedMessage]] | None:
        """A tap on the morning list: ``(confirmation, the waiting messages to
        run now, in order)``, or None when it is not that tap."""
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if not tap.startswith(TAP_PREFIX):
            return None
        site_id = tap[len(TAP_PREFIX):]
        if site_id == "else":
            return ReplySpec(text=_say(_language_of(None), "typed")), []
        if site_label(actor, site_id) is None:
            return ReplySpec(text=_say("english", "unknown")), []
        ids = _ids(actor)
        if ids is None:
            await self.set_today(actor, project_id=None, site_id=site_id)
            return ReplySpec(text=_say("english", "set", label=site_label(actor, site_id) or "")), []
        try:
            return await self._release(actor, ids, site_id, typed=False)
        except Exception:  # noqa: BLE001 -- the switch itself still worked
            _log.warning("work_site.release_failed user=%s", ids[1], exc_info=True)
            return ReplySpec(text=_say("english", "set", label=site_label(actor, site_id) or "")), []


#: Words around a typed site name that do not change what it says.
_FILLER = frozenset({"at", "now", "in", "to", "is", "am", "i", "im", "i'm", "the"})
