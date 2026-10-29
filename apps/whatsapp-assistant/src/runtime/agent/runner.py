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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from channel.replies import ReplySpec
from interactions.saved_summary import QUESTION_PREFIX, render_saved
from mesiri_ai.models import ChatMessage, ToolOutcome, ToolRunResult
from mesiri_ai.ports.tool_calling import ToolCallingProvider
from runtime.reply_composer import BODY_MAX

from . import draft as dr
from .equipment import is_problem_only
from .gateway import WorkflowGateway
from .material_direction import asked_direction, is_cancel
from .prompt import (
    _MANGLISH_WORDS,
    SYSTEM_PROMPT,
    AgentContext,
    build_messages,
    is_manglish,
    letters_of,
    preferred_language,
    reply_language,
    reply_letters_rule,
)
from .reply_clean import clean_annotations, clean_model_text
from .reply_text import (
    manglish_word_count,
    mixed_script_words,
    sentences,
    trim_at_sentence,
    without_engineer_promise,
    without_manglish,
    without_native_script,
    without_save_prompt,
    without_stray_sentences,
    without_undo_prompt,
)
from .save_button import SAVE_TITLE
from .toolbox import HOURS_QUESTION, AgentToolbox, SavedItem, offers_engineer, tomorrow_plan_text
from .tools import (
    NOTE_FOR_ENGINEER,
    REPORT_ISSUE,
    SET_SITE_CONDITIONS,
    WRITE_TOOLS,
    ScopeLookup,
    tool_specs,
)
from .wording import language_of, say, usual_from

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
        site_queue: list[dict] | None = None,
        reply_language_setter: Callable[[str | None], Awaitable[bool]] | None = None,
    ) -> AgentResult:
        # Request 143: the turn's reply language, decided once; every line of the code's
        # and the prompt's language rule follow it.
        language = language_of(user_text, usual_from(ctx.last_language, ctx.last_script))
        toolbox = AgentToolbox(
            gateway=gateway,
            scope=scope,
            user_text=user_text,
            language=language,
            lap=lap,
            after_tool=after_tool,
            site_queue=[dict(i) for i in site_queue or []],
            reply_language_setter=reply_language_setter,
        )
        # WA-52: only a reply that OFFERED to ask counts ("Shall I ask your
        # engineer?"), not one that merely named the engineer.
        if hasattr(gateway, "wording_language"):
            gateway.wording_language = language
        toolbox.engineer_offered = bool(ctx.turns) and offers_engineer(ctx.turns[-1].assistant_reply)
        # Request 104, D2: the hours-lost question is asked once.
        toolbox.hours_asked = bool(ctx.turns) and HOURS_QUESTION in ctx.turns[-1].assistant_reply
        if ctx.turns and is_cancel(user_text) and asked_direction(ctx.turns[-1].assistant_reply):
            # Request 143: Cancel on "Received or used?": nothing to save, no model.
            _decided(toolbox, "reply", TEMPLATE)
            return AgentResult("ok", ReplySpec(text=say("material.direction_cancelled", language)), toolbox)
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
        if toolbox.language_changed:
            # Live 29 Oct: this very reply is in the language they just set.
            preferred_language.set(toolbox.language_choice)
            language = language_of(user_text, usual_from(ctx.last_language, ctx.last_script))
            toolbox.language = language
            if hasattr(gateway, "wording_language"):
                gateway.wording_language = language
        await self._tomorrow_plan(toolbox, user_text)
        await self._problem_only(toolbox, user_text)
        await self._problem_part(toolbox, user_text)
        await toolbox.finish_site_queue()
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
            _decided(toolbox, "item_source", "code:tomorrow_plan")
            await toolbox.handle(SET_SITE_CONDITIONS, {"tomorrow_plan": plan})

    @staticmethod
    async def _problem_only(toolbox: AgentToolbox, user_text: str) -> None:
        """Request 124, E: "mixer breakdown aayi" / "pump problem" with nothing
        else in it is an issue to save. The model sometimes answered it in words
        ("issue aayi kodukkaam") and called no tool, so nothing was saved and no
        card came: the card is made here from the message's own words. Only for
        a company holding messages as a draft card."""
        if (
            not toolbox.draft_mode
            or toolbox.called & WRITE_TOOLS
            or toolbox.parked is not None
            or not is_problem_only(user_text)
        ):
            return
        from .equipment import has_equipment

        narrative = " ".join(user_text.split())[:160]
        kind = "EQUIPMENT_BREAKDOWN" if has_equipment(user_text) else "OTHER"
        _decided(toolbox, "item_source", "code:problem_only")
        await toolbox.handle(REPORT_ISSUE, {"issue_type": kind, "narrative": narrative})

    @staticmethod
    async def _problem_part(toolbox: AgentToolbox, user_text: str) -> None:
        """WA-82: a breakdown inside a longer site note ("..., mixer breakdown aayi pani 2
        hour ninnu") is an issue line of the card, even when the model saved the other parts
        and called no ``report_issue`` (live 27 Oct, round 7: the card lost it). The line
        is made from the message's own words; the card shows it before anything is saved.
        Only for a company holding messages as a draft card."""
        if not toolbox.draft_mode or REPORT_ISSUE in toolbox.called or toolbox.parked is not None:
            return
        if not toolbox.called & WRITE_TOOLS:
            return  # a message that is only the problem is _problem_only's
        from .equipment import has_equipment, hours_lost_minutes, problem_clause

        clause = problem_clause(user_text)
        if clause is None:
            return
        args: dict = {
            "issue_type": "EQUIPMENT_BREAKDOWN" if has_equipment(clause) else "OTHER",
            "narrative": clause[:160],
        }
        minutes = hours_lost_minutes(clause)
        if minutes:
            args["delay_duration_minutes"] = minutes
        _log.warning("agent.problem_part_added correlation_id=%s", getattr(toolbox, "correlation_id", None))
        _decided(toolbox, "item_source", "code:problem_part")
        await toolbox.handle(REPORT_ISSUE, args)

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
        if toolbox.answers == [toolbox.report_text]:
            return run  # the report's line is the code's, already in their language (request 143)
        said_now = (run.text or "").strip()
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
        if (
            letters_of(user_text) == "latin"
            and reply_language(user_text) not in ("malayalam", "hindi", "native")
            and any("English letters" in p for p in problems)
        ):
            return run.model_copy(update={"text": without_native_script(text)})
        if reply_language(user_text) in ("english", "hinglish") and any("Manglish" in p for p in problems):
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
        return run.model_copy(update={"text": covering_sentence(items, user_text, toolbox.language)})

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
        draft_mode = getattr(toolbox.gateway, "draft_mode", False) is True
        # Request 132: the card, its questions and its buttons are the code's; the
        # model's own words never carry one, nor a note it read in its prompt.
        text = clean_model_text(text) if draft_mode else clean_annotations(text)
        if (code_made := self._code_card(toolbox)) is not None:
            return code_made
        if (report := _report_only(toolbox)) is not None:
            return report
        if draft_mode and (open_draft := _open_draft(toolbox)) is not None:
            _decided(toolbox, "reply", MODEL_FILTERED)
            text = _one_sentence(text)
            if _APOLOGY.match(text) and not _failed_this_turn(toolbox, open_draft):
                # WA-81 (live 27 Oct, #4338): "Sorry, couldn't record it" above a card
                # that HAS the line, waiting on its question. The card says what is so.
                text = ""
        if (failed := self._code_failure(toolbox, text)) is not None:
            return failed
        if toolbox.parked_site:
            # [111]: the site question is the code's, in the sender's language;
            # the model's words around it ("Ethra per vannu Site B-il?") went
            # out as a different question.
            text = ""
            hold = toolbox.site_hold_line()
            if hold and hold not in toolbox.system_lines:
                toolbox.system_lines.append(hold)
        if toolbox.module_off_line and not _entries(toolbox):
            # WA-84 (live 27 Oct, M27): the model retold it in English to a Manglish sender.
            return ReplySpec(text=toolbox.module_off_line)
        if toolbox.equipment_noted and not _entries(toolbox):
            # Request 104: the one plain line, whatever the model wrote.
            from .equipment import EQUIPMENT_LINE

            return ReplySpec(text=EQUIPMENT_LINE)
        if _entries(toolbox) or _save_card(toolbox.parked):
            # Before the Save tap nothing is kept (WA-37).
            text = without_saved_claims(text)
        if _save_card(toolbox.parked):
            # Request 115: a held card is not saved. Whatever the model wrote
            # as "✅ Saved: ..." over it, or as UNDO, goes; only entries that
            # were really written keep the system's own block below.
            text = without_undo_prompt(text)
            text = _without_pending_saved(text, toolbox)
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
        if not self._save_attached(toolbox):
            # Only a reply with a card under it may ask to tap Save (22 Oct).
            text = without_save_prompt(text)
            if (waiting := _choice_line(toolbox)) is not None:
                # Request 129: a card with only a question on it (labour Replace / Add)
                # has no Save button; the sentence says what to tap.
                text = f"{text}\n\n{waiting}".strip()
        tail: list[str] = []
        if block:
            if not text and run.stop_reason == "max_steps":
                text = CHECK_LINE
            elif run.stop_reason != "max_steps" and toolbox.parked is None:
                text = self._natural(text, toolbox)
            tail.append(block)
        if line := _report_line(toolbox):
            # Request 143: the PDF went with the tool call; the model says nothing about it.
            tail.append(line)
        asked = _questions_line(toolbox)
        if asked:
            tail.append(asked)
        for line in toolbox.system_lines:
            if line not in text:
                tail.append(line)
        if not text and not tail:
            return self._fallback(toolbox, partial=run.stop_reason == "max_steps")
        if _entries(toolbox) and not _open_draft(toolbox) and "undo" not in (text + "\n".join(tail)).casefold():
            tail.append(UNDO_LINE)
        text = _within_cap(text, tail)
        parked = toolbox.parked
        if parked is None:
            return _with_card(ReplySpec(text=text), toolbox)
        draft = _open_draft(toolbox)
        if draft is not None and dr.card_rows(draft):
            # Request 124: a question must not push the card out (as request 90 for
            # the Save card): its options stay in the words, answered by typing.
            from .save_button import question_as_text

            asked = question_as_text(parked)
            return _with_card(ReplySpec(text=f"{text}\n\n{asked.text}" if asked.text not in text else text), toolbox)
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

    @staticmethod
    def _code_card(toolbox: AgentToolbox) -> ReplySpec | None:
        """Request 136: above a draft card this turn changed, every word is the code's:
        one sentence from ``card_sentence`` (the sender's language), the card, its
        questions and the system's own lines. The model's text is not used, so it
        cannot contradict the card ("Site B tap cheyyu" while the buttons ask). A turn
        that also answered a lookup keeps the model's (filtered) words for the answer;
        None then, and for anything that is not a draft card."""
        draft = _open_draft(toolbox)
        if draft is None or toolbox.answers or toolbox.parked is not None:
            return None
        if toolbox.module_off_line or toolbox.equipment_noted:
            return None
        tail = [_saved_block(toolbox)]
        if asked := _questions_line(toolbox):
            tail.append(asked)
        tail.extend(line for line in toolbox.system_lines if line not in tail)
        text = _within_cap(card_sentence(draft, toolbox.user_text, toolbox.language), [t for t in tail if t])
        _decided(toolbox, "reply", TEMPLATE)
        return _with_card(ReplySpec(text=text), toolbox)

    @staticmethod
    def _code_failure(toolbox: AgentToolbox, text: str) -> ReplySpec | None:
        """Request 137 (E): a failed write or correction with no card, no saved line, no
        answer and no question to show for the turn is answered by the code's template."""
        if getattr(toolbox.gateway, "draft_mode", False) is not True or toolbox.attempted_writes <= 0:
            return None
        if toolbox.failed <= 0 and not _APOLOGY.match(text):
            return None  # a write that came back with a question or a redirect is the model's to continue
        if (
            _entries(toolbox)
            or toolbox.answers
            or toolbox.parked is not None
            or toolbox.parked_site
            or toolbox.module_off_line
            or toolbox.equipment_noted
            or _open_draft(toolbox) is not None
        ):
            return None
        _decided(toolbox, "reply", TEMPLATE)
        return ReplySpec(text=_FAILED[toolbox.language])

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
            return covering_sentence(items, toolbox.user_text, toolbox.language)
        return text

    def _save_attached(self, toolbox: AgentToolbox) -> bool:
        """Whether the reply goes out with a Save button: a draft card whose
        every line still waits on an answer has Cancel and its answers only."""
        draft = _open_draft(toolbox)
        if draft is not None and dr.card_rows(draft):
            return bool(draft.ready_items)
        return self._card_attached(toolbox)

    @staticmethod
    def _card_attached(toolbox: AgentToolbox) -> bool:
        """Whether the reply goes out with a Save card (Save / Cancel under
        it): entries were prepared, and they fit one tap. A gateway that cannot
        say counts any entry as a card."""
        entries = _entries(toolbox)
        if (draft := _open_draft(toolbox)) is not None:
            return bool(dr.card_rows(draft))
        if not entries:
            # Request 114: a held work-done card has Save / Cancel under it too.
            return _save_card(toolbox.parked)
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
        line = _report_line(toolbox)
        if line:
            parts.append(line)
        parts.extend(a for a in toolbox.answers if not (line and a == toolbox.report_text))
        parked = toolbox.parked
        if parked is not None:
            parts.append(parked.text)
        elif not parts:
            parts.extend(toolbox.notes[:1] or [NOTHING_LINE])
        if partial and (toolbox.saved or toolbox.attempted_writes):
            parts.append(CHECK_LINE)
        text = _unique_paragraphs("\n\n".join(p for p in parts if p))
        if parked is None:
            return _with_card(ReplySpec(text=text), toolbox)
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
    if language in ("english", "manglish", "hinglish") and letters == "native":
        problems.append("it uses Malayalam/Hindi script but the message is in English letters")
    elif language in ("english", "hinglish") and manglish_word_count(reply, _MANGLISH_WORDS):
        problems.append(f"it is in Manglish but the message is in {'English' if language == 'english' else 'Hindi'}")
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
    "hinglish": "{items}. Sahi ho to Save dabayein.",
}


#: What to tap when the card has no Save button yet, only the answers to its question.
#: Named only when every answer is this short ("Replace" / "Add"); else the card asks.
_SHORT_OPTION = 12
_CHOOSE = {
    "english": "Please tap {options}.",
    "manglish": "{options} tap cheyyu.",
    "malayalam": "{options} അമർത്തുക.",
    "hindi": "{options} दबाएँ.",
    "hinglish": "{options} dabayein.",
}


def _choice_line(toolbox: AgentToolbox) -> str | None:
    """"Replace or Add tap cheyyu", in the sender's language, for an open draft
    card that has answers to tap but nothing to Save yet; None otherwise."""
    draft = _open_draft(toolbox)
    if draft is None or draft.ready_items:
        return None
    asking = next(iter(draft.waiting_items), None)
    options = list(asking.options if asking else ())
    if not options or any(len(o) > _SHORT_OPTION for o in options):
        # Request 136: naming only the short ones told them to tap "Site B" while the
        # card asked between "Green Villa, Kakkanad" and "Site B" (28 Oct).
        return None
    return _CHOOSE[toolbox.language].format(options=" or ".join(options))


#: Request 136: the one sentence above a draft card, by what the card needs next.
#: The Malayalam, Hindi and Hinglish lines (and Manglish "_ASKS") are Claude's
#: drafts, PENDING the native review of WA-76.
_CARD_CHECK = {
    "english": "Please check the card and tap Save.",
    "manglish": "Card nokki shariyenkil Save tap cheyyu.",
    "malayalam": "കാർഡ് നോക്കി ശരിയാണെങ്കിൽ Save അമർത്തുക.",
    "hindi": "कार्ड देखें, सही हो तो Save दबाएँ.",
    "hinglish": "Card dekhein, sahi ho to Save dabayein.",
}
#: Request 137 (E): a write or correction that failed with nothing on screen to show
#: for it. The words are the code's, in the sender's language, with a next step; the
#: model never writes free text on a failure ("Sorry, couldn't change it" went out
#: for a percentage on 28 Oct).
_FAILED = {
    "english": "That wasn't saved or changed. Please send it again in one line: the work, the place and the figure.",
    "manglish": "Athu save/maattan pattiyilla. Work, sthalam, figure ennivayode oru line-il veendum ayakku.",
    "malayalam": "അത് സേവ് ചെയ്യാനോ മാറ്റാനോ കഴിഞ്ഞില്ല. പണി, സ്ഥലം, കണക്ക് എന്നിവ ഒരു വരിയിൽ വീണ്ടും അയക്കുക.",
    "hindi": "वह सेव या बदला नहीं जा सका. कृपया काम, जगह और आँकड़ा एक लाइन में फिर भेजें.",
    "hinglish": "Woh save ya change nahi hua. Kaam, jagah aur figure ek line mein dobara bhejein.",
}
_CARD_ASKS = {
    "english": "Please answer the question on the card.",
    "manglish": "Card-ile chodyathinu answer cheyyu.",
    "malayalam": "കാർഡിലെ ചോദ്യത്തിന് ഉത്തരം നൽകുക.",
    "hindi": "कार्ड पर पूछे गए सवाल का जवाब दें.",
    "hinglish": "Card par pooche gaye sawal ka jawab dein.",
}
_CARD_BOTH = {
    "english": "Please answer the question on the card, then tap Save.",
    "manglish": "Card-ile chodyathinu answer cheythittu Save tap cheyyu.",
    "malayalam": "കാർഡിലെ ചോദ്യത്തിന് ഉത്തരം നൽകി Save അമർത്തുക.",
    "hindi": "कार्ड पर पूछे गए सवाल का जवाब दें, फिर Save दबाएँ.",
    "hinglish": "Card par pooche gaye sawal ka jawab dein, phir Save dabayein.",
}
#: Code ids of who wrote a reply (request 136, C): ``TEMPLATE`` = ``card_sentence``.
TEMPLATE = "template"
MODEL_FILTERED = "model_filtered"


def card_sentence(draft: dr.MessageDraft, user_text: str, language: str | None = None) -> str:
    """The sentence above a draft card, in the sender's language (the turn's, else
    the message's): tap Save; answer the question (or tap its short answers); or both.
    Empty when nothing on the card can be saved or answered (the card says what could
    not be read)."""
    language = language or language_of(user_text)
    waiting, ready = draft.waiting_items, draft.ready_items
    if waiting and not ready:
        options = list(waiting[0].options)
        if options and len(waiting) == 1 and all(len(o) <= _SHORT_OPTION for o in options):
            return _CHOOSE[language].format(options=" or ".join(options))
        return _CARD_ASKS[language]
    if waiting:
        return _CARD_BOTH[language]
    return _CARD_CHECK[language] if ready else ""


def _decided(toolbox: AgentToolbox, what: str, by: str) -> None:
    from .draft_flow import decided

    decided(toolbox.gateway, what, by)


def covering_sentence(summaries: list[str], user_text: str, language: str | None = None) -> str:
    # The card header says "To close:" / "Send to engineer:" already (request 104):
    # the sentence above it says it as words, not the same label twice.
    said = [
        s.strip().replace("To close: ", "Close ", 1).replace("Send to engineer: ", "Send to your engineer: ", 1)
        for s in summaries
        if s
    ]
    items = "; ".join(said)
    items = items[:1].upper() + items[1:]
    return _COVERING[language or language_of(user_text)].format(items=items)


def _report_only(toolbox: AgentToolbox) -> ReplySpec | None:
    """Request 143: a turn that only asked for the report is answered by the code's
    one sentence (the PDFs went with the tool call); the model writes no report text."""
    if not toolbox.report_text or toolbox.answers != [toolbox.report_text]:
        return None
    if _entries(toolbox) or toolbox.parked is not None or _open_draft(toolbox) is not None:
        return None
    _decided(toolbox, "reply", TEMPLATE)
    return ReplySpec(text=toolbox.report_text)


def _report_line(toolbox: AgentToolbox) -> str:
    """Request 143: the report asked for in the same message as entries: one line
    under the card. The PDF went already; the items join the day on Save."""
    if not toolbox.report_text:
        return ""
    if toolbox.report_documents:
        return say("report.with_card", language_of(toolbox.user_text))
    return toolbox.report_text


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


def _save_card(parked: ReplySpec | None) -> bool:
    """Request 114: the question held for the sender is a Save / Cancel card
    (work done on an open activity), not a Yes / No."""
    return parked is not None and any(row.title == SAVE_TITLE for row in parked.buttons or ())


def _without_pending_saved(text: str, toolbox: AgentToolbox) -> str:
    """``text`` without a "✅ Saved: ..." header (and its bullets) the model put
    over a card that waits on the Save tap (request 115). With no entry really
    written, any such header goes; with some, only the ones that play back the
    card's own items, since the system's block speaks for the written ones."""
    if not _entries(toolbox):
        return _without_saved_block(text)
    pending = _normalized(_card_details(toolbox.parked.text if toolbox.parked else ""))
    kept: list[str] = []
    for line in text.split("\n"):
        norm = _normalized(line)
        if _SAVED_HEAD.match(line) and norm and norm.split(" ", 1)[-1] in pending:
            continue
        kept.append(line)
    return "\n".join(kept).strip()


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


def _open_draft(toolbox: AgentToolbox) -> dr.MessageDraft | None:
    """Request 124: the sender's draft card, when this turn changed it (a turn
    that only answers a question never repeats the card)."""
    gateway = toolbox.gateway
    if getattr(gateway, "draft_mode", False) is not True:
        return None
    draft = getattr(gateway, "draft", None)
    if draft is None or not draft.items or not getattr(gateway, "draft_new", None):
        return None
    return draft


def _draft_site(toolbox: AgentToolbox, draft: dr.MessageDraft) -> str | None:
    names = {i.site for i in draft.items if i.state != dr.UNREADABLE and i.site}
    return next(iter(names)) if len(names) == 1 else None


def _with_card(spec: ReplySpec, toolbox: AgentToolbox) -> ReplySpec:
    """``spec`` with the draft card's buttons under it (Save, Cancel, and the
    options of an open question), when this turn put something on the card."""
    draft = _open_draft(toolbox)
    if draft is None:
        return spec
    rows = dr.card_rows(draft)
    if not rows:
        return spec
    from runtime.reply_composer import pick_form

    return pick_form(spec.text, rows)


def _saved_block(toolbox: AgentToolbox) -> str:
    """The deterministic "Saved:" block, when every saved entry has a summary
    (else the model's own wording stands, as before)."""
    if (draft := _open_draft(toolbox)) is not None:
        # Request 124: one card for the whole draft, from the draft itself.
        return dr.card_text(draft, site=_draft_site(toolbox, draft))
    entries = _entries(toolbox)
    if not entries or not all(item.summary for item in entries):
        return ""
    return render_saved([item.summary for item in entries if item.summary])


#: An apology opening the model's words ("Sorry, ...", "ക്ഷമിക്കണം", "maaf kijiye").
_APOLOGY = re.compile(r"^\W*(sorry|apolog|kshamikk|ക്ഷമ|maaf|माफ)", re.I)


def _failed_this_turn(toolbox: AgentToolbox, draft: dr.MessageDraft) -> bool:
    """Whether a line this message put on the card could not be read."""
    new = set(getattr(toolbox.gateway, "draft_new", None) or [])
    return toolbox.failed > 0 or any(i.state == dr.UNREADABLE and i.id in new for i in draft.items)


#: Request 132: the longest the model's words above a draft card.
ONE_SENTENCE_MAX = 200


def _one_sentence(text: str) -> str:
    """The model's words above a card: its first sentence, short. The card says the
    rest (lines, questions, buttons), and a second sentence was where it invented one."""
    first = next((s.strip() for s in sentences(text) if s.strip()), "")
    return trim_at_sentence(first, ONE_SENTENCE_MAX)


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
    if (draft := _open_draft(toolbox)) is not None:
        # Request 127: a question the card shows (❓ ...) is said once: the model's
        # own copy of it in the words above went out as the same sentence twice.
        asked |= {_normalized(i.question) for i in draft.waiting_items if i.question}
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
