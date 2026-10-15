"""Tell the Mesiri team something in their WhatsApp group (SS-14).

Posts through the teammate listener (teammate/README.md), the same `POST
/send` its `inbox.py post` uses: only into the chat labelled `team` for this
project, rate-limited by the listener. Needs `TEAMMATE_TOKEN` (and
optionally `TEAMMATE_API`, `TEAMMATE_PROJECT`) in the app's environment;
without a token it logs and does nothing, so a missing setup never breaks a
customer's conversation. Best-effort throughout: the record the team works
from is the control panel, this is only the nudge.
"""

from __future__ import annotations

import base64
import logging
import os

import httpx

_log = logging.getLogger("mesiri.team_notify")

_DEFAULT_API = "https://api.whatsapp.mesiri.ai/teammate"
_TIMEOUT_SECONDS = 15.0
_IMAGE_MAX_BYTES = 5 * 1024 * 1024  # the listener's own limit


class TeamNotifier:
    def __init__(
        self,
        *,
        token: str | None = None,
        api: str | None = None,
        project: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token if token is not None else os.environ.get("TEAMMATE_TOKEN")
        self._api = (api or os.environ.get("TEAMMATE_API") or _DEFAULT_API).rstrip("/")
        self._project = project or os.environ.get("TEAMMATE_PROJECT") or "mesiri"
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def post(
        self, text: str, *, images: list[tuple[bytes, str | None]] | None = None
    ) -> bool:
        """Post `text`, then each (bytes, caption) image. True if the text went."""
        if not self._token:
            _log.info("team_notify.skipped reason=no_token")
            return False
        try:
            async with self._session() as client:
                chat = await self._team_chat(client)
                if chat is None:
                    return False
                await self._send(client, {"chat": chat, "project": self._project, "text": text})
                for data, caption in images or []:
                    if len(data) > _IMAGE_MAX_BYTES:
                        continue
                    await self._send(
                        client,
                        {
                            "chat": chat,
                            "project": self._project,
                            "image_base64": base64.b64encode(data).decode(),
                            "caption": caption,
                        },
                    )
            return True
        except Exception:  # noqa: BLE001
            _log.exception("team_notify.failed")
            return False

    def _session(self) -> httpx.AsyncClient:
        if self._client is not None:
            return _Borrowed(self._client)  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _team_chat(self, client: httpx.AsyncClient) -> str | None:
        response = await client.get(
            f"{self._api}/chats", params={"project": self._project}, headers=self._headers()
        )
        response.raise_for_status()
        teams = [
            c
            for c in response.json().get("chats", [])
            if c.get("role") == "team" and c.get("project") in (None, self._project)
        ]
        if len(teams) != 1:
            _log.warning("team_notify.no_single_team_chat count=%d", len(teams))
            return None
        return teams[0]["jid"]

    async def _send(self, client: httpx.AsyncClient, body: dict) -> None:
        response = await client.post(f"{self._api}/send", json=body, headers=self._headers())
        response.raise_for_status()


class _Borrowed:
    """Use a caller's client in `async with` without closing it."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *exc: object) -> None:
        return None
