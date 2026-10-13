"""Organization settings — the catalog of per-tenant tunable rules.

Pure definitions, no I/O: what settings exist, what shape each holds, and
what an org that has never configured one falls back to. The store
(infrastructure/postgres/repositories/organization_settings.py) reads and
writes rows; this module is the single place that decides what a valid
setting *is*, so an unknown key can be rejected at the API boundary rather
than silently persisted and never read by anything.

Defaults matter more than usual here: no row exists for any org until
someone changes something in the control panel, so the default IS the
behaviour for every existing tenant. Each default below is chosen to match
what the code did before the setting existed.
"""

from __future__ import annotations

from dataclasses import dataclass

from mesiri.domains.organizations.branding import DEFAULT_BRANDING

# Every role the system recognises (users/router.py's _VALID_ROLES). Kept as
# a frozenset here so a settings payload naming a role that doesn't exist is
# rejected at the boundary instead of silently never matching anyone.
VALID_ROLES: frozenset[str] = frozenset(
    {"ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE"}
)

# Which roles may create a materials_catalog entry directly from a WhatsApp
# report (STA-139). Default is Admin + Project Manager: before this setting
# existed the WhatsApp path could not create catalog entries at all, so the
# conservative default keeps casual field reports from populating a shared
# catalog with typos, while still unblocking the people who own it.
WHATSAPP_MATERIAL_CREATE_ROLES = "whatsapp_material_create_roles"
FINANCE_SETTINGS = "finance_settings"
LABOUR_SETTINGS = "labour_settings"
ENABLED_MODULES = "enabled_modules"
# Letterhead details and logo (BE-20); rules in domains/organizations/branding.py.
BRANDING = "branding"

# Product modules a company can have switched on (V1 tracker BE-06). Each key
# gates one or more API routers (domains/shared/modules.py's require_module)
# and the WhatsApp workflows of the same area. Company, projects, sites, users
# and auth are not modules: every company always has them.
MODULES: dict[str, str] = {
    "dpr": "Daily progress: activities, issues, photos, timeline and DPRs",
    "labour": "Labour attendance and workforce",
    "materials": "Materials received, used and stock",
    "finance": "Expenses, petty cash, transfers, accounts and vendors",
    "automations": "User-defined scheduled messages",
}

# Short names for the control panel's module switches (SA-07).
MODULE_LABELS: dict[str, str] = {
    "dpr": "Daily progress (DPR)",
    "labour": "Labour",
    "materials": "Materials",
    "finance": "Finance",
    "automations": "Automations",
}

# DPR is the product: a company without it has nothing to use.
ALWAYS_ON_MODULES: frozenset[str] = frozenset({"dpr"})

# What V1 sells.
V1_MODULES: tuple[str, ...] = ("dpr", "labour", "materials")

# A company that has never had its modules set gets V1. Flipped from "every
# module on" in the same release as the dashboard hiding (WEB-02) and the
# WhatsApp polite refusal (WA-07), so a switched-off module is hidden
# everywhere at the moment it stops working. Finance and automations are
# switched on per company from the control panel (SA-07).
DEFAULT_ENABLED_MODULES: list[str] = list(V1_MODULES)

# Settings only a platform admin may change. Modules are tied to what a
# customer pays for, so a company's own admin can read them but not edit them.
SUPERADMIN_ONLY_KEYS: frozenset[str] = frozenset({ENABLED_MODULES})

DEFAULT_FINANCE_SETTINGS = {
    "base_currency": "INR",
    "currency_symbol": "₹",
    "fiscal_year_start": "04-01",
    "low_float_threshold": 50000.0,
    "auto_approval_limit": 5000.0,
    "require_receipt_above": 1000.0,
    "duplicate_window_hours": 24,
    "default_tax_rate": 18.0,
    "enabled_payment_methods": ["bank_transfer", "cash", "upi", "cheque", "card"],
    "low_balance_warning_enabled": True,
    "transfer_receipt_enabled": True,
    "expense_card_enabled": True,
    "weekly_digest_enabled": True,
    "weekly_digest_schedule": "weekly_monday",
}

# Every default here matches what the WhatsApp labour workflow already does
# with no setting present, per workflows/labour_update/nodes.py: it never
# writes the register on its own (principle P1) and asks nothing beyond what
# match_workers already asks — these toggles govern dashboard-side behaviour
# layered on top, not the workflow's own matching logic.
DEFAULT_LABOUR_SETTINGS = {
    "missing_report_reminder_enabled": True,
    "missing_report_reminder_time": "18:00",
    "headcount_anomaly_alert_enabled": True,
    "wage_change_alert_enabled": True,
    "require_dashboard_approval_for_new_worker": False,
}


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """What a setting holds and what it means when it's never been set."""

    key: str
    default: object
    description: str


_SPECS: dict[str, SettingSpec] = {
    WHATSAPP_MATERIAL_CREATE_ROLES: SettingSpec(
        key=WHATSAPP_MATERIAL_CREATE_ROLES,
        default=["ADMIN", "PROJECT_MANAGER"],
        description=(
            "Roles allowed to add a new material to the catalog directly from a "
            "WhatsApp report. Anyone else is told to ask their admin."
        ),
    ),
    FINANCE_SETTINGS: SettingSpec(
        key=FINANCE_SETTINGS,
        default=DEFAULT_FINANCE_SETTINGS,
        description="Organization-wide financial preferences & WhatsApp assistant policies.",
    ),
    LABOUR_SETTINGS: SettingSpec(
        key=LABOUR_SETTINGS,
        default=DEFAULT_LABOUR_SETTINGS,
        description="Organization-wide labour attendance preferences & WhatsApp assistant policies.",
    ),
    ENABLED_MODULES: SettingSpec(
        key=ENABLED_MODULES,
        default=DEFAULT_ENABLED_MODULES,
        description=(
            "Product modules switched on for this company. Changed by the "
            "Mesiri team only; a switched-off module's pages and WhatsApp "
            "flows are unavailable."
        ),
    ),
    BRANDING: SettingSpec(
        key=BRANDING,
        default=DEFAULT_BRANDING,
        description=(
            "How the company appears on its DPRs: printed name, brand colour, GSTIN, "
            "signatory and logo. Edited through the branding page, not here."
        ),
    ),
}

# Settings with their own endpoint (GET/PUT /company/branding and the logo
# upload). The generic settings API refuses them: a hand-written logo key could
# point at another company's file.
DEDICATED_ENDPOINT_KEYS: frozenset[str] = frozenset({BRANDING})


def is_known_key(key: str) -> bool:
    return key in _SPECS


def default_for(key: str) -> object:
    """The value an org that has never configured `key` behaves as."""
    spec = _SPECS.get(key)
    if spec is None:
        raise KeyError(f"unknown organization setting: {key}")
    return spec.default


def all_specs() -> tuple[SettingSpec, ...]:
    """Every known setting — what the control panel renders its form from."""
    return tuple(_SPECS.values())


def validate_role_list(value: object) -> list[str]:
    """Coerce and validate a roles payload, raising ValueError on anything
    that isn't a list of known role names.

    Uppercases on the way in so the stored value is always canonical and the
    read path never has to case-normalize before comparing.
    """
    if not isinstance(value, list):
        raise ValueError("value must be a list of role names")
    roles: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError("value must be a list of role names")
        role = entry.strip().upper()
        if role not in VALID_ROLES:
            raise ValueError(f"unknown role: {entry}")
        if role not in roles:
            roles.append(role)
    return roles


def module_catalogue() -> list[dict[str, object]]:
    """Every module with what the control panel needs to render its switch,
    in catalogue order -- so the UI never keeps its own copy of the list."""
    return [
        {
            "key": key,
            "label": MODULE_LABELS.get(key, key),
            "description": description,
            "always_on": key in ALWAYS_ON_MODULES,
            "in_v1": key in V1_MODULES,
        }
        for key, description in MODULES.items()
    ]


def validate_module_list(value: object) -> list[str]:
    """Coerce and validate an enabled-modules payload.

    Lowercases, drops duplicates, always includes the always-on modules, and
    returns the list in catalogue order so the stored value is canonical and
    two equivalent payloads persist identically.
    """
    if not isinstance(value, list):
        raise ValueError("value must be a list of module names")
    wanted: set[str] = set(ALWAYS_ON_MODULES)
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError("value must be a list of module names")
        module = entry.strip().lower()
        if module not in MODULES:
            raise ValueError(f"unknown module: {entry}")
        wanted.add(module)
    return [module for module in MODULES if module in wanted]


def enabled_modules(stored: object) -> list[str]:
    """The canonical enabled list for a stored value.

    Defensive about the stored shape: a hand-edited or legacy row that isn't
    a valid module list falls back to the default rather than switching a
    company's modules off by accident.
    """
    try:
        return validate_module_list(stored)
    except ValueError:
        return list(DEFAULT_ENABLED_MODULES)


def module_enabled(module: str, stored: object) -> bool:
    """True if `module` is on for a company whose setting value is `stored`."""
    if module in ALWAYS_ON_MODULES:
        return True
    return module in enabled_modules(stored)


def validate(key: str, value: object) -> object:
    """Validate `value` for `key`, returning the canonical form to persist."""
    if not is_known_key(key):
        raise ValueError(f"unknown organization setting: {key}")
    if key in DEDICATED_ENDPOINT_KEYS:
        raise ValueError(f"'{key}' is set through its own page, not the settings API")
    if key == WHATSAPP_MATERIAL_CREATE_ROLES:
        return validate_role_list(value)
    if key == ENABLED_MODULES:
        return validate_module_list(value)
    return value


def role_allowed(role: str | None, allowed: object) -> bool:
    """True if `role` appears in an `allowed` roles setting value.

    Defensive about the stored shape: a hand-edited or legacy row that isn't
    a list of strings denies rather than crashes the WhatsApp reply, since
    this runs inside the inbound journey where an exception costs the user
    their whole message.
    """
    if not role or not isinstance(allowed, list):
        return False
    return role.strip().upper() in {
        str(entry).strip().upper() for entry in allowed if isinstance(entry, str)
    }
