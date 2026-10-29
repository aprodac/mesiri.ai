"""Meta Cloud API Groups API: create a group, its invite link, join requests (WA-87).

Transport only, like outbound.py beside it: no Mesiri logic, never raises,
returns None/False on any failure (logged). Messages INTO a group go through
WhatsAppSender with a ``group:<id>`` target; this module only manages groups.

Endpoints (Meta's Groups API reference; not yet tried against the live API --
the WA-87 spike confirms them, see docs/execution/WHATSAPP_GROUPS_PLAN.md):

- ``POST /{phone-number-id}/groups`` with ``subject`` (max 128 characters),
  ``description`` (max 2048) and ``join_approval_mode``. Meta answers at once
  and sends the group id and invite link later, on the ``group_lifecycle_update``
  webhook (runtime/group_chat.py's ``handle_event``).
- ``GET /{group-id}/invite_link``
- ``POST`` / ``DELETE /{group-id}/join_requests`` approve / reject requests.

There is no call that adds a person: everyone joins through the invite link.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SUBJECT_MAX_CHARS = 128
DESCRIPTION_MAX_CHARS = 2048
APPROVAL_REQUIRED = "approval_required"


class WhatsAppGroupsClient:
    """Manage WhatsApp groups owned by Mesiri's business number."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        access_token: str,
        phone_number_id: str,
        api_version: str = "v21.0",
        graph_base_url: str = "https://graph.facebook.com",
    ) -> None:
        self._client = client
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._base = f"{graph_base_url.rstrip('/')}/{api_version}"

    @property
    def enabled(self) -> bool:
        return bool(self._access_token and self._phone_number_id)

    async def _call(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self.enabled:
            logger.warning("whatsapp_groups.disabled (missing phone_number_id/access_token)")
            return None
        try:
            resp = await self._client.request(
                method,
                f"{self._base}/{path}",
                json=json,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        except httpx.HTTPError as exc:
            logger.error("whatsapp_groups.%s %s failed: %s", method, path, exc)
            return None
        if resp.status_code >= 400:
            logger.error("whatsapp_groups.%s %s rejected (%s): %s", method, path, resp.status_code, resp.text[:300])
            return None
        try:
            body = resp.json()
        except ValueError:
            body = {}
        return body if isinstance(body, dict) else {}

    async def create_group(
        self, subject: str, *, description: str | None = None, join_approval_mode: str = APPROVAL_REQUIRED
    ) -> dict[str, Any] | None:
        """Meta's answer to the create call (it may carry a request id or the
        group id), or None when Meta refused it."""
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "subject": subject[:SUBJECT_MAX_CHARS],
            "join_approval_mode": join_approval_mode,
        }
        if description:
            payload["description"] = description[:DESCRIPTION_MAX_CHARS]
        body = await self._call("POST", f"{self._phone_number_id}/groups", json=payload)
        if body is not None:
            logger.info("whatsapp_groups.create_accepted response=%s", str(body)[:300])
        return body

    async def invite_link(self, group_id: str) -> str | None:
        body = await self._call("GET", f"{group_id}/invite_link")
        link = (body or {}).get("invite_link")
        return str(link) if link else None

    async def approve_join_requests(self, group_id: str, join_request_ids: list[str]) -> bool:
        return await self._join_requests("POST", group_id, join_request_ids)

    async def reject_join_requests(self, group_id: str, join_request_ids: list[str]) -> bool:
        return await self._join_requests("DELETE", group_id, join_request_ids)

    async def _join_requests(self, method: str, group_id: str, ids: list[str]) -> bool:
        if not ids:
            return False
        body = await self._call(
            method,
            f"{group_id}/join_requests",
            json={"messaging_product": "whatsapp", "join_requests": [str(i) for i in ids]},
        )
        return body is not None
