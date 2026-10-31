"""ConfirmedActionV2 -> Material command mapping — unit tests (pure, no I/O)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from mesiri.application.materials.mapper import build_command
from mesiri_contracts.application.commands.material import (
    RecordMaterialReceiptCommand,
    RecordMaterialUsageCommand,
)
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

ORG = "11111111-1111-4111-8111-111111111111"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"
USR = "22222222-2222-4222-8222-222222222222"


def _confirmed(action_type: DraftActionType, fields: dict) -> ConfirmedActionV2:
    draft = DraftActionV2(
        draft_id="draft_1",
        correlation_id="cor_1",
        workflow_instance_id="wf_1",
        action_type=action_type,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
        fields=fields,
    )
    return ConfirmedActionV2(
        confirmed_action_id="conf_1",
        workflow_instance_id="wf_1",
        correlation_id="cor_1",
        draft_action=draft,
        confirmed_by_user_id=USR,
    )


def test_maps_receipt_action_type_to_receipt_command():
    confirmed = _confirmed(
        DraftActionType.RECORD_MATERIAL_RECEIPT,
        {"material_name": "cement", "quantity": 20, "unit": "bags", "direction": "received"},
    )
    cmd = build_command(confirmed)
    assert isinstance(cmd, RecordMaterialReceiptCommand)
    assert cmd.material_name == "cement"
    assert cmd.quantity == Decimal("20")
    assert cmd.unit == "bags"


def test_maps_usage_action_type_to_usage_command():
    confirmed = _confirmed(
        DraftActionType.RECORD_MATERIAL_USAGE,
        {"material_name": "sand", "quantity": 5, "unit": "tons", "direction": "used"},
    )
    cmd = build_command(confirmed)
    assert isinstance(cmd, RecordMaterialUsageCommand)
    assert cmd.material_name == "sand"
    assert cmd.quantity == Decimal("5")


def test_idempotency_key_is_workflow_instance_id_not_confirmed_action_id():
    confirmed = _confirmed(
        DraftActionType.RECORD_MATERIAL_RECEIPT,
        {"material_name": "cement", "quantity": 20, "unit": "bags"},
    )
    cmd = build_command(confirmed)
    assert cmd.idempotency_key == "wf_1"
    assert cmd.idempotency_key != confirmed.confirmed_action_id


def test_scope_denormalized_from_draft_action():
    confirmed = _confirmed(
        DraftActionType.RECORD_MATERIAL_RECEIPT,
        {"material_name": "cement", "quantity": 20, "unit": "bags"},
    )
    cmd = build_command(confirmed)
    assert cmd.organization_id == ORG
    assert cmd.project_id == PRJ
    assert cmd.site_id == SITE
    assert cmd.created_by == USR


def test_project_id_none_is_preserved_not_invented():
    """Domain validation rejects a missing project_id; the mapper must never
    invent one (Flaw 1 in the M8 plan)."""
    draft = DraftActionV2(
        draft_id="draft_1",
        correlation_id="cor_1",
        workflow_instance_id="wf_1",
        action_type=DraftActionType.RECORD_MATERIAL_RECEIPT,
        organization_id=ORG,
        user_id=USR,
        project_id=None,
        fields={"material_name": "cement", "quantity": 20, "unit": "bags"},
    )
    confirmed = ConfirmedActionV2(
        confirmed_action_id="conf_1",
        workflow_instance_id="wf_1",
        correlation_id="cor_1",
        draft_action=draft,
        confirmed_by_user_id=USR,
    )
    cmd = build_command(confirmed)
    assert cmd.project_id is None


def test_the_date_decided_upstream_is_used_not_overwritten():
    """STA-166: the mapper used to stamp date.today() over whatever the
    message said, so "cement delivered yesterday" was filed under today.
    Canonicalization now owns the decision -- it is the only point holding
    both the message and the sender's timezone (see
    canonicalization/occurred_date.py)."""
    confirmed = _confirmed(
        DraftActionType.RECORD_MATERIAL_RECEIPT,
        {
            "material_name": "cement",
            "quantity": 20,
            "unit": "bags",
            "occurred_date": "2026-07-20",
            "occurred_date_source": "stated_by_user",
        },
    )
    cmd = build_command(confirmed)
    assert cmd.occurred_date == date(2026, 7, 20)
    assert cmd.occurred_date_source == "stated_by_user"


def test_occurred_date_defaults_to_today_when_a_draft_predates_dating():
    """An older draft, persisted at AWAITING_CONFIRMATION before this
    shipped, must stay confirmable rather than failing on a field it never
    carried."""
    confirmed = _confirmed(
        DraftActionType.RECORD_MATERIAL_RECEIPT,
        {"material_name": "cement", "quantity": 20, "unit": "bags"},
    )
    cmd = build_command(confirmed)
    assert cmd.occurred_date == date.today()
    assert cmd.occurred_date_source == "inferred_at_confirmation"


def test_a_corrupt_stored_date_falls_back_rather_than_failing_the_save():
    confirmed = _confirmed(
        DraftActionType.RECORD_MATERIAL_RECEIPT,
        {"material_name": "cement", "quantity": 20, "unit": "bags", "occurred_date": "not-a-date"},
    )
    cmd = build_command(confirmed)
    assert cmd.occurred_date == date.today()


def test_missing_quantity_coerces_to_zero_not_a_crash():
    confirmed = _confirmed(
        DraftActionType.RECORD_MATERIAL_RECEIPT,
        {"material_name": "cement", "unit": "bags"},  # no quantity field at all
    )
    cmd = build_command(confirmed)
    assert cmd.quantity == Decimal("0")  # will be caught by Domain validation, not the mapper


def test_stock_count_adjustment_keeps_its_reason_and_note_on_both_sides():
    """Request 171: a stock count is an adjustment with a reason, never a fake 'used'."""
    down = build_command(
        _confirmed(
            DraftActionType.RECORD_MATERIAL_USAGE,
            {
                "material_name": "cement",
                "quantity": 176,
                "unit": "bags",
                "movement_reason": "ADJUSTMENT_OUT",
                "notes": "Stock count: records 176, counted 0",
            },
        )
    )
    assert isinstance(down, RecordMaterialUsageCommand)
    assert (down.movement_reason, down.notes) == ("ADJUSTMENT_OUT", "Stock count: records 176, counted 0")
    up = build_command(
        _confirmed(
            DraftActionType.RECORD_MATERIAL_RECEIPT,
            {"material_name": "cement", "quantity": 5, "unit": "bags", "movement_reason": "ADJUSTMENT_IN", "notes": "n"},
        )
    )
    assert isinstance(up, RecordMaterialReceiptCommand)
    assert (up.movement_reason, up.notes) == ("ADJUSTMENT_IN", "n")


def test_ordinary_usage_has_no_reason_so_it_stays_consumed():
    cmd = build_command(
        _confirmed(DraftActionType.RECORD_MATERIAL_USAGE, {"material_name": "sand", "quantity": 5, "unit": "tons"})
    )
    assert cmd.movement_reason is None and cmd.notes is None
