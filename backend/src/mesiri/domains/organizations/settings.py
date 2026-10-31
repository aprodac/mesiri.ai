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
VALID_ROLES: frozenset[str] = frozenset({"ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE"})

# Which roles may create a materials_catalog entry directly from a WhatsApp
# report (STA-139). Default is every role (owner decision, request 159, 30 Oct
# 2026): a material that came in or was used is added right there, after a
# "same as <listed material>?" check against typos. An org can narrow the list.
WHATSAPP_MATERIAL_CREATE_ROLES = "whatsapp_material_create_roles"
FINANCE_SETTINGS = "finance_settings"
LABOUR_SETTINGS = "labour_settings"
ENABLED_MODULES = "enabled_modules"
# Letterhead details and logo (BE-20); rules in domains/organizations/branding.py.
BRANDING = "branding"
# Daily setup questions (SS-14); rules in domains/organizations/setup_questions.py.
SETUP_PROGRESS = "setup_progress"
BRANDING_REQUESTS = "branding_requests"
# "Continue after the trial" requests (SS-08); rules in trial_notices.py.
CONTINUE_REQUESTS = "continue_requests"
# The dashboard's getting-started card (SS-07/SS-19): hidden for the company
# until a time, so "Hide for now" holds for every admin and browser.
GETTING_STARTED = "getting_started"
# Joining a company by code (SS-05); rules in domains/organizations/team_join.py.
JOIN_CODE = "join_code"
JOIN_REQUESTS = "join_requests"
# How WhatsApp updates are saved (WA-01). "save_first": saved straight away as
# a draft the engineer confirms with the evening DPR (decided 13 Oct 2026, on
# for every company). "confirm_first": the old "Confirm? YES/NO" before
# saving -- kept as a per-company switch back, not deleted.
CAPTURE_MODE = "capture_mode"
CAPTURE_MODE_SAVE_FIRST = "save_first"
CAPTURE_MODE_CONFIRM_FIRST = "confirm_first"
CAPTURE_MODES: frozenset[str] = frozenset({CAPTURE_MODE_SAVE_FIRST, CAPTURE_MODE_CONFIRM_FIRST})
# One draft per open card, written only on the Save tap (request 124, P1;
# docs/architecture/ADR-draft-per-message.md). Off for every company until the
# Mesiri team switches it on for one.
DRAFT_V2 = "draft_v2"

# Which agent handles a company's WhatsApp messages (request 174, v2 pilot).
# "classic" (the default, and what every unreadable value means): today's agent only.
# "v2_shadow": today's agent replies; the v2 materials agent then runs on the side,
# saves nothing and only logs its proposed card. "v2" (request 180): ONE agent reads every
# plain message, decides and writes its own reply; the old code is only its tools.
# "v2_materials" is the older name of the same mode and is still accepted (it reads as "v2").
# Changed by the Mesiri team only.
ASSISTANT_MODE = "assistant_mode"
ASSISTANT_MODE_CLASSIC = "classic"
ASSISTANT_MODE_V2_SHADOW = "v2_shadow"
ASSISTANT_MODE_V2_MATERIALS = "v2_materials"  # alias of ASSISTANT_MODE_V2
ASSISTANT_MODE_V2 = "v2"
ASSISTANT_MODES: frozenset[str] = frozenset(
    {ASSISTANT_MODE_CLASSIC, ASSISTANT_MODE_V2_SHADOW, ASSISTANT_MODE_V2, ASSISTANT_MODE_V2_MATERIALS}
)

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
SUPERADMIN_ONLY_KEYS: frozenset[str] = frozenset(
    {ENABLED_MODULES, CAPTURE_MODE, DRAFT_V2, ASSISTANT_MODE}
)

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
        # Request 159 (owner, 30 Oct 2026): everyone may add a material from
        # WhatsApp, asked right where it came in or was used. An org that saved
        # its own list keeps it.
        default=["ADMIN", "FINANCE", "PROJECT_MANAGER", "SITE_ENGINEER"],
        description=(
            "Roles allowed to add a new material to the catalog directly from a "
            "WhatsApp report (every role by default). Anyone else is told to ask "
            "their admin."
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
    CAPTURE_MODE: SettingSpec(
        key=CAPTURE_MODE,
        default=CAPTURE_MODE_SAVE_FIRST,
        description=(
            "How WhatsApp updates are saved: 'save_first' (saved straight away as a "
            "draft, confirmed with the evening DPR) or 'confirm_first' (asks "
            "'Confirm?' before saving). Changed by the Mesiri team only."
        ),
    ),
    DRAFT_V2: SettingSpec(
        key=DRAFT_V2,
        default=True,
        description=(
            "true (the default for every company since request 136, 28 Oct): a WhatsApp "
            "message is held as one draft card and written only when the sender taps Save "
            "(Cancel writes nothing). false: the old flow, kept only as the per-company off "
            "switch. Changed by the Mesiri team only."
        ),
    ),
    ASSISTANT_MODE: SettingSpec(
        key=ASSISTANT_MODE,
        default=ASSISTANT_MODE_CLASSIC,
        description=(
            "Which agent answers WhatsApp messages: 'classic' (today's agent, the default), "
            "'v2_shadow' (today's agent replies; the v2 materials agent runs after it, saves "
            "nothing and only logs what it would have proposed) or 'v2' (one agent reads every "
            "message and writes its own reply; 'v2_materials' is the same mode under its old "
            "name). Changed by the Mesiri team only."
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
    SETUP_PROGRESS: SettingSpec(
        key=SETUP_PROGRESS,
        default={},
        description=(
            "Which daily setup questions WhatsApp has asked the owner, and their "
            "answers. Written by the assistant only."
        ),
    ),
    BRANDING_REQUESTS: SettingSpec(
        key=BRANDING_REQUESTS,
        default=[],
        description=(
            "Letterhead, visiting card and logo files the owner sent on WhatsApp for "
            "the Mesiri team to set up. Handled from the control panel."
        ),
    ),
    JOIN_CODE: SettingSpec(
        key=JOIN_CODE,
        default=None,
        description=(
            "The code people send on WhatsApp (JOIN ACME-4821) to ask to join this "
            "company. Shown to admins and project managers on WhatsApp ('join code')."
        ),
    ),
    JOIN_REQUESTS: SettingSpec(
        key=JOIN_REQUESTS,
        default=[],
        description=(
            "People who asked to join with the company's code, waiting for an admin "
            "to approve or reject them on WhatsApp."
        ),
    ),
    GETTING_STARTED: SettingSpec(
        key=GETTING_STARTED,
        default={},
        description=(
            "The dashboard's getting-started card: hidden_until, when an admin chose "
            "'Hide for now'. Written through /company/setup-progress only."
        ),
    ),
    CONTINUE_REQUESTS: SettingSpec(
        key=CONTINUE_REQUESTS,
        default=[],
        description=(
            "Requests from a trial company to keep using Mesiri (WhatsApp or dashboard). "
            "The Mesiri team converts the company to paid from the control panel."
        ),
    ),
}

# Settings with their own endpoint (GET/PUT /company/branding and the logo
# upload), or written only by the assistant (SS-14). The generic settings API
# refuses them: a hand-written logo key could point at another company's file.
DEDICATED_ENDPOINT_KEYS: frozenset[str] = frozenset(
    {
        BRANDING,
        SETUP_PROGRESS,
        BRANDING_REQUESTS,
        CONTINUE_REQUESTS,
        JOIN_CODE,
        JOIN_REQUESTS,
        GETTING_STARTED,
    }
)


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
    if key == CAPTURE_MODE:
        mode = str(value).strip().lower() if isinstance(value, str) else ""
        if mode not in CAPTURE_MODES:
            raise ValueError(f"capture_mode must be one of {sorted(CAPTURE_MODES)}")
        return mode
    if key == DRAFT_V2:
        if not isinstance(value, bool):
            raise ValueError("draft_v2 must be true or false")
        return value
    if key == ASSISTANT_MODE:
        mode = str(value).strip().lower() if isinstance(value, str) else ""
        if mode not in ASSISTANT_MODES:
            raise ValueError(f"assistant_mode must be one of {sorted(ASSISTANT_MODES)}")
        return ASSISTANT_MODE_V2 if mode == ASSISTANT_MODE_V2_MATERIALS else mode
    return value


def assistant_mode(stored: object) -> str:
    """The company's agent mode. Anything unset, unreadable or from before this
    setting's values ("agent", "off") is "classic": production is unchanged."""
    mode = stored.strip().lower() if isinstance(stored, str) else ""
    if mode == ASSISTANT_MODE_V2_MATERIALS:
        return ASSISTANT_MODE_V2  # the old name of the same mode (no data migration)
    return mode if mode in ASSISTANT_MODES else ASSISTANT_MODE_CLASSIC


def draft_v2_enabled(stored: object) -> bool:
    """On for every company (request 136) unless its setting is exactly ``false``,
    the Mesiri team's per-company off switch. Unset or unreadable is on."""
    return stored is not False


def saves_first(stored: object) -> bool:
    """True unless the company was switched back to confirm-first. Anything
    unreadable counts as the default (save first), never as an error."""
    return stored != CAPTURE_MODE_CONFIRM_FIRST


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
