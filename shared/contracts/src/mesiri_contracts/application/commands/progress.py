"""Progress Application Commands — the typed handoff from ConfirmedActionV2.

Placed here rather than under the backend's application package, matching
Material and Labour (see labour.py's docstring: "where Material and Expense
disagree ... follow Material" — commands are shared contract surface, not
backend-internal).

Two commands, not one, because Activity creation and a Progress Update are
structurally different acts (docs/execution/DAILY_REPORTING_PLAN.md ADR-D1,
ADR-D12): creating an Activity carries the full header (location, work
package, contractor, initial quantities); appending a Progress Update carries
only what changed at that moment, against an activity that already exists.
Collapsing them into one command with optional fields would blur exactly the
distinction P1 depends on — an Activity's header is mutable (via a
correction, see ADR-D14), a Progress Update never is.

`work_type` is free text in V1 (plan open decision #4) — no catalog exists to
validate it against, unlike Material's `material_name`. `unit`/`unit_id`
follow Material's exact resolution shape: `unit` is what the user said,
`unit_id` is filled in by the Handler's resolver
(application/progress/resolution.py) before persistence, reusing
`units_of_measure`/`unit_aliases` (0290) rather than building a second
resolution path.

Ownership: SHARED ARCHITECTURE — part of the M0 contract surface. Version: v2.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, model_validator

from mesiri_contracts.assistant.v2.uuid_scope import CanonicalUuid

CONTRACT_VERSION = "v2"


class ActivityQuantityInput(BaseModel):
    """One measured quantity reported against an Activity or a Progress Update.

    An Activity can carry zero of these (P10 — a narrative-only report is a
    valid record) or several (e.g. "180 sqm plastered, 2 doors fixed" in one
    message).
    """

    version: str = CONTRACT_VERSION

    #: Free text in V1 — see module docstring.
    work_type: str | None = None

    #: What the user said (e.g. "sqm", "bags"). Resolved to unit_id by the
    #: Handler before persistence; never resolved by AI (plan P5's sibling
    #: rule for quantities — only *planned* quantities are barred from AI
    #: inference, but unit *spelling* resolution is deterministic lookup,
    #: not inference, so it is fine to do here).
    unit: str
    unit_id: CanonicalUuid | None = None

    quantity: Decimal

    #: ACHIEVED ("180 today") vs CUMULATIVE ("1840 to date") — see plan §6.3.
    measurement_type: str = "ACHIEVED"

    model_config = {"extra": "forbid"}


class CreateActivityCommand(BaseModel):
    """Create a new Activity — the default path when no open activity matches
    (plan §1B.1, `activity_creation` graph)."""

    version: str = CONTRACT_VERSION

    command_id: str
    idempotency_key: str
    correlation_id: str

    organization_id: CanonicalUuid
    project_id: CanonicalUuid | None
    site_id: CanonicalUuid | None

    #: Nullable — P4: capture must work with zero Work Package/Location
    #: configuration. Backfillable from the dashboard later.
    work_package_id: CanonicalUuid | None = None
    location_id: CanonicalUuid | None = None

    work_type: str | None = None
    narrative: str | None = None
    contractor: str | None = None

    started_at: str | None = None  # "HH:MM", optional
    ended_at: str | None = None

    quantities: list[ActivityQuantityInput] = []

    activity_date: date
    occurred_date_source: str = "inferred_at_confirmation"

    #: "whatsapp_text" | "whatsapp_voice" | "whatsapp_image" | "dashboard" —
    #: same provenance metadata shape as Labour's `recorded_via`.
    source: str = "whatsapp_text"

    created_by: CanonicalUuid

    model_config = {"extra": "forbid"}


class AttachEvidenceCommand(BaseModel):
    """Attach one or more photos to an existing Activity as evidence (#2
    Batch Media). Distinct from CreateActivityCommand/AddProgressUpdateCommand:
    an attachment is never a draft awaiting YES/NO confirmation (a photo is
    unambiguous evidence, not a business fact someone could have misheard),
    so this command has no idempotency_key and does not travel through
    ConfirmedActionV2 -- it is dispatched directly from the WhatsApp image-
    purpose tap handler once the target activity is known, mirroring how
    interactions/image_purpose.py already holds media outside the normal
    draft/confirm machinery.

    `media_object_keys` (plural) is the whole point of this command over a
    single-attachment shape: a batch of N photos tapped "Site Update" in one
    picker answer must attach as N rows in one transaction, not N separate
    round trips each able to partially fail.
    """

    version: str = CONTRACT_VERSION

    command_id: str
    correlation_id: str

    organization_id: CanonicalUuid
    activity_id: CanonicalUuid

    media_object_keys: list[str]
    mime_type: str | None = None
    #: The reporter's own caption, if any -- a fact, never AI-generated (see
    #: migration 0430's progress_attachments docstring on the caption/
    #: ai_caption split).
    caption: str | None = None

    uploaded_by: CanonicalUuid

    model_config = {"extra": "forbid"}


class AddProgressUpdateCommand(BaseModel):
    """Append a Progress Update to an existing Activity (plan §1B.1,
    `activity_continuation` graph). Never edits the Activity or a prior
    update — P1."""

    version: str = CONTRACT_VERSION

    command_id: str
    idempotency_key: str
    correlation_id: str

    organization_id: CanonicalUuid
    activity_id: CanonicalUuid

    #: STARTED | PROGRESS | PAUSED | RESUMED | COMPLETED | NOTE
    update_kind: str

    narrative: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_id: CanonicalUuid | None = None

    occurred_at: datetime

    source: str = "whatsapp_text"

    created_by: CanonicalUuid

    model_config = {"extra": "forbid"}


class CorrectActivityQuantityCommand(BaseModel):
    """Correct a Progress Update's quantity/unit (ADR-D14: "make that 180",
    not "another 180"). Never edits `progress_update_id` in place --
    Progress Updates stay append-only (P1) even under correction. Persisting
    this appends a NEW progress_updates row carrying `supersedes_id =
    progress_update_id`; the row this corrects is never touched.

    `narrative`/`work_type` are absent on purpose: a correction only ever
    restates the number, never re-describes the work -- if the description
    was also wrong, that is an Activity header correction
    (correct_activity_fields, dashboard-only in V1), a different command
    entirely."""

    version: str = CONTRACT_VERSION

    command_id: str
    idempotency_key: str
    correlation_id: str

    organization_id: CanonicalUuid
    #: The progress_updates row being corrected -- resolved by seeding
    #: (runtime/inbound_journey.py's `_seed_correction_target`), never
    #: stated by the user.
    progress_update_id: CanonicalUuid | None = None
    #: WRK-06: or the quantity the activity was started with
    #: (``activity_quantities``), which has no progress update of its own:
    #: "180 sqm plastering" then "correction, 150". Exactly one of the two.
    activity_quantity_id: CanonicalUuid | None = None

    new_quantity: Decimal
    new_unit: str | None = None
    new_unit_id: CanonicalUuid | None = None

    reason: str | None = None
    source: str = "whatsapp_text"

    created_by: CanonicalUuid

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _one_target(self) -> CorrectActivityQuantityCommand:
        if (self.progress_update_id is None) == (self.activity_quantity_id is None):
            raise ValueError("exactly one of progress_update_id / activity_quantity_id is needed")
        return self


class ReportSiteIssueCommand(BaseModel):
    """Report a Site Issue (blocker/delay) -- always a new site_issues row,
    never a continuation of a prior one (unlike AddProgressUpdateCommand,
    there is no "same issue, more detail" concept in V1: a second report
    about the same problem is simply a second issue).

    `issue_type`/`severity` are closed enums (site_issue_type/
    site_issue_status per migration 0430) the AI extraction picks directly --
    unlike Expense's category_text, there is no org-scoped catalog to
    resolve against, so no Handler-side resolution step is needed (mirrors
    Material's `unit`/`unit_id` split NOT applying here, since there is
    nothing analogous to resolve)."""

    version: str = CONTRACT_VERSION

    command_id: str
    idempotency_key: str
    correlation_id: str

    organization_id: CanonicalUuid
    project_id: CanonicalUuid | None
    site_id: CanonicalUuid | None
    activity_id: CanonicalUuid | None = None

    issue_type: str
    severity: str = "MEDIUM"
    narrative: str | None = None
    delay_duration_minutes: int | None = None

    occurred_date: date
    occurred_date_source: str = "inferred_at_confirmation"

    source: str = "whatsapp_text"

    created_by: CanonicalUuid

    model_config = {"extra": "forbid"}


class CloseSiteIssueCommand(BaseModel):
    """Acknowledge / resolve / mark won't-fix / cancel / reopen an EXISTING
    Site Issue -- always targets "the most recently reported issue in the
    right status" (resolved by seeding, never stated by the user), mirroring
    how application/finance/reverse_commands.py's ReverseTransactionCommand
    targets "the most recent record of a kind." Unlike
    ReportSiteIssueCommand, this never creates a new row -- only
    transitions an existing one's status:

        OPEN                        -> ACKNOWLEDGED   (acknowledge)
        OPEN/ACKNOWLEDGED           -> RESOLVED       (resolve)
        OPEN/ACKNOWLEDGED           -> WONT_FIX       (wont_fix)
        OPEN/ACKNOWLEDGED           -> CANCELLED      (cancel)
        ACKNOWLEDGED/RESOLVED/WONT_FIX -> OPEN        (reopen)

    `cancel` is the withdrawal path for a report that should never have
    existed, and is deliberately a transition rather than a delete (P1).
    `reopen` is the only backwards transition, and deliberately cannot
    revive a CANCELLED issue: "that was never real" and "that isn't fixed
    after all" are different claims, and re-reporting is the honest route
    back from the first."""

    version: str = CONTRACT_VERSION

    command_id: str
    idempotency_key: str
    correlation_id: str

    organization_id: CanonicalUuid
    site_issue_id: CanonicalUuid

    #: "acknowledge" | "resolve" | "wont_fix" | "cancel" | "reopen"
    action: str
    resolution_notes: str | None = None

    created_by: CanonicalUuid

    model_config = {"extra": "forbid"}
