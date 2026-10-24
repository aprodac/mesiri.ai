"""Cards for things that are not a saved record (request 104).

A Save card is built from review-log drafts (``save_button.py``). Some things
the sender asks for are not drafts: sending a question to the engineer, setting
the day's weather or tomorrow's plan, closing issues. They still wait on the
same Save / Cancel taps, so nothing happens before the tap and the model never
claims it did. Each is a *pending action*: what to do, kept per sender (Redis,
a few hours) and named on the tap by an id (fact type ``action``). On Save the
tap runs it and reports what really happened; on Cancel it is dropped.

Kinds:

- ``engineer_question``: WhatsApp the site's engineer(s), else its project
  manager(s), through the notification queue and its send/skip rules
  (24 h window, templates, opt-outs). The reply says who got it and who did not.
- ``site_conditions``: weather, site working, hours lost and tomorrow's plan of
  the site's day, through the setter the dashboard uses
  (``PostgresDprRepository.set_site_day_conditions``).
- ``close_issues``: resolve the named site issues through the same dispatcher a
  confirmed "resolve" takes.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

_log = logging.getLogger("mesiri.agent")

#: The fact type of a pending action on a card (a tap id carries its id).
ACTION_FACT = "action"

ENGINEER_QUESTION = "engineer_question"
SITE_CONDITIONS = "site_conditions"
CLOSE_ISSUES = "close_issues"

ACTION_TTL_SECONDS = 6 * 60 * 60

#: Said when the tap finds nothing waiting (expired, or already tapped).
GONE_LINE = "That one is already done or has expired. Please ask again."


@dataclass(slots=True)
class PendingAction:
    id: str
    kind: str
    payload: dict[str, Any]
    #: One short line for the card, e.g. "Rain, half day" -- from the data.
    summary: str
    created: float = field(default_factory=time.time)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: Any) -> PendingAction | None:
        try:
            return cls(
                id=str(raw["id"]),
                kind=str(raw["kind"]),
                payload=dict(raw["payload"]),
                summary=str(raw["summary"]),
                created=float(raw.get("created", 0)),
            )
        except Exception:  # noqa: BLE001 -- an unreadable action is no action
            return None


def new_action(kind: str, payload: dict[str, Any], summary: str) -> PendingAction:
    return PendingAction(id=uuid.uuid4().hex, kind=kind, payload=payload, summary=summary)


class ActionStore:
    """Per sender, the actions their open card waits on (Redis)."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    @staticmethod
    def _key(actor: Any, action_id: str) -> str | None:
        org = getattr(actor, "organization_id", None)
        user = getattr(actor, "user_id", None)
        return f"{org}:user:{user}:pending_action:{action_id}" if org and user else None

    async def put(self, actor: Any, action: PendingAction) -> bool:
        key = self._key(actor, action.id)
        if key is None:
            return False
        try:
            await self._redis.set_json(key, action.to_json(), ttl_seconds=ACTION_TTL_SECONDS)
        except Exception:  # noqa: BLE001 -- no stored action means no card; the caller says so
            _log.warning("agent.action_write_failed", exc_info=True)
            return False
        return True

    async def take(self, actor: Any, action_id: str) -> PendingAction | None:
        """The action, removed as it is read: a second tap finds nothing, so
        an action never runs twice."""
        key = self._key(actor, action_id)
        if key is None:
            return None
        try:
            raw = await self._redis.get_json(key)
            if not raw:
                return None
            await self._redis.delete(self._redis.namespaced(key))
        except Exception:  # noqa: BLE001
            _log.warning("agent.action_read_failed", exc_info=True)
            return None
        return PendingAction.from_json(raw)

    async def drop(self, actor: Any, action_id: str) -> None:
        key = self._key(actor, action_id)
        if key is None:
            return
        try:
            await self._redis.delete(self._redis.namespaced(key))
        except Exception:  # noqa: BLE001
            _log.warning("agent.action_drop_failed", exc_info=True)


#: What a skip reason of the notification queue means to the sender.
_SKIP_WORDS = {
    "outside_whatsapp_session_window_needs_template": (
        "hasn't messaged Mesiri in the last 24 hours, so WhatsApp won't deliver it"
    ),
    "no_resolvable_recipient": "has no WhatsApp number on Mesiri",
    "opted_out": "has opted out of messages",
    "send_failed": "could not be reached just now",
    "held": "is held until the morning",
}


def skip_words(reason: str) -> str:
    return _SKIP_WORDS.get(reason, "could not be reached")


def names_line(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def engineer_report(recipients: list[dict[str, Any]], outcomes: dict[str, str]) -> str:
    """What happened to the question, from the queue's own outcomes: who got
    it, who did not and why. Never says "sent" for a row that was skipped."""
    got, missed = [], []
    for person in recipients:
        outcome = outcomes.get(str(person.get("notification_id")), "send_failed")
        label = person["name"] + (f" ({person['role']})" if person.get("role") else "")
        if outcome == "sent":
            got.append(label)
        else:
            missed.append(f"{person['name']} {skip_words(outcome)}")
    if got and not missed:
        return f"✅ Sent to {names_line(got)}."
    if got:
        return f"✅ Sent to {names_line(got)}. Not delivered: " + "; ".join(missed) + "."
    return "❌ Not sent: " + "; ".join(missed) + ". Please ask them directly."


def engineer_message(*, asker: str, site: str | None, question: str) -> str:
    where = f" at {site}" if site else ""
    return f"❓ Question from {asker}{where}:\n{question}\n\nPlease reply to {asker} directly."


class ActionService:
    """Runs a pending action when its Save tap arrives. Built once with the
    services it needs; one method per kind, each returns the line to say."""

    def __init__(
        self,
        *,
        store: ActionStore,
        db: Any,
        actor_reader: Any,
        dispatcher: Any | None = None,
        object_storage: Any | None = None,
        approved_templates: frozenset[str] = frozenset(),
    ) -> None:
        self.store = store
        self._db = db
        self._actor_reader = actor_reader
        self._dispatcher = dispatcher
        self._object_storage = object_storage
        self._approved = approved_templates

    async def run(self, action: PendingAction, actor: Any, sender: Any) -> str:
        try:
            if action.kind == ENGINEER_QUESTION:
                return await self._send_engineer_question(action, actor, sender)
            if action.kind == SITE_CONDITIONS:
                return await self._set_conditions(action)
            if action.kind == CLOSE_ISSUES:
                return await self._close_issues(action, actor)
        except Exception:  # noqa: BLE001 -- said plainly, never "done"
            _log.exception("agent.action_failed kind=%s", action.kind)
            return "❌ That didn't go through, so nothing was changed. Please try again."
        return GONE_LINE

    # -- engineer question ------------------------------------------------------

    async def engineers(
        self, *, organization_id: str, project_id: str | None, site_id: str | None, exclude_user: str | None
    ) -> list[dict[str, Any]]:
        """Who a question for the engineer goes to: the site's engineers, else
        the project's managers and admins; only people with a WhatsApp number,
        never the sender."""
        from runtime import automation_audience as audience
        from runtime.project_auto_dpr import _project_dpr_recipients

        ids: list[str] = []
        if site_id:
            ids = list(
                await audience._site_engineers_for_sites(
                    self._db, organization_id=organization_id, site_ids=[site_id]
                )
            )
        if not ids and project_id:
            ids = list(
                await _project_dpr_recipients(
                    self._db, organization_id=organization_id, project_id=project_id
                )
            )
        ids = [i for i in dict.fromkeys(ids) if i != str(exclude_user)]
        people: list[dict[str, Any]] = []
        for user_id in ids:
            wa_id = await self._actor_reader.resolve_whatsapp_id_by_user_id(user_id)
            if not wa_id:
                continue
            name, role = await self._name_and_role(organization_id, user_id)
            people.append({"user_id": user_id, "name": name, "role": role})
        return people

    async def _name_and_role(self, organization_id: str, user_id: str) -> tuple[str, str]:
        import sqlalchemy as sa

        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    sa.text("SELECT full_name, role FROM users WHERE id = :id AND organization_id = :org"),
                    {"id": uuid.UUID(user_id), "org": uuid.UUID(organization_id)},
                )
            ).mappings().first()
        if row is None:
            return "Someone", ""
        return str(row["full_name"] or "Someone"), _role_word(str(row["role"] or ""))

    async def _send_engineer_question(self, action: PendingAction, actor: Any, sender: Any) -> str:
        payload = action.payload
        text = engineer_message(
            asker=str(payload.get("asker") or "A teammate"),
            site=payload.get("site_name"),
            question=str(payload["question"]),
        )
        queued = await self.queue_messages(
            organization_id=str(actor.organization_id),
            action_id=action.id,
            payload=payload,
            text=text,
            recipients=[dict(p) for p in payload["recipients"]],
        )
        if not queued:
            return "❌ Not sent: that question was already sent to them."
        outcomes = await self.deliver(frozenset(p["notification_id"] for p in queued), sender)
        return engineer_report(queued, outcomes)

    async def queue_messages(
        self,
        *,
        organization_id: str,
        action_id: str,
        payload: dict[str, Any],
        text: str,
        recipients: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """One notification row per person (the queue the evening review and
        the DPR use); each recipient comes back with its ``notification_id``."""
        from mesiri.infrastructure.postgres.repositories.notifications import (
            PostgresNotificationRepository,
        )

        queued: list[dict[str, Any]] = []
        async with self._db.transaction() as conn:
            repo = PostgresNotificationRepository(conn)
            for person in recipients:
                notification_id = await repo.claim(
                    organization_id=uuid.UUID(organization_id),
                    rule_key=f"engineer_question:{payload.get('site_id') or payload.get('project_id')}",
                    subject_id=f"{action_id}:{person['user_id']}",
                    occurred_on=datetime.now(UTC).date(),
                    recipient_user_id=uuid.UUID(person["user_id"]),
                    project_id=uuid.UUID(payload["project_id"]) if payload.get("project_id") else None,
                    site_id=uuid.UUID(payload["site_id"]) if payload.get("site_id") else None,
                    payload={"message": text},
                )
                if notification_id is not None:
                    queued.append({**person, "notification_id": str(notification_id)})
        return queued

    async def deliver(self, ids: frozenset[str], sender: Any) -> dict[str, str]:
        """Send those rows now by the queue's own rules (24 h window,
        templates, opt-outs). Returns ``{id: "sent" | the skip reason}``."""
        from runtime.send_pending_notifications import drain_and_send

        outcomes: dict[str, str] = {}
        await drain_and_send(
            db=self._db,
            actor_reader=self._actor_reader,
            sender=sender,
            object_storage=self._object_storage,
            approved_templates=self._approved,
            only_ids=ids,
            outcomes=outcomes,
        )
        return outcomes

    # -- site conditions --------------------------------------------------------

    async def _set_conditions(self, action: PendingAction) -> str:
        from mesiri.application.dpr import site_day
        from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

        payload = action.payload
        changes = dict(payload["changes"])
        try:
            async with self._db.transaction() as conn:
                await PostgresDprRepository(conn).set_site_day_conditions(
                    organization_id=uuid.UUID(payload["organization_id"]),
                    project_id=uuid.UUID(payload["project_id"]),
                    site_id=uuid.UUID(payload["site_id"]),
                    report_date=date.fromisoformat(payload["report_date"]),
                    changes=changes,
                )
        except site_day.InvalidSiteDayTransition:
            return (
                "❌ That day's report is already confirmed, so its weather and plan can't be "
                "changed here. Ask for it to be revised on the dashboard."
            )
        except ValueError as exc:
            return f"❌ Couldn't save it: {exc}."
        return f"✅ Saved: {action.summary}."

    # -- close issues -----------------------------------------------------------

    async def _close_issues(self, action: PendingAction, actor: Any) -> str:
        if self._dispatcher is None:
            return "❌ Closing issues isn't available here just now. Nothing was changed."
        from mesiri_contracts.application.results.execution_result import ExecutionStatus
        from mesiri_contracts.assistant.draft_action import DraftActionType
        from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
        from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

        payload = action.payload
        done, failed = [], []
        for issue in payload["issues"]:
            instance = f"wa-close-{action.id}-{issue['id']}"
            draft = DraftActionV2(
                draft_id=f"draft-{instance}",
                correlation_id=instance,
                workflow_instance_id=instance,
                action_type=DraftActionType.CLOSE_SITE_ISSUE,
                organization_id=str(actor.organization_id),
                user_id=str(actor.user_id),
                project_id=payload.get("project_id"),
                site_id=issue.get("site_id") or payload.get("site_id"),
                fields={"site_issue_id": issue["id"], "action": "resolve"},
            )
            confirmed = ConfirmedActionV2(
                confirmed_action_id=f"conf-{instance}",
                workflow_instance_id=instance,
                correlation_id=instance,
                draft_action=draft,
                confirmed_by_user_id=str(actor.user_id),
            )
            try:
                result = await self._dispatcher.dispatch(confirmed)
            except Exception:  # noqa: BLE001
                _log.exception("agent.close_issue_failed issue=%s", issue["id"])
                failed.append(issue["title"])
                continue
            (done if result.status is ExecutionStatus.SUCCEEDED else failed).append(issue["title"])
        if done and not failed:
            return "✅ Closed: " + "; ".join(done) + "."
        if done:
            return "✅ Closed: " + "; ".join(done) + ". ❌ Couldn't close: " + "; ".join(failed) + "."
        return "❌ Couldn't close: " + "; ".join(failed) + ". Nothing was changed."


_ROLE_WORDS = {
    "SITE_ENGINEER": "site engineer",
    "PROJECT_MANAGER": "project manager",
    "ADMIN": "admin",
    "OWNER": "owner",
    "SUPERVISOR": "supervisor",
}


def _role_word(role: str) -> str:
    return _ROLE_WORDS.get(role.upper(), role.replace("_", " ").lower())
