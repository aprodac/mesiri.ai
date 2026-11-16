"""Daily setup questions for a new company's owner (SS-14).

Rules live in mesiri/domains/organizations/setup_questions.py; this is the
WhatsApp side. After Mesiri has replied to one of the owner's own messages
(so we're inside WhatsApp's 24-hour window and need no template), at most one
question a day:

    branding     "Send a photo of your letterhead / visiting card / logo"
                 -> the photos are saved as a branding request and posted
                 to the Mesiri team's WhatsApp group; the team fills the
                 letterhead in from the control panel; the owner is told
                 on their next message once it's done
    report_time  [7 pm] [8 pm] [Keep 9 pm] -> every project's send deadline
    more_sites   [Add a site] [No] -> the existing "add a site" workflow

Before them, for a new owner who has not answered it on the dashboard (SS-34, guided onboarding):

    start_mode   "How would you like to start?" [Step by step] [Bring my Excel/paper]
                 [Used other software] [I'll find my way] -> users.start_mode, the same answer
                 as the dashboard's question; the reply is the first tip for that answer

Never asked while the owner has a confirmation or question open, or entries
waiting for Save (v3's ready list, classic's card or draft, WA-176), so a
setup question can't land in the middle of something else.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from channel.replies import ListRow, ReplySpec
from mesiri.domains.identity.preferences_router import (
    START_MODES,
    effective_reply_language,
    start_mode_for,
)
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.organizations import setup_questions as rules
from mesiri.infrastructure.postgres.repositories.organization_settings import (
    PostgresOrganizationSettingsRepository,
)
from mesiri_contracts.assistant.enums import InputModality
from runtime.agent.wording import LANGUAGES, LINES, say

if TYPE_CHECKING:
    from backend.ports import ActorIdentity
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from mesiri_contracts.common.storage import ObjectStoragePort
    from runtime.team_notify import TeamNotifier
    from workflows import WorkflowRuntime

_log = logging.getLogger("mesiri.setup_questions")

TAP_PREFIX = "setup_q:"
SKIP_BRANDING = "setup_q:branding_skip"
TIME_PREFIX = "setup_q:time:"
ADD_SITE = "setup_q:site_add"
NO_SITE = "setup_q:site_no"
#: SET-08 / SET-11: with several projects the answer asks which one.
SITE_IN_PREFIX = "setup_q:site_in:"
TIME_FOR_PREFIX = "setup_q:time_for:"
ALL_PROJECTS = "all"
#: SS-34: "How would you like to start?" answers, ``setup_q:mode:<start mode>``.
MODE_PREFIX = "setup_q:mode:"

#: onboarding_progress writes today's date here when it sends the progress card.
CARD_SENT_KEY = "user:{user_id}:onboarding_card_sent"

_OWNER_ROLE = "ADMIN"
_ASKED_TTL_SECONDS = 24 * 60 * 60
#: After the first photo, more photos in the next half hour join the request.
_COLLECT_TTL_SECONDS = 30 * 60
#: Nothing due: don't look again for a few hours (it runs after every message
#: from an owner). A finished branding request waits at most this long.
_IDLE_TTL_SECONDS = 3 * 60 * 60

#: SS-63 (16 Nov 2026): every line below is the owner's own language, from runtime/agent/wording.py LINES (English,
#: Manglish, Malayalam, Hindi, Hinglish), picked per message from their reply language (users.reply_language, WA-169;
#: none chosen: Manglish, WA-207). The names below are the English lines, kept for callers and tests.
_LANG: ContextVar[str] = ContextVar("setup_questions_language", default="english")


def _t(key: str, **values: str) -> str:
    """The line ``key`` in this message's language (``_LANG``)."""
    return say(key, _LANG.get(), **values)


def _en(key: str) -> str:
    return LINES[key]["english"]


ASK_BRANDING = _en("setup.ask_branding")
BRANDING_RECEIVED = _en("setup.branding_received")
BRANDING_MORE = _en("setup.branding_more")
BRANDING_SKIPPED = _en("setup.branding_skipped")
BRANDING_DONE = _en("setup.branding_done")
ASK_REPORT_TIME = _en("setup.ask_report_time")
REPORT_TIME_SET = _en("setup.report_time_set")
REPORT_TIME_KEPT = _en("setup.report_time_kept")
ASK_MORE_SITES = _en("setup.ask_more_sites")
ASK_SITE_PROJECT = _en("setup.ask_site_project")
ASK_TIME_SCOPE = _en("setup.ask_time_scope")
REPORT_TIME_SET_FOR = _en("setup.report_time_set_for")
NO_MORE_SITES = _en("setup.no_more_sites")
EXPIRED = _en("setup.expired")
#: WA-84: "report time 7 pm aakku" from someone who may not change it (the dashboard's rule).
REPORT_TIME_OWNER_ONLY = _en("setup.report_time_owner_only")
#: WA-84: the times a report can go out at, said before the buttons.
REPORT_TIME_PICK = _en("setup.report_time_pick")
REPORT_TIME_CHOICES = _en("setup.report_time_choices")

_TIME_LABEL = {"19:00": "7 pm", "20:00": "8 pm", "21:00": "9 pm"}

#: SS-34 (guided-onboarding-plan.md 6.1): the dashboard's four answers, in WhatsApp's 24-character titles.
ASK_START_MODE = _en("start.ask")


def start_mode_rows(language: str = "english") -> tuple[ListRow, ...]:
    """The four answers as list rows, in ``language`` (titles at most 24 characters, descriptions 72)."""
    return tuple(
        ListRow(id=f"{MODE_PREFIX}{mode}", title=say(f"start.{mode}.title", language),
                description=say(f"start.{mode}.hint", language))
        for mode in START_MODES
    )


START_MODE_ROWS: tuple[ListRow, ...] = start_mode_rows()
#: The reply to each answer: its first tip (nothing for "I'll find my way" beyond the thanks).
START_MODE_REPLY: dict[str, str] = {mode: _en(f"start.{mode}.reply") for mode in START_MODES}


class _RedisLike(Protocol):
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


_organizations = sa.Table(
    "organizations",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("timezone", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)
#: SS-34: the owner's own start mode (migration 0553), read to know whether to ask and written by the answer.
_users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("start_mode", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("reply_language", sa.String),
)
_projects = sa.Table(
    "projects",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("dpr_send_deadline", sa.String),
)


def _time_label(value: str | None) -> str:
    return _TIME_LABEL.get(str(value or ""), str(value or "9 pm"))


class SetupQuestions:
    def __init__(
        self,
        *,
        db: PostgresDatabase,
        redis: _RedisLike,
        storage: ObjectStoragePort,
        notifier: TeamNotifier,
        workflow_runtime: WorkflowRuntime,
        start_site_followup: Callable[..., Any],
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._db = db
        self._redis = redis
        self._storage = storage
        self._notifier = notifier
        self._runtime = workflow_runtime
        self._start_site_followup = start_site_followup
        self._now = now or (lambda: dt.datetime.now(dt.UTC))

    # -- after Mesiri has replied to the owner ---------------------------------

    async def after_reply(self, actor: ActorIdentity | None, send: Callable[..., Any]) -> None:
        """Send today's setup question (or a "your letterhead is ready"
        notice) if one is due. `send(spec)` delivers a ReplySpec."""
        if actor is None or actor.organization_id is None or not actor.org_active:
            return
        if str(actor.role or "").upper() != _OWNER_ROLE:
            return
        if await self._redis.get_json(self._hint_key(actor.user_id)):
            return  # a question is still waiting for its answer
        if await self._redis.get_json(self._idle_key(actor.user_id)):
            return  # checked recently and nothing was due
        if await self._busy(actor.user_id, actor.organization_id):
            return
        # The setup-progress card went out today: its NEXT box is today's ask.
        if await self._redis.get_json(CARD_SENT_KEY.format(user_id=actor.user_id)) == self._today(
            actor.timezone
        ).isoformat():
            return

        await self._use_language(actor)
        org_id = actor.organization_id
        async with self._db.transaction() as conn:
            org = (
                await conn.execute(
                    sa.select(_organizations.c.timezone, _organizations.c.created_at).where(
                        _organizations.c.id == org_id
                    )
                )
            ).first()
            if org is None:
                return
            repo = PostgresOrganizationSettingsRepository(conn)
            requests = await repo.get(org_id, org_settings.BRANDING_REQUESTS)
            finished = rules.request_to_announce(requests)
            if finished is not None:
                await repo.set(
                    org_id,
                    org_settings.BRANDING_REQUESTS,
                    rules.mark_announced(requests, finished["id"]),
                    updated_by=None,
                )
                spec: ReplySpec | None = ReplySpec(text=_t("setup.branding_done"))
                question = None
            else:
                today = self._today(org.timezone)
                created_on = org.created_at.astimezone(_zone(org.timezone)).date()
                progress = await repo.get(org_id, org_settings.SETUP_PROGRESS)
                question = rules.next_question(
                    progress,
                    today=today,
                    company_created_on=created_on,
                    ask_start_mode=await self._should_ask_start_mode(conn, actor),
                )
                if question is None:
                    # SS-38: no setup question today, so maybe one of the first week's tips (never both in a day).
                    tip = rules.next_tip(
                        progress, start_mode=await self._start_mode(conn, actor), today=today,
                        company_created_on=created_on,
                    )
                    if tip is None:
                        await self._redis.set_json(
                            self._idle_key(actor.user_id), True, ttl_seconds=_IDLE_TTL_SECONDS
                        )
                        return
                    sent = (progress.get("tips") or {}) if isinstance(progress, dict) else {}
                    first = not (isinstance(sent, dict) and sent.get("sent"))
                    # The first tip says how to stop them ("no more tips": v3 set_start_mode to free).
                    spec = ReplySpec(text=_t(f"tip.{tip}") + (f"\n\n{_t('tip.stop')}" if first else ""))
                    await repo.set(
                        org_id, org_settings.SETUP_PROGRESS, rules.record_tip(progress, tip, today=today), updated_by=None
                    )
                    await self._redis.set_json(self._idle_key(actor.user_id), True, ttl_seconds=_IDLE_TTL_SECONDS)
                    _log.info("setup_question.tip org=%s tip=%s", org_id, tip)
                else:
                    spec = await self._question_spec(conn, org_id, question)
                    await repo.set(
                        org_id,
                        org_settings.SETUP_PROGRESS,
                        rules.record(progress, question, rules.ASKED, today=today),
                        updated_by=None,
                    )
        if question is not None:
            await self._redis.set_json(
                self._hint_key(actor.user_id),
                {"question": question},
                ttl_seconds=_ASKED_TTL_SECONDS,
            )
            _log.info("setup_question.asked org=%s question=%s", org_id, question)
        await send(spec)

    async def is_open(self, user_id: str, organization_id: Any = None) -> bool:
        """A setup question waits for its answer, or a confirmation / question
        is open, or entries wait for Save: nothing else unprompted goes out (used
        by onboarding_progress)."""
        if await self._redis.get_json(self._hint_key(user_id)):
            return True
        return await self._busy(user_id, organization_id)

    async def ask(self, actor: ActorIdentity, question: str, send: Callable[..., Any]) -> None:
        """Ask one specific setup question now (the progress card's NEXT box
        points at it). Same record-and-remember steps as after_reply."""
        await self._use_language(actor)
        async with self._db.transaction() as conn:
            org = (
                await conn.execute(
                    sa.select(_organizations.c.timezone).where(
                        _organizations.c.id == actor.organization_id
                    )
                )
            ).first()
            spec = await self._question_spec(conn, actor.organization_id, question)
            repo = PostgresOrganizationSettingsRepository(conn)
            progress = await repo.get(actor.organization_id, org_settings.SETUP_PROGRESS)
            await repo.set(
                actor.organization_id,
                org_settings.SETUP_PROGRESS,
                rules.record(
                    progress, question, rules.ASKED, today=self._today(org.timezone if org else None)
                ),
                updated_by=None,
            )
        await self._redis.set_json(
            self._hint_key(actor.user_id), {"question": question}, ttl_seconds=_ASKED_TTL_SECONDS
        )
        await send(spec)

    async def offer_report_time(self, actor: ActorIdentity, wanted: str | None) -> ReplySpec:
        """WA-84: "report time 7 pm aakku" asks the report-time question of SS-14 now,
        with its buttons; the tap changes it (``handle_tap``), so nothing changes
        without one. Only the owner, as on the dashboard."""
        await self._use_language(actor)
        if str(getattr(actor, "role", "") or "").strip().upper() != _OWNER_ROLE:
            return ReplySpec(text=_t("setup.report_time_owner_only"))
        async with self._db.transaction() as conn:
            spec = await self._question_spec(conn, actor.organization_id, rules.REPORT_TIME)
        await self._redis.set_json(
            self._hint_key(actor.user_id), {"question": rules.REPORT_TIME}, ttl_seconds=_ASKED_TTL_SECONDS
        )
        lead = (
            _t("setup.report_time_pick", time=_time_label(wanted))
            if wanted in rules.REPORT_TIMES
            else _t("setup.report_time_choices")
        )
        return ReplySpec(text=f"{spec.text}\n{lead}", buttons=spec.buttons)

    # -- answers ----------------------------------------------------------------

    async def handle_tap(self, message: Any, actor: ActorIdentity) -> ReplySpec | None:
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if not tap.startswith(TAP_PREFIX):
            return None
        await self._use_language(actor)
        hint = await self._redis.get_json(self._hint_key(actor.user_id))
        question = hint.get("question") if isinstance(hint, dict) else None
        if tap.startswith(MODE_PREFIX):
            return await self._start_mode_tap(actor, question, tap[len(MODE_PREFIX) :])
        expected = {
            SKIP_BRANDING: rules.BRANDING,
            ADD_SITE: rules.MORE_SITES,
            NO_SITE: rules.MORE_SITES,
        }.get(tap)
        if expected is None:
            if tap.startswith(SITE_IN_PREFIX):
                expected = rules.MORE_SITES
            elif tap.startswith((TIME_PREFIX, TIME_FOR_PREFIX)):
                expected = rules.REPORT_TIME
        if expected is None or question != expected:
            return ReplySpec(text=_t("setup.expired"))
        await self._clear_hint(actor.user_id)

        if tap.startswith(TIME_FOR_PREFIX):
            return await self._time_for(actor, hint, tap[len(TIME_FOR_PREFIX) :])
        if tap.startswith(SITE_IN_PREFIX):
            project = next(
                (p for p in actor.projects or [] if str(p.id) == tap[len(SITE_IN_PREFIX) :]), None
            )
            if project is None:
                return ReplySpec(text=_t("setup.expired"))
            return await self._start_site_followup(
                stage="site",
                project_id=str(project.id),
                actor=actor,
                workflow_runtime=self._runtime,
            )

        if tap == SKIP_BRANDING:
            await self._record(actor, rules.BRANDING, rules.SKIPPED)
            return ReplySpec(text=_t("setup.branding_skipped"))

        if tap.startswith(TIME_PREFIX):
            chosen = tap[len(TIME_PREFIX) :]
            if chosen not in rules.REPORT_TIMES:
                return ReplySpec(text=_t("setup.expired"))
            async with self._db.transaction() as conn:
                current = await self._current_deadline(conn, actor.organization_id)
            if chosen != current and len(actor.projects or []) > 1:
                # SET-11: a change with several projects asks where it applies.
                await self._redis.set_json(
                    self._hint_key(actor.user_id),
                    {"question": rules.REPORT_TIME, "time": chosen},
                    ttl_seconds=_ASKED_TTL_SECONDS,
                )
                return self._time_scope_spec(actor, chosen)
            async with self._db.transaction() as conn:
                if chosen != current:
                    await conn.execute(
                        _projects.update()
                        .where(_projects.c.organization_id == actor.organization_id)
                        .values(dpr_send_deadline=chosen)
                    )
            await self._record(actor, rules.REPORT_TIME, rules.ANSWERED)
            key = "setup.report_time_kept" if chosen == current else "setup.report_time_set"
            return ReplySpec(text=_t(key, time=_time_label(chosen)))

        await self._record(actor, rules.MORE_SITES, rules.ANSWERED)
        if tap == NO_SITE or not actor.projects:
            return ReplySpec(text=_t("setup.no_more_sites"))
        if len(actor.projects) > 1:
            # SET-08: never the first project by default.
            await self._redis.set_json(
                self._hint_key(actor.user_id),
                {"question": rules.MORE_SITES},
                ttl_seconds=_ASKED_TTL_SECONDS,
            )
            return self._project_picker(
                _t("setup.ask_site_project"), SITE_IN_PREFIX, list(actor.projects)
            )
        return await self._start_site_followup(
            stage="site",
            project_id=str(actor.projects[0].id),
            actor=actor,
            workflow_runtime=self._runtime,
        )

    async def handle_media(self, message: Any, actor: ActorIdentity) -> ReplySpec | None:
        """A photo or document sent while the branding question is open."""
        if message.modality not in (InputModality.IMAGE, InputModality.DOCUMENT):
            return None
        if message.media is None or not message.media.object_key:
            return None
        hint = await self._redis.get_json(self._hint_key(actor.user_id))
        if not isinstance(hint, dict) or hint.get("question") != rules.BRANDING:
            return None
        await self._use_language(actor)

        async with self._db.transaction() as conn:
            repo = PostgresOrganizationSettingsRepository(conn)
            requests, started = rules.add_branding_files(
                await repo.get(actor.organization_id, org_settings.BRANDING_REQUESTS),
                object_key=message.media.object_key,
                content_type=message.media.mime_type,
                sent_by=str(actor.user_id),
                now=self._now(),
            )
            await repo.set(
                actor.organization_id, org_settings.BRANDING_REQUESTS, requests, updated_by=None
            )
        if started:
            await self._record(actor, rules.BRANDING, rules.ANSWERED)
        # Keep collecting for a while: a letterhead and a logo come as two photos.
        await self._redis.set_json(
            self._hint_key(actor.user_id),
            {"question": rules.BRANDING},
            ttl_seconds=_COLLECT_TTL_SECONDS,
        )
        await self._tell_team(actor, message, first=started)
        return ReplySpec(text=_t("setup.branding_received" if started else "setup.branding_more"))

    # -- internals --------------------------------------------------------------

    @staticmethod
    def _project_picker(text: str, prefix: str, projects: list[Any], *, first: ListRow | None = None) -> ReplySpec:
        rows = ([first] if first else []) + [
            ListRow(id=f"{prefix}{p.id}", title=p.name[:24]) for p in projects
        ]
        if len(rows) <= 3:
            return ReplySpec(text=text, buttons=tuple(rows))
        return ReplySpec(text=text, list_button_label=_t("setup.choose"), list_rows=tuple(rows[:10]))

    def _time_scope_spec(self, actor: ActorIdentity, chosen: str) -> ReplySpec:
        return self._project_picker(
            _t("setup.ask_time_scope", time=_time_label(chosen)),
            TIME_FOR_PREFIX,
            list(actor.projects or []),
            first=ListRow(id=f"{TIME_FOR_PREFIX}{ALL_PROJECTS}", title=_t("setup.all_projects")),
        )

    async def _time_for(self, actor: ActorIdentity, hint: Any, which: str) -> ReplySpec:
        chosen = str(hint.get("time") or "") if isinstance(hint, dict) else ""
        if chosen not in rules.REPORT_TIMES:
            return ReplySpec(text=_t("setup.expired"))
        project = None
        if which != ALL_PROJECTS:
            project = next((p for p in actor.projects or [] if str(p.id) == which), None)
            if project is None:
                return ReplySpec(text=_t("setup.expired"))
        async with self._db.transaction() as conn:
            stmt = _projects.update().where(_projects.c.organization_id == actor.organization_id)
            if project is not None:
                stmt = stmt.where(_projects.c.id == uuid.UUID(str(project.id)))
            await conn.execute(stmt.values(dpr_send_deadline=chosen))
        await self._record(actor, rules.REPORT_TIME, rules.ANSWERED)
        if project is not None:
            return ReplySpec(text=_t("setup.report_time_set_for", project=project.name, time=_time_label(chosen)))
        return ReplySpec(text=_t("setup.report_time_set", time=_time_label(chosen)))

    async def _use_language(self, actor: ActorIdentity) -> None:
        """SS-63: this message's lines in the owner's reply language (users.reply_language, WA-169): their choice, or
        Manglish when none is chosen (WA-207); "auto" follows each message, and this is no reply to one: Manglish too.
        No user row (a stand-in in tests): English."""
        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    sa.select(_users.c.reply_language).where(
                        _users.c.id == uuid.UUID(str(actor.user_id)),
                        _users.c.organization_id == actor.organization_id,
                    )
                )
            ).first()
        language = "english" if row is None else effective_reply_language(getattr(row, "reply_language", None))
        _LANG.set(language if language in LANGUAGES else "manglish")

    async def _start_mode(self, conn: Any, actor: ActorIdentity) -> str | None:
        """SS-38: how the owner chose to start (what no answer means for them: ``start_mode_for``); None: no row."""
        row = (
            await conn.execute(
                sa.select(_users.c.start_mode, _users.c.created_at).where(
                    _users.c.id == uuid.UUID(str(actor.user_id)),
                    _users.c.organization_id == actor.organization_id,
                )
            )
        ).first()
        return None if row is None else start_mode_for(row.start_mode, row.created_at, self._now())[0]

    async def _should_ask_start_mode(self, conn: Any, actor: ActorIdentity) -> bool:
        """SS-34: the dashboard's rule (``start_mode_for``): asked only of a new person who has not answered."""
        row = (
            await conn.execute(
                sa.select(_users.c.start_mode, _users.c.created_at).where(
                    _users.c.id == uuid.UUID(str(actor.user_id)),
                    _users.c.organization_id == actor.organization_id,
                )
            )
        ).first()
        if row is None:
            return False
        return start_mode_for(row.start_mode, row.created_at, self._now())[1]

    async def _start_mode_tap(self, actor: ActorIdentity, question: str | None, mode: str) -> ReplySpec:
        """SS-34: the answer to "How would you like to start?", on the owner's own row, as the dashboard saves it.
        A late tap after the question was answered elsewhere still just records the newer answer."""
        if mode not in START_MODES:
            return ReplySpec(text=_t("setup.expired"))
        if question == rules.START_MODE:
            await self._clear_hint(actor.user_id)
        async with self._db.transaction() as conn:
            await conn.execute(
                _users.update()
                .where(
                    _users.c.id == uuid.UUID(str(actor.user_id)),
                    _users.c.organization_id == actor.organization_id,
                )
                .values(start_mode=mode)
            )
        await self._record(actor, rules.START_MODE, rules.ANSWERED)
        _log.info("setup_question.start_mode org=%s mode=%s", actor.organization_id, mode)
        return ReplySpec(text=_t(f"start.{mode}.reply"))

    async def _question_spec(self, conn: Any, org_id: Any, question: str) -> ReplySpec:
        if question == rules.START_MODE:
            return ReplySpec(text=_t("start.ask"), list_button_label=_t("setup.choose"), list_rows=start_mode_rows(_LANG.get()))
        if question == rules.BRANDING:
            return ReplySpec(text=_t("setup.ask_branding"), buttons=[ListRow(id=SKIP_BRANDING, title=_t("setup.skip"))])
        if question == rules.REPORT_TIME:
            current = await self._current_deadline(conn, org_id)
            buttons = [
                ListRow(
                    id=f"{TIME_PREFIX}{t}",
                    title=_t("setup.keep_time", time=_time_label(t)) if t == current else _time_label(t),
                )
                for t in rules.REPORT_TIMES
            ]
            return ReplySpec(
                text=_t("setup.ask_report_time", current=_time_label(current)), buttons=buttons
            )
        return ReplySpec(
            text=_t("setup.ask_more_sites"),
            buttons=[ListRow(id=ADD_SITE, title=_t("setup.add_site")), ListRow(id=NO_SITE, title=_t("setup.no"))],
        )

    async def _current_deadline(self, conn: Any, org_id: Any) -> str:
        row = (
            await conn.execute(
                sa.select(_projects.c.dpr_send_deadline)
                .where(_projects.c.organization_id == org_id)
                .limit(1)
            )
        ).first()
        return row.dpr_send_deadline if row is not None and row.dpr_send_deadline else "21:00"

    async def _record(self, actor: ActorIdentity, question: str, state: str) -> None:
        async with self._db.transaction() as conn:
            org = (
                await conn.execute(
                    sa.select(_organizations.c.timezone).where(
                        _organizations.c.id == actor.organization_id
                    )
                )
            ).first()
            repo = PostgresOrganizationSettingsRepository(conn)
            progress = await repo.get(actor.organization_id, org_settings.SETUP_PROGRESS)
            await repo.set(
                actor.organization_id,
                org_settings.SETUP_PROGRESS,
                rules.record(
                    progress, question, state, today=self._today(org.timezone if org else None)
                ),
                updated_by=None,
            )

    async def _tell_team(self, actor: ActorIdentity, message: Any, *, first: bool) -> None:
        if not self._notifier.configured:
            return
        images: list[tuple[bytes, str | None]] = []
        if message.modality is InputModality.IMAGE:
            try:
                stored = await self._storage.get_object(message.media.object_key)
                images.append((stored.data, actor.org_name))
            except Exception:  # noqa: BLE001
                _log.warning("setup_question.image_read_failed key=%s", message.media.object_key)
        text = (
            f"🏷️ *{actor.org_name or 'A company'}* sent letterhead/logo photos for their "
            f"report (from {actor.full_name}). Set it up in the control panel: "
            "company → Branding requests."
            if first
            else f"🏷️ One more from *{actor.org_name or 'a company'}*."
        )
        await self._notifier.post(text, images=images)

    async def _busy(self, user_id: str, organization_id: Any = None) -> bool:
        try:
            if await self._runtime.get_awaiting_confirmation(user_id):
                return True
            if await self._runtime.get_awaiting_input(user_id):
                return True
            return await self._save_waiting(user_id, organization_id)
        except Exception:  # noqa: BLE001 -- unsure means don't interrupt
            return True

    async def _save_waiting(self, user_id: str, organization_id: Any) -> bool:
        """WA-176: entries wait for this person's Save, on any assistant: v3's ready list,
        classic's open card or its open draft. Asking about a letterhead under an unsaved
        "10 bags cement" buried the Save (live 4 Nov)."""
        if not organization_id:
            return False
        from agent_api.whatsapp import has_ready_entries, state_key
        from runtime.agent.cards import OPEN, CardStore
        from runtime.agent.draft_store import PostgresDraftStore

        if has_ready_entries(await self._redis.get_json(state_key(organization_id, user_id))):
            return True
        card = await CardStore(self._redis).get(
            SimpleNamespace(organization_id=organization_id, user_id=user_id)
        )
        if card is not None and card.state == OPEN and card.items:
            return True
        return await PostgresDraftStore(self._db).open_for(organization_id, user_id) is not None

    async def _clear_hint(self, user_id: str) -> None:
        await self._redis.set_json(self._hint_key(user_id), None, ttl_seconds=60)

    def _today(self, timezone: str | None) -> dt.date:
        return self._now().astimezone(_zone(timezone)).date()

    @staticmethod
    def _hint_key(user_id: str) -> str:
        return f"user:{user_id}:setup_question"

    @staticmethod
    def _idle_key(user_id: str) -> str:
        return f"user:{user_id}:setup_idle"


def _zone(name: str | None) -> dt.tzinfo:
    try:
        return ZoneInfo(name or "Asia/Kolkata")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Kolkata")
