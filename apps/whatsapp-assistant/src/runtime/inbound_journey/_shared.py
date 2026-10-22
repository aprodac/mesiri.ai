"""Constants shared by 2+ of this package's submodules.

Kept separate from any one submodule so neither has to import the other just
to reach a bare constant -- see the package's __init__.py for the re-export
surface these feed into.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("mesiri.inbound_journey")

# Who may create a project or site over WhatsApp, and the words when not
# (ARCH-06: kept from the retired process.py for runtime/agent/query_entry.py).
_PROJECT_CREATE_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER"})
_PROJECT_CREATE_DENIED_REPLY = "⛔ Only an admin or project manager can create a project."
_SITE_CREATE_DENIED_REPLY = "⛔ Only an admin or project manager can create a site."


async def _send_with_one_retry(send, *, what: str, correlation_id: str) -> bool:  # type: ignore[no-untyped-def]
    """Run ``send`` (a document fetch + send); on a failure try once more
    before giving up, and log every failure with its cause so the team's
    friction/alert path sees it (request 57, A5). True when it went."""
    for attempt in (1, 2):
        try:
            await send()
            return True
        except Exception:  # noqa: BLE001 -- the text reply already went; this must not fail the journey
            _log.warning(
                "%s_send_failed correlation_id=%s attempt=%s",
                what,
                correlation_id,
                attempt,
                exc_info=True,
            )
    return False
