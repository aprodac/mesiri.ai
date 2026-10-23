"""Send unhandled errors to Sentry, so the team hears about them first (INF-07).

Off unless ``SENTRY_DSN`` is set in /opt/mesiri/.env: with no DSN this is a
no-op and nothing leaves the server. The app (runtime/lifecycle.py) and the
worker (worker.py) each call ``init_error_reporting`` once at startup.

What reaches Sentry is kept to what is needed to fix a bug. Customers'
WhatsApp messages, photos and phone numbers are not:

- no request bodies (the webhook body *is* the customer's message),
- no local variables in stack frames (they hold message text and numbers),
- no IPs, cookies or auth headers (``send_default_pii=False``),
- any run of 10+ digits left in a message or breadcrumb is masked, since
  log lines name senders by number (``_scrub``).

Errors only: no performance tracing, so no per-request cost or volume.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

_log = logging.getLogger("mesiri.error_reporting")

# A WhatsApp number in any of the forms the logs use: 919876543210,
# +91 98765 43210, 98765-43210. Shorter numbers (ids, counts) are left alone.
_PHONE = re.compile(r"\+?\d[\d \-]{8,}\d")
_MASK = "[number]"


def _mask(text: str) -> str:
    return _PHONE.sub(
        lambda m: _MASK if sum(c.isdigit() for c in m.group()) >= 10 else m.group(), text
    )


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _mask(value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _before_send(event: dict, _hint: dict) -> dict:
    for key in ("message", "logentry", "exception", "breadcrumbs", "extra", "request"):
        if key in event:
            event[key] = _scrub(event[key])
    return event


def _before_breadcrumb(crumb: dict, _hint: dict) -> dict:
    return _scrub(crumb)


def init_error_reporting(service: str) -> bool:
    """Start Sentry for this process. True if it is on.

    ``service`` ("app" or "worker") is attached to every event so the two
    processes can be told apart. Never raises: error reporting must not be
    the reason a process fails to start.
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        _log.info("error_reporting.off reason=no_dsn")
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        from runtime.build_info import build_sha

        sentry_sdk.init(
            dsn=dsn,
            environment=os.environ.get("MESIRI_ENVIRONMENT") or "development",
            release=build_sha(),
            server_name=service,
            send_default_pii=False,
            include_local_variables=False,
            max_request_body_size="never",
            traces_sample_rate=0.0,
            before_send=_before_send,
            before_breadcrumb=_before_breadcrumb,
            # logger.error / logger.exception become Sentry events; info and
            # warning lines only ride along as breadcrumbs.
            integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        )
        sentry_sdk.set_tag("service", service)
    except Exception:  # noqa: BLE001
        _log.exception("error_reporting.init_failed")
        return False
    _log.info("error_reporting.on service=%s", service)
    return True
