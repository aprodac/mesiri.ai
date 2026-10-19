"""Sample receipts for every type -- shared by the receipt unit tests and by
scripts/render_receipt_samples.py (which renders them to PNGs to look at)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from channel.receipt.data import ReceiptData, build_receipt_data, combine_receipts
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"
WHEN = datetime(2026, 10, 19, 10, 57, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Named:
    id: str
    name: str


def receipt(
    action_type: DraftActionType,
    fields: dict,
    *,
    project: str = "Riverside Tower",
    site: str = "Block A",
    reporter: str | None = "Mohammed",
    row_id: str = "abcd1234-0000",
    late_entry: bool = False,
) -> ReceiptData:
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
    return build_receipt_data(
        draft,
        record_row_id=row_id,
        reporter_name=reporter,
        projects=[Named(PRJ, project)],
        sites=[Named(SITE, site)],
        confirmed_at=WHEN,
        late_entry=late_entry,
    )


def labour(trades: list[tuple[str, int]], **kw) -> ReceiptData:
    lines = [{"worker_name": None, "trade": t, "headcount": n} for t, n in trades]
    return receipt(DraftActionType.RECORD_LABOUR_ATTENDANCE, {"lines": lines}, **kw)


FIVE_TRADES = [("mason", 6), ("helper", 12), ("bar_bender", 4), ("carpenter", 3), ("electrician", 2)]
SEVEN_TRADES = [*FIVE_TRADES, ("plumber", 2), ("painter", 5)]

MATERIAL_IN = (
    DraftActionType.RECORD_MATERIAL_RECEIPT,
    {"material_name": "cement", "quantity": 50, "unit": "bags", "supplier": "UltraTech"},
)
MATERIAL_USED = (
    DraftActionType.RECORD_MATERIAL_USAGE,
    {"material_name": "cement", "quantity": 18, "unit": "bags", "work_item": "Slab casting"},
)
EXPENSE = (
    DraftActionType.RECORD_EXPENSE,
    {"amount": "4500", "category": "transport", "description": "Tipper hire for debris"},
)
ISSUE = (
    DraftActionType.RECORD_SITE_ISSUE,
    {"issue_type": "MATERIAL_SHORTAGE", "severity": "HIGH", "narrative": "Out of 8mm bars"},
)
ACTIVITY = (
    DraftActionType.CREATE_ACTIVITY,
    {"work_type": "plastering", "narrative": "Third floor plastering done", "contractor": "ABC Co"},
)
ACTIVITY_QTY = (
    DraftActionType.CREATE_ACTIVITY,
    {"work_type": "shuttering", "quantity": 120, "unit": "sqm", "contractor": "Biju & Sons"},
)
CORRECTION = (
    DraftActionType.CORRECT_ACTIVITY_QUANTITY,
    {
        "old_quantity": 120,
        "old_unit": "sqm",
        "new_quantity": 150,
        "unit": "sqm",
        "correction_activity_summary": "Shuttering, 2nd floor slab",
    },
)
UNDO = (
    DraftActionType.REVERSE_TRANSACTION,
    {
        "target_kind": "activity",
        "reversal_activity_summary": "Plastering, 3rd floor",
        "reversal_occurred_date": "2026-10-19",
    },
)
MALAYALAM = (
    DraftActionType.RECORD_MATERIAL_USAGE,
    {"material_name": "സിമന്റ്", "quantity": 12, "unit": "ബാഗ്", "work_item": "സ്ലാബ് വാർപ്പ്"},
)
LONG = (
    DraftActionType.RECORD_SITE_ISSUE,
    {
        "issue_type": "WATER_LEAKAGE",
        "severity": "MEDIUM",
        "narrative": "Water is leaking through the second floor shuttering joints near the "
        "staircase core wall, and the curing pipe on the east side has also burst",
    },
)


def part_rows(n: int) -> list[ReceiptData]:
    """n saved parts of one note, cycling through the record types."""
    makers = [
        lambda: labour(FIVE_TRADES),
        lambda: receipt(*MATERIAL_IN),
        lambda: receipt(*MATERIAL_USED),
        lambda: receipt(*ACTIVITY_QTY),
        lambda: receipt(*ISSUE),
        lambda: receipt(*EXPENSE),
    ]
    return [makers[i % len(makers)]() for i in range(n)]


def multi(n: int) -> ReceiptData:
    return combine_receipts(part_rows(n))


def all_samples() -> dict[str, ReceiptData]:
    return {
        "labour_5_trades": labour(FIVE_TRADES),
        "labour_7_trades": labour(SEVEN_TRADES),
        "labour_1_trade": labour([("mason", 4)]),
        "material_in": receipt(*MATERIAL_IN),
        "material_used": receipt(*MATERIAL_USED),
        "expense": receipt(*EXPENSE),
        "issue": receipt(*ISSUE),
        "activity": receipt(*ACTIVITY),
        "activity_qty": receipt(*ACTIVITY_QTY),
        "correction": receipt(*CORRECTION),
        "undo": receipt(*UNDO),
        "late_entry": receipt(*MATERIAL_IN, late_entry=True),
        "malayalam": receipt(*MALAYALAM, site="ബ്ലോക്ക് എ", project="റിവർസൈഡ് ടവർ", reporter="മുഹമ്മദ്"),
        "long_names": receipt(*LONG, project="Riverside Tower Phase Two Residential Complex", site="Block A North Wing Podium Level"),
        "multi_3": multi(3),
        "multi_6": multi(6),
        "multi_12": multi(12),
    }
