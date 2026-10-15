"""How a login or signup code reaches the phone (SS-06, WEB-12).

Chosen by the server setting `MESIRI_LOGIN_CODE_SENDER`:

    whatsapp (default)  the Meta authentication template `mesiri_login_code`,
                        sent only once its name is also in
                        `WHATSAPP_APPROVED_TEMPLATES` (WA-12). Until Meta
                        approves it, code login and web signup answer
                        "not available yet" instead of sending something
                        Meta will reject.
    dev                 nothing is sent: the code is logged and returned to
                        the browser, so signup and code login can be tried
                        without Meta. Never set this on a server real people
                        use: anyone could log in as any number.
    off                 code login and web signup are unavailable.
"""

from __future__ import annotations

import logging
import os

import httpx

from channel.whatsapp.outbound import WhatsAppSender
from channel.whatsapp.templates import LOGIN_CODE, approved_template_names

SENDER_SETTING = "MESIRI_LOGIN_CODE_SENDER"

_log = logging.getLogger("mesiri.auth")


class CodeLoginUnavailable(Exception):  # noqa: N818 - a state, not a fault
    """No way to get a code to a phone on this server right now."""


class WhatsAppLoginCodeSender:
    echoes_code = False

    def __init__(self, settings) -> None:  # runtime.dependencies.Settings
        self._settings = settings

    async def send(self, phone: str, code: str) -> bool:
        async with httpx.AsyncClient(timeout=15.0) as client:
            sender = WhatsAppSender(
                client=client,
                access_token=self._settings.access_token,
                phone_number_id=self._settings.phone_number_id,
                api_version=self._settings.api_version,
                graph_base_url=self._settings.graph_base_url,
            )
            return await sender.send_template(
                phone,
                name=LOGIN_CODE.name,
                language=LOGIN_CODE.language,
                body_params=(code,),
                button_url_param=code,
            )


class DevLoginCodeSender:
    """Sends nothing; the route hands the code back to the browser."""

    echoes_code = True

    async def send(self, phone: str, code: str) -> bool:
        _log.warning(
            "login_code.dev_sender phone=%s code=%s -- %s=dev: codes are shown, not sent",
            phone,
            code,
            SENDER_SETTING,
        )
        return True


def build_login_code_sender() -> WhatsAppLoginCodeSender | DevLoginCodeSender:
    """The sender this server is set up for; raises CodeLoginUnavailable."""
    mode = (os.environ.get(SENDER_SETTING) or "whatsapp").strip().lower()
    if mode == "dev":
        return DevLoginCodeSender()
    if mode != "whatsapp":
        raise CodeLoginUnavailable(f"{SENDER_SETTING}={mode}")

    from runtime.dependencies import Settings as WhatsAppSettings

    try:
        settings = WhatsAppSettings()  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001 - missing WhatsApp config = unavailable
        raise CodeLoginUnavailable("WhatsApp is not configured") from exc
    if LOGIN_CODE.name not in approved_template_names(settings.approved_templates):
        raise CodeLoginUnavailable(f"template {LOGIN_CODE.name} not approved")
    return WhatsAppLoginCodeSender(settings)
