"""Activity Creation & Continuation workflow nodes — pure functions, no LangGraph, no I/O, no SQL.

Merges what used to be two separate workflows (site_update's "always create
a new Activity" and activity_continuation's "always append to whichever
activity_id the caller was handed") into one, per docs/execution/
ACTIVITY_RESOLUTION_AND_CORRECTION_PLAN.md. The reason: deciding
create-vs-continue purely from the extracted `update_kind` word, before any
open-activity lookup, produced two real bugs --

  F1 (wrong target): "finished plastering" appended to whichever open
  activity was most recently touched, even if it was blockwork.

  F2 (dead end): a continuation message with nothing open told the user to
  redescribe their report from scratch instead of just creating one.

`resolve_target` is the fix: it scores every open activity
(runtime/inbound_journey.py's `_seed_open_activity` seeds the candidate
list, same "a node must never query a repository itself" rule every other
resolution gate in this repo follows) against this message's own
`work_type`, via workflows/site_update/matching.py, and only asks when
there is genuine ambiguity. `build_draft` then branches on whether that
resolution left `activity_id` set.

Field names read here (`work_type`, `quantities`, `narrative`,
`location_id`, `work_package_id`, `contractor`, `activity_date`,
`activity_id`, `update_kind`, `quantity`, `unit`) are exactly what
application/progress/mapper.py's `build_create_activity_command` /
`build_add_progress_update_command` read out of
`confirmed.draft_action.fields` -- this is the one place upstream of that
mapper that decides the field names, so a rename on either side must change
both.
"""

from __future__ import annotations

import re
from datetime import date

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id

from ..readable import field_lines
from ..slots import RETRY_PREFIX, SlotCandidate, match_slot_answer, slot_options
from ..state import WorkflowGraphState
from .matching import ActivityCandidate, MatchOutcome
from .matching import resolve_target as score_open_activities

_TARGET_SLOT_NAME = "activity_target"
#: Chosen when the user says none of the offered candidates are right --
#: always offered alongside them (see `_to_slot_candidates`), since a picker
#: that could only ever pick an existing activity would have no way to
#: correct a wrong guess about there being an ambiguity at all.
NEW_ACTIVITY_SENTINEL = "new_activity"
_NEW_WORK_LABEL = "This is new work"

#: `match_slot_answer` (workflows/slots.py) only matches whole-string
#: substring containment, so a reply that wraps the intended choice in
#: justification -- "New cause it's 3rd floor" -- fails to match either
#: candidate label and falls through to a re-ask, even though the user
#: unambiguously picked the escape hatch. Since no other candidate label on
#: this picker ever contains the standalone word "new" (they're work-type/
#: narrative summaries), a bare "new" anywhere in the reply is treated as
#: this one, checked only after the generic matcher comes up empty.
_NEW_WORK_PATTERN = re.compile(r"\bnew\b", re.IGNORECASE)

#: WA-03 (quiet daytime): set by seeding for a company that saves first. An
#: unclear "open work or new work?" is then saved as new work instead of
#: asked; the engineer sees both on the evening report.
UNCLEAR_TARGET_IS_NEW_KEY = "_unclear_target_is_new"

#: Plumbing carried through collected_fields between passes -- never a real
#: business field, must never reach draft.fields or the confirmation prompt.
_RESOLUTION_PLUMBING_KEYS = frozenset(
    {
        "_open_activity_candidates",
        "_target_resolved",
        "_slot_answer_text",
        UNCLEAR_TARGET_IS_NEW_KEY,
    }
)


def _candidate_label(work_type: str | None, narrative: str | None) -> str:
    bits = [b for b in (work_type, narrative) if b]
    return " — ".join(bits) if bits else "Untitled activity"


def _to_slot_candidates(items) -> list[SlotCandidate]:
    """Build the picker's choices from anything shaped like an activity
    (ActivityCandidate or matching.ScoredActivity both qualify -- same three
    attributes). Always ends with the "this is new work" escape hatch."""
    options = [
        SlotCandidate(value=item.activity_id, label=_candidate_label(item.work_type, item.narrative))
        for item in items
    ]
    options.append(SlotCandidate(value=NEW_ACTIVITY_SENTINEL, label=_NEW_WORK_LABEL))
    return options


def _build_target_prompt(items) -> str:
    lines = ["Which work is this about?", ""]
    lines.extend(
        f"{i}. {_candidate_label(item.work_type, item.narrative)}" for i, item in enumerate(items, start=1)
    )
    lines.append(f"{len(items) + 1}. {_NEW_WORK_LABEL}")
    lines.append("")
    lines.append("Reply with a number, or just tell me which one.")
    return "\n".join(lines)


def _raw_candidates(fields: dict) -> list[ActivityCandidate]:
    """The open-activity list seeded by runtime/inbound_journey.py's
    `_seed_open_activity`, as plain JSON-safe dicts (this state is persisted
    with model_dump_json() between messages, so nothing richer survives)."""
    raw = fields.get("_open_activity_candidates") or []
    return [
        ActivityCandidate(
            activity_id=str(c["activity_id"]), work_type=c.get("work_type"), narrative=c.get("narrative")
        )
        for c in raw
        if isinstance(c, dict) and c.get("activity_id")
    ]


def _apply_match(fields: dict, *, activity_id: str, work_type: str | None, narrative: str | None) -> dict:
    resolved = dict(fields)
    resolved["activity_id"] = activity_id
    summary_bits = [b for b in (work_type, narrative) if b]
    if summary_bits:
        resolved["activity_summary"] = " — ".join(summary_bits)
    resolved["_target_resolved"] = True
    resolved.pop("_open_activity_candidates", None)
    return resolved


def resolve_target(state: WorkflowGraphState) -> dict:
    """Decide whether this message continues an open Activity or starts a
    new one. See module docstring for what this replaces and why.

    Already resolved (a remembered activity_id already won outright during
    seeding -- see runtime/inbound_journey.py's `_seed_open_activity`
    docstring on precedence -- or a prior pass in this same run already
    decided) -> no-op.

    Otherwise scores every seeded candidate against this message's own
    work_type/update_kind (workflows/site_update/matching.py).
    AUTO_MATCHED sets activity_id silently; NO_MATCH leaves it unset
    (build_draft then creates a new Activity -- the fix for F2); ASK_USER
    sets awaiting_slot and ends this pass with a picker that always
    includes "this is new work" (the fix for F1: a clash or real ambiguity
    must never resolve to a silent guess).
    """
    fields = dict(state.get("collected_fields") or {})
    if fields.get("activity_id") or fields.get("_target_resolved"):
        return {"collected_fields": fields}

    candidates = _raw_candidates(fields)
    answer_text = fields.pop("_slot_answer_text", None)

    if answer_text is not None:
        options = _to_slot_candidates(candidates)
        matched = match_slot_answer(answer_text, options)
        if matched is None and _NEW_WORK_PATTERN.search(answer_text):
            matched = NEW_ACTIVITY_SENTINEL
        if matched is None:
            return {
                "collected_fields": fields,
                "awaiting_slot": _TARGET_SLOT_NAME,
                "awaiting_slot_options": slot_options(options),
                "pending_prompt": f"{RETRY_PREFIX}\n\n{_build_target_prompt(candidates)}",
            }
        if matched == NEW_ACTIVITY_SENTINEL:
            fields["_target_resolved"] = True
            fields.pop("_open_activity_candidates", None)
            return {"collected_fields": fields, "awaiting_slot": None}
        chosen = next(c for c in candidates if c.activity_id == matched)
        return {
            "collected_fields": _apply_match(
                fields, activity_id=chosen.activity_id, work_type=chosen.work_type, narrative=chosen.narrative
            ),
            "awaiting_slot": None,
        }

    result = score_open_activities(
        message_work_type=fields.get("work_type"),
        update_kind=fields.get("update_kind"),
        candidates=candidates,
    )

    if result.outcome is MatchOutcome.AUTO_MATCHED:
        best = result.candidates[0]
        return {
            "collected_fields": _apply_match(
                fields, activity_id=best.activity_id, work_type=best.work_type, narrative=best.narrative
            )
        }
    if result.outcome is MatchOutcome.NO_MATCH:
        fields["_target_resolved"] = True
        fields.pop("_open_activity_candidates", None)
        return {"collected_fields": fields}

    # ASK_USER -- unless this company saves first (WA-03): then new work.
    if fields.pop(UNCLEAR_TARGET_IS_NEW_KEY, False):
        fields["_target_resolved"] = True
        fields.pop("_open_activity_candidates", None)
        return {"collected_fields": fields}
    options = _to_slot_candidates(result.candidates)
    return {
        "collected_fields": fields,
        "awaiting_slot": _TARGET_SLOT_NAME,
        "awaiting_slot_options": slot_options(options),
        "pending_prompt": _build_target_prompt(result.candidates),
    }


def build_draft(state: WorkflowGraphState) -> dict:
    """Map collected fields into a DraftAction. Shape-mapping only — no
    validation. Branches on whether `resolve_target` left `activity_id`
    set: present -> append a Progress Update to that Activity; absent ->
    create a new one."""
    fields = {
        key: value
        for key, value in (state.get("collected_fields") or {}).items()
        if key not in _RESOLUTION_PLUMBING_KEYS
    }
    if fields.get("activity_id"):
        return _build_continuation_draft(state, fields)
    return _build_creation_draft(state, fields)


def _build_creation_draft(state: WorkflowGraphState, fields: dict) -> dict:
    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.CREATE_ACTIVITY,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=state.get("project_id"),
        site_id=state.get("site_id"),
        fields=fields,
    )
    return {"draft_action": draft}


def _build_continuation_draft(state: WorkflowGraphState, fields: dict) -> dict:
    """`AddProgressUpdateCommand.quantity`/`.unit` are singular
    (application/progress/mapper.py's `build_add_progress_update_command`),
    but general_site_update extraction always fills the plural `quantities`
    array (platform/ai's extraction prompt has no singular-quantity shape at
    all) -- so a continuation message stating an amount via that array
    silently lost it before this fold existed. V1 takes the first quantity
    line only: AddProgressUpdateCommand has no way to carry more than one
    (a real gap if a continuation message ever states two unrelated
    quantities in one message, which P10 narrative-only capture makes rare
    enough to accept for now)."""
    folded = dict(fields)
    if folded.get("quantity") is None:
        raw_quantities = folded.get("quantities")
        if isinstance(raw_quantities, list) and raw_quantities:
            first = raw_quantities[0]
            if isinstance(first, dict):
                folded.setdefault("quantity", first.get("quantity"))
                folded.setdefault("unit", first.get("unit"))
    folded.pop("quantities", None)

    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.ADD_PROGRESS_UPDATE,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=state.get("project_id"),
        site_id=state.get("site_id"),
        fields=folded,
    )
    return {"draft_action": draft}


def request_confirmation(state: WorkflowGraphState) -> dict:
    """Compose the confirmation prompt — the gate nothing is persisted
    before (principle P2). Branches on the draft's action_type, since
    creation and continuation show different shapes."""
    draft: DraftActionV2 = state["draft_action"]
    if draft.action_type is DraftActionType.ADD_PROGRESS_UPDATE:
        return _request_continuation_confirmation(draft)
    return _request_creation_confirmation(draft)


# --- Creation confirmation ---------------------------------------------------

# Rendered by dedicated lines below (quantities as a bulleted list, the date
# with its "(assumed today)" qualifier), not as raw key:value lines -- shown
# unformatted they would be unreadable exactly when the user most needs to
# check them. Internal plumbing fields are hidden outright.
_CREATION_DISPLAY_HIDDEN_FIELD_KEYS = frozenset(
    {
        "quantities",
        "occurred_date",
        "occurred_date_source",
        "project_name",
        "site_name",
        "location_name",
        "work_package_name",
        "source",
        "work_type",
        "contractor",
        "narrative",
        "progress_percent",
    }
)


def _date_line(fields: dict) -> str | None:
    """The day being recorded, marked when Mesiri guessed it. Same reasoning
    as Material's and Labour's equivalents (workflows/material/nodes.py,
    workflows/labour_update/nodes.py): a Progress Update can only append a
    correction, never edit the Activity's date, so confirmation is the one
    cheap moment to catch a wrong guess.

    Reads `occurred_date` (not `activity_date`, the DB column name) --
    canonicalization/occurred_date.py writes `occurred_date`/
    `occurred_date_source` onto every module's fields uniformly; `activity_date`
    is a Progress-specific rename that only happens later, in
    application/progress/mapper.py's `_activity_date`."""
    raw = str(fields.get("occurred_date") or "").strip()
    if not raw:
        return None
    try:
        shown = date.fromisoformat(raw).strftime("%d %b %Y")
    except ValueError:
        shown = raw
    if str(fields.get("occurred_date_source") or "") == "inferred_at_confirmation":
        return f"   • Date: {shown} (assumed today)"
    return f"   • Date: {shown}"


def _quantity_line(entry: dict) -> str | None:
    quantity = entry.get("quantity")
    unit = entry.get("unit")
    if quantity is None or not unit:
        return None
    work_type = entry.get("work_type")
    label = f"{quantity} {unit}"
    if work_type:
        label = f"{label} {work_type}"
    return f"   • {label}"


def _request_creation_confirmation(draft: DraftActionV2) -> dict:
    """Project, site, location and work package are shown by name when the
    caller seeded them (`*_name` fields, mirroring Labour's project_name/
    site_name convention) and omitted otherwise: a bare UUID is worse than
    saying nothing, and a nullable location/work package (P4) is a normal,
    expected state for this confirmation to render correctly regardless."""
    fields = draft.fields

    out = ["*Confirm this record?*", "", "🏗️ Site Activity"]

    project_name = fields.get("project_name")
    site_name = fields.get("site_name")
    location_name = fields.get("location_name")
    work_package_name = fields.get("work_package_name")
    if project_name:
        out.append(f"   • Project: {project_name}")
    if site_name:
        out.append(f"   • Site: {site_name}")
    if location_name:
        out.append(f"   • Location: {location_name}")
    if work_package_name:
        out.append(f"   • Work Package: {work_package_name}")
    date_line = _date_line(fields)
    if date_line:
        out.append(date_line)

    work_type = fields.get("work_type")
    if work_type:
        out.append(f"   • Work: {work_type}")
    contractor = fields.get("contractor")
    if contractor:
        out.append(f"   • Contractor: {contractor}")
    if fields.get("progress_percent") is not None:
        out.append(f"   • Progress: {fields['progress_percent']}%")

    narrative = fields.get("narrative")
    if narrative:
        out.append("")
        out.append(f"   \"{narrative}\"")

    quantities = fields.get("quantities")
    if isinstance(quantities, list) and quantities:
        out.append("")
        for entry in quantities:
            if isinstance(entry, dict):
                line = _quantity_line(entry)
                if line:
                    out.append(line)

    out.extend(field_lines(fields, skip=_CREATION_DISPLAY_HIDDEN_FIELD_KEYS))

    out.append("")
    out.append("Reply YES to confirm or NO to cancel.")
    return {"pending_prompt": "\n".join(out)}


# --- Continuation confirmation -----------------------------------------------

_UPDATE_KIND_LABEL: dict[str, str] = {
    "STARTED": "Started",
    "PROGRESS": "Progress update",
    "PAUSED": "Paused",
    "RESUMED": "Resumed",
    "COMPLETED": "Completed",
    "NOTE": "Note",
}

_CONTINUATION_DISPLAY_HIDDEN_FIELD_KEYS = frozenset(
    {
        "activity_id",
        "update_kind",
        "quantity",
        "unit",
        "unit_id",
        "narrative",
        "activity_summary",
        "progress_percent",
        "occurred_at",
        "occurred_date_source",
        "source",
    }
)


def _request_continuation_confirmation(draft: DraftActionV2) -> dict:
    fields = draft.fields

    kind = str(fields.get("update_kind") or "PROGRESS").upper()
    label = _UPDATE_KIND_LABEL.get(kind, "Progress update")

    out = ["*Confirm this update?*", "", f"🏗️ {label}"]

    activity_summary = fields.get("activity_summary")
    if activity_summary:
        out.append(f"   • Activity: {activity_summary}")

    narrative = fields.get("narrative")
    if narrative:
        out.append("")
        out.append(f'   "{narrative}"')

    quantity = fields.get("quantity")
    unit = fields.get("unit")
    if quantity is not None and unit:
        out.append("")
        out.append(f"   • {quantity} {unit}")
    if fields.get("progress_percent") is not None:
        out.append(f"   • Progress: {fields['progress_percent']}%")

    out.extend(field_lines(fields, skip=_CONTINUATION_DISPLAY_HIDDEN_FIELD_KEYS))

    out.append("")
    out.append("Reply YES to confirm or NO to cancel.")
    return {"pending_prompt": "\n".join(out)}
