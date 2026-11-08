"""Structural drawings (DR-09): the schedules a structural set prints, the foundation's quantities, and the checks
between sheets. Pure: works on ``pdf_text.pages`` word lists with each page's ``reader.sheet``.

What a Kerala structural consultant's set prints, and what is read from it:

- **Design notes:** grade of concrete (M20) and steel (Fe 500), safe bearing capacity, the floors it is designed for
  (B+G+2), clear covers, the PCC offset.
- **Footing schedule:** a table row per footing type: ``F1 250X250 70 20 16 nos. 16 dia bars 16 nos. 16 dia bars``
  (size A x B, depth D at the column, edge thickness C, main and distribution bars).
- **Footing plan:** every footing's mark and size where it sits (``F1-250X250``) and the column on it (``C3``); so the
  number of each footing type, and which column each carries, are counted, not typed.
- **Combined footings:** a footing on the plan that is not in the schedule but has its own detail
  (``F6 COMBINED FOOTING``): size from the plan, depth and bars (``14 nos-16 dia``) from the detail.
- **Column schedule:** ``COLUMN - C1`` panels with their size, ``REINF: 4 T25+8 T20`` and ``TIES: T8 @ 20 CM C/C``.
- **Slab schedules** per floor: ``S1 ONE WAY 13cm 10 @ 15 cm C/C 8 @ 20 cm C/C``.

**Quantities** (``takeoff``), every figure with how it was worked out:

- Footing concrete: the base slab (A x B x C) plus the sloped part as a frustum from A x B up to the column plus
  ``OFFSET_CM`` on each side (the prismoidal formula). A footing whose column size is not known is taken as a flat
  block A x B x D (more than it is), and says so.
- PCC under each footing: (A + 2 x offset) x (B + 2 x offset) x ``PCC_CM``.
- Footing steel: each bar is the footing's size less the cover at both ends, plus an upturn at each end of the edge
  thickness less the covers; kg = length x d² / 162.
- Column steel per metre of height (bars + ties) for each column type and for all the columns on the footing plan:
  the floor heights are not on these sheets, so totals per floor are left to the person.
- Cement: M20 at ``CEMENT_BAGS["M20"]`` bags a cubic metre, PCC 1:4:8 at ``CEMENT_BAGS["1:4:8"]``.

Nothing here is a design check: a structural engineer designs and checks; this reads what was drawn and adds it up.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any

from mesiri.domains.drawings.reader import lines

#: The slope of a footing starts this far outside the column face (the usual detail; the set says it when drawn).
OFFSET_CM = 10.0
#: PCC under footings: thickness and the offset beyond the footing on each side (unless the notes say otherwise).
PCC_CM = 10.0
PCC_OFFSET_CM = 10.0
#: Clear covers used when the notes do not give them (mm).
COVER_MM = {"footing": 50.0, "column": 40.0}
#: Bags of cement (50 kg) per cubic metre of concrete, nominal mixes.
CEMENT_BAGS = {"M15": 6.3, "M20": 8.0, "M25": 8.6, "1:4:8": 3.4, "1:3:6": 4.4}

_FOOTING_ROW = re.compile(
    r"\b(F\d{1,2}[A-Z]?)\s+(\d{2,4})\s*[X×x]\s*(\d{2,4})\s+(\d{2,3})\s+(\d{1,3})\s+(\d{1,3})\s*nos\.?\s*(\d{1,2})\s*"
    r"(?:mm\s*)?(?:dia|ø|φ|#)\.?\s*(?:bars?)?\s*(\d{1,3})\s*nos\.?\s*(\d{1,2})\s*(?:mm\s*)?(?:dia|ø|φ|#)", re.I)
_FOOTING_MARK = re.compile(r"^(F\d{1,2}[A-Z]?)\s*-\s*(\d{2,4})\s*[X×x]\s*(\d{2,4})$")
_COLUMN_MARK = re.compile(r"^(C\d{1,2}[A-Z]?)$")
_COLUMN_SIZED = re.compile(r"^(C\d{1,2}[A-Z]?)\s*-\s*(\d{2,3})\s*[X×x]\s*(\d{2,3})$")
_BARS = re.compile(r"(\d{1,2})\s*[-\s]?\s*[T#Yy](\d{1,2})\b")
_TIES = re.compile(r"T(\d{1,2})\s*@\s*(\d{1,3})\s*(?:CM|cm)", re.I)
_SLAB_ROW = re.compile(
    r"\b(S\d{1,2})\s+(ONE\s*WAY|TWO\s*WAY|DOUBLE\s*MESH|CANTILEVER)\s+(\d{1,2})\s*cm\s+(\d{1,2})\s*@\s*(\d{1,3})\s*"
    r"cm\s*C/?C\s+(\d{1,2})\s*@\s*(\d{1,3})\s*cm", re.I)
_NOS_DIA = re.compile(r"(\d{1,3})\s*nos\.?\s*-?\s*(\d{1,2})\s*(?:mm\s*)?dia", re.I)


def kg_per_m(dia_mm: float) -> float:
    """Weight of a steel bar per metre: d² / 162."""
    return dia_mm * dia_mm / 162.0


def _rows(page: Mapping[str, Any]) -> list[list[Mapping[str, Any]]]:
    return lines(page["words"])


def _text(row: list[Mapping[str, Any]]) -> str:
    return " ".join(w["text"] for w in row)


def notes(pages: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Design notes printed on the sheets: grades, SBC, floors designed for, covers, PCC offset."""
    text = " ".join(_text(r) for p in pages for r in _rows(p))
    out: dict[str, Any] = {}
    if m := re.search(r"Grade\s+of\s+Concrete\s*:?\s*(M\s?\d{2})", text, re.I):
        out["concrete"] = m.group(1).replace(" ", "").upper()
    elif m := re.search(r"\bMix\s*:?\s*(M\s?\d{2})\b", text, re.I):
        out["concrete"] = m.group(1).replace(" ", "").upper()
    if m := re.search(r"Grade\s+of\s+Steel\s*:?\s*(Fe\s?\d{3})", text, re.I):
        out["steel"] = "Fe " + re.sub(r"\D", "", m.group(1))
    if m := re.search(r"SBC\s+(?:is\s+)?(?:taken\s+as\s+)?(\d{1,3})\s*(?:T|t/m)", text):
        out["sbc_t_per_sqm"] = int(m.group(1))
    if m := re.search(r"design(?:ed)?\s+(?:is\s+done\s+)?for\s+((?:B\s*\+\s*)?G\s*\+\s*\d+)", text, re.I):
        out["designed_for"] = m.group(1).replace(" ", "").upper()
    if m := re.search(r"Footing\s*-?\s*(\d{2,3})\s*mm", text, re.I):
        out["cover_footing_mm"] = float(m.group(1))
    if m := re.search(r"Column\s*-?\s*(\d{2,3})\s*mm", text, re.I):
        out["cover_column_mm"] = float(m.group(1))
    if m := re.search(r"Off\s*set\s+for\s+P\.?\s*C\.?\s*C\.?\s*:?\s*(\d{1,2})\s*cm", text, re.I):
        out["pcc_offset_cm"] = float(m.group(1))
    if m := re.search(r"P\.?\s*C\.?\s*C\.?\s*(1\s*:\s*\d\s*:\s*\d{1,2})", text, re.I):
        out["pcc_mix"] = m.group(1).replace(" ", "")
    return out


def footing_schedule(pages: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in pages:
        for row in _rows(p):
            for m in _FOOTING_ROW.finditer(_text(row)):
                mark = m.group(1).upper()
                out.setdefault(mark, {
                    "mark": mark, "a": int(m.group(2)), "b": int(m.group(3)), "d": int(m.group(4)),
                    "c": int(m.group(5)), "main": {"nos": int(m.group(6)), "dia": int(m.group(7))},
                    "dist": {"nos": int(m.group(8)), "dia": int(m.group(9))}, "page": p["number"]})
    return out


def _centre(w: Mapping[str, Any]) -> tuple[float, float]:
    return ((w["x0"] + w.get("x1", w["x0"])) / 2, w["top"])


def footing_plan(pages: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The page with the most footing marks (at least 3): each footing with its column, and every column mark."""
    best = None
    for p in pages:
        marks = [(w, m) for w in p["words"] if (m := _FOOTING_MARK.match(w["text"].strip()))]
        if len(marks) >= 3 and (best is None or len(marks) > len(best[1])):
            best = (p, marks)
    if best is None:
        return None
    page, marks = best
    columns = [w for w in page["words"] if _COLUMN_MARK.match(w["text"].strip())]
    footings = []
    for w, m in marks:
        fx, fy = _centre(w)
        # The column on a footing: the nearest column mark below the footing's label (drawn inside its outline).
        near = sorted(columns, key=lambda c: math.hypot(_centre(c)[0] - fx, _centre(c)[1] - fy))
        footings.append({"mark": m.group(1).upper(), "a": int(m.group(2)), "b": int(m.group(3)),
                         "column": near[0]["text"].strip().upper() if near else None,
                         "x": round(fx, 1), "y": round(fy, 1)})
    return {"page": page["number"], "footings": footings,
            "columns": [{"mark": c["text"].strip().upper(), "x": round(_centre(c)[0], 1), "y": round(_centre(c)[1], 1)}
                        for c in columns]}


def column_schedule(pages: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """``COLUMN - C1`` panels: size (the two dimension figures in the panel), bars and ties."""
    out: dict[str, dict[str, Any]] = {}
    for p in pages:
        rows = _rows(p)
        heads = []
        for row in rows:
            for i, w in enumerate(row):
                if w["text"].strip().upper() != "COLUMN":
                    continue
                for nxt in row[i + 1:i + 3]:
                    if _COLUMN_MARK.match(nxt["text"].strip().strip("-")):
                        heads.append({"mark": nxt["text"].strip().strip("-").upper(), "x": _centre(w)[0],
                                      "top": w["top"]})
                        break
        if not heads:
            continue
        reinf = [(w, row) for row in rows for w in row if w["text"].strip().upper().startswith("REINF")]
        ties = [(w, row) for row in rows for w in row if w["text"].strip().upper().startswith("TIES")]

        def owner(w: Mapping[str, Any], heads: list[dict[str, Any]] = heads) -> dict[str, Any] | None:
            above = [h for h in heads if h["top"] < w["top"]]
            if not above:
                return None
            return min(above, key=lambda h: (abs(h["x"] - _centre(w)[0]) // 40, w["top"] - h["top"]))

        def after(w: Mapping[str, Any], row: list[Mapping[str, Any]]) -> str:
            """The words after a "REINF:" / "TIES:" up to the next one on its row."""
            words, on = [], False
            for x in row:
                if x is w:
                    on = True
                    continue
                if on and x["text"].strip().upper().startswith(("REINF", "TIES")):
                    break
                if on:
                    words.append(x["text"])
            return " ".join(words)

        for w, row in reinf:
            h = owner(w)
            if h is None:
                continue
            bars = [{"nos": int(n), "dia": int(d)} for n, d in _BARS.findall(after(w, row))]
            if bars:
                out.setdefault(h["mark"], {"mark": h["mark"], "page": p["number"]})["bars"] = bars
        for w, row in ties:
            h = owner(w)
            if h is None:
                continue
            if m := _TIES.search(after(w, row)):
                out.setdefault(h["mark"], {"mark": h["mark"], "page": p["number"]})["ties"] = {
                    "dia": int(m.group(1)), "spacing_cm": int(m.group(2))}
        # The size: the dimension figures (15 to 150) in the panel, above the bars line.
        for h in heads:
            entry = out.get(h["mark"])
            if not entry:
                continue
            bars_top = min((w["top"] for w, _ in reinf if owner(w) is h), default=None)
            if bars_top is None:
                continue
            figures = [int(w["text"]) for row in rows for w in row
                       if w["text"].strip().isdigit() and 15 <= int(w["text"]) <= 150 and h["top"] < w["top"] < bars_top
                       and owner(w) is h]
            sizes = sorted(set(figures))
            if len(sizes) == 1:
                entry["size"] = [sizes[0], sizes[0]]
            elif len(sizes) == 2:
                entry["size"] = sizes
    return out


def combined_footings(pages: list[Mapping[str, Any]], plan: Mapping[str, Any] | None,
                      schedule: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Footings on the plan that are not in the schedule but have their own "COMBINED FOOTING" detail."""
    if not plan:
        return {}
    out: dict[str, dict[str, Any]] = {}
    marks = {f["mark"]: f for f in plan["footings"] if f["mark"] not in schedule}
    for p in pages:
        rows = _rows(p)
        text = [(_text(r), r) for r in rows]
        for mark, f in marks.items():
            idx = [i for i, (t, _) in enumerate(text) if re.search(rf"\b{mark}\b.*COMBINED\s+FOOTING", t, re.I)]
            if not idx:
                continue
            start, end = idx[0], idx[-1]
            # The section: from the plan's title to the section's title (bars, depth, the columns on it).
            section_rows = rows[start:end + 1] if end > start else rows[start:]
            bars = [{"nos": int(n), "dia": int(d)} for t in (_text(r) for r in section_rows)
                    for n, d in _NOS_DIA.findall(t)]
            cols = [m.group(1).upper() for r in section_rows for w in r if (m := _COLUMN_SIZED.match(w["text"]))]
            sized = {m.group(1).upper(): [int(m.group(2)), int(m.group(3))] for r in section_rows for w in r
                     if (m := _COLUMN_SIZED.match(w["text"]))}
            length, width = max(f["a"], f["b"]), min(f["a"], f["b"])
            depth = None
            for r in section_rows:
                nums = [int(w["text"]) for w in r if w["text"].isdigit()]
                if not nums or "PCC" in _text(r).upper() or _NOS_DIA.search(_text(r)):
                    continue  # the PCC's thickness, or a bar count ("22 nos-12 dia")
                if len(nums) > 1 and abs(sum(nums) - length) <= 3:
                    continue  # a chain of dimensions along the footing
                for n in nums:
                    if 20 <= n <= 150 and n not in (length, width):
                        depth = n
            out[mark] = {"mark": mark, "length": length, "width": width, "depth": depth, "bars": bars,
                         "columns_in_detail": cols, "column_sizes": sized, "page": p["number"]}
    return out


def slab_schedules(pages: list[Mapping[str, Any]], sheets: Mapping[int, Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in pages:
        for row in _rows(p):
            for m in _SLAB_ROW.finditer(_text(row)):
                kind = re.sub(r"\s+", " ", m.group(2).upper())
                main = {"dia": int(m.group(4)), "spacing_cm": int(m.group(5))}
                dist = {"dia": int(m.group(6)), "spacing_cm": int(m.group(7))}
                layers = 2 if kind == "DOUBLE MESH" else 1
                steel = layers * (kg_per_m(main["dia"]) * 100 / main["spacing_cm"]
                                  + kg_per_m(dist["dia"]) * 100 / dist["spacing_cm"])
                sheet = sheets.get(p["number"]) or {}
                floor = sheet.get("level") or re.sub(r"\s*DETAILS?$", "", sheet.get("title") or "").strip() or None
                out.append({"floor": floor, "page": p["number"], "mark": m.group(1).upper(),
                            "kind": kind.title(), "thickness_cm": int(m.group(3)), "main": main, "dist": dist,
                            "steel_kg_per_sqm": round(steel, 2), "concrete_cum_per_sqm": int(m.group(3)) / 100,
                            "basis": f"{'two layers of ' if layers == 2 else ''}main {main['dia']} mm @ "
                                     f"{main['spacing_cm']} cm + distribution {dist['dia']} mm @ "
                                     f"{dist['spacing_cm']} cm, per m² of slab"})
    return out


def _footing_concrete(a: float, b: float, d: float, c: float, col: list[int] | None) -> tuple[float, str]:
    """m³ of one sloped footing (cm in)."""
    a1 = a * b
    if col is None or d <= c:
        return a * b * d / 1e6, "flat block A×B×D (column size not known: a little more than drawn)"
    a2 = (col[0] + 2 * OFFSET_CM) * (col[1] + 2 * OFFSET_CM)
    vol = a1 * c + (d - c) / 3 * (a1 + a2 + math.sqrt(a1 * a2))
    return vol / 1e6, f"A×B×C + slope from A×B to the column + {OFFSET_CM:g} cm each side"


def takeoff(pages: list[Mapping[str, Any]], sheets: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Everything above for a set, or None when the set has no footing schedule, footing plan or column schedule."""
    by_page = {s["page"]: s for s in sheets}
    sched = footing_schedule(pages)
    plan = footing_plan(pages)
    cols = column_schedule(pages)
    if not (sched or plan or cols):
        return None
    info = notes(pages)
    combined = combined_footings(pages, plan, sched)
    slabs = slab_schedules(pages, by_page)
    cover_f = info.get("cover_footing_mm", COVER_MM["footing"]) / 10
    cover_c = info.get("cover_column_mm", COVER_MM["column"]) / 10
    pcc_off = info.get("pcc_offset_cm", PCC_OFFSET_CM)
    grade = info.get("concrete") or "M20"
    pcc_mix = info.get("pcc_mix") or "1:4:8"

    steel_by_dia: dict[int, float] = defaultdict(float)
    footings_out: list[dict[str, Any]] = []
    concrete = pcc = 0.0
    counts = Counter(f["mark"] for f in (plan or {}).get("footings", []))
    for mark, n in sorted(counts.items(), key=lambda kv: (len(kv[0]), kv[0])):
        on_plan = [f for f in plan["footings"] if f["mark"] == mark] if plan else []
        row = sched.get(mark)
        comb = combined.get(mark)
        entry: dict[str, Any] = {"mark": mark, "count": n, "columns": sorted({f["column"] for f in on_plan
                                                                              if f["column"]})}
        if comb and comb["columns_in_detail"]:
            entry["columns"] = sorted(set(comb["columns_in_detail"]))
        if row:
            a, b, d, c = row["a"], row["b"], row["d"], row["c"]
            vol, how = 0.0, ""
            for f in on_plan:
                v, how = _footing_concrete(a, b, d, c, (cols.get(f["column"] or "") or {}).get("size"))
                vol += v
            up = max(c - 2 * cover_f, 0)
            main_len = (a - 2 * cover_f + 2 * up) / 100
            dist_len = (b - 2 * cover_f + 2 * up) / 100
            kg_main = row["main"]["nos"] * main_len * kg_per_m(row["main"]["dia"]) * n
            kg_dist = row["dist"]["nos"] * dist_len * kg_per_m(row["dist"]["dia"]) * n
            steel_by_dia[row["main"]["dia"]] += kg_main
            steel_by_dia[row["dist"]["dia"]] += kg_dist
            p_vol = (a + 2 * pcc_off) * (b + 2 * pcc_off) * PCC_CM / 1e6 * n
            entry.update({"size": f"{a}×{b}", "depth_cm": d, "edge_cm": c, "concrete_cum": round(vol, 2),
                          "pcc_cum": round(p_vol, 2), "steel_kg": round(kg_main + kg_dist, 1),
                          "bars": f"{row['main']['nos']} nos {row['main']['dia']} mm × {main_len:.2f} m and "
                                  f"{row['dist']['nos']} nos {row['dist']['dia']} mm × {dist_len:.2f} m each way",
                          "basis": how})
            concrete += vol
            pcc += p_vol
        elif comb and comb["depth"]:
            L, W, D = comb["length"], comb["width"], comb["depth"]
            vol = L * W * D / 1e6 * n
            kg = 0.0
            # More bars are spread along the long side, so they run across it (the short way), and the fewer run
            # the long way.
            for bar in sorted(comb["bars"], key=lambda x: x["nos"]):
                span = (L if bar is min(comb["bars"], key=lambda x: x["nos"]) else W) - 2 * cover_f
                w = bar["nos"] * span / 100 * kg_per_m(bar["dia"]) * n
                steel_by_dia[bar["dia"]] += w
                kg += w
            p_vol = (L + 2 * pcc_off) * (W + 2 * pcc_off) * PCC_CM / 1e6 * n
            entry.update({"size": f"{W}×{L}", "depth_cm": D, "concrete_cum": round(vol, 2), "pcc_cum": round(p_vol, 2),
                          "steel_kg": round(kg, 1), "combined": True,
                          "bars": ", ".join(f"{x['nos']} nos {x['dia']} mm" for x in comb["bars"]),
                          "basis": "combined footing: block L×W×D, straight bars (no upturns drawn)"})
            concrete += vol
            pcc += p_vol
        else:
            entry["basis"] = "not in the footing schedule and no detail read: not counted"
        footings_out.append(entry)

    columns_out = []
    col_counts = Counter(c["mark"] for c in (plan or {}).get("columns", []))
    per_m_total = 0.0
    for mark, col in sorted(cols.items(), key=lambda kv: (len(kv[0]), kv[0])):
        bars_kg = sum(b["nos"] * kg_per_m(b["dia"]) for b in col.get("bars") or [])
        ties_kg = 0.0
        if (t := col.get("ties")) and (size := col.get("size")):
            tie_len = 2 * (size[0] + size[1] - 4 * cover_c) / 100 + 24 * t["dia"] / 1000  # two 135° hooks
            ties_kg = 100 / t["spacing_cm"] * tie_len * kg_per_m(t["dia"])
        n = col_counts.get(mark, 0)
        per_m_total += (bars_kg + ties_kg) * n
        columns_out.append({"mark": mark, "size": "×".join(map(str, col.get("size") or [])) or None,
                            "bars": " + ".join(f"{b['nos']} T{b['dia']}" for b in col.get("bars") or []) or None,
                            "ties": f"T{col['ties']['dia']} @ {col['ties']['spacing_cm']} cm" if col.get("ties") else None,
                            "kg_per_m": round(bars_kg + ties_kg, 1), "count_on_plan": n})

    bags = CEMENT_BAGS.get(grade, CEMENT_BAGS["M20"]) * concrete + CEMENT_BAGS.get(pcc_mix, 3.4) * pcc
    result = {
        "notes": info,
        "footings": footings_out,
        "columns": columns_out,
        "slabs": slabs,
        "foundation": {
            "footings": sum(counts.values()),
            "concrete_cum": round(concrete, 2), "concrete_grade": grade,
            "pcc_cum": round(pcc, 2), "pcc_mix": pcc_mix,
            "steel_kg": round(sum(steel_by_dia.values()), 1),
            "steel_by_dia": {f"{d} mm": round(kg, 1) for d, kg in sorted(steel_by_dia.items())},
            "cement_bags": math.ceil(bags),
        },
        "columns_kg_per_m": round(per_m_total, 1),
        "assumptions": [
            f"Footing concrete: base slab plus the slope up to the column + {OFFSET_CM:g} cm each side.",
            f"PCC {pcc_mix}: {PCC_CM:g} cm thick, {pcc_off:g} cm beyond each footing.",
            f"Footing bars: footing size less {cover_f * 10:g} mm cover at each end, with an upturn of the edge "
            f"thickness less covers; kg = length × d²/162. Net cut lengths: add your usual wastage.",
            f"Cement: {CEMENT_BAGS.get(grade, 8.0):g} bags/m³ for {grade}, {CEMENT_BAGS.get(pcc_mix, 3.4):g} for PCC "
            f"{pcc_mix}.",
            "Columns: per metre of height (the floor heights are not on these sheets).",
        ],
        "plan_page": (plan or {}).get("page"),
    }
    result["checks"] = cross_checks(sched, plan, cols, combined)
    return result


def cross_checks(sched: Mapping[str, Any], plan: Mapping[str, Any] | None, cols: Mapping[str, Any],
                 combined: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Mismatches between the footing plan, the schedules and the details: things to ask the consultant."""
    out: list[dict[str, Any]] = []

    def add(severity: str, page: int | None, message: str, why: str) -> None:
        out.append({"kind": "structure", "severity": severity, "page": page, "sheet": None, "message": message,
                    "why": why})

    if plan:
        pg = plan["page"]
        for f in plan["footings"]:
            row = sched.get(f["mark"])
            if row and (row["a"], row["b"]) != (f["a"], f["b"]) and (row["a"], row["b"]) != (f["b"], f["a"]):
                add("high", pg, f"{f['mark']} is {f['a']}×{f['b']} on the footing plan but {row['a']}×{row['b']} in "
                                f"the footing schedule.", "Site digs and ties to one of them: ask which is right.")
        missing = sorted({f["mark"] for f in plan["footings"] if f["mark"] not in sched and f["mark"] not in combined})
        for mark in missing:
            add("high", pg, f"{mark} is on the footing plan but not in the footing schedule and has no detail.",
                "Its depth and bars are not given anywhere.")
        unused = sorted(set(sched) - {f["mark"] for f in plan["footings"]})
        if unused:
            add("low", pg, f"{', '.join(unused)} in the footing schedule but not on the footing plan.",
                "A footing type nobody builds, or one left off the plan.")
        on_plan = {c["mark"] for c in plan["columns"]}
        if cols:
            for mark in sorted(on_plan - set(cols)):
                add("high", pg, f"Column {mark} is on the footing plan but not in the column schedule.",
                    "Its size and bars are not given.")
            for mark in sorted(set(cols) - on_plan):
                add("low", pg, f"Column {mark} is in the column schedule but not on the footing plan.",
                    "A column type nobody builds, or one left off the plan.")
        for mark, comb in combined.items():
            f = next((x for x in plan["footings"] if x["mark"] == mark), None)
            shown = comb["columns_in_detail"]
            if not f or not shown:
                continue
            near = sorted(plan["columns"], key=lambda c: math.hypot(c["x"] - f["x"], c["y"] - f["y"]))[:len(shown)]
            on = sorted(c["mark"] for c in near)
            if sorted(shown) != on:
                add("high", comb["page"], f"{mark} combined footing: the detail names its columns "
                                          f"{' and '.join(shown)}, the footing plan shows {' and '.join(on)}.",
                    "The columns on it differ in bars; the starter bars left in the footing must be the right ones.")
            for cm, size in comb["column_sizes"].items():
                sch = (cols.get(cm) or {}).get("size")
                if sch and sorted(sch) != sorted(size):
                    add("high", comb["page"], f"{cm} is {size[0]}×{size[1]} in the {mark} detail but "
                                              f"{sch[0]}×{sch[1]} in the column schedule.",
                        "The column and its starter bars are cast to one of them.")
    return out
