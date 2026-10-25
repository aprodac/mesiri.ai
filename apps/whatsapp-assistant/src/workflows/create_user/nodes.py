"""Create-user workflow nodes — pure functions, no LangGraph, no I/O, no SQL.

Mirrors workflows/add_project_member/nodes.py's build_draft/
request_confirmation shape and role normalization exactly, minus the
project scope -- a new user isn't created under any particular project
(that's a separate, later ADD_PROJECT_MEMBER, see the setup-offer chain in
runtime/inbound_journey/seeding.py).

`whatsapp_number` is only normalized to digits here (pure string work, no
I/O) -- it is NOT resolved/deduplicated against existing users, since that
is a DB round trip a pure node must never perform (workflows/runtime.py's
rule). The backend Handler rejects a number already in use at persist time
(see application/users/create_user_execution.py), the same "hard rejection,
never a silent default" treatment every other name/number resolution in
this codebase gets.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id

from ..role_words import ROLE_DISPLAY, normalize_role, role_not_allowed_reply
from ..state import WorkflowGraphState

_MISSING_NAME_PROMPT = "What's this person's name?"
_MISSING_NUMBER_PROMPT = "What's their WhatsApp number?"
_INVALID_NUMBER_PROMPT = (
    "That doesn't look like a valid WhatsApp number — please resend it with the "
    "country code, e.g. 9198765xxxxx."
)


# A WhatsApp number is always at least a 10-digit local number; most will
# carry a country code too. This is a sanity floor, not format validation --
# genuine E.164 validation happens nowhere in this codebase today (see
# users/router.py's own UserCreate, which accepts whatsapp_number as a bare
# optional string with no format check at all); this only catches a
# transcription/typo that's obviously not a phone number at all (e.g. a
# 3-digit "number").
_MIN_DIGITS = 10

#: E.164's own maximum. Bounds find_mentioned_phone_number's search on the
#: long side, the same way _MIN_DIGITS bounds it on the short side -- a
#: 20-digit reference number mentioned nearby must not be mistaken for a
#: phone number just because it also happens to be all digits.
_MAX_DIGITS = 15


def _normalize_phone(number_hint: object) -> str | None:
    """Strip everything but digits. Returns None if what's left is too short
    to plausibly be a phone number at all."""
    digits = "".join(ch for ch in str(number_hint or "") if ch.isdigit())
    return digits if len(digits) >= _MIN_DIGITS else None


def find_mentioned_phone_number(texts: Iterable[str]) -> str | None:
    """Scan free-form text -- recent conversation turns, typically -- for a
    plausible phone number already stated, and return it normalized.

    Built for exactly the case a live user report surfaced: "+91 97781
    90485 create Hysam in project hospital" states the number and the
    request in the same message, but ADD_PROJECT_MEMBER's own extraction
    schema has no phone-number field, so the number was silently dropped --
    several turns later, CREATE_USER asked for it again from scratch, which
    reads as "I already told you that" from the sender's side. See
    runtime/inbound_journey/resume.py's start_member_create_plan, the one
    caller: before asking, it checks memory.recent_turns.RecentTurnsStore
    for exactly this.

    Deliberately conservative, the same floor/ceiling _normalize_phone and
    E.164 respectively impose: only a maximal run of digit-ish characters
    (allowing +, spaces, hyphens within it) between _MIN_DIGITS and
    _MAX_DIGITS digits counts. Short numbers (a headcount, an amount) and
    long ones (an order/reference id) are excluded on purpose -- a wrong
    guess here is silently offered to the sender as their own new user's
    phone number, so the bar is "clearly phone-shaped", not "any digits".

    Scans in order and returns the FIRST match -- if a number appears in
    more than one turn, the earliest-stated one wins, since that is closest
    to how the sender is likely to have meant it (stated once, referred to
    since).
    """
    for text in texts:
        for run in re.findall(r"[\d][\d\s\-+]*\d", str(text or "")):
            digits = "".join(ch for ch in run if ch.isdigit())
            if _MIN_DIGITS <= len(digits) <= _MAX_DIGITS:
                return digits
    return None


_NUMBER_SLOT_NAME = "whatsapp_number"


def resolve_whatsapp_number(state: WorkflowGraphState) -> dict:
    """Resolve the new user's WhatsApp number via a real slot-fill, run
    before build_draft.

    Added for ENTITY_RESOLUTION_PLAN.md's CREATE_USER -> ADD_PROJECT_MEMBER
    chain (runtime/inbound_journey/resume.py's start_member_create_plan),
    which deliberately starts this workflow with only a name and no number --
    the number is never in the original "add X as PM" message. Before this
    node existed, a missing number produced only a bare pending_prompt with
    no `awaiting_slot` (see build_draft's prior version), so the run
    completed as terminal COMPLETED (workflows/runtime.py's start(): only an
    `awaiting_slot` value persists a resumable COLLECTING_FIELDS state).
    Nothing was left listening, so the reply to "What's their WhatsApp
    number?" landed as an ordinary new message, Understanding called it
    `unknown`, and the number was silently lost -- confirmed by a live
    trace, not a hypothetical.

    Mirrors expense_capture/nodes.py's resolve_account shape (pop
    `_slot_answer_text` set by WorkflowRuntime.provide_input on resume,
    validate, clear `awaiting_slot` on success or re-ask on failure) --
    free-text, not choice-based, so match_slot_answer/SlotCandidate don't
    apply here; _normalize_phone is the existing validator, unchanged.

    A message that already carries a number (the common, non-chained
    "create Rajesh, 9198765xxxxx, as site engineer" case) is unaffected --
    resolves and clears on the very first pass, same as before this node
    existed.

    No full_name yet either: falls through unresolved, deferring to
    build_draft's own missing-name prompt (a single-message retry, not a
    slot) -- that field's behaviour is intentionally untouched here."""
    fields = dict(state.get("collected_fields") or {})
    if not str(fields.get("full_name") or "").strip():
        return {}

    answer_text = fields.pop("_slot_answer_text", None)
    if answer_text is not None:
        phone = _normalize_phone(answer_text)
        if phone is not None:
            fields["whatsapp_number"] = phone
            return {"collected_fields": fields, "awaiting_slot": None}
        return {
            "collected_fields": fields,
            "awaiting_slot": _NUMBER_SLOT_NAME,
            "pending_prompt": f"Sorry, that doesn't look right. {_INVALID_NUMBER_PROMPT}",
        }

    raw_number = fields.get("whatsapp_number")
    if str(raw_number or "").strip():
        phone = _normalize_phone(raw_number)
        if phone is not None:
            fields["whatsapp_number"] = phone
            return {"collected_fields": fields, "awaiting_slot": None}
        return {
            "collected_fields": fields,
            "awaiting_slot": _NUMBER_SLOT_NAME,
            "pending_prompt": _INVALID_NUMBER_PROMPT,
        }

    return {
        "collected_fields": fields,
        "awaiting_slot": _NUMBER_SLOT_NAME,
        "pending_prompt": _MISSING_NUMBER_PROMPT,
    }


def build_draft(state: WorkflowGraphState) -> dict:
    """Map collected fields into a DraftAction, or -- if AI extraction never
    filled in a name -- complete with a clarifying reply and no draft at all
    (see WorkflowDefinition.allows_completion_without_draft in workflows/
    registry.py, which permits WorkflowKey.CREATE_USER to complete without a
    draft for exactly this case).

    By the time this runs, resolve_whatsapp_number has already guaranteed
    whatsapp_number is either a normalized, valid number or the graph never
    reached here at all (see graph.py's conditional edge) -- except when
    full_name itself was missing, in which case resolve_whatsapp_number is a
    no-op and whatsapp_number may still be raw/absent. The checks below stay
    as defence in depth for that path and for any future caller that invokes
    this node directly."""
    fields = dict(state.get("collected_fields") or {})
    full_name = str(fields.get("full_name") or "").strip()
    if not full_name:
        return {"pending_prompt": _MISSING_NAME_PROMPT}
    raw_number = fields.get("whatsapp_number")
    if not str(raw_number or "").strip():
        return {"pending_prompt": _MISSING_NUMBER_PROMPT}
    phone = _normalize_phone(raw_number)
    if phone is None:
        return {"pending_prompt": _INVALID_NUMBER_PROMPT}
    role = normalize_role(fields.get("role"))
    refused = role_not_allowed_reply(fields.get("created_by_role"), role)
    if refused:
        return {"pending_prompt": refused}
    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.CREATE_USER,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=None,
        site_id=None,
        fields={
            "full_name": full_name,
            "whatsapp_number": phone,
            "role": role,
            "created_by_role": fields.get("created_by_role"),
        },
    )
    return {"draft_action": draft}


def request_confirmation(state: WorkflowGraphState) -> dict:
    """Compose the confirmation prompt. Deterministic formatting only — no
    localization/templates/AI generation here (see workflows/material/
    nodes.py). The phone number is called out with its own line and an
    explicit "please check this" -- a mis-heard or mis-typed digit here
    doesn't fail loudly, it silently hands WhatsApp access to whoever
    actually holds that number."""
    draft: DraftActionV2 = state["draft_action"]
    full_name = draft.fields.get("full_name")
    phone = draft.fields.get("whatsapp_number")
    role = ROLE_DISPLAY.get(str(draft.fields.get("role") or ""), "Site Engineer")
    lines = [
        "*Confirm this action?*",
        "",
        f"👤 Create a new user: *{full_name}*",
        f"📱 WhatsApp: {phone} — please double check this number",
        f"🏷️ Role: {role}",
        "",
        "Reply YES to confirm or NO to cancel.",
    ]
    return {"pending_prompt": "\n".join(lines)}
