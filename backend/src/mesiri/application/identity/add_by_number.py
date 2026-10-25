"""Add a person by name and WhatsApp number alone (WEB-17).

Site staff report on WhatsApp and may never open the dashboard, so the Team
page's "Add a person" must not ask them for an email and password. This is
the dashboard's door into the SAME creation step the WhatsApp "add Ravi,
98765..., as site engineer" and the shared-contact flow (SS-13) use --
CreateUserHandler, with its role rules (a project manager can't make an
admin, WA-67) and its one-number-one-person check (BE-04) -- so a person
comes out the same whichever door they came through. Nothing here writes
the users table itself.

The number is stored the way signup stores the owner's (normalize_phone:
digits, country code first, a bare Indian mobile gets 91), which is what
WhatsApp sends as the sender id, so their first message finds them.

Takes the caller's connection and never commits.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from mesiri.application.dpr.recipients import RecipientError, normalize_phone
from mesiri.infrastructure.postgres.repositories.create_user_execution import (
    PostgresCreateUserExecutionRepository,
)
from mesiri_contracts.application.results.execution_result import ExecutionStatus

from .create_user_commands import CreateUserCommand
from .handlers import CreateUserHandler
from .repository import CreateUserExecutionRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


class MemberNotAdded(Exception):
    """The person wasn't added; the message says why, in plain words."""


async def add_member_by_number(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID | str,
    created_by: uuid.UUID | str,
    created_by_role: str,
    full_name: str,
    whatsapp_number: str,
    role: str,
    repo: CreateUserExecutionRepository | None = None,
) -> uuid.UUID:
    """Create the person and return their id, or raise MemberNotAdded."""
    try:
        number = normalize_phone(whatsapp_number)
    except RecipientError as exc:
        raise MemberNotAdded(str(exc)) from exc

    cmd = CreateUserCommand(
        idempotency_key=f"dashboard-create-user:{uuid.uuid4()}",
        organization_id=str(organization_id),
        created_by=str(created_by),
        created_by_role=(created_by_role or "").upper() or None,
        full_name=full_name,
        whatsapp_number=number,
        role=(role or "").upper(),
    )
    result = await CreateUserHandler(repo or PostgresCreateUserExecutionRepository()).handle(
        conn, cmd
    )
    if result.status != ExecutionStatus.SUCCEEDED or not result.material_row_id:
        reasons = result.rejection_reasons or ["the person could not be added"]
        message = "; ".join(reasons)
        raise MemberNotAdded(message[:1].upper() + message[1:])
    return uuid.UUID(result.material_row_id)
