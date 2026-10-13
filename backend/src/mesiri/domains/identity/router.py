import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.bootstrap.settings import PostgresSettings
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.postgres.dependency import get_db_conn as get_shared_db_conn
from mesiri.infrastructure.postgres.models.user import UserModel

from .auth_service import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

_organizations = sa.Table(
    "organizations",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
)

_users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("full_name", sa.String),
)


# Temporary direct dependency on PostgresDatabase for the initial setup
async def get_db_conn():
    # In a real setup, we would inject this via the AppLifecycle/Container
    # For now, we instantiate settings to get a connection.
    # We will refine this injection later.
    settings = PostgresSettings()
    db = PostgresDatabase(settings)
    await db.connect()
    async with db.transaction() as conn:
        yield conn


class UserLogin(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


# There is deliberately no public /auth/register: it accepted any `role` and
# `organization_id` unauthenticated, so anyone could mint a platform-admin
# token. See apps/whatsapp-assistant/src/auth/router.py.


@router.post("/login", response_model=Token)
async def login(user_in: UserLogin, conn: AsyncConnection = Depends(get_db_conn)):
    result = await conn.execute(select(UserModel).where(UserModel.email == user_in.email))
    user_row = result.first()

    if not user_row:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = user_row[0]  # The UserModel instance

    if not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "org": str(user.organization_id) if user.organization_id else "",
            "role": user.role.value,
        }
    )
    return {"access_token": access_token, "token_type": "bearer"}


class MeResponse(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str | None
    role: str
    full_name: str
    access_policy: dict


@router.get("/me", response_model=MeResponse)
async def me(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_shared_db_conn),
):
    """Return the authenticated user's identity, role, org, and access policy.

    Reuses get_auth_context (see domains/projects/router.py) so this stays
    consistent with the same JWT validation + access-policy resolution every
    other scoped endpoint uses, rather than re-deriving it here.
    """
    org_result = await conn.execute(
        sa.select(_organizations.c.name).where(_organizations.c.id == auth_context.organization_id)
    )
    org_row = org_result.first()

    user_result = await conn.execute(
        sa.select(_users.c.full_name).where(_users.c.id == auth_context.user_id)
    )
    user_row = user_result.first()

    return MeResponse(
        user_id=auth_context.user_id,
        organization_id=auth_context.organization_id,
        organization_name=org_row.name if org_row else None,
        role=auth_context.role,
        full_name=user_row.full_name if user_row else "",
        access_policy={
            "mode": auth_context.access_policy.mode,
            "projects": auth_context.access_policy.projects,
        },
    )
