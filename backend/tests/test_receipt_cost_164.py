"""Request 164: a delivery's cost travels from the card fields to the receipt command."""

from decimal import Decimal

from mesiri_contracts.application.commands.material import RecordMaterialReceiptCommand


def test_receipt_command_cost_is_optional_and_additive():
    fields = RecordMaterialReceiptCommand.model_fields
    assert fields["total_cost"].default is None and fields["unit_cost"].default is None


def test_receipt_command_carries_cost():
    cmd = RecordMaterialReceiptCommand(
        command_id="c", idempotency_key="k", correlation_id="x", organization_id="11111111-1111-1111-1111-111111111111",
        project_id=None, site_id=None, material_name="Cement", quantity=Decimal(100), unit="bags",
        occurred_date="2026-10-31", created_by="22222222-2222-2222-2222-222222222222", total_cost=Decimal(10000),
    )
    assert cmd.total_cost == Decimal(10000)
