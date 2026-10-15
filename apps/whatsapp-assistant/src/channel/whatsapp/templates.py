"""Registry of Meta-approved WhatsApp message templates (WA-12).

Outside the 24-hour customer-service window Meta only delivers a message
built from a template that was submitted and approved in WhatsApp Manager.
Each template Mesiri can send is declared here, with exactly the name,
language and shape that was submitted -- Meta matches on name + language
code, and a mismatch is rejected.

A declared template is only actually sent once it is also listed in
`WHATSAPP_APPROVED_TEMPLATES` (comma-separated names). Declaring it here
is "the code can send it"; listing it there is "Meta has approved it".
Until both hold, a notification that needs it is skipped with a reason
(`template_not_approved:<name>`), exactly as before WA-12 -- never sent
to Meta only to be rejected.

The text to submit for each template lives in docs/ops/whatsapp-templates.md.

A notification row asks for a template through its payload:
    {"template": {"name": "<name>", "body_params": ["...", ...]}}
plus, for a template with a document header, the existing
`document_object_key` (the same PDF the in-window send attaches).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Meta's limits for a body text parameter: no newlines or tabs, no more
# than four consecutive spaces, and the whole body at most 1024 chars.
# Cleaned here rather than trusted from the caller -- a bad parameter
# fails the whole send, asynchronously, with nothing shown to the user.
_PARAM_MAX_CHARS = 200
_WHITESPACE_RUN = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    name: str
    language: str
    category: str  # UTILITY / AUTHENTICATION / MARKETING, as submitted to Meta
    body_param_count: int
    header: str | None = None  # "document" or None


#: The project DPR (BE-16) for an owner/PM who has not messaged in 24 h.
#: Header: the PDF. Body (submitted text, docs/ops/whatsapp-templates.md):
#:   "Daily progress report for {{1}}, {{2}}. {{3}} The PDF is attached;
#:    reply here if anything needs fixing."
DPR_DELIVERY = TemplateSpec(
    name="mesiri_dpr_delivery",
    language="en",
    category="UTILITY",
    body_param_count=3,
    header="document",
)

#: A one-time login / signup code (SS-06, WEB-12). An AUTHENTICATION
#: template: Meta fixes the wording, "{{1}} is your verification code.", plus
#: the security line, a 10-minute expiry footer and a "Copy code" button. The
#: code is sent twice, as the body param and as the button's url param.
LOGIN_CODE = TemplateSpec(
    name="mesiri_login_code",
    language="en",
    category="AUTHENTICATION",
    body_param_count=1,
)

TEMPLATES: dict[str, TemplateSpec] = {spec.name: spec for spec in (DPR_DELIVERY, LOGIN_CODE)}


def approved_template_names(raw: str | None) -> frozenset[str]:
    """Parses the `WHATSAPP_APPROVED_TEMPLATES` setting."""
    return frozenset(name.strip() for name in (raw or "").split(",") if name.strip())


def clean_param(value: Any) -> str:
    """One body parameter in a form Meta accepts: single-line, collapsed
    whitespace, capped, never empty (Meta rejects an empty parameter)."""
    text = _WHITESPACE_RUN.sub(" ", str(value if value is not None else "")).strip()
    if len(text) > _PARAM_MAX_CHARS:
        text = text[: _PARAM_MAX_CHARS - 1].rstrip() + "…"
    return text or "-"


@dataclass(frozen=True, slots=True)
class TemplateChoice:
    """What the send policy decided for a row outside the session window:
    a spec to send with these params, or a skip reason."""

    spec: TemplateSpec | None
    body_params: tuple[str, ...] = ()
    skip_reason: str | None = None


def choose_template(payload: dict[str, Any] | None, approved: frozenset[str]) -> TemplateChoice:
    """Which template (if any) a notification can go out as."""
    request = (payload or {}).get("template")
    if not isinstance(request, dict) or not request.get("name"):
        return TemplateChoice(None, skip_reason="outside_whatsapp_session_window_needs_template")

    name = str(request["name"])
    spec = TEMPLATES.get(name)
    if spec is None:
        return TemplateChoice(None, skip_reason=f"unknown_template:{name}")
    if name not in approved:
        return TemplateChoice(None, skip_reason=f"template_not_approved:{name}")

    params = tuple(clean_param(p) for p in (request.get("body_params") or []))
    if len(params) != spec.body_param_count:
        return TemplateChoice(None, skip_reason=f"template_params_mismatch:{name}")
    return TemplateChoice(spec, body_params=params)
