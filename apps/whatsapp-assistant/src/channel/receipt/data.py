"""Maps a confirmed record into the receipt-card data shape.

Pure, no I/O -- one function per DraftActionType, all producing the same
generic shape (brand/category/value/subtitle/location/dateTime/sections/
footer), plus a per-category `accent`/`badge_icon` and a `template_variant`
that template.py uses to pick between the record-card layout (money/material/
labour/etc.) and the activity-card layout (site activity create/progress/
correction/undo) -- see the Module Placement Log entry in AGENTS.md.

Field labels/icons here are display concerns, not business logic -- adding a
new DraftActionType means adding a case here, never touching the domain
layer or the template.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2


@dataclass(frozen=True, slots=True)
class ReceiptField:
    icon: str  # key into template.py's _ICONS
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class ReceiptLocationRow:
    icon: str
    text: str


@dataclass(frozen=True, slots=True)
class ReceiptCorrection:
    """Old -> new value for a quantity edit -- rendered as a diff chip by the
    activity template, not squeezed into a single pre-joined section field."""

    old_value: str
    new_value: str


@dataclass(frozen=True, slots=True)
class ReceiptData:
    brand: str
    category: str
    value: str
    subtitle: str
    location: list[ReceiptLocationRow]
    date: str
    time: str
    sections: list[list[ReceiptField]]
    id_label: str
    record_id: str
    saved_at: str
    logo_text: str
    accent: str = "#0A8F4C"
    badge_icon: str = "layers"
    template_variant: str = "record"
    correction: ReceiptCorrection | None = None


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


def _labour_summary(fields: dict) -> tuple[int, str, int]:
    """Total people, a readable trade list, and how many were named.

    Attendance is the one record type whose value is a *list*, not a single
    quantity, so the receipt has to summarise rather than echo a field. Trades
    are de-duplicated but kept in the order reported, so the card reads the way
    the supervisor wrote it.
    """
    raw = fields.get("lines")
    lines = [line for line in raw if isinstance(line, dict)] if isinstance(raw, list) else []
    headcount = 0
    named = 0
    trades: list[str] = []
    for line in lines:
        try:
            count = int(line.get("headcount", 1))
        except (TypeError, ValueError):
            count = 1
        headcount += count
        if str(line.get("worker_name") or "").strip():
            named += 1
        trade = str(line.get("trade") or "").strip().replace("_", " ")
        if trade and trade not in trades:
            trades.append(trade)
    return headcount, ", ".join(t.title() for t in trades), named


def _labour_people(headcount: int, named: int) -> str:
    """How the headcount breaks down between named people and counted groups —
    the distinction principle P10 exists to preserve, so it belongs on the
    record the user keeps."""
    if not headcount:
        return "—"
    if named == 0:
        return f"{headcount} (by headcount)"
    if named == headcount:
        return f"{headcount} named"
    return f"{headcount} ({named} named, {headcount - named} by headcount)"


def build_receipt_data(
    draft: DraftActionV2,
    *,
    record_row_id: str,
    reporter_name: str | None,
    projects: list[Any],
    sites: list[Any],
    confirmed_at: datetime,
) -> ReceiptData:
    """Build the generic receipt shape for a confirmed DraftAction.

    ``record_row_id`` comes from ExecutionResult, not the draft -- it is the
    real persisted row id, so the receipt's "Record id" points at a row that
    actually exists. Named for materials on the contract
    (``ExecutionResult.material_row_id``) because materials came first; it
    now carries the expense, transfer, petty-cash and labour ids too, so the
    parameter is spelled for what it is rather than inheriting a name that
    stopped being true several record types ago.
    """
    fields = draft.fields
    material_name = str(fields.get("material_name", "")).strip() or "Material"
    project_name = _project_name(draft.project_id, projects) or "—"
    site_name = _site_name(draft.site_id, sites) or "—"
    reporter = reporter_name or "—"

    location = [
        ReceiptLocationRow("building", project_name),
        ReceiptLocationRow("pin", site_name),
    ]

    # Defaults for the record-card fields every branch below overrides with
    # its own category color/icon; only the activity family (create/progress/
    # correction/undo) switches template_variant and sets `correction`.
    template_variant = "record"
    correction: ReceiptCorrection | None = None

    if draft.action_type is DraftActionType.RECORD_EXPENSE:
        expense_category = str(fields.get("category", "")).strip() or "Uncategorized"
        category = "Expense"
        value = str(fields.get("amount", "")).strip() or "0"
        subtitle = f"{expense_category.title()} expense recorded"
        sections = [
            [
                ReceiptField("layers", "Category", expense_category.title()),
                ReceiptField("store", "Description", str(fields.get("description") or "—")),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "EX"
        accent, badge_icon = "#B45309", "store"
    elif draft.action_type is DraftActionType.RECORD_MATERIAL_RECEIPT:
        category = "Material receipt"
        value = _fmt_quantity(fields)
        subtitle = f"{material_name.title()} received"
        sections = [
            [
                ReceiptField("layers", "Material", material_name.title()),
                ReceiptField("store", "Supplier", str(fields.get("supplier") or "—")),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "MR"
        accent, badge_icon = "#0A8F4C", "layers"
    elif draft.action_type is DraftActionType.RECORD_LABOUR_ATTENDANCE:
        headcount, trades, named = _labour_summary(fields)
        category = "Labour attendance"
        value = str(headcount)
        subtitle = f"{headcount} worker{'s' if headcount != 1 else ''} recorded"
        sections = [
            [
                ReceiptField("users", "Workers", _labour_people(headcount, named)),
                ReceiptField("layers", "Trades", trades or "—"),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "LA"
        accent, badge_icon = "#7C3AED", "users"
    elif draft.action_type is DraftActionType.TRANSFER_MONEY:
        # Petty cash issue/return (Finance Slice 5) emits this same
        # DraftActionType as a plain transfer -- `direction` (only ever set
        # by petty cash's build_draft) is the one field that tells them
        # apart. from_account_name/to_account_name/other_account_name/
        # recipient_account_name are all real resolved names, not ids --
        # see transfer/petty_cash nodes.py's build_draft docstrings.
        direction = str(fields.get("direction", "")).strip().lower()
        value = str(fields.get("amount", "")).strip() or "0"
        if direction in ("issue", "return"):
            category = "Petty cash"
            recipient = str(fields.get("recipient_account_name") or "—")
            other_name = str(fields.get("other_account_name") or "—")
            if direction == "return":
                subtitle = f"Returned by {recipient}"
                sections = [
                    [
                        ReceiptField("user", "Returned by", recipient),
                        ReceiptField("building", "Into", other_name),
                    ]
                ]
            else:
                subtitle = f"Issued to {recipient}"
                sections = [
                    [
                        ReceiptField("user", "Issued to", recipient),
                        ReceiptField("building", "From", other_name),
                    ]
                ]
            id_prefix = "PC"
        else:
            category = "Transfer"
            from_name = str(fields.get("from_account_name") or "—")
            to_name = str(fields.get("to_account_name") or "—")
            subtitle = f"{from_name} → {to_name}"
            sections = [
                [
                    ReceiptField("building", "From", from_name),
                    ReceiptField("building", "To", to_name),
                ]
            ]
            id_prefix = "TR"
        accent, badge_icon = "#0891B2", "building"
        sections.append(
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ]
        )
    elif draft.action_type is DraftActionType.REVERSE_TRANSACTION:
        # target_kind/reversal_* are seeded from a real DB read
        # (runtime/reversal_query.py), never an AI hint -- see
        # reverse/nodes.py's build_draft docstring.
        target_kind = str(fields.get("target_kind", "")).strip().lower()
        category = "Reversal"
        value = str(fields.get("reversal_amount", "")).strip() or "0"
        if target_kind == "activity":
            # ADR-D15: no monetary value to headline -- "Undone" in place of
            # an amount, matching this being a retraction, not a transaction.
            # Renders through the activity template's muted "undone" ribbon
            # treatment (template.py), not the record card's green "Saved" pill.
            category = "Undo"
            value = "Undone"
            summary = str(fields.get("reversal_activity_summary") or "Site activity")
            occurred_date = str(fields.get("reversal_occurred_date") or "—")
            subtitle = "Activity removed"
            sections = [
                [
                    ReceiptField("store", "Activity", summary),
                    ReceiptField("calendar", "Date", occurred_date),
                ]
            ]
            template_variant = "activity"
        elif target_kind == "attendance":
            # Headlined as a withdrawal, not an amount: the cost is context
            # for what stopped counting, not a transaction that happened.
            category = "Undo"
            value = "Withdrawn"
            site = str(fields.get("reversal_attendance_site") or "—")
            subtitle = "Attendance report withdrawn"
            sections = [
                [
                    ReceiptField("building", "Site", site),
                    ReceiptField("calendar", "Day", str(fields.get("reversal_occurred_date") or "—")),
                ],
                [
                    ReceiptField("user", "Workers", str(fields.get("reversal_attendance_headcount") or "—")),
                    ReceiptField("store", "Cost removed", f"₹{fields.get('reversal_amount') or '0'}"),
                ],
            ]
            template_variant = "activity"
        elif target_kind == "petty_cash":
            # Named for the person, not the account pair -- same reasoning
            # as reverse/nodes.py's petty cash confirmation branch.
            holder = str(fields.get("reversal_petty_cash_holder") or "—")
            direction = str(fields.get("reversal_petty_cash_direction", "")).strip().lower()
            subtitle = "Petty cash reversed"
            sections = [
                [
                    ReceiptField("user", "Returned by" if direction == "return" else "Issued to", holder),
                    ReceiptField(
                        "building",
                        "Account",
                        str(
                            fields.get("reversal_from_account_name")
                            if direction == "return"
                            else fields.get("reversal_to_account_name")
                        )
                        or "—",
                    ),
                ]
            ]
        elif target_kind == "transfer":
            from_name = str(fields.get("reversal_from_account_name") or "—")
            to_name = str(fields.get("reversal_to_account_name") or "—")
            subtitle = "Transfer reversed"
            sections = [
                [
                    ReceiptField("building", "From", from_name),
                    ReceiptField("building", "To", to_name),
                ]
            ]
        else:
            description = str(fields.get("reversal_description") or "—")
            occurred_date = str(fields.get("reversal_occurred_date") or "—")
            subtitle = "Expense reversed"
            sections = [
                [
                    ReceiptField("store", "Description", description),
                    ReceiptField("calendar", "Original date", occurred_date),
                ]
            ]
        sections.append(
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ]
        )
        id_prefix = "RV"
        accent, badge_icon = "#DC2626", "undo"
    elif draft.action_type is DraftActionType.MANAGE_MONEY_ACCOUNT:
        action = str(fields.get("action", "")).strip().lower()
        category = "Account"
        if action == "create":
            value = "Created"
            subtitle = f"New account: {fields.get('name', '—')}"
            sections = [[ReceiptField("building", "Account", str(fields.get("name") or "—"))]]
        elif action == "rename":
            value = "Renamed"
            subtitle = f"{fields.get('target_name', '—')} → {fields.get('new_name', '—')}"
            sections = [
                [
                    ReceiptField("building", "From", str(fields.get("target_name") or "—")),
                    ReceiptField("building", "To", str(fields.get("new_name") or "—")),
                ]
            ]
        else:
            value = "Deactivated"
            subtitle = str(fields.get("target_name") or "—")
            sections = [[ReceiptField("building", "Account", str(fields.get("target_name") or "—"))]]
        sections.append(
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ]
        )
        id_prefix = "AC"
        accent, badge_icon = "#475569", "building"
    elif draft.action_type is DraftActionType.RECORD_MATERIAL_USAGE:
        category = "Material usage"
        value = _fmt_quantity(fields)
        subtitle = f"{material_name.title()} used"
        sections = [
            [
                ReceiptField("layers", "Material", material_name.title()),
                ReceiptField("hammer", "Used for", str(fields.get("work_item") or "—")),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "MU"
        accent, badge_icon = "#2563EB", "layers"
    elif draft.action_type is DraftActionType.CREATE_ACTIVITY:
        work_type = str(fields.get("work_type") or "Activity")
        category = "Site Activity"
        value = work_type.title()
        subtitle = str(fields.get("narrative") or f"{work_type.title()} logged")
        sections = [
            [
                ReceiptField("hammer", "Work", work_type.title()),
                ReceiptField("store", "Contractor", str(fields.get("contractor") or "—")),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "AL"
        accent, badge_icon = "#4F46E5", "hammer"
        template_variant = "activity"
    elif draft.action_type is DraftActionType.ADD_PROGRESS_UPDATE:
        update_kind = str(fields.get("update_kind") or "PROGRESS").replace("_", " ")
        category = "Progress Update"
        value = update_kind.title()
        subtitle = str(fields.get("narrative") or f"{update_kind.title()} update")
        sections = [
            [
                ReceiptField("layers", "Activity", str(fields.get("activity_summary") or "—")),
                ReceiptField("hammer", "Update", update_kind.title()),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "PU"
        accent, badge_icon = "#4F46E5", "hammer"
        template_variant = "activity"
    elif draft.action_type is DraftActionType.CORRECT_ACTIVITY_QUANTITY:
        # ADR-D14: old_quantity/old_unit are seeded straight from a real DB
        # read (runtime/inbound_journey.py's _seed_correction_target), never
        # an unresolved AI hint -- same reasoning reverse/nodes.py's
        # reversal_* fields document for keeping them in draft.fields.
        old_quantity = fields.get("old_quantity")
        old_unit = str(fields.get("old_unit") or "")
        new_quantity = fields.get("new_quantity")
        new_unit = str(fields.get("unit") or old_unit)
        category = "Correction"
        value = f"{new_quantity} {new_unit}".strip()
        subtitle = "Quantity corrected"
        # No "Quantity" field here -- the activity template renders the
        # old->new change as a struck-through diff chip (data.correction
        # below), so repeating it as a plain field would show it twice.
        sections = [
            [
                ReceiptField("layers", "Activity", str(fields.get("correction_activity_summary") or "—")),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "QC"
        accent, badge_icon = "#B45309", "hammer"
        template_variant = "activity"
        correction = ReceiptCorrection(
            old_value=f"{old_quantity} {old_unit}".strip(),
            new_value=f"{new_quantity} {new_unit}".strip(),
        )
    elif draft.action_type is DraftActionType.RECORD_SITE_ISSUE:
        issue_type = str(fields.get("issue_type") or "Issue").replace("_", " ")
        category = "Site Issue"
        value = str(fields.get("severity") or "—").title()
        subtitle = str(fields.get("narrative") or f"{issue_type.title()} reported")
        sections = [
            [
                ReceiptField("layers", "Type", issue_type.title()),
                ReceiptField("hammer", "Severity", str(fields.get("severity") or "—").title()),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "SI"
        accent, badge_icon = "#EA580C", "hammer"
    elif draft.action_type is DraftActionType.CLOSE_SITE_ISSUE:
        action = str(fields.get("action") or "").replace("_", " ")
        issue_type = str(fields.get("site_issue_type") or "Issue").replace("_", " ")
        category = "Site Issue"
        value = action.title() or "Updated"
        subtitle = str(fields.get("site_issue_narrative") or issue_type.title())
        sections = [
            [
                ReceiptField("layers", "Type", issue_type.title()),
                ReceiptField("store", "Notes", str(fields.get("resolution_notes") or "—")),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "SC"
        accent, badge_icon = "#EA580C", "hammer"
    elif draft.action_type is DraftActionType.CREATE_PROJECT:
        category = "Project"
        value = "Created"
        subtitle = f"New project: {fields.get('name', '—')}"
        sections = [
            [
                ReceiptField("building", "Project", str(fields.get("name") or "—")),
                ReceiptField("pin", "Location", str(fields.get("location") or "—")),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "PJ"
        accent, badge_icon = "#4F46E5", "building"
    elif draft.action_type is DraftActionType.CREATE_SITE:
        category = "Site"
        value = "Created"
        subtitle = f"New site: {fields.get('name', '—')}"
        sections = [
            [
                ReceiptField("building", "Site", str(fields.get("name") or "—")),
                ReceiptField("pin", "Location", str(fields.get("location") or "—")),
            ],
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "ST"
        accent, badge_icon = "#4F46E5", "building"
    elif draft.action_type is DraftActionType.ADD_PROJECT_MEMBER:
        category = "Project Member"
        value = "Added"
        subtitle = f"{fields.get('member_name', '—')} added to the project"
        sections = [
            [
                ReceiptField("user", "Member", str(fields.get("member_name") or "—")),
                ReceiptField("layers", "Role", str(fields.get("role") or "—").replace("_", " ").title()),
            ],
            [
                ReceiptField("user", "Added by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "PM"
        accent, badge_icon = "#4F46E5", "user"
    elif draft.action_type is DraftActionType.CREATE_USER:
        category = "New User"
        value = "Created"
        subtitle = f"New user: {fields.get('full_name', '—')}"
        sections = [
            [
                ReceiptField("user", "Name", str(fields.get("full_name") or "—")),
                ReceiptField("whatsapp", "Number", str(fields.get("whatsapp_number") or "—")),
                ReceiptField("layers", "Role", str(fields.get("role") or "—").replace("_", " ").title()),
            ],
            [
                ReceiptField("user", "Added by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ],
        ]
        id_prefix = "US"
        accent, badge_icon = "#4F46E5", "user"
    else:
        # Defensive only -- every DraftActionType above is expected to have
        # an explicit case. A genuinely new, uncased type renders a generic
        # "Record" card rather than silently mislabeling itself as whatever
        # branch happened to be last (the bug this replaced: every new
        # DraftActionType added without a case here rendered as "Material
        # usage" with a bogus quantity line).
        category = "Record"
        value = "Confirmed"
        subtitle = "Record confirmed"
        sections = [
            [
                ReceiptField("user", "Reported by", reporter),
                ReceiptField("whatsapp", "Source", "WhatsApp"),
            ]
        ]
        id_prefix = "RC"
        accent, badge_icon = "#0A8F4C", "layers"

    record_id = f"{id_prefix}-{confirmed_at:%d%m%y}-{record_row_id.replace('-', '')[:4].upper()}"

    return ReceiptData(
        brand="MESIRI",
        category=category,
        value=value,
        subtitle=subtitle,
        location=location,
        date=f"{confirmed_at:%d %b %Y}",
        time=f"{confirmed_at:%I:%M %p}",
        sections=sections,
        id_label="Record id",
        record_id=record_id,
        saved_at=f"{confirmed_at:%d %b %Y · %I:%M %p}",
        logo_text="MESIRI AI",
        accent=accent,
        badge_icon=badge_icon,
        template_variant=template_variant,
        correction=correction,
    )
