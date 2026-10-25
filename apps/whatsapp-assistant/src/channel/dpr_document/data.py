"""Maps a DPR version's `payload` JSONB (backend/.../dpr.py's assembled
dict) into the shape template.py renders. Pure, no I/O -- mirrors
channel/receipt/data.py's split between data-shaping and layout.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from trade_label import trade_label


@dataclass(frozen=True, slots=True)
class DprActivityRow:
    work_type: str
    narrative: str
    status: str
    contractor: str
    quantities: str
    evidence_count: int
    # BE-11: repeats an earlier work item of the day. Absent before BE-11.
    possible_duplicate: bool = False
    #: WRK-01: work started on an earlier day and updated on this one -- the
    #: day it was started, "20 Oct". Empty for the day's own work.
    continued_from: str = ""


@dataclass(frozen=True, slots=True)
class DprIssueRow:
    issue_type: str
    severity: str
    narrative: str
    status: str
    # Only populated at project level (ADR-D9/P8's roll-up tags each issue
    # with the site it came from); "—" for a SITE report, where it's
    # already implied by the whole document.
    site_name: str = "—"
    #: BE-51: an issue reported on an earlier day and still open (or closed
    #: on this one) -- the day it was reported, "12 Oct". Empty for the day's
    #: own issues.
    since: str = ""


@dataclass(frozen=True, slots=True)
class DprTradeRow:
    trade: str
    headcount: int


@dataclass(frozen=True, slots=True)
class DprMaterialRow:
    material_name: str
    received: str
    used: str
    unit: str
    # BE-12: stock after the day, and whether more was used than the site is
    # known to hold. Absent from reports stored before BE-12.
    closing: str | None = None
    beyond_stock: bool = False


@dataclass(frozen=True, slots=True)
class DprSiteRow:
    site_name: str
    reported: bool
    activity_count: int
    open_issue_count: int
    headcount: int


@dataclass(frozen=True, slots=True)
class DprLateEntryRow:
    """An earlier day's entry that arrived after that day was confirmed (BE-13)."""

    report_date: str
    summary: str


@dataclass(frozen=True, slots=True)
class DprDocumentData:
    code: str
    project_name: str
    site_name: str
    report_date: str
    is_project: bool = False
    activities: list[DprActivityRow] = field(default_factory=list)
    issues: list[DprIssueRow] = field(default_factory=list)
    activity_count: int = 0
    open_issue_count: int = 0
    evidence_count: int = 0
    trades: list[DprTradeRow] = field(default_factory=list)
    headcount: int = 0
    labour_cost: str = "0"
    materials: list[DprMaterialRow] = field(default_factory=list)
    sites: list[DprSiteRow] = field(default_factory=list)
    reported_site_count: int = 0
    total_site_count: int = 0
    # Site conditions (BE-14); "Not set" when the engineer gave none.
    weather: str = "Not set"
    site_working: str = "Not set"
    hours_lost: str = "—"
    tomorrow_plan: str = ""
    late_entries: list[DprLateEntryRow] = field(default_factory=list)
    # BE-18: the version's AI summary of its confirmed facts; "" for none.
    summary: str = ""
    # WEB-27: the date as people say it ("Friday, 24 October 2026"), and the
    # labour cost in rupees ("₹14,400"), "" when there is none to show.
    date_label: str = ""
    labour_cost_label: str = ""


_WEATHER_LABELS = {
    "sunny": "Sunny",
    "cloudy": "Cloudy",
    "rainy": "Rain",
    "windy": "Windy",
    "extreme_heat": "Extreme heat",
}
_SITE_WORKING_LABELS = {"full": "Full day", "half": "Half day", "none": "No work"}


def _pretty(label: object) -> str:
    """``SLAB_SHUTTERING`` -> ``Slab Shuttering``; a word that starts with a
    digit stays lower case (``5th``, not str.title()'s ``5Th``)."""
    if not label:
        return "—"
    return " ".join(
        w.capitalize() if w[:1].isalpha() else w.lower()
        for w in str(label).replace("_", " ").split()
    )


def _number(value: object) -> str:
    """``180.000`` -> ``180``, ``2.400`` -> ``2.4``: quantities come from a
    NUMERIC column and carry its scale."""
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    text = format(n.normalize(), "f")
    return text if text != "-0" else "0"


def _quantities_text(quantities: list[dict[str, Any]]) -> str:
    if not quantities:
        return "—"
    parts = []
    for q in quantities:
        work = q.get("work_type")
        part = f"{_number(q.get('quantity'))} {q.get('unit') or ''}".strip()
        parts.append(f"{part} {_pretty(work)}" if work else part)
    return ", ".join(parts)


def _rupees(value: object) -> str:
    """``14400`` -> ``₹14,400`` (Indian grouping: ``₹1,23,456``); "" for none."""
    try:
        n = Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return ""
    if n <= 0:
        return ""
    whole, _, frac = format(n.quantize(Decimal("0.01")), "f").partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    text = ",".join([*groups, tail])
    return f"₹{text}" + (f".{frac}" if frac != "00" else "")


def _date_label(value: object) -> str:
    try:
        day = datetime.date.fromisoformat(str(value))
    except ValueError:
        return str(value or "—")
    return f"{day:%A}, {day.day} {day:%B %Y}"


def _short_day(value: object) -> str:
    """"2026-10-12" -> "12 Oct"; empty when there is no day."""
    import datetime

    try:
        day = datetime.date.fromisoformat(str(value or ""))
    except ValueError:
        return ""
    return f"{day.day} {day:%b}"


def build_document_data(
    *, code: str, payload: dict[str, Any], summary: str | None = None
) -> DprDocumentData:
    """Shape an assembled DPR payload (see backend/.../dpr.py's
    `assemble_site_report_payload`) into what the template renders. Missing
    fields degrade to placeholders rather than raising -- a partially-filled
    payload should still render a readable, honest document."""
    activities = [
        DprActivityRow(
            work_type=_pretty(a.get("work_type")),
            narrative=a.get("narrative") or "—",
            status=_pretty(a.get("status")),
            contractor=a.get("contractor") or "—",
            quantities=_quantities_text(a.get("quantities") or []),
            evidence_count=int(a.get("evidence_count") or 0),
            possible_duplicate=bool(a.get("possible_duplicate")),
            continued_from=_short_day(a.get("started_on")) if a.get("continued") else "",
        )
        for a in payload.get("activities", [])
    ]
    is_project = payload.get("level") == "PROJECT"
    issues = [
        DprIssueRow(
            issue_type=_pretty(i.get("issue_type")),
            severity=_pretty(i.get("severity")),
            narrative=i.get("narrative") or "—",
            status=_pretty(i.get("status")),
            site_name=_pretty(i.get("site_name")) if is_project else "—",
            since=_short_day(i.get("reported_on")),
        )
        # A project payload already holds its sites' earlier issues in
        # `issues` (assembly.build_project_report_payload).
        for i in [*payload.get("issues", []), *payload.get("carried_issues", [])]
    ]
    labour = payload.get("labour") or {}
    trades = [
        DprTradeRow(trade=trade_label(t.get("trade")) or "—", headcount=int(t.get("headcount") or 0))
        for t in labour.get("trades", [])
    ]
    materials = [
        DprMaterialRow(
            material_name=_pretty(m.get("material_name")),
            received=str(m.get("received") or "0"),
            used=str(m.get("used") or "0"),
            unit=m.get("unit") or "—",
            closing=m.get("closing"),
            beyond_stock=bool(m.get("beyond_stock")),
        )
        for m in payload.get("materials", [])
    ]
    sites = [
        DprSiteRow(
            site_name=_pretty(s.get("site_name")),
            reported=bool(s.get("reported")),
            activity_count=int(s.get("activity_count") or 0),
            open_issue_count=int(s.get("open_issue_count") or 0),
            headcount=int(s.get("headcount") or 0),
        )
        for s in payload.get("sites", [])
    ]
    conditions = payload.get("conditions") or {}
    hours_lost = conditions.get("hours_lost")
    return DprDocumentData(
        summary=(summary or "").strip(),
        date_label=_date_label(payload.get("report_date")),
        labour_cost_label=_rupees(labour.get("total_cost")),
        weather=_WEATHER_LABELS.get(conditions.get("weather") or "", "Not set"),
        site_working=_SITE_WORKING_LABELS.get(conditions.get("site_working") or "", "Not set"),
        hours_lost=f"{hours_lost} h" if hours_lost is not None else "—",
        tomorrow_plan=conditions.get("tomorrow_plan") or "",
        late_entries=[
            DprLateEntryRow(
                report_date=str(e.get("report_date") or "—"), summary=str(e.get("summary") or "—")
            )
            for e in payload.get("late_entries") or []
        ],
        code=code,
        project_name=payload.get("project_name") or "—",
        site_name=payload.get("site_name") or "—",
        report_date=payload.get("report_date") or "—",
        is_project=is_project,
        activities=activities,
        issues=issues,
        activity_count=int(payload.get("activity_count") or len(activities)),
        open_issue_count=int(payload.get("open_issue_count") or 0),
        evidence_count=int(payload.get("evidence_count") or 0),
        trades=trades,
        headcount=int(labour.get("headcount") or 0),
        labour_cost=str(labour.get("total_cost") or "0"),
        materials=materials,
        sites=sites,
        reported_site_count=int(payload.get("reported_site_count") or 0),
        total_site_count=int(payload.get("total_site_count") or len(sites)),
    )
