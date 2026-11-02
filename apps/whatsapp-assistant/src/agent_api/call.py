"""WA-118: what the assistant says on a WhatsApp call.

The call spike sends what Sarvam heard and speaks what comes back. A caller goes through the
checks a message goes through (a known number, an active company, the trial cap, a company on
the API agent). Entries go to the chat as the usual Save card, so a tap saves them, never speech.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from mesiri.domains.organizations import settings as settings_spec
from mesiri.infrastructure.postgres.tenant import bind_tenant

from .whatsapp import MODE, ApiWhatsApp

_log = logging.getLogger(__name__)

NOT_KNOWN = "ഈ നമ്പർ മെസിരിയിൽ ഇല്ല."
NOT_ON_CALLS = "ഇപ്പോൾ കോളിൽ മറുപടി പറയാൻ പറ്റില്ല. വാട്സ്ആപ്പിൽ മെസ്സേജ് അയക്കൂ."
NOT_NOW = "ഇപ്പോൾ നോക്കാൻ പറ്റിയില്ല. ഒന്നുകൂടി പറയൂ."


class CallAnswers:
    def __init__(self, *, provider: Any, database: Any, redis: Any, sessions: Any, actor_reader: Any,
                 org_settings: Any, usage_guard: Any, send: Any = None, send_document: Any = None,
                 message_logger: Any = None) -> None:
        self._provider = provider
        self._database = database
        self._redis = redis
        self._sessions = sessions
        self._actors = actor_reader
        self._org_settings = org_settings
        self._usage_guard = usage_guard
        self._send = send
        self._send_document = send_document
        self._message_logger = message_logger
        self._api: ApiWhatsApp | None = None

    def _agent(self) -> ApiWhatsApp:
        """Built on the first call: nothing is loaded until someone is on the allow-list and calls."""
        if self._api is None:
            self._api = ApiWhatsApp(provider=self._provider, database=self._database, redis=self._redis,
                                    send=self._send, transcribe=None, message_logger=self._message_logger,
                                    sessions=self._sessions, send_document=self._send_document)
        return self._api

    async def answer(self, wa_id: str, text: str) -> str:
        started = time.monotonic()
        try:
            ctx = await self._actors.resolve_by_whatsapp_id(wa_id)
            if ctx is None:
                return NOT_KNOWN
            bind_tenant(ctx.organization_id)
            if not ctx.org_active or not await self._on_calls(ctx):
                return NOT_ON_CALLS
            words = await self._agent().on_call(text, ctx, str(uuid.uuid4()), wa_id)
        except Exception:  # noqa: BLE001 -- the caller hears a sentence, never silence
            _log.exception("agent_api.call_failed")
            return NOT_NOW
        _log.info("agent_api.call_answer seconds=%.2f", time.monotonic() - started)
        return words or NOT_NOW

    async def _on_calls(self, ctx: Any) -> bool:
        if (await self._usage_guard.check(ctx.organization_id)).over_cap:
            return False
        stored = await self._org_settings.get(
            organization_id=str(ctx.organization_id), key=settings_spec.ASSISTANT_MODE)
        return settings_spec.assistant_mode(stored) == MODE
