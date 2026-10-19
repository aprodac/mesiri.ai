"""Shared single-choice slot-filling helper for LangGraph workflow nodes.

Pure -- no I/O, no AI calls, no DB. Candidate lists are seeded into a node's
`collected_fields` by the caller before the graph runs (a node must never
query a repository itself, see workflows/runtime.py's docstring); this module
only decides whether to auto-fill, ask, or leave a field unset, and matches a
free-text/numbered reply back against the same candidate list. One instance
of this pattern is reused by every finance workflow that needs to ask "which
one?" -- expense_capture's account slot today, transfers/petty cash later
(see docs/execution/FINANCE_MODULE_PLAN.md's Slice 1).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Opens every "that wasn't one of the choices" re-ask. The interaction layer
#: recognises a re-ask by this prefix (is_retry_prompt) to give a question at
#: most one second chance -- see interactions/handler.py's handle_slot_answer.
RETRY_PREFIX = "I couldn't tell which one you meant."
#: Promotion's own, friendlier re-ask (workflows/worker_promotion/nodes.py).
PROMOTION_RETRY_PREFIX = "No worries."


def is_retry_prompt(prompt: str | None) -> bool:
    """True when ``prompt`` is a slot question's second ask."""
    return bool(prompt) and prompt.lstrip().startswith((RETRY_PREFIX, PROMOTION_RETRY_PREFIX))


#: Ids of the worker-promotion question buttons (workflows/worker_promotion/
#: wording.py). Options carrying them are shown as reply buttons, and a tap is
#: handed to the workflow as the id, so the title can be in any language.
BUTTON_ID_PREFIXES = ("promo_", "dup_")

#: Told to the sender when a question that is not about worker promotion was
#: set aside because their message was something else.
QUESTION_DROPPED_NOTE = "I've set that question aside. Send it again whenever you like."

_GREETINGS = frozenset(
    {"hi", "hii", "hiii", "hello", "hey", "heyy", "hai", "namaste", "namaskaram", "thanks",
     "thankyou", "ok", "okay", "good", "gm", "mesiri", "mesii", "mesi"}
)
#: Words that, alone, are an answer to some question rather than a new message.
_ANSWER_WORDS = frozenset({"ok", "okay", "thanks"})
#: A reply this long is a sentence about something, not a pick from a list.
_MAX_ANSWER_WORDS = 3


def looks_unrelated(text: str | None) -> bool:
    """True when ``text`` is plainly not an answer to a pick-from-a-list
    question: a greeting, a question, or a sentence ("I have a work on new
    site", "Today 5 workers came"). Anything short that merely failed to
    match -- a typo, a half name -- is not, and gets one friendly re-ask."""
    words = "".join(c if c.isalnum() or c.isspace() else " " for c in (text or "").lower()).split()
    if not words:
        return False
    if "?" in (text or ""):
        return True
    if len(words) > _MAX_ANSWER_WORDS:
        return True
    return words[0] in _GREETINGS and not (len(words) == 1 and words[0] in _ANSWER_WORDS)


@dataclass(frozen=True, slots=True)
class SlotCandidate:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class SlotResolution:
    """Outcome of resolving one single-choice slot for a single node pass.

    Exactly one of `resolved_value` or `awaiting_slot` is set -- never both,
    never neither (0 candidates resolves to `resolved_value=None` with no
    question asked, since there is nothing to choose between).
    """

    resolved_value: str | None
    awaiting_slot: str | None
    slot_prompt: str | None

    def __post_init__(self) -> None:
        if self.awaiting_slot is not None and self.slot_prompt is None:
            raise ValueError("awaiting_slot requires a slot_prompt")
        if self.awaiting_slot is not None and self.resolved_value is not None:
            raise ValueError("a slot cannot be both resolved and awaiting an answer")


def resolve_single_choice_slot(
    *, slot_name: str, prompt_title: str, candidates: list[SlotCandidate]
) -> SlotResolution:
    """0 candidates -> proceed unset (nothing to choose between). 1 candidate
    -> auto-fill silently, never ask when there is no real ambiguity. N
    candidates -> ask, as a numbered list."""
    if not candidates:
        return SlotResolution(resolved_value=None, awaiting_slot=None, slot_prompt=None)
    if len(candidates) == 1:
        return SlotResolution(
            resolved_value=candidates[0].value, awaiting_slot=None, slot_prompt=None
        )
    return SlotResolution(
        resolved_value=None,
        awaiting_slot=slot_name,
        slot_prompt=_format_prompt(prompt_title, candidates),
    )


def match_slot_answer(text: str, candidates: list[SlotCandidate]) -> str | None:
    """Match a numbered or free-text reply against candidate labels.

    Numbered replies ("2") are the fast path; free text matches case-
    insensitively against a candidate's label (exact or substring either
    direction, so "site cash" matches "Site Cash" and a slightly longer
    phrase like "from site cash please" still matches). Returns None when
    nothing matches -- the caller re-asks rather than guessing.
    """
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.isdigit():
        index = int(stripped) - 1
        if 0 <= index < len(candidates):
            return candidates[index].value
    lowered = stripped.lower()
    for candidate in candidates:
        label_lower = candidate.label.lower()
        if lowered == label_lower or lowered in label_lower or label_lower in lowered:
            return candidate.value
    return None


def slot_options(candidates: list[SlotCandidate]) -> list[dict[str, str]]:
    """Plain-dict form of a candidate list, for a node to attach to its
    return dict as `awaiting_slot_options` alongside `awaiting_slot`/
    `pending_prompt` -- the send side (runtime/inbound_journey.py) turns
    this into a real WhatsApp interactive list so the question is tappable,
    not just a numbered block of text. `match_slot_answer` already accepts
    free text, so a tapped row (which comes back as `NormalizedMessage.text
    = title`, see ingress/normalization.py's `_resolve_interactive_reply`)
    is matched exactly the same way a typed reply would be -- no new
    parsing needed on the way back in."""
    return [{"value": c.value, "label": c.label} for c in candidates]


def _format_prompt(title: str, candidates: list[SlotCandidate]) -> str:
    lines = [title, ""]
    lines.extend(f"{i}. {c.label}" for i, c in enumerate(candidates, start=1))
    lines.append("")
    lines.append("Reply with a number, or just tell me which one.")
    return "\n".join(lines)
