"""Read a whole drawing set (DR-01..DR-04): sheets, levels, rooms, fixtures and the checks, in one result. Pure
over ``pdf_text.pages``; ``read_pdf`` opens the file.

Nothing is stored (DR-04): the result is shown to the person who uploaded the set. Saving sheets and facts into the
documents register is DR-07, after DOC-01.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from mesiri.domains.drawings import checks, drafts, facts, reader

FIXTURE_ORDER = ("toilet", "urinal", "wash", "lift", "stair")


def read_pages(pages: list[Mapping[str, Any]]) -> dict[str, Any]:
    sheets = []
    for page in pages:
        s = reader.sheet(page)
        words = page["words"]
        units = s["units"] or "cm"
        s["levels"] = facts.levels(words) if s["kind"] in ("section", "elevation", None) else []
        s["rooms"] = [{**r, "computed": facts.area_of(r["a"], r["b"], units)} for r in facts.rooms(words)] \
            if s["kind"] in ("plan", None) else []
        s["fixtures"] = facts.fixtures(words) if s["kind"] == "plan" else {}
        sheets.append(s)

    level_pages: dict[float, list[int]] = defaultdict(list)
    for s in sheets:
        for lv in s["levels"]:
            level_pages[lv["value"]].append(s["page"])
    totals = {k: sum(s["fixtures"].get(k, 0) for s in sheets) for k in FIXTURE_ORDER}
    first = next((s for s in sheets if s["has_text"]), {})
    result = {
        "pages": len(pages),
        "project": first.get("project"),
        "client": first.get("client"),
        "architect": first.get("architect"),
        "units": first.get("units"),
        "sheets": sheets,
        "levels": [{"value": v, "pages": p} for v, p in sorted(level_pages.items(), key=lambda kv: -kv[0])],
        "floors": [s["level"] for s in sheets if s["kind"] == "plan" and s["level"]],
        "fixtures": totals,
        "checks": checks.run(sheets),
    }
    # DR-05 / DR-06: drafts the person edits and confirms (never saved from here).
    result["draft_schedule"] = drafts.schedule(result)
    result["draft_boq"] = drafts.boq(result)
    return result


def read_pdf(data: bytes) -> dict[str, Any]:
    from mesiri.domains.drawings import pdf_text

    return read_pages(pdf_text.pages(data))
