"""Platform-admin account management for the control panel.

Distinct from the tenant-scoped users/router.py (both the apps/whatsapp-
assistant and backend/ copies) -- those hard-filter every query by the
caller's organization_id, which platform admins don't have. This file owns
all SQL for platform-admin accounts: role='ADMIN' AND organization_id IS
NULL, never anything else. Gated by require_platform_admin on every route.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

import bcrypt as _bcrypt
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.application.audit.record import record_admin_action
from mesiri.domains.audit import actions as audit
from mesiri.domains.audit.actions import actor_from_admin
from mesiri.domains.shared.auth import require_platform_admin

router = APIRouter(prefix="/admin/platform-users", tags=["admin"])

_VALID_STATUSES = {"active", "inactive", "suspended", "invited"}


def _hash_pw(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def _get_engine():
    host = os.environ.get("MESIRI_POSTGRES__HOST", "localhost")
    port = os.environ.get("MESIRI_POSTGRES__PORT", "5432")
    user = os.environ.get("MESIRI_POSTGRES__USER", "mesiri")
    password = os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")
    database = os.environ.get("MESIRI_POSTGRES__DATABASE", "mesiri")
    dsn = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    return create_async_engine(dsn, echo=False, pool_pre_ping=True)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _get_engine()
    return _engine


users_table = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("organization_id", sa.UUID),
    sa.Column("email", sa.String),
    sa.Column("hashed_password", sa.String),
    sa.Column("full_name", sa.String),
    sa.Column("role", sa.String),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


class PlatformUser(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    status: str
    created_at: datetime | None = None


class PlatformUserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)
    full_name: str


class PlatformUserUpdate(BaseModel):
    full_name: str | None = None
    status: str | None = None
    new_password: str | None = Field(default=None, min_length=8)


@router.get("", response_model=list[PlatformUser])
async def list_platform_users(_admin: dict = Depends(require_platform_admin)):
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(
                users_table.c.id,
                users_table.c.email,
                users_table.c.full_name,
                users_table.c.status,
                users_table.c.created_at,
            )
            .where(users_table.c.role == "ADMIN", users_table.c.organization_id.is_(None))
            .order_by(users_table.c.created_at)
        )
        rows = result.fetchall()
    return [
        PlatformUser(
            id=row.id,
            email=row.email,
            full_name=row.full_name or "",
            status=row.status or "active",
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("", response_model=PlatformUser)
async def create_platform_user(
    user_in: PlatformUserCreate, _admin: dict = Depends(require_platform_admin)
):
    engine = get_engine()
    user_id = uuid.uuid4()

    async with engine.begin() as conn:
        existing = await conn.execute(
            sa.select(users_table.c.id).where(users_table.c.email == user_in.email)
        )
        if existing.first():
            raise HTTPException(status_code=400, detail="Email already registered")

        await conn.execute(
            users_table.insert().values(
                id=user_id,
                organization_id=None,
                email=user_in.email,
                hashed_password=_hash_pw(user_in.password),
                full_name=user_in.full_name,
                role="ADMIN",
                status="active",
            )
        )
        await record_admin_action(
            conn,
            actor=actor_from_admin(_admin),
            action=audit.PLATFORM_ADMIN_CREATED,
            target_type="user",
            target_id=user_id,
            summary=f"Added platform admin {user_in.full_name}",
            details={"email": user_in.email, "full_name": user_in.full_name},
        )

    return PlatformUser(
        id=user_id, email=user_in.email, full_name=user_in.full_name, status="active"
    )


@router.patch("/{user_id}", response_model=PlatformUser)
async def update_platform_user(
    user_id: uuid.UUID,
    update: PlatformUserUpdate,
    admin: dict = Depends(require_platform_admin),
):
    engine = get_engine()

    async with engine.begin() as conn:
        existing = await conn.execute(
            sa.select(
                users_table.c.id, users_table.c.email, users_table.c.full_name, users_table.c.status
            ).where(
                users_table.c.id == user_id,
                users_table.c.role == "ADMIN",
                users_table.c.organization_id.is_(None),
            )
        )
        row = existing.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Platform admin not found")

        values: dict = {}

        if update.full_name is not None:
            values["full_name"] = update.full_name

        if update.status is not None:
            if update.status not in _VALID_STATUSES:
                raise HTTPException(status_code=400, detail=f"Invalid status: {update.status}")
            if update.status != "active":
                if str(user_id) == admin.get("sub"):
                    raise HTTPException(
                        status_code=400, detail="Cannot deactivate your own account"
                    )
                active_count = await conn.execute(
                    sa.select(sa.func.count())
                    .select_from(users_table)
                    .where(
                        users_table.c.role == "ADMIN",
                        users_table.c.organization_id.is_(None),
                        users_table.c.status == "active",
                        users_table.c.id != user_id,
                    )
                )
                if active_count.scalar_one() < 1:
                    raise HTTPException(
                        status_code=400, detail="Cannot deactivate the last active platform admin"
                    )
            values["status"] = update.status

        if update.new_password is not None:
            values["hashed_password"] = _hash_pw(update.new_password)

        if values:
            await conn.execute(
                users_table.update().where(users_table.c.id == user_id).values(**values)
            )
            await record_admin_action(
                conn,
                actor=actor_from_admin(admin),
                action=audit.PLATFORM_ADMIN_UPDATED,
                target_type="user",
                target_id=user_id,
                summary=f"Platform admin {row.full_name or row.email}: changed "
                + ", ".join(sorted("password" if k == "hashed_password" else k for k in values)),
                details={
                    "before": {k: getattr(row, k) for k in values if k != "hashed_password"},
                    "after": values,
                },
            )

        final = await conn.execute(
            sa.select(
                users_table.c.email,
                users_table.c.full_name,
                users_table.c.status,
                users_table.c.created_at,
            ).where(users_table.c.id == user_id)
        )
        final_row = final.first()

    return PlatformUser(
        id=user_id,
        email=final_row.email,
        full_name=final_row.full_name or "",
        status=final_row.status or "active",
        created_at=final_row.created_at,
    )
