"""The Welcome card: shown to someone just added to a project.

"Hi <first>. You're the <role>." who added them, three example messages for
their role (what to send), and the first action. Examples are plain strings
here; the Malayalam-English mix is how people on site actually write.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import clip, render_html

#: Three things a person in this role sends, per role (default: site engineer).
EXAMPLES: dict[str, tuple[str, ...]] = {
    "SITE_ENGINEER": (
        "Ennu 12 workers, plastering 2nd floor",
        "Slab shuttering 80% aayi",
        "Cement ethra bags baki?",
    ),
    "SUPERVISOR": (
        "10 mason, 15 helper ennu",
        "Bar bending kazhinju, 3rd floor",
        "Steel 2 ton vannu",
    ),
    "PROJECT_MANAGER": (
        "Ennathe report ayakku",
        "Cement stock ethra?",
        "Evide ethra workers undu?",
    ),
}
_DEFAULT_ROLE = "SITE_ENGINEER"

ROLE_NAMES = {
    "SITE_ENGINEER": "site engineer",
    "SUPERVISOR": "supervisor",
    "PROJECT_MANAGER": "project manager",
    "ADMIN": "admin",
}
FOOTER = "Send today's first update, or a voice note"

_BODY = """
<div class="hello">Hi {{ first }}.</div>
<div class="hello sub2">You're the {{ role }}.</div>
<div class="by sub">Added by {{ added_by }}{% if company %} &middot; {{ company }}{% endif %}</div>
<div class="label eg">Send things like</div>
{% for line in examples %}
<div class="ex"><span class="n">{{ loop.index }}</span><span class="text">{{ line }}</span></div>
{% endfor %}
"""

_STYLE = """
.hello { font-size: 40px; font-weight: 700; line-height: 1.1; letter-spacing: -0.02em;
  overflow-wrap: anywhere; }
.hello.sub2 { color: #6B7280; margin-top: 4px; font-size: 30px; }
.by { margin-top: 14px; }
.eg { margin: 26px 0 6px; }
.ex { display: flex; gap: 14px; padding: 13px 0; border-top: 1px solid #E5E7EB; align-items: baseline; }
.ex .n { font-size: 12px; font-weight: 700; color: #6B7280; width: 14px; }
"""


@dataclass(frozen=True, slots=True)
class WelcomeCard:
    first: str
    role: str
    added_by: str
    company: str
    examples: tuple[str, ...]


def build_welcome_card(
    *, first: str, role_code: str, added_by: str, company: str
) -> WelcomeCard:
    code = str(role_code or "").upper()
    return WelcomeCard(
        first=clip(first, 20),
        role=ROLE_NAMES.get(code, code.replace("_", " ").lower() or "team member"),
        added_by=clip(added_by, 26) or "your admin",
        company=clip(company, 28),
        examples=EXAMPLES.get(code, EXAMPLES[_DEFAULT_ROLE]),
    )


def welcome_html(card: WelcomeCard) -> str:
    return render_html(
        _BODY,
        tag="Welcome",
        where=clip(card.company, 30),
        footer=FOOTER,
        style=_STYLE,
        first=card.first,
        role=card.role,
        added_by=card.added_by,
        company=card.company,
        examples=card.examples,
    )
