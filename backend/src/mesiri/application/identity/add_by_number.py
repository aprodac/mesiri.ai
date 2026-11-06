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
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

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


@dataclass(frozen=True, slots=True)
class AddedToProject:
    user_id: uuid.UUID
    full_name: str
    #: A new person was made (False: they were already in this company).
    created: bool
    #: They were already on this project, with the role they had.
    already_on_project: bool


async def add_to_project_by_number(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID | str,
    project_id: uuid.UUID | str,
    created_by: uuid.UUID | str,
    created_by_role: str,
    full_name: str,
    whatsapp_number: str,
    role: str,
) -> AddedToProject:
    """Put the person with this number on the project with this role, making
    them first when the company doesn't have them yet: one step for every
    door that adds someone by number (the dashboard, the WhatsApp assistant,
    an approved join request, a shared contact). Making them is
    add_member_by_number (its role rules, one number = one person); putting
    them on the project is AddProjectMemberHandler's own write. Who may add
    to this project is the caller's check (an admin, or its manager).
    Raises MemberNotAdded with a plain reason."""
    from mesiri.application.projects.add_member_commands import AddProjectMemberCommand
    from mesiri.application.projects.handlers import AddProjectMemberHandler
    from mesiri.application.projects.name_resolution import PostgresMemberNameResolver
    from mesiri.infrastructure.postgres.repositories.add_project_member_execution import (
        PostgresAddProjectMemberExecutionRepository,
    )
    from mesiri.infrastructure.postgres.tenant import unscoped

    try:
        number = normalize_phone(whatsapp_number)
    except RecipientError as exc:
        raise MemberNotAdded(str(exc)) from exc
    digits = "".join(ch for ch in number if ch.isdigit())
    role = (role or "").upper()
    async with unscoped(conn):  # one number = one person, in any company (BE-04)
        row = (
            await conn.execute(
                sa.text(
                    "SELECT id, organization_id, full_name FROM users "
                    "WHERE whatsapp_number IS NOT NULL "
                    "AND regexp_replace(whatsapp_number, '\\D', '', 'g') = :d LIMIT 1"
                ),
                {"d": digits},
            )
        ).first()
    if row is not None and str(row.organization_id) != str(organization_id):
        raise MemberNotAdded(
            "That number is already used by someone in another company on Mesiri"
        )
    created = row is None
    if row is None:
        user_id = await add_member_by_number(
            conn,
            organization_id=organization_id,
            created_by=created_by,
            created_by_role=created_by_role,
            full_name=full_name,
            whatsapp_number=number,
            role=role,
        )
        name = " ".join(str(full_name or "").split())
    else:
        user_id, name = row.id, row.full_name or full_name

    on_project = (
        await conn.execute(
            sa.text("SELECT 1 FROM project_members WHERE project_id = :p AND user_id = :u"),
            {"p": uuid.UUID(str(project_id)), "u": user_id},
        )
    ).first()
    if on_project is not None:
        return AddedToProject(user_id, name, created, True)

    cmd = AddProjectMemberCommand(
        idempotency_key=f"add-by-number:{uuid.uuid4()}",
        organization_id=str(organization_id),
        project_id=str(project_id),
        created_by=str(created_by),
        created_by_role=(created_by_role or "").upper() or None,
        member_name=name,
        member_user_id=str(user_id),
        role=role,
    )
    result = await AddProjectMemberHandler(
        PostgresAddProjectMemberExecutionRepository(), PostgresMemberNameResolver()
    ).handle(conn, cmd)
    if result.status != ExecutionStatus.SUCCEEDED:
        reasons = result.rejection_reasons or ["they could not be added to the project"]
        message = "; ".join(reasons)
        raise MemberNotAdded(message[:1].upper() + message[1:])
    return AddedToProject(user_id, name, created, False)
