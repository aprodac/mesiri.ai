"""Labour attendance workflow nodes — pure functions, no LangGraph, no I/O, no SQL.

Mirrors workflows/material/nodes.py for shape and workflows/expense_capture/
nodes.py for slot-filling. Each node takes the graph's working state and
returns the partial update LangGraph merges in.

**What is different here, and why.** Every other v1 workflow asks a *fixed*
number of questions: expense_capture has exactly two slots (`account_id`,
`duplicate_confirm`), each its own node with its own edge. Labour cannot work
that way — one attendance may name seven workers, of whom any number between
zero and seven are ambiguous, and the graph has no way to know which before it
runs.

So worker matching is a single **re-entrant** node that resolves as much as it
can per pass and asks about at most one line before stopping. The line it is
asking about is encoded in the slot name (``worker_match:2``), because the
graph is compiled without a checkpointer and is re-invoked from scratch on
every inbound message — `collected_fields` (persisted as WorkflowState.v1) is
the only thing that survives between passes, so the node re-derives everything
else from it. See workflows/runtime.py's `provide_input`.

Resolving everything resolvable *before* asking is what keeps this usable: a
ten-worker report with nine confident matches asks one question, not ten.
That is principle P9 (optimize for speed of recording) in practice, while P4
(never identify a worker by name alone) still decides what counts as
confident.

**Why this node calls domain code when others don't.** `match_worker` lives in
the backend's `domains/workforce/matching.py` and is imported directly here,
which no other workflow node does. The rule nodes obey is "no I/O, no SQL, no
repository access" — `match_worker` is a pure scoring function over candidates
the *caller* supplied (seeded into `collected_fields['worker_candidates']`,
see workflows/runtime.py's docstring), so it breaks none of that. The
alternative — having the runtime pre-compute match results and seed those too —
would split one loop across two layers for no gain in purity.

**Input shape.** `collected_fields['lines']` is a list of dicts, each either a
named worker or a headcount group (plan principle P10 — a site reports whichever
way it can, and one message may mix both)::

    {"worker_name": "Ravi", "trade": "mason", "headcount": 1, "daily_wage": 800}
    {"worker_name": None,   "trade": "helper", "headcount": 12, "daily_wage": 600}

Phase 6 rewrites AI extraction to produce this; until then the graph is
already correct, and with no candidates seeded every named line simply
resolves to a temporary worker without asking anything.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from mesiri.domains.workforce.matching import (
    MatchOutcome,
    MatchResult,
    ReportedWorker,
    WorkerCandidate,
    match_worker,
)
from mesiri.domains.workforce.workers import normalize_name, normalize_trade
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.common.ids import new_id
from trade_label import trade_label

from ..readable import field_lines
from ..slots import (
    RETRY_PREFIX,
    SlotCandidate,
    match_slot_answer,
    resolve_single_choice_slot,
    slot_options,
)
from ..state import WorkflowGraphState

#: Slot names are ``worker_match:<line index>``. The index is part of the name
#: rather than a separate field because `awaiting_slot` is the only routing
#: signal the graph and the runtime both see, and routing must stay
#: slot-specific (a stale slot from another question must never re-trigger
#: this node's edge — the bug expense_capture's `_route_after_account_
#: resolution` documents).
WORKER_MATCH_SLOT_PREFIX = "worker_match:"

#: Always offered as the last choice. Without it the user has no way to say
#: "none of these", and a temporary worker becomes unrecordable rather than
#: first-class (principle P3). Choosing it sets ``worker_id = None`` on the
#: line and writes nothing at all to the register (principle P1) — promotion
#: into the register is a separate, explicitly confirmed act.
SOMEONE_NEW_SENTINEL = "__someone_new__"
_SOMEONE_NEW_LABEL = "Someone new"

#: Written onto a line once matching has decided it, so a later pass skips it.
#: Workflow bookkeeping, never part of the command — stripped in `build_draft`.
_RESOLVED_FLAG = "worker_match_resolved"

#: Where a "Akhil -> Akhilesh" correction is handed to this node. Set on the
#: pending draft by the correction path (interactions/handler.py), consumed
#: at the top of match_workers, and never persisted beyond that pass.
NAME_CORRECTIONS_FIELD = "_name_corrections"

#: The "you already reported this day" question. Attendance cannot be edited
#: (P5), so a supervisor who forgets someone re-sends the whole list. Until
#: this existed, the second report was stored as an independent row and both
#: counted -- a day of 18 workers reading as 16 + 18 = 34 man-days.
#:
#: Deliberately *not* auto-resolved. Both answers are legitimate and only the
#: supervisor knows which is true: a re-send corrects, while a second shift or
#: a different crew on the same site is a genuinely separate report. Guessing
#: either way silently loses real attendance or silently doubles it.
DUPLICATE_DAY_SLOT_NAME = "attendance_duplicate_day"
REPLACE_SENTINEL = "replace"
ADD_SEPARATELY_SENTINEL = "add_separately"
_DUPLICATE_DAY_CANDIDATES = [
    SlotCandidate(value=REPLACE_SENTINEL, label="Replace it"),
    SlotCandidate(value=ADD_SEPARATELY_SENTINEL, label="Add as separate"),
]


def _existing_report_summary(existing: dict[str, Any]) -> str:
    """Describe what is already recorded, so the choice is informed rather
    than a bare yes/no about something the supervisor cannot see."""
    headcount = existing.get("total_headcount")
    lines = existing.get("line_count")
    parts: list[str] = []
    if isinstance(headcount, int) and headcount > 0:
        parts.append(f"{headcount} {'worker' if headcount == 1 else 'workers'}")
    elif isinstance(lines, int) and lines > 0:
        parts.append(f"{lines} {'line' if lines == 1 else 'lines'}")
    cost = _fmt_amount(existing.get("total_cost"))
    if cost:
        parts.append(f"₹{cost}")
    return ", ".join(parts) if parts else "an earlier report"


def check_duplicate_day(state: WorkflowGraphState) -> dict:
    """Ask whether this replaces the report already recorded for the same day.

    No-op unless the caller seeded `existing_report` (runtime/inbound_journey/
    seeding.py's `_seed_existing_attendance` -- a node never queries a
    repository itself), and unless the question is still unanswered.

    "Replace it" carries the earlier report's id through to the command as
    `corrects_report_id`, which persistence writes and every total already
    honours: both rows survive for audit, only the newer one counts. "Add as
    separate" leaves it unset and both count, which is correct for a second
    shift.
    """
    fields = dict(state.get("collected_fields") or {})
    existing = fields.get("existing_report")
    if not isinstance(existing, dict) or not existing.get("report_id"):
        return {}
    if fields.get("duplicate_day_answered"):
        return {}

    prompt_title = (
        f"You already reported {_existing_report_summary(existing)} for this day. "
        "Does this replace that, or is it a separate report?"
    )

    def _ask(title: str) -> dict:
        resolution = resolve_single_choice_slot(
            slot_name=DUPLICATE_DAY_SLOT_NAME,
            prompt_title=title,
            candidates=_DUPLICATE_DAY_CANDIDATES,
        )
        return {
            "collected_fields": fields,
            "awaiting_slot": resolution.awaiting_slot,
            "awaiting_slot_options": slot_options(_DUPLICATE_DAY_CANDIDATES),
            "pending_prompt": resolution.slot_prompt,
        }

    if state.get("awaiting_slot") == DUPLICATE_DAY_SLOT_NAME:
        answer_text = fields.pop("_slot_answer_text", None)
        if answer_text is not None:
            matched = match_slot_answer(answer_text, _DUPLICATE_DAY_CANDIDATES)
            if matched is None:
                return _ask(f"{RETRY_PREFIX} {prompt_title}")
            resolved = {**fields, "duplicate_day_answered": True}
            if matched == REPLACE_SENTINEL:
                resolved["corrects_report_id"] = str(existing["report_id"])
            return {
                "collected_fields": resolved,
                "awaiting_slot": None,
                "awaiting_slot_options": None,
                "pending_prompt": None,
            }

    return _ask(prompt_title)


def _apply_name_corrections(
    lines: list[dict[str, Any]], corrections: dict[str, Any]
) -> list[dict[str, Any]]:
    """Rewrite worker names on the extracted lines, and un-decide those lines.

    Matching against the *old* spelling is exactly what the user is telling
    us was wrong, so any decision already recorded for a corrected line --
    the matched worker_id and the resolved flag -- is thrown away and the
    line goes back through matching from scratch. Keeping it would leave
    "Akhilesh" linked to whoever "Akhil" resolved to, which is the silent
    false merge this module exists to prevent (P4).

    Matching on the name is case- and space-insensitive so the correction can
    be typed the way it reads on screen. `worker_name_original` is left
    untouched: it records what was actually written on the sheet or said out
    loud, and a correction does not change that history.
    """
    wanted = {normalize_name(old): new for old, new in corrections.items() if str(new).strip()}
    if not wanted:
        return lines

    corrected: list[dict[str, Any]] = []
    for line in lines:
        name = str(line.get("worker_name") or "")
        replacement = wanted.get(normalize_name(name)) if name else None
        if replacement is None:
            corrected.append(line)
            continue
        updated = {**line, "worker_name": str(replacement).strip()}
        updated.pop(_RESOLVED_FLAG, None)
        updated["worker_id"] = None
        corrected.append(updated)
    return corrected


# --- Reading the seeded state ---------------------------------------------


def _as_lines(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Copy the attendance lines out of collected_fields.

    Defensive about shape: these fields arrive from AI extraction and survive
    a JSON round-trip through the workflow_instances table, so anything
    non-conforming is skipped rather than raising — a malformed line must not
    take down a report that is otherwise fine.
    """
    raw = fields.get("lines")
    if not isinstance(raw, list):
        return []
    return [dict(line) for line in raw if isinstance(line, dict)]


def _as_candidates(fields: dict[str, Any]) -> list[WorkerCandidate]:
    """Register candidates seeded by the caller (a repository read).

    Empty is a legitimate, common state — a brand-new organization has no
    register at all — and resolves every named line to a temporary worker
    with no questions asked.
    """
    raw = fields.get("worker_candidates")
    if not isinstance(raw, list):
        return []
    candidates: list[WorkerCandidate] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        worker_id = entry.get("worker_id") or entry.get("id")
        name = entry.get("name")
        if not worker_id or not name:
            continue
        candidates.append(
            WorkerCandidate(
                worker_id=str(worker_id),
                name=str(name),
                trade=entry.get("trade"),
                contractor=entry.get("contractor"),
                seen_on_site=bool(entry.get("seen_on_site")),
                seen_on_project=bool(entry.get("seen_on_project")),
            )
        )
    return candidates


def _reported(line: dict[str, Any]) -> ReportedWorker:
    return ReportedWorker(
        name=str(line.get("worker_name") or ""),
        trade=line.get("trade"),
        contractor=line.get("contractor"),
        daily_wage=line.get("daily_wage"),
        activity=line.get("activity"),
    )


def _needs_match(line: dict[str, Any]) -> bool:
    """A line needs matching only if it names someone and hasn't been decided.

    A headcount group ("12 helpers") names nobody, so there is nothing to
    match and nothing to ask — it goes straight through.
    """
    if line.get(_RESOLVED_FLAG):
        return False
    return bool(str(line.get("worker_name") or "").strip())


def _slot_index(awaiting_slot: str) -> int | None:
    suffix = awaiting_slot[len(WORKER_MATCH_SLOT_PREFIX) :]
    try:
        return int(suffix)
    except ValueError:
        return None


# --- Asking about one line -------------------------------------------------


def _pretty_trade(trade: str | None) -> str:
    return trade_label(trade)


def _slot_candidates(result: MatchResult, candidates: list[WorkerCandidate]) -> list[SlotCandidate]:
    """Tappable choices for one ambiguous line: the plausible workers, then
    "Someone new".

    Labels are the worker's name and nothing else. A tapped WhatsApp row comes
    back as its *title*, which `match_slot_answer` then matches against the
    label byte for byte, and a row title over 24 characters makes the send
    side drop the whole list back to plain text (see runtime/inbound_journey.py's
    `_render_reply`). Reasons therefore go in the prompt body, not the label.
    Two candidates sharing a name are disambiguated by trade — the one case
    where a bare name genuinely cannot identify the choice.
    """
    by_id = {c.worker_id: c for c in candidates}
    names = [scored.name for scored in result.candidates]
    options: list[SlotCandidate] = []
    for scored in result.candidates:
        label = scored.name
        if names.count(scored.name) > 1:
            trade = normalize_trade(by_id[scored.worker_id].trade) if scored.worker_id in by_id else None
            if trade:
                label = f"{scored.name} ({_pretty_trade(trade)})"
        options.append(SlotCandidate(value=scored.worker_id, label=label))
    options.append(SlotCandidate(value=SOMEONE_NEW_SENTINEL, label=_SOMEONE_NEW_LABEL))
    return options


def _match_prompt(
    reported: ReportedWorker,
    result: MatchResult,
    candidates: list[WorkerCandidate],
    options: list[SlotCandidate],
    *,
    retry: bool = False,
) -> str:
    """Word the question.

    Two shapes, because a changed trade and an ambiguous name are different
    questions needing different answers (principle P4). When the register and
    the report disagree about someone's trade, the prompt must name *both*
    trades and offer the two readings explicitly — "same worker, updated
    trade" versus "a different person who shares a name". A bare "which of
    these?" invites the user to pick the familiar name without noticing the
    discrepancy, which is precisely how one worker's history gets merged with
    another's.
    """
    by_id = {c.worker_id: c for c in candidates}
    top = result.candidates[0]

    if top.trade_changed:
        registered = _pretty_trade(normalize_trade(by_id[top.worker_id].trade)) if top.worker_id in by_id else "something else"
        reported_trade = _pretty_trade(normalize_trade(reported.trade))
        header = (
            f"The register says {top.name} is a {registered}, "
            f"but today's report says {reported_trade}.\n"
            f"Same worker with an updated trade, or a different {reported.name}?"
        )
    else:
        trade_hint = f" ({_pretty_trade(normalize_trade(reported.trade))})" if reported.trade else ""
        header = f'Which "{reported.name}"{trade_hint} is this?'

    if retry:
        header = f"{RETRY_PREFIX} {header}"

    lines = [header, ""]
    # Reasons are shown so the choice is auditable rather than magical: the
    # user can see *why* a candidate is being suggested and correct a wrong
    # suggestion knowingly.
    reason_by_id = {scored.worker_id: scored.reasons for scored in result.candidates}
    for number, option in enumerate(options, start=1):
        if option.value == SOMEONE_NEW_SENTINEL:
            lines.append(f"{number}. {option.label} — record as a temporary worker")
            continue
        reasons = reason_by_id.get(option.value, ())
        suffix = f" — {', '.join(reasons)}" if reasons else ""
        lines.append(f"{number}. {option.label}{suffix}")
    lines.append("")
    lines.append("Reply with a number, or just tell me which one.")
    return "\n".join(lines)


def _ask(
    fields: dict[str, Any],
    lines: list[dict[str, Any]],
    index: int,
    result: MatchResult,
    candidates: list[WorkerCandidate],
    *,
    retry: bool = False,
) -> dict:
    if lines:
        fields["lines"] = lines
    options = _slot_candidates(result, candidates)
    return {
        "collected_fields": fields,
        "awaiting_slot": f"{WORKER_MATCH_SLOT_PREFIX}{index}",
        "awaiting_slot_options": slot_options(options),
        "pending_prompt": _match_prompt(
            _reported(lines[index]), result, candidates, options, retry=retry
        ),
    }


# --- Nodes -----------------------------------------------------------------


def match_workers(state: WorkflowGraphState) -> dict:
    """Resolve every named line to a registered worker, a temporary worker, or
    a question — asking about at most one line per pass.

    Order matters: an answer to the previous question is applied *first*, then
    the scan continues from the top and stops at the next line that genuinely
    needs a decision. That ordering is what makes the node re-entrant without
    a checkpointer, and it terminates because every pass either records a
    decision on at least one line or asks about one.
    """
    fields = dict(state.get("collected_fields") or {})
    lines = _as_lines(fields)
    candidates = _as_candidates(fields)
    answer_text = fields.pop("_slot_answer_text", None)
    awaiting = state.get("awaiting_slot") or ""

    # Name corrections ("Akhil -> Akhilesh") arrive as a field on the pending
    # draft and are applied here, at the top, so everything below re-runs
    # against the corrected names: matching is re-scored, the register is
    # re-consulted, and the preview is rebuilt. A corrected name is a
    # different person as far as matching is concerned, so a decision already
    # made about the old spelling has to be discarded rather than carried
    # over -- see _apply_name_corrections.
    corrections = fields.pop(NAME_CORRECTIONS_FIELD, None)
    if isinstance(corrections, dict) and corrections:
        lines = _apply_name_corrections(lines, corrections)
        fields["lines"] = lines

    if awaiting.startswith(WORKER_MATCH_SLOT_PREFIX) and answer_text is not None:
        index = _slot_index(awaiting)
        if index is not None and 0 <= index < len(lines):
            line = lines[index]
            # Re-scored rather than remembered: `match_worker` is pure and the
            # candidate list is unchanged, so this reproduces exactly the
            # option list the user was shown — cheaper and less fragile than
            # persisting it.
            result = match_worker(_reported(line), candidates)
            matched = match_slot_answer(answer_text, _slot_candidates(result, candidates))
            if matched is None:
                # Re-ask the same line rather than guessing. Flagged as a retry
                # so the user knows their reply wasn't understood instead of
                # seeing the identical prompt twice.
                return _ask(fields, lines, index, result, candidates, retry=True)
            line["worker_id"] = None if matched == SOMEONE_NEW_SENTINEL else matched
            line[_RESOLVED_FLAG] = True

    for index, line in enumerate(lines):
        if not _needs_match(line):
            continue
        result = match_worker(_reported(line), candidates)
        if result.outcome is MatchOutcome.AUTO_MATCHED:
            line["worker_id"] = result.matched_worker_id
            line[_RESOLVED_FLAG] = True
            continue
        if result.outcome is MatchOutcome.NO_MATCH:
            # Not in the register, and nothing plausible enough to suggest:
            # a temporary worker. Recorded on the line with no worker_id and
            # NOT added to the register (principle P1).
            line["worker_id"] = None
            line[_RESOLVED_FLAG] = True
            continue
        return _ask(fields, lines, index, result, candidates)

    if lines:
        fields["lines"] = lines
    return {"collected_fields": fields, "awaiting_slot": None}


#: Seeded plumbing and workflow bookkeeping, never business fields. Excluded
#: from the draft so they neither appear in the confirmation nor reach
#: RecordLabourAttendanceCommand (whose models are `extra: forbid`).
#: `existing_report` and `duplicate_day_answered` are how check_duplicate_day
#: kept its place across passes -- the command needs only the answer itself
#: (`corrects_report_id`), not the bookkeeping that produced it.
#: `day_counted_lines` (BE-10) is read by the save-first reply, never stored.
_INTERNAL_FIELD_KEYS = frozenset(
    {"worker_candidates", "existing_report", "duplicate_day_answered", "day_counted_lines"}
)


def build_draft(state: WorkflowGraphState) -> dict:
    """Map collected fields into a DraftAction. Shape-mapping only — no validation.

    Line-level `worker_match_resolved` flags are stripped here for the same
    reason expense_capture drops `account_candidates`: they are how this
    workflow kept its place, not something the user should see echoed back or
    the backend should receive.
    """
    fields = {
        key: value
        for key, value in (state.get("collected_fields") or {}).items()
        if key not in _INTERNAL_FIELD_KEYS
    }
    if isinstance(fields.get("lines"), list):
        fields["lines"] = [
            {k: v for k, v in line.items() if k != _RESOLVED_FLAG} if isinstance(line, dict) else line
            for line in fields["lines"]
        ]
    draft = DraftActionV2(
        draft_id=new_id("draft"),
        correlation_id=state["correlation_id"],
        workflow_instance_id=state["workflow_instance_id"],
        action_type=DraftActionType.RECORD_LABOUR_ATTENDANCE,
        organization_id=state["organization_id"],
        user_id=state["user_id"],
        project_id=state.get("project_id"),
        site_id=state.get("site_id"),
        fields=fields,
    )
    return {"draft_action": draft}


# --- Confirmation preview --------------------------------------------------

#: Rendered by the summary block above, so they must not also appear as raw
#: key:value lines below it. "recorded_via" is provenance (how the report
#: arrived -- see canonicalization/builder.py) that the command needs but the
#: supervisor confirming a headcount has no reason to see.
_DISPLAY_HIDDEN_FIELD_KEYS = frozenset(
    {
        "lines",
        "attachment_object_keys",
        "media_object_key",
        "project_name",
        "site_name",
        "recorded_via",
        # An opaque uuid tells the supervisor nothing; the confirmation says
        # in words that this replaces the earlier report (see
        # request_confirmation), which is the part that matters.
        "corrects_report_id",
        # Both rendered by the date line in request_confirmation, which reads
        # them together to say whether the date was stated or assumed. Shown
        # as raw key:value lines they would be noise ("occurred_date_source:
        # inferred_at_confirmation" means nothing to a supervisor).
        "occurred_date",
        "occurred_date_source",
    }
)


def _date_line(fields: dict[str, Any]) -> str | None:
    """The day being recorded, marked when Mesiri guessed it.

    Shown because attendance is append-only: a wrong date cannot be edited
    afterwards, only superseded, so confirmation is the only cheap moment to
    catch it. Saying "(assumed today)" out loud is the point -- a guess
    presented as fact is what let "yesterday 12 masons worked" get filed
    under today without anyone noticing.
    """
    raw = str(fields.get("occurred_date") or "").strip()
    if not raw:
        return None
    try:
        shown = date.fromisoformat(raw).strftime("%d %b %Y")
    except ValueError:
        shown = raw
    if str(fields.get("occurred_date_source") or "") == "inferred_at_confirmation":
        return f"   • Date: {shown} (assumed today)"
    return f"   • Date: {shown}"


def _fmt_amount(value: object) -> str:
    """Render an amount without a noisy trailing .00. Mirrors the helper in
    workflows/account_balance_query/nodes.py."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    if number == number.to_integral_value():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def _line_summary(line: dict[str, Any]) -> str:
    """One attendance line, rendered as the site would say it.

    Named workers and headcount groups read differently on purpose — "Ravi —
    mason" and "12 × helper" are how the report was given, and echoing it back
    in the same shape is what lets someone check it at a glance (principle P9).
    """
    trade = _pretty_trade(normalize_trade(line.get("trade")))
    wage = line.get("daily_wage")
    name = str(line.get("worker_name") or "").strip()
    try:
        headcount = int(line.get("headcount", 1))
    except (TypeError, ValueError):
        headcount = 1

    if name:
        # A name transliterated from Malayalam/Hindi/Tamil is shown beside the
        # original spelling ("Ravi (രവി)"). Confirmation is the one moment
        # someone is actually looking at this, and the supervisor is far better
        # placed than we are to catch a wrong reading — but only if they can
        # see what was on the paper.
        original = str(line.get("worker_name_original") or "").strip()
        display = f"{name} ({original})" if original and original != name else name
        parts = [display]
        if trade:
            parts.append(trade)
        if wage is not None:
            parts.append(f"₹{_fmt_amount(wage)}")
        marker = _status_marker(line)
        if marker:
            parts.append(marker)
        return " — ".join(parts)

    label = f"{headcount} × {trade}" if trade else f"{headcount} workers"
    if wage is not None:
        label = f"{label} — ₹{_fmt_amount(wage)} each"
    marker = _status_marker(line)
    if marker:
        label = f"{label} — {marker}"
    return label


def _status_marker(line: dict[str, Any]) -> str | None:
    """How a non-present line is flagged in the confirmation.

    Only ever shown for absent or half-day: annotating every present line
    would bury the two that matter in noise. Attendance cannot be edited after
    confirmation (P5), so this is the one moment a misread P/A/H column can be
    caught."""
    status = str(line.get("attendance_status") or "present")
    if status == "absent":
        return "absent"
    if status == "half_day":
        return "half day"
    return None


def _totals(lines: list[dict[str, Any]]) -> tuple[int, Decimal]:
    """Headcount and cost. Operational cost only — not payroll: no overtime
    pay, no deductions, no statutory contributions (all explicitly out of
    scope).

    Absent lines are skipped and half days are halved, so the number the
    supervisor is asked to confirm is people who worked, not rows on the
    sheet. A photographed muster roll lists the whole crew including the
    absentees; counting those would put a day's wage against someone the
    sheet says was not there. Kept in step with _line_totals in
    repositories/workforce.py -- the dashboard and this confirmation have
    disagreed about the same report once already.
    """
    headcount = 0
    cost = Decimal("0")
    for line in lines:
        status = str(line.get("attendance_status") or "present")
        if status == "absent":
            continue
        fraction = Decimal("0.5") if status == "half_day" else Decimal("1")
        try:
            count = int(line.get("headcount", 1))
        except (TypeError, ValueError):
            count = 1
        headcount += count
        wage = line.get("daily_wage")
        if wage is None:
            continue
        try:
            cost += Decimal(str(wage)) * count * fraction
        except (InvalidOperation, ValueError):
            continue
    return headcount, cost


def request_confirmation(state: WorkflowGraphState) -> dict:
    """Compose the confirmation prompt — the gate nothing is persisted before
    (principle P2).

    Unlike material's and expense's previews, this does not simply dump
    `draft.fields` as key:value lines: Labour's central field is a *list* of
    lines, which would render as raw dicts and be unreadable exactly when the
    user most needs to check it. Deterministic formatting only — no
    localization, templates or AI generation here (see workflows/material/
    nodes.py).

    Project and site are shown by name when the caller seeded them, and
    omitted otherwise: a bare UUID is worse than saying nothing.
    """
    draft: DraftActionV2 = state["draft_action"]
    fields = draft.fields
    raw_lines = fields.get("lines")
    lines_data = [line for line in raw_lines if isinstance(line, dict)] if isinstance(raw_lines, list) else []
    headcount, cost = _totals(lines_data)

    out = ["*Confirm this record?*", "", "👷 Labour Attendance"]

    project_name = (state.get("collected_fields") or {}).get("project_name")
    site_name = (state.get("collected_fields") or {}).get("site_name")
    if project_name:
        out.append(f"   • Project: {project_name}")
    if site_name:
        out.append(f"   • Site: {site_name}")
    date_line = _date_line(fields)
    if date_line:
        out.append(date_line)

    out.extend(field_lines(fields, skip=_DISPLAY_HIDDEN_FIELD_KEYS))

    if lines_data:
        out.append("")
        for line in lines_data:
            out.append(f"   • {_line_summary(line)}")
        out.append("")
        out.append(f"   {headcount} worker{'s' if headcount != 1 else ''}")
        if cost > 0:
            out.append(f"   Total: ₹{_fmt_amount(cost)}")

    if fields.get("attachment_object_keys") or fields.get("media_object_key"):
        out.append("   • 📎 Attendance sheet attached")

    # Stated in words rather than left implicit. Replacing is the one answer
    # that changes what an existing record counts for, and this is the last
    # moment before it happens -- attendance cannot be edited afterwards (P5).
    if fields.get("corrects_report_id"):
        out.append("")
        out.append("   ♻️ This replaces your earlier report for this day.")

    out.append("")
    out.append("Reply YES to confirm or NO to cancel.")
    return {"pending_prompt": "\n".join(out)}
