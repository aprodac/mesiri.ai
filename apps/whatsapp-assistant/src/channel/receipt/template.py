"""HTML/CSS re-implementation of the user-supplied RecordCard React design.

Two visual treatments driven by ``data.template_variant`` -- data.py decides
what goes in each field and which variant applies, this file only decides how
the card looks:

- ``"record"`` (default): the original card -- brand top-left, green "Saved"
  pill top-right. Every money/material/labour/site-issue/account/project/site
  type uses this, each with its own ``accent``/``badge_icon`` (data.py) so
  categories are distinguishable by color+icon without a different layout.
- ``"activity"``: site activity create/progress/correction/undo. Same base
  card, but the header leads with the category's badge icon in a colored
  circle (a "site log entry", not a transaction receipt) instead of the brand
  wordmark, a correction renders its old->new change as a struck-through diff
  chip (``data.correction``) instead of a plain field, and an undo renders a
  muted card with a red "UNDONE" ribbon in place of the green "Saved" pill.

Icons are simplified stroke-based SVGs (not a lucide-react port) since
fidelity of the receipt's *data* matters far more than pixel-identical icon
glyphs for a WhatsApp image; swap in real lucide SVG paths later if that gap
ever matters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .data import ReceiptData

if TYPE_CHECKING:
    from jinja2 import Template

_INK = "#1D1D1F"
_SUB = "#86868B"
_LINE = "#E8E8ED"
_WHATSAPP = "#25D366"

# Simplified stroke-based icon glyphs, 24x24 viewBox, stroke=currentColor.
_ICONS: dict[str, str] = {
    "building": '<rect x="4" y="3" width="16" height="18" rx="1"/><line x1="8" y1="7" x2="8" y2="7"/><line x1="12" y1="7" x2="12" y2="7"/><line x1="16" y1="7" x2="16" y2="7"/><line x1="8" y1="11" x2="8" y2="11"/><line x1="12" y1="11" x2="12" y2="11"/><line x1="16" y1="11" x2="16" y2="11"/><line x1="8" y1="15" x2="8" y2="15"/><line x1="16" y1="15" x2="16" y2="15"/><path d="M10 21v-4h4v4"/>',
    "pin": '<path d="M12 21s7-6.1 7-11.5A7 7 0 0 0 5 9.5C5 14.9 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.3"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>',
    "store": '<path d="M4 8l1-4h14l1 4"/><path d="M4 8a2 2 0 0 0 4 0 2 2 0 0 0 4 0 2 2 0 0 0 4 0 2 2 0 0 0 4 0"/><path d="M5 8v11h14V8"/><path d="M9 19v-6h6v6"/>',
    "user": '<circle cx="12" cy="8" r="3.6"/><path d="M5 20c0-4 3-6.5 7-6.5s7 2.5 7 6.5"/>',
    # A crowd, distinct from "user" (one person, used for "Reported by") --
    # labour attendance needs both on the same card and they must not look
    # like the same field.
    "users": '<circle cx="9" cy="8" r="3.2"/><path d="M2.5 19.5c0-3.6 2.9-5.8 6.5-5.8s6.5 2.2 6.5 5.8"/><path d="M16.5 5.2a3.2 3.2 0 0 1 0 6.1"/><path d="M18 13.9c2.1.5 3.5 2.2 3.5 4.4"/>',
    "whatsapp": '<path d="M12 3a9 9 0 0 0-7.8 13.5L3 21l4.7-1.2A9 9 0 1 0 12 3z"/><path d="M8.5 8.7c.2-.6.5-.6.8-.6h.6c.2 0 .4 0 .6.5s.7 1.7.7 1.8-.1.3-.2.5-.3.4-.5.6-.3.4-.1.7c.2.3.9 1.4 1.9 2.2 1.3 1.1 2.2 1.3 2.5 1.5.3.1.5.1.7-.1s.8-.9 1-1.2.4-.2.7-.1 1.7.8 2 .9.5.2.5.4c0 .2 0 1-.4 1.4-.4.5-1.8 1.3-3.2.7-1.8-.7-4.2-2.3-5.9-4.9-.6-1-.3-1.5.1-1.9z"/>',
    "hammer": '<path d="M14.5 3.5l6 6-3 3-6-6 3-3z"/><path d="M13 9L4 18l2 2 9-9"/><path d="M3 21l3-3"/>',
    "check": '<path d="M4 12l6 6L20 6"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="8" y1="3" x2="8" y2="7"/><line x1="16" y1="3" x2="16" y2="7"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "hash": '<line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="9" y1="4" x2="7" y2="20"/><line x1="17" y1="4" x2="15" y2="20"/>',
    "barchart": '<line x1="6" y1="20" x2="6" y2="13"/><line x1="12" y1="20" x2="12" y2="8"/><line x1="18" y1="20" x2="18" y2="4"/>',
    # Reversal/undo badge -- a counter-clockwise arrow, distinct from "check"
    # so an undone record never looks like a freshly-saved one at a glance.
    "undo": '<path d="M3 11a8 8 0 1 1 2.6 6.2"/><path d="M3 4v7h7"/>',
}


def _icon_svg(name: str, *, size: int = 14, color: str = _INK) -> str:
    path = _ICONS.get(name, "")
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{path}</svg>'
    )


_CARD_TEMPLATE_SRC = (
    """
<!doctype html>
<html><head><meta charset="utf-8"><style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #EEEEF0; padding: 16px; font-family: -apple-system, BlinkMacSystemFont,
    "SF Pro Display", "SF Pro Text", Inter, system-ui, sans-serif; }
  .card { max-width: 620px; margin: 0 auto; background: #FFFFFF; border-radius: 18px;
    padding: 16px 22px; box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.05);
    border: 1px solid {{ line }}; }
  .card.activity { border-left: 4px solid {{ accent }}; }
  .card.undone { background: #F4F4F5; }
  .header { display: flex; align-items: center; justify-content: space-between; }
  .brand { display: flex; align-items: center; gap: 7px; font-size: 13.5px; font-weight: 700;
    letter-spacing: 0.12em; color: {{ ink }}; }
  .saved-pill { display: flex; align-items: center; gap: 6px; border-radius: 999px;
    background: #EAF8EE; color: {{ accent }}; font-size: 11.5px; font-weight: 600;
    padding: 5px 12px 5px 8px; }
  .saved-dot { width: 14px; height: 14px; border-radius: 50%; background: {{ accent }};
    display: flex; align-items: center; justify-content: center; }
  .ribbon-undone { display: flex; align-items: center; gap: 6px; border-radius: 999px;
    background: {{ accent }}; color: #fff; font-size: 11.5px; font-weight: 700;
    letter-spacing: 0.04em; padding: 5px 12px; }
  .headline { display: flex; margin-top: 12px; gap: 16px; }
  .headline-main { flex: 1; }
  .headline-category-row { display: flex; align-items: center; gap: 6px; }
  .badge-circle { display: flex; align-items: center; justify-content: center; width: 20px; height: 20px;
    border-radius: 50%; background: {{ accent }}22; flex-shrink: 0; }
  .headline-category { font-size: 12px; font-weight: 600; letter-spacing: 0.05em; color: {{ accent }}; }
  .headline-value { margin-top: 3px; font-size: 36px; font-weight: 700; line-height: 1;
    letter-spacing: -0.03em; color: {{ ink }}; }
  .headline-subtitle { margin-top: 4px; font-size: 14px; color: {{ sub }}; }
  .location { width: 240px; flex-shrink: 0; }
  .info-row { display: flex; align-items: center; gap: 10px; padding: 7px 0; font-size: 14.5px;
    color: {{ ink }}; border-bottom: 1px solid {{ line }}; }
  .info-row.last { border-bottom: none; }
  .datetime { display: flex; align-items: center; gap: 10px; padding-top: 6px; font-size: 14.5px;
    color: {{ ink }}; }
  .datetime span { display: flex; align-items: center; gap: 7px; }
  .hr { height: 1px; background: {{ line }}; margin-top: 12px; }
  .section { display: grid; column-gap: 32px; row-gap: 10px; padding: 10px 0; }
  .section-col { display: flex; align-items: flex-start; gap: 8px; }
  .section-col.bordered { border-left: 1px solid {{ line }}; padding-left: 20px; }
  .field-label { font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.04em; color: {{ sub }}; }
  .field-value { margin-top: 2px; font-size: 14.5px; color: {{ ink }}; }
  .diff-chip { display: flex; align-items: center; gap: 8px; }
  .diff-old { text-decoration: line-through; color: {{ sub }}; }
  .diff-arrow { color: {{ sub }}; }
  .diff-new { font-weight: 700; color: {{ ink }}; }
  .footer { display: flex; align-items: center; justify-content: space-between; padding-top: 10px; }
  .footer-logo { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 700;
    letter-spacing: 0.03em; color: {{ sub }}; }
</style></head>
<body>
  <div class="card{{ ' activity' if data.template_variant == 'activity' else '' }}{{ ' undone' if data.category == 'Undo' else '' }}">
    <div class="header">
      <div class="brand">{{ icon_barchart }}{{ data.brand }}</div>
      {% if data.category == 'Undo' %}
      <div class="ribbon-undone">{{ icon_undo }}UNDONE</div>
      {% else %}
      <div class="saved-pill"><span class="saved-dot">{{ icon_check }}</span>Saved</div>
      {% endif %}
    </div>

    <div class="headline">
      <div class="headline-main">
        <div class="headline-category-row">
          <span class="badge-circle">{{ icon_badge }}</span>
          <div class="headline-category">{{ data.category.upper() }}</div>
        </div>
        <div class="headline-value">{{ data.value }}</div>
        <div class="headline-subtitle">{{ data.subtitle }}</div>
      </div>
      <div class="location">
        {% for row in data.location %}
        <div class="info-row{{ ' last' if loop.last else '' }}">{{ icon(row.icon) }}<span>{{ row.text }}</span></div>
        {% endfor %}
        <div class="datetime">
          <span>{{ icon_calendar }}{{ data.date }}</span>
          <span>{{ icon_clock }}{{ data.time }}</span>
        </div>
      </div>
    </div>

    <div class="hr"></div>

    {% if data.correction %}
    <div class="section" style="grid-template-columns: 1fr;">
      <div class="section-col">
        {{ icon('hammer') }}
        <div>
          <div class="field-label">Quantity</div>
          <div class="field-value diff-chip">
            <span class="diff-old">{{ data.correction.old_value }}</span>
            <span class="diff-arrow">&rarr;</span>
            <span class="diff-new">{{ data.correction.new_value }}</span>
          </div>
        </div>
      </div>
    </div>
    <div class="hr"></div>
    {% endif %}

    {% for section in data.sections %}
    <div class="section" style="grid-template-columns: repeat({{ section|length }}, 1fr);">
      {% for f in section %}
      <div class="section-col{{ ' bordered' if not loop.first else '' }}">
        {{ icon(f.icon) }}
        <div>
          <div class="field-label">{{ f.label }}</div>
          <div class="field-value">{{ f.value }}</div>
        </div>
      </div>
      {% endfor %}
    </div>
    <div class="hr"></div>
    {% endfor %}

    <div class="footer">
      <div class="section-col">{{ icon_hash }}<div><div class="field-label">{{ data.id_label }}</div>
        <div class="field-value" style="font-weight:600;">{{ data.record_id }}</div></div></div>
      <div class="section-col">{{ icon_clock }}<div><div class="field-label">Saved at</div>
        <div class="field-value">{{ data.saved_at }}</div></div></div>
      <div class="footer-logo">{{ icon_barchart_accent }}{{ data.logo_text }}</div>
    </div>
  </div>
</body></html>
"""
)


_card_template: Template | None = None


def render_html(data: ReceiptData) -> str:
    # jinja2 is only required if a receipt is actually rendered -- lazy
    # import + lazy Template compilation, matching how playwright is lazily
    # imported in render.py, so the core test suite (and everything that
    # merely imports channel.receipt, e.g. runtime/dependencies.py) runs
    # without jinja2 installed. See pyproject.toml's "receipt" extra.
    global _card_template
    if _card_template is None:
        from jinja2 import Template

        # BE-36: every value is escaped (receipt text comes from WhatsApp
        # messages); only the built-in SVG icons below are trusted markup.
        _card_template = Template(_CARD_TEMPLATE_SRC, autoescape=True)

    from markupsafe import Markup

    def icon(name: str) -> Markup:
        # WhatsApp keeps its brand green, matching the original design --
        # every other icon uses the standard ink color.
        color = _WHATSAPP if name == "whatsapp" else _INK
        return Markup(_icon_svg(name, color=color))

    return _card_template.render(
        data=data,
        ink=_INK,
        sub=_SUB,
        line=_LINE,
        accent=data.accent,
        icon=icon,
        icon_barchart=Markup(_icon_svg("barchart", size=16)),
        icon_barchart_accent=Markup(_icon_svg("barchart", size=13, color=data.accent)),
        icon_check=Markup(
            f'<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">{_ICONS["check"]}</svg>'
        ),
        icon_undo=Markup(
            f'<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">{_ICONS["undo"]}</svg>'
        ),
        icon_badge=Markup(_icon_svg(data.badge_icon, size=12, color=data.accent)),
        icon_calendar=Markup(_icon_svg("calendar")),
        icon_clock=Markup(_icon_svg("clock")),
        icon_hash=Markup(_icon_svg("hash")),
    )
