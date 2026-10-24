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
from runtime.reply_composer import BODY_MAX

from .gateway import WorkflowGateway
from .prompt import (
    _MANGLISH_WORDS,
    SYSTEM_PROMPT,
    AgentContext,
    build_messages,
    is_manglish,
    letters_of,
    reply_language,
    reply_letters_rule,
)
from .reply_text import (
    dpr_caption,
    manglish_word_count,
    mixed_script_words,
    sentences,
    trim_at_sentence,
    without_engineer_promise,
    without_manglish,
    without_native_script,
    without_save_prompt,
    without_stray_sentences,
)
from .toolbox import HOURS_QUESTION, AgentToolbox, SavedItem, offers_engineer, tomorrow_plan_text
from .tools import NOTE_FOR_ENGINEER, SET_SITE_CONDITIONS, ScopeLookup, tool_specs

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
        # WA-52: only a reply that OFFERED to ask counts ("Shall I ask your
        # engineer?"), not one that merely named the engineer.
        toolbox.engineer_offered = bool(ctx.turns) and offers_engineer(ctx.turns[-1].assistant_reply)
        # Request 104, D2: the hours-lost question is asked once.
        toolbox.hours_asked = bool(ctx.turns) and HOURS_QUESTION in ctx.turns[-1].assistant_reply
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
        await self._tomorrow_plan(toolbox, user_text)
        run = await self._in_manglish(run, messages, user_text, correlation_id)
        run = await self._one_script(run, messages, user_text, correlation_id)
        run = await self._answer_in_language(run, messages, toolbox, user_text, correlation_id)
        _park_plain_question(run, toolbox)
        # WA-37: every figure the model writes must come from what it was
        # given (the message, the facts in its prompt, a tool result) or from
        # what it handed a tool -- a saved figure is also on the system's own
        # line under the reply, where the sender checks it before Save.
        sources = [text for _, text in prompt_messages]
        for call in run.calls:
            sources.append(json.dumps(call.arguments, ensure_ascii=False, default=str))
            sources.append(json.dumps(call.outcome.content, ensure_ascii=False, default=str))
        if not unbacked_numbers(run.text or "", sources):
            # (a reply with a made-up figure loses that sentence below anyway)
            run = await self._covering(run, messages, toolbox, user_text, correlation_id)
        return AgentResult("ok", self._compose(run, toolbox, sources, correlation_id), toolbox, run=run)

    @staticmethod
    async def _tomorrow_plan(toolbox: AgentToolbox, user_text: str) -> None:
        """Request 104, B: "Tomorrow plan: ..." is never just "noted". When the
        model did not call ``set_site_conditions`` for it, the card is prepared
        here from the message's own words."""
        plan = tomorrow_plan_text(user_text)
        if plan and SET_SITE_CONDITIONS not in toolbox.called and toolbox.parked is None:
            await toolbox.handle(SET_SITE_CONDITIONS, {"tomorrow_plan": plan})

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
        if not text or reply_language(user_text) != "manglish" or is_manglish(text) or letters_of(text) != "latin":
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

    async def _answer_in_language(
        self,
        run: ToolRunResult,
        messages: list[ChatMessage],
        toolbox: AgentToolbox,
        user_text: str,
        correlation_id: str | None,
    ) -> ToolRunResult:
        """Request 90: a lookup's answer (a report, a count) goes through the
        same language decision as every other reply. When the model gave no
        words of its own, the system's English answer would go out as it is
        ("innale report ayakku" answered in English, 23 Oct): it is said once
        more in the language of THIS message, with no tools. Anything going
        wrong keeps the answer as it was."""
        language = reply_language(user_text)
        if language in (None, "english") or not toolbox.answers:
            return run
        said_now = (run.text or "").strip()
        caption = dpr_caption(toolbox.report_text or "", language)
        if caption is not None and toolbox.answers == [toolbox.report_text] and (not said_now or looks_english(said_now)):
            return run.model_copy(update={"text": caption})
        if said_now:
            return run
        answer = "\n".join(toolbox.answers)[:800]
        if not looks_english(answer):
            return run
        ask = (
            "Say this answer to the sender as a short reply. " + (reply_letters_rule(user_text) or "")
            + " Same meaning, same numbers, nothing added. Only the reply.\n\n" + answer
        )
        try:
            again = await self._provider.run_tools(
                SYSTEM_PROMPT,
                [*messages, ChatMessage(role="user", text=ask)],
                [],
                _no_tools,
                max_steps=1,
                timeout_seconds=MANGLISH_TIMEOUT_SECONDS,
                correlation_id=correlation_id,
            )
        except Exception:  # noqa: BLE001 -- the answer goes out as it is
            _log.warning("agent.answer_language_failed correlation_id=%s", correlation_id)
            return run
        said = (again.text or "").strip()
        if not said or script_problems(said, user_text) or looks_english(said):
            return run
        return run.model_copy(update={"text": said})

    async def _one_script(
        self,
        run: ToolRunResult,
        messages: list[ChatMessage],
        user_text: str,
        correlation_id: str | None,
    ) -> ToolRunResult:
        """The reply is in the letters and language of THIS message, one script
        (22 Oct: "innaleത്തെ" went out; English in, Manglish out). A reply
        that is not gets one more try with no tools; if that is wrong too, the
        sentences that break the rule go, so the sender never reads them."""
        text = (run.text or "").strip()
        problems = script_problems(text, user_text)
        if not text or not problems:
            return run
        ask = (
            "Your last reply was rejected: " + "; ".join(problems) + ". Say it again, same meaning and "
            "numbers, nothing added. " + (reply_letters_rule(user_text) or "") + " Only the reply."
        )
        retried = ""
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
            retried = (again.text or "").strip()
        except Exception:  # noqa: BLE001 -- the sentences that break the rule go instead
            _log.warning("agent.script_retry_failed correlation_id=%s", correlation_id)
        if retried and not script_problems(retried, user_text):
            return run.model_copy(update={"text": retried})
        _log.warning("agent.script_fallback correlation_id=%s problems=%s", correlation_id, problems)
        if letters_of(user_text) == "latin" and any("English letters" in p for p in problems):
            return run.model_copy(update={"text": without_native_script(text)})
        if reply_language(user_text) == "english" and any("Manglish" in p for p in problems):
            text = without_manglish(text, _MANGLISH_WORDS)
        broken = mixed_script_words(text)
        kept = "".join(p for p in sentences(text) if not any(w in p for w in broken))
        return run.model_copy(update={"text": kept.strip()})

    async def _covering(
        self,
        run: ToolRunResult,
        messages: list[ChatMessage],
        toolbox: AgentToolbox,
        user_text: str,
        correlation_id: str | None,
    ) -> ToolRunResult:
        """Request 83: the sentence above the card names every item on it (it
        left out "2 electricians" on 22 Oct). One more try, with no tools, when
        one is missing; then the system's own sentence, built from the card's
        items in the sender's language. A reply that carries a question is left
        alone: the question must still end it."""
        items = [item.summary for item in _entries(toolbox) if item.summary and not item.carried]
        text = (run.text or "").strip()
        if not items or not text or toolbox.parked is not None:
            return run
        missing = uncovered_items(text, items)
        claims = bool(_SAVED_CLAIM.search(text)) and self._card_attached(toolbox)
        if not missing and not claims:
            return run
        ask = (
            "Your last reply was not right for a card that is not saved yet. "
            + ("It left out: " + "; ".join(missing) + ". " if missing else "")
            + ("It said the entry is written, noted or saved, which is not true before they tap Save. " if claims else "")
            + "Say it again in the same language and letters, naming every one of these, with their numbers: "
            + "; ".join(items)
            + ". Ask them to check it and tap Save; never say it is saved, written, noted or done. "
            "Short, friendly, nothing added. Only the reply."
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
            retried = (again.text or "").strip()
        except Exception:  # noqa: BLE001 -- the system's sentence stands in
            _log.warning("agent.coverage_retry_failed correlation_id=%s", correlation_id)
            retried = ""
        if retried and not uncovered_items(retried, items) and not _SAVED_CLAIM.search(retried):
            return run.model_copy(update={"text": retried})
        _log.warning(
            "agent.coverage_fallback correlation_id=%s missing=%s claims=%s", correlation_id, len(missing), claims
        )
        return run.model_copy(update={"text": covering_sentence(items, user_text)})

    # -- the one reply -----------------------------------------------------

    def _compose(
        self,
        run: ToolRunResult,
        toolbox: AgentToolbox,
        sources: list[str],
        correlation_id: str | None = None,
    ) -> ReplySpec:
        if toolbox.parked is not None:
            toolbox.drop_actions()
        text = (run.text or "").strip()
        if toolbox.equipment_noted and not _entries(toolbox):
            # Request 104: the one plain line, whatever the model wrote.
            from .equipment import EQUIPMENT_LINE

            return ReplySpec(text=EQUIPMENT_LINE)
        if _entries(toolbox):
            # Before the Save tap nothing is kept (WA-37).
            text = without_saved_claims(text)
        text = without_tool_talk(text)
        if not _questions_line(toolbox) and not _engineer_card(toolbox):
            # WA-52: nothing went to the engineer, so the reply never says it did.
            # (A Send card is no promise: its words say what will be sent.)
            text = without_engineer_promise(text)
        if toolbox.parked is None and (_entries(toolbox) or toolbox.system_lines or toolbox.answers):
            text = without_stray_sentences(text, _grounds(toolbox))
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
            # A figure the model made up (or worked out) is never sent. Only
            # the sentences carrying one go (22 Oct: an example "100 bags?"
            # took the whole question with it); with none left, the system's
            # own words stand in for the reply.
            _log.warning(
                "agent.number_guard correlation_id=%s numbers=%s", correlation_id, sorted(unbacked)
            )
            text = without_numbers(text, unbacked)
        if not self._card_attached(toolbox):
            # Only a reply with a card under it may ask to tap Save (22 Oct).
            text = without_save_prompt(text)
        tail: list[str] = []
        if block:
            if not text and run.stop_reason == "max_steps":
                text = CHECK_LINE
            elif run.stop_reason != "max_steps" and toolbox.parked is None:
                text = self._natural(text, toolbox)
            tail.append(block)
            draft = draft_report_line(toolbox.report_text)
            if draft:
                tail.append(draft)
        asked = _questions_line(toolbox)
        if asked:
            tail.append(asked)
        for line in toolbox.system_lines:
            if line not in text:
                tail.append(line)
        if not text and not tail:
            return self._fallback(toolbox, partial=run.stop_reason == "max_steps")
        if _entries(toolbox) and "undo" not in (text + "\n".join(tail)).casefold():
            tail.append(UNDO_LINE)
        text = _within_cap(text, tail)
        parked = toolbox.parked
        if parked is None:
            return ReplySpec(text=text)
        if toolbox.parked_confirm:
            # Confirm-first: the record itself goes under the model's words,
            # so Yes confirms what they can see (22 Oct: only "Sheri aano?"
            # and two buttons went out). Its "Reply YES" line is the buttons.
            details = _card_details(parked.text)
            if details and details not in text:
                text = f"{text}\n\n{details}"
        elif "?" not in text and "？" not in text:
            # The model left the question out: the buttons would hang in the air.
            text = f"{text}\n\n{parked.text}"
        return ReplySpec(
            text=text,
            list_button_label=parked.list_button_label,
            list_rows=parked.list_rows,
            buttons=parked.buttons,
        )

    def _natural(self, text: str, toolbox: AgentToolbox) -> str:
        """Request 89: after every strip, the words above a Save card must
        still say what is on it. A bare "Okay." (what is left when "noted" and
        the like are cut out of the model's sentence), or a sentence that lost
        an item, is replaced by the system's own natural sentence built from the
        card's items in the sender's language, never by a flat "Okay."."""
        if not text or not self._card_attached(toolbox):
            return text
        items = [item.summary for item in _entries(toolbox) if item.summary and not item.carried]
        if not items:
            return text
        bare = len(re.findall(r"[^\W\d_]{2,}", text)) < 3
        if bare or uncovered_items(text, items):
            _log.warning("agent.natural_fallback bare=%s", bare)
            return covering_sentence(items, toolbox.user_text)
        return text

    @staticmethod
    def _card_attached(toolbox: AgentToolbox) -> bool:
        """Whether the reply goes out with a Save card (Save / Cancel under
        it): entries were prepared, and they fit one tap. A gateway that cannot
        say counts any entry as a card."""
        entries = _entries(toolbox)
        if not entries:
            return False
        handled = getattr(toolbox.gateway, "handled", None)
        if handled is None:
            return True
        from .save_button import facts_of

        carry = lambda name: [i.fact for i in getattr(toolbox.gateway, name, ())]  # noqa: E731
        # Request 104: a pending action (a question for the engineer, the day's
        # weather, issues to close) is on the card like a draft.
        return (
            facts_of(handled, before=carry("carry_before"), after=[*carry("carry_after"), *carry("action_items")])
            is not None
        )

    def _fallback(self, toolbox: AgentToolbox, *, partial: bool) -> ReplySpec:
        """The reply when the model gave no usable text: the pipeline's own
        words for what it did."""
        block = _saved_block(toolbox)
        parts = [block] if block else [item.text for item in toolbox.saved]
        draft = draft_report_line(toolbox.report_text) if block else ""
        if draft:
            parts.append(draft)
        parts.extend(a for a in toolbox.answers if not (draft and a == toolbox.report_text))
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


#: Little words that mark a sentence as English; Manglish keeps its English
#: nouns ("cement", "report") but not these.
_ENGLISH_LITTLE_WORDS = frozenset(
    "the is are was were to of and for how what when please can could need have has do does did will "
    "would my me we you your our this that it with from not much many any there".split()
)


def looks_english(text: str) -> bool:
    """A message that is plainly English: three words or more, two of them
    little English words, and none a Manglish word. A guess about the reply's
    language is made only for such a message."""
    if is_manglish(text) or text.startswith("(They sent"):
        return False
    words = re.findall(r"[a-z]+", text.lower())
    return len(words) >= 3 and len(set(words) & _ENGLISH_LITTLE_WORDS) >= 2


def script_problems(reply: str, user_text: str) -> list[str]:
    """What is wrong with the language and letters of ``reply`` for a message
    ``user_text`` (request 89: the language is decided from the message in code,
    ``reply_language``): a word in two scripts, native script for a message in
    English letters, Manglish for a message in English, English letters for a
    message in its own script. A message with no language of its own forces
    nothing."""
    problems = []
    mixed = mixed_script_words(reply)
    if mixed:
        problems.append("it has a word that mixes English and Malayalam letters (" + ", ".join(mixed[:3]) + ")")
    language = reply_language(user_text)
    letters = letters_of(reply)
    if language in ("english", "manglish") and letters == "native":
        problems.append("it uses Malayalam/Hindi script but the message is in English letters")
    elif language == "english" and manglish_word_count(reply, _MANGLISH_WORDS):
        problems.append("it is in Manglish but the message is in English")
    elif language in ("malayalam", "hindi", "native") and letters == "latin" and len(re.findall(r"[A-Za-z]+", reply)) >= 3:
        problems.append("it is in English letters but the message is in its own script")
    return problems


#: A reply with buttons is a WhatsApp interactive body, 1024 characters at
#: most, and the composer adds a line or two after the agent's text.
REPLY_CAP = BODY_MAX - 80


def _within_cap(words: str, tail: list[str]) -> str:
    """The model's ``words`` and the system's ``tail`` lines as one reply. Only
    when it would pass the cap are the words shortened, at a real sentence end
    (22 Oct: a reply stopped after "e.g.")."""
    rest = "\n\n".join(tail)
    if not words:
        return rest
    if not rest:
        return trim_at_sentence(words, REPLY_CAP)
    if len(words) + len(rest) + 2 > REPLY_CAP:
        words = trim_at_sentence(words, max(REPLY_CAP - len(rest) - 2, 0))
    return f"{words}\n\n{rest}" if words else rest


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_ORDINAL = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)
_LABOUR_TOTAL = re.compile(r"^\s*\d+ workers?\s*\(")


def _required_numbers(summary: str) -> set[str]:
    """The figures a sentence about this card line must carry: its counts and
    amounts, not the labour total ("15 workers (5 mason, 8 helper, 2
    electrician)": 5, 8 and 2) and not a floor ("3rd floor")."""
    text = _ORDINAL.sub(" ", summary)
    if _LABOUR_TOTAL.match(text):
        text = text.split("(", 1)[1]
    return _numbers(text)


def uncovered_items(sentence: str, summaries: list[str]) -> list[str]:
    """The card lines ``sentence`` does not mention: a figure of the line that
    is not in it; for a line with no figure, none of its words (only checked
    for a sentence in English letters, whose words are the card's)."""
    spoken_numbers = _numbers(sentence)
    spoken = sentence.casefold()
    latin = letters_of(sentence) == "latin"
    missing = []
    for summary in summaries:
        need = _required_numbers(summary)
        if need:
            if not need <= spoken_numbers:
                missing.append(summary)
            continue
        words = [w for w in re.findall(r"[^\W\d_]{4,}", summary.casefold())]
        if latin and words and not any(w[:5] in spoken for w in words):
            missing.append(summary)
    return missing


#: The system's own sentence above the card when the model's leaves an item
#: out twice: {items} are the card's lines. Never says it is saved (WA-37).
_COVERING = {
    "english": "{items}. Please check it and tap Save.",
    "manglish": "{items}. Nokki shariyenkil Save tap cheyyu.",
    "malayalam": "{items}. ശരിയാണെങ്കിൽ Save അമർത്തുക.",
    "hindi": "{items}. सही हो तो Save दबाएँ.",
}


def covering_sentence(summaries: list[str], user_text: str) -> str:
    # The card header says "To close:" / "Send to engineer:" already (request 104):
    # the sentence above it says it as words, not the same label twice.
    said = [
        s.strip().replace("To close: ", "Close ", 1).replace("Send to engineer: ", "Send to your engineer: ", 1)
        for s in summaries
        if s
    ]
    items = "; ".join(said)
    items = items[:1].upper() + items[1:]
    if re.search(r"[ഀ-ൿ]", user_text):
        language = "malayalam"
    elif re.search(r"[ऀ-ॿ]", user_text):
        language = "hindi"
    elif is_manglish(user_text):
        language = "manglish"
    else:
        language = "english"
    return _COVERING[language].format(items=items)


#: "• Work: 2 items", one line per section of the day's draft report.
_DRAFT_LINE = re.compile(r"^\s*•\s*(?P<item>\S.*)$", re.MULTILINE)
DRAFT_TAIL = "(The items above are added once you tap Save.)"


def draft_report_line(report_text: str | None) -> str:
    """Request 83: ONE line for "send the report" asked in the same message as
    saves -- what the day's draft holds so far (the WA-40 preview request_dpr
    returned), and that the new items join it on Save. Empty when the answer
    carries no preview (a finished PDF is attached by its own path)."""
    text = report_text or ""
    items = [m.group("item").strip().rstrip(".") for m in _DRAFT_LINE.finditer(text)]
    if items:
        return f"Today's draft so far: {', '.join(items)}. {DRAFT_TAIL}"
    if text.startswith(("No DPR has been generated", "Nothing's been logged for today")):
        return f"Today's draft so far: nothing yet. {DRAFT_TAIL}"
    return ""


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


def without_numbers(reply: str, numbers: set[str]) -> str:
    """``reply`` without the sentences that carry any of ``numbers``; empty
    when nothing worded is left."""
    kept = [part for part in sentences(reply) if part and not (_numbers(part) & numbers)]
    text = "".join(kept).strip()
    if _numbers(text) & numbers or len(re.findall(r"[^\W\d_]+", text)) < 3:
        # A figure split across "sentences" ("12.5"), or only a scrap left
        # ("Rs."): the system's own words instead (review, 22 Oct).
        return ""
    return text


def unbacked_numbers(reply: str, sources: list[str]) -> set[str]:
    """WA-37: the numbers in the model's ``reply`` that appear in none of
    ``sources`` (its prompt and its tool results)."""
    allowed = set(_ALWAYS_ALLOWED)
    for source in sources:
        allowed |= _numbers(source)
    return _numbers(reply) - allowed


#: "It is saved / recorded" in the languages the sites write in. Before the
#: Save tap nothing is kept, so a sentence saying so is not true (WA-37).
#: Manglish for "it is written / done", which no reply may say before the Save
#: tap (22 Oct: "issue aayi ezhuthiyittund"). Unlike the English claims, which
#: are cut out of the sentence, a reply with one is asked for again.
_DONE_WORD = re.compile(
    r"\b(?:ezhuthiyittund[u]?|ezhuthiyirikkunnu|rekhappeduthiyittund|cheythittund|aakkiyittund|vechittund)\b",
    re.IGNORECASE,
)
_SAVED_CLAIM = re.compile(
    r"(?<!not )\b(?:saved|recorded|logged|noted)\b"
    r"|\b(?:save|record|rekhappeduthi|note)\s*(?:cheythu|cheythittund|aakki)"
    r"|" + _DONE_WORD.pattern + ""
    r"|സേവ്\s*ചെയ്തു|സേവ്\s*ചെയ്തിട്ടുണ്ട്|രേഖപ്പെടുത്തി|സേവ്\s*ആയി"
    r"|सेव\s*(?:कर\s*)?(?:दिया|किया|हो\s*गया)|दर्ज\s*(?:कर\s*)?(?:दिया|किया|हो\s*गया)",
    re.IGNORECASE,
)
# Sentences are cut by reply_text.sentences: a "." inside a number ("12.5"), before
# a space-less word ("Rs.4500") or in an abbreviation ("e.g.") does not end one.


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


#: What the model is told about tools and buttons, never words for a site
#: (live 22 Oct: "Options: ... The options are shown as buttons; when they
#: answer, call this tool again with that exact project." went out).
_TOOL_TALK = re.compile(
    r"\b(?:this|the|a|save|that) tool\b|new_material|ask_user|\[options:|shown as buttons|^\s*options\s*:"
    r"|\bcall (?:this|the|a) |nothing was saved",
    re.IGNORECASE,
)


def without_tool_talk(text: str) -> str:
    """``text`` without the sentences that repeat the system's notes to the model."""
    kept = [part for part in sentences(text) if part and not _TOOL_TALK.search(part)]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


def _card_details(card: str) -> str:
    """A confirmation card without its header and its "Reply YES" line."""
    kept = [
        line
        for line in card.splitlines()
        if not line.strip().startswith("*Confirm") and "reply yes" not in line.casefold()
    ]
    return "\n".join(kept).strip()


def without_saved_claims(text: str) -> str:
    """``text`` without what says an entry is already saved: the claiming
    clause, or the whole sentence when it is nothing else."""
    kept = [_without_claim(part) for part in sentences(text) if part]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


def _grounds(toolbox: AgentToolbox) -> list[str]:
    """What a sentence of the reply may be about: the sender's message and what
    the tools returned or were given."""
    grounds = [toolbox.user_text, *(i.summary or "" for i in toolbox.saved), *toolbox.answers, *toolbox.notes]
    grounds.extend(toolbox.system_lines)
    return grounds


def _entries(toolbox: AgentToolbox) -> list[SavedItem]:
    """What was saved as an entry. A question passed to the engineer is not
    one (WA-37): the model says it was passed on; it is no line to check."""
    return [
        item for item in toolbox.saved if not (item.summary or "").startswith(QUESTION_PREFIX)
    ]


#: Marks a question the system passed to the engineer (WA-37): said, not saved.
QUESTION_MARK = "📨 "


def _engineer_card(toolbox: AgentToolbox) -> bool:
    """Request 104: a "Send to engineer" card is on this reply."""
    return any(item.tool == NOTE_FOR_ENGINEER for item in toolbox.saved)


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


# (also the card headers of request 104, so a model-written "📝 To close: ..." is not doubled)
_SAVED_HEAD = re.compile(r"^\s*(?:✅|📝\s*(?:To close|To save|Send to engineer))")
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


def _park_plain_question(run: ToolRunResult, toolbox: AgentToolbox) -> None:
    """The model asked in words alone, with no tool at all ("pani nadakkunnu"
    -> "Ethu pani?": live golden set, 22 Oct, now and then): the question is
    still the one the conversation waits on, as if it had called ask_user."""
    text = (run.text or "").strip()
    if run.calls or toolbox.parked is not None or not text.endswith(("?", "？")):
        return
    toolbox.parked = ReplySpec(text=text)
    toolbox.parked_by = "ask"
