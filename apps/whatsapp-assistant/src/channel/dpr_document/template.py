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

_INK = "#14161A"
_SUB = "#6B7078"
_LINE = "#E6E6E3"
_ACCENT = "#0A8F4C"
_WARN = "#B3261E"

_DOCUMENT_TEMPLATE_SRC = """
<!doctype html>
<html><head><meta charset="utf-8"><style>
  /* WEB-27, redesigned twice on 15 Nov (Ilan: "still bad, completely change its design"). A report a site
     engineer is proud to forward: the day as a big date block in the company's colour, the project large, the day
     in one strip of figures, then two columns -- what was done (cards) on the left, the people and tomorrow on the
     right. Inter is embedded (the server has no fonts of its own). Red only for what is wrong. */
  {{ fonts|safe }}
  @page { size: A4; margin: 10mm 0 12mm; }
  @page :first { margin-top: 0; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: "Inter", "Noto Sans Malayalam", "Noto Sans Devanagari", "Noto Sans", sans-serif;
    color: {{ ink }}; font-size: 10.5px; line-height: 1.45; background: #fff; font-variant-numeric: tabular-nums; }
  .wrap { padding: 0 32px; }

  /* Letterhead strip */
  .top { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 18px 32px 14px; }
  .letterhead { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .lh-logo { max-height: 40px; max-width: 120px; object-fit: contain; }
  .lh-name { font-size: 13px; font-weight: 800; letter-spacing: -0.01em; }
  .lh-line { font-size: 8.5px; color: {{ sub }}; }
  .doc { text-align: right; }
  .doc .kind { font-size: 8px; font-weight: 800; letter-spacing: 0.18em; text-transform: uppercase; color: {{ accent }}; }
  .doc .title { font-size: 11px; font-weight: 700; margin-top: 1px; }
  .doc .code { display: inline-block; margin-top: 4px; font-size: 8.5px; font-weight: 600; color: {{ sub }};
    border: 1px solid {{ line }}; border-radius: 999px; padding: 1px 8px; }

  /* Hero: the date block and the project */
  .hero { display: flex; align-items: stretch; margin: 0 32px; border-radius: 14px; overflow: hidden;
    background: #F6F6F4; }
  .dateblock { background: {{ accent }}; color: #fff; padding: 14px 20px; display: flex; align-items: center; gap: 12px;
    min-width: 170px; }
  .dateblock .dnum { font-size: 46px; font-weight: 800; line-height: 1; letter-spacing: -0.04em; }
  .dateblock .dmon { font-size: 11px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
  .dateblock .dday { font-size: 11px; opacity: 0.85; margin-top: 2px; }
  .ident { padding: 14px 20px; flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: center; }
  .ident .project { font-size: 22px; font-weight: 800; letter-spacing: -0.025em; line-height: 1.1; }
  .ident .where { font-size: 11.5px; color: {{ sub }}; margin-top: 3px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .ident .dot { width: 3px; height: 3px; border-radius: 50%; background: #B8BCC2; }
  .client-logo { max-height: 20px; max-width: 80px; object-fit: contain; }

  .summary { margin: 12px 32px 0; padding: 10px 14px; border-radius: 10px; border: 1px solid {{ line }};
    font-size: 11.5px; line-height: 1.55; display: flex; gap: 10px; }
  .summary .label { flex-shrink: 0; font-size: 8px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase;
    color: #fff; background: {{ ink }}; border-radius: 4px; padding: 2px 6px; height: fit-content; margin-top: 2px; }

  /* The day in one strip */
  .meta { display: grid; grid-template-columns: repeat({{ 4 if data.is_project else 7 }}, 1fr); margin: 12px 32px 0;
    border: 1px solid {{ line }}; border-radius: 12px; overflow: hidden; }
  .meta-item { padding: 9px 10px; border-left: 1px solid {{ line }}; }
  .meta-item:first-child { border-left: none; }
  .meta-item .label { display: flex; align-items: center; gap: 4px; font-size: 7.5px; font-weight: 700;
    letter-spacing: 0.08em; text-transform: uppercase; color: {{ sub }}; }
  .meta-item .label svg { width: 11px; height: 11px; stroke: {{ sub }}; fill: none; stroke-width: 2; flex-shrink: 0; }
  .meta-item .value { margin-top: 3px; font-size: 18px; font-weight: 800; letter-spacing: -0.02em; }
  .meta-item .value.small { font-size: 11.5px; font-weight: 700; padding-top: 5px; letter-spacing: 0; }
  .meta-item .value.none { color: #B0B4BA; font-weight: 600; }
  .meta-item.alert { background: #FEF3F2; }
  .meta-item.alert .value, .meta-item.alert .label { color: {{ warn }}; }
  .meta-item.alert .label svg { stroke: {{ warn }}; }

  /* Two columns */
  .cols { display: grid; grid-template-columns: minmax(0, 1fr) 210px; gap: 20px; margin: 16px 32px 0; align-items: start; }
  .side { display: flex; flex-direction: column; gap: 14px; }
  .section { margin-bottom: 16px; }
  .side .section { margin-bottom: 0; padding: 12px; border-radius: 12px; background: #F6F6F4; }
  .section-title { display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 800; letter-spacing: -0.01em;
    margin-bottom: 8px; break-after: avoid; }
  .section-title .no { display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 18px;
    padding: 0 5px; border-radius: 6px; background: {{ accent }}; color: #fff; font-size: 9.5px; font-weight: 800; }
  .section-title .aside { margin-left: auto; font-size: 9.5px; font-weight: 600; color: {{ sub }}; }

  /* Work cards */
  .cards { display: flex; flex-direction: column; gap: 7px; }
  .cards.two { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
  .full { margin: 0 32px; }
  .full .cards.issues { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
  .card { border: 1px solid {{ line }}; border-radius: 10px; padding: 9px 12px 9px 14px; position: relative; break-inside: avoid; }
  .card::before { content: ""; position: absolute; left: 0; top: 10px; bottom: 10px; width: 3px; border-radius: 0 3px 3px 0;
    background: {{ accent }}; }
  .card.st-stopped::before, .card.st-open::before { background: {{ warn }}; }
  .card.st-planned::before, .card.st-cancelled::before { background: #B0B4BA; }
  .card .row { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
  .card .what { font-size: 11.5px; font-weight: 700; }
  .card .detail { margin-top: 2px; color: #374151; }
  .card .facts { margin-top: 5px; display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 9.5px; color: {{ sub }}; }
  .card .facts b { color: {{ ink }}; font-weight: 700; }
  .empty { color: {{ sub }}; font-style: italic; padding: 10px 12px; border: 1px dashed {{ line }}; border-radius: 10px; }
  .side .empty { border: none; padding: 2px 0; }

  .pill { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 8.5px; font-weight: 700; white-space: nowrap; }
  .st-completed, .st-resolved { background: #E3F4EA; color: #0B6B3A; }
  .st-in-progress, .st-acknowledged { background: #FFF2DB; color: #8A5300; }
  .st-stopped, .st-open { background: #FDECEA; color: #A1251B; }
  .st-planned, .st-wont-fix, .st-cancelled { background: #EFEFF2; color: #55555A; }
  .card.st-completed, .card.st-in-progress, .card.st-stopped, .card.st-planned, .card.st-open, .card.st-resolved,
  .card.st-acknowledged, .card.st-wont-fix, .card.st-cancelled { background: #fff; color: {{ ink }}; }
  .sev { display: inline-block; font-size: 8px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase;
    padding: 1px 6px; border-radius: 4px; }
  .severity-critical, .severity-high { background: #FDECEA; color: {{ warn }}; }
  .severity-medium { background: #FFF2DB; color: #B45309; }
  .severity-low { background: #EFEFF2; color: {{ sub }}; }
  .stock-flag { color: {{ warn }}; font-size: 9.5px; margin: 3px 0 0; }
  .cont { font-size: 9.5px; color: {{ sub }}; margin-top: 2px; }
  .photos { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; margin-top: 7px; }
  .photos img { width: 74px; height: 56px; object-fit: cover; border-radius: 6px; }
  .photos .more { font-size: 9.5px; color: {{ sub }}; }

  /* Tables (materials, sites, machines, late entries) */
  table { width: 100%; border-collapse: separate; border-spacing: 0; border: 1px solid {{ line }}; border-radius: 10px; overflow: hidden; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  th { text-align: left; font-size: 7.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
    color: {{ sub }}; padding: 6px 10px; background: #F6F6F4; border-bottom: 1px solid {{ line }}; }
  td { padding: 6px 10px; border-bottom: 1px solid {{ line }}; font-size: 10px; vertical-align: top; }
  tbody tr:last-child td { border-bottom: none; }
  td.num, th.num { text-align: right; }
  td.strong { font-weight: 700; }
  td.low { color: {{ warn }}; font-weight: 800; }
  tr.group td { padding: 7px 10px 3px; font-size: 7.5px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase;
    color: {{ accent }}; border-bottom: none; }
  .muted { color: {{ sub }}; }
  .note { margin-top: 6px; padding: 7px 10px; border-radius: 8px; background: #FEF3F2; color: #8C1D16; font-size: 9.5px; }

  /* Manpower bars (side) */
  .bars { display: flex; flex-direction: column; gap: 6px; }
  .bar .lbl { display: flex; justify-content: space-between; font-size: 9.5px; }
  .bar .lbl b { font-weight: 800; }
  .bar .track { height: 6px; border-radius: 3px; background: #E4E4E0; margin-top: 2px; overflow: hidden; }
  .bar .fill { height: 6px; border-radius: 3px; background: {{ accent }}; }
  .total { display: flex; justify-content: space-between; align-items: baseline; margin-top: 8px; padding-top: 7px;
    border-top: 1px solid #E4E4E0; }
  .total .n { font-size: 20px; font-weight: 800; letter-spacing: -0.02em; }
  .total .t { font-size: 9px; color: {{ sub }}; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
  .cost { margin-top: 4px; font-size: 9.5px; color: {{ sub }}; }
  .plan { white-space: pre-line; font-size: 10.5px; }

  .signatory { display: flex; justify-content: flex-end; break-inside: avoid; margin-top: 6px; }
  .signatory .box { width: 200px; text-align: center; font-size: 10px; }
  .signatory .rule { border-top: 1px solid {{ ink }}; margin: 22px 0 4px; }
  .signatory .name { font-weight: 800; }
  .signatory .role { color: {{ sub }}; font-size: 9px; }
  .footer { margin: 14px 32px 0; padding-top: 8px; border-top: 1px solid {{ line }};
    display: flex; justify-content: space-between; font-size: 8px; color: {{ sub }}; }
</style></head>
<body>
  {% set icons = {
    "people": '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.3-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20c-.4-2.6-1.9-4.3-4-5"/></svg>',
    "work": '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h10"/></svg>',
    "photo": '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="14" rx="2"/><circle cx="12" cy="13" r="3.5"/><path d="M8 6l1.5-2.5h5L16 6"/></svg>',
    "issue": '<svg viewBox="0 0 24 24"><path d="M12 3l9.5 17h-19z"/><path d="M12 10v4M12 17v.5"/></svg>',
    "sky": '<svg viewBox="0 0 24 24"><path d="M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 18z"/></svg>',
    "site": '<svg viewBox="0 0 24 24"><path d="M3 21h18M5 21V9l7-5 7 5v12M10 21v-6h4v6"/></svg>',
    "clock": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  } %}

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

  <div class="hero">
    <div class="dateblock">
      <div class="dnum">{{ day.num }}</div>
      <div><div class="dmon">{{ day.month }}</div><div class="dday">{{ day.weekday }}</div></div>
    </div>
    <div class="ident">
      <div class="project">{{ data.project_name }}</div>
      <div class="where"><span>{{ "All sites" if data.is_project else data.site_name }}</span>
        {% if lh and (lh.client_name or lh.client_logo_data_uri) %}<span class="dot"></span>
        {% if lh.client_logo_data_uri %}<img class="client-logo" src="{{ lh.client_logo_data_uri|e }}" alt=""/>{% endif %}
        {% if lh.client_name %}<span>Client: {{ lh.client_name|e }}</span>{% endif %}{% endif %}
      </div>
    </div>
  </div>

  {% if data.summary %}
  <div class="summary"><div class="label">Summary</div><div>{{ data.summary }}</div></div>
  {% endif %}

  <div class="meta">
    {% if data.is_project %}
    <div class="meta-item"><div class="label">{{ icons.site|safe }}Sites Reporting</div><div class="value">{{ data.reported_site_count }}/{{ data.total_site_count }}</div></div>
    {% endif %}
    <div class="meta-item"><div class="label">{{ icons.people|safe }}Workers</div><div class="value {{ 'none' if not data.headcount }}">{{ data.headcount or "—" }}</div></div>
    {% if not data.is_project %}
    <div class="meta-item"><div class="label">{{ icons.work|safe }}Work items</div><div class="value {{ 'none' if not data.activity_count }}">{{ data.activity_count or "—" }}</div></div>
    <div class="meta-item"><div class="label">{{ icons.photo|safe }}Photos</div><div class="value {{ 'none' if not data.evidence_count }}">{{ data.evidence_count or "—" }}</div></div>
    {% endif %}
    <div class="meta-item {{ 'alert' if data.open_issue_count }}"><div class="label">{{ icons.issue|safe }}Open issues</div><div class="value {{ 'none' if not data.open_issue_count }}">{{ data.open_issue_count or "—" }}</div></div>
    {% if not data.is_project %}
    <div class="meta-item"><div class="label">{{ icons.sky|safe }}Weather</div><div class="value small {{ 'none' if data.weather == 'Not set' }}">{{ data.weather }}</div></div>
    <div class="meta-item"><div class="label">{{ icons.site|safe }}Site working</div><div class="value small {{ 'none' if data.site_working == 'Not set' }}">{{ data.site_working }}</div></div>
    <div class="meta-item {{ 'alert' if data.hours_lost != '—' and data.hours_lost != '0 h' }}"><div class="label">{{ icons.clock|safe }}Hours lost</div><div class="value small {{ 'none' if data.hours_lost == '—' }}">{{ data.hours_lost }}</div></div>
    {% else %}
    <div class="meta-item"><div class="label">{{ icons.issue|safe }}Issues listed</div><div class="value {{ 'none' if not data.issues }}">{{ data.issues|length or "—" }}</div></div>
    {% endif %}
  </div>

  <div class="cols">
  <div class="main">
  {% set n = namespace(i=0) %}
  {% if data.is_project %}
  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Sites</div>
    <table>
      <thead><tr><th style="width:34%">Site</th><th style="width:22%">Reported</th>
        <th class="num" style="width:15%">Work items</th><th class="num" style="width:15%">Open issues</th>
        <th class="num" style="width:14%">Workers</th></tr></thead>
      <tbody>
        {% for s in data.sites %}
        <tr><td class="strong">{{ s.site_name }}</td>
          <td>{% if s.reported %}<span class="pill st-completed">Yes</span>{% else %}<span class="pill st-stopped">Not reported</span>{% endif %}</td>
          <td class="num">{{ s.activity_count }}</td><td class="num">{{ s.open_issue_count }}</td><td class="num">{{ s.headcount }}</td></tr>
        {% else %}
        <tr><td colspan="5" class="muted">No active sites under this project.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  {% set n.i = n.i + 1 %}
  <div class="section">
    <div class="section-title"><span class="no">{{ n.i }}</span>Work done
      {% if data.activities %}<span class="aside">{{ data.activities|length }} item{{ "" if data.activities|length == 1 else "s" }}</span>{% endif %}</div>
    <div class="cards{{ ' two' if data.activities|length > 3 }}">
      {% for a in data.activities %}
      {% set st = a.status|lower|replace(' ', '-') %}
      <div class="card st-{{ st }}">
        <div class="row"><div class="what">{{ a.work_type }}</div><span class="pill st-{{ st }}">{{ a.status }}</span></div>
        {% if a.narrative and a.narrative != "—" %}<div class="detail">{{ a.narrative }}</div>{% endif %}
        <div class="facts">
          {% if a.quantities and a.quantities != "—" %}<span>Quantity <b>{{ a.quantities }}</b></span>{% endif %}
          {% if a.contractor and a.contractor != "—" %}<span>Contractor <b>{{ a.contractor }}</b></span>{% endif %}
          {% if a.evidence_count %}<span>Photos <b>{{ a.evidence_count }}</b></span>{% endif %}
        </div>
        {% if a.continued_from %}<div class="cont">Continued from {{ a.continued_from }}</div>{% endif %}
        {% if a.possible_duplicate %}<div class="stock-flag">Possible duplicate</div>{% endif %}
        {% if a.thumbs %}<div class="photos">
          {% for t in a.thumbs %}<img src="{{ t }}" alt="Site photo">{% endfor %}
          {% if a.photos_more %}<span class="more">+ {{ a.photos_more }} more</span>{% endif %}
        </div>{% endif %}
      </div>
      {% else %}
      <div class="empty">No activities logged for this date.</div>
      {% endfor %}
    </div>
  </div>
  {% endif %}
  </div>
  <div class="side">
    <div class="section">
      <div class="section-title">Manpower</div>
      {% set rows = data.trades if data.trades else [] %}
      {% if data.trades %}
        {% set top = data.trades|map(attribute="headcount")|max %}
        <div class="bars">
        {% for t in data.trades %}
          <div class="bar"><div class="lbl"><span>{{ t.trade }}</span><b>{{ t.headcount }}</b></div>
            <div class="track"><div class="fill" style="width: {{ (100 * t.headcount / (top or 1))|round|int }}%"></div></div></div>
        {% endfor %}
        </div>
      {% elif data.headcount and data.is_project %}
        {% set top = data.sites|map(attribute="headcount")|max %}
        <div class="bars">
        {% for st in data.sites if st.headcount %}
          <div class="bar"><div class="lbl"><span>{{ st.site_name }}</span><b>{{ st.headcount }}</b></div>
            <div class="track"><div class="fill" style="width: {{ (100 * st.headcount / (top or 1))|round|int }}%"></div></div></div>
        {% endfor %}
        </div>
      {% elif not data.headcount %}
        <div class="empty">No attendance recorded for this date.</div>
      {% endif %}
      {% if data.headcount %}
      <div class="total"><span class="t">On site</span><span class="n">{{ data.headcount }}</span></div>
      {% if data.labour_cost_label %}<div class="cost">Labour cost {{ data.labour_cost_label }}</div>{% endif %}
      {% endif %}
    </div>

    {% if data.tomorrow_plan %}
    <div class="section">
      <div class="section-title">Tomorrow's Plan</div>
      <div class="plan">{{ data.tomorrow_plan|e }}</div>
    </div>
    {% endif %}


  </div>
  </div>

  <div class="full">
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
          <td class="muted">{{ m.unit }}</td></tr>
        {% else %}
        <tr><td colspan="4" class="muted"><i>No material movements recorded for this date.</i></td></tr>
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
    <div class="cards{{ ' issues' if data.issues|length > 1 }}">
      {% for i in data.issues %}
      {% set st = i.status|lower|replace(' ', '-') %}
      <div class="card st-{{ 'open' if st in ('open', 'acknowledged') and i.severity|lower in ('critical', 'high') else st }}">
        <div class="row">
          <div class="what"><span class="sev severity-{{ i.severity|lower }}">{{ i.severity }}</span> {{ i.issue_type }}{% if data.is_project %} <span class="muted">· {{ i.site_name }}</span>{% endif %}</div>
          <span class="pill st-{{ st }}">{{ i.status }}</span></div>
        <div class="detail">{{ i.narrative }}{% if i.since %}<span class="muted"> · reported {{ i.since }}</span>{% endif %}</div>
      </div>
      {% else %}
      <div class="empty">No issues reported for this date.</div>
      {% endfor %}
    </div>
  </div>

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
  </div>

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
    from channel.receipt.template import _font_css

    return _document_template.render(
        data=data, lh=letterhead, ink=_INK, sub=_SUB, line=_LINE, accent=accent, warn=_WARN,
        day=_day_parts(data.report_date), fonts=_font_css(),
    )


def _day_parts(report_date: str) -> dict[str, str]:
    """The date block: "15", "Nov 2026", "Sunday"; the raw text when it is not a date."""
    import datetime

    try:
        d = datetime.date.fromisoformat(str(report_date)[:10])
    except ValueError:
        return {"num": "", "month": str(report_date), "weekday": ""}
    return {"num": str(d.day), "month": f"{d:%b %Y}", "weekday": f"{d:%A}"}
