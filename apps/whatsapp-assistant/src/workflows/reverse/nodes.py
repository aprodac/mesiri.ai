"""Reverse workflow nodes — pure functions, no LangGraph, no I/O, no SQL, no domain rules.

Finance Module Slice 7: "reverse my last expense"/"cancel that transfer".
No slot-filling here -- runtime/inbound_journey.py's seeding step
(`_seed_reversal_target`) already resolved "the most recent expense/transfer
of the requested kind" into a concrete `expense_id`/`money_transaction_id`
before this graph ever runs (a node must never query a repository itself,
see workflows/runtime.py's docstring), mirroring how account admin's
deterministic parser resolves everything before its own graph runs.

Unlike every other finance workflow, there is a genuine "nothing to
reverse" outcome: when the seeding step found no matching record,
`build_draft` deliberately omits `draft_action` and returns a friendly
`pending_prompt` instead -- `WorkflowDefinition.allows_completion_without_draft`
in workflows/registry.py allows `WorkflowKey.REVERSE` to complete without a
draft for exactly this case.
"""

from __future__ import annotations

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id

from ..state import WorkflowGraphState

_INTERNAL_FIELD_KEYS: frozenset[str] = frozenset()
# reversal_amount/reversal_description/reversal_occurred_date/
# reversal_from_account_name/reversal_to_account_name used to be excluded
# here as "confirm-prompt-only plumbing," matching the pattern every other
# finance workflow uses for its own display-only fields -- but unlike those,
# these five are seeded straight from a real DB read (runtime/reversal_
# query.py, via _seed_reversal_target), never an unresolved AI hint, so
# there's nothing to re-resolve or risk being stale. Kept in draft.fields so
# channel/receipt/data.py's build_receipt_data can show a real reversal
# receipt (amount, description/date, or the two account names) instead of
# only the bare expense_id/money_transaction_id it had before.

_NOTHING_TO_REVERSE = {
    "expense": "You have no confirmed expenses to reverse.",
    "transfer": "You have no transfers to reverse.",
    "petty_cash": "You have no petty cash issues or returns to reverse.",
    # Reporter-scoped, so "you" is literal here -- another supervisor's
    # report is not a candidate and saying "there are none" would be wrong
    # if it said "no reports exist".
    "attendance": (
        "I don't see an attendance report you filed that I can withdraw. "
        "If you need to fix a headcount, send the day again and choose "
        "\"Replace it\"."
    ),
    # ADR-D15: same-session only -- this is the honest reply both when
    # nothing was ever logged this conversation AND when it was logged too
    # long ago to still be "the thing I just sent" (see runtime/
    # reversal_query.py's find_latest_activity docstring).
    "activity": "I don't see anything you just logged that I can undo right now.",
}


def build_draft(state: WorkflowGraphState) -> dict:
    """Map already-resolved fields into a DraftAction, or -- if nothing was
    found to reverse -- complete with a friendly reply and no draft at all."""
    fields = dict(state.get("collected_fields") or {})
    target_kind = str(fields.get("target_kind", "")).strip().lower()
    has_target = bool(
        fields.get("expense_id")
        or fields.get("money_transaction_id")
        or fields.get("activity_id")
        or fields.get("attendance_report_id")
    )

    if not has_target:
        return {
            "pending_prompt": _NOTHING_TO_REVERSE.get(target_kind, "Nothing found to reverse.")
        }

    draft_fields = {key: value for key, value in fields.items() if key not in _INTERNAL_FIELD_KEYS}
    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.REVERSE_TRANSACTION,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=state.get("project_id"),
        site_id=state.get("site_id"),
        fields=draft_fields,
    )
    return {"draft_action": draft}


def request_confirmation(state: WorkflowGraphState) -> dict:
    """Deterministic formatting only, using the display fields seeded
    alongside the resolved target (still in collected_fields at this point,
    even though build_draft excluded them from draft.fields)."""
    all_fields = state.get("collected_fields") or {}
    target_kind = str(all_fields.get("target_kind", "")).strip().lower()
    amount = all_fields.get("reversal_amount")

    if target_kind == "activity":
        summary = all_fields.get("reversal_activity_summary") or "your last site update"
        occurred_date = all_fields.get("reversal_occurred_date")
        lines = [
            "*Confirm this undo?*",
            "",
            "↩️ Remove activity",
            f"   • {summary} ({occurred_date})",
            "",
            "Reply YES to confirm or NO to cancel.",
        ]
    elif target_kind == "attendance":
        # Site and date lead, because the mistake this exists to fix is a
        # report filed against the wrong site -- those two lines are what
        # the user checks. Headcount and cost follow so the scale of what
        # is being withdrawn is visible before it happens (P2).
        site = all_fields.get("reversal_attendance_site") or "your site"
        occurred_date = all_fields.get("reversal_occurred_date")
        headcount = all_fields.get("reversal_attendance_headcount")
        workers = f"{headcount} worker{'' if headcount == 1 else 's'}"
        lines = [
            "*Confirm this withdrawal?*",
            "",
            "↩️ Withdraw attendance report",
            f"   • {site} ({occurred_date})",
            f"   • {workers}, ₹{amount}",
            "",
            "It stops counting everywhere, but stays on record.",
            "",
            "Reply YES to confirm or NO to cancel.",
        ]
    elif target_kind == "petty_cash":
        # Same underlying row as the transfer branch below, deliberately
        # phrased around the person instead of the two accounts: nobody
        # thinks of "₹20,000 to Alan" as "Company Account → Alan Usman —
        # Petty Cash", and a confirmation the user cannot recognise is not
        # a confirmation (principle P2).
        holder = all_fields.get("reversal_petty_cash_holder") or "that person"
        direction = str(all_fields.get("reversal_petty_cash_direction", "")).strip().lower()
        movement = f"returned by {holder}" if direction == "return" else f"issued to {holder}"
        lines = [
            "*Confirm this reversal?*",
            "",
            "↩️ Reverse petty cash",
            f"   • Amount: {amount}",
            f"   • {movement}",
            "",
            "Reply YES to confirm or NO to cancel.",
        ]
    elif target_kind == "transfer":
        from_name = all_fields.get("reversal_from_account_name")
        to_name = all_fields.get("reversal_to_account_name")
        lines = [
            "*Confirm this reversal?*",
            "",
            "↩️ Reverse transfer",
            f"   • Amount: {amount}",
            f"   • {from_name} → {to_name}",
            "",
            "Reply YES to confirm or NO to cancel.",
        ]
    else:
        description = all_fields.get("reversal_description") or "—"
        occurred_date = all_fields.get("reversal_occurred_date")
        lines = [
            "*Confirm this reversal?*",
            "",
            "↩️ Reverse expense",
            f"   • Amount: {amount}",
            f"   • {description} ({occurred_date})",
            "",
            "Reply YES to confirm or NO to cancel.",
        ]
    return {"pending_prompt": "\n".join(lines)}
