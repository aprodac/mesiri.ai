"""[233] Fields the code can fill from the person's own words, and a check of a held body against its tool's schema.

4 Nov (asus, "plastering done on 2nd floor"): the model prepared a work update with no narrative and no quantities;
the API refused it on Save, and the refused line came back on every card. The model reads; the code fills what it can
derive and holds only a body that will pass.
"""

from __future__ import annotations

import re
from typing import Any

WORK_TOOL = "record_work"
#: The API's own refusal when a work update has neither (``progress/validation.py``).
NARRATIVE_REFUSAL = re.compile(r"narrative or at least one quantity", re.I)


def _their_line(summary: str, names: tuple[str, ...]) -> str:
    """The entry's one-line summary in their words, without the code's notes (" · 📍 ...") and without a trailing
    " at <site or project>" the line names (the record already has the site)."""
    line = summary.split(" · ", 1)[0].strip()
    head, sep, tail = line.rpartition(" at ")
    tail_key = tail.strip().casefold()
    if sep and head.strip() and tail_key:
        for name in names:
            full = name.casefold().strip()
            first = full.split(",")[0].strip()
            if tail_key in (full, first):
                return head.strip()
    return line


def other_script(text: str) -> bool:
    """[243]: ``text`` has a letter outside the Latin alphabet (Malayalam, Tamil, Devanagari, Arabic, ...)."""
    return any(c.isalpha() and ord(c) >= _NON_LATIN for c in text)


#: [243]: from here on (Greek, Cyrillic, Arabic, the Indic scripts) a letter is not Latin; emoji and ₹ are not letters.
_NON_LATIN = 0x0370
_NOT_TEXT = ("enum", "format", "const")


def not_english(parameters: dict[str, Any], body: dict[str, Any], at: str = "") -> list[str]:
    """[243]: the free-text fields of a held body written in another script, read from the tool's own schema (the
    OpenAPI request body): strings only, never ids, enums or dates. Everything Mesiri saves is English."""
    out: list[str] = []
    props = parameters.get("properties", {})
    for name, value in body.items():
        schema = props.get(name) or {}
        variants = [schema, *schema.get("anyOf", []), *schema.get("oneOf", [])]
        if isinstance(value, str):
            if name.endswith("_id") or any(k in v for v in variants for k in _NOT_TEXT):
                continue
            if other_script(value):
                out.append(at + name)
        elif isinstance(value, list):
            items = next((v.get("items") for v in variants if isinstance(v.get("items"), dict)), {})
            for i, row in enumerate(value, 1):
                if isinstance(row, dict):
                    out += not_english(items, row, f"{at}{name}[{i}].")
                elif isinstance(row, str) and other_script(row):
                    out.append(f"{at}{name}[{i}]")
        elif isinstance(value, dict):
            nested = next((v for v in variants if v.get("properties")), {})
            out += not_english(nested, value, f"{at}{name}.")
    return out


def fill_body(tool: str, body: dict[str, Any], summary: str, names: tuple[str, ...] = ()) -> dict[str, Any]:
    """``body`` with the fields the code can derive. A work update with neither a narrative nor a quantity gets its
    narrative from the entry's summary (their words). Anything else is returned as it was. [243]: never a summary in
    another script (the card line is in their language; the record is English)."""
    if tool == WORK_TOOL and not str(body.get("narrative") or "").strip() and not body.get("quantities"):
        words = _their_line(summary, names)
        if words and not other_script(words):
            return {**body, "narrative": words}
    return body


def missing_in_body(parameters: dict[str, Any], body: dict[str, Any]) -> list[str]:
    """Required fields still missing inside the body's nested lists (``lines[].trade``, ``quantities[].unit``), read
    from the tool's own schema (the OpenAPI request body): the top level is checked where the call is made."""
    out: list[str] = []
    props = parameters.get("properties", {})
    for name, value in body.items():
        schema = props.get(name) or {}
        items = schema.get("items") if schema.get("type") == "array" else None
        if not (isinstance(items, dict) and isinstance(value, list)):
            continue
        for i, row in enumerate(value, 1):
            if not isinstance(row, dict):
                continue
            for need in items.get("required", []):
                if row.get(need) in (None, "", []):
                    out.append(f"{name}[{i}].{need}")
    return out
