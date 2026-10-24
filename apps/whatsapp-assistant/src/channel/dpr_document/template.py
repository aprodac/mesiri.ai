"""HTML/CSS layout for the DPR PDF -- a full A4 page, not a WhatsApp card
(contrast channel/receipt/template.py, which renders one screenshot-sized
card). Same lazy-Jinja2-import convention: the core test suite runs without
jinja2 installed unless a document is actually rendered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .data import DprDocumentData
from .letterhead import Letterhead

if TYPE_CHECKING:
    from jinja2 import Template

_INK = "#1D1D1F"
_SUB = "#6E6E73"
_LINE = "#E1E1E6"
_ACCENT = "#0A8F4C"
_WARN = "#B3261E"

_DOCUMENT_TEMPLATE_SRC = """
<!doctype html>
<html><head><meta charset="utf-8"><style>
  /* WEB-27: the DPR as a construction report people recognise -- letterhead,
     a project block, the day in figures, then numbered sections. One accent
     (the company's brand colour), tints of it for structure; red only for
     what is wrong. Tables keep their header on every page and never split
     a row. */
  /* Continuation pages get their own top and bottom margin; the first page's
     top is the body's padding. */
  @page { size: A4; margin: 12mm 0 12mm; }
  @page :first { margin-top: 0; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    color: {{ ink }}; padding: 30px 36px 0; font-size: 11.5px; line-height: 1.4; background: #fff; }
  .tint { background: color-mix(in srgb, {{ accent }} 7%, #fff); }

  /* Letterhead band */
  .top { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px;
    padding-bottom: 14px; border-bottom: 3px solid {{ accent }}; }
  .letterhead { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .lh-logo { max-height: 54px; max-width: 140px; object-fit: contain; }
  .lh-name { font-size: 18px; font-weight: 700; color: {{ accent }}; letter-spacing: -0.01em; }
  .lh-line { font-size: 9.5px; color: {{ sub }}; margin-top: 1px; }
  .doc { text-align: right; flex-shrink: 0; }
  .doc .kind { font-size: 9px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: {{ accent }}; }
  .doc .title { font-size: 19px; font-weight: 700; letter-spacing: -0.01em; margin-top: 1px; }
  .doc .code { font-size: 10px; color: {{ sub }}; margin-top: 3px; font-variant-numeric: tabular-nums; }

  /* Project block */
  .info { display: grid; grid-template-columns: repeat(4, 1fr); margin-top: 14px;
    border: 1px solid {{ line }}; border-radius: 6px; overflow: hidden; }
  .info > div { padding: 7px 10px; border-left: 1px solid {{ line }}; min-width: 0; }
  .info > div:first-child { border-left: none; }
  .info .k { font-size: 8.5px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: {{ sub }}; }
  .info .v { font-size: 12px; font-weight: 600; margin-top: 1px; overflow-wrap: anywhere; }
  .client-logo { max-height: 22px; max-width: 90px; object-fit: contain; display: block; margin-top: 2px; }

  .summary { margin-top: 12px; padding: 9px 12px; background: color-mix(in srgb, {{ accent }} 7%, #fff); border-left: 3px solid {{ accent }};
    border-radius: 0 6px 6px 0; font-size: 12px; line-height: 1.5; }
  .summary .label { font-size: 8.5px; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: {{ accent }}; margin-bottom: 2px; }

  /* The day in figures */
  .meta { display: grid; grid-template-columns: repeat({{ 4 if data.is_project else 7 }}, 1fr); gap: 6px; margin-top: 12px; }
  .meta-item { border-radius: 6px; padding: 8px 10px; }
  .meta-item .label { font-size: 8.5px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: {{ sub }}; }
  .meta-item .value { margin-top: 2px; font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .meta-item .value.small { font-size: 12.5px; padding-top: 3px; }
  .meta-item .value.none { color: #A1A1A6; font-weight: 500; }
  .meta-item.alert { background: #FDECEA; }
  .meta-item.alert .value { color: {{ warn }}; }

  /* Sections */
  .section { margin-top: 18px; }
  .section-title { display: flex; align-items: baseline; gap: 8px; font-size: 12.5px; font-weight: 700;
    margin-bottom: 6px; break-after: avoid; }
  .section-title .no { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px;
    border-radius: 4px; background: {{ accent }}; color: #fff; font-size: 10px; font-weight: 700; }
  .section-title .aside { margin-left: auto; font-size: 10.5px; font-weight: 500; color: {{ sub }}; }
  table { width: 100%; border-collapse: separate; border-spacing: 0; border: 1px solid {{ line }}; border-radius: 6px; overflow: hidden; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  th { text-align: left; font-size: 8.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em;
    color: {{ sub }}; padding: 6px 9px; border-bottom: 1px solid {{ line }};
    background: color-mix(in srgb, {{ accent }} 7%, #fff); }
  td { padding: 6px 9px; border-bottom: 1px solid {{ line }}; font-size: 11px; vertical-align: top; }
  tbody tr:nth-child(even) td { background: #FAFAFB; }
  tbody tr:last-child td { border-bottom: none; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.strong { font-weight: 600; }
  tr.total td { font-weight: 700; background: color-mix(in srgb, {{ accent }} 7%, #fff) !important; border-top: 1px solid {{ line }}; }
  .muted { color: {{ sub }}; }
  .empty { color: {{ sub }}; font-style: italic; padding: 9px; background: #fff !important; }

  .pill { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 9.5px; font-weight: 600; white-space: nowrap; }
  .st-completed, .st-resolved { background: #E3F4EA; color: #0B6B3A; }
  .st-in-progress, .st-acknowledged { background: #FFF2DB; color: #8A5300; }
  .st-stopped, .st-open { background: #FDECEA; color: #A1251B; }
  .st-planned, .st-wont-fix, .st-cancelled { background: #F0F0F3; color: #55555A; }
  .severity-critical, .severity-high { color: {{ warn }}; font-weight: 700; }
  .severity-medium { color: #B45309; font-weight: 600; }
  .severity-low { color: {{ sub }}; font-weight: 600; }
  .stock-flag { color: {{ warn }}; font-size: 10px; margin: 3px 0 0; }
  .note { margin-top: 6px; padding: 7px 10px; border-radius: 6px; background: #FDECEA; color: #8C1D16; font-size: 10.5px; }
  .plan { padding: 9px 12px; border: 1px solid {{ line }}; border-radius: 6px; white-space: pre-line; font-size: 11.5px; }

  .signatory { margin-top: 30px; display: flex; justify-content: flex-end; break-inside: avoid; }
  .signatory .box { width: 210px; text-align: center; font-size: 11px; }
  .signatory .rule { border-top: 1px solid {{ ink }}; margin-bottom: 4px; height: 26px; }
  .signatory .name { font-weight: 600; }
  .signatory .role { color: {{ sub }}; font-size: 10px; }
  .footer { margin-top: 22px; padding-top: 8px; border-top: 1px solid {{ line }};
    display: flex; justify-content: space-between; font-size: 9px; color: {{ sub }}; }
</style></head>
<body>
  <div class="top">
    {% if lh %}
    <div class="letterhead">
      {% if lh.logo_data_uri %}<img class="lh-logo" src="{{ lh.logo_data_uri|e }}" alt=""/>{% endif %}
      <div>
        <div class="lh-name">{{ lh.company_name|e }}</div>
        {% if lh.address %}<div class="lh-line">{{ lh.address|e }}</div>{% endif %}
        {% if lh.contact %}<div class="lh-line">{{ lh.contact|e }}</div>{% endif %}
        {% if lh.gstin %}<div class="lh-line">GSTIN: {{ lh.gstin|e }}</div>{% endif %}
      </div>
    </div>
    {% else %}
    <div></div>
    {% endif %}
    <div class="doc">
      <div class="kind">{{ "Project" if data.is_project else "Site" }} report</div>
      <div class="title">Daily Progress Report</div>
      <div class="code">{{ data.code }}</div>
    </div>
  </div>

  <div class="info">
    <div><div class="k">Project</div><div class="v">{{ data.project_name }}</div></div>
    <div><div class="k">Site</div><div class="v">{{ "All sites" if data.is_project else data.site_name }}</div></div>
    <div><div class="k">Date</div><div class="v">{{ data.date_label or data.report_date }}</div></div>
    <div><div class="k">Client</div><div class="v">
      {% if lh and lh.client_logo_data_uri %}<img class="client-logo" src="{{ lh.client_logo_data_uri|e }}" alt=""/>{% endif %}
      {% if lh and lh.client_name %}Client: {{ lh.client_name|e }}{% elif not (lh and lh.client_logo_data_uri) %}<span class="muted">—</span>{% endif %}
    </div></div>
  </div>

  {% if data.summary %}
  <div class="summary"><div class="label">Summary</div>{{ data.summary }}</div>
  {% endif %}

  <div class="meta">
    {% if data.is_project %}
    <div class="meta-item tint"><div class="label">Sites Reporting</div><div class="value">{{ data.reported_site_count }}/{{ data.total_site_count }}</div></div>
    {% endif %}
    <div class="meta-item tint"><div class="label">Workers</div><div class="value">{{ data.headcount or "—" }}</div></div>
    {% if not data.is_project %}
    <div class="meta-item tint"><div class="label">Work items</div><div class="value">{{ data.activity_count or "—" }}</div></div>
    <div class="meta-item tint"><div class="label">Photos</div><div class="value">{{ data.evidence_count or "—" }}</div></div>
    {% endif %}
    <div class="meta-item {{ 'alert' if data.open_issue_count else 'tint' }}"><div class="label">Open issues</div><div class="value">{{ data.open_issue_count or "—" }}</div></div>
    {% if not data.is_project %}
    <div class="meta-item tint"><div class="label">Weather</div><div class="value small {{ 'none' if data.weather == 'Not set' }}">{{ data.weather }}</div></div>
    <div class="meta-item tint"><div class="label">Site working</div><div class="value small {{ 'none' if data.site_working == 'Not set' }}">{{ data.site_working }}</div></div>
    <div class="meta-item {{ 'alert' if data.hours_lost != '—' and data.hours_lost != '0 h' else 'tint' }}"><div class="label">Hours lost</div><div class="value small {{ 'none' if data.hours_lost == '—' }}">{{ data.hours_lost }}</div></div>
    {% else %}
    <div class="meta-item tint"><div class="label">Issues listed</div><div class="value">{{ data.issues|length or "—" }}</div></div>
    {% endif %}
  </div>

  {% set n = namespace(i=0) %}
  {% if data.is_project %}
  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Sites</div>
    <table>
      <thead><tr><th style="width:34%">Site</th><th style="width:18%">Reported</th>
        <th class="num" style="width:16%">Work items</th><th class="num" style="width:16%">Open issues</th>
        <th class="num" style="width:16%">Workers</th></tr></thead>
      <tbody>
        {% for s in data.sites %}
        <tr><td class="strong">{{ s.site_name }}</td>
          <td>{% if s.reported %}<span class="pill st-completed">Yes</span>{% else %}<span class="pill st-stopped">Not reported</span>{% endif %}</td>
          <td class="num">{{ s.activity_count }}</td><td class="num">{{ s.open_issue_count }}</td><td class="num">{{ s.headcount }}</td></tr>
        {% else %}
        <tr><td colspan="5" class="empty">No active sites under this project.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Work done
      {% if data.activities %}<span class="aside">{{ data.activities|length }} item{{ "" if data.activities|length == 1 else "s" }}</span>{% endif %}</div>
    <table>
      <thead><tr><th style="width:22%">Work</th><th style="width:31%">Details</th>
        <th style="width:13%">Status</th><th style="width:14%">Contractor</th>
        <th style="width:14%">Quantity</th><th class="num" style="width:6%">Photos</th></tr></thead>
      <tbody>
        {% for a in data.activities %}
        <tr><td class="strong">{{ a.work_type }}{% if a.possible_duplicate %}<div class="stock-flag">Possible duplicate</div>{% endif %}</td>
          <td>{{ a.narrative }}</td>
          <td><span class="pill st-{{ a.status|lower|replace(' ', '-') }}">{{ a.status }}</span></td>
          <td>{{ a.contractor }}</td><td>{{ a.quantities }}</td><td class="num">{{ a.evidence_count or "—" }}</td></tr>
        {% else %}
        <tr><td colspan="6" class="empty">No activities logged for this date.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Manpower
      {% if data.headcount %}<span class="aside">{{ data.headcount }} on site{% if data.labour_cost_label %} · Labour cost {{ data.labour_cost_label }}{% endif %}</span>{% endif %}</div>
    <table>
      <thead><tr><th style="width:80%">Trade</th><th class="num" style="width:20%">Headcount</th></tr></thead>
      <tbody>
        {% for t in data.trades %}
        <tr><td>{{ t.trade }}</td><td class="num">{{ t.headcount }}</td></tr>
        {% else %}
        <tr><td colspan="2" class="empty">No attendance recorded for this date.</td></tr>
        {% endfor %}
        {% if data.trades|length > 1 %}<tr class="total"><td>Total</td><td class="num">{{ data.headcount }}</td></tr>{% endif %}
      </tbody>
    </table>
  </div>

  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Materials</div>
    <table>
      <thead><tr><th style="width:46%">Material</th><th class="num" style="width:18%">Received</th>
        <th class="num" style="width:18%">Used</th><th style="width:18%">Unit</th></tr></thead>
      <tbody>
        {% for m in data.materials %}
        <tr><td class="strong">{{ m.material_name }}</td><td class="num">{{ m.received }}</td><td class="num">{{ m.used }}</td><td>{{ m.unit }}</td></tr>
        {% else %}
        <tr><td colspan="4" class="empty">No material movements recorded for this date.</td></tr>
        {% endfor %}
      </tbody>
    </table>
    {% for m in data.materials if m.beyond_stock %}
    <p class="note">Check: more {{ m.material_name }} used than the site's known stock
      (stock now {{ m.closing }} {{ m.unit }}). A delivery or opening stock may be missing.</p>
    {% endfor %}
  </div>

  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Site Issues
      {% if data.open_issue_count %}<span class="aside">{{ data.open_issue_count }} open</span>{% endif %}</div>
    <table>
      <thead><tr>
        {% if data.is_project %}<th style="width:16%">Site</th>{% endif %}
        <th style="width:18%">Type</th><th style="width:11%">Severity</th>
        <th style="width:{{ '39%' if data.is_project else '55%' }}">What happened</th><th style="width:16%">Status</th></tr></thead>
      <tbody>
        {% for i in data.issues %}
        <tr>
          {% if data.is_project %}<td>{{ i.site_name }}</td>{% endif %}
          <td class="strong">{{ i.issue_type }}</td>
          <td class="severity-{{ i.severity|lower }}">{{ i.severity }}</td>
          <td>{{ i.narrative }}</td>
          <td><span class="pill st-{{ i.status|lower|replace(' ', '-') }}">{{ i.status }}</span></td></tr>
        {% else %}
        <tr><td colspan="{{ 5 if data.is_project else 4 }}" class="empty">No issues reported for this date.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {% if data.tomorrow_plan %}
  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Tomorrow's Plan</div>
    <div class="plan">{{ data.tomorrow_plan|e }}</div>
  </div>
  {% endif %}

  {% if data.late_entries %}
  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Late entries for earlier days</div>
    <table>
      <thead><tr><th style="width:18%">Day</th><th>Entry</th></tr></thead>
      <tbody>
        {% for e in data.late_entries %}
        <tr><td>{{ e.report_date }}</td><td>{{ e.summary }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
    <p class="stock-flag">Sent after that day's report was confirmed. Not part of the confirmed report for that day.</p>
  </div>
  {% endif %}

  {% if lh and (lh.signatory_name or lh.signatory_designation) %}
  <div class="signatory"><div class="box">
    <div class="rule"></div>
    <div class="name">{{ lh.signatory_name|e }}</div>
    <div class="role">{{ lh.signatory_designation|e }}</div>
  </div></div>
  {% endif %}

  <div class="footer">
    <span>Generated with Mesiri</span>
    <span>{{ data.code }} · {{ data.report_date }}</span>
  </div>
</body></html>
"""

_document_template: Template | None = None


def render_html(data: DprDocumentData, letterhead: Letterhead | None = None) -> str:
    """The DPR page; with a ``letterhead`` (BE-19) it carries the company's
    logo, details and brand colour, the client's logo and the signatory."""
    global _document_template
    if _document_template is None:
        from jinja2 import Template

        # BE-36: every value is escaped. The DPR is built from what people
        # typed on WhatsApp and rendered in a real browser; nothing in `data`
        # or the letterhead is markup.
        _document_template = Template(_DOCUMENT_TEMPLATE_SRC, autoescape=True)

    accent = (letterhead.brand_color if letterhead else None) or _ACCENT
    return _document_template.render(
        data=data, lh=letterhead, ink=_INK, sub=_SUB, line=_LINE, accent=accent, warn=_WARN
    )
