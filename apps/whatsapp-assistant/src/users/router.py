"""Users router — tenant user management for the Mesiri app."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime

import bcrypt as _bcrypt
import jwt
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.application.identity.phone_numbers import NUMBER_TAKEN_MESSAGE, whatsapp_number_taken
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from users.access_service import AccessPolicy, apply_access_policy

router = APIRouter(prefix="/users", tags=["users"])

# ---------------------------------------------------------------------------
# Shared crypto config
# ---------------------------------------------------------------------------
# SECRET_KEY / ALGORITHM: the one shared definition (identity/auth_service).
# A hardcoded copy here ignored MESIRI_JWT_SECRET, so setting the secret in
# production would have locked these routes out while leaving them forgeable.


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


# Raw table reference
users_table = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("organization_id", sa.UUID),
    sa.Column("email", sa.String),
    sa.Column("username", sa.String),
    sa.Column("hashed_password", sa.String),
    sa.Column("full_name", sa.String),
    sa.Column("role", sa.String),
    sa.Column("whatsapp_number", sa.String),
    sa.Column("status", sa.String),
    sa.Column("access_policy", sa.JSON),
)

projects_table = sa.Table(
    "projects",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("organization_id", sa.UUID),
)

sites_table = sa.Table(
    "sites",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("project_id", sa.UUID),
    sa.Column("organization_id", sa.UUID),
)

# project_members/site_members are the tables AuthorizationService (REST) and
# the WhatsApp context resolver (context/main_table_repositories.py) actually
# authorize against -- see migration 0350. access_policy
# below is written alongside for GET /me backward compatibility only; it is
# no longer read for authorization decisions anywhere.
project_members_table = sa.Table(
    "project_members",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("project_id", sa.UUID),
    sa.Column("user_id", sa.UUID),
    sa.Column("role", sa.String),
    sa.Column("site_access_mode", sa.String),
)

site_members_table = sa.Table(
    "site_members",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("site_id", sa.UUID),
    sa.Column("user_id", sa.UUID),
)

_DEFAULT_ACCESS_POLICY: dict = {"mode": "custom_projects", "projects": []}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class UserResponse(BaseModel):
    id: uuid.UUID
    email: str | None = None
    username: str | None = None
    full_name: str
    role: str
    whatsapp_number: str | None = None
    status: str
    access_policy: dict | None = None


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    role: str
    whatsapp_number: str | None = None


class UserUpdate(BaseModel):
    """Partial update — only provided fields are changed. Email is immutable."""

    full_name: str | None = None
    role: str | None = None
    whatsapp_number: str | None = None
    password: str | None = None


class StatusUpdate(BaseModel):
    status: str


def _row_to_response(row) -> UserResponse:
    return UserResponse(
        id=row.id,
        email=row.email,
        username=row.username,
        full_name=row.full_name,
        role=row.role,
        whatsapp_number=row.whatsapp_number,
        status=row.status or "active",
        access_policy=row.access_policy or _DEFAULT_ACCESS_POLICY,
    )


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
async def get_current_admin(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if (payload.get("role") or "").upper() != "ADMIN":
            raise HTTPException(status_code=403, detail="Not authorized (Admin only)")
        return payload
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("", response_model=list[UserResponse])
@router.get("/", response_model=list[UserResponse], include_in_schema=False)
async def list_users(admin_payload: dict = Depends(get_current_admin)):
    engine = get_engine()
    org_id = admin_payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Admin has no organization")

    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(users_table).where(users_table.c.organization_id == org_id)
        )
        rows = result.fetchall()

    return [_row_to_response(row) for row in rows]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: uuid.UUID, admin_payload: dict = Depends(get_current_admin)):
    engine = get_engine()
    org_id = admin_payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Admin has no organization")

    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(users_table).where(
                users_table.c.id == user_id,
                users_table.c.organization_id == org_id,
            )
        )
        row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _row_to_response(row)


@router.post("", response_model=UserResponse)
@router.post("/", response_model=UserResponse, include_in_schema=False)
async def create_user(user_in: UserCreate, admin_payload: dict = Depends(get_current_admin)):
    engine = get_engine()
    org_id = admin_payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Admin has no organization")

    valid_roles = ["ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE"]
    if user_in.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of {valid_roles}")

    user_id = uuid.uuid4()
    async with engine.begin() as conn:
        # Check existing
        result = await conn.execute(
            sa.select(users_table).where(users_table.c.email == user_in.email)
        )
        if result.first():
            raise HTTPException(status_code=400, detail="Email already registered")
        if user_in.whatsapp_number and await whatsapp_number_taken(conn, user_in.whatsapp_number):
            raise HTTPException(status_code=409, detail=NUMBER_TAKEN_MESSAGE)

        hashed_pwd = _hash_pw(user_in.password)
        await conn.execute(
            users_table.insert().values(
                id=user_id,
                organization_id=org_id,
                email=user_in.email,
                hashed_password=hashed_pwd,
                full_name=user_in.full_name,
                role=user_in.role,
                whatsapp_number=user_in.whatsapp_number,
                status="active",
                access_policy=_DEFAULT_ACCESS_POLICY,
            )
        )

    async with engine.connect() as conn:
        result = await conn.execute(sa.select(users_table).where(users_table.c.id == user_id))
        row = result.first()

    return _row_to_response(row)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    user_in: UserUpdate,
    admin_payload: dict = Depends(get_current_admin),
):
    engine = get_engine()
    org_id = admin_payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Admin has no organization")

    if user_in.role is not None:
        valid_roles = ["ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE"]
        if user_in.role not in valid_roles:
            raise HTTPException(
                status_code=400, detail=f"Invalid role. Must be one of {valid_roles}"
            )

    # Build the set of changes from provided fields only.
    values: dict = {}
    if user_in.full_name is not None:
        values["full_name"] = user_in.full_name
    if user_in.role is not None:
        values["role"] = user_in.role
    if user_in.whatsapp_number is not None:
        # Empty string clears the number; otherwise store the trimmed value.
        values["whatsapp_number"] = user_in.whatsapp_number.strip() or None
    if user_in.password:
        values["hashed_password"] = _hash_pw(user_in.password)

    async with engine.begin() as conn:
        # Tenant-scoped lookup: an admin can only edit users in their own org.
        result = await conn.execute(
            sa.select(users_table).where(
                users_table.c.id == user_id,
                users_table.c.organization_id == org_id,
            )
        )
        existing = result.first()
        if existing is None:
            raise HTTPException(status_code=404, detail="User not found")
        if values.get("whatsapp_number") and await whatsapp_number_taken(
            conn, values["whatsapp_number"], except_user_id=user_id
        ):
            raise HTTPException(status_code=409, detail=NUMBER_TAKEN_MESSAGE)

        if values:
            await conn.execute(
                users_table.update()
                .where(
                    users_table.c.id == user_id,
                    users_table.c.organization_id == org_id,
                )
                .values(**values)
            )

    async with engine.connect() as conn:
        result = await conn.execute(sa.select(users_table).where(users_table.c.id == user_id))
        row = result.first()

    return _row_to_response(row)


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: uuid.UUID, admin_payload: dict = Depends(get_current_admin)):
    engine = get_engine()
    org_id = admin_payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Admin has no organization")

    if str(admin_payload.get("sub")) == str(user_id):
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(users_table.c.id).where(
                users_table.c.id == user_id,
                users_table.c.organization_id == org_id,
            )
        )
        if result.first() is None:
            raise HTTPException(status_code=404, detail="User not found")

        try:
            await conn.execute(users_table.delete().where(users_table.c.id == user_id))
        except Exception as exc:
            if "foreign key" in str(exc).lower() or "23503" in str(exc):
                raise HTTPException(
                    status_code=409,
                    detail="User has existing records (projects, reports, or messages) and cannot be deleted. Deactivate the account instead.",
                ) from exc
            raise



@router.patch("/{user_id}/status", response_model=UserResponse)
async def update_user_status(
    user_id: uuid.UUID,
    body: StatusUpdate,
    admin_payload: dict = Depends(get_current_admin),
):
    engine = get_engine()
    org_id = admin_payload.get("org")
    valid_statuses = {"active", "inactive", "suspended", "invited"}

    if body.status not in valid_statuses:
        raise HTTPException(
            status_code=400, detail=f"Invalid status. Must be one of {sorted(valid_statuses)}"
        )

    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(users_table).where(
                users_table.c.id == user_id,
                users_table.c.organization_id == org_id,
            )
        )
        if result.first() is None:
            raise HTTPException(status_code=404, detail="User not found")

        await conn.execute(
            users_table.update()
            .where(
                users_table.c.id == user_id,
                users_table.c.organization_id == org_id,
            )
            # Normalized: user status is stored lowercase, and a caller
            # sending "Active" would make the assistant's lookup miss the
            # row and treat that person as an unrecognized number.
            .values(status=body.status.strip().lower())
        )

    async with engine.connect() as conn:
        result = await conn.execute(sa.select(users_table).where(users_table.c.id == user_id))
        row = result.first()

    return _row_to_response(row)


@router.get("/{user_id}/access", response_model=AccessPolicy)
async def get_user_access(
    user_id: uuid.UUID,
    admin_payload: dict = Depends(get_current_admin),
):
    engine = get_engine()
    org_id = admin_payload.get("org")
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(users_table.c.access_policy).where(
                users_table.c.id == user_id,
                users_table.c.organization_id == org_id,
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
    admin_payload: dict = Depends(get_current_admin),
):
    """Set a user's project/site access.

    Used to only write ``users.access_policy`` -- a JSONB column that
    AuthorizationService and the WhatsApp context resolver stopped reading
    after migration 0350 (see that migration's docstring: three disconnected
    access mechanisms existed, and project_members/site_members is the one
    both consult). That made this endpoint a no-op in practice: an admin
    granting or revoking access here saw the change reflected in the
    dashboard's own UserDetails/Users pages (which still render
    access_policy) while the user's actual REST and WhatsApp access were
    untouched. This now writes project_members/site_members -- a full
    replace of this user's membership set, which the WhatsApp context
    resolver reads directly (context/main_table_repositories.py).

    "all_projects" writes zero project_members rows on purpose: it's read as
    a live, standing bypass everywhere access is checked (AuthorizationService
    ._resolve_project_scope, backend/postgres/actor.py,
    context/main_table_repositories.py, and this app's own
    projects/router.py._is_org_wide)
    -- the same treatment the ADMIN role already gets. An earlier version of
    this endpoint materialized one project_members row per project that
    existed *at grant time*, which silently excluded every project created
    afterwards even though the admin's intent was "all projects, always".
    access_policy is still written for GET /me (documented as reading it for
    backward compatibility), and is now also the source of truth those live
    checks read for a non-admin's org-wide bypass.
    """
    engine = get_engine()
    org_id = admin_payload.get("org")

    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(users_table.c.id, users_table.c.role).where(
                users_table.c.id == user_id,
                users_table.c.organization_id == org_id,
            )
        )
        user_row = result.first()
        if user_row is None:
            raise HTTPException(status_code=404, detail="User not found")

        # Shared with the control panel's platform-admin equivalent (see
        # users/access_service.py) so both surfaces provably apply the same
        # validation, the same membership replace, and the same all_projects
        # bypass semantics.
        await apply_access_policy(
            conn,
            user_id=user_id,
            org_id=org_id,
            user_role=user_row.role,
            policy=policy,
        )

    return policy


# ---------------------------------------------------------------------------
# WhatsApp Messages Explorer DB Tables
# ---------------------------------------------------------------------------
def _wa_ids(whatsapp_number: str | None) -> list[str]:
    """The sender IDs this user's messages carry: their number's digits."""
    digits = re.sub(r"\D", "", whatsapp_number or "")
    return [digits] if digits else []


inbound_messages_table = sa.Table(
    "inbound_messages",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("correlation_id", sa.String),
    sa.Column("sender_wa_id", sa.String),
    sa.Column("message_type", sa.String),
    sa.Column("raw_payload", sa.JSON),
    sa.Column("normalized_message", sa.JSON),
    sa.Column("body_text", sa.String),
    sa.Column("media_object_key", sa.String),
    sa.Column("received_at", sa.DateTime(timezone=True)),
    sa.Column("processed_at", sa.DateTime(timezone=True)),
    sa.Column("processing_status", sa.String),
    sa.Column("error_code", sa.String),
    sa.Column("assistant_reply", sa.String),
)

timeline_entries_table = sa.Table(
    "timeline_entries",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("organization_id", sa.UUID),
    sa.Column("project_id", sa.UUID),
    sa.Column("site_id", sa.UUID),
    sa.Column("event_type", sa.String),
    sa.Column("summary", sa.String),
    sa.Column("occurred_at", sa.DateTime(timezone=True)),
    sa.Column("correlation_id", sa.String),
    sa.Column("source_aggregate_type", sa.String),
    sa.Column("source_aggregate_id", sa.UUID),
)

interactions_table = sa.Table(
    "interactions",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("user_id", sa.UUID),
    sa.Column("kind", sa.String),
    sa.Column("prompt", sa.String),
    sa.Column("status", sa.String),
    sa.Column("correlation_id", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)

journey_traces_table = sa.Table(
    "journey_traces",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("correlation_id", sa.String),
    sa.Column("stage", sa.String),
    sa.Column("stage_payload", sa.JSON),
    sa.Column("duration_ms", sa.Integer),
    sa.Column("succeeded", sa.Boolean),
    sa.Column("error_code", sa.String),
    sa.Column("error_message", sa.String),
    sa.Column("severity", sa.String),
    sa.Column("event_source", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)

provider_executions_table = sa.Table(
    "provider_executions",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("correlation_id", sa.String),
    sa.Column("stage", sa.String),
    sa.Column("provider", sa.String),
    sa.Column("operation", sa.String),
    sa.Column("model", sa.String),
    sa.Column("latency_ms", sa.Float),
    sa.Column("succeeded", sa.Boolean),
    sa.Column("error_code", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


# ---------------------------------------------------------------------------
# WhatsApp Messages Explorer Schemas
# ---------------------------------------------------------------------------
class MessageOutcomeResponse(BaseModel):
    record_type: str
    record_id: uuid.UUID
    summary: str


class MessageProjectResponse(BaseModel):
    id: uuid.UUID
    name: str


class MessageSiteResponse(BaseModel):
    id: uuid.UUID
    name: str


class UserWhatsAppMessageResponse(BaseModel):
    id: str
    correlation_id: str
    sender_wa_id: str
    message_type: str
    body_text: str | None = None
    media_object_key: str | None = None
    occurred_at: datetime
    direction: str
    processing_status: str
    error_code: str | None = None
    clarification_status: str
    project: MessageProjectResponse | None = None
    site: MessageSiteResponse | None = None
    outcome: MessageOutcomeResponse | None = None


class UserWhatsAppMessageListResponse(BaseModel):
    items: list[UserWhatsAppMessageResponse]
    total: int


class MessageTraceResponse(BaseModel):
    stage: str
    succeeded: bool
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    severity: str
    event_source: str
    created_at: datetime


class MessageProviderExecutionResponse(BaseModel):
    stage: str
    provider: str
    operation: str
    model: str | None = None
    latency_ms: float | None = None
    succeeded: bool
    error_code: str | None = None
    created_at: datetime


class UserWhatsAppMessageDetailResponse(BaseModel):
    id: uuid.UUID
    correlation_id: str
    sender_wa_id: str
    message_type: str
    body_text: str | None = None
    media_object_key: str | None = None
    received_at: datetime
    processed_at: datetime | None = None
    processing_status: str
    error_code: str | None = None
    assistant_reply: str | None = None
    raw_payload: dict | None = None
    normalized_message: dict | None = None
    clarification_status: str
    project: MessageProjectResponse | None = None
    site: MessageSiteResponse | None = None
    outcome: MessageOutcomeResponse | None = None
    traces: list[MessageTraceResponse] = []
    providers: list[MessageProviderExecutionResponse] = []


# ---------------------------------------------------------------------------
# WhatsApp Messages Explorer Endpoints
# ---------------------------------------------------------------------------
@router.get("/{user_id}/whatsapp/messages", response_model=UserWhatsAppMessageListResponse)
async def list_user_whatsapp_messages(
    user_id: uuid.UUID,
    wa_id: str | None = None,
    direction: str | None = None,
    message_type: str | None = None,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    processing_status: str | None = None,
    clarification_status: str | None = None,
    has_attachments: bool | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: str = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_payload: dict = Depends(get_current_admin),
):
    engine = get_engine()
    org_id = admin_payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Admin has no organization")

    async with engine.connect() as conn:
        # Check target user
        user_res = await conn.execute(
            sa.select(users_table).where(
                users_table.c.id == user_id, users_table.c.organization_id == org_id
            )
        )
        target_user = user_res.first()
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        # The user's WhatsApp number, as inbound messages store it (digits)
        wa_ids = _wa_ids(target_user.whatsapp_number)

        if not wa_ids:
            return UserWhatsAppMessageListResponse(items=[], total=0)

        # Build SQL where clauses
        inbound_clauses = ["sender_wa_id = ANY(:wa_ids)"]
        outbound_clauses = ["sender_wa_id = ANY(:wa_ids)", "assistant_reply IS NOT NULL"]
        sql_params = {"wa_ids": wa_ids}

        if wa_id:
            inbound_clauses.append("sender_wa_id = :wa_id")
            outbound_clauses.append("sender_wa_id = :wa_id")
            sql_params["wa_id"] = wa_id

        if message_type:
            inbound_clauses.append("message_type = :message_type")
            if message_type != "text":
                outbound_clauses.append("FALSE")
            sql_params["message_type"] = message_type

        if processing_status:
            inbound_clauses.append("processing_status = :processing_status")
            if processing_status != "completed":
                outbound_clauses.append("FALSE")
            sql_params["processing_status"] = processing_status

        if has_attachments is not None:
            if has_attachments:
                inbound_clauses.append("media_object_key IS NOT NULL")
                outbound_clauses.append("FALSE")
            else:
                inbound_clauses.append("media_object_key IS NULL")

        if search:
            inbound_clauses.append("body_text ILIKE :search")
            outbound_clauses.append("assistant_reply ILIKE :search")
            sql_params["search"] = f"%{search}%"

        if date_from:
            inbound_clauses.append("received_at >= :date_from")
            outbound_clauses.append("COALESCE(processed_at, received_at) >= :date_from")
            sql_params["date_from"] = date_from

        if date_to:
            inbound_clauses.append("received_at <= :date_to")
            outbound_clauses.append("COALESCE(processed_at, received_at) <= :date_to")
            sql_params["date_to"] = date_to

        if project_id:
            project_exists = "EXISTS (SELECT 1 FROM timeline_entries te WHERE te.correlation_id = inbound_messages.correlation_id AND te.project_id = :project_id)"
            inbound_clauses.append(project_exists)
            outbound_clauses.append(project_exists)
            sql_params["project_id"] = project_id

        if site_id:
            site_exists = "EXISTS (SELECT 1 FROM timeline_entries te WHERE te.correlation_id = inbound_messages.correlation_id AND te.site_id = :site_id)"
            inbound_clauses.append(site_exists)
            outbound_clauses.append(site_exists)
            sql_params["site_id"] = site_id

        if clarification_status:
            if clarification_status == "awaiting_user":
                clar_exists = "EXISTS (SELECT 1 FROM interactions i WHERE i.correlation_id = inbound_messages.correlation_id AND i.kind = 'clarification' AND i.status = 'pending')"
                inbound_clauses.append(clar_exists)
                outbound_clauses.append(clar_exists)
            elif clarification_status == "resolved":
                clar_exists = "EXISTS (SELECT 1 FROM interactions i WHERE i.correlation_id = inbound_messages.correlation_id AND i.kind = 'clarification' AND i.status = 'resolved')"
                inbound_clauses.append(clar_exists)
                outbound_clauses.append(clar_exists)
            elif clarification_status == "none":
                clar_not_exists = "NOT EXISTS (SELECT 1 FROM interactions i WHERE i.correlation_id = inbound_messages.correlation_id AND i.kind = 'clarification')"
                inbound_clauses.append(clar_not_exists)
                outbound_clauses.append(clar_not_exists)

        inbound_select = f"""
        SELECT 
            id,
            correlation_id,
            sender_wa_id,
            message_type,
            body_text,
            media_object_key,
            received_at AS occurred_at,
            'inbound' AS direction,
            processing_status,
            error_code
        FROM inbound_messages
        WHERE {" AND ".join(inbound_clauses)}
        """

        outbound_select = f"""
        SELECT 
            id,
            correlation_id,
            sender_wa_id,
            'text' AS message_type,
            assistant_reply AS body_text,
            NULL AS media_object_key,
            COALESCE(processed_at, received_at) AS occurred_at,
            'outbound' AS direction,
            'completed' AS processing_status,
            NULL AS error_code
        FROM inbound_messages
        WHERE {" AND ".join(outbound_clauses)}
        """

        if direction == "inbound":
            query = inbound_select
        elif direction == "outbound":
            query = outbound_select
        else:
            query = f"({inbound_select}) UNION ALL ({outbound_select})"

        sort_dir = "ASC" if sort == "asc" else "DESC"
        full_query = f"""
        SELECT * FROM ({query}) q
        ORDER BY occurred_at {sort_dir}, id {sort_dir}
        LIMIT :limit OFFSET :offset
        """

        count_query = f"SELECT COUNT(*) FROM ({query}) q"

        rows = (
            (
                await conn.execute(
                    sa.text(full_query), {**sql_params, "limit": limit, "offset": offset}
                )
            )
            .mappings()
            .all()
        )
        total = (await conn.execute(sa.text(count_query), sql_params)).scalar_one()

        correlation_ids = [row["correlation_id"] for row in rows]
        timeline_lookup = {}
        interaction_lookup = {}
        projects_lookup = {}
        sites_lookup = {}

        if correlation_ids:
            # Query timeline entries
            t_res = await conn.execute(
                sa.select(
                    timeline_entries_table.c.correlation_id,
                    timeline_entries_table.c.project_id,
                    timeline_entries_table.c.site_id,
                    timeline_entries_table.c.event_type,
                    timeline_entries_table.c.summary,
                    timeline_entries_table.c.source_aggregate_type,
                    timeline_entries_table.c.source_aggregate_id,
                ).where(timeline_entries_table.c.correlation_id.in_(correlation_ids))
            )
            t_rows = t_res.fetchall()
            for r in t_rows:
                timeline_lookup[r.correlation_id] = r

            # Query projects & sites
            project_ids = {r.project_id for r in t_rows if r.project_id}
            site_ids = {r.site_id for r in t_rows if r.site_id}

            if project_ids:
                p_res = await conn.execute(
                    sa.select(projects_table.c.id, projects_table.c.name).where(
                        projects_table.c.id.in_(project_ids)
                    )
                )
                projects_lookup = {r.id: r.name for r in p_res.fetchall()}

            if site_ids:
                s_res = await conn.execute(
                    sa.select(sites_table.c.id, sites_table.c.name).where(
                        sites_table.c.id.in_(site_ids)
                    )
                )
                sites_lookup = {r.id: r.name for r in s_res.fetchall()}

            # Query interactions
            i_res = await conn.execute(
                sa.select(
                    interactions_table.c.correlation_id,
                    interactions_table.c.kind,
                    interactions_table.c.status,
                ).where(interactions_table.c.correlation_id.in_(correlation_ids))
            )
            i_rows = i_res.fetchall()
            for r in i_rows:
                interaction_lookup[r.correlation_id] = r

        items = []
        for row in rows:
            cid = row["correlation_id"]

            project_data = None
            site_data = None
            outcome_data = None

            t_entry = timeline_lookup.get(cid)
            if t_entry:
                if t_entry.project_id and t_entry.project_id in projects_lookup:
                    project_data = MessageProjectResponse(
                        id=t_entry.project_id, name=projects_lookup[t_entry.project_id]
                    )
                if t_entry.site_id and t_entry.site_id in sites_lookup:
                    site_data = MessageSiteResponse(
                        id=t_entry.site_id, name=sites_lookup[t_entry.site_id]
                    )
                if t_entry.source_aggregate_type:
                    outcome_data = MessageOutcomeResponse(
                        record_type=t_entry.source_aggregate_type,
                        record_id=t_entry.source_aggregate_id,
                        summary=t_entry.summary,
                    )

            i_entry = interaction_lookup.get(cid)
            clar_status = "none"
            if i_entry and i_entry.kind == "clarification":
                if i_entry.status == "pending":
                    clar_status = "awaiting_user"
                else:
                    clar_status = i_entry.status

            msg_id = str(row["id"])
            if row["direction"] == "outbound":
                msg_id = f"{msg_id}_reply"

            items.append(
                UserWhatsAppMessageResponse(
                    id=msg_id,
                    correlation_id=cid,
                    sender_wa_id=row["sender_wa_id"],
                    message_type=row["message_type"],
                    body_text=row["body_text"],
                    media_object_key=row["media_object_key"],
                    occurred_at=row["occurred_at"],
                    direction=row["direction"],
                    processing_status=row["processing_status"],
                    error_code=row["error_code"],
                    clarification_status=clar_status,
                    project=project_data,
                    site=site_data,
                    outcome=outcome_data,
                )
            )

        return UserWhatsAppMessageListResponse(items=items, total=total)


@router.get(
    "/{user_id}/whatsapp/messages/{message_id}", response_model=UserWhatsAppMessageDetailResponse
)
async def get_user_whatsapp_message_detail(
    user_id: uuid.UUID,
    message_id: str,
    admin_payload: dict = Depends(get_current_admin),
):
    engine = get_engine()
    org_id = admin_payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Admin has no organization")

    # Handle reply suffix if present
    msg_uuid_str = message_id
    if msg_uuid_str.endswith("_reply"):
        msg_uuid_str = msg_uuid_str[:-6]

    try:
        msg_uuid = uuid.UUID(msg_uuid_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid message_id") from exc

    async with engine.connect() as conn:
        # Check target user
        user_res = await conn.execute(
            sa.select(users_table).where(
                users_table.c.id == user_id, users_table.c.organization_id == org_id
            )
        )
        target_user = user_res.first()
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        # The user's WhatsApp number, as inbound messages store it (digits)
        wa_ids = set(_wa_ids(target_user.whatsapp_number))

        # Fetch message detail
        msg_res = await conn.execute(
            sa.select(inbound_messages_table).where(inbound_messages_table.c.id == msg_uuid)
        )
        msg_row = msg_res.first()
        if not msg_row or msg_row.sender_wa_id not in wa_ids:
            raise HTTPException(status_code=404, detail="Message not found")

        cid = msg_row.correlation_id

        # Query timeline outcome
        t_res = await conn.execute(
            sa.select(
                timeline_entries_table.c.project_id,
                timeline_entries_table.c.site_id,
                timeline_entries_table.c.event_type,
                timeline_entries_table.c.summary,
                timeline_entries_table.c.source_aggregate_type,
                timeline_entries_table.c.source_aggregate_id,
            ).where(timeline_entries_table.c.correlation_id == cid)
        )
        t_row = t_res.first()

        project_data = None
        site_data = None
        outcome_data = None

        if t_row:
            if t_row.project_id:
                p_res = await conn.execute(
                    sa.select(projects_table.c.name).where(projects_table.c.id == t_row.project_id)
                )
                p_row = p_res.first()
                if p_row:
                    project_data = MessageProjectResponse(id=t_row.project_id, name=p_row.name)

            if t_row.site_id:
                s_res = await conn.execute(
                    sa.select(sites_table.c.name).where(sites_table.c.id == t_row.site_id)
                )
                s_row = s_res.first()
                if s_row:
                    site_data = MessageSiteResponse(id=t_row.site_id, name=s_row.name)

            if t_row.source_aggregate_type:
                outcome_data = MessageOutcomeResponse(
                    record_type=t_row.source_aggregate_type,
                    record_id=t_row.source_aggregate_id,
                    summary=t_row.summary,
                )

        # Query interaction (clarification)
        i_res = await conn.execute(
            sa.select(interactions_table.c.kind, interactions_table.c.status).where(
                interactions_table.c.correlation_id == cid
            )
        )
        i_row = i_res.first()
        clar_status = "none"
        if i_row and i_row.kind == "clarification":
            if i_row.status == "pending":
                clar_status = "awaiting_user"
            else:
                clar_status = i_row.status

        # Query traces
        traces_res = await conn.execute(
            sa.select(journey_traces_table)
            .where(journey_traces_table.c.correlation_id == cid)
            .order_by(journey_traces_table.c.created_at.asc())
        )
        traces = [
            MessageTraceResponse(
                stage=r.stage,
                succeeded=r.succeeded,
                duration_ms=r.duration_ms,
                error_code=r.error_code,
                error_message=r.error_message,
                severity=r.severity or "info",
                event_source=r.event_source or "pipeline_stage",
                created_at=r.created_at,
            )
            for r in traces_res.fetchall()
        ]

        # Query provider executions
        pe_res = await conn.execute(
            sa.select(provider_executions_table)
            .where(provider_executions_table.c.correlation_id == cid)
            # BE-25 per-call cost rows are for the control panel, not tenants.
            .where(provider_executions_table.c.stage != "metered")
            .order_by(provider_executions_table.c.created_at.asc())
        )
        providers = [
            MessageProviderExecutionResponse(
                stage=r.stage,
                provider=r.provider,
                operation=r.operation,
                model=r.model,
                latency_ms=r.latency_ms,
                succeeded=r.succeeded,
                error_code=r.error_code,
                created_at=r.created_at,
            )
            for r in pe_res.fetchall()
        ]

        return UserWhatsAppMessageDetailResponse(
            id=msg_row.id,
            correlation_id=cid,
            sender_wa_id=msg_row.sender_wa_id,
            message_type=msg_row.message_type,
            body_text=msg_row.body_text,
            media_object_key=msg_row.media_object_key,
            received_at=msg_row.received_at,
            processed_at=msg_row.processed_at,
            processing_status=msg_row.processing_status,
            error_code=msg_row.error_code,
            assistant_reply=msg_row.assistant_reply,
            raw_payload=msg_row.raw_payload,
            normalized_message=msg_row.normalized_message,
            clarification_status=clar_status,
            project=project_data,
            site=site_data,
            outcome=outcome_data,
            traces=traces,
            providers=providers,
        )
