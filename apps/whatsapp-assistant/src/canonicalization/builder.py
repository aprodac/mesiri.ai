"""Builds CanonicalEvent v2 from UnderstandingResult + ResolvedContext v2."""

from __future__ import annotations

from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.understanding_result import UnderstandingResult


def _ensure_site_update_narrative(fields: dict, understanding: UnderstandingResult) -> dict:
    """A site update always carries the sender's own words as its narrative.

    The extraction prompt asks for `narrative` ("the report in the sender's own
    words"), but a model can return only work_type/location -- most often for
    one part of a multi-part message. The backend rejects an activity with
    neither narrative nor quantity ("activity must have a narrative or at
    least one quantity"), so "Plastering done on 2nd floor east side" was lost
    after the sender had confirmed it. The message text is what the sender
    said; use it rather than dropping the work.
    """
    narrative = str(fields.get("narrative") or "").strip()
    if narrative:
        # Where the work was done has no column of its own (location_id is a
        # registered location, not free text), so it lives in the words.
        location = str(fields.get("location") or "").strip()
        if location and location.casefold() not in narrative.casefold():
            return {**fields, "narrative": f"{narrative} ({location})"}
        return fields
    if len(understanding.intents) > 1:
        # The message text covers every intent, so it is not this one's own
        # words; describe it from what was extracted instead.
        bits = [str(fields.get(k)).strip() for k in ("work_type", "location") if fields.get(k)]
        text = " - ".join(bits)
    else:
        text = (
            understanding.translated_text
            or understanding.normalized_text
            or understanding.transcript
            or ""
        ).strip()
    if not text:
        return fields
    return {**fields, "narrative": text}


_LABOUR_NAME_ALIASES = ("name", "worker_name", "worker")
_LABOUR_COUNT_ALIASES = ("headcount", "count", "number", "quantity", "workers")


def _coerce_headcount(raw: object, *, named: bool) -> int:
    """A line's headcount, defaulting sanely rather than rejecting.

    A named person is always 1 -- a provider that returns ``{"name": "Ravi",
    "headcount": 12}`` has misread "Ravi" and "12 helpers" as one line, and
    trusting the 12 would silently bill twelve days to one man.
    """
    if named:
        return 1
    try:
        value = int(float(str(raw)))
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


def _is_non_latin(name: str) -> bool:
    """True when a name carries no Latin letters at all.

    Used only to notice that transliteration did not happen. Deliberately
    "no Latin letters" rather than "any non-Latin character": a genuinely
    transliterated name can still carry a diacritic or an apostrophe, and
    flagging those would bury the real cases in noise.
    """
    return bool(name.strip()) and not any(
        "a" <= char.lower() <= "z" for char in name
    )


def _labour_line(raw: dict) -> dict | None:
    """Normalize one extracted worker entry, or None if it says nothing."""
    name = next((raw[k] for k in _LABOUR_NAME_ALIASES if raw.get(k)), None)
    name = str(name).strip() if name else None
    count_raw = next((raw[k] for k in _LABOUR_COUNT_ALIASES if raw.get(k) is not None), None)
    trade = raw.get("trade") or raw.get("skill") or raw.get("role")
    wage = raw.get("daily_wage") or raw.get("wage") or raw.get("rate")

    if not name and not trade and count_raw is None:
        return None

    line: dict = {
        "worker_name": name,
        "trade": str(trade).strip() if trade else None,
        "headcount": _coerce_headcount(count_raw, named=bool(name)),
    }
    # The name as actually written, when the sheet wasn't in Latin script.
    # Kept because transliteration is a judgement call the supervisor is far
    # better placed to check than we are -- showing "Ravi (രവി)" back to them
    # lets a wrong reading be caught at confirmation, which is the one moment
    # anyone is looking. Dropped when it adds nothing (identical to the
    # transliteration), so a Latin-script sheet gains no noise.
    original = raw.get("name_original") or raw.get("original_name")
    if original and str(original).strip() and str(original).strip() != name:
        line["worker_name_original"] = str(original).strip()
    elif name and _is_non_latin(name):
        # The model was asked to transliterate and did not. Record what it
        # actually returned as the original, so the native spelling is never
        # lost and the preview shows it -- a supervisor can then fix the
        # reading with a plain "രവി is Ravi" (see interactions/
        # name_corrections.py) instead of redoing the report.
        #
        # The name itself is left as-is rather than guessed at: there is no
        # transliteration table here, and inventing one would put a wrong
        # name on a wage record. Leaving it visibly wrong is recoverable;
        # silently inventing a plausible-looking name is not.
        line["worker_name_original"] = name
    if wage is not None:
        line["daily_wage"] = wage
    for key in ("contractor", "activity", "remarks"):
        if raw.get(key):
            line[key] = str(raw[key]).strip()

    status = _labour_attendance_status(raw)
    if status is not None:
        line["attendance_status"] = status

    overtime = raw.get("overtime_hours") or raw.get("ot_hours") or raw.get("overtime")
    if overtime is not None:
        line["overtime_hours"] = overtime
    return line


#: What a muster roll actually writes in the P/A/H column, mapped to the three
#: values the contract allows. Anything unrecognised is left unset rather than
#: guessed: the default is "present", and a wrong guess here either deletes a
#: day's pay or invents one.
_ATTENDANCE_STATUS_ALIASES: dict[str, str] = {
    "p": "present", "present": "present", "yes": "present", "y": "present",
    "full": "present", "full_day": "present", "fullday": "present", "1": "present",
    "a": "absent", "absent": "absent", "no": "absent", "n": "absent",
    "leave": "absent", "off": "absent", "0": "absent",
    "h": "half_day", "hd": "half_day", "half": "half_day",
    "half_day": "half_day", "halfday": "half_day", "half day": "half_day",
    "0.5": "half_day",
}


def _labour_attendance_status(raw: dict) -> str | None:
    """Normalize the sheet's attendance mark, or None to leave the default.

    Returns None for anything unrecognised on purpose. `attendance_status`
    defaults to "present", which is correct for every typed report (a
    supervisor listing names is listing who worked) and for a sheet whose
    column the model could not read. Marking someone absent on a guess would
    silently remove a day's wage from a real person.
    """
    for key in ("attendance_status", "status", "attendance", "present"):
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            return "present" if value else "absent"
        text = str(value).strip().lower()
        if text in _ATTENDANCE_STATUS_ALIASES:
            return _ATTENDANCE_STATUS_ALIASES[text]
    return None


# How the report reached Mesiri, mapped from the real input modality of the
# message that started the workflow (recorded once at canonicalization --
# see _normalize_labour_fields below -- and never overwritten by a later
# slot-filling reply in the same conversation, which is always TEXT/
# INTERACTIVE regardless of how the original report arrived).
#
# DOCUMENT shares "whatsapp_image": both go through the vision path
# (understanding/pipeline.py handles IMAGE and DOCUMENT identically), and
# the labour_attendance_reports.recorded_via check constraint intentionally
# has no separate bucket for a distinction the rest of the system doesn't
# make either. UNKNOWN/anything unmapped falls back to the command
# contract's own default ("whatsapp_text") rather than inventing a value
# here -- the mapper is closer to that call and pins the exact string.
_RECORDED_VIA_BY_MODALITY: dict[InputModality, str] = {
    InputModality.TEXT: "whatsapp_text",
    InputModality.INTERACTIVE: "whatsapp_text",
    InputModality.VOICE: "whatsapp_voice",
    InputModality.IMAGE: "whatsapp_image",
    InputModality.DOCUMENT: "whatsapp_image",
}


def _normalize_labour_fields(fields: dict, *, input_modality: InputModality | None = None) -> dict:
    """Map whatever the provider returned onto the canonical ``lines`` shape.

    The workflow (workflows/labour_update) only ever reads ``lines``: a list
    where each entry is either a named person or an anonymous headcount group
    (plan principle P10). Getting to that single shape here -- rather than
    teaching the graph three input dialects -- is the same job
    ``_normalize_material_fields`` does for ``material``/``event`` aliases.

    Three inputs are accepted because all three genuinely occur:

    1. ``workers``: [...] -- what the extraction prompt now asks for.
    2. ``lines``: [...] -- already canonical (a corrected/replayed event).
    3. flat ``headcount``/``trade`` -- what the prompt asked for until
       2026-07-26, and what a provider still falls back to on a terse message
       like "12 masons". Folded into a single group line so an older or
       simpler extraction keeps working rather than becoming unactionable.

    Alias keys are popped, not copied: leaving both ``workers`` and ``lines``
    behind would show the same attendance twice in the confirmation text.

    ``recorded_via`` is set here too, from ``input_modality``, when a mapping
    exists -- simple provenance metadata (how the report arrived: text,
    voice, image, or later dashboard), not something the workflow displays or
    the domain rules act on. Left unset when unmapped so the command's own
    default applies rather than this function inventing one.
    """
    out = dict(fields)
    if input_modality in _RECORDED_VIA_BY_MODALITY:
        out["recorded_via"] = _RECORDED_VIA_BY_MODALITY[input_modality]
    raw_lines = out.pop("workers", None) or out.pop("lines", None)

    lines: list[dict] = []
    if isinstance(raw_lines, list):
        for entry in raw_lines:
            if isinstance(entry, dict):
                line = _labour_line(entry)
            elif entry:
                # A bare string ("12 helpers", or just "Ravi") -- keep it as a
                # name rather than discarding the only thing the user said.
                line = _labour_line({"name": str(entry)})
            else:
                line = None
            if line is not None:
                lines.append(line)

    if not lines:
        flat = _labour_line(
            {
                "name": next((out.get(k) for k in _LABOUR_NAME_ALIASES if out.get(k)), None),
                "headcount": out.get("headcount") or out.get("count"),
                "trade": out.get("trade"),
                "daily_wage": out.get("daily_wage"),
            }
        )
        if flat is not None:
            lines.append(flat)

    # Popped once folded in, so they don't also render as their own lines in
    # the confirmation prompt alongside the line they produced.
    for key in ("headcount", "count", "trade", "daily_wage", "worker_name", "name"):
        out.pop(key, None)

    if lines:
        contractor = out.get("contractor")
        if contractor:
            # Stated once for the whole report ("all from Kumar Team"), but
            # matching scores it per worker -- so push it down to any line
            # that didn't state its own.
            for line in lines:
                line.setdefault("contractor", str(contractor).strip())
        out["lines"] = lines
    return out












