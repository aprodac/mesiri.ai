"""The agent loop for one message: run the model with the tools, then turn
what happened into the ONE reply.

Failure policy (writes make a retry unsafe):
- the model/provider fails before any record was attempted -> "outage": the
  caller says it will process this in a few minutes and retries the message
  (the classic outage path, runtime/ai_outage.py);
- it fails after a record was attempted -> never retried; the sender gets what
  was saved and is told to check the rest;
- a deadline that passes mid-save lets the save finish first (the toolbox
  shields it), so the reply never forgets or repeats it.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from channel.replies import ReplySpec
from interactions.saved_summary import QUESTION_PREFIX, render_saved
from mesiri_ai.models import ChatMessage, ToolOutcome, ToolRunResult
from mesiri_ai.ports.tool_calling import ToolCallingProvider

from .gateway import WorkflowGateway
from .prompt import SYSTEM_PROMPT, AgentContext, build_messages, is_manglish, letters_of
from .toolbox import AgentToolbox, SavedItem, asks_for_engineer
from .tools import ScopeLookup, tool_specs

_log = logging.getLogger("mesiri.agent")

#: Per message: tool rounds, and the overall deadline (request [40]).
MAX_STEPS = 3
TIMEOUT_SECONDS = 25.0  # a 4-part note is ~2 model rounds + 4 saves; 12s cut it off (request [43])

UNDO_LINE = "Wrong? Reply UNDO."
#: The second try for a Manglish reply is short: past this, English goes out.
MANGLISH_TIMEOUT_SECONDS = 4.0


async def _no_tools(name: str, args: dict) -> ToolOutcome:
    return ToolOutcome(content={"status": "error", "reason": "no tools in this step"})
CHECK_LINE = (
    "I couldn't finish the rest of your message, so please check what is saved and "
    "send anything missing again."
)
NOTHING_LINE = "Sorry, I couldn't work that out. Could you say it again in a few words?"


@dataclass(slots=True)
class AgentResult:
    #: "ok" | "outage" | "degraded"
    outcome: str
    reply: ReplySpec | None
    toolbox: AgentToolbox
    run: ToolRunResult | None = None
    error: BaseException | None = None

    @property
    def saved_count(self) -> int:
        return len(self.toolbox.saved)


class AgentRunner:
    def __init__(
        self,
        provider: ToolCallingProvider,
        *,
        max_steps: int = MAX_STEPS,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._provider = provider
        self._max_steps = max_steps
        self._timeout = timeout_seconds

    async def run(
        self,
        *,
        ctx: AgentContext,
        user_text: str,
        gateway: WorkflowGateway,
        scope: ScopeLookup,
        correlation_id: str | None = None,
        lap: Callable[[str], None] | None = None,
        after_tool: Callable[[], None] | None = None,
    ) -> AgentResult:
        toolbox = AgentToolbox(
            gateway=gateway, scope=scope, user_text=user_text, lap=lap, after_tool=after_tool
        )
        toolbox.engineer_offered = bool(ctx.turns) and asks_for_engineer(ctx.turns[-1].assistant_reply)
        prompt_messages = build_messages(ctx, user_text)
        messages = [ChatMessage(role=r, text=t) for r, t in prompt_messages]
        try:
            run = await self._provider.run_tools(
                SYSTEM_PROMPT,
                messages,
                tool_specs(),
                toolbox.handle,
                max_steps=self._max_steps,
                timeout_seconds=self._timeout,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001 — every provider/model failure lands here
            await toolbox.settle()
            if toolbox.attempted_writes == 0 and toolbox.parked is None:
                _log.warning("agent.outage correlation_id=%s error=%r", correlation_id, exc)
                return AgentResult("outage", None, toolbox, error=exc)
            _log.exception("agent.degraded correlation_id=%s", correlation_id)
            return AgentResult(
                "degraded", self._fallback(toolbox, partial=True), toolbox, error=exc
            )
        await toolbox.settle()
        run = await self._in_manglish(run, messages, user_text, correlation_id)
        # WA-37: every figure the model writes must come from what it was
        # given (the message, the facts in its prompt, a tool result) or from
        # what it handed a tool -- a saved figure is also on the system's own
        # line under the reply, where the sender checks it before Save.
        sources = [text for _, text in prompt_messages]
        for call in run.calls:
            sources.append(json.dumps(call.arguments, ensure_ascii=False, default=str))
            sources.append(json.dumps(call.outcome.content, ensure_ascii=False, default=str))
        return AgentResult("ok", self._compose(run, toolbox, sources, correlation_id), toolbox, run=run)

    async def _in_manglish(
        self,
        run: ToolRunResult,
        messages: list[ChatMessage],
        user_text: str,
        correlation_id: str | None,
    ) -> ToolRunResult:
        """A Manglish message answered in English gets one more try, with no
        tools: the same reply, in Manglish (round 3b, 21 Oct: told to, the
        model still answered English one time in three). Anything going wrong
        keeps the English reply; nothing is run or saved again."""
        text = (run.text or "").strip()
        if not text or not is_manglish(user_text) or is_manglish(text) or letters_of(text) != "latin":
            return run
        ask = (
            "Say your last reply again in Manglish (Malayalam in English letters), the way a "
            "site supervisor texts. Same meaning, same numbers, nothing added. Only the reply."
        )
        try:
            again = await self._provider.run_tools(
                SYSTEM_PROMPT,
                [*messages, ChatMessage(role="model", text=text), ChatMessage(role="user", text=ask)],
                [],
                _no_tools,
                max_steps=1,
                timeout_seconds=MANGLISH_TIMEOUT_SECONDS,
                correlation_id=correlation_id,
            )
        except Exception:  # noqa: BLE001 -- the English reply still goes out
            _log.warning("agent.manglish_retry_failed correlation_id=%s", correlation_id)
            return run
        if not is_manglish(again.text or ""):
            return run
        return run.model_copy(update={"text": again.text})

    # -- the one reply -----------------------------------------------------

    def _compose(
        self,
        run: ToolRunResult,
        toolbox: AgentToolbox,
        sources: list[str],
        correlation_id: str | None = None,
    ) -> ReplySpec:
        text = (run.text or "").strip()
        if _entries(toolbox):
            # Before the Save tap nothing is kept (WA-37).
            text = without_saved_claims(text)
        text = saved_list(_unique_paragraphs(text))
        block = _saved_block(toolbox)
        if block:
            # The model's words come first (WA-37: it talks, it is not a
            # receipt); under them the system's short line of what was saved,
            # built from the saved data (request 57, B3), never the model's own
            # list, which echoed the sender's raw words.
            text = _without_echoed_questions(_without_saved_block(text), toolbox)
        else:
            text = _without_echoed_questions(text, toolbox, saved_list=False)
        unbacked = unbacked_numbers(text, sources)
        leaked = _CODE_WORD.findall(text)
        if leaked:
            # WA-37: "സ്ല clientIdb-ന്" went out on 21 Oct -- a code word is
            # never part of a site reply.
            _log.warning("agent.code_word_guard correlation_id=%s words=%s", correlation_id, leaked)
            text = ""
        if unbacked:
            # A figure the model made up (or worked out) is never sent: the
            # system's own words stand in for the whole reply.
            _log.warning(
                "agent.number_guard correlation_id=%s numbers=%s", correlation_id, sorted(unbacked)
            )
            text = ""
        if block:
            if not text and run.stop_reason == "max_steps":
                text = CHECK_LINE
            text = f"{text}\n\n{block}" if text else block
        asked = _questions_line(toolbox)
        if asked:
            text = f"{text}\n\n{asked}" if text else asked
        if not text:
            return self._fallback(toolbox, partial=run.stop_reason == "max_steps")
        if _entries(toolbox) and "undo" not in text.casefold():
            text = f"{text}\n\n{UNDO_LINE}"
        parked = toolbox.parked
        if parked is None:
            return ReplySpec(text=text)
        if "?" not in text and "？" not in text:
            # The model left the question out: the buttons would hang in the air.
            text = f"{text}\n\n{parked.text}"
        return ReplySpec(
            text=text,
            list_button_label=parked.list_button_label,
            list_rows=parked.list_rows,
            buttons=parked.buttons,
        )

    def _fallback(self, toolbox: AgentToolbox, *, partial: bool) -> ReplySpec:
        """The reply when the model gave no usable text: the pipeline's own
        words for what it did."""
        block = _saved_block(toolbox)
        parts = [block] if block else [item.text for item in toolbox.saved]
        parts.extend(toolbox.answers)
        parked = toolbox.parked
        if parked is not None:
            parts.append(parked.text)
        elif not parts:
            parts.extend(toolbox.notes[:1] or [NOTHING_LINE])
        if partial and (toolbox.saved or toolbox.attempted_writes):
            parts.append(CHECK_LINE)
        text = _unique_paragraphs("\n\n".join(p for p in parts if p))
        if parked is None:
            return ReplySpec(text=text)
        return ReplySpec(
            text=text,
            list_button_label=parked.list_button_label,
            list_rows=parked.list_rows,
            buttons=parked.buttons,
        )


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
#: A camelCase or snake_case identifier ("clientIdb", "site_id"): code, not words.
_CODE_WORD = re.compile(r"\b[a-z]+[A-Z][A-Za-z]*\b|\b[a-z]+_[a-z_]+\b")
#: Words for one thing ("1 more question") need no source.
_ALWAYS_ALLOWED = frozenset({"0", "1"})


def _numbers(text: str) -> set[str]:
    """Every number in ``text``, normalised: "1,500" and "1500.0" are "1500"."""
    found: set[str] = set()
    for raw in _NUMBER.findall(text or ""):
        try:
            value = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            continue
        found.add(format(value.normalize(), "f"))
    return found


def unbacked_numbers(reply: str, sources: list[str]) -> set[str]:
    """WA-37: the numbers in the model's ``reply`` that appear in none of
    ``sources`` (its prompt and its tool results)."""
    allowed = set(_ALWAYS_ALLOWED)
    for source in sources:
        allowed |= _numbers(source)
    return _numbers(reply) - allowed


#: "It is saved / recorded" in the languages the sites write in. Before the
#: Save tap nothing is kept, so a sentence saying so is not true (WA-37).
_SAVED_CLAIM = re.compile(
    r"(?<!not )\b(?:saved|recorded|logged|noted)\b"
    r"|\b(?:save|record|rekhappeduthi|note)\s*(?:cheythu|cheythittund|aakki)"
    r"|സേവ്\s*ചെയ്തു|സേവ്\s*ചെയ്തിട്ടുണ്ട്|രേഖപ്പെടുത്തി|സേവ്\s*ആയി"
    r"|सेव\s*(?:कर\s*)?(?:दिया|किया|हो\s*गया)|दर्ज\s*(?:कर\s*)?(?:दिया|किया|हो\s*गया)",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?।\n]*(?:[.!?।]+|\n|$)")


_CLAUSE = re.compile(r"[^,;]*(?:[,;]\s*|$)")


def _without_claim(sentence: str) -> str:
    """The sentence without its claiming part: "50 bag cement vannu, save
    cheythu." keeps "50 bag cement vannu." (round 3, 21 Oct: dropping the
    whole sentence left the reply with no words of the model's at all)."""
    if not _SAVED_CLAIM.search(sentence):
        return sentence
    # Only what comes before the claim: after it is the claimed list itself
    # ("Saved: 15 workers, 180 sqm plastering, ...").
    kept: list[str] = []
    for clause in (c for c in _CLAUSE.findall(sentence) if c):
        if _SAVED_CLAIM.search(clause):
            break
        kept.append(clause)
    body = "".join(kept).rstrip().rstrip(",;").rstrip()
    if not body:
        return ""
    end = re.search(r"[.!?।]+\s*$|\n$", sentence)
    return body + (end.group(0) if end else "")


def without_saved_claims(text: str) -> str:
    """``text`` without what says an entry is already saved: the claiming
    clause, or the whole sentence when it is nothing else."""
    kept = [_without_claim(part) for part in _SENTENCE.findall(text) if part]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


def _entries(toolbox: AgentToolbox) -> list[SavedItem]:
    """What was saved as an entry. A question passed to the engineer is not
    one (WA-37): the model says it was passed on; it is no line to check."""
    return [
        item for item in toolbox.saved if not (item.summary or "").startswith(QUESTION_PREFIX)
    ]


#: Marks a question the system passed to the engineer (WA-37): said, not saved.
QUESTION_MARK = "📨 "


def _questions_line(toolbox: AgentToolbox) -> str:
    """The questions passed to the engineer, one line each, from the saved
    notes themselves -- so the sender always hears where the question went,
    whatever the model wrote."""
    return "\n".join(
        f"{QUESTION_MARK}{item.summary}"
        for item in toolbox.saved
        if (item.summary or "").startswith(QUESTION_PREFIX)
    )


def _saved_block(toolbox: AgentToolbox) -> str:
    """The deterministic "Saved:" block, when every saved entry has a summary
    (else the model's own wording stands, as before)."""
    entries = _entries(toolbox)
    if not entries or not all(item.summary for item in entries):
        return ""
    return render_saved([item.summary for item in entries if item.summary])


def _normalized(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE).split()).casefold()


def _without_echoed_questions(text: str, toolbox: AgentToolbox, *, saved_list: bool = True) -> str:
    """A question passed to the engineer has its own line; the model repeating
    it back (WA-37: the 21 Oct reply said it twice), or, under a "Saved:" list
    (``saved_list``), any line that only plays back the sender's own words,
    adds nothing (request 57, B2/B3)."""
    asked = {
        _normalized(item.summary[len(QUESTION_PREFIX):])
        for item in toolbox.saved
        if item.summary and item.summary.startswith(QUESTION_PREFIX)
    }
    spoken = _normalized(toolbox.user_text)
    if not text:
        return text
    kept = []
    for line in text.split("\n"):
        norm = _normalized(line)
        # The sender's own words played back ("6 mason, 10 helper vannu") say
        # nothing the "Saved:" list does not, whatever else the line is.
        echo = saved_list and len(norm.split()) >= 3 and norm in spoken
        if echo or any(question and question in norm for question in asked):
            continue
        kept.append(line)
    return "\n".join(kept).strip("\n").strip()


_SAVED_HEAD = re.compile(r"^\s*✅")
_BULLET = re.compile(r"^\s*[•\-\*]\s")


def _without_saved_block(text: str) -> str:
    """The model's text minus any "✅ Saved:" header (with an inline item) and
    the bullets under it, whatever language the model wrote it in."""
    kept: list[str] = []
    dropping = False
    for line in text.split("\n"):
        if _SAVED_HEAD.match(line):
            dropping = True
            continue
        if dropping and _BULLET.match(line):
            continue
        dropping = False
        kept.append(line)
    return "\n".join(kept).strip("\n").strip()


_SAVED_LINE = re.compile(r"^\s*(?:✅\s*)?(?:recorded|saved)\s*:?\s+(?P<what>\S.*)$", re.IGNORECASE)
_TODAY_END = re.compile(r"[\s,]+(?:for\s+|from\s+)?today\s*[.!]?\s*$", re.IGNORECASE)


def saved_list(text: str) -> str:
    """B-9: "Recorded 12 masons present today. / Recorded 5 bags ... today."
    as one header and short bullets, when the model wrote one such line per
    thing despite the prompt. Two or more such lines only; anything else
    (one line, another language) is left as written."""
    lines = text.split("\n")
    hits = [i for i, line in enumerate(lines) if _SAVED_LINE.match(line)]
    if len(hits) < 2:
        return text
    out: list[str] = []
    for i, line in enumerate(lines):
        match = _SAVED_LINE.match(line) if i in hits else None
        if match is None:
            out.append(line)
            continue
        if i == hits[0]:
            out.append("✅ Saved:")
        what = _TODAY_END.sub("", match.group("what")).rstrip(" .")
        out.append(f"• {what[:1].upper()}{what[1:]}")
    return "\n".join(out)


def _unique_paragraphs(text: str) -> str:
    """The same paragraph twice in one reply (a note the model quoted and the
    pipeline's own words) is said once."""
    seen: set[str] = set()
    kept: list[str] = []
    for part in text.split("\n\n"):
        key = " ".join(part.split()).casefold()
        if key and key in seen:
            continue
        seen.add(key)
        kept.append(part)
    return "\n\n".join(kept)


def default_now() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Kolkata"))
