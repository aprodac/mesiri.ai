"""[233] Fields the code can fill from the person's own words, and a check of a held body against its tool's schema.

4 Nov (asus, "plastering done on 2nd floor"): the model prepared a work update with no narrative and no quantities;
the API refused it on Save, and the refused line came back on every card. The model reads; the code fills what it can
derive and holds only a body that will pass.
"""

from __future__ import annotations

import asyncio
import re
import uuid
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


def _uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def names_for_ids(parameters: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """LRN-F16 / WA-316 (20 Nov, recording episode 3: Anil's "Annex: Manoj, Satheesh, Vinod present" was held with
    ``worker_id: "Manoj"`` on each line, and Save got 422 "Input should be a valid UUID" for the whole report): a name
    the model put in an id field, where the same row has the name's own field (``worker_id`` beside ``worker_name``),
    moves to that field, and the id is left out, so the API matches the name the way it does for anyone typed by name.
    Read from the tool's own schema (its fields), at the top level and inside its lists; an id that is an id is never touched, and a
    field with no name beside it is left for the checks that already ask the model to look the record up."""

    def fix(props: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
        out = row
        for field in props:
            value = row.get(field)
            # Every record id in this API is a UUID; the tool schemas the model sees keep no format, so the field's
            # name says it is an id.
            if not field.endswith("_id") or value in (None, ""):
                continue
            name_field = field[:-3] + "_name"
            if _uuid(value) or name_field not in props:
                continue
            out = {k: v for k, v in out.items() if k != field}
            if not str(out.get(name_field) or "").strip():
                out[name_field] = str(value)
        return out

    props = parameters.get("properties", {})
    out = fix(props, body)
    for name, value in list(out.items()):
        schema = props.get(name) or {}
        items = schema.get("items") if schema.get("type") == "array" else None
        if isinstance(items, dict) and isinstance(value, list):
            inner = items.get("properties") or {}
            fixed = [fix(inner, row) if isinstance(row, dict) else row for row in value]
            if fixed != value:
                out = {**out, name: fixed}
    return out


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


#: [248]: how long one fallback translation may take before the field is left as it is (it is a few words).
TRANSLATE_SECONDS = 6.0
_PATH = re.compile(r"([^.\[\]]+)(?:\[(\d+)\])?")


async def to_english(provider: Any, texts: list[str], correlation_id: str | None = None, *,
                     latin: bool = False) -> dict[str, str]:
    """[248]: Mesiri translates a word or a field into English itself; the person is never asked to.

    5 Nov (New India, a new owner's first voice note): the model left "സിമൻ്റ്" in Malayalam twice and Mesiri asked
    the person to say "cement" in English. Translating is the AI's job. This runs only on the rare path where the
    model's body is still in another script (one short call per distinct text, in parallel), through the provider's
    own translation route (``translate_to_english``, the control panel's "translation" row). Returns {text: English}
    for the texts it could translate; one it could not (no route, a failure, a timeout, still not Latin) is left out.
    ``latin``: also words in Latin letters (Manglish "kambi"), for a material word that is not in the company's list;
    a translation that only gives the word back is left out.
    """
    translate = getattr(provider, "translate_to_english", None)
    wanted = [t for t in dict.fromkeys(texts) if isinstance(t, str) and t.strip() and (latin or other_script(t))]
    if translate is None or not wanted:
        return {}

    async def one(text: str) -> str:
        try:
            result = await asyncio.wait_for(translate(text, correlation_id=correlation_id), TRANSLATE_SECONDS)
        except Exception:  # noqa: BLE001 -- a failed translation leaves the field as it is; never the person's job
            return ""
        out = " ".join(str(getattr(result, "translated_text", "") or "").split()).strip(" .\"'")
        return "" if not out or other_script(out) or out.casefold() == text.strip().casefold() else out

    done = await asyncio.gather(*(one(t) for t in wanted))
    return {t: e for t, e in zip(wanted, done, strict=True) if e}


def _steps(path: str) -> list[str | int]:
    out: list[str | int] = []
    for name, index in _PATH.findall(path):
        out.append(name)
        if index:
            out.append(int(index) - 1)
    return out


def field_at(body: Any, path: str) -> Any:
    """The value at a :func:`not_english` path ("narrative", "lines[2].trade"), or None."""
    node = body
    for step in _steps(path):
        try:
            node = node[step]
        except (KeyError, IndexError, TypeError):
            return None
    return node


def set_field(body: Any, path: str, value: Any) -> None:
    """Set the value at a :func:`not_english` path; a path that is not there is left alone."""
    steps = _steps(path)
    parent = body
    for step in steps[:-1]:
        try:
            parent = parent[step]
        except (KeyError, IndexError, TypeError):
            return
    try:
        parent[steps[-1]] = value
    except (KeyError, IndexError, TypeError):
        return


async def translate_body(provider: Any, parameters: dict[str, Any], body: dict[str, Any],
                         correlation_id: str | None = None) -> list[str]:
    """[248]: translate the body's free-text fields that are not English, in place. Returns the fields still not
    English (none, when every one was translated)."""
    foreign = not_english(parameters, body)
    if not foreign:
        return []
    done = await to_english(provider, [str(field_at(body, p) or "") for p in foreign], correlation_id)
    for path in foreign:
        if (english := done.get(str(field_at(body, path) or ""))):
            set_field(body, path, english)
    return not_english(parameters, body)
