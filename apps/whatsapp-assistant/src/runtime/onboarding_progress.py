"""The setup-progress card for a new company's owner (SS-17).

Card 3 of the onboarding cards (channel/onboarding_cards): "N / 6" and the
next thing to do. Six steps, all read from data that already exists (nothing
new is stored about the company):

    company & site   always (the card only exists for a company)
    first update     any saved site record: work (activities) or a material
                     / issue (timeline_entries), the same rule as SA-02
    materials list   the catalogue has an active material
    company logo     a letterhead logo is uploaded, or the owner answered the
                     SS-14 branding question with photos
    site engineer    a project member with role SITE_ENGINEER
    report time      changed from the default, or the SS-14 report-time
                     question answered (same rule as the dashboard checklist)

When it is sent:
    a. right after the company's first saved update;
    b. after a later step completes;
    c. when the owner types "setup" / "setup status" (any time).
(a) and (b) are unprompted: at most one a day, never while a confirmation or
question is open, and only for self-serve WhatsApp companies in their first
30 days. The day a card goes out, SS-14 asks no separate setup question (its
NEXT box is the ask); when the next step is the report time the card is
followed by that question's buttons, because it is answered by a tap.

What was last shown (the done steps, the day) is a Redis hint, like the setup
question's: if it is lost the worst case is one extra card.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from channel.onboarding_cards import (
    ProgressFacts,
    build_progress_card,
    language_to_lang,
    render_card_png,
)
from mesiri.application.organizations.companies_overview import (
    DEFAULT_CUTOFF_TIME,
    DEFAULT_SEND_TIME,
)
from mesiri.domains.organizations import setup_questions as rules
from runtime.setup_questions import CARD_SENT_KEY

if TYPE_CHECKING:
    from backend.ports import ActorIdentity
    from channel.receipt import ReceiptRenderer
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from runtime.reply_language import UserLanguageStore
    from runtime.setup_questions import SetupQuestions

_log = logging.getLogger("mesiri.onboarding_progress")

_OWNER_ROLE = "ADMIN"
#: Same window as the SS-14 setup questions.
ACTIVE_DAYS = rules.ASK_WITHIN_DAYS
_STATE_TTL_SECONDS = 60 * 24 * 60 * 60
_SETUP_WORDS = frozenset({"setup", "setup status", "set up", "set up status"})

_FACTS_SQL = sa.text(
    """
    SELECT
      (EXISTS (SELECT 1 FROM activities a
                WHERE a.organization_id = o.id AND a.deleted_at IS NULL)
       OR EXISTS (SELECT 1 FROM timeline_entries t WHERE t.organization_id = o.id)
      ) AS first_update,
      EXISTS (SELECT 1 FROM materials_catalog m
               WHERE m.organization_id = o.id AND m.is_active) AS materials,
      (EXISTS (SELECT 1 FROM organization_settings st
                WHERE st.organization_id = o.id AND st.key = 'branding'
                  AND st.value ->> 'logo_object_key' IS NOT NULL)
       OR EXISTS (SELECT 1 FROM organization_settings st
                   WHERE st.organization_id = o.id AND st.key = 'setup_progress'
                     AND st.value -> 'branding' ->> 'state' = 'answered')
      ) AS logo,
      EXISTS (SELECT 1 FROM project_members pm JOIN projects p ON p.id = pm.project_id
               WHERE p.organization_id = o.id AND pm.role = 'SITE_ENGINEER') AS site_engineer,
      (EXISTS (SELECT 1 FROM projects p
                WHERE p.organization_id = o.id
                  AND (p.reporting_cutoff_time <> :default_cutoff
                       OR p.dpr_send_deadline <> :default_send))
       OR EXISTS (SELECT 1 FROM organization_settings st
                   WHERE st.organization_id = o.id AND st.key = 'setup_progress'
                     AND st.value -> 'report_time' ->> 'state' = 'answered')
      ) AS report_time,
      o.created_at, o.signup_source
    FROM organizations o WHERE o.id = :org_id
    """
)


class _RedisLike(Protocol):
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


def is_status_request(text: str | None) -> bool:
    """"setup" / "setup status" typed on its own (case and punctuation ignored)."""
    cleaned = re.sub(r"[^a-z ]", "", str(text or "").lower())
    return " ".join(cleaned.split()) in _SETUP_WORDS


def card_due(previous: dict[str, Any] | None, facts: ProgressFacts, *, today: str) -> bool:
    """The unprompted-card rule, pure.

    No card yet: wait for the first saved update (trigger a). Otherwise: a
    step completed since the last card (trigger b). Never twice in a day."""
    done = set(facts.done_keys())
    if previous is None:
        return facts.first_update
    if previous.get("on") == today:
        return False
    return bool(done - set(previous.get("done") or ()))


class OnboardingProgress:
    def __init__(
        self,
        *,
        db: PostgresDatabase,
        redis: _RedisLike,
        renderer: ReceiptRenderer | None,
        setup_questions: SetupQuestions | None,
        language_store: UserLanguageStore | None,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._db = db
        self._redis = redis
        self._renderer = renderer
        self._setup_questions = setup_questions
        self._language_store = language_store
        self._now = now or (lambda: dt.datetime.now(dt.UTC))

    # -- triggers ---------------------------------------------------------------

    async def after_reply(
        self,
        actor: ActorIdentity | None,
        *,
        wa_id: str,
        send_image: Callable[..., Any],
        send_spec: Callable[..., Any],
    ) -> bool:
        """Triggers (a) and (b). True when a card was sent."""
        if not _is_owner(actor):
            return False
        assert actor is not None
        today = self._today(actor.timezone)
        previous = await self._state(actor.user_id)
        if previous is not None and previous.get("on") == today.isoformat():
            return False
        if self._setup_questions is not None and await self._setup_questions.is_open(actor.user_id):
            return False
        facts, created_at, source = await self._read(actor.organization_id)
        if source != "whatsapp" or created_at is None:
            return False
        if (self._now() - created_at).days > ACTIVE_DAYS:
            return False
        if not card_due(previous, facts, today=today.isoformat()):
            return False
        return await self._send(
            actor, facts, wa_id=wa_id, send_image=send_image, send_spec=send_spec, prompted=False
        )

    async def send_status(
        self,
        actor: ActorIdentity,
        *,
        wa_id: str,
        send_image: Callable[..., Any],
        send_spec: Callable[..., Any],
        send_text: Callable[..., Any],
    ) -> None:
        """Trigger (c): the owner asked. Always answers, with a text fallback."""
        facts, _, _ = await self._read(actor.organization_id)
        sent = await self._send(
            actor, facts, wa_id=wa_id, send_image=send_image, send_spec=send_spec, prompted=True
        )
        if not sent:
            card = build_progress_card(site_name=_site_name(actor), facts=facts)
            await send_text(wa_id, f"Setup: {card.done} / {card.total}\n{card.action_label}: {card.action_text}")

    # -- internals --------------------------------------------------------------

    async def _send(
        self,
        actor: ActorIdentity,
        facts: ProgressFacts,
        *,
        wa_id: str,
        send_image: Callable[..., Any],
        send_spec: Callable[..., Any],
        prompted: bool,
    ) -> bool:
        lang = "en"
        if self._language_store is not None:
            language, _ = await self._language_store.get_profile(user_id=actor.user_id)
            lang = language_to_lang(language)
        card = build_progress_card(site_name=_site_name(actor), facts=facts, lang=lang)
        png = await render_card_png(self._renderer, card)
        if png is None or not await send_image(wa_id, png, caption=None):
            return False
        today = self._today(actor.timezone).isoformat()
        previous = await self._state(actor.user_id)
        await self._redis.set_json(
            self._state_key(actor.user_id),
            {
                "on": today if not prompted else (previous or {}).get("on"),
                "done": list(facts.done_keys()),
            },
            ttl_seconds=_STATE_TTL_SECONDS,
        )
        await self._redis.set_json(
            CARD_SENT_KEY.format(user_id=actor.user_id), today, ttl_seconds=36 * 60 * 60
        )
        _log.info(
            "onboarding_card.sent org=%s done=%s/%s prompted=%s",
            actor.organization_id,
            card.done,
            card.total,
            prompted,
        )
        # The report time is answered with a tap, so its buttons follow the card.
        if card.next_step == "report_time" and self._setup_questions is not None:
            try:
                if not await self._setup_questions.is_open(actor.user_id):
                    await self._setup_questions.ask(actor, rules.REPORT_TIME, send_spec)
            except Exception:  # noqa: BLE001 -- the card already went out
                _log.exception("onboarding_card.report_time_ask_failed user=%s", actor.user_id)
        return True

    async def _read(self, organization_id: str | None) -> tuple[ProgressFacts, dt.datetime | None, str]:
        if not organization_id:
            return ProgressFacts(), None, ""
        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    _FACTS_SQL,
                    {
                        "org_id": uuid.UUID(str(organization_id)),
                        "default_cutoff": DEFAULT_CUTOFF_TIME,
                        "default_send": DEFAULT_SEND_TIME,
                    },
                )
            ).first()
        if row is None:
            return ProgressFacts(), None, ""
        facts = ProgressFacts(
            first_update=bool(row.first_update),
            materials=bool(row.materials),
            logo=bool(row.logo),
            site_engineer=bool(row.site_engineer),
            report_time=bool(row.report_time),
        )
        return facts, row.created_at, str(row.signup_source or "")

    async def _state(self, user_id: str) -> dict[str, Any] | None:
        try:
            value = await self._redis.get_json(self._state_key(user_id))
        except Exception:  # noqa: BLE001 -- unsure: treat as no card yet
            return None
        return value if isinstance(value, dict) else None

    def _today(self, timezone: str | None) -> dt.date:
        try:
            zone: dt.tzinfo = ZoneInfo(timezone or "Asia/Kolkata")
        except Exception:  # noqa: BLE001
            zone = ZoneInfo("Asia/Kolkata")
        return self._now().astimezone(zone).date()

    @staticmethod
    def _state_key(user_id: str) -> str:
        return f"user:{user_id}:onboarding_card"


def _is_owner(actor: ActorIdentity | None) -> bool:
    return (
        actor is not None
        and actor.organization_id is not None
        and actor.org_active
        and str(actor.role or "").upper() == _OWNER_ROLE
    )


def _site_name(actor: ActorIdentity) -> str:
    if actor.sites:
        return actor.sites[0].name
    if actor.projects:
        return actor.projects[0].name
    return actor.org_name or ""
