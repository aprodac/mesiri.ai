"""Who gets a project's DPR, and whether WhatsApp may message them (BE-15).

Pure rules, no SQL (the table is migration 0471; SQL lives in
infrastructure/postgres/repositories/report_recipients.py).

- A project's recipients are its active `report_recipients` rows. With none,
  the default audience applies -- the project's admins and project managers,
  as BE-16 has always sent to -- so nothing changes until someone sets a list.
- A recipient is a company user or an outside contact (name + phone).
- Company users may be messaged unless they opted out. An outside contact
  must have opted in first: Meta requires opt-in before a business starts a
  conversation, and a contact never agreed to anything by joining a company.
"""

from __future__ import annotations

OPTED_IN = "opted_in"
OPTED_OUT = "opted_out"

RECORDED_BY_ADMIN = "recorded_by_admin"
WHATSAPP_REPLY = "whatsapp_reply"
WEB_FORM = "web_form"
METHODS = (RECORDED_BY_ADMIN, WHATSAPP_REPLY, WEB_FORM)

# Roles that may change who receives a project's DPR.
MANAGER_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER"})

_MIN_DIGITS = 10
_MAX_DIGITS = 15  # E.164
_NAME_MAX = 120
_LABEL_MAX = 60


class RecipientError(ValueError):
    """A recipient request that can't be accepted; the message says why."""


def normalize_phone(raw: object) -> str:
    """A phone number in WhatsApp-id form: digits only, country code first.
    A bare 10-digit Indian mobile (starts 6-9) gets 91 in front -- the
    common way a site office writes a number; anything else must carry its
    country code. Raises RecipientError when it can't be a phone number."""
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0") and digits[1] in "6789":
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        digits = "91" + digits
    if not (_MIN_DIGITS + 1 <= len(digits) <= _MAX_DIGITS):
        raise RecipientError("Enter the phone number with its country code, e.g. +91 98765 43210")
    return digits


def clean_contact(*, name: object, phone: object, label: object = None) -> dict[str, str | None]:
    """An outside contact's fields, validated and trimmed."""
    clean_name = str(name or "").strip()
    if not clean_name:
        raise RecipientError("A contact needs a name")
    if len(clean_name) > _NAME_MAX:
        raise RecipientError(f"Name is longer than {_NAME_MAX} characters")
    clean_label = str(label or "").strip() or None
    if clean_label and len(clean_label) > _LABEL_MAX:
        raise RecipientError(f"Label is longer than {_LABEL_MAX} characters")
    return {"name": clean_name, "phone": normalize_phone(phone), "label": clean_label}


def may_message(*, consent_state: str | None, requires_opt_in: bool) -> tuple[bool, str | None]:
    """Whether WhatsApp may message this number now, and the skip reason if
    not. `consent_state` is the latest whatsapp_opt_ins state (None = no
    record). An opt-out always wins; an outside contact needs an opt-in."""
    if consent_state == OPTED_OUT:
        return False, "opted_out"
    if requires_opt_in and consent_state != OPTED_IN:
        return False, "no_opt_in"
    return True, None
