"""Users domain router — tenant user management for the mobile app.

Endpoints
---------
POST /users               create a new user in the caller's org  (admin)
GET  /users               list all users in the caller's org  (admin)
GET  /users/{id}          fetch a single user with access policy  (admin)
PATCH /users/{id}         update role / full_name / whatsapp  (admin)
PATCH /users/{id}/status  change lifecycle status  (admin)
GET  /users/{id}/access   read the user's project/site access policy  (admin)
PUT  /users/{id}/access   replace the user's project/site access policy  (admin)
"""

from __future__ import annotations

import uuid
from typing import Any

import bcrypt as _bcrypt
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from ...application.identity.phone_numbers import NUMBER_TAKEN_MESSAGE, whatsapp_number_taken
from ...infrastructure.postgres.dependency import get_db_conn
from ..shared.auth import require_admin

router = APIRouter(prefix="/users", tags=["users"])

# ---------------------------------------------------------------------------
# Raw table refs (avoids ORM enum-type conflicts with legacy data)
# ---------------------------------------------------------------------------
_users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("email", sa.String),
    sa.Column("hashed_password", sa.String),
    sa.Column("full_name", sa.String),
    sa.Column("role", sa.String),
    sa.Column("whatsapp_number", sa.String),
    sa.Column("status", sa.String),
    sa.Column("access_policy", sa.JSON),
)

_DEFAULT_ACCESS_POLICY: dict[str, Any] = {"mode": "custom_projects", "projects": []}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    whatsapp_number: str | None = None
    status: str
    access_policy: dict | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    whatsapp_number: str | None = None
    password: str | None = None


class StatusUpdate(BaseModel):
    status: str


class AccessPolicy(BaseModel):
    mode: str
    projects: list[dict] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_VALID_ROLES = {"ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE"}
_VALID_STATUSES = {"active", "inactive", "suspended", "invited"}


def _row_to_response(row: Any) -> UserResponse:
    return UserResponse(
        id=row.id,
        email=row.email,
        full_name=row.full_name,
        role=row.role,
        whatsapp_number=row.whatsapp_number,
        status=row.status or "active",
        access_policy=row.access_policy or _DEFAULT_ACCESS_POLICY,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    full_name: str
    email: str
    password: str
    role: str
    whatsapp_number: str | None = None


@router.post("", response_model=UserResponse, status_code=201)
@router.post("/", response_model=UserResponse, status_code=201, include_in_schema=False)
async def create_user(
    body: UserCreate,
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Create a new user in the admin's organization."""
    org_id = admin.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Token missing org claim")

    role = body.role.upper()
    if role not in _VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of {sorted(_VALID_ROLES)}",
        )

    # Check for duplicate email within this org
    existing = await conn.execute(sa.select(_users.c.id).where(_users.c.email == body.email))
    if existing.first():
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    if body.whatsapp_number and await whatsapp_number_taken(conn, body.whatsapp_number):
        raise HTTPException(status_code=409, detail=NUMBER_TAKEN_MESSAGE)

    hashed_password = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt()).decode()

    new_id = uuid.uuid4()
    await conn.execute(
        _users.insert().values(
            id=new_id,
            organization_id=org_id,
            email=body.email,
            hashed_password=hashed_password,
            full_name=body.full_name,
            role=role,
            whatsapp_number=body.whatsapp_number or None,
            status="active",
            access_policy=_DEFAULT_ACCESS_POLICY,
        )
    )

    result = await conn.execute(sa.select(_users).where(_users.c.id == new_id))
    return _row_to_response(result.first())


@router.get("", response_model=list[UserResponse])
@router.get("/", response_model=list[UserResponse], include_in_schema=False)
async def list_users(
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = admin.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Token missing org claim")

    result = await conn.execute(sa.select(_users).where(_users.c.organization_id == org_id))
    return [_row_to_response(r) for r in result.fetchall()]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = admin.get("org")
    result = await conn.execute(
        sa.select(_users).where(
            _users.c.id == user_id,
            _users.c.organization_id == org_id,
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _row_to_response(row)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = admin.get("org")

    if body.role is not None and body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of {sorted(_VALID_ROLES)}",
        )

    result = await conn.execute(
        sa.select(_users).where(
            _users.c.id == user_id,
            _users.c.organization_id == org_id,
        )
    )
    existing = result.first()
    if existing is None:
        raise HTTPException(status_code=404, detail="User not found")

    values: dict[str, Any] = {}
    if body.full_name is not None:
        values["full_name"] = body.full_name
    if body.role is not None:
        values["role"] = body.role
    if body.whatsapp_number is not None:
        values["whatsapp_number"] = body.whatsapp_number.strip() or None
        if values["whatsapp_number"] and await whatsapp_number_taken(
            conn, values["whatsapp_number"], except_user_id=user_id
        ):
            raise HTTPException(status_code=409, detail=NUMBER_TAKEN_MESSAGE)
    if body.password:
        values["hashed_password"] = _bcrypt.hashpw(
            body.password.encode(), _bcrypt.gensalt()
        ).decode()

    if values:
        await conn.execute(
            _users.update()
            .where(
                _users.c.id == user_id,
                _users.c.organization_id == org_id,
            )
            .values(**values)
        )

    result2 = await conn.execute(sa.select(_users).where(_users.c.id == user_id))
    return _row_to_response(result2.first())


@router.patch("/{user_id}/status", response_model=UserResponse)
async def update_user_status(
    user_id: uuid.UUID,
    body: StatusUpdate,
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {sorted(_VALID_STATUSES)}",
        )

    org_id = admin.get("org")
    result = await conn.execute(
        sa.select(_users).where(
            _users.c.id == user_id,
            _users.c.organization_id == org_id,
        )
    )
    if result.first() is None:
        raise HTTPException(status_code=404, detail="User not found")

    await conn.execute(
        _users.update()
        .where(
            _users.c.id == user_id,
            _users.c.organization_id == org_id,
        )
        .values(status=body.status)
    )

    result2 = await conn.execute(sa.select(_users).where(_users.c.id == user_id))
    return _row_to_response(result2.first())


@router.get("/{user_id}/access", response_model=AccessPolicy)
async def get_user_access(
    user_id: uuid.UUID,
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = admin.get("org")
    result = await conn.execute(
        sa.select(_users.c.access_policy).where(
            _users.c.id == user_id,
            _users.c.organization_id == org_id,
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    policy = row.access_policy or _DEFAULT_ACCESS_POLICY
    return AccessPolicy(**policy)


@router.put("/{user_id}/access", response_model=AccessPolicy)
async def update_user_access(
    user_id: uuid.UUID,
    policy: AccessPolicy,
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    if policy.mode not in ("all_projects", "custom_projects"):
        raise HTTPException(
            status_code=400,
            detail="mode must be 'all_projects' or 'custom_projects'",
        )

    org_id = admin.get("org")
    result = await conn.execute(
        sa.select(_users.c.id).where(
            _users.c.id == user_id,
            _users.c.organization_id == org_id,
        )
    )
    if result.first() is None:
        raise HTTPException(status_code=404, detail="User not found")

    await conn.execute(
        _users.update()
        .where(
            _users.c.id == user_id,
            _users.c.organization_id == org_id,
        )
        .values(access_policy=policy.model_dump())
    )
    return policy


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = admin.get("org")
    result = await conn.execute(
        sa.select(_users.c.id).where(
            _users.c.id == user_id,
            _users.c.organization_id == org_id,
        )
    )
    if result.first() is None:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        await conn.execute(
            _users.delete().where(
                _users.c.id == user_id,
                _users.c.organization_id == org_id,
            )
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "foreign key" in msg or "violates" in msg or "constraint" in msg or "23503" in msg:
            raise HTTPException(
                status_code=409,
                detail="User cannot be deleted because they own historical records. Please deactivate or suspend their account instead.",
            ) from exc
        raise HTTPException(status_code=500, detail=f"Database error: {str(exc)}") from exc
