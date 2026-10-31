"""Plain-words lines for confirmation prompts (request [37] item 7).

A confirmation used to print each draft field as `key: value`, so a site
engineer read `amount: 1500`, `paid_from_own_pocket: True`, `direction:
received`. These helpers turn a field into a labelled line a person reads --
"Amount: ₹1,500", "Paid: own pocket" -- and keep plumbing (ids, flags the
workflow set for itself) out of sight.

Used by every confirmation that still lists leftover fields (material,
expense, site update, labour, site issue). Pure formatting, no I/O.
"""

from __future__ import annotations

from typing import Any

from trade_label import trade_label


def format_quantity(value: Any) -> str:
    """A stock quantity as people read it: whole numbers stay whole, otherwise
    up to 2 decimals (1.43, 2.5). One rule for the text reply and the Stock card."""
    number = float(value)
    if abs(number - round(number)) < 0.005:
        return str(int(round(number)))
    return f"{number:.2f}".rstrip("0").rstrip(".")


#: What each known field is called to a person.
FIELD_LABELS: dict[str, str] = {
    "material_name": "Material",
    "quantity": "Quantity",
    "unit": "Unit",
    "direction": "Direction",
    "supplier": "Supplier",
    "work_item": "Used for",
    "project_name": "Project",
    "site_name": "Site",
    "location_name": "Location",
    "amount": "Amount",
    "vendor": "For",
    "category": "Category",
    "description": "Note",
    "paid_to": "Paid to",
    "paid_from_own_pocket": "Paid",
    "tax_rate": "Tax rate",
    "tax_amount": "Tax",
    "headcount": "Workers",
    "trade": "Trade",
    "severity": "Severity",
    "issue_type": "Issue",
    "narrative": "Details",
    "work_type": "Work",
    "contractor": "Contractor",
}

#: Fields no person needs to see: the workflow's own bookkeeping and what the
#: system already shows another way (a "Receipt attached" line, the date line).
HIDDEN_FIELDS = frozenset(
    {
        "currency",
        "available_stock",
        "no_opening_stock",
        "site_label",
        "from_site_name",
        "to_site_name",
        "movement_reason",
        "notes",
        "counted",
        "book_stock",
        "is_forwarded",
        "is_frequently_forwarded",
        "is_tax_inclusive",
        "media_object_key",
        "source",
        "occurred_date",
        "occurred_date_source",
        "own_pocket_assumed",
    }
)

_INR = frozenset({"inr", "rupee", "rupees", "rs", "rs.", "₹", ""})


def is_hidden(key: str) -> bool:
    return key in HIDDEN_FIELDS or key.startswith("_") or key.endswith("_id") or key.endswith("_ids")


def label_for(key: str) -> str:
    return FIELD_LABELS.get(key) or key.replace("_", " ").strip().capitalize()


def money(amount: Any, currency: Any = None) -> str:
    """₹1,500 / ₹1,500.50 for rupees (the default), "1,500 USD" otherwise."""
    try:
        number = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    text = f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"
    code = str(currency or "").strip()
    if code.lower() in _INR:
        return f"₹{text}"
    return f"{text} {code.upper()}"


def value_text(key: str, value: Any, fields: dict[str, Any] | None = None) -> str:
    """One field's value as a person says it."""
    if key == "amount":
        return money(value, (fields or {}).get("currency"))
    if key == "paid_from_own_pocket":
        return "own pocket" if value else "company account"
    if key == "trade":
        return trade_label(value) or str(value)
    if key == "direction":
        return str(value).capitalize()
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def field_lines(fields: dict[str, Any], *, skip: frozenset[str] = frozenset()) -> list[str]:
    """`   • Label: value` for each visible field, in the order given."""
    lines = []
    for key, value in fields.items():
        if key in skip or is_hidden(key) or value in (None, "", [], {}):
            continue
        lines.append(f"   • {label_for(key)}: {value_text(key, value, fields)}")
    return lines


#: A friendly name for what a workflow records, for summaries ("Work done").
WORKFLOW_NAMES: dict[str, str] = {
    "site.update": "Work done",
    "site.activity_continuation": "Work update",
    "site.activity_correction": "Work correction",
    "labour.attendance": "Labour attendance",
    "labour.worker_promotion": "Worker added",
    "material.receipt": "Material received",
    "material.usage": "Material used",
    "equipment.usage": "Equipment used",
    "expense.submit": "Expense",
    "site.issue_report": "Site issue",
    "site.issue_close": "Issue closed",
    "finance.transfer": "Money transfer",
    "finance.petty_cash": "Petty cash",
    "project.create": "New project",
    "site.create": "New site",
    "user.create": "New user",
    "project.add_member": "Project member added",
}


def workflow_name(workflow_key: str) -> str:
    return WORKFLOW_NAMES.get(workflow_key) or workflow_key.replace(".", " ").replace("_", " ").capitalize()
