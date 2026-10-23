"""Tell the super admins on WhatsApp when something breaks (SA-11).

Every ERROR log line and unhandled exception in the app and the worker (the
same events INF-07 sends to Sentry) becomes a short WhatsApp message to each
super admin: every platform admin with a WhatsApp number on their account,
plus the numbers in the `ops_alerts` platform setting (control panel ->
Settings, audited). The AI provider alert (runtime/ai_failure_alert.py)
comes here too.

- The same error (logger + message template + exception type + line) is
  sent at most once per 30 minutes, across the app and the worker (Redis).
- Inside a super admin's 24 h window the alert is a normal message; outside
  it the `mesiri_ops_alert` template, once approved. When nobody could be
  reached, the team WhatsApp group gets it (setting `team_group_fallback`).
- A super admin can reply `alert details` (the latest alert's full error),
  `mute alerts` / `mute alerts 2h` (default 1 h, at most 24 h) and
  `unmute alerts`. These words are answered whoever else the number is in
  Mesiri, so they work from a phone that is also a test company's user.
- Phone numbers in the text are masked, as for Sentry. Message text that ends
  up in a log line can reach a super admin, who can read messages in the
  control panel already.

Best-effort throughout: an alert that cannot go is a WARNING in the log
(never an ERROR, which would alert again), and nothing here can fail a
customer's message. Off with MESIRI_OPS_ALERTS=off (staging sets it) or the
setting's `enabled` switch.
"""

from __future__ import annotations

import asyncio
import contextvars
import datetime as dt
import hashlib
import logging
import os
import re
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from runtime.error_reporting import _mask

_log = logging.getLogger("mesiri.ops_alerts")

THROTTLE_SECONDS = 30 * 60
_SETTINGS_CACHE_SECONDS = 60.0
_DETAIL_TTL_SECONDS = 24 * 3600
_MAX_MUTE_HOURS = 24
_BODY_MAX_CHARS = 400
_DETAIL_MAX_CHARS = 3000
_MAX_IN_FLIGHT = 20
_OFF_ENV = "MESIRI_OPS_ALERTS"

# Set while an alert is being sent, so a failure inside the send (logged by
# the sender) never becomes an alert of its own.
_sending: contextvars.ContextVar[bool] = contextvars.ContextVar("ops_alert_sending", default=False)

# Loggers whose errors are not ours to alert on, or would loop.
_IGNORED_LOGGERS = ("mesiri.ops_alerts", "mesiri.team_notify", "uvicorn.access")

_DETAILS = re.compile(r"^(alert|alerts|error)\s+details?$|^details$")
_MUTE = re.compile(r"^mute(\s+alerts?)?(\s+(\d{1,2})\s*(h|hr|hrs|hour|hours)?)?$")
_UNMUTE = re.compile(r"^unmute(\s+alerts?)?$")

DETAILS_NONE = "No error alert in the last 24 hours."
MUTED = "🔕 Error alerts muted for {hours} h on this number. Send *unmute alerts* to turn them back on."
UNMUTED = "🔔 Error alerts are on again for this number."


@dataclass(frozen=True, slots=True)
class Alert:
    key: str  # what makes two alerts "the same error"
    service: str  # "app" / "worker"
    summary: str  # one line, already masked
    detail: str = ""  # stack trace etc., already masked


def alert_from_record(record: logging.LogRecord, service: str) -> Alert:
    """The alert for one ERROR log record."""
    exc_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else ""
    template = record.msg if isinstance(record.msg, str) else type(record.msg).__name__
    fingerprint = f"{record.name}|{template}|{exc_type}|{record.pathname}:{record.lineno}"
    key = hashlib.sha1(fingerprint.encode(), usedforsecurity=False).hexdigest()[:16]
    try:
        message = record.getMessage()
    except Exception:  # noqa: BLE001 -- a bad %-format must not lose the alert
        message = str(record.msg)
    summary = message.splitlines()[0] if message else record.name
    if exc_type:
        exc_text = str(record.exc_info[1]) if record.exc_info and record.exc_info[1] else ""
        summary = f"{summary} ({exc_type}{': ' + exc_text if exc_text else ''})"
    detail = message
    if record.exc_info:
        detail += "\n" + "".join(traceback.format_exception(*record.exc_info))
    return Alert(
        key=key,
        service=service,
        summary=_clip(_mask(summary), _BODY_MAX_CHARS),
        detail=_mask(detail)[-_DETAIL_MAX_CHARS:],
    )


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def alerts_switched_off() -> bool:
    return os.environ.get(_OFF_ENV, "").strip().lower() in {"0", "off", "false", "no"}


class OpsAlerts:
    def __init__(
        self,
        *,
        sender: Any,
        db: Any,
        redis: Any,
        team_notifier: Any = None,
        service: str = "app",
        approved_templates: frozenset[str] = frozenset(),
        last_inbound_at: Callable[[str], Awaitable[dt.datetime | None]] | None = None,
        now: Callable[[], dt.datetime] | None = None,
        clock: Callable[[], float] = time.monotonic,
        live: bool = True,
    ) -> None:
        self._sender = sender
        self._db = db
        self._redis = redis
        self._team_notifier = team_notifier
        self.service = service
        self._approved_templates = approved_templates
        self._last_inbound_at = last_inbound_at
        self._now = now or (lambda: dt.datetime.now(dt.UTC))
        self._clock = clock
        self._cached: tuple[float, dict[str, Any], frozenset[str]] | None = None
        # False with the in-memory Redis (tests, local dev): nothing is sent.
        self.live = live

    # -- sending ---------------------------------------------------------------

    async def send(self, alert: Alert) -> int:
        """Send one alert; returns how many super admins it reached."""
        token = _sending.set(True)
        try:
            return await self._send(alert)
        except Exception:  # noqa: BLE001
            _log.warning("ops_alert.failed key=%s", alert.key, exc_info=True)
            return 0
        finally:
            _sending.reset(token)

    async def _send(self, alert: Alert) -> int:
        # An outage is when alerts matter most, so a database or Redis that is
        # down only weakens the rules (last known numbers, this process's own
        # throttle in OpsAlertLogHandler), never stops the alert.
        try:
            setting, recipients = await self._settings_and_recipients()
        except Exception:  # noqa: BLE001
            _log.warning("ops_alert.recipients_unavailable", exc_info=True)
            if self._cached is not None:
                setting, recipients = self._cached[1], self._cached[2]
            else:
                setting, recipients = {"enabled": True, "team_group_fallback": True}, frozenset()
        if not setting.get("enabled", True):
            return 0
        try:
            first = await self._redis.set_if_absent(
                self._key("seen", alert.key), "1", ttl_seconds=THROTTLE_SECONDS
            )
            if first:
                await self._redis.set_json(
                    self._key("last"),
                    {"service": alert.service, "summary": alert.summary,
                     "detail": alert.detail, "at": self._now().isoformat()},
                    ttl_seconds=_DETAIL_TTL_SECONDS,
                )
        except Exception:  # noqa: BLE001
            _log.warning("ops_alert.redis_unavailable", exc_info=True)
            first = True
        if not first:
            return 0
        text = (
            f"⚠️ *Mesiri error* ({alert.service})\n{alert.summary}\n\n"
            "Reply *alert details* for the full error, *mute alerts 2h* to pause."
        )
        reached = 0
        for wa_id in sorted(recipients):
            if await self._muted(wa_id):
                continue
            try:
                if await self._deliver(wa_id, alert, text):
                    reached += 1
                else:
                    _log.warning("ops_alert.not_reached wa_id=%s reason=outside_window", wa_id)
            except Exception:  # noqa: BLE001 -- one number's failure must not stop the rest
                _log.warning("ops_alert.not_reached wa_id=%s", wa_id, exc_info=True)
        if reached == 0 and setting.get("team_group_fallback", True) and self._team_notifier:
            await self._team_notifier.post(text)
        _log.info("ops_alert.sent key=%s recipients=%s reached=%s", alert.key, len(recipients), reached)
        return reached

    async def _muted(self, wa_id: str) -> bool:
        try:
            return bool(await self._redis.get_json(self._key("mute", wa_id)))
        except Exception:  # noqa: BLE001 -- Redis down: send rather than stay quiet
            return False

    async def _deliver(self, wa_id: str, alert: Alert, text: str) -> bool:
        from channel.whatsapp.templates import OPS_ALERT, clean_param

        if await self._outside_window(wa_id):
            if OPS_ALERT.name not in self._approved_templates:
                return False
            return await self._sender.send_template(
                wa_id,
                name=OPS_ALERT.name,
                language=OPS_ALERT.language,
                body_params=(clean_param(alert.service), clean_param(alert.summary)),
            )
        return await self._sender.send_text(wa_id, text)

    async def _outside_window(self, wa_id: str) -> bool:
        if self._last_inbound_at is None:
            return False
        from mesiri.application.notifications.checks import is_within_whatsapp_session_window

        try:
            last = await self._last_inbound_at(wa_id)
        except Exception:  # noqa: BLE001 -- unknown = try free-form
            return False
        return not is_within_whatsapp_session_window(last_inbound_at=last, now=self._now())

    # -- who gets them ---------------------------------------------------------

    async def _settings_and_recipients(self) -> tuple[dict[str, Any], frozenset[str]]:
        now = self._clock()
        if self._cached is not None and now - self._cached[0] < _SETTINGS_CACHE_SECONDS:
            return self._cached[1], self._cached[2]
        from sqlalchemy import text

        from mesiri.domains.organizations import platform_settings as spec
        from mesiri.infrastructure.postgres.repositories.platform_settings import (
            PostgresPlatformSettingsRepository,
        )
        from mesiri.infrastructure.postgres.tenant import tenant_scope

        # No company: super admins have none, and row-level security (BE-03)
        # would hide them while a customer's message has its company bound.
        with tenant_scope(None):
            async with self._db.transaction() as conn:
                setting = await PostgresPlatformSettingsRepository(conn).get(spec.OPS_ALERTS)
                rows = (
                    await conn.execute(
                        text(
                            "SELECT whatsapp_number FROM users WHERE role = 'ADMIN' "
                            "AND organization_id IS NULL AND status = 'active' "
                            "AND whatsapp_number IS NOT NULL"
                        )
                    )
                ).scalars()
                numbers = {_digits(n) for n in rows}
        numbers |= {_digits(n) for n in setting.get("numbers") or []}
        recipients = frozenset(n for n in numbers if n)
        self._cached = (now, dict(setting), recipients)
        return self._cached[1], recipients

    # -- a super admin's reply -------------------------------------------------

    async def handle_reply(self, wa_id: str, text: str | None) -> str | None:
        """The answer to `alert details` / `mute alerts 2h` / `unmute alerts`
        from a super admin, or None when the message is anything else."""
        words = " ".join(str(text or "").lower().split()).rstrip(".!")
        if not words or not (_DETAILS.match(words) or _MUTE.match(words) or _UNMUTE.match(words)):
            return None
        wa_id = _digits(wa_id)
        _setting, recipients = await self._settings_and_recipients()
        if wa_id not in recipients:
            return None
        if _DETAILS.match(words):
            last = await self._redis.get_json(self._key("last"))
            if not isinstance(last, dict):
                return DETAILS_NONE
            return f"*Last error* ({last.get('service')}, {last.get('at', '')[:16]} UTC)\n\n{last.get('detail') or last.get('summary')}"
        if _UNMUTE.match(words):
            # delete() takes a raw key; overwrite the namespaced one instead.
            await self._redis.set_json(self._key("mute", wa_id), None, ttl_seconds=60)
            return UNMUTED
        match = _MUTE.match(words)
        hours = min(int(match.group(3)), _MAX_MUTE_HOURS) if match and match.group(3) else 1
        hours = max(hours, 1)
        await self._redis.set_json(self._key("mute", wa_id), True, ttl_seconds=hours * 3600)
        return MUTED.format(hours=hours)

    def _key(self, *parts: str) -> str:
        return ":".join(("ops_alert", *parts))


class OpsAlertLogHandler(logging.Handler):
    """Turns ERROR log records into alerts, sent in the background."""

    def __init__(self, alerts: OpsAlerts) -> None:
        super().__init__(level=logging.ERROR)
        self._alerts = alerts
        self._loop: asyncio.AbstractEventLoop | None = None
        self._recent: dict[str, float] = {}
        self._tasks: set[asyncio.Future] = set()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if _sending.get() or record.name.startswith(_IGNORED_LOGGERS):
                return
            alert = alert_from_record(record, self._alerts.service)
            # In-process first pass, so an error in a loop doesn't hit Redis
            # for every line; Redis decides across processes.
            now = time.monotonic()
            if now - self._recent.get(alert.key, -THROTTLE_SECONDS) < THROTTLE_SECONDS:
                return
            if len(self._tasks) >= _MAX_IN_FLIGHT:
                return
            self._recent[alert.key] = now
            self._schedule(alert)
        except Exception:  # noqa: BLE001 -- logging must never raise
            self.handleError(record)

    def _schedule(self, alert: Alert) -> None:
        try:
            loop = asyncio.get_running_loop()
            self._loop = loop
        except RuntimeError:  # a thread without a loop: hand it to the app's loop
            loop = self._loop
            if loop is None or loop.is_closed():
                return
            loop.call_soon_threadsafe(self._start, alert)
            return
        self._start(alert)

    def _start(self, alert: Alert) -> None:
        # A fresh context: no company bound (BE-03), so the super admins'
        # rows (no company) are visible, and _sending starts unset.
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._alerts.send(alert), context=contextvars.Context())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def install_ops_alerts(alerts: OpsAlerts | None, service: str) -> OpsAlertLogHandler | None:
    """Attach the handler to the root logger for this process ("app" or
    "worker"), replacing an earlier one. None when there is nothing to send
    through (no real Redis) or MESIRI_OPS_ALERTS=off."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, OpsAlertLogHandler):
            root.removeHandler(handler)
    if alerts is None or not alerts.live:
        return None
    if alerts_switched_off():
        _log.info("ops_alerts.off reason=env")
        return None
    alerts.service = service
    handler = OpsAlertLogHandler(alerts)
    root.addHandler(handler)
    _log.info("ops_alerts.on service=%s", service)
    return handler
