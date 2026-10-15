"""Material domain validation (M8) — pure functions, no I/O, no SQL.

Uses only fields the schema actually has. No unit-of-measure conversion, no
stock/balance check (materials_catalog intentionally has no balance table
yet — see migration 0180's docstring). Runs in the Application Handler
*before* any transaction opens (validation needs no connection at all).
"""

from __future__ import annotations

from mesiri_contracts.application.commands.material import (
    RecordMaterialReceiptCommand,
    RecordMaterialUsageCommand,
)


def validate_receipt(cmd: RecordMaterialReceiptCommand) -> list[str]:
    """Return violation reasons; empty list means valid."""
    reasons: list[str] = []
    if cmd.project_id is None:
        reasons.append("project is not resolved")
    if cmd.quantity <= 0:
        reasons.append("quantity must be positive")
    if not cmd.material_name.strip():
        reasons.append("material_name is required")
    if not cmd.unit.strip():
        reasons.append("unit is required")
    return reasons


def validate_usage(cmd: RecordMaterialUsageCommand) -> list[str]:
    """Return violation reasons; empty list means valid."""
    reasons: list[str] = []
    if cmd.project_id is None:
        reasons.append("project is not resolved")
    if cmd.quantity <= 0:
        reasons.append("quantity must be positive")
    if not cmd.material_name.strip():
        reasons.append("material_name is required")
    if not cmd.unit.strip():
        reasons.append("unit is required")
    return reasons


def validate(cmd: RecordMaterialReceiptCommand | RecordMaterialUsageCommand) -> list[str]:
    """Single dispatch entry point the Handler calls — before any transaction opens."""
    if isinstance(cmd, RecordMaterialReceiptCommand):
        return validate_receipt(cmd)
    return validate_usage(cmd)


# ---------------------------------------------------------------------------
# Movement reason rules (dashboard Materials surface — direct web writes)
# ---------------------------------------------------------------------------
# OPENING_STOCK (BE-12): what was already on site when it started using
# Mesiri, entered once per site+material by an elevated role.
OPENING_STOCK = "OPENING_STOCK"
RECEIPT_REASONS = ("RECEIVED", "TRANSFER_IN", "RETURN_IN", "ADJUSTMENT_IN", OPENING_STOCK)
USAGE_REASONS = ("CONSUMED", "TRANSFER_OUT", "RETURN_TO_VENDOR", "WASTAGE", "ADJUSTMENT_OUT")
ADJUSTMENT_REASONS = ("ADJUSTMENT_IN", "ADJUSTMENT_OUT")
# Reasons only ADJUSTMENT_ROLES may record: they change stock without a
# delivery or a use behind them.
ELEVATED_REASONS = (*ADJUSTMENT_REASONS, OPENING_STOCK)
ADJUSTMENT_ROLES = ("ADMIN", "PROJECT_MANAGER")


def is_valid_receipt_reason(reason: str) -> bool:
    return reason in RECEIPT_REASONS


def is_valid_usage_reason(reason: str) -> bool:
    return reason in USAGE_REASONS


def role_can_adjust(role: str) -> bool:
    """Corrections/adjustments are restricted to elevated roles."""
    return role.upper() in ADJUSTMENT_ROLES
