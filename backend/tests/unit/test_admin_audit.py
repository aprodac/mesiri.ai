"""BE-05: the superadmin audit log's rules (no database)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from mesiri.application.audit.record import record_admin_action
from mesiri.domains.audit import actions as audit


def test_actor_from_admin_reads_the_jwt_claims() -> None:
    admin_id = uuid.uuid4()
    actor = audit.actor_from_admin({"sub": str(admin_id), "name": " Priya ", "org": ""})
    assert actor == audit.AuditActor(kind="platform_admin", user_id=admin_id, label="Priya")


@pytest.mark.parametrize("payload", [{}, None, {"sub": "not-a-uuid"}, {"sub": None}])
def test_actor_from_admin_tolerates_missing_claims(payload) -> None:
    actor = audit.actor_from_admin(payload)
    assert actor.kind == "platform_admin"
    assert actor.user_id is None


def test_secrets_are_never_stored_at_any_depth() -> None:
    cleaned = audit.redact(
        {
            "before": {"full_name": "A"},
            "after": {"hashed_password": "$2b$...", "full_name": "B"},
            "providers": [{"api_key": "sk-live-123", "base_url": "https://x"}],
            "password": None,
        }
    )
    assert cleaned == {
        "before": {"full_name": "A"},
        "after": {"hashed_password": "[changed]", "full_name": "B"},
        "providers": [{"api_key": "[changed]", "base_url": "https://x"}],
        # Nothing was set, so nothing to hide.
        "password": None,
    }


def test_ids_and_dates_become_json() -> None:
    some_id = uuid.uuid4()
    when = dt.datetime(2026, 10, 15, tzinfo=dt.UTC)
    assert audit.redact({"id": some_id, "at": when, "day": when.date()}) == {
        "id": str(some_id),
        "at": "2026-10-15T00:00:00+00:00",
        "day": "2026-10-15",
    }


def test_trial_control_actions_are_ready_for_ss10() -> None:
    for action in (
        "company.trial_extended",
        "company.converted",
        "company.suspended",
        "company.reactivated",
        "platform_setting.changed",
    ):
        assert action in audit.ACTIONS


class _Conn:
    def __init__(self) -> None:
        self.executed: list = []

    async def execute(self, statement):
        self.executed.append(statement)


async def test_record_writes_one_redacted_row() -> None:
    conn = _Conn()
    org_id = uuid.uuid4()
    entry = await record_admin_action(
        conn,
        actor=audit.AuditActor(kind="platform_admin", label="Priya"),
        action=audit.COMPANY_SUSPENDED,
        organization_id=org_id,
        target_type="organization",
        target_id=org_id,
        summary="Suspended",
        details={"after": {"status": "suspended", "password": "x"}},
    )
    assert len(conn.executed) == 1
    params = conn.executed[0].compile().params
    assert params["action"] == "company.suspended"
    assert params["target_id"] == str(org_id)
    assert params["details"] == {"after": {"status": "suspended", "password": "[changed]"}}
    assert entry.actor_label == "Priya"


@pytest.mark.parametrize(
    ("action", "kind"),
    [("company.renamed_typo", "platform_admin"), ("company.created", "robot")],
)
async def test_unknown_action_or_actor_is_refused_before_writing(action, kind) -> None:
    conn = _Conn()
    with pytest.raises(ValueError, match="unknown audit"):
        await record_admin_action(conn, actor=audit.AuditActor(kind=kind), action=action)
    assert conn.executed == []
