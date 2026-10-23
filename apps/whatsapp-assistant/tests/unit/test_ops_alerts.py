"""SA-11: error alerts to the super admins on WhatsApp."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from contextlib import asynccontextmanager
from typing import Any

import pytest

from mesiri.domains.organizations import platform_settings as spec
from mesiri.infrastructure.postgres.tenant import current_tenant, tenant_scope
from mesiri.infrastructure.redis.client import FakeRedis
from runtime import ops_alerts
from runtime.ops_alerts import (
    Alert,
    OpsAlertLogHandler,
    OpsAlerts,
    alert_from_record,
    install_ops_alerts,
)

NOW = dt.datetime(2026, 10, 23, 9, 0, tzinfo=dt.UTC)
ADMIN_A, ADMIN_B = "919000000001", "919000000002"


class FakeSender:
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.texts: list[tuple[str, str]] = []
        self.templates: list[tuple[str, str, tuple]] = []
        self._fail_for = fail_for or set()

    async def send_text(self, wa_id: str, body: str) -> bool:
        if wa_id in self._fail_for:
            raise RuntimeError("meta said no")
        self.texts.append((wa_id, body))
        return True

    async def send_template(self, wa_id: str, *, name: str, language: str, body_params=()) -> bool:
        self.templates.append((wa_id, name, tuple(body_params)))
        return True


class FakeTeam:
    def __init__(self) -> None:
        self.posts: list[str] = []

    async def post(self, text: str, **_: Any) -> bool:
        self.posts.append(text)
        return True


class FixedAlerts(OpsAlerts):
    """The send rules, without the database lookup."""

    def __init__(self, *, recipients=(ADMIN_A, ADMIN_B), setting=None, **kwargs) -> None:
        super().__init__(db=None, now=lambda: NOW, **kwargs)
        self._setting = {**spec.DEFAULT_OPS_ALERTS, **(setting or {})}
        self._fixed = frozenset(recipients)

    async def _settings_and_recipients(self):
        return self._setting, self._fixed


def _alert(key: str = "k1") -> Alert:
    return Alert(key=key, service="worker", summary="dpr.render_failed project=Skyline")


async def test_every_super_admin_gets_the_alert_once() -> None:
    sender = FakeSender()
    alerts = FixedAlerts(sender=sender, redis=FakeRedis())
    assert await alerts.send(_alert()) == 2
    assert sorted(wa for wa, _ in sender.texts) == [ADMIN_A, ADMIN_B]
    assert "dpr.render_failed project=Skyline" in sender.texts[0][1]
    assert "alert details" in sender.texts[0][1]
    # The same error again within 30 minutes: nothing more.
    assert await alerts.send(_alert()) == 0
    assert len(sender.texts) == 2
    # A different error still goes.
    assert await alerts.send(_alert("k2")) == 2


async def test_switched_off_in_the_setting_sends_nothing() -> None:
    sender, team = FakeSender(), FakeTeam()
    alerts = FixedAlerts(sender=sender, redis=FakeRedis(), team_notifier=team, setting={"enabled": False})
    assert await alerts.send(_alert()) == 0
    assert sender.texts == [] and team.posts == []


async def test_outside_the_window_uses_the_template_once_approved() -> None:
    async def long_ago(_wa: str):
        return NOW - dt.timedelta(days=3)

    sender = FakeSender()
    alerts = FixedAlerts(
        sender=sender,
        redis=FakeRedis(),
        recipients=(ADMIN_A,),
        approved_templates=frozenset({"mesiri_ops_alert"}),
        last_inbound_at=long_ago,
    )
    assert await alerts.send(_alert()) == 1
    assert sender.texts == []
    assert sender.templates == [(ADMIN_A, "mesiri_ops_alert", ("worker", "dpr.render_failed project=Skyline"))]


async def test_nobody_reached_falls_back_to_the_team_group() -> None:
    async def long_ago(_wa: str):
        return None  # never messaged: outside the window, template not approved

    sender, team = FakeSender(), FakeTeam()
    alerts = FixedAlerts(sender=sender, redis=FakeRedis(), team_notifier=team, last_inbound_at=long_ago)
    assert await alerts.send(_alert()) == 0
    assert sender.templates == [] and len(team.posts) == 1
    assert "dpr.render_failed" in team.posts[0]


async def test_one_failing_number_does_not_stop_the_others() -> None:
    sender, team = FakeSender(fail_for={ADMIN_A}), FakeTeam()
    alerts = FixedAlerts(sender=sender, redis=FakeRedis(), team_notifier=team)
    assert await alerts.send(_alert()) == 1
    assert [wa for wa, _ in sender.texts] == [ADMIN_B]
    assert team.posts == []


async def test_mute_unmute_and_details() -> None:
    sender, redis = FakeSender(), FakeRedis()
    alerts = FixedAlerts(sender=sender, redis=redis)

    assert await alerts.handle_reply(ADMIN_A, "alert details") == ops_alerts.DETAILS_NONE
    assert "2 h" in await alerts.handle_reply(ADMIN_A, "Mute alerts 2h")
    await alerts.send(Alert(key="k1", service="app", summary="boom", detail="Traceback ... boom"))
    assert [wa for wa, _ in sender.texts] == [ADMIN_B]  # A is muted

    details = await alerts.handle_reply(f"+{ADMIN_A}", "alert details")
    assert "Traceback ... boom" in details

    assert await alerts.handle_reply(ADMIN_A, "unmute alerts") == ops_alerts.UNMUTED
    await alerts.send(_alert("k2"))
    assert ADMIN_A in [wa for wa, _ in sender.texts]


@pytest.mark.parametrize("text", ["mute", "mute 3h", "mute alerts", "MUTE ALERTS 24 hours"])
async def test_mute_forms(text: str) -> None:
    alerts = FixedAlerts(sender=FakeSender(), redis=FakeRedis())
    assert (await alerts.handle_reply(ADMIN_A, text)).startswith("🔕")


async def test_mute_is_capped_at_a_day() -> None:
    alerts = FixedAlerts(sender=FakeSender(), redis=FakeRedis())
    assert "24 h" in await alerts.handle_reply(ADMIN_A, "mute alerts 99h")


async def test_replies_only_for_super_admins_and_only_those_words() -> None:
    alerts = FixedAlerts(sender=FakeSender(), redis=FakeRedis())
    assert await alerts.handle_reply("919999999999", "alert details") is None
    assert await alerts.handle_reply(ADMIN_A, "10 masons today, mute the details") is None
    assert await alerts.handle_reply(ADMIN_A, "") is None


def _record(msg: str, *args, exc: BaseException | None = None, lineno: int = 10) -> logging.LogRecord:
    exc_info = (type(exc), exc, exc.__traceback__) if exc else None
    return logging.LogRecord("mesiri.dpr", logging.ERROR, "/x/dpr.py", lineno, msg, args, exc_info)


def test_alert_from_record_masks_numbers_and_groups_by_template() -> None:
    try:
        raise ValueError("bad row for 919876543210")
    except ValueError as exc:
        first = alert_from_record(_record("send failed wa_id=%s", "919876543210", exc=exc), "app")
        second = alert_from_record(_record("send failed wa_id=%s", "918888888888", exc=exc), "app")
    assert "919876543210" not in first.summary and "[number]" in first.summary
    assert "ValueError" in first.summary
    assert "919876543210" not in first.detail and "Traceback" in first.detail
    # Same place, same template, different number: the same error.
    assert first.key == second.key
    other_line = alert_from_record(_record("send failed wa_id=%s", "1", lineno=11), "app")
    assert other_line.key != first.key


class RecordingAlerts:
    service = "app"
    live = True

    def __init__(self) -> None:
        self.sent: list[Alert] = []
        self.tenants: list[Any] = []

    async def send(self, alert: Alert) -> int:
        self.tenants.append(current_tenant())
        # A failure while sending is logged, and must not alert again.
        logging.getLogger("mesiri.whatsapp").error("send failed while alerting")
        self.sent.append(alert)
        return 1


async def test_handler_sends_errors_in_the_background_without_the_company() -> None:
    alerts = RecordingAlerts()
    handler = OpsAlertLogHandler(alerts)  # type: ignore[arg-type]
    log = logging.getLogger("mesiri.test_ops_alerts")
    log.addHandler(handler)
    try:
        with tenant_scope("6f1c1a62-3d4c-4f0a-9a43-2b1f4c2e9d11"):
            for project in ("Skyline", "Other"):  # the same error twice: one alert
                log.error("dpr.render_failed project=%s", project)
            log.warning("just a warning")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        log.removeHandler(handler)
    assert [a.summary for a in alerts.sent] == ["dpr.render_failed project=Skyline"]
    assert alerts.tenants == [None]


async def test_handler_ignores_its_own_loggers() -> None:
    alerts = RecordingAlerts()
    handler = OpsAlertLogHandler(alerts)  # type: ignore[arg-type]
    handler.emit(logging.LogRecord("mesiri.ops_alerts", logging.ERROR, "x", 1, "loop", (), None))
    await asyncio.sleep(0)
    assert alerts.sent == []


def test_install_needs_real_redis_and_honours_the_kill_switch(monkeypatch) -> None:
    root = logging.getLogger()
    alerts = FixedAlerts(sender=FakeSender(), redis=FakeRedis())
    try:
        alerts.live = False
        assert install_ops_alerts(alerts, "app") is None
        alerts.live = True
        monkeypatch.setenv("MESIRI_OPS_ALERTS", "off")
        assert install_ops_alerts(alerts, "app") is None
        monkeypatch.delenv("MESIRI_OPS_ALERTS")
        first = install_ops_alerts(alerts, "worker")
        second = install_ops_alerts(alerts, "worker")
        assert first is not None and second is not None
        assert [h for h in root.handlers if isinstance(h, OpsAlertLogHandler)] == [second]
        assert alerts.service == "worker"
    finally:
        install_ops_alerts(None, "app")
    assert not any(isinstance(h, OpsAlertLogHandler) for h in root.handlers)


# -- who gets them: platform admins' numbers + the setting's ----------------


class _Result:
    def __init__(self, *, first=None, scalars=()) -> None:
        self._first, self._scalars = first, scalars

    def first(self):
        return self._first

    def scalars(self):
        return iter(self._scalars)


class _Conn:
    def __init__(self, setting_row, admin_numbers) -> None:
        self._setting_row, self._admin_numbers = setting_row, admin_numbers
        self.sql: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.sql.append(sql)
        if "platform_settings" in sql:
            return _Result(first=self._setting_row)
        return _Result(scalars=self._admin_numbers)


class _Db:
    def __init__(self, conn) -> None:
        self.conn = conn
        self.tenants: list[Any] = []

    @asynccontextmanager
    async def transaction(self):
        self.tenants.append(current_tenant())
        yield self.conn


async def test_recipients_are_platform_admins_plus_the_setting() -> None:
    class Row:
        value = {"numbers": ["919000000003", ADMIN_A]}

    db = _Db(_Conn(Row(), ["+91 90000 00001", None, "919000000002"]))
    alerts = OpsAlerts(sender=FakeSender(), db=db, redis=FakeRedis())
    with tenant_scope("6f1c1a62-3d4c-4f0a-9a43-2b1f4c2e9d11"):
        setting, recipients = await alerts._settings_and_recipients()
    assert recipients == {ADMIN_A, ADMIN_B, "919000000003"}
    assert setting["enabled"] is True
    assert db.tenants == [None]  # looked up with no company bound
    assert "organization_id IS NULL" in db.conn.sql[1]
    # Cached for a minute.
    await alerts._settings_and_recipients()
    assert len(db.tenants) == 1


# -- the platform setting ------------------------------------------------------


def test_setting_normalizes_numbers() -> None:
    stored = spec.validate(spec.OPS_ALERTS, {"numbers": ["98765 43210", "+91-98765-43210", "447700900123"]})
    assert stored["numbers"] == ["447700900123", "919876543210"]
    assert stored["enabled"] is True and stored["team_group_fallback"] is True


@pytest.mark.parametrize(
    "value",
    [{"numbers": ["123"]}, {"numbers": "919876543210"}, {"enabled": "yes"}, {"recipients": []}],
)
def test_setting_rejects_bad_values(value) -> None:
    with pytest.raises(ValueError):
        spec.validate(spec.OPS_ALERTS, value)


# -- wiring: the real message handler and the AI provider alert ---------------


async def test_the_message_handler_answers_alert_words_before_anything_else() -> None:
    import httpx

    from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
    from runtime.dependencies import Settings, build_container

    settings = Settings(verify_token="v", app_secret="s", access_token="a")
    async with httpx.AsyncClient(timeout=5.0) as http_client:
        container = build_container(settings, http_client)
    assert isinstance(container.ops_alerts, OpsAlerts)
    assert container.ops_alerts.live is False  # in-memory Redis: never sends

    async def fixed():
        return dict(spec.DEFAULT_OPS_ALERTS), frozenset({ADMIN_A})

    container.ops_alerts._settings_and_recipients = fixed  # type: ignore[method-assign]

    class _Sender(FakeSender):
        def __getattr__(self, _name: str):
            async def _quiet(*args: Any, **kwargs: Any) -> bool:
                return True

            return _quiet

    sender = _Sender()
    handler = container.simulate_handler(sender)
    message = NormalizedMessage(
        message_id="wamid.1",
        sender=SenderInfo(wa_id=ADMIN_A, phone_number=ADMIN_A),
        timestamp=NOW,
        modality="text",
        text="mute alerts 3h",
    )
    await handler(message, {})
    assert sender.texts and sender.texts[0][0] == ADMIN_A
    assert sender.texts[0][1].startswith("🔕") and "3 h" in sender.texts[0][1]


async def test_ai_provider_alert_reaches_the_super_admins(monkeypatch) -> None:
    from mesiri_ai.core.errors import AUTH_OR_QUOTA_ERROR_CODE
    from mesiri_ai.core.failures import ProviderFailure
    from runtime.ai_failure_alert import AIFailureAlerter

    monkeypatch.delenv("MESIRI_OPS_ALERTS", raising=False)
    sender = FakeSender()
    alerts = FixedAlerts(sender=sender, redis=FakeRedis(), recipients=(ADMIN_A,))
    failure = ProviderFailure("deepseek", "extract", AUTH_OR_QUOTA_ERROR_CODE, status_code=402)
    await AIFailureAlerter(None, alerts).on_failure(failure)
    assert len(sender.texts) == 1 and "402" in sender.texts[0][1]

    alerts.live = False  # tests / local dev
    await AIFailureAlerter(None, alerts).on_failure(failure)
    assert len(sender.texts) == 1


class _DownRedis(FakeRedis):
    async def set_if_absent(self, *args: Any, **kwargs: Any) -> bool:
        raise ConnectionError("redis down")

    async def get_json(self, *args: Any, **kwargs: Any):
        raise ConnectionError("redis down")


async def test_redis_down_still_alerts() -> None:
    sender = FakeSender()
    alerts = FixedAlerts(sender=sender, redis=_DownRedis(), recipients=(ADMIN_A,))
    assert await alerts.send(_alert()) == 1


async def test_database_down_uses_the_last_numbers_or_the_team_group() -> None:
    class _DownDb:
        def transaction(self):
            raise ConnectionError("postgres down")

    sender, team = FakeSender(), FakeTeam()
    alerts = OpsAlerts(sender=sender, db=_DownDb(), redis=FakeRedis(), team_notifier=team)
    assert await alerts.send(_alert("k1")) == 0
    assert len(team.posts) == 1  # never knew the numbers: the team group

    alerts._cached = (-1e9, dict(spec.DEFAULT_OPS_ALERTS), frozenset({ADMIN_A}))
    assert await alerts.send(_alert("k2")) == 1
    assert [wa for wa, _ in sender.texts] == [ADMIN_A]
