"""Petty cash workflow nodes — pure functions, no LangGraph, no I/O, no SQL, no domain rules.

Finance Module Slice 5: petty cash issue/return is deliberately built as a
convenience shape over Slice 3's transfer, not a new transaction type (see
docs/execution/FINANCE_MODULE_PLAN.md and Linear STA-147) -- `build_draft`
below emits the exact same `DraftActionType.TRANSFER_MONEY` transfer's own
build_draft emits, so the existing transfer backend chain (mapper,
validation, resolution, handler, dispatcher) needs no changes at all.

The one new piece of resolution this needs -- turning a recipient's name
("Alan") into their employee_advance money_account, auto-created on first
issuance -- is I/O, so it cannot happen in a node (see workflows/runtime.py's
"a node must never query a repository itself"). It happens in
runtime/inbound_journey.py's seeding step instead, the same place
_seed_account_candidates already seeds the org's regular accounts (see
runtime/petty_cash_query.py). This graph only ever needs to resolve the
*other* leg of the transfer -- the org account being paid out of (issue) or
returned into (return) -- via the same single-choice slot machinery
expense_capture's resolve_account uses (Finance Module Slice 1), minus the
"own pocket" sentinel: petty cash always moves between two real accounts.
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

_OTHER_ACCOUNT_PROMPT = {
    "issue": "Which account is this petty cash being paid out of?",
    "return": "Which account is this petty cash being returned to?",
}
_INTERNAL_FIELD_KEYS = frozenset(
    {
        "account_candidates",
        "recipient_name",
        # recipient_account_id is dropped, not recipient_account_name --
        # its value is already duplicated onto from_account_id/to_account_id
        # (see resolve_other_account's fields.setdefault), and the *name*
        # (unlike direction below) needs to stay for the receipt/confirm
        # prompt since nothing else carries it forward.
        "recipient_account_id",
    }
)
# direction and recipient_account_name are deliberately NOT internal-only:
# both are already-resolved, canonical values (direction is deterministic
# from canonicalization; recipient_account_name comes straight from
# runtime/petty_cash_query.py's real account row, never an AI hint) needed
# by channel/receipt/data.py's build_receipt_data to tell a petty cash
# receipt apart from a plain transfer and show who it was issued to /
# returned by.


def _other_slot_name(direction: str) -> str | None:
    if direction == "issue":
        return "from_account_id"
    if direction == "return":
        return "to_account_id"
    return None


def _recipient_slot_name(direction: str) -> str | None:
    if direction == "issue":
        return "to_account_id"
    if direction == "return":
        return "from_account_id"
    return None


def _candidates(raw: list[dict[str, Any]]) -> list[SlotCandidate]:
    return [SlotCandidate(value=str(c["id"]), label=str(c["name"])) for c in raw]


def resolve_other_account(state: WorkflowGraphState) -> dict:
    """Fill in the recipient's already-resolved advance account on one leg
    of the transfer, and resolve the other leg (the org account being paid
    out of, or returned into) via the single-choice slot machinery -- ask
    only when genuinely ambiguous, exactly like expense_capture's
    resolve_account. An unrecognized `direction` (should never happen once
    canonicalization/mapping.py has classified it) leaves both legs unset;
    the backend's transfer validation rejects a draft missing either
    account rather than this node guessing."""
    fields = dict(state.get("collected_fields") or {})
    direction = str(fields.get("direction", "")).strip().lower()
    other_slot = _other_slot_name(direction)
    recipient_slot = _recipient_slot_name(direction)
    if other_slot is None or recipient_slot is None:
        return {}

    fields.setdefault(recipient_slot, fields.get("recipient_account_id"))
    if fields.get(other_slot) is not None:
        return {"collected_fields": fields}

    prompt_title = _OTHER_ACCOUNT_PROMPT[direction]
    candidates = _candidates(fields.get("account_candidates") or [])
    is_awaiting_this_slot = state.get("awaiting_slot") == other_slot

    if is_awaiting_this_slot:
        answer_text = fields.pop("_slot_answer_text", None)
        if answer_text is not None:
            matched = match_slot_answer(answer_text, candidates)
            if matched is not None:
                fields[other_slot] = matched
                return {"collected_fields": fields, "awaiting_slot": None}
            resolution = resolve_single_choice_slot(
                slot_name=other_slot,
                prompt_title=f"{RETRY_PREFIX} {prompt_title}",
                candidates=candidates,
            )
            return {
                "collected_fields": fields,
                "awaiting_slot": resolution.awaiting_slot,
                "awaiting_slot_options": slot_options(candidates),
                "pending_prompt": resolution.slot_prompt,
            }

    resolution = resolve_single_choice_slot(
        slot_name=other_slot, prompt_title=prompt_title, candidates=candidates
    )
    if resolution.resolved_value is not None:
        fields[other_slot] = resolution.resolved_value
        return {"collected_fields": fields}
    return {
        "collected_fields": fields,
        "awaiting_slot": resolution.awaiting_slot,
        "awaiting_slot_options": slot_options(candidates),
        "pending_prompt": resolution.slot_prompt,
    }


def build_draft(state: WorkflowGraphState) -> dict:
    """Map collected fields into a DraftAction -- DraftActionType.TRANSFER_MONEY,
    same as workflows/transfer/nodes.py's build_draft, so this reuses the
    existing transfer dispatcher/handler unchanged (see module docstring).

    Also resolves the org-side ("other") account's real name from
    account_candidates -- same lookup request_confirmation already does for
    the prompt, persisted here too so channel/receipt/data.py's
    build_receipt_data can show it without any I/O of its own."""
    all_fields = state.get("collected_fields") or {}
    direction = str(all_fields.get("direction", "")).strip().lower()
    other_slot = _other_slot_name(direction)
    names_by_id = {str(c["id"]): c["name"] for c in (all_fields.get("account_candidates") or [])}
    fields = {key: value for key, value in all_fields.items() if key not in _INTERNAL_FIELD_KEYS}
    if other_slot and fields.get(other_slot) is not None:
        fields["other_account_name"] = names_by_id.get(fields[other_slot], fields[other_slot])
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
    """Deterministic formatting only, mirrors transfer's request_confirmation
    but phrased for petty cash issue/return."""
    draft: DraftActionV2 = state["draft_action"]
    all_fields = state.get("collected_fields") or {}
    direction = str(all_fields.get("direction", "")).strip().lower()
    recipient_name = all_fields.get("recipient_account_name") or all_fields.get("recipient_name")
    names_by_id = {str(c["id"]): c["name"] for c in (all_fields.get("account_candidates") or [])}
    other_slot = _other_slot_name(direction)
    other_account_id = draft.fields.get(other_slot) if other_slot else None
    other_name = names_by_id.get(other_account_id, other_account_id)
    amount = draft.fields.get("amount")

    if direction == "return":
        title = "*Confirm this petty cash return?*"
        detail_lines = [
            f"   • Amount: {amount}",
            f"   • Returned by: {recipient_name}",
            f"   • Into: {other_name}",
        ]
    else:
        title = "*Confirm this petty cash issuance?*"
        detail_lines = [
            f"   • Amount: {amount}",
            f"   • To: {recipient_name}",
            f"   • From: {other_name}",
        ]
    lines = [title, "", "💰 Petty Cash", *detail_lines, "", "Reply YES to confirm or NO to cancel."]
    return {"pending_prompt": "\n".join(lines)}
