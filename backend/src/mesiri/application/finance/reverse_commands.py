"""ReverseTransaction Application Command.

Local to backend (not a shared mesiri_contracts contract), mirrors
application/finance/transfer_commands.py's reasoning. `expense_id`/
`money_transaction_id` are already real UUIDs by the time this command
exists -- runtime/inbound_journey.py's seeding step resolves "the most
recent expense/transfer" into a concrete id before the draft is ever built
(see workflows/reverse/nodes.py), mirroring how transfer's account ids are
resolved before its draft.

`created_by_role` travels through the draft the same way transfer's does
(seeded in runtime/inbound_journey.py, carried in draft.fields) so the
who-may-reverse rule can be enforced in reverse_validation.py.
"""

from __future__ import annotations

from pydantic import BaseModel


class ReverseTransactionCommand(BaseModel):
    model_config = {"extra": "forbid"}

    idempotency_key: str
    organization_id: str
    created_by: str
    created_by_role: str | None = None

    target_kind: str  # "expense" | "transfer" | "activity" | "attendance"
    expense_id: str | None = None
    money_transaction_id: str | None = None
    # ADR-D15 (docs/execution/DAILY_REPORTING_PLAN.md): undo of an Activity
    # the reporter just created. Composes through Progress's own
    # PostgresProgressReadRepository.void_activity, same "each module owns
    # its own reversal" reasoning expense/transfer already follow.
    activity_id: str | None = None
    # Withdraw a labour attendance report filed against the wrong site
    # (migration 0462). Composes through Workforce's own
    # void_attendance_report, same reasoning again -- this module routes,
    # it never learns another module's storage.
    #
    # Distinct from the "Replace it" path: re-sending a day supersedes a
    # report within one project/site/day, which is the right repair for a
    # miscount and cannot reach a report on the wrong site at all.
    attendance_report_id: str | None = None

    correlation_id: str | None = None
