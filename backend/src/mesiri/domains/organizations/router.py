import uuid
from datetime import datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.shared.auth import require_admin
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.models.organization import (
    DeploymentType,
    OrganizationStatus,
)
from mesiri.infrastructure.postgres.repositories.organization_settings import (
    PostgresOrganizationSettingsRepository,
)

router = APIRouter(prefix="/company", tags=["company"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    deployment_type: DeploymentType
    db_route: str
    status: OrganizationStatus
    code: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    primary_contact: str | None = None
    timezone: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CompanyUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    primary_contact: str | None = None
    timezone: str | None = None


class CompanySummaryResponse(BaseModel):
    total_users: int
    active_users: int
    admin_count: int
    pm_count: int
    site_engineer_count: int
    finance_count: int
    total_projects: int
    total_sites: int
    wa_mapped_users: int
    wa_unmapped_users: int
    active_conversations_count: int
    messages_received_today: int
    messages_requiring_clarification: int
    last_whatsapp_activity: datetime | None = None


class UserMinResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    status: str
    whatsapp_number: str | None = None


class MessageSummary(BaseModel):
    id: uuid.UUID
    correlation_id: str
    direction: str  # "inbound" | "outbound"
    sender_wa_id: str
    message_type: str
    body: str
    processing_status: str
    error_code: str | None = None
    timestamp: datetime
    member: UserMinResponse | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    site_id: uuid.UUID | None = None
    site_name: str | None = None


class MessageListResponse(BaseModel):
    items: list[MessageSummary]
    total: int


class ConversationSummary(BaseModel):
    sender_wa_id: str
    member: UserMinResponse | None = None
    last_message_preview: str
    last_direction: str  # "inbound" | "outbound"
    last_activity: datetime
    message_count: int
    processing_status: str | None = None
    error_code: str | None = None


class ConversationListResponse(BaseModel):
    items: list[ConversationSummary]
    total: int


class JourneyTrace(BaseModel):
    stage: str
    succeeded: bool
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime


class ProviderExecution(BaseModel):
    stage: str
    provider: str
    operation: str
    model: str | None = None
    latency_ms: float | None = None
    succeeded: bool
    created_at: datetime


class TimelineEntryMin(BaseModel):
    id: uuid.UUID
    event_type: str
    summary: str
    source_aggregate_type: str
    source_aggregate_id: uuid.UUID
    occurred_at: datetime


class InteractionMin(BaseModel):
    id: uuid.UUID
    kind: str
    prompt: str
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


class MessageDetailResponse(BaseModel):
    id: uuid.UUID
    correlation_id: str
    sender_wa_id: str
    message_type: str
    body_text: str | None = None
    processing_status: str
    error_code: str | None = None
    received_at: datetime
    processed_at: datetime | None = None
    raw_payload_captured: bool
    assistant_reply: str | None = None
    raw_payload: dict | None = None
    normalized_message: dict | None = None
    media_object_key: str | None = None
    member: UserMinResponse | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    traces: list[JourneyTrace] = []
    providers: list[ProviderExecution] = []
    timeline_entries: list[TimelineEntryMin] = []
    interactions: list[InteractionMin] = []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("", response_model=CompanyResponse)
async def get_company(
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = admin.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Token missing org claim")

    query = sa.text(
        "SELECT id, name, deployment_type, db_route, status, code, email, phone, address, primary_contact, timezone, created_at, updated_at "
        "FROM organizations WHERE id = :org_id"
    )
    result = await conn.execute(query, {"org_id": uuid.UUID(org_id)})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Organization not found")
    return row


@router.patch("", response_model=CompanyResponse)
async def update_company(
    body: CompanyUpdate,
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = admin.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Token missing org claim")

    # Build UPDATE query
    updates = []
    params = {"org_id": uuid.UUID(org_id)}
    for field, val in body.model_dump(exclude_unset=True).items():
        updates.append(f"{field} = :{field}")
        params[field] = val

    if not updates:
        # No updates requested, just return current
        return await get_company(admin, conn)

    query = sa.text(
        f"UPDATE organizations SET {', '.join(updates)}, updated_at = now() WHERE id = :org_id"
    )
    await conn.execute(query, params)
    return await get_company(admin, conn)


# ---------------------------------------------------------------------------
# Settings — per-tenant tunable rules (migration 0364)
# ---------------------------------------------------------------------------
@router.get("/settings")
async def get_company_settings(
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Every known setting for the caller's org, with defaults filled in for
    anything never configured — so the control panel renders a complete form
    on first load without special-casing a brand-new tenant.

    `specs` carries the catalog (key + description + default) alongside the
    live values so the UI doesn't have to hardcode a copy of the setting
    list that could drift from the backend's.
    """
    org_id = admin.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Token missing org claim")

    repo = PostgresOrganizationSettingsRepository(conn)
    values = await repo.get_all(uuid.UUID(org_id))
    return {
        "settings": values,
        "specs": [
            {"key": spec.key, "description": spec.description, "default": spec.default}
            for spec in org_settings.all_specs()
        ],
        "valid_roles": sorted(org_settings.VALID_ROLES),
    }


class OrganizationSettingUpdate(BaseModel):
    key: str
    value: object


@router.put("/settings")
async def update_company_setting(
    body: OrganizationSettingUpdate,
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Set one setting for the caller's own org.

    Validation lives in domains/organizations/settings.py, not here — an
    unknown key or a malformed value is rejected at this boundary rather
    than persisted as a row nothing will ever read.
    """
    org_id = admin.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="Token missing org claim")

    # Modules are tied to what a customer pays for: a company admin can read
    # them (GET above) but only a platform admin may change them, through
    # PUT /admin/organizations/{org_id}/settings.
    if body.key in org_settings.SUPERADMIN_ONLY_KEYS:
        raise HTTPException(
            status_code=403, detail=f"'{body.key}' can only be changed by the Mesiri team"
        )

    try:
        canonical = org_settings.validate(body.key, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    repo = PostgresOrganizationSettingsRepository(conn)
    user_id = admin.get("sub")
    await repo.set(
        uuid.UUID(org_id),
        body.key,
        canonical,
        updated_by=uuid.UUID(user_id) if user_id else None,
    )
    return {"key": body.key, "value": canonical}


@router.get("/summary", response_model=CompanySummaryResponse)
async def get_company_summary(
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_uuid = uuid.UUID(admin.get("org"))

    # 1. Total & Active users
    u_total = await conn.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE organization_id = :org_id"), {"org_id": org_uuid}
    )
    u_active = await conn.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE organization_id = :org_id AND status = 'active'"),
        {"org_id": org_uuid},
    )

    # 2. Roles count
    r_admin = await conn.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE organization_id = :org_id AND role = 'ADMIN'"),
        {"org_id": org_uuid},
    )
    r_pm = await conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM users WHERE organization_id = :org_id AND role = 'PROJECT_MANAGER'"
        ),
        {"org_id": org_uuid},
    )
    r_engineer = await conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM users WHERE organization_id = :org_id AND role = 'SITE_ENGINEER'"
        ),
        {"org_id": org_uuid},
    )
    r_finance = await conn.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE organization_id = :org_id AND role = 'FINANCE'"),
        {"org_id": org_uuid},
    )

    # 3. Projects & Sites
    p_total = await conn.execute(
        sa.text("SELECT COUNT(*) FROM projects WHERE organization_id = :org_id"),
        {"org_id": org_uuid},
    )
    s_total = await conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM sites WHERE project_id IN (SELECT id FROM projects WHERE organization_id = :org_id)"
        ),
        {"org_id": org_uuid},
    )

    # 4. WhatsApp coverage
    wa_mapped = await conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM users WHERE organization_id = :org_id AND whatsapp_number IS NOT NULL"
        ),
        {"org_id": org_uuid},
    )
    wa_unmapped = await conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM users WHERE organization_id = :org_id AND whatsapp_number IS NULL"
        ),
        {"org_id": org_uuid},
    )

    # 5. Conversations, received today, requiring clarification, last activity
    conversations = await conn.execute(
        sa.text(
            "SELECT COUNT(DISTINCT sender_wa_id) FROM inbound_messages WHERE organization_id = :org_id"
        ),
        {"org_id": org_uuid},
    )
    today_received = await conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM inbound_messages WHERE organization_id = :org_id AND received_at >= CURRENT_DATE"
        ),
        {"org_id": org_uuid},
    )
    clarifications = await conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM interactions WHERE user_id IN (SELECT id FROM users WHERE organization_id = :org_id) AND status = 'pending'"
        ),
        {"org_id": org_uuid},
    )
    last_act = await conn.execute(
        sa.text("SELECT MAX(received_at) FROM inbound_messages WHERE organization_id = :org_id"),
        {"org_id": org_uuid},
    )

    return CompanySummaryResponse(
        total_users=u_total.scalar_one(),
        active_users=u_active.scalar_one(),
        admin_count=r_admin.scalar_one(),
        pm_count=r_pm.scalar_one(),
        site_engineer_count=r_engineer.scalar_one(),
        finance_count=r_finance.scalar_one(),
        total_projects=p_total.scalar_one(),
        total_sites=s_total.scalar_one(),
        wa_mapped_users=wa_mapped.scalar_one(),
        wa_unmapped_users=wa_unmapped.scalar_one(),
        active_conversations_count=conversations.scalar_one(),
        messages_received_today=today_received.scalar_one(),
        messages_requiring_clarification=clarifications.scalar_one(),
        last_whatsapp_activity=last_act.scalar_one(),
    )


@router.get("/whatsapp/messages", response_model=MessageListResponse)
async def list_messages(
    direction: str = "all",
    search: str | None = None,
    member_id: uuid.UUID | None = None,
    message_type: str | None = None,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    processing_status: str | None = None,
    has_attachments: bool | None = None,
    mapped_participant: str | None = None,  # "mapped" | "unmapped" | "all"
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = uuid.UUID(admin.get("org"))

    # Build filtering clauses
    where_inbound = ["im.organization_id = :org_id"]
    where_outbound = ["im.organization_id = :org_id", "im.assistant_reply IS NOT NULL"]
    params = {"org_id": org_id, "limit": limit, "offset": offset}

    if search:
        search_like = f"%{search}%"
        where_inbound.append(
            "(im.body_text ILIKE :search_like OR im.sender_wa_id ILIKE :search_like OR u.full_name ILIKE :search_like)"
        )
        where_outbound.append(
            "(im.assistant_reply ILIKE :search_like OR im.sender_wa_id ILIKE :search_like OR u.full_name ILIKE :search_like)"
        )
        params["search_like"] = search_like

    if member_id:
        where_inbound.append("u.id = :member_id")
        where_outbound.append("u.id = :member_id")
        params["member_id"] = member_id

    if message_type:
        where_inbound.append("im.message_type = :message_type")
        where_outbound.append("1=0")  # Outbound is always text reply
        params["message_type"] = message_type

    if project_id:
        where_inbound.append("im.project_id = :project_id")
        where_outbound.append("im.project_id = :project_id")
        params["project_id"] = project_id

    if site_id:
        where_inbound.append("im.site_id = :site_id")
        where_outbound.append("im.site_id = :site_id")
        params["site_id"] = site_id

    if processing_status:
        where_inbound.append("im.processing_status = :processing_status")
        where_outbound.append("im.processing_status = :processing_status")
        params["processing_status"] = processing_status

    if has_attachments is not None:
        if has_attachments:
            where_inbound.append("im.media_object_key IS NOT NULL")
            where_outbound.append(
                "1=0"
            )  # Outbound from DB has no media_object_key stored on message log row
        else:
            where_inbound.append("im.media_object_key IS NULL")

    if mapped_participant == "mapped":
        where_inbound.append("u.id IS NOT NULL")
        where_outbound.append("u.id IS NOT NULL")
    elif mapped_participant == "unmapped":
        where_inbound.append("u.id IS NULL")
        where_outbound.append("u.id IS NULL")

    # Build query UNION
    inbound_part = f"""
        SELECT 
            im.id, im.correlation_id, 'inbound' AS direction, im.sender_wa_id, im.message_type,
            COALESCE(im.body_text, '') AS body, im.processing_status, im.error_code, im.received_at AS timestamp,
            im.project_id, p.name AS project_name, im.site_id, s.name AS site_name,
            u.id AS user_id, u.email AS user_email, u.full_name AS user_name, u.role AS user_role, u.status AS user_status
        FROM inbound_messages im
        LEFT JOIN users u ON u.whatsapp_number = im.sender_wa_id
        LEFT JOIN projects p ON p.id = im.project_id
        LEFT JOIN sites s ON s.id = im.site_id
        WHERE {" AND ".join(where_inbound)}
    """

    outbound_part = f"""
        SELECT 
            im.id, im.correlation_id, 'outbound' AS direction, im.sender_wa_id, 'text' AS message_type,
            COALESCE(im.assistant_reply, '') AS body, 'completed' AS processing_status, NULL AS error_code, COALESCE(im.processed_at, im.received_at) AS timestamp,
            im.project_id, p.name AS project_name, im.site_id, s.name AS site_name,
            u.id AS user_id, u.email AS user_email, u.full_name AS user_name, u.role AS user_role, u.status AS user_status
        FROM inbound_messages im
        LEFT JOIN users u ON u.whatsapp_number = im.sender_wa_id
        LEFT JOIN projects p ON p.id = im.project_id
        LEFT JOIN sites s ON s.id = im.site_id
        WHERE {" AND ".join(where_outbound)}
    """

    if direction == "inbound":
        query_body = inbound_part
    elif direction == "outbound":
        query_body = outbound_part
    else:
        query_body = f"{inbound_part} UNION ALL {outbound_part}"

    query_str = f"""
        SELECT * FROM ({query_body}) q
        ORDER BY timestamp DESC
        LIMIT :limit OFFSET :offset
    """

    count_str = f"SELECT COUNT(*) FROM ({query_body}) q"

    rows = (await conn.execute(sa.text(query_str), params)).mappings().all()
    total = (
        await conn.execute(
            sa.text(count_str), {k: v for k, v in params.items() if k not in ("limit", "offset")}
        )
    ).scalar_one()

    items = []
    for r in rows:
        member = None
        if r.user_id:
            member = UserMinResponse(
                id=r.user_id,
                email=r.user_email,
                full_name=r.user_name,
                role=r.user_role,
                status=r.user_status,
                whatsapp_number=r.sender_wa_id,
            )

        items.append(
            MessageSummary(
                id=r.id,
                correlation_id=r.correlation_id,
                direction=r.direction,
                sender_wa_id=r.sender_wa_id,
                message_type=r.message_type,
                body=r.body,
                processing_status=r.processing_status,
                error_code=r.error_code,
                timestamp=r.timestamp,
                member=member,
                project_id=r.project_id,
                project_name=r.project_name,
                site_id=r.site_id,
                site_name=r.site_name,
            )
        )

    return MessageListResponse(items=items, total=total)


@router.get("/whatsapp/messages/{message_id}", response_model=MessageDetailResponse)
async def get_message_detail(
    message_id: uuid.UUID,
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = uuid.UUID(admin.get("org"))

    query = sa.text(
        "SELECT im.id, im.correlation_id, im.sender_wa_id, im.message_type, im.body_text, im.processing_status, "
        "im.error_code, im.received_at, im.processed_at, im.raw_payload_captured, im.assistant_reply, "
        "im.raw_payload, im.normalized_message, im.media_object_key, im.project_id, p.name AS project_name, "
        "im.site_id, s.name AS site_name, u.id AS user_id, u.email AS user_email, u.full_name AS user_name, "
        "u.role AS user_role, u.status AS user_status "
        "FROM inbound_messages im "
        "LEFT JOIN users u ON u.whatsapp_number = im.sender_wa_id "
        "LEFT JOIN projects p ON p.id = im.project_id "
        "LEFT JOIN sites s ON s.id = im.site_id "
        "WHERE im.id = :message_id AND im.organization_id = :org_id"
    )
    result = await conn.execute(query, {"message_id": message_id, "org_id": org_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")

    # Traces
    traces_rows = (
        (
            await conn.execute(
                sa.text(
                    "SELECT stage, succeeded, duration_ms, error_code, error_message, created_at FROM journey_traces WHERE correlation_id = :cid ORDER BY created_at ASC"
                ),
                {"cid": row.correlation_id},
            )
        )
        .mappings()
        .all()
    )

    # Providers
    providers_rows = (
        (
            await conn.execute(
                sa.text(
                    "SELECT stage, provider, operation, model, latency_ms, succeeded, created_at FROM provider_executions WHERE correlation_id = :cid ORDER BY created_at ASC"
                ),
                {"cid": row.correlation_id},
            )
        )
        .mappings()
        .all()
    )

    # Timeline
    timeline_rows = (
        (
            await conn.execute(
                sa.text(
                    "SELECT id, event_type, summary, source_aggregate_type, source_aggregate_id, occurred_at FROM timeline_entries WHERE correlation_id = :cid ORDER BY occurred_at ASC"
                ),
                {"cid": row.correlation_id},
            )
        )
        .mappings()
        .all()
    )

    # Interactions
    interactions_rows = (
        (
            await conn.execute(
                sa.text(
                    "SELECT id, kind, prompt, status, created_at, resolved_at FROM interactions WHERE correlation_id = :cid ORDER BY created_at ASC"
                ),
                {"cid": row.correlation_id},
            )
        )
        .mappings()
        .all()
    )

    member = None
    if row.user_id:
        member = UserMinResponse(
            id=row.user_id,
            email=row.user_email,
            full_name=row.user_name,
            role=row.user_role,
            status=row.user_status,
            whatsapp_number=row.sender_wa_id,
        )

    return MessageDetailResponse(
        id=row.id,
        correlation_id=row.correlation_id,
        sender_wa_id=row.sender_wa_id,
        message_type=row.message_type,
        body_text=row.body_text,
        processing_status=row.processing_status,
        error_code=row.error_code,
        received_at=row.received_at,
        processed_at=row.processed_at,
        raw_payload_captured=row.raw_payload_captured,
        assistant_reply=row.assistant_reply,
        raw_payload=row.raw_payload,
        normalized_message=row.normalized_message,
        media_object_key=row.media_object_key,
        member=member,
        project_id=row.project_id,
        project_name=row.project_name,
        site_id=row.site_id,
        site_name=row.site_name,
        traces=[JourneyTrace(**t) for t in traces_rows],
        providers=[ProviderExecution(**p) for p in providers_rows],
        timeline_entries=[TimelineEntryMin(**te) for te in timeline_rows],
        interactions=[InteractionMin(**i) for i in interactions_rows],
    )


@router.get("/whatsapp/conversations", response_model=ConversationListResponse)
async def list_conversations(
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = uuid.UUID(admin.get("org"))

    where = ["im.organization_id = :org_id"]
    params: dict = {"org_id": org_id, "limit": limit, "offset": offset}

    if search:
        search_like = f"%{search}%"
        where.append("(im.sender_wa_id ILIKE :search_like OR u.full_name ILIKE :search_like)")
        params["search_like"] = search_like

    query_str = f"""
        SELECT sender_wa_id, body_text, assistant_reply, message_type, processing_status,
               error_code, last_activity, message_count,
               user_id, user_email, user_name, user_role, user_status
        FROM (
            SELECT
                im.sender_wa_id, im.body_text, im.assistant_reply, im.message_type,
                im.processing_status, im.error_code,
                GREATEST(im.received_at, COALESCE(im.processed_at, im.received_at)) AS last_activity,
                COUNT(*) OVER (PARTITION BY im.sender_wa_id) AS message_count,
                ROW_NUMBER() OVER (PARTITION BY im.sender_wa_id ORDER BY im.received_at DESC) AS rn,
                u.id AS user_id, u.email AS user_email, u.full_name AS user_name,
                u.role AS user_role, u.status AS user_status
            FROM inbound_messages im
            LEFT JOIN users u ON u.whatsapp_number = im.sender_wa_id
            WHERE {" AND ".join(where)}
        ) sub
        WHERE rn = 1
        ORDER BY last_activity DESC
        LIMIT :limit OFFSET :offset
    """

    count_str = f"""
        SELECT COUNT(DISTINCT im.sender_wa_id)
        FROM inbound_messages im
        LEFT JOIN users u ON u.whatsapp_number = im.sender_wa_id
        WHERE {" AND ".join(where)}
    """

    rows = (await conn.execute(sa.text(query_str), params)).mappings().all()
    total = (
        await conn.execute(
            sa.text(count_str), {k: v for k, v in params.items() if k not in ("limit", "offset")}
        )
    ).scalar_one()

    items = []
    for r in rows:
        member = None
        if r.user_id:
            member = UserMinResponse(
                id=r.user_id,
                email=r.user_email,
                full_name=r.user_name,
                role=r.user_role,
                status=r.user_status,
                whatsapp_number=r.sender_wa_id,
            )

        last_direction = "outbound" if r.assistant_reply else "inbound"
        preview = r.assistant_reply if r.assistant_reply else (r.body_text or "")

        items.append(
            ConversationSummary(
                sender_wa_id=r.sender_wa_id,
                member=member,
                last_message_preview=preview,
                last_direction=last_direction,
                last_activity=r.last_activity,
                message_count=r.message_count,
                processing_status=r.processing_status,
                error_code=r.error_code,
            )
        )

    return ConversationListResponse(items=items, total=total)


@router.get(
    "/whatsapp/conversations/{conversation_id}/messages", response_model=list[MessageSummary]
)
async def list_conversation_messages(
    conversation_id: str,  # conversation_id is sender_wa_id
    limit: int = Query(default=100, ge=1, le=500),
    admin: dict = Depends(require_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    org_id = uuid.UUID(admin.get("org"))

    # Query all inbound messages and outbound assistant replies for this wa_id
    inbound_part = """
        SELECT 
            im.id, im.correlation_id, 'inbound' AS direction, im.sender_wa_id, im.message_type,
            COALESCE(im.body_text, '') AS body, im.processing_status, im.error_code, im.received_at AS timestamp,
            im.project_id, p.name AS project_name, im.site_id, s.name AS site_name,
            u.id AS user_id, u.email AS user_email, u.full_name AS user_name, u.role AS user_role, u.status AS user_status
        FROM inbound_messages im
        LEFT JOIN users u ON u.whatsapp_number = im.sender_wa_id
        LEFT JOIN projects p ON p.id = im.project_id
        LEFT JOIN sites s ON s.id = im.site_id
        WHERE im.organization_id = :org_id AND im.sender_wa_id = :wa_id
    """

    outbound_part = """
        SELECT 
            im.id, im.correlation_id, 'outbound' AS direction, im.sender_wa_id, 'text' AS message_type,
            COALESCE(im.assistant_reply, '') AS body, 'completed' AS processing_status, NULL AS error_code, COALESCE(im.processed_at, im.received_at) AS timestamp,
            im.project_id, p.name AS project_name, im.site_id, s.name AS site_name,
            u.id AS user_id, u.email AS user_email, u.full_name AS user_name, u.role AS user_role, u.status AS user_status
        FROM inbound_messages im
        LEFT JOIN users u ON u.whatsapp_number = im.sender_wa_id
        LEFT JOIN projects p ON p.id = im.project_id
        LEFT JOIN sites s ON s.id = im.site_id
        WHERE im.organization_id = :org_id AND im.sender_wa_id = :wa_id AND im.assistant_reply IS NOT NULL
    """

    query_str = f"""
        SELECT * FROM ({inbound_part} UNION ALL {outbound_part}) q
        ORDER BY timestamp ASC
        LIMIT :limit
    """

    rows = (
        (
            await conn.execute(
                sa.text(query_str), {"org_id": org_id, "wa_id": conversation_id, "limit": limit}
            )
        )
        .mappings()
        .all()
    )

    items = []
    for r in rows:
        member = None
        if r.user_id:
            member = UserMinResponse(
                id=r.user_id,
                email=r.user_email,
                full_name=r.user_name,
                role=r.user_role,
                status=r.user_status,
                whatsapp_number=r.sender_wa_id,
            )

        items.append(
            MessageSummary(
                id=r.id,
                correlation_id=r.correlation_id,
                direction=r.direction,
                sender_wa_id=r.sender_wa_id,
                message_type=r.message_type,
                body=r.body,
                processing_status=r.processing_status,
                error_code=r.error_code,
                timestamp=r.timestamp,
                member=member,
                project_id=r.project_id,
                project_name=r.project_name,
                site_id=r.site_id,
                site_name=r.site_name,
            )
        )

    return items
