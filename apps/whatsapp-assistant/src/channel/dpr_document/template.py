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
  /* WEB-27, redesigned 15 Nov (Ilan: "upgrade the DPR PDF, better UI"): the same family as the weekly report --
     a dark band (who, what, which day), the project large, the day in figure cards, sections marked with the
     brand colour. Tight enough that an ordinary site day is one page. Red only for what is wrong. Tables keep
     their header on every page and never split a row. */
  @page { size: A4; margin: 12mm 0 12mm; }
  @page :first { margin-top: 0; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    color: {{ ink }}; font-size: 11px; line-height: 1.4; background: #fff; }
  .page { padding: 0 34px; }
  .tint { background: color-mix(in srgb, {{ accent }} 6%, #fff); }

  /* The band */
  .top { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px;
    background: #181B1F; color: #fff; padding: 22px 34px 18px; border-bottom: 4px solid {{ accent }}; }
  .letterhead { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .lh-logo { max-height: 46px; max-width: 120px; object-fit: contain; background: #fff; border-radius: 4px; padding: 3px; }
  .lh-name { font-size: 16px; font-weight: 700; color: #fff; letter-spacing: -0.01em; }
  .lh-line { font-size: 9px; color: #A6ACB4; margin-top: 1px; }
  .doc { text-align: right; flex-shrink: 0; }
  .doc .kind { font-size: 8.5px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
    color: color-mix(in srgb, {{ accent }} 55%, #fff); }
  .doc .title { font-size: 12px; font-weight: 600; color: #D9DCE0; margin-top: 2px; }
  .doc .day { font-size: 19px; font-weight: 700; letter-spacing: -0.01em; margin-top: 3px; }
  .doc .code { font-size: 9px; color: #A6ACB4; margin-top: 3px; font-variant-numeric: tabular-nums; }

  /* Project block */
  .head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; margin-top: 16px; }
  .head .project { font-size: 21px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.15; }
  .head .where { font-size: 11.5px; color: {{ sub }}; margin-top: 2px; }
  .head .client { text-align: right; font-size: 10px; color: {{ sub }}; }
  .client-logo { max-height: 24px; max-width: 90px; object-fit: contain; display: block; margin: 0 0 2px auto; }

  .summary { margin-top: 12px; padding: 9px 12px; background: color-mix(in srgb, {{ accent }} 7%, #fff);
    border-left: 3px solid {{ accent }}; font-size: 11.5px; line-height: 1.5; }
  .summary .label { font-size: 8px; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: {{ accent }}; margin-bottom: 2px; }

  /* The day in figures */
  .meta { display: grid; grid-template-columns: repeat({{ 4 if data.is_project else 7 }}, 1fr); gap: 6px; margin-top: 12px; }
  .meta-item { padding: 7px 9px 8px; border: 1px solid {{ line }}; border-top: 3px solid {{ accent }}; background: #fff; }
  .meta-item .label { font-size: 8px; font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase; color: {{ sub }}; }
  .meta-item .value { margin-top: 2px; font-size: 17px; font-weight: 800; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
  .meta-item .value.small { font-size: 12px; font-weight: 700; padding-top: 4px; }
  .meta-item .value.none { color: #A1A1A6; font-weight: 500; }
  .meta-item.alert { border-top-color: {{ warn }}; background: #FFF6F5; }
  .meta-item.alert .value { color: {{ warn }}; }

  /* Sections */
  .section { margin-top: 15px; }
  tr.group td { padding-top: 7px; font-size: 9.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
    color: {{ sub }}; background: #fff !important; }
  .section-title { display: flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 800;
    margin-bottom: 6px; break-after: avoid; letter-spacing: -0.005em; }
  .section-title .no { display: inline-block; width: 4px; height: 14px; background: {{ accent }}; color: transparent;
    font-size: 0; }
  .section-title .aside { margin-left: auto; font-size: 10px; font-weight: 500; color: {{ sub }}; }
  table { width: 100%; border-collapse: separate; border-spacing: 0; border-top: 2px solid {{ ink }}; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  th { text-align: left; font-size: 8px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.07em;
    color: {{ sub }}; padding: 5px 8px; border-bottom: 1px solid {{ line }}; background: #fff; }
  td { padding: 5px 8px; border-bottom: 1px solid {{ line }}; font-size: 10.5px; vertical-align: top; }
  tbody tr:nth-child(even) td { background: #FAFAFB; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.strong { font-weight: 600; }
  tr.total td { font-weight: 700; background: color-mix(in srgb, {{ accent }} 7%, #fff) !important; }
  .muted { color: {{ sub }}; }
  .empty { color: {{ sub }}; font-style: italic; padding: 8px; background: #fff !important; }
  td.low { color: {{ warn }}; font-weight: 700; }

  .pill { display: inline-block; padding: 1px 7px; border-radius: 3px; font-size: 9px; font-weight: 700; white-space: nowrap;
    letter-spacing: .02em; }
  .st-completed, .st-resolved { background: #E3F4EA; color: #0B6B3A; }
  .st-in-progress, .st-acknowledged { background: #FFF2DB; color: #8A5300; }
  .st-stopped, .st-open { background: #FDECEA; color: #A1251B; }
  .st-planned, .st-wont-fix, .st-cancelled { background: #F0F0F3; color: #55555A; }
  .severity-critical, .severity-high { color: {{ warn }}; font-weight: 700; }
  .severity-medium { color: #B45309; font-weight: 600; }
  .severity-low { color: {{ sub }}; font-weight: 600; }
  .stock-flag { color: {{ warn }}; font-size: 9.5px; margin: 3px 0 0; }
  .photos { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 2px 0 4px; }
  .photos img { width: 15%; max-width: 110px; height: 80px; object-fit: cover; border-radius: 2px; }
  .photos .more { font-size: 10.5px; opacity: 0.7; }
  tr.photo-row td { border-top: none; }
  .cont { font-size: 9.5px; margin: 2px 0 0; opacity: 0.7; }
  .note { margin-top: 6px; padding: 6px 10px; background: #FDECEA; color: #8C1D16; font-size: 10px; }
  .plan { padding: 8px 12px; border-left: 3px solid {{ accent }}; background: #FAFAFB; white-space: pre-line; font-size: 11px; }

  /* Manpower as chips */
  .trades { display: flex; flex-wrap: wrap; gap: 6px; }
  .trade { display: flex; align-items: baseline; gap: 6px; border: 1px solid {{ line }}; padding: 5px 10px; }
  .trade .n { font-size: 14px; font-weight: 800; font-variant-numeric: tabular-nums; }
  .trade .t { font-size: 10.5px; color: {{ sub }}; }
  .trade.total { background: #181B1F; border-color: #181B1F; color: #fff; }
  .trade.total .t { color: #C9CDD2; }

  .end { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin-top: 22px; break-inside: avoid; }
  .signatory { display: flex; justify-content: flex-end; break-inside: avoid; }
  .signatory .box { width: 200px; text-align: center; font-size: 10.5px; }
  .signatory .rule { border-top: 1px solid {{ ink }}; margin-bottom: 4px; height: 24px; }
  .signatory .name { font-weight: 700; }
  .signatory .role { color: {{ sub }}; font-size: 9.5px; }
  .footer { margin-top: 16px; padding: 8px 0 0; border-top: 1px solid {{ line }};
    display: flex; justify-content: space-between; font-size: 8.5px; color: {{ sub }}; }
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
      <div class="day">{{ data.date_label or data.report_date }}</div>
      <div class="code">{{ data.code }}</div>
    </div>
  </div>
  <div class="page">

  <div class="head">
    <div>
      <div class="project">{{ data.project_name }}</div>
      <div class="where">{{ "All sites" if data.is_project else data.site_name }}</div>
    </div>
    {% if lh and (lh.client_name or lh.client_logo_data_uri) %}
    <div class="client">
      {% if lh.client_logo_data_uri %}<img class="client-logo" src="{{ lh.client_logo_data_uri|e }}" alt=""/>{% endif %}
      {% if lh.client_name %}Client: {{ lh.client_name|e }}{% endif %}
    </div>
    {% endif %}
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
        <tr><td class="strong">{{ a.work_type }}{% if a.continued_from %}<div class="cont">Continued from {{ a.continued_from }}</div>{% endif %}{% if a.possible_duplicate %}<div class="stock-flag">Possible duplicate</div>{% endif %}</td>
          <td>{{ a.narrative }}</td>
          <td><span class="pill st-{{ a.status|lower|replace(' ', '-') }}">{{ a.status }}</span></td>
          <td>{{ a.contractor }}</td><td>{{ a.quantities }}</td><td class="num">{{ a.evidence_count or "—" }}</td></tr>
        {% if a.thumbs %}
        <tr class="photo-row"><td colspan="6"><div class="photos">
          {% for t in a.thumbs %}<img src="{{ t }}" alt="Site photo">{% endfor %}
          {% if a.photos_more %}<span class="more">+ {{ a.photos_more }} more</span>{% endif %}
        </div></td></tr>
        {% endif %}
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
    {% if data.trades %}
    <div class="trades">
      {% for t in data.trades %}<div class="trade"><span class="n">{{ t.headcount }}</span><span class="t">{{ t.trade }}</span></div>{% endfor %}
      {% if data.trades|length > 1 %}<div class="trade total"><span class="n">{{ data.headcount }}</span><span class="t">Total</span></div>{% endif %}
    </div>
    {% elif data.headcount %}
    {# 15 Nov: a project's day has no trade split; "No attendance recorded" with 21 workers on site was wrong. #}
    <div class="trades">
      {% if data.is_project %}{% for st in data.sites if st.headcount %}<div class="trade"><span class="n">{{ st.headcount }}</span><span class="t">{{ st.site_name }}</span></div>{% endfor %}{% endif %}
      <div class="trade total"><span class="n">{{ data.headcount }}</span><span class="t">Total</span></div>
    </div>
    {% else %}
    <table><tbody><tr><td class="empty">No attendance recorded for this date.</td></tr></tbody></table>
    {% endif %}
  </div>

  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Materials</div>
    {% set stock = data.materials|selectattr("closing")|list %}
    <table>
      <thead><tr><th style="width:{{ '40%' if stock else '46%' }}">Material</th><th class="num" style="width:15%">Received</th>
        <th class="num" style="width:15%">Used</th>{% if stock %}<th class="num" style="width:15%">Stock left</th>{% endif %}
        <th style="width:15%">Unit</th></tr></thead>
      <tbody>
        {% for m in data.materials %}
        {% if m.group %}<tr class="group"><td colspan="{{ 5 if stock else 4 }}">{{ m.group }}</td></tr>{% endif %}
        <tr><td class="strong">{{ m.material_name }}</td><td class="num">{{ m.received }}</td><td class="num">{{ m.used }}</td>
          {% if stock %}<td class="num{{ ' low' if m.beyond_stock or (m.closing or '').startswith('-') }}">{{ m.closing or "—" }}</td>{% endif %}
          <td>{{ m.unit }}</td></tr>
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

  {% if data.machinery %}
  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Machinery</div>
    <table>
      <thead><tr><th style="width:30%">Machine</th><th class="num" style="width:11%">Worked</th>
        <th class="num" style="width:11%">Idle</th><th class="num" style="width:13%">Breakdown</th>
        <th class="num" style="width:11%">Diesel</th><th style="width:24%">Note</th></tr></thead>
      <tbody>
        {% for m in data.machinery %}
        <tr><td class="strong">{{ m.machine }}{% if m.ownership %} <span class="muted">· {{ m.ownership }}</span>{% endif %}{% if m.site_name %} <span class="muted">· {{ m.site_name }}</span>{% endif %}</td>
          <td class="num">{{ m.worked }} h</td><td class="num">{{ m.idle }} h</td><td class="num">{{ m.breakdown }} h</td>
          <td class="num">{{ m.fuel }}</td><td>{{ m.note }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

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
          <td>{{ i.narrative }}{% if i.since %}<span class="muted"> · reported {{ i.since }}</span>{% endif %}</td>
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
