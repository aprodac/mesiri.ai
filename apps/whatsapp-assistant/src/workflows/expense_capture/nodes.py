"""Expense capture workflow nodes — pure functions, no LangGraph, no I/O, no SQL, no domain rules.

Mirrors workflows/material/nodes.py. Each node takes the graph's working
state and returns the partial update LangGraph merges in. Shape-mapping
only — amount>0 and category resolution belong to the Application/Domain
layer (see backend's application/expenses/{validation.py,resolution.py}),
not here.

`resolve_account` is Finance Module Slice 1's "which account?" slot: account
candidates are seeded into `collected_fields['account_candidates']` by the
caller (a node must never query a repository itself -- see
runtime/money_account_query.py and workflows/runtime.py's docstring), and
"my own pocket" is always appended as an extra choice so paying personally
is a first-class answer, not merely an omitted account. See
docs/execution/FINANCE_MODULE_PLAN.md's Slice 1.

Every `SlotCandidate.label` in this module must stay <=24 chars: it doubles
as a WhatsApp interactive list-row title, and
runtime/inbound_journey.py::_render_reply degrades the whole question to
plain numbered text (no tappable list at all) the moment any one label in
the set is too long, rather than truncate it and risk a tapped row no
longer matching its own candidate. A too-long own-pocket/vendor-confirm
label silently broke this for every user until 2026-07-26 -- see git
history around that date.

`check_duplicate` is Finance Module Slice 8's "looks like a duplicate,
record anyway?" gate: whether a likely-duplicate confirmed expense already
exists is decided by the caller (runtime/inbound_journey.py's
`_seed_duplicate_check`, same "a node must never query a repository itself"
rule) and seeded as `collected_fields['is_potential_duplicate']`. This node
only asks the yes/no question -- reusing the same single-choice slot
machinery as resolve_account, since a genuine yes/no is just an N=2 choice --
and, uniquely among this graph's nodes, can end the whole workflow with no
draft at all when the answer is "no" (see graph.py's routing).

`resolve_vendor` is the "vendor not found, create it?" gate: whether the
extracted vendor name matches an existing active vendor is decided by the
caller (runtime/inbound_journey.py's `_seed_vendor_check`, same rule) and
seeded as `collected_fields['vendor_needs_confirmation']`. Reuses the same
yes/no slot machinery as check_duplicate. Unlike check_duplicate, "no" never
cancels the whole record -- it just drops the vendor from the draft (so
application/expenses/resolution.py resolves vendor_id=None instead of
auto-creating), matching the user's explicit request that this must never
block the expense itself. "yes" leaves the vendor field untouched, letting
the resolver's existing create-on-first-use behavior create it exactly as
before.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id

from ..readable import field_lines
from ..slots import SlotCandidate, match_slot_answer, resolve_single_choice_slot, slot_options
from ..state import WorkflowGraphState

OWN_POCKET_SENTINEL = "own_pocket"
_ACCOUNT_SLOT_NAME = "account_id"
_ACCOUNT_PROMPT_TITLE = "Which account did you pay from?"
_OWN_POCKET_LABEL = "My own pocket"


def _account_candidates(raw_candidates: list[dict[str, Any]]) -> list[SlotCandidate]:
    candidates = [SlotCandidate(value=str(c["id"]), label=str(c["name"])) for c in raw_candidates]
    candidates.append(SlotCandidate(value=OWN_POCKET_SENTINEL, label=_OWN_POCKET_LABEL))
    return candidates


def _apply_account_choice(value: str, fields: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(fields)
    if value == OWN_POCKET_SENTINEL:
        resolved["paid_from_own_pocket"] = True
    else:
        resolved["account_id"] = value
    return resolved


def resolve_account(state: WorkflowGraphState) -> dict:
    """Resolve the paid-from choice, asking only when genuinely ambiguous.

    Already resolved (account_id or paid_from_own_pocket already set) ->
    no-op. Otherwise builds the candidate list (real accounts + the always-
    present own-pocket sentinel) and either auto-fills (0 real accounts ->
    own pocket is the only choice), consumes a pending slot answer
    (`_slot_answer_text`, set by WorkflowRuntime.provide_input on resume),
    or asks.
    """
    fields = dict(state.get("collected_fields") or {})
    if fields.get("account_id") is not None or fields.get("paid_from_own_pocket"):
        return {}

    raw_candidates = fields.get("account_candidates") or []
    candidates = _account_candidates(raw_candidates)
    answer_text = fields.pop("_slot_answer_text", None)

    if answer_text is not None:
        matched = match_slot_answer(answer_text, candidates)
        if matched is not None:
            return {"collected_fields": _apply_account_choice(matched, fields), "awaiting_slot": None}
        # No match -- re-ask with the same choices, distinguishing the retry
        # so the user knows their reply wasn't understood rather than
        # silently seeing the identical prompt twice.
        resolution = resolve_single_choice_slot(
            slot_name=_ACCOUNT_SLOT_NAME,
            prompt_title=f"Sorry, I didn't catch that. {_ACCOUNT_PROMPT_TITLE}",
            candidates=candidates,
        )
        return {
            "collected_fields": fields,
            "awaiting_slot": resolution.awaiting_slot,
            "awaiting_slot_options": slot_options(candidates),
            "pending_prompt": resolution.slot_prompt,
        }

    resolution = resolve_single_choice_slot(
        slot_name=_ACCOUNT_SLOT_NAME, prompt_title=_ACCOUNT_PROMPT_TITLE, candidates=candidates
    )
    if resolution.resolved_value is not None:
        resolved = _apply_account_choice(resolution.resolved_value, fields)
        if not raw_candidates:
            # No company account exists, so own pocket is the only place this
            # can be recorded -- not a choice the sender made. Saying so in the
            # confirmation beats silently showing "own pocket".
            resolved["own_pocket_assumed"] = True
        return {"collected_fields": resolved}
    return {
        "collected_fields": fields,
        "awaiting_slot": resolution.awaiting_slot,
        "awaiting_slot_options": slot_options(candidates),
        "pending_prompt": resolution.slot_prompt,
    }


_DUPLICATE_SLOT_NAME = "duplicate_confirm"
_DUPLICATE_PROMPT_TITLE = (
    "⚠️ This looks like a duplicate of an expense you already recorded today. Record it anyway?"
)
_DUPLICATE_CANDIDATES = [
    SlotCandidate(value="yes", label="Yes, record it anyway"),
    SlotCandidate(value="no", label="No, cancel"),
]
_NOT_RECORDED_REPLY = "Ok, I won't record that expense."


def check_duplicate(state: WorkflowGraphState) -> dict:
    """Ask "record anyway?" only when the caller flagged a likely duplicate
    and it hasn't been answered yet. Not a duplicate (or already answered)
    -> no-op, straight through to build_draft. `resolve_single_choice_slot`
    with exactly 2 candidates always asks (never auto-fills) -- there is no
    scenario where a genuine yes/no question should be skipped."""
    fields = dict(state.get("collected_fields") or {})
    if fields.get("duplicate_confirmed") is not None or not fields.get("is_potential_duplicate"):
        return {}

    is_awaiting_this_slot = state.get("awaiting_slot") == _DUPLICATE_SLOT_NAME
    if is_awaiting_this_slot:
        answer_text = fields.pop("_slot_answer_text", None)
        if answer_text is not None:
            matched = match_slot_answer(answer_text, _DUPLICATE_CANDIDATES)
            if matched is not None:
                if matched == "no":
                    return {
                        "collected_fields": {**fields, "duplicate_confirmed": "no"},
                        "awaiting_slot": None,
                        "pending_prompt": _NOT_RECORDED_REPLY,
                    }
                return {
                    "collected_fields": {**fields, "duplicate_confirmed": "yes"},
                    "awaiting_slot": None,
                }
            resolution = resolve_single_choice_slot(
                slot_name=_DUPLICATE_SLOT_NAME,
                prompt_title=f"Sorry, I didn't catch that. {_DUPLICATE_PROMPT_TITLE}",
                candidates=_DUPLICATE_CANDIDATES,
            )
            return {
                "collected_fields": fields,
                "awaiting_slot": resolution.awaiting_slot,
                "awaiting_slot_options": slot_options(_DUPLICATE_CANDIDATES),
                "pending_prompt": resolution.slot_prompt,
            }

    resolution = resolve_single_choice_slot(
        slot_name=_DUPLICATE_SLOT_NAME,
        prompt_title=_DUPLICATE_PROMPT_TITLE,
        candidates=_DUPLICATE_CANDIDATES,
    )
    return {
        "collected_fields": fields,
        "awaiting_slot": resolution.awaiting_slot,
        "awaiting_slot_options": slot_options(_DUPLICATE_CANDIDATES),
        "pending_prompt": resolution.slot_prompt,
    }


_VENDOR_SLOT_NAME = "vendor_confirm"
_VENDOR_ADD_NEW = "yes"
_VENDOR_SKIP = "no"
_VENDOR_CANDIDATES = [
    SlotCandidate(value=_VENDOR_ADD_NEW, label="Yes, add new vendor"),
    SlotCandidate(value=_VENDOR_SKIP, label="No, skip vendor"),
]


def _vendor_choices(fields: dict) -> list[SlotCandidate]:
    """The rows to offer for an unmatched vendor.

    With no near-matches this is the original Yes/No pair. With near-matches
    seeded by _seed_vendor_check (Phase 4), each one leads, followed by the
    SAME two rows -- "add new" and "skip" are the escape hatches, and Phase
    3's lesson (ENTITY_RESOLUTION_PLAN.md §5.1) is that an Ambiguous the user
    cannot decline is a trap, not a question. Here that matters twice over:
    picking a suggested vendor is not a cosmetic choice, it decides which
    business this spend is attributed to.

    A candidate's `value` is its display name rather than its id because
    match_slot_answer matches on the row's label, and the answer is used
    directly as the vendor name -- the backend re-matches by exact name
    (application/vendors/resolution.py), so the name is the useful identifier
    here, not the uuid.
    """
    seeded = fields.get("vendor_candidates")
    if not isinstance(seeded, list) or not seeded:
        return _VENDOR_CANDIDATES
    suggestions = [
        SlotCandidate(value=str(c["label"]), label=str(c["label"]))
        for c in seeded
        if isinstance(c, dict) and c.get("label")
    ]
    if not suggestions:
        return _VENDOR_CANDIDATES
    return [*suggestions, *_VENDOR_CANDIDATES]


def _vendor_prompt(vendor_name: str, has_suggestions: bool = False) -> str:
    if has_suggestions:
        return (
            f'I don\'t have "{vendor_name}" as a vendor. Did you mean one of these?'
        )
    return f'I don\'t have "{vendor_name}" as a vendor yet. Add it as a new vendor?'


def _vendor_answer(matched: str, fields: dict) -> dict:
    """Apply a settled vendor answer. `matched` is either one of the two
    control values or an existing vendor's exact name."""
    if matched == _VENDOR_SKIP:
        resolved = dict(fields)
        resolved.pop("vendor", None)
        resolved["vendor_confirmed"] = "no"
        return {"collected_fields": resolved, "awaiting_slot": None}
    resolved = dict(fields)
    if matched != _VENDOR_ADD_NEW:
        # An existing vendor was chosen -- adopt its exact stored spelling so
        # the backend resolver matches it instead of creating a duplicate.
        resolved["vendor"] = matched
    resolved["vendor_confirmed"] = "yes"
    return {"collected_fields": resolved, "awaiting_slot": None}


def resolve_vendor(state: WorkflowGraphState) -> dict:
    """Settle an unmatched vendor name before the draft is built -- either by
    adopting one of the near-matches _seed_vendor_check found, adding it as a
    new vendor, or dropping it. No flag (vendor omitted, or it resolved
    exactly) or already answered -> no-op, straight through to build_draft."""
    fields = dict(state.get("collected_fields") or {})
    if fields.get("vendor_confirmed") is not None or not fields.get("vendor_needs_confirmation"):
        return {}

    vendor_name = str(fields.get("vendor") or "").strip()
    if not vendor_name:
        return {}

    choices = _vendor_choices(fields)
    prompt_title = _vendor_prompt(vendor_name, has_suggestions=choices is not _VENDOR_CANDIDATES)

    is_awaiting_this_slot = state.get("awaiting_slot") == _VENDOR_SLOT_NAME
    if is_awaiting_this_slot:
        answer_text = fields.pop("_slot_answer_text", None)
        if answer_text is not None:
            matched = match_slot_answer(answer_text, choices)
            if matched is not None:
                return _vendor_answer(matched, fields)
            resolution = resolve_single_choice_slot(
                slot_name=_VENDOR_SLOT_NAME,
                prompt_title=f"Sorry, I didn't catch that. {prompt_title}",
                candidates=choices,
            )
            return {
                "collected_fields": fields,
                "awaiting_slot": resolution.awaiting_slot,
                "awaiting_slot_options": slot_options(choices),
                "pending_prompt": resolution.slot_prompt,
            }

    resolution = resolve_single_choice_slot(
        slot_name=_VENDOR_SLOT_NAME, prompt_title=prompt_title, candidates=choices
    )
    return {
        "collected_fields": fields,
        "awaiting_slot": resolution.awaiting_slot,
        "awaiting_slot_options": slot_options(choices),
        "pending_prompt": resolution.slot_prompt,
    }


_INTERNAL_FIELD_KEYS = frozenset(
    {
        "account_candidates",
        "is_potential_duplicate",
        "duplicate_confirmed",
        "vendor_needs_confirmation",
        "vendor_confirmed",
        "vendor_candidates",
    }
)


def build_draft(state: WorkflowGraphState) -> dict:
    """Map collected fields into a DraftAction. Shape-mapping only — no validation.

    Excludes `account_candidates` -- the seeded candidate list resolve_account
    consumes is plumbing, never a field the user should see echoed back in
    the confirmation prompt or passed on to RecordExpenseCommand.
    """
    fields = {
        key: value
        for key, value in (state.get("collected_fields") or {}).items()
        if key not in _INTERNAL_FIELD_KEYS
    }
    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.RECORD_EXPENSE,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=state.get("project_id"),
        site_id=state.get("site_id"),
        fields=fields,
    )
    return {"draft_action": draft}


# Kept in draft.fields (the backend needs it -- see RecordExpenseCommand.
# media_object_key) but never shown as a raw key:value line; a "📎 Receipt
# attached" note is shown instead, below. occurred_date/occurred_date_source
# are rendered by _date_line instead of as raw lines, same reasoning.
_DISPLAY_HIDDEN_FIELD_KEYS = frozenset(
    {"media_object_key", "occurred_date", "occurred_date_source"}
)


def _date_line(fields: dict) -> str | None:
    """The day being recorded, marked when Mesiri guessed it. Backported from
    Labour's workflows/labour_update/nodes.py (STA-166)."""
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


def request_confirmation(state: WorkflowGraphState) -> dict:
    """Compose the confirmation prompt. Deterministic formatting only — no
    localization/templates/AI generation here (see workflows/material/nodes.py)."""
    draft: DraftActionV2 = state["draft_action"]
    lines = ["*Confirm this record?*", "", "💸 Expense"]
    date_line = _date_line(draft.fields)
    if date_line:
        lines.append(date_line)
    shown = {k: v for k, v in draft.fields.items() if k not in _DISPLAY_HIDDEN_FIELD_KEYS}
    own_pocket = shown.pop("paid_from_own_pocket", False)
    assumed = shown.pop("own_pocket_assumed", False)
    lines.extend(field_lines(shown))
    if own_pocket:
        lines.append(
            "   • Paid: own pocket (no company account set up yet)"
            if assumed
            else "   • Paid: own pocket"
        )
    if draft.fields.get("media_object_key"):
        lines.append("   • 📎 Receipt attached")
    lines.append("")
    lines.append("Reply YES to confirm or NO to cancel.")
    return {"pending_prompt": "\n".join(lines)}
