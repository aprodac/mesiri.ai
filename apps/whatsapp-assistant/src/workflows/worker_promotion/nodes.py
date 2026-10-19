"""Worker promotion workflow nodes — pure functions, no I/O, no SQL, no LangGraph.

The optional step *after* attendance is already recorded: offer to add the
newly-seen named temporary workers to the permanent Worker Register. It never
runs before attendance is saved, and never blocks or slows it (plan
principles P1 + P9 — record fast, manage the register later).

The single re-entrant node ``offer_and_promote`` handles up to three passes:

Pass 1 (no slot filled):
    List the named temporary workers and ask which to add. Answers are given
    **by name**, not by list number -- on a 15-worker report, numbers are
    unreadable on a phone and easy to mis-key.

Pass 2 (``promotion_choice`` answered):
    Resolve the chosen names, then run the duplicate check: score each
    against the existing register on name + trade + contractor (the same
    domain scorer attendance matching uses). Anyone with no likely match is
    created immediately. Anyone who *does* look like an existing worker is
    held back for one confirming question rather than silently creating a
    second record for the same person.

Pass 3 (``promotion_duplicate_check`` answered, only when pass 2 held someone):
    Whoever the user says is genuinely a different person gets created; the
    rest are left alone, already being in the register.

**I/O isolation.** The register snapshot is *seeded* into the state by the
caller (runtime/inbound_journey.py), the same pattern that worker candidates
are seeded for ``match_workers`` in the labour_update workflow. This node
decides but never writes: whoever it concludes should be added is listed
under ``WORKERS_TO_CREATE`` in the returned state, and the caller performs
the inserts.

That split is not stylistic. This state is persisted between messages with
``model_dump_json()``, so a create-callable seeded in alongside the data
would fail to serialize outright -- and even if it didn't, ``provide_input``
rebuilds the fields from the database on the next message, so the callable
would be gone by the pass that needed it. Both failures were silent: the
save raised, the run was recorded as failed, and the offer simply never
arrived.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mesiri.domains.workforce.matching import (
    ReportedWorker,
    WorkerCandidate,
    score_candidate,
)
from mesiri.domains.workforce.workers import normalize_name

from ..slots import SlotCandidate, slot_options
from ..state import WorkflowGraphState
from . import wording

#: Slot holding "which of these workers should I add?".
PROMOTION_SLOT = "promotion_choice"
#: Slot holding "which of these are actually different people?".
DUPLICATE_SLOT = "promotion_duplicate_check"

#: Any register entry scoring at or above this is worth one question before a
#: new permanent worker is created.
#:
#: Deliberately lower than matching.ASK, which governs the *attendance* path.
#: There, a question costs the supervisor time mid-report, so the threshold is
#: set to keep interruptions rare (P9). Here attendance is already saved and
#: the entire purpose of the step is to avoid a duplicate register entry, so
#: the trade-off inverts: asking is nearly free, and a wrong silent write is
#: permanent. At 0.20 this catches the case ASK misses -- a partial name whose
#: score was pulled under ASK by a trade mismatch ("Ajith, painter" against
#: registered "Ajith Kumar, mason"), which is a trade change at least as often
#: as it is a second person. Below it there is no name overlap at all, and
#: trade or contractor alone must never suggest a specific person (P4).
_DUPLICATE_SUSPICION = 0.20

_NONE_WORDS = frozenset(
    {
        "none",
        "no",
        "not",
        "now",
        "skip",
        "nope",
        "cancel",
        "later",
        "nobody",
        "nothing",
        "dont",
        "don't",
    }
)
_ALL_WORDS = frozenset({"all", "both", "everyone", "everybody", "yes", "yeah", "yep", "ok", "okay"})
#: Typed or tapped, "Choose": let me pick which of them to add.
_CHOOSE_WORDS = frozenset({"choose", "select", "pick", "some", "few"})
_ADD_VERBS = frozenset({"add", "save", "register", "keep", "make", "mark", "put"})
#: "Is it the same person?" -- the three answers, tapped (ids) or typed.
_SAME_WORDS = frozenset({"same", "yes", "yeah", "yep", "ok", "okay", "already", "sure"})
_NEW_WORDS = frozenset({"new", "different", "another", "separate", "no", "nope", "nah"})
_SKIP_WORDS = frozenset(
    {"skip", "none", "nobody", "cancel", "later", "nothing", "not", "dont", "don't", "unsure"}
)
#: Most look-alikes asked about in one go; the rest stay temporary. Three
#: questions is already a lot to put to someone on a site.
_MAX_DUPLICATE_QUESTIONS = 3
#: A reply longer than this that is not made of answer words and listed names
#: is a sentence about something else, not an answer.
_MAX_SHORT_REPLY_WORDS = 3

#: Words that carry no selection meaning here -- the reply is *already* an
#: answer to "which of these should I add?", so the verb around it is noise.
#: Without stripping these, the entirely natural "save all" fell through to
#: name matching, matched nobody, and re-asked the same question forever.
_FILLER_WORDS = frozenset(
    {
        "save",
        "saving",
        "add",
        "adding",
        "register",
        "registering",
        "keep",
        "make",
        "mark",
        "set",
        "put",
        "please",
        "pls",
        "plz",
        "them",
        "these",
        "those",
        "it",
        "to",
        "the",
        "my",
        "our",
        "as",
        "in",
        "into",
        "on",
        "of",
        "and",
        "worker",
        "workers",
        "permanent",
        "permanently",
        "list",
        "thanks",
        "thank",
        "you",
    }
)

#: A reply carrying one of these names people to *leave out*, and this parser
#: reads names as people to put in -- so "all except Rahul" would otherwise
#: select exactly the one person the user excluded. Exclusions are re-asked
#: rather than guessed at: a wrongly added worker cannot be undone from
#: WhatsApp, and one extra question costs nothing here.
_EXCLUSION_WORDS = frozenset({"except", "but", "besides", "apart", "without", "excluding"})


# --- Helpers -----------------------------------------------------------------


def _promotable(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Named temporary workers the caller seeded for this workflow."""
    raw = fields.get("promotable_workers")
    if not isinstance(raw, list):
        return []
    return [w for w in raw if isinstance(w, dict) and str(w.get("name") or "").strip()]


def _pretty_trade(trade: str | None) -> str:
    return (trade or "").replace("_", " ").strip().title()


def _describe(worker: dict[str, Any]) -> str:
    trade = _pretty_trade(worker.get("trade"))
    return f"{worker['name']} – {trade}" if trade else str(worker["name"])


def _example_names(workers: list[dict[str, Any]]) -> str:
    """A worked example built from the names actually on screen, so the reply
    format is unambiguous without generalising from placeholders."""
    names = [str(w["name"]) for w in workers]
    return ", ".join(names[:2]) if len(names) > 1 else names[0]


def _names_of(workers: list[dict[str, Any]]) -> list[str]:
    return [str(w["name"]) for w in workers]


def _build_offer_message(workers: list[dict[str, Any]]) -> str:
    template = wording.OFFER_ONE if len(workers) == 1 else wording.OFFER_MANY
    question = template.format(names=wording.join_names(_names_of(workers)))
    return f"{wording.INTRO}\n\n{question}"


def _offer_options(workers: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The buttons under the offer: add them / pick some / not now."""
    if len(workers) == 1:
        add = SlotCandidate(wording.ID_ADD_ALL, wording.TITLE_ADD_ONE)
        options = [add, SlotCandidate(wording.ID_NOT_NOW, wording.TITLE_NOT_NOW)]
    else:
        title = wording.TITLE_ADD_BOTH if len(workers) == 2 else wording.TITLE_ADD_ALL
        options = [
            SlotCandidate(wording.ID_ADD_ALL, title),
            SlotCandidate(wording.ID_CHOOSE, wording.TITLE_CHOOSE),
            SlotCandidate(wording.ID_NOT_NOW, wording.TITLE_NOT_NOW),
        ]
    return slot_options(options)


def _duplicate_options() -> list[dict[str, str]]:
    return slot_options(
        [
            SlotCandidate(wording.ID_SAME, wording.TITLE_SAME),
            SlotCandidate(wording.ID_NEW, wording.TITLE_NEW),
            SlotCandidate(wording.ID_SKIP, wording.TITLE_SKIP),
        ]
    )


def _select_by_name(text: str, workers: list[dict[str, Any]]) -> list[int] | None:
    """Resolve a free-text reply to indices into ``workers``.

    Accepts "all", "none", or any list of names in any separator style
    ("Ajith, Rahul" / "Ajith and Rahul" / "ajith rahul"). Matching is on
    normalized names; a reply naming nobody recognisable returns None so the
    question is re-asked rather than silently doing nothing.
    """
    normalized_reply = normalize_name(text)
    if not normalized_reply:
        return None
    reply_tokens = set(normalized_reply.split())

    # An exclusion ("all except Rahul") names who to leave out, and everything
    # below reads names as who to put in. Re-ask instead of inverting the
    # user's meaning.
    if reply_tokens & _EXCLUSION_WORDS:
        return None

    # A sentence that merely mentions a listed name ("I have work on Anil's
    # site") is not a pick: any long reply with words that are neither names
    # nor answers is left to be re-asked or closed, never read as "add Anil".
    answer_words = _ALL_WORDS | _NONE_WORDS | _CHOOSE_WORDS | _FILLER_WORDS | _ADD_VERBS
    known = {tok for w in workers for tok in normalize_name(str(w["name"])).split()}
    strangers = reply_tokens - answer_words - known - {"also", "only", "just", "plus"}
    if strangers and len(normalized_reply.split()) > _MAX_SHORT_REPLY_WORDS:
        return None

    # "all" / "none", however they are phrased. Read from the words that are
    # left once the filler verbs are removed, rather than by matching the whole
    # reply against a fixed list of phrasings -- that list can never be
    # complete, and "save all" (which it did not contain) is the most natural
    # way to say yes.
    meaningful = reply_tokens - _FILLER_WORDS
    # A name on the list always wins over a keyword, so a worker called
    # "Sabu" is still selectable even though the reply reads like filler.
    listed = {token for worker in workers for token in normalize_name(str(worker["name"])).split()}
    meaningful -= listed
    # A bare "add" / "save it" (the "Add" button, typed) names nobody, so it
    # means everyone offered -- but "add Anil" has a listed name in it and
    # must not.
    if not meaningful and not (reply_tokens & listed) and reply_tokens & _ADD_VERBS:
        return list(range(len(workers)))
    if meaningful and meaningful <= _ALL_WORDS:
        return list(range(len(workers)))
    if meaningful and meaningful <= _NONE_WORDS:
        return []

    chosen: set[int] = set()
    for i, worker in enumerate(workers):
        worker_name = normalize_name(str(worker["name"]))
        if not worker_name:
            continue
        # The whole name as a phrase ("ravi kumar"), or every token of it
        # present somewhere in the reply.
        if worker_name in normalized_reply or set(worker_name.split()) <= reply_tokens:
            chosen.add(i)

    # Then part of a name: typing "Ajith" for a listed "Ajith Kumar" is the
    # natural reply, and rejecting it made the question feel broken. Only
    # counted when that part picks out exactly one worker on the list -- with
    # both an "Ajith Kumar" and an "Ajith Nair" offered, "Ajith" is genuinely
    # ambiguous and re-asking beats promoting the wrong person.
    #
    # This runs even when the pass above already matched somebody, because a
    # reply can mix the two: "Ajith and Niyas" against a list holding "Ajith
    # Kumar" and "Niyas" matches Niyas in full and Ajith only in part, and
    # stopping early would silently drop Ajith.
    for token in reply_tokens:
        hits = [
            i
            for i, worker in enumerate(workers)
            if token in normalize_name(str(worker["name"])).split()
        ]
        if len(hits) == 1:
            chosen.add(hits[0])

    return sorted(chosen) or None


def _wants_to_choose(text: str, workers: list[dict[str, Any]]) -> bool:
    """ "Choose" (the button, or typed): show the names, let me pick."""
    tokens = set(normalize_name(text).split())
    listed = {tok for w in workers for tok in normalize_name(str(w["name"])).split()}
    meaningful = (tokens - _FILLER_WORDS) - listed
    return bool(meaningful) and meaningful <= _CHOOSE_WORDS


def _parse_same_new_skip(text: str) -> str | None:
    """ "same" / "new" / "skip" from a tap or a typed reply; None when it is
    none of the three. "Skip" outranks the others, so "not sure" and "no,
    skip it" never create a worker."""
    reply = normalize_name(text)
    if reply in ("1", "2", "3"):  # the buttons' order, typed as a number
        return {"1": "same", "2": "new", "3": "skip"}[reply]
    tokens = set(reply.split())
    if len(reply.split()) > _MAX_SHORT_REPLY_WORDS:
        return None  # "I have a work on new site" is not "new person"
    if tokens & _SKIP_WORDS:
        return "skip"
    if tokens & _NEW_WORDS:
        return "new"
    if tokens & _SAME_WORDS:
        return "same"
    return None


def _named_answer(text: str, held: dict[str, Any]) -> str | None:
    """A typed name at "is it the same person?" (owner's decision, 19 Oct):
    the look-alike's own name means "a new person with this name", the existing
    worker's name means "the same person". None for anything else."""
    reply = normalize_name(text)
    if not reply:
        return None
    new, old = (
        normalize_name(str(held.get("name") or "")),
        normalize_name(str(held.get("_similar_to") or "")),
    )
    if reply == new and reply != old:
        return "new"
    if reply == old and reply != new:
        return "same"
    return None


def _as_candidates(register: list[Any]) -> list[WorkerCandidate]:
    out: list[WorkerCandidate] = []
    for row in register:
        if not isinstance(row, dict) or not row.get("worker_id"):
            continue
        out.append(
            WorkerCandidate(
                worker_id=str(row["worker_id"]),
                name=str(row.get("name") or ""),
                trade=row.get("trade"),
                contractor=row.get("contractor"),
            )
        )
    return out


def _register_since(fields: dict[str, Any], worker_id: str) -> Any:
    for row in fields.get("_register") or []:
        if isinstance(row, dict) and str(row.get("worker_id")) == worker_id:
            return row.get("since")
    return None


def _likely_existing(
    worker: dict[str, Any], register: list[WorkerCandidate]
) -> WorkerCandidate | None:
    """The existing register entry this worker probably already is.

    Scores with the shared domain scorer on name + trade + contractor, against
    _DUPLICATE_SUSPICION rather than match_worker's attendance-tuned bands.
    Deliberately passes no site/project history: this asks "is this person
    already in the register?", which has nothing to do with where they have
    worked.
    """
    if not register:
        return None
    reported = ReportedWorker(
        name=str(worker["name"]),
        trade=worker.get("trade"),
        contractor=worker.get("contractor"),
    )
    best = max(
        ((score_candidate(reported, c), c) for c in register),
        key=lambda pair: pair[0].confidence,
        default=None,
    )
    if best is None or best[0].confidence < _DUPLICATE_SUSPICION:
        return None
    return best[1]


def _since(iso: Any) -> str | None:
    """ "2 Oct" from an ISO date, None when there is none."""
    try:
        day = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None
    return f"{day.day} {day.strftime('%b')}"


def _detail(held: dict[str, Any]) -> str:
    """ " (mason, since 2 Oct)" -- what the sender knows the register entry by."""
    parts = [
        p
        for p in (
            _pretty_trade(held.get("_similar_trade")).lower(),
            _since(held.get("_similar_since")),
        )
        if p
    ]
    if not parts:
        return ""
    if len(parts) == 2:
        return f" ({parts[0]}, since {parts[1]})"
    return f" ({parts[0]})" if held.get("_similar_trade") else f" (since {parts[0]})"


def _duplicate_question(held: list[dict[str, Any]], index: int, *, retry: bool = False) -> str:
    w = held[index]
    new, old = wording.bold(w["name"]), wording.bold(w["_similar_to"])
    if retry:
        return wording.RETRY_LOOKS_LIKE.format(new=new, old=old)
    template = wording.LOOKS_LIKE if index == 0 else wording.LOOKS_LIKE_NEXT
    question = template.format(new=new, old=old, detail=_detail(w))
    return f"{wording.INTRO}\n\n{question}" if index == 0 else question


#: Key under which the node hands the caller the workers it decided to add.
#: Plain JSON-safe dicts, because this survives a trip through Postgres.
WORKERS_TO_CREATE = "workers_to_create"


def _queue_for_creation(workers: list[dict[str, Any]], fields: dict[str, Any]) -> list[str]:
    """Record which workers the caller should write. Returns their names.

    The node decides; it never writes. Nodes are pure (no I/O, no
    repositories -- see workflows/runtime.py), and this state is persisted
    between messages with model_dump_json(), so a callable smuggled in here
    would neither serialize nor survive to the pass that needed it. The
    caller picks these up from WorkflowRunResult.collected_fields.
    """
    queued = [
        {
            "name": str(worker["name"]),
            "trade": worker.get("trade"),
            "daily_wage": worker.get("daily_wage"),
        }
        for worker in workers
    ]
    fields[WORKERS_TO_CREATE] = queued
    return [w["name"] for w in queued]


def _closing_message(queued: list[str]) -> str:
    # "stay as temporary" and "made permanent" are both literally true now:
    # recording the attendance already gave everyone named a register row
    # marked temporary, and promotion flips that same row to permanent rather
    # than creating a second one (see labour_execution._ensure_worker_identities).
    if not queued:
        return wording.NONE_ADDED
    return wording.MADE_PERMANENT.format(names=", ".join(queued))


def _duplicates_closing(
    queued: list[str], same: list[dict[str, Any]], kept: list[dict[str, Any]]
) -> str:
    """One summary for the whole look-alike round: who was added, who was
    already there, who is left as a separate temporary name."""
    lines: list[str] = []
    if queued:
        lines.append(wording.MADE_PERMANENT.format(names=", ".join(queued)))
    for w in same:
        lines.append(
            wording.SAME_NOT_ADDED.format(
                new=wording.bold(w["name"]), old=wording.bold(w["_similar_to"])
            )
        )
    if kept:
        lines.append(wording.KEPT_SEPARATE.format(names=wording.join_names(_names_of(kept))))
    return "\n".join(lines) if lines else wording.NONE_ADDED


def _ask(
    prompt: str, slot: str, fields: dict[str, Any], options: list[dict[str, str]] | None = None
) -> dict:
    out = {"collected_fields": fields, "awaiting_slot": slot, "pending_prompt": prompt}
    if options:
        out["awaiting_slot_options"] = options
    return out


def _done(prompt: str, fields: dict[str, Any]) -> dict:
    return {
        "collected_fields": fields,
        "awaiting_slot": None,
        "awaiting_slot_options": None,
        "pending_prompt": prompt,
    }


def _ask_next_duplicate(fields: dict[str, Any]) -> dict | None:
    """The question for the next look-alike, or None when none is left."""
    held: list[dict[str, Any]] = list(fields.get("_held_for_duplicate_check") or [])
    index = int(fields.get("_dup_index") or 0)
    if index >= min(len(held), _MAX_DUPLICATE_QUESTIONS):
        return None
    return _ask(_duplicate_question(held, index), DUPLICATE_SLOT, fields, _duplicate_options())


def _finish_duplicates(fields: dict[str, Any]) -> dict:
    """Everyone asked about has been decided (or the sender skipped the rest):
    add those confirmed as new, leave every other look-alike as it is."""
    held: list[dict[str, Any]] = list(fields.get("_held_for_duplicate_check") or [])
    confirmed_new = list(fields.get("_confirmed_new") or [])
    same = list(fields.get("_confirmed_same") or [])
    decided = {w["name"] for w in confirmed_new} | {w["name"] for w in same}
    kept = [w for w in held if w["name"] not in decided]
    already = list(fields.get("_cleared_so_far") or [])
    queued = _queue_for_creation(already + confirmed_new, fields)
    return _done(_duplicates_closing(queued, same, kept), fields)


# --- Node --------------------------------------------------------------------


def offer_and_promote(state: WorkflowGraphState) -> dict:
    """Re-entrant node — see module docstring for the three-pass semantics."""
    fields = dict(state.get("collected_fields") or {})
    workers = _promotable(fields)

    # Guard: only ever reached via inbound_journey's direct instantiation, and
    # only when it found named temps. An empty list means the caller made a
    # mistake -- complete neutrally rather than sending an empty offer.
    if not workers:
        return {"collected_fields": fields, "awaiting_slot": None, "pending_prompt": None}

    answer = fields.pop("_slot_answer_text", None)
    if isinstance(answer, str):
        # A tapped button arrives as its id; typed words fall through as they are.
        answer = wording.ID_ANSWERS.get(answer.strip(), answer)
    awaiting = state.get("awaiting_slot")
    register = _as_candidates(fields.get("_register") or [])

    # --- Pass 3: is each look-alike the same person, or a new one? -----------
    if awaiting == DUPLICATE_SLOT and answer is not None:
        held: list[dict[str, Any]] = list(fields.get("_held_for_duplicate_check") or [])
        index = int(fields.get("_dup_index") or 0)
        choice = _parse_same_new_skip(answer)
        if choice is None and index < len(held):
            choice = _named_answer(answer, held[index])
        if choice is None or index >= len(held):
            if index >= len(held):
                return _finish_duplicates(fields)
            return _ask(
                _duplicate_question(held, index, retry=True),
                DUPLICATE_SLOT,
                fields,
                _duplicate_options(),
            )
        if choice == "skip":
            # "I'm not sure": nobody else is asked about, nobody is added from
            # this round (those already cleared still are).
            return _finish_duplicates(fields)
        key = "_confirmed_new" if choice == "new" else "_confirmed_same"
        fields[key] = list(fields.get(key) or []) + [held[index]]
        fields["_dup_index"] = index + 1
        return _ask_next_duplicate(fields) or _finish_duplicates(fields)

    # --- Pass 2: resolve the chosen names, then screen for duplicates --------
    if awaiting == PROMOTION_SLOT and answer is not None:
        if not fields.get("_choosing") and _wants_to_choose(answer, workers):
            fields["_choosing"] = True
            example = _example_names(workers)
            return _ask(
                wording.CHOOSE.format(example=example),
                PROMOTION_SLOT,
                fields,
                slot_options(
                    [
                        SlotCandidate(wording.ID_ADD_ALL, wording.TITLE_ADD_ALL),
                        SlotCandidate(wording.ID_NOT_NOW, wording.TITLE_NOT_NOW),
                    ]
                ),
            )
        selection = _select_by_name(answer, workers)
        if selection is None:
            if fields.get("_choosing"):
                prompt = wording.RETRY_CHOOSE.format(example=_example_names(workers))
                options = slot_options(
                    [
                        SlotCandidate(wording.ID_ADD_ALL, wording.TITLE_ADD_ALL),
                        SlotCandidate(wording.ID_NOT_NOW, wording.TITLE_NOT_NOW),
                    ]
                )
            else:
                prompt = wording.RETRY_OFFER.format(names=wording.join_names(_names_of(workers)))
                options = _offer_options(workers)
            return _ask(prompt, PROMOTION_SLOT, fields, options)
        if not selection:
            return _done(_closing_message([]), fields)

        clear: list[dict[str, Any]] = []
        held = []
        for i in selection:
            worker = workers[i]
            similar = _likely_existing(worker, register)
            if similar:
                held.append(
                    {
                        **worker,
                        "_similar_to": similar.name,
                        "_similar_trade": similar.trade,
                        "_similar_since": _register_since(fields, similar.worker_id),
                    }
                )
            else:
                clear.append(worker)

        if held:
            fields["_held_for_duplicate_check"] = held
            fields["_dup_index"] = 0
            # Carried so the run ends with one closing summary covering both
            # halves, rather than two partial ones.
            fields["_cleared_so_far"] = clear
            fields.pop("_choosing", None)
            return _ask_next_duplicate(fields) or _finish_duplicates(fields)

        queued = _queue_for_creation(clear, fields)
        return _done(_closing_message(queued), fields)

    # --- Pass 1: the offer ---------------------------------------------------
    return _ask(_build_offer_message(workers), PROMOTION_SLOT, fields, _offer_options(workers))
