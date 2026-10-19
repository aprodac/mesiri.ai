"""Maps a confirmed record into the receipt-card data shape.

Pure, no I/O -- one branch per DraftActionType, all producing the same
generic shape: a hero (a number and unit, or a title when the record has no
number), a site/date line, and rows. template.py decides how it looks; this
file decides what goes on it.

Every record has a ``ReceiptKind`` -- the colour *and* shape it is drawn with
(work ■ green, labour ● blue, material in ▲ / used ▼ amber, issue ◆ red,
expense ▬ purple), so a card is recognisable at a glance and still readable
without colour. Several records of one message are folded into one card by
``combine_receipts`` (one row each).

Field labels are display concerns, not business logic -- adding a new
DraftActionType means adding a case here, never touching the domain layer or
the template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from trade_label import trade_label

#: Rows shown at full size; a card with more shows MAX_ROWS - 1 and "+N more".
MAX_ROWS = 10
#: Label/value rows on a single-record card.
MAX_DETAIL_ROWS = 6

STATUS_SAVED = "SAVED"
STATUS_DRAFT = "SAVED · DRAFT"
STATUS_UNDONE = "UNDONE"
STATUS_LATE = "LATE ENTRY"

FOOTER_DRAFT = "Confirm with tonight's report"
FOOTER_UNDONE = "Not in tonight's report"
FOOTER_LATE = "Late entry: shows in your next report"


class ReceiptKind(str, Enum):  # noqa: UP042 -- matches the rest of the codebase
    WORK = "work"
    LABOUR = "labour"
    MATERIAL_IN = "material_in"
    MATERIAL_USED = "material_used"
    ISSUE = "issue"
    EXPENSE = "expense"
    UNDONE = "undone"
    #: Setup/admin records (account, project, site, member) and anything uncased.
    RECORD = "record"


@dataclass(frozen=True, slots=True)
class KindStyle:
    colour: str
    shape: str  # square | circle | up | down | diamond | bar | ring


KIND_STYLE: dict[ReceiptKind, KindStyle] = {
    ReceiptKind.WORK: KindStyle("#0A8F4C", "square"),
    ReceiptKind.LABOUR: KindStyle("#2563EB", "circle"),
    ReceiptKind.MATERIAL_IN: KindStyle("#D97706", "up"),
    ReceiptKind.MATERIAL_USED: KindStyle("#D97706", "down"),
    ReceiptKind.ISSUE: KindStyle("#DC2626", "diamond"),
    ReceiptKind.EXPENSE: KindStyle("#7C3AED", "bar"),
    ReceiptKind.UNDONE: KindStyle("#6B7280", "ring"),
    ReceiptKind.RECORD: KindStyle("#1D1D1F", "ring"),
}

#: Short uppercase tag shown on a row of a multi-part card.
KIND_TAG: dict[ReceiptKind, str] = {
    ReceiptKind.WORK: "WORK",
    ReceiptKind.LABOUR: "LABOUR",
    ReceiptKind.MATERIAL_IN: "MATERIAL IN",
    ReceiptKind.MATERIAL_USED: "MATERIAL USED",
    ReceiptKind.ISSUE: "ISSUE",
    ReceiptKind.EXPENSE: "EXPENSE",
    ReceiptKind.UNDONE: "UNDONE",
    ReceiptKind.RECORD: "RECORD",
}


@dataclass(frozen=True, slots=True)
class ReceiptRow:
    """One line of the card: marker | TAG | text | right-aligned value."""

    kind: ReceiptKind
    tag: str
    text: str
    value: str = ""
    emphasis: bool = False  # value in the record's colour


@dataclass(frozen=True, slots=True)
class ReceiptTrade:
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class ReceiptCorrection:
    """Old -> new value for a quantity edit: old struck through in grey."""

    old_value: str
    new_value: str


@dataclass(frozen=True, slots=True)
class ReceiptData:
    kind: ReceiptKind
    category: str
    status: str
    site_line: str
    meta_line: str
    record_id: str
    footer_note: str
    # Hero: a number (+ unit), or -- for a record with no number -- a title.
    hero_number: str = ""
    hero_unit: str = ""
    hero_title: str = ""
    hero_status: str = ""  # e.g. "Open", drawn in the record's colour
    rows: list[ReceiptRow] = field(default_factory=list)
    more: int = 0  # rows/trades saved but not drawn
    trades: list[ReceiptTrade] = field(default_factory=list)
    correction: ReceiptCorrection | None = None
    #: This record as one line of a combined card (see combine_receipts).
    summary: ReceiptRow | None = None


def _project_name(project_id: str | None, projects: list[Any]) -> str | None:
    if not project_id:
        return None
    return next((p.name for p in projects if p.id == project_id), None)


def _site_name(site_id: str | None, sites: list[Any]) -> str | None:
    if not site_id:
        return None
    return next((s.name for s in sites if s.id == site_id), None)


def _fmt_quantity(fields: dict) -> str:
    quantity = fields.get("quantity", "")
    unit = fields.get("unit", "")
    return f"{quantity} {unit}".strip()


def _labour_trades(fields: dict) -> tuple[list[ReceiptTrade], int, int]:
    """Per-trade headcount, the total, and how many people were named.

    Attendance is the one record type whose value is a *list*, not a single
    quantity, so the receipt has to summarise rather than echo a field. Trades
    are merged but kept in the order reported, so the card reads the way the
    supervisor wrote it.
    """
    raw = fields.get("lines")
    lines = [line for line in raw if isinstance(line, dict)] if isinstance(raw, list) else []
    counts: dict[str, int] = {}
    headcount = 0
    named = 0
    for line in lines:
        try:
            count = int(line.get("headcount", 1))
        except (TypeError, ValueError):
            count = 1
        headcount += count
        if str(line.get("worker_name") or "").strip():
            named += 1
        trade = trade_label(line.get("trade")) or "Workers"
        counts[trade] = counts.get(trade, 0) + count
    return [ReceiptTrade(name, count) for name, count in counts.items()], headcount, named


def _labour_people(headcount: int, named: int) -> str:
    """How the headcount breaks down between named people and counted groups —
    the distinction principle P10 exists to preserve, so it belongs on the
    record the user keeps."""
    if not headcount:
        return ""
    if named == 0:
        return f"{headcount} by headcount"
    if named == headcount:
        return f"{headcount} named"
    return f"{named} named, {headcount - named} by headcount"


def _progress_percent(fields: dict) -> str:
    """"40%" when the record states how much is done, else ""."""
    raw = _present(fields.get("progress_percent"))
    if not raw:
        return ""
    try:
        pct = float(raw.rstrip("%"))
    except ValueError:
        return ""
    return f"{int(pct)}%" if pct.is_integer() else f"{pct:g}%"


def _work_line(work_type: str, fields: dict, pct: str) -> str:
    """"Plastering · 2nd floor · 40%": what was done, where, how far."""
    return " · ".join(p for p in (work_type, _present(fields.get("location")), pct) if p)


def _present(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    return "" if text in ("—", "-", "None") else text


def _rows(kind: ReceiptKind, *pairs: tuple[str, Any]) -> list[ReceiptRow]:
    """Label/value rows for a single-record card; empty values are dropped."""
    out = [ReceiptRow(kind, label, _present(value)) for label, value in pairs if _present(value)]
    return out[:MAX_DETAIL_ROWS]


_DRAFT_TYPES = frozenset(
    {
        DraftActionType.CREATE_ACTIVITY,
        DraftActionType.ADD_PROGRESS_UPDATE,
        DraftActionType.RECORD_LABOUR_ATTENDANCE,
        DraftActionType.RECORD_MATERIAL_RECEIPT,
        DraftActionType.RECORD_MATERIAL_USAGE,
        DraftActionType.RECORD_SITE_ISSUE,
    }
)


def _status_word(close_action: str) -> str:
    return {"resolve": "Resolved", "close": "Closed"}.get(close_action, close_action.title())


def company_zone(name: str | None) -> tzinfo:
    """The company's timezone (organizations.timezone), India by default and
    on any unknown name -- the same fallback as runtime/setup_questions.py."""
    try:
        return ZoneInfo(name or "Asia/Kolkata")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Kolkata")


def build_receipt_data(
    draft: DraftActionV2,
    *,
    record_row_id: str,
    reporter_name: str | None,
    projects: list[Any],
    sites: list[Any],
    confirmed_at: datetime,
    late_entry: bool = False,
    timezone: str | None = None,
) -> ReceiptData:
    """Build the generic receipt shape for a confirmed DraftAction.

    ``record_row_id`` comes from ExecutionResult, not the draft -- it is the
    real persisted row id, so the receipt's record id points at a row that
    actually exists. Named for materials on the contract
    (``ExecutionResult.material_row_id``) because materials came first; it
    now carries the expense, transfer, petty-cash and labour ids too.
    """
    # The instant is UTC; the card shows the company's clock and calendar
    # day (record id, date and time) -- converted here, once.
    confirmed_at = confirmed_at.astimezone(company_zone(timezone))
    fields = draft.fields
    material_name = str(fields.get("material_name", "")).strip() or "Material"
    project_name = _project_name(draft.project_id, projects)
    site_name = _site_name(draft.site_id, sites)
    reporter = reporter_name or ""

    # Defaults every branch below overrides as needed.
    kind = ReceiptKind.RECORD
    hero_number = hero_unit = hero_title = hero_status = ""
    rows: list[ReceiptRow] = []
    trades: list[ReceiptTrade] = []
    correction: ReceiptCorrection | None = None
    summary_tag = summary_text = summary_value = ""

    if draft.action_type is DraftActionType.RECORD_EXPENSE:
        expense_category = str(fields.get("category", "")).strip() or "Uncategorized"
        kind = ReceiptKind.EXPENSE
        category = "Expense"
        hero_number = f"₹{str(fields.get('amount', '')).strip() or '0'}"
        rows = _rows(kind, ("Category", expense_category.title()), ("Description", fields.get("description")))
        id_prefix = "EX"
        summary_text = str(fields.get("description") or expense_category.title())
        summary_value = hero_number
    elif draft.action_type is DraftActionType.RECORD_MATERIAL_RECEIPT:
        kind = ReceiptKind.MATERIAL_IN
        category = "Material received"
        hero_number, hero_unit = str(fields.get("quantity", "")).strip(), str(fields.get("unit", "")).strip()
        rows = _rows(kind, ("Material", material_name.title()), ("Supplier", fields.get("supplier")))
        id_prefix = "MR"
        summary_text, summary_value = material_name.title(), _fmt_quantity(fields)
    elif draft.action_type is DraftActionType.RECORD_MATERIAL_USAGE:
        kind = ReceiptKind.MATERIAL_USED
        category = "Material used"
        hero_number, hero_unit = str(fields.get("quantity", "")).strip(), str(fields.get("unit", "")).strip()
        rows = _rows(kind, ("Material", material_name.title()), ("Used for", fields.get("work_item")))
        id_prefix = "MU"
        summary_text, summary_value = material_name.title(), _fmt_quantity(fields)
    elif draft.action_type is DraftActionType.RECORD_LABOUR_ATTENDANCE:
        trades, headcount, named = _labour_trades(fields)
        kind = ReceiptKind.LABOUR
        category = "Labour attendance"
        hero_number = str(headcount)
        hero_unit = "worker" if headcount == 1 else "workers"
        rows = _rows(kind, ("People", _labour_people(headcount, named) if named else ""))
        id_prefix = "LA"
        summary_text = ", ".join(t.name for t in trades[:3]) + (" …" if len(trades) > 3 else "")
        summary_value = f"{headcount} {hero_unit}"
    elif draft.action_type is DraftActionType.TRANSFER_MONEY:
        # Petty cash issue/return (Finance Slice 5) emits this same
        # DraftActionType as a plain transfer -- `direction` (only ever set
        # by petty cash's build_draft) is the one field that tells them apart.
        kind = ReceiptKind.EXPENSE
        direction = str(fields.get("direction", "")).strip().lower()
        hero_number = f"₹{str(fields.get('amount', '')).strip() or '0'}"
        if direction in ("issue", "return"):
            category = "Petty cash"
            recipient = str(fields.get("recipient_account_name") or "")
            other_name = str(fields.get("other_account_name") or "")
            if direction == "return":
                rows = _rows(kind, ("Returned by", recipient), ("Into", other_name))
                summary_text = f"Returned by {recipient}" if recipient else "Petty cash returned"
            else:
                rows = _rows(kind, ("Issued to", recipient), ("From", other_name))
                summary_text = f"Issued to {recipient}" if recipient else "Petty cash issued"
            id_prefix = "PC"
        else:
            category = "Transfer"
            from_name = str(fields.get("from_account_name") or "")
            to_name = str(fields.get("to_account_name") or "")
            rows = _rows(kind, ("From", from_name), ("To", to_name))
            summary_text = f"{from_name} → {to_name}" if from_name and to_name else "Transfer"
            id_prefix = "TR"
        summary_value = hero_number
    elif draft.action_type is DraftActionType.REVERSE_TRANSACTION:
        # target_kind/reversal_* are seeded from a real DB read
        # (runtime/reversal_query.py), never an AI hint -- see
        # reverse/nodes.py's build_draft docstring.
        kind = ReceiptKind.UNDONE
        target_kind = str(fields.get("target_kind", "")).strip().lower()
        category = "Undo" if target_kind in ("activity", "attendance") else "Reversal"
        amount = str(fields.get("reversal_amount", "")).strip() or "0"
        if target_kind == "activity":
            # ADR-D15: no monetary value to headline -- "Undone" in place of
            # an amount, matching this being a retraction, not a transaction.
            hero_title = "Undone"
            rows = _rows(
                kind,
                ("Activity", fields.get("reversal_activity_summary") or "Site activity"),
                ("Date", fields.get("reversal_occurred_date")),
            )
        elif target_kind == "attendance":
            # Headlined as a withdrawal, not an amount: the cost is context
            # for what stopped counting, not a transaction that happened.
            hero_title = "Withdrawn"
            rows = _rows(
                kind,
                ("Site", fields.get("reversal_attendance_site")),
                ("Day", fields.get("reversal_occurred_date")),
                ("Workers", fields.get("reversal_attendance_headcount")),
                ("Cost removed", f"₹{amount}"),
            )
        elif target_kind == "petty_cash":
            # Named for the person, not the account pair -- same reasoning
            # as reverse/nodes.py's petty cash confirmation branch.
            hero_number = f"₹{amount}"
            direction = str(fields.get("reversal_petty_cash_direction", "")).strip().lower()
            account = (
                fields.get("reversal_from_account_name")
                if direction == "return"
                else fields.get("reversal_to_account_name")
            )
            rows = _rows(
                kind,
                ("Returned by" if direction == "return" else "Issued to", fields.get("reversal_petty_cash_holder")),
                ("Account", account),
            )
        elif target_kind == "transfer":
            hero_number = f"₹{amount}"
            rows = _rows(
                kind,
                ("From", fields.get("reversal_from_account_name")),
                ("To", fields.get("reversal_to_account_name")),
            )
        else:
            hero_number = f"₹{amount}"
            rows = _rows(
                kind,
                ("Description", fields.get("reversal_description")),
                ("Original date", fields.get("reversal_occurred_date")),
            )
        id_prefix = "RV"
        summary_text = (
            {"activity": "Activity removed", "attendance": "Attendance withdrawn"}.get(target_kind)
            or f"{target_kind.replace('_', ' ').title() or 'Expense'} reversed"
        )
        summary_value = hero_number or hero_title
    elif draft.action_type is DraftActionType.MANAGE_MONEY_ACCOUNT:
        action = str(fields.get("action", "")).strip().lower()
        category = "Account"
        if action == "create":
            hero_title = "Created"
            rows = _rows(kind, ("Account", fields.get("name")))
        elif action == "rename":
            hero_title = "Renamed"
            rows = _rows(kind, ("From", fields.get("target_name")), ("To", fields.get("new_name")))
        else:
            hero_title = "Deactivated"
            rows = _rows(kind, ("Account", fields.get("target_name")))
        id_prefix = "AC"
        summary_text = f"Account {hero_title.lower()}"
    elif draft.action_type is DraftActionType.CREATE_ACTIVITY:
        work_type = str(fields.get("work_type") or "Activity").replace("_", " ").title()
        kind = ReceiptKind.WORK
        category = "Site activity"
        pct = _progress_percent(fields)
        if _present(fields.get("quantity")):
            hero_number, hero_unit = str(fields["quantity"]).strip(), str(fields.get("unit") or "").strip()
        elif pct:
            hero_number, hero_unit = pct.rstrip("%"), "% done"
        else:
            hero_title = work_type
        if pct:
            # What was reported, from the saved data -- the percentage is the
            # point of the message, so it is never left to the free-text note.
            rows = _rows(
                kind,
                ("Work", _work_line(work_type, fields, pct)),
                ("Contractor", fields.get("contractor")),
            )
            summary_text = _work_line(work_type, fields, "")
            summary_value = pct
        else:
            rows = _rows(
                kind,
                ("Work", work_type if hero_number else ""),
                ("Details", fields.get("narrative")),
                ("Contractor", fields.get("contractor")),
            )
            summary_text = work_type
            summary_value = _fmt_quantity(fields) if hero_number else ""
        id_prefix = "AL"
    elif draft.action_type is DraftActionType.ADD_PROGRESS_UPDATE:
        update_kind = str(fields.get("update_kind") or "PROGRESS").replace("_", " ").title()
        kind = ReceiptKind.WORK
        category = "Progress update"
        pct = _progress_percent(fields)
        if pct:
            hero_number, hero_unit = pct.rstrip("%"), "% done"
            rows = _rows(
                kind,
                ("Activity", fields.get("activity_summary")),
                ("Progress", pct),
            )
        else:
            hero_title = update_kind
            rows = _rows(
                kind,
                ("Activity", fields.get("activity_summary")),
                ("Details", fields.get("narrative")),
            )
        id_prefix = "PU"
        summary_text = str(fields.get("activity_summary") or "Progress update")
        summary_value = pct or update_kind
    elif draft.action_type is DraftActionType.CORRECT_ACTIVITY_QUANTITY:
        # ADR-D14: old_quantity/old_unit are seeded straight from a real DB
        # read (runtime/inbound_journey/seeding.py), never an unresolved AI
        # hint -- same reasoning reverse/nodes.py's reversal_* fields document.
        old_unit = str(fields.get("old_unit") or "")
        new_unit = str(fields.get("unit") or old_unit)
        kind = ReceiptKind.WORK
        category = "Correction"
        hero_number, hero_unit = str(fields.get("new_quantity", "")).strip(), new_unit
        rows = _rows(kind, ("Activity", fields.get("correction_activity_summary")))
        correction = ReceiptCorrection(
            old_value=f"{fields.get('old_quantity')} {old_unit}".strip(),
            new_value=f"{fields.get('new_quantity')} {new_unit}".strip(),
        )
        id_prefix = "QC"
        summary_text = str(fields.get("correction_activity_summary") or "Quantity corrected")
        summary_value = correction.new_value
    elif draft.action_type is DraftActionType.RECORD_SITE_ISSUE:
        issue_type = str(fields.get("issue_type") or "Issue").replace("_", " ").title()
        kind = ReceiptKind.ISSUE
        category = "Site issue"
        hero_title = issue_type
        hero_status = "Open"
        rows = _rows(
            kind,
            ("Severity", str(fields.get("severity") or "").title()),
            ("Details", fields.get("narrative")),
        )
        id_prefix = "SI"
        summary_text = str(fields.get("narrative") or issue_type)
        summary_value = "Open"
    elif draft.action_type is DraftActionType.CLOSE_SITE_ISSUE:
        issue_type = str(fields.get("site_issue_type") or "Issue").replace("_", " ").title()
        kind = ReceiptKind.ISSUE
        category = "Site issue"
        hero_title = issue_type
        hero_status = _status_word(str(fields.get("action") or "").replace("_", " ")) or "Updated"
        rows = _rows(
            kind,
            ("Details", fields.get("site_issue_narrative")),
            ("Notes", fields.get("resolution_notes")),
        )
        id_prefix = "SC"
        summary_text = str(fields.get("site_issue_narrative") or issue_type)
        summary_value = hero_status
    elif draft.action_type is DraftActionType.CREATE_PROJECT:
        category, hero_title = "Project", "Created"
        rows = _rows(kind, ("Project", fields.get("name")), ("Location", fields.get("location")))
        id_prefix = "PJ"
        summary_text = f"Project {fields.get('name') or ''}".strip()
    elif draft.action_type is DraftActionType.CREATE_SITE:
        category, hero_title = "Site", "Created"
        rows = _rows(kind, ("Site", fields.get("name")), ("Location", fields.get("location")))
        id_prefix = "ST"
        summary_text = f"Site {fields.get('name') or ''}".strip()
    elif draft.action_type is DraftActionType.ADD_PROJECT_MEMBER:
        category, hero_title = "Project member", "Added"
        rows = _rows(
            kind,
            ("Member", fields.get("member_name")),
            ("Role", str(fields.get("role") or "").replace("_", " ").title()),
        )
        id_prefix = "PM"
        summary_text = str(fields.get("member_name") or "Project member")
    elif draft.action_type is DraftActionType.CREATE_USER:
        category, hero_title = "New user", "Created"
        rows = _rows(
            kind,
            ("Name", fields.get("full_name")),
            ("Number", fields.get("whatsapp_number")),
            ("Role", str(fields.get("role") or "").replace("_", " ").title()),
        )
        id_prefix = "US"
        summary_text = str(fields.get("full_name") or "New user")
    else:
        # Defensive only -- every DraftActionType above is expected to have
        # an explicit case. A genuinely new, uncased type renders a generic
        # "Record" card rather than silently mislabeling itself as whatever
        # branch happened to be last.
        category, hero_title = "Record", "Confirmed"
        id_prefix = "RC"
        summary_text = "Record confirmed"

    # More than MAX_ROWS trades: draw the first MAX_ROWS - 1, count the rest.
    more = 0
    if len(trades) > MAX_ROWS:
        more = len(trades) - (MAX_ROWS - 1)
        trades = trades[: MAX_ROWS - 1]

    undone = kind is ReceiptKind.UNDONE
    if undone:
        status, footer = STATUS_UNDONE, FOOTER_UNDONE
    elif late_entry:
        status, footer = STATUS_LATE, FOOTER_LATE
    elif draft.action_type in _DRAFT_TYPES:
        status, footer = STATUS_DRAFT, FOOTER_DRAFT
    else:
        status, footer = STATUS_SAVED, ""

    record_id = f"{id_prefix}-{confirmed_at:%d%m%y}-{record_row_id.replace('-', '')[:4].upper()}"
    # A project and its only site often share a name ("Green Villa, Kakkanad"):
    # say it once.
    names = [site_name, project_name]
    if site_name and project_name and site_name.strip().casefold() == project_name.strip().casefold():
        names = [site_name]
    place = " · ".join(p for p in names if p)
    when = f"{confirmed_at:%d %b %Y} · {confirmed_at:%I:%M %p}".replace(" 0", " ")
    meta = " · ".join(p for p in (when, reporter) if p)

    return ReceiptData(
        kind=kind,
        category=category,
        status=status,
        site_line=place or "—",
        meta_line=meta,
        record_id=record_id,
        footer_note=footer,
        hero_number=hero_number,
        hero_unit=hero_unit,
        hero_title=hero_title,
        hero_status=hero_status,
        rows=rows,
        more=more,
        trades=trades,
        correction=correction,
        summary=ReceiptRow(
            kind,
            summary_tag or KIND_TAG[kind],
            summary_text,
            summary_value,
            emphasis=kind is ReceiptKind.ISSUE,
        ),
    )


def combine_receipts(parts: list[ReceiptData]) -> ReceiptData:
    """One card for a multi-part note: a row per saved record.

    The first part supplies the site, date and reporter (parts of one
    message share them). More than MAX_ROWS rows shows MAX_ROWS - 1 and "+N
    more" -- all of them are still saved and listed in the reply text.
    """
    if not parts:
        raise ValueError("combine_receipts needs at least one receipt")
    if len(parts) == 1:
        return parts[0]
    first = parts[0]
    rows = [p.summary for p in parts if p.summary is not None]
    more = 0
    if len(rows) > MAX_ROWS:
        more = len(rows) - (MAX_ROWS - 1)
        rows = rows[: MAX_ROWS - 1]
    all_undone = all(p.kind is ReceiptKind.UNDONE for p in parts)
    draft = any(p.status == STATUS_DRAFT for p in parts)
    late = any(p.status == STATUS_LATE for p in parts)
    if all_undone:
        status = STATUS_UNDONE
    else:
        status = f"{len(parts)} {STATUS_LATE if late else (STATUS_DRAFT if draft else STATUS_SAVED)}"
    return ReceiptData(
        kind=ReceiptKind.RECORD,
        category="Site update",
        status=status,
        site_line=first.site_line,
        meta_line=first.meta_line,
        record_id=f"{first.record_id} +{len(parts) - 1}",
        footer_note=first.footer_note,
        hero_number=str(len(parts)),
        hero_unit="parts",
        rows=rows,
        more=more,
    )
