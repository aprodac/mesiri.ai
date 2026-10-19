"""Builds CanonicalEvent v2 from UnderstandingResult + ResolvedContext v2."""

from __future__ import annotations

import logging

from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.canonical_event import (
    CanonicalEventType,
    IntentCompleteness,
)
from mesiri_contracts.assistant.confidence import ConfidenceLevel
from mesiri_contracts.assistant.enums import InputModality, SemanticType
from mesiri_contracts.assistant.understanding_result import UnderstandingResult
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.resolved_context import ResolvedContextV2
from mesiri_contracts.common.ids import new_id

from .mapping import REQUIRED_FIELDS, resolve_event_type
from .occurred_date import resolve_occurred_date
from .progress import apply_progress

logger = logging.getLogger(__name__)

_TERMINAL_EVENT_TYPES = frozenset(
    {CanonicalEventType.GENERAL_QUESTION_ASKED, CanonicalEventType.UNRECOGNIZED}
)


def _select_candidate(understanding: UnderstandingResult) -> Candidate | None:
    for candidate in understanding.candidates:
        if candidate.semantic_type == understanding.semantic_type:
            return candidate
    return None


def _missing_required(event_type: CanonicalEventType, fields: dict) -> list[str]:
    required = REQUIRED_FIELDS.get(event_type, ())
    return [name for name in required if not fields.get(name)]


_RECEIVED_SYNONYMS = {
    "arrival",
    "arrived",
    "received",
    "receive",
    "delivery",
    "delivered",
    "deliver",
    "brought",
    "inward",
}
_USED_SYNONYMS = {
    "used",
    "use",
    "usage",
    "consumed",
    "consume",
    "applied",
    "utilized",
    "utilised",
    "outward",
}

def _normalize_material_fields(fields: dict) -> dict:
    """Map common provider aliases onto canonical material field names.

    Every alias key consumed here is popped from the result, not just copied --
    otherwise both the raw alias (``material``, ``event``) and the canonical
    name (``material_name``, ``direction``) end up in the same dict and both
    show up, duplicated, in the confirmation text the user sees."""
    out = dict(fields)
    material_alias = out.pop("material", None)
    if not out.get("material_name") and material_alias:
        out["material_name"] = material_alias

    direction = str(out.get("direction", "")).strip().lower()
    # The provider may have put a synonym directly in `direction`, or used a
    # different key entirely (`event`/`action`/`status`) instead of the exact
    # "received"/"used" the extraction prompt asks for -- check all of them
    # for known vocabulary before giving up as unrecognized. Popped either
    # way: an alias key that didn't resolve to a known direction is noise,
    # not a field the confirmation prompt should ever display.
    event_alias = out.pop("event", None)
    action_alias = out.pop("action", None)
    status_alias = out.pop("status", None)
    if direction not in ("received", "used"):
        candidates = (
            direction,
            str(event_alias or "").strip().lower(),
            str(action_alias or "").strip().lower(),
            str(status_alias or "").strip().lower(),
        )
        for value in candidates:
            if value in _RECEIVED_SYNONYMS:
                out["direction"] = "received"
                break
            if value in _USED_SYNONYMS:
                out["direction"] = "used"
                break

    # The extraction prompts ask for `supplier`, but a model can phrase the key
    # its own way; the receipt command only reads `supplier`, so an alias left
    # as-is silently saved "Received 40 bags cement from Sharma Traders" with
    # no supplier.
    for supplier_alias in ("supplier_name", "vendor", "vendor_name", "from", "received_from"):
        alias_value = out.pop(supplier_alias, None)
        if not str(out.get("supplier") or "").strip() and str(alias_value or "").strip():
            out["supplier"] = str(alias_value).strip()

    unit = out.get("unit")
    if unit:
        # Spelling normalization (bag/bags/sack -> one canonical unit) now
        # happens against the DB-backed unit_aliases table, in the material/
        # unit resolution gate (runtime/inbound_journey.py) -- trim only here.
        out["unit"] = str(unit).strip()

    return out


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


def _build_event_from_intent(
    *,
    semantic_type: SemanticType,
    candidate: Candidate | None,
    understanding: UnderstandingResult,
    context: ResolvedContextV2,
    direction_hint: str | None,
    forwarded: bool,
    frequently_forwarded: bool,
) -> CanonicalEventV2:
    """The real work behind ``build_canonical_event`` -- extracted in Phase B3
    (docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md) so it can build one
    event per INTENT (``understanding.intents``, Phase B2) rather than only
    ever reading ``understanding.semantic_type``/the one candidate that
    matches it. ``build_canonical_event`` below is now a thin wrapper calling
    this with the primary semantic_type/candidate; every existing caller of
    that singular function is unaffected by this refactor -- same inputs,
    same output, verified byte-identical by the existing test suite.

    ``semantic_type``/``candidate`` are passed in explicitly rather than
    re-derived from ``understanding`` so this same function serves BOTH the
    single-intent path (n<=1, byte-identical to pre-B3 behaviour) and the
    genuinely-plural path (n>1, only possible once B4 changes the extraction
    prompt) -- each intent supplies its own semantic_type/candidate, while
    message-level context (``understanding.original_content_reference``,
    ``context.timezone``, ``forwarded``, etc.) is shared across every event
    built from the one message, exactly as it already is for the single
    event case.
    """
    fields: dict = {}
    warnings: list[str] = []
    if candidate is not None:
        fields = {**candidate.fields, **candidate.unknown_fields}
        warnings = list(candidate.warnings)

    if forwarded:
        fields["is_forwarded"] = True
        if frequently_forwarded:
            fields["is_frequently_forwarded"] = True

    if understanding.original_content_reference:
        # The media (image/voice/document) this event was extracted from --
        # carried through fields, generic across every event type, so a
        # confirmed workflow execution can save it as evidence later (e.g.
        # expense_capture's build_draft keeps this field, and
        # RecordExpenseCommand.media_object_key writes an expense_attachments
        # row). Not expense-specific: any future domain that wants to attach
        # the source media gets this for free.
        fields["media_object_key"] = understanding.original_content_reference

    if semantic_type is SemanticType.LABOUR_UPDATE:
        fields = _normalize_labour_fields(fields, input_modality=understanding.input_modality)

    if semantic_type in (
        SemanticType.LABOUR_UPDATE,
        SemanticType.MATERIAL_UPDATE,
        SemanticType.EXPENSE,
        SemanticType.SITE_ISSUE,
    ):
        # Dated here, not in the mapper: this is the only point that holds
        # both what the message said and where the sender is (see
        # canonicalization/occurred_date.py). Originally built for Labour
        # alone (STA-161); Material and Expense had the identical pair of
        # bugs -- a stated date silently overwritten with today, and "today"
        # meaning the server's UTC today rather than the site's -- so this is
        # the one-line backport STA-166 asks for (STA-161's docstring on
        # resolve_occurred_date was written expecting exactly this).
        fields = resolve_occurred_date(fields, timezone_name=context.timezone)

    if semantic_type is SemanticType.GENERAL_SITE_UPDATE:
        fields = _ensure_site_update_narrative(fields, understanding)
        fields = apply_progress(
            fields,
            (
                understanding.translated_text
                or understanding.normalized_text
                or understanding.transcript
            )
            if len(understanding.intents) <= 1
            else None,
        )

    if semantic_type is SemanticType.MATERIAL_UPDATE:
        fields = _normalize_material_fields(fields)
        if fields.get("direction") not in ("received", "used") and direction_hint in (
            "received",
            "used",
        ):
            fields["direction"] = direction_hint

        if fields.get("direction") not in ("received", "used") and (
            fields.get("material_name") or fields.get("quantity")
        ):
            # The message clearly reads as a material report (it named a
            # material and/or a quantity) but direction still couldn't be
            # pinned down -- e.g. transcription noise garbled the one word
            # that says arrived/used, and no button hint was there to fall
            # back on. resolve_event_type below would otherwise call this
            # UNRECOGNIZED, the same terminal bucket as a message that isn't
            # about material at all, which renders as a full reset to the
            # category menu (see render_direct_reply). Ask specifically for
            # the missing piece instead, the same way any other missing
            # required field already does.
            return CanonicalEventV2(
                event_id=new_id("evt"),
                correlation_id=understanding.correlation_id,
                source_message_id=understanding.source_message_id,
                conversation_id=context.conversation_id,
                event_type=CanonicalEventType.CLARIFICATION_REQUIRED,
                completeness=IntentCompleteness.NEEDS_CLARIFICATION,
                organization_id=context.organization_id,
                user_id=context.user_id,
                project_id=context.project_id,
                site_id=context.site_id,
                permissions=context.permissions,
                fields=fields,
                missing_fields=["direction"],
                warnings=warnings,
            )

    event_type = resolve_event_type(semantic_type, fields)

    if event_type in _TERMINAL_EVENT_TYPES:
        completeness = IntentCompleteness.NOT_ACTIONABLE
        missing_fields: list[str] = []
    elif understanding.overall_confidence == ConfidenceLevel.UNUSABLE:
        completeness = IntentCompleteness.NOT_ACTIONABLE
        missing_fields = _missing_required(event_type, fields)
    else:
        missing_fields = _missing_required(event_type, fields)
        if missing_fields:
            completeness = IntentCompleteness.NEEDS_CLARIFICATION
            event_type = CanonicalEventType.CLARIFICATION_REQUIRED
        else:
            completeness = IntentCompleteness.ACTIONABLE

    return CanonicalEventV2(
        event_id=new_id("evt"),
        correlation_id=understanding.correlation_id,
        source_message_id=understanding.source_message_id,
        conversation_id=context.conversation_id,
        event_type=event_type,
        completeness=completeness,
        organization_id=context.organization_id,
        user_id=context.user_id,
        project_id=context.project_id,
        site_id=context.site_id,
        permissions=context.permissions,
        fields=fields,
        missing_fields=missing_fields,
        warnings=warnings,
    )


def build_canonical_event(
    understanding: UnderstandingResult,
    context: ResolvedContextV2,
    *,
    direction_hint: str | None = None,
    forwarded: bool = False,
    frequently_forwarded: bool = False,
) -> CanonicalEventV2:
    """Normalize AI output + resolved context into a CanonicalEvent v2.

    ``direction_hint`` is a fallback default only -- set when the user tapped
    Material's Arrived/Used buttons (channel/replies.py MATERIAL_DIRECTION_
    BUTTONS) before reporting. It's applied only if the message's own words
    didn't already resolve to a clear "received"/"used"; an explicit spoken/
    typed direction always wins over a stale or mismatched hint.

    ``forwarded`` / ``frequently_forwarded`` come from Meta's own message
    context (see ingress/normalization.py's `_resolve_forwarding`). They are
    carried as fields rather than acted on here: canonicalization decides
    business intent, not presentation, and every workflow already gates on a
    Yes/No confirmation. What they change is what that confirmation *says* --
    a second-hand report gets flagged as such so the sender re-reads it
    instead of tapping Yes reflexively (see interactions/response_handler.py).
    """
    return _build_event_from_intent(
        semantic_type=understanding.semantic_type,
        candidate=_select_candidate(understanding),
        understanding=understanding,
        context=context,
        direction_hint=direction_hint,
        forwarded=forwarded,
        frequently_forwarded=frequently_forwarded,
    )


# #13 Cross-Module Trigger: a material report naming a `work_item` ("used 40
# bags of cement during plastering") is describing TWO things in one breath.
# Only these two event types carry a work_item at all -- MaterialUpdateCandidate's
# docstring documents it as a usage-only field, but a receipt naming the work
# it's for ("cement delivered for the plastering crew") is just as valid a
# cross-module signal, so both are covered here.
_WORK_ITEM_LINKED_TYPES = frozenset(
    {CanonicalEventType.MATERIAL_RECEIPT_REQUESTED, CanonicalEventType.MATERIAL_USAGE_REQUESTED}
)


def build_canonical_events(
    understanding: UnderstandingResult,
    context: ResolvedContextV2,
    *,
    direction_hint: str | None = None,
    forwarded: bool = False,
    frequently_forwarded: bool = False,
) -> list[CanonicalEventV2]:
    """Like build_canonical_event, but may return MORE than one event when a
    single message describes more than one distinct thing (#1 Multi-Activity,
    #13 Cross-Module Trigger). events[0] is always exactly what
    build_canonical_event alone would have produced -- every existing caller
    of the singular function is unaffected by this one existing alongside it.

    Scope, as of Phase B3 (docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md):
    when `understanding.intents` (Phase B2) is genuinely plural -- only
    possible once B4 changes the extraction prompt -- this builds one event
    PER intent directly, via the same `_build_event_from_intent` helper
    `build_canonical_event` itself now delegates to. Until then (today,
    always: B4 hasn't shipped), this function is unchanged from before B3:
    the primary event plus the ONE deterministic case it already detected --
    a material report's own `work_item` field (#13 Cross-Module Trigger),
    which the extraction prompt already asks for and which already flows
    into fields unchanged -- no new AI extraction risk. It does NOT split a
    single free-text sentence describing several unrelated things ("finished
    plastering Block A, started painting Block B") into separate segments;
    that is exactly what B4's prompt change is for. The sequencing machinery
    this function feeds (planning/decomposition.py's build_plan_from_segments,
    via runtime/inbound_journey/process.py -- see docs/execution/
    UNIFIED_UNDERSTANDING_PIPELINE.md Phase A2) is general-purpose and
    already exercised by both paths below.
    """
    if len(understanding.intents) > 1:
        events: list[CanonicalEventV2] = []
        for intent in understanding.intents:
            try:
                semantic_type = SemanticType(intent.semantic_type)
            except ValueError:
                semantic_type = SemanticType.UNKNOWN
            events.append(
                _build_event_from_intent(
                    semantic_type=semantic_type,
                    candidate=intent,
                    understanding=understanding,
                    context=context,
                    direction_hint=direction_hint,
                    forwarded=forwarded,
                    frequently_forwarded=frequently_forwarded,
                )
            )
        return events

    primary = build_canonical_event(
        understanding,
        context,
        direction_hint=direction_hint,
        forwarded=forwarded,
        frequently_forwarded=frequently_forwarded,
    )
    events = [primary]

    if primary.completeness is IntentCompleteness.ACTIONABLE and primary.event_type in _WORK_ITEM_LINKED_TYPES:
        work_item = primary.fields.get("work_item")
        if work_item:
            events.append(_build_linked_activity_segment(primary, work_item=str(work_item)))

    return events


def _build_linked_activity_segment(primary: CanonicalEventV2, *, work_item: str) -> CanonicalEventV2:
    """The second segment for a material report naming what it was for.

    Deterministic -- requires no new AI extraction, since `work_item`
    already flows through _normalize_material_fields untouched into
    primary.fields whenever the provider populates it. Synthesizes an
    ACTIVITY_CONTINUATION_REQUESTED segment so the activity gets captured
    too, sequenced right after the material segment via workflows/batch.py
    -- never merged into the material workflow itself, and never written by
    it: Daily Reporting never writes another module's ledger, and Material
    never writes Daily Reporting's tables (ADR-D2/P3). Linking the two
    confirmed records together (activity_links, MATERIAL_MOVEMENT) is not
    yet wired -- see workflows/batch.py's module docstring on scope.

    No required fields (ACTIVITY_CONTINUATION_REQUESTED needs none -- see
    canonicalization/mapping.py's REQUIRED_FIELDS): a bare narrative is a
    complete, actionable continuation on its own (P10). Routed to the same
    merged WorkflowKey.SITE_UPDATE as any other site update
    (planner/routing.py); workflows/site_update/nodes.py's resolve_target
    decides whether this appends to an open Activity or creates a new one
    from this narrative, exactly as it would for a real stand-alone message.
    """
    return CanonicalEventV2(
        event_id=new_id("evt"),
        correlation_id=primary.correlation_id,
        source_message_id=primary.source_message_id,
        conversation_id=primary.conversation_id,
        causation_id=primary.event_id,
        event_type=CanonicalEventType.ACTIVITY_CONTINUATION_REQUESTED,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=primary.organization_id,
        user_id=primary.user_id,
        project_id=primary.project_id,
        site_id=primary.site_id,
        permissions=primary.permissions,
        fields={"narrative": work_item, "update_kind": "PROGRESS"},
    )


def log_canonical_event(event: CanonicalEventV2) -> None:
    logger.info(
        "CanonicalEvent correlation_id=%s event_type=%s completeness=%s "
        "organization=%s user=%s project=%s site=%s",
        event.correlation_id,
        event.event_type.value,
        event.completeness.value,
        event.organization_id,
        event.user_id,
        event.project_id or "unknown",
        event.site_id or "unknown",
    )
    if event.missing_fields:
        logger.info("CanonicalEvent missing_fields=%s", event.missing_fields)
    if event.warnings:
        logger.info("CanonicalEvent warnings=%s", event.warnings)
