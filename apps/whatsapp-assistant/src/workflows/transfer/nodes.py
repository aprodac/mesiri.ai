"""Transfer workflow nodes — pure functions, no LangGraph, no I/O, no SQL, no domain rules.

Two independent slots (from_account_id, to_account_id), each resolved the
same way expense_capture's resolve_account resolves its one slot (Finance
Module Slice 1): try the AI-extracted name first, then ask only if it
doesn't match. Unlike expense capture there is no "own pocket" sentinel --
both sides of a transfer are always one of the org's own accounts.

`resolve_to_account` excludes whatever `resolve_from_account` already
picked from its candidate list, so the two slots can never resolve to the
same account through the ask-a-question path (a same-account transfer can
still reach the backend if there is only one account in the org at all --
that is caught by application/finance/transfer_validation.py, not here).
"""

from __future__ import annotations

from typing import Any

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id

from ..slots import (
    RETRY_PREFIX,
    SlotCandidate,
    match_slot_answer,
    resolve_single_choice_slot,
    slot_options,
)
from ..state import WorkflowGraphState

_FROM_SLOT = "from_account_id"
_TO_SLOT = "to_account_id"
_FROM_PROMPT = "Which account are you transferring FROM?"
_TO_PROMPT = "Which account are you transferring TO?"
_INTERNAL_FIELD_KEYS = frozenset(
    {"account_candidates", "from_account_name", "to_account_name"}
)


def _candidates(raw: list[dict[str, Any]], *, exclude_id: str | None = None) -> list[SlotCandidate]:
    return [
        SlotCandidate(value=str(c["id"]), label=str(c["name"]))
        for c in raw
        if exclude_id is None or str(c["id"]) != exclude_id
    ]


def _resolve_slot(
    fields: dict[str, Any],
    *,
    slot_key: str,
    name_key: str,
    prompt_title: str,
    candidates: list[SlotCandidate],
    is_awaiting_this_slot: bool,
) -> dict:
    """Shared resolution shape for one slot. Returns the partial state update
    for this node: either the resolved field merged in, or awaiting_slot +
    pending_prompt set."""
    if is_awaiting_this_slot:
        answer_text = fields.pop("_slot_answer_text", None)
        if answer_text is not None:
            matched = match_slot_answer(answer_text, candidates)
            if matched is not None:
                fields[slot_key] = matched
                return {"collected_fields": fields, "awaiting_slot": None}
            resolution = resolve_single_choice_slot(
                slot_name=slot_key,
                prompt_title=f"{RETRY_PREFIX} {prompt_title}",
                candidates=candidates,
            )
            return {
                "collected_fields": fields,
                "awaiting_slot": resolution.awaiting_slot,
                "awaiting_slot_options": slot_options(candidates),
                "pending_prompt": resolution.slot_prompt,
            }

    name = fields.get(name_key)
    if name:
        matched = match_slot_answer(str(name), candidates)
        if matched is not None:
            fields[slot_key] = matched
            return {"collected_fields": fields}

    resolution = resolve_single_choice_slot(
        slot_name=slot_key, prompt_title=prompt_title, candidates=candidates
    )
    if resolution.resolved_value is not None:
        fields[slot_key] = resolution.resolved_value
        return {"collected_fields": fields}
    return {
        "collected_fields": fields,
        "awaiting_slot": resolution.awaiting_slot,
        "awaiting_slot_options": slot_options(candidates),
        "pending_prompt": resolution.slot_prompt,
    }


def resolve_from_account(state: WorkflowGraphState) -> dict:
    fields = dict(state.get("collected_fields") or {})
    if fields.get(_FROM_SLOT) is not None:
        return {}
    candidates = _candidates(fields.get("account_candidates") or [])
    return _resolve_slot(
        fields,
        slot_key=_FROM_SLOT,
        name_key="from_account_name",
        prompt_title=_FROM_PROMPT,
        candidates=candidates,
        is_awaiting_this_slot=state.get("awaiting_slot") == _FROM_SLOT,
    )


def resolve_to_account(state: WorkflowGraphState) -> dict:
    fields = dict(state.get("collected_fields") or {})
    if fields.get(_TO_SLOT) is not None:
        return {}
    candidates = _candidates(fields.get("account_candidates") or [], exclude_id=fields.get(_FROM_SLOT))
    return _resolve_slot(
        fields,
        slot_key=_TO_SLOT,
        name_key="to_account_name",
        prompt_title=_TO_PROMPT,
        candidates=candidates,
        is_awaiting_this_slot=state.get("awaiting_slot") == _TO_SLOT,
    )


def build_draft(state: WorkflowGraphState) -> dict:
    """Map collected fields into a DraftAction. Shape-mapping only — no
    validation (that belongs to application/finance/transfer_validation.py).

    `from_account_name`/`to_account_name` at this point still hold whatever
    raw AI-extracted hint text resolve_from_account/resolve_to_account
    matched against candidates with (e.g. "company acc") -- not fit to show
    on a receipt. Overwritten here with the real resolved account's name
    from `account_candidates` (the same lookup request_confirmation already
    does, just also persisted now instead of thrown away) so
    channel/receipt/data.py's build_receipt_data can show real names
    without any I/O of its own.
    """
    all_fields = state.get("collected_fields") or {}
    names_by_id = {str(c["id"]): c["name"] for c in (all_fields.get("account_candidates") or [])}
    fields = {
        key: value for key, value in all_fields.items() if key not in _INTERNAL_FIELD_KEYS
    }
    if fields.get(_FROM_SLOT) is not None:
        fields["from_account_name"] = names_by_id.get(fields[_FROM_SLOT], fields[_FROM_SLOT])
    if fields.get(_TO_SLOT) is not None:
        fields["to_account_name"] = names_by_id.get(fields[_TO_SLOT], fields[_TO_SLOT])
    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.TRANSFER_MONEY,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=state.get("project_id"),
        site_id=state.get("site_id"),
        fields=fields,
    )
    return {"draft_action": draft}


def request_confirmation(state: WorkflowGraphState) -> dict:
    """Deterministic formatting only — resolves account names from the
    seeded candidate list (still in collected_fields at this point, even
    though build_draft excluded it from draft.fields) so the prompt reads
    "Company Bank" rather than a raw UUID."""
    draft: DraftActionV2 = state["draft_action"]
    all_fields = state.get("collected_fields") or {}
    names_by_id = {str(c["id"]): c["name"] for c in (all_fields.get("account_candidates") or [])}
    from_name = names_by_id.get(draft.fields.get("from_account_id"), draft.fields.get("from_account_id"))
    to_name = names_by_id.get(draft.fields.get("to_account_id"), draft.fields.get("to_account_id"))
    amount = draft.fields.get("amount")
    lines = [
        "*Confirm this transfer?*",
        "",
        "🔁 Transfer",
        f"   • Amount: {amount}",
        f"   • From: {from_name}",
        f"   • To: {to_name}",
        "",
        "Reply YES to confirm or NO to cancel.",
    ]
    return {"pending_prompt": "\n".join(lines)}
