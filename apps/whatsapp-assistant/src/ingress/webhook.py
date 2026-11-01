"""Expose Meta WhatsApp webhook HTTP endpoints."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ingress.calls_forward import forward_calls, has_calls_change
from ingress.receiver import WhatsAppReceiver
from ingress.verification import (
    WebhookVerificationError,
    verify_request_signature,
    verify_subscription_challenge,
)
from runtime.dependencies import Settings, get_container, get_receiver, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp-webhook"])


@router.get("")
async def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Handle Meta webhook subscription verification."""
    try:
        challenge = verify_subscription_challenge(
            hub_mode=hub_mode,
            hub_verify_token=hub_verify_token,
            hub_challenge=hub_challenge,
            expected_verify_token=settings.verify_token,
        )
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    logger.info("WhatsApp webhook subscription verified")
    return Response(content=challenge, media_type="text/plain")


@router.post("")
async def receive_webhook(
    request: Request,
    receiver: WhatsAppReceiver = Depends(get_receiver),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Accept verified Meta webhook payloads and schedule ingress processing."""
    payload_bytes = await request.body()

    try:
        verify_request_signature(
            payload=payload_bytes,
            signature_header=request.headers.get("X-Hub-Signature-256"),
            app_secret=settings.app_secret,
        )
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError as exc:
        logger.warning("Rejected webhook with invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if payload.get("object") != "whatsapp_business_account":
        logger.info("Ignored webhook for unsupported object=%s", payload.get("object"))
        return Response(status_code=200)

    if settings.calls_forward_url and has_calls_change(payload):
        forward_calls(
            get_container(request).http_client,
            settings.calls_forward_url,
            payload_bytes,
            request.headers["X-Hub-Signature-256"],
        )

    await receiver.handle_payload(payload)
    return Response(status_code=200)
