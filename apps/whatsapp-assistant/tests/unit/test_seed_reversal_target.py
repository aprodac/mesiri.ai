"""_seed_reversal_target -- the #6 Undo generic-kind resolution branch.

Mirrors test_workforce_seeding.py's shape: a fake ReversalTargetQueryService
stands in for the real Postgres-backed one (which needs a live DB and is
covered by that repository's own SQL, not here). What's protected here is
pure wiring: a bare "undo" (no target_kind) must resolve via
find_latest_of_either_kind and write the winning kind back onto fields so
workflows/reverse/nodes.py renders the right confirmation prompt.
"""

from __future__ import annotations

from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.planner_decision import (
    PlannerDecisionType,
    PlannerPriority,
    WorkflowKey,
)
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from runtime.inbound_journey import _seed_reversal_target

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"


class _Actor:
    organization_id = ORG
    user_id = USR
    role = "site_engineer"


class _FakeReversalQuery:
    def __init__(
        self,
        *,
        either_kind_result=None,
        transfer=None,
        expense=None,
        petty_cash=None,
        attendance=None,
    ):
        self._either_kind_result = either_kind_result
        self._transfer = transfer
        self._expense = expense
        self._petty_cash = petty_cash
        self._attendance = attendance
        self.either_kind_calls = 0
        self.petty_cash_calls = 0
        self.attendance_calls: list[str] = []

    async def find_latest_of_either_kind(self, *, organization_id, project_id, site_id):
        self.either_kind_calls += 1
        return self._either_kind_result

    async def find_latest_transfer(self, *, organization_id):
        return self._transfer

    async def find_latest_petty_cash(self, *, organization_id):
        self.petty_cash_calls += 1
        return self._petty_cash

    async def find_latest_expense(self, *, organization_id, project_id, site_id):
        return self._expense

    async def find_latest_attendance(self, *, organization_id, reported_by_user_id):
        self.attendance_calls.append(reported_by_user_id)
        return self._attendance


def _decision() -> PlannerDecisionV2:
    return PlannerDecisionV2(
        correlation_id="cor_1",
        source_message_id="msg_1",
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key=WorkflowKey.REVERSE,
        reason=CanonicalEventType.EXPENSE_REVERSAL_REQUESTED,
        priority=PlannerPriority.NORMAL,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
    )


def _event(fields: dict) -> CanonicalEventV2:
    return CanonicalEventV2(
        event_id="evt_1",
        correlation_id="cor_1",
        source_message_id="msg_1",
        event_type=CanonicalEventType.EXPENSE_REVERSAL_REQUESTED,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
        fields=fields,
    )


async def test_missing_target_kind_calls_find_latest_of_either_kind():
    query = _FakeReversalQuery(
        either_kind_result=(
            "expense",
            {
                "expense_id": "exp-1",
                "amount": "500",
                "description": "diesel",
                "occurred_date": "2026-07-20",
            },
        )
    )
    event = _event({})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert query.either_kind_calls == 1
    assert event.fields["target_kind"] == "expense"
    assert event.fields["expense_id"] == "exp-1"
    assert event.fields["reversal_amount"] == "500"


async def test_missing_target_kind_resolving_to_transfer_writes_transfer_fields():
    query = _FakeReversalQuery(
        either_kind_result=(
            "transfer",
            {
                "money_transaction_id": "txn-1",
                "amount": "1000",
                "from_account_name": "Petty Cash",
                "to_account_name": "Site Bank",
            },
        )
    )
    event = _event({})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert event.fields["target_kind"] == "transfer"
    assert event.fields["money_transaction_id"] == "txn-1"
    assert event.fields["reversal_from_account_name"] == "Petty Cash"
    assert event.fields["reversal_to_account_name"] == "Site Bank"


async def test_nothing_found_leaves_target_kind_unset_for_the_generic_message():
    query = _FakeReversalQuery(either_kind_result=None)
    event = _event({})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    # Deliberately absent -- workflows/reverse/nodes.py's build_draft falls
    # through to its generic "Nothing found to reverse." message for any
    # unrecognized target_kind (see mapping.py/reverse/nodes.py docstrings).
    assert "target_kind" not in event.fields
    assert "expense_id" not in event.fields
    assert "money_transaction_id" not in event.fields


async def test_explicit_target_kind_skips_the_either_kind_lookup_entirely():
    """An explicit "reverse my last expense" must not pay for (or risk being
    overridden by) the generic either-kind comparison -- existing, narrower
    behavior is untouched by the #6 Undo addition."""
    query = _FakeReversalQuery(
        either_kind_result=("transfer", {"money_transaction_id": "should-not-be-used"}),
        expense={
            "expense_id": "exp-explicit",
            "amount": "250",
            "description": "cement",
            "occurred_date": "2026-07-25",
        },
    )
    event = _event({"target_kind": "expense"})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert query.either_kind_calls == 0
    assert event.fields["expense_id"] == "exp-explicit"
    assert "money_transaction_id" not in event.fields


# --- Petty cash ------------------------------------------------------------
#
# A petty cash movement IS a `transfer` row (see
# find_latest_reversible_petty_cash) -- these protect the part that decides
# what to CALL it, which is what the user actually sees.


def _advance_transfer(**overrides):
    """A transfer whose destination is someone's advance account."""
    return {
        "money_transaction_id": "txn-pc",
        "amount": "20000",
        "from_account_name": "Company Account",
        "to_account_name": "Alan Usman — Petty Cash",
        "from_account_type": "bank",
        "to_account_type": "employee_advance",
        **overrides,
    }


async def test_explicit_petty_cash_kind_uses_the_petty_cash_finder():
    query = _FakeReversalQuery(petty_cash=_advance_transfer())
    event = _event({"target_kind": "petty_cash"})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert query.petty_cash_calls == 1
    assert event.fields["money_transaction_id"] == "txn-pc"
    assert event.fields["reversal_petty_cash_direction"] == "issue"
    assert event.fields["reversal_petty_cash_holder"] == "Alan Usman"


async def test_transfer_landing_on_an_advance_is_relabelled_petty_cash():
    """"Reverse my last transfer" about a petty cash issuance is imprecise,
    not wrong -- the record decides what it was, so the confirmation names a
    person instead of "Company Account -> Alan Usman — Petty Cash"."""
    query = _FakeReversalQuery(transfer=_advance_transfer())
    event = _event({"target_kind": "transfer"})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert event.fields["target_kind"] == "petty_cash"
    assert event.fields["reversal_petty_cash_holder"] == "Alan Usman"


async def test_a_plain_transfer_is_not_relabelled():
    query = _FakeReversalQuery(
        transfer=_advance_transfer(
            to_account_name="Site Bank", to_account_type="bank"
        )
    )
    event = _event({"target_kind": "transfer"})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert event.fields["target_kind"] == "transfer"
    assert "reversal_petty_cash_holder" not in event.fields


async def test_money_leaving_an_advance_reads_as_a_return():
    query = _FakeReversalQuery(
        petty_cash=_advance_transfer(
            from_account_name="Alan Usman — Petty Cash",
            from_account_type="employee_advance",
            to_account_name="Company Account",
            to_account_type="bank",
        )
    )
    event = _event({"target_kind": "petty_cash"})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert event.fields["reversal_petty_cash_direction"] == "return"
    assert event.fields["reversal_petty_cash_holder"] == "Alan Usman"


async def test_an_advance_named_unconventionally_falls_back_to_the_account_name():
    """The " — Petty Cash" strip is coupled to petty_cash_resolution.py's
    naming by convention only, so it must degrade to something correct."""
    query = _FakeReversalQuery(
        petty_cash=_advance_transfer(to_account_name="Old Imported Advance")
    )
    event = _event({"target_kind": "petty_cash"})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert event.fields["reversal_petty_cash_holder"] == "Old Imported Advance"


async def test_bare_undo_resolving_to_an_advance_transfer_is_also_relabelled():
    query = _FakeReversalQuery(either_kind_result=("transfer", _advance_transfer()))
    event = _event({})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert event.fields["target_kind"] == "petty_cash"
    assert event.fields["reversal_petty_cash_holder"] == "Alan Usman"


# --- Attendance ------------------------------------------------------------


def _attendance_target(**overrides):
    return {
        "attendance_report_id": "rep-1",
        "occurred_date": "2026-07-30",
        "total_headcount": 18,
        "total_cost": "12600.00",
        "site_name": "Block A",
        "project_name": "Skyline Towers",
        **overrides,
    }


async def test_attendance_kind_seeds_the_report_and_its_site():
    query = _FakeReversalQuery(attendance=_attendance_target())
    event = _event({"target_kind": "attendance"})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert event.fields["attendance_report_id"] == "rep-1"
    assert event.fields["reversal_occurred_date"] == "2026-07-30"
    assert event.fields["reversal_attendance_headcount"] == 18
    assert event.fields["reversal_amount"] == "12600.00"
    assert event.fields["reversal_attendance_site"] == "Block A"


async def test_attendance_lookup_is_scoped_to_the_reporter():
    """Reporter-scoped, not org-wide: an org-wide "most recent report" would
    let one supervisor withdraw another site's day."""
    query = _FakeReversalQuery(attendance=_attendance_target())
    await _seed_reversal_target(_event({"target_kind": "attendance"}), _decision(), query, _Actor())

    assert query.attendance_calls == [USR]


async def test_attendance_falls_back_to_the_project_when_there_is_no_site():
    query = _FakeReversalQuery(attendance=_attendance_target(site_name=None))
    event = _event({"target_kind": "attendance"})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert event.fields["reversal_attendance_site"] == "Skyline Towers"


async def test_nothing_to_withdraw_leaves_the_report_id_unset():
    query = _FakeReversalQuery(attendance=None)
    event = _event({"target_kind": "attendance"})
    await _seed_reversal_target(event, _decision(), query, _Actor())

    assert "attendance_report_id" not in event.fields


async def test_bare_undo_never_arbitrates_into_attendance():
    """A bare "undo" compares expense against transfer only. Attendance is
    reporter-scoped and would need a different signal than org-wide recency,
    so it is reachable only by naming it -- same reasoning that keeps
    activity out of the either-kind comparison."""
    query = _FakeReversalQuery(
        either_kind_result=("expense", {"expense_id": "exp-1", "amount": "5", "description": "d", "occurred_date": "2026-07-30"}),
        attendance=_attendance_target(),
    )
    await _seed_reversal_target(_event({}), _decision(), query, _Actor())

    assert query.attendance_calls == []
