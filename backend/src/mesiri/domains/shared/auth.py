"""Shared FastAPI auth dependencies for domain routers."""

from __future__ import annotations

import jwt
from fastapi import Depends, Header, HTTPException

from ..identity.auth_service import ALGORITHM, SECRET_KEY
from . import clock


async def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    clock.bind_from_token(payload)  # SS-74a: a sample company's own date, else the real one
    return payload


async def require_admin(payload: dict = Depends(get_current_user)) -> dict:
    role = (payload.get("role") or "").upper()
    if role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


async def require_platform_admin(payload: dict = Depends(get_current_user)) -> dict:
    """Platform-wide operator, distinct from a tenant's own org ADMIN.

    A platform admin is a user with role=ADMIN and no organization_id — the
    JWT encodes an empty `org` claim in that case (see auth/router.py's
    _create_token). Tenant org admins must not be able to provision other
    tenants or read another organization's WhatsApp message content.
    """
    role = (payload.get("role") or "").upper()
    org = payload.get("org")
    if role != "ADMIN" or org:
        raise HTTPException(status_code=403, detail="Platform admin access required")
    return payload
