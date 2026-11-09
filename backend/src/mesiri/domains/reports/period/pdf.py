"""The period report as a PDF (PRC-19, D-R3), fpdf2 as the DPR PDF.

Page 1 is the whole story for someone who reads nothing else: the company's letterhead, the headline, four
figures, one row per area, up to four approved photos. The sections follow from page 2. It renders what
``engine.build`` returned and computes nothing of its own.

The core PDF fonts are Latin-1 only: rupees print as "Rs" and other characters are replaced (the DPR PDF's rule).
fpdf2 is imported lazily so the core test suite runs without it.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from mesiri.domains.dpr.pdf import _latin1

logger = logging.getLogger(__name__)

PAGE_PHOTOS = 4
PAGE_NEEDS = 5
_W = 180  # A4 minus 15 mm margins
INK = (26, 29, 33)
MUTED = (91, 97, 104)
LINE = (229, 231, 235)
SOFT = (246, 246, 243)
YELLOW = (250, 204, 21)
TONE = {"good": (15, 81, 50), "warn": (154, 62, 11), "bad": (180, 35, 24), "none": (107, 113, 120),
        "info": (30, 58, 138)}
_TITLE = {"week": "Weekly report", "month": "Monthly report", "custom": "Report"}


def t(text: Any) -> str:
    """Text for the core fonts: rupees as Rs, arrows as words, the rest Latin-1."""
    s = "" if text is None else str(text)
    s = s.replace("₹", "Rs ").replace("▲", "up").replace("▼", "down").replace("—", "-").replace("·", "-")
    return _latin1(s)


async def photo_bytes(storage: Any, photos: dict | None) -> list[tuple[dict, bytes]]:
    """The first photos' bytes from storage (page 1 shows ``PAGE_PHOTOS``); a photo that cannot be read is skipped."""
    out: list[tuple[dict, bytes]] = []
    if not storage or not photos:
        return out
    for row in photos["rows"][:PAGE_PHOTOS]:
        try:
            obj = await storage.get_object(row["_key"])
            if obj.data:
                out.append((row, bytes(obj.data)))
        except Exception:  # noqa: BLE001 -- a report prints without a photo rather than fail
            logger.warning("period_report.photo_unreadable key=%s", row.get("_key"))
    return out


def render(report: dict[str, Any], company: dict[str, Any], images: list[tuple[dict, bytes]] | None = None) -> bytes:
    from fpdf import FPDF

    generated = report["generated_at"][:16].replace("T", " ")

    class Doc(FPDF):
        def footer(self) -> None:
            self.set_y(-12)
            self.set_font("Helvetica", "", 7)
            self.set_text_color(*MUTED)
            self.cell(_W / 2, 5, t(f"Made from Mesiri on {generated} UTC; figures as recorded then."))
            self.cell(_W / 2, 5, f"Page {self.page_no()} of {{nb}}", align="R")

    pdf = Doc(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(15, 14, 15)
    pdf.add_page()
    _letterhead(pdf, company)
    _title(pdf, report)
    _headline(pdf, report["headline"])
    _kpis(pdf, report["kpis"][:4])
    _areas(pdf, report["areas"])
    _needs_first(pdf, report["needs_you"][:PAGE_NEEDS])
    _photos(pdf, images or [])

    s = report["sections"]
    pdf.add_page()
    if "work" in s:
        _work(pdf, s["work"])
    if "schedule" in s and s["schedule"]["rows"]:
        _schedule(pdf, s["schedule"])
    if "labour" in s:
        _labour(pdf, s["labour"], report.get("sees_money"))
    if "materials" in s and s["materials"]["rows"]:
        _materials(pdf, s["materials"], report.get("sees_money"))
    if "money" in s:
        _money(pdf, s["money"])
    if "issues" in s:
        _issues(pdf, s["issues"])
    if "completeness" in s:
        _completeness(pdf, s["completeness"])
    if len(report["needs_you"]) > PAGE_NEEDS:
        _needs(pdf, report["needs_you"])
    return bytes(pdf.output())


# -- page 1 -----------------------------------------------------------------------------------------------------------

def _letterhead(pdf, company: dict[str, Any]) -> None:
    name = company.get("letterhead_name") or company.get("company_name") or ""
    top = pdf.get_y()
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*INK)
    pdf.cell(_W * 0.6, 7, t(name))
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(*MUTED)
    right = [x for x in (f"GSTIN {company['gstin']}" if company.get("gstin") else None, company.get("phone"),
                         company.get("address")) if x]
    pdf.set_xy(15 + _W * 0.6, top)
    pdf.multi_cell(_W * 0.4, 3.6, t("\n".join(right)), align="R")
    pdf.set_y(max(pdf.get_y(), top + 8))
    pdf.set_draw_color(*INK)
    pdf.set_line_width(0.5)
    pdf.line(15, pdf.get_y() + 1, 15 + _W, pdf.get_y() + 1)
    pdf.set_line_width(0.2)
    pdf.ln(4)


def _title(pdf, report: dict[str, Any]) -> None:
    p = report["period"]
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    sub = f"{_TITLE[p['kind']]}: " + (f"{p['label']}, {p['range']}" if p["kind"] != "custom" else p["range"])
    if report.get("running"):
        sub += " (so far)"
    pdf.cell(0, 5, t(sub), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*INK)
    where = report["project"]["name"] + (f" - {report['site']['name']}" if report.get("site") else "")
    pdf.cell(0, 8, t(where), new_x="LMARGIN", new_y="NEXT")
    if report["project"].get("client"):
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 4.5, t(f"Client: {report['project']['client']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def _headline(pdf, h: dict[str, Any]) -> None:
    text = " ".join([h["lead"], *h["facts"]])
    pdf.set_font("Helvetica", "", 10)
    lines = pdf.multi_cell(_W - 8, 5, t(text), dry_run=True, output="LINES")
    height = 5 * len(lines) + 6
    y = pdf.get_y()
    pdf.set_fill_color(*SOFT)
    pdf.rect(15, y, _W, height, style="F")
    pdf.set_fill_color(*YELLOW)
    pdf.rect(15, y, 1.4, height, style="F")
    pdf.set_xy(19, y + 3)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 10)
    pdf.write(5, t(h["lead"] + " "))
    pdf.set_font("Helvetica", "", 10)
    pdf.set_left_margin(19)
    pdf.set_right_margin(19)
    pdf.write(5, t(" ".join(h["facts"])))
    pdf.set_left_margin(15)
    pdf.set_right_margin(15)
    pdf.set_y(y + height + 4)


def _kpis(pdf, kpis: list[dict[str, Any]]) -> None:
    if not kpis:
        return
    gap = 3
    w = (_W - gap * (len(kpis) - 1)) / len(kpis)
    y = pdf.get_y()
    for i, k in enumerate(kpis):
        x = 15 + i * (w + gap)
        pdf.set_draw_color(*LINE)
        pdf.rect(x, y, w, 19)
        pdf.set_xy(x + 2.5, y + 2)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(w - 5, 4, t(k["label"]))
        pdf.set_xy(x + 2.5, y + 6.5)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*INK)
        pdf.cell(w - 5, 6, t(k["value"]))
        pdf.set_xy(x + 2.5, y + 13)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(*TONE.get(k.get("tone") or "none", MUTED) if k.get("tone") != "none" else MUTED)
        pdf.cell(w - 5, 4, t(k.get("note") or ""))
    pdf.set_y(y + 23)


def _areas(pdf, areas: list[dict[str, Any]]) -> None:
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(*MUTED)
    widths = (30, 28, _W - 58)
    for head, w in zip(("Area", "Status", "In short"), widths, strict=True):
        pdf.cell(w, 5, head)
    pdf.ln(5)
    pdf.set_draw_color(*LINE)
    for a in areas:
        y = pdf.get_y()
        pdf.line(15, y, 15 + _W, y)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*INK)
        pdf.set_xy(15, y + 1)
        pdf.cell(widths[0], 5, t(a["title"].replace("Is the data complete?", "Data")))
        colour = TONE.get(a["status"], MUTED)
        pdf.set_fill_color(*colour)
        pdf.ellipse(15 + widths[0], y + 2.6, 2, 2, style="F")
        pdf.set_text_color(*colour)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_xy(15 + widths[0] + 3, y + 1)
        pdf.cell(widths[1] - 3, 5, t(a["word"]))
        pdf.set_text_color(*INK)
        pdf.set_xy(15 + widths[0] + widths[1], y + 1)
        pdf.multi_cell(widths[2], 5, t(a["note"]))
        pdf.set_y(max(pdf.get_y(), y + 7))
    pdf.ln(3)


def _needs_first(pdf, items: list[dict[str, Any]]) -> None:
    """Page 1's "Needs you": the worst few, a coloured mark each."""
    if not items:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, "Needs you", new_x="LMARGIN", new_y="NEXT")
    for n in items:
        y = pdf.get_y()
        pdf.set_fill_color(*TONE.get(n["level"], MUTED))
        pdf.rect(15, y + 0.8, 1.2, 4.4, style="F")
        pdf.set_xy(18, y)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*INK)
        title = t(n["title"])
        pdf.cell(pdf.get_string_width(title) + 2, 6, title)
        if n.get("detail"):
            pdf.set_text_color(*MUTED)
            pdf.set_font("Helvetica", "", 7.5)
            pdf.cell(0, 6, t(n["detail"])[:110])
        pdf.ln(6)
    pdf.ln(3)


def _photos(pdf, images: list[tuple[dict, bytes]]) -> None:
    if not images:
        return
    gap, n = 3, PAGE_PHOTOS
    w = (_W - gap * (n - 1)) / n
    h = w * 0.75
    if pdf.get_y() + h + 10 > pdf.h - 16:
        return  # page 1 only: the photos never push the page over
    y = pdf.get_y()
    shown = 0
    for i, (row, data) in enumerate(images[:n]):
        x = 15 + i * (w + gap)
        try:
            pdf.image(io.BytesIO(data), x=x, y=y, w=w, h=h, keep_aspect_ratio=True)
        except Exception:  # noqa: BLE001 -- a format fpdf cannot read: leave the space empty
            logger.warning("period_report.photo_not_rendered")
            continue
        shown += 1
        pdf.set_xy(x, y + h + 0.5)
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(*MUTED)
        cap = row.get("caption") or row.get("work") or ""
        pdf.multi_cell(w, 3, t(f"{_short_day(row.get('date'))} {cap}".strip()[:70]))
    if shown:
        pdf.set_y(y + h + 8)


def _short_day(iso: str | None) -> str:
    import datetime

    if not iso:
        return ""
    d = datetime.date.fromisoformat(iso[:10])
    return f"{d.day} {d:%b}"


# -- detail pages -----------------------------------------------------------------------------------------------------

def _heading(pdf, text: str, note: str | None = None) -> None:
    if pdf.get_y() > pdf.h - 50:
        pdf.add_page()
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*INK)
    pdf.cell(0, 7, t(text), new_x="LMARGIN", new_y="NEXT")
    if note:
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(0, 4.5, t(note), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _table(pdf, header: list[str], rows: list[list[Any]], widths: list[float], empty: str = "Nothing recorded.",
           align: str = "") -> None:
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(*MUTED)
    pdf.set_fill_color(*SOFT)
    for i, (head, w) in enumerate(zip(header, widths, strict=True)):
        pdf.cell(w, 6, t(head), fill=True, align="R" if align and align[i] == "R" else "L")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*INK)
    pdf.set_draw_color(*LINE)
    if not rows:
        pdf.set_text_color(*MUTED)
        pdf.cell(sum(widths), 6, t(empty), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*INK)
        return
    for row in rows:
        if pdf.get_y() > pdf.h - 22:
            pdf.add_page()
        y = pdf.get_y()
        for i, (value, w) in enumerate(zip(row, widths, strict=True)):
            text = t(value)
            while pdf.get_string_width(text) > w - 1.5 and len(text) > 3:
                text = text[:-4] + "..."
            pdf.cell(w, 5.5, text, align="R" if align and align[i] == "R" else "L")
        pdf.ln(5.5)
        pdf.line(15, y + 5.5, 15 + sum(widths), y + 5.5)
    pdf.ln(2)


def _state(state: str | None) -> str:
    return {"late": "Late", "behind": "Behind", "on_track": "On track", "not_started": "Not started", "done": "Done",
            "unscheduled": "No dates"}.get(state or "", state or "")


def _work(pdf, w: dict[str, Any]) -> None:
    note = (f"{w['done_pct'] or 0}% of the job done this period" +
            (f" against {w['plan_pct']}% planned" if w.get("plan_pct") is not None else "") +
            f". {w['progress_to_date'] or 0}% done to date" +
            (f", {w['expected_to_date']}% expected by now." if w.get("expected_to_date") is not None else "."))
    if w.get("work_in_other_unit"):
        note += f" {w['work_in_other_unit']} record(s) in another unit are not added in."
    _heading(pdf, "Work", note)
    rows = [[r["activity"], r.get("site") or "", "; ".join(f"{d['quantity']} {d['unit']} {d['work']}"
                                                           for d in r["done_in_period"]) or "-",
             f"{r['progress'] if r['progress'] is not None else '-'}%",
             f"{r['expected']}%" if r.get("expected") is not None else "-", _state(r["state"])] for r in w["rows"]]
    _table(pdf, ["Activity", "Site", "Done this period", "To date", "Plan", "Status"], rows, [42, 24, 62, 16, 14, 22],
           align="LLLRRL")


def _schedule(pdf, s: dict[str, Any]) -> None:
    note = (f"Forecast finish {_short_day(s.get('forecast_finish'))}" if s.get("forecast_finish") else "No forecast") + \
           (f", {s['slip_days']} days after plan." if s.get("slip_days") else ", on plan.")
    _heading(pdf, "Late or behind", note)
    rows = [[r["activity"] + (" *" if r["critical"] else ""), r.get("site") or "", _state(r["state"]),
             str(r["days_late"] or r["slip_days"]), _short_day(r.get("forecast_end")), r.get("assigned_to") or ""]
            for r in s["rows"][:20]]
    _table(pdf, ["Activity (* critical path)", "Site", "State", "Days", "Now ends", "Who"], rows,
           [58, 28, 22, 14, 22, 36], align="LLLRLL")


def _labour(pdf, lb: dict[str, Any], money: bool | None) -> None:
    note = f"{lb['man_days']} man-days ({lb['prev_man_days']} last period)" + \
           (f"; wages {t(_inr(lb['wages']))}." if money and lb.get("wages") is not None else ".")
    _heading(pdf, "Labour", note)
    head = ["Trade", "Man-days"] + (["Wages"] if money else [])
    rows = [[r["label"], r["man_days"]] + ([_inr(r.get("wages"))] if money else []) for r in lb["by_trade"]]
    _table(pdf, head, rows, [70, 30] + ([40] if money else []), align="LRR")
    days = [[f"{_short_day(d['date'])}", d["man_days"]] + ([_inr(d.get("wages"))] if money else [])
            for d in lb["by_day"]]
    if len(days) <= 31:
        _table(pdf, ["Day", "Man-days"] + (["Wages"] if money else []), days, [70, 30] + ([40] if money else []),
               align="LRR")


def _materials(pdf, m: dict[str, Any], money: bool | None) -> None:
    _heading(pdf, "Materials", f"{m['received_items']} received, {m['used_items']} used, {m['running_low']} running low.")
    rows = [[r["material"], r.get("site") or "", r["received"], r["used"], r["closing"], r["unit"],
             str(r["days_left"]) if r.get("days_left") is not None else "-", "Low" if r["running_low"] else ""]
            + ([_inr(r.get("spend"))] if money else []) for r in m["rows"][:40]]
    head = ["Material", "Site", "In", "Used", "Left", "Unit", "Days", ""] + (["Spend"] if money else [])
    widths = [46, 26, 16, 16, 16, 14, 12, 10] + ([24] if money else [])
    _table(pdf, head, rows, widths, align="LLRRRLRLR")


def _money(pdf, mo: dict[str, Any]) -> None:
    _heading(pdf, "Money", f"Spent {t(_inr(mo['spent']))} ({t(_inr(mo['prev_spent']))} last period).")
    _table(pdf, ["Where it went", "Amount"], [[c["label"], _inr(c["amount"])] for c in mo["centres"]], [70, 40],
           align="LR")
    if mo.get("worst_lines"):
        _table(pdf, ["Line (labour against work done)", "Done", "Labour", "Earned", "Difference"],
               [[f"{ln['work']}", f"{ln['done_quantity']} {ln['unit']}", _inr(ln["labour_cost"]),
                 _inr(ln["earned_labour"]), _inr(ln["difference"])] for ln in mo["worst_lines"]],
               [70, 28, 27, 27, 28], align="LRRRR")
    if "billed" in mo:
        _table(pdf, ["Client bills", "Amount"],
               [["Billed in the period", _inr(mo["billed"])], ["Received in the period", _inr(mo["received"])],
                ["Owed by the client now", _inr(mo["owed"])], ["Of it, over 30 days", _inr(mo["overdue"])]],
               [70, 40], align="LR")


def _issues(pdf, i: dict[str, Any]) -> None:
    _heading(pdf, "Issues", f"{i['raised']} raised, {i['closed']} closed, {i['open']} still open.")
    rows = [[r["type"].replace("_", " ").capitalize(), r["severity"].capitalize(), r.get("what") or "",
             r.get("site") or "", str(r["days_open"])] for r in i["rows"]]
    _table(pdf, ["Type", "Severity", "What", "Site", "Days open"], rows, [30, 20, 82, 28, 20], empty="Nothing open.",
           align="LLLLR")


def _completeness(pdf, c: dict[str, Any]) -> None:
    _heading(pdf, "Is the data complete?",
             f"{c['days_full']} of {c['days_total']} days with every site report confirmed.")
    rows = [[f"{d['weekday']} {_short_day(d['date'])}", f"{d['reports']} of {d['sites']}",
             f"{d['attendance']} of {d['sites']}", d.get("weather") or ""] for d in c["days"]]
    _table(pdf, ["Day", "Site reports confirmed", "Attendance", "Weather"], rows, [40, 45, 45, 50], align="LRRL")


def _needs(pdf, items: list[dict[str, Any]]) -> None:
    _heading(pdf, "Needs you")
    _table(pdf, ["", "What", "Detail"], [[{"bad": "!", "warn": "-", "info": ""}[n["level"]], n["title"],
                                         n.get("detail") or ""] for n in items[:20]], [6, 92, 82])


def _inr(v: Any) -> str:
    from mesiri.domains.reports.period.headline import inr

    return t(inr(v)) if v is not None else "-"
