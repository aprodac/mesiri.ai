"""v2's own reply (request 196): the model's words, then what the code draws.

The model writes the reply: the greeting, every answer, every part of the message, in the
sender's language. The code keeps only the guarantees and draws the rest:

- honesty: no claimed save / change / send, no figure that is in no source, no promise to the
  engineer that no tool made, no tool or code words;
- below the words: the lines waiting for Save, the questions on them, the system's own lines and
  the buttons (the same functions today's agent uses to draw a card).

Nothing replaces the model's words with a template because they do not repeat the lines (that is
what dropped the greeting, the weather answer and "who else reported" on 1 Nov: today's composer
has four places that do it, built for today's agent, whose words were not trusted). The
deliberately code-written replies stay the code's: a report-only turn, a module that is off,
equipment, a failed write, a site question, and a turn where the model wrote nothing.
"""

from __future__ import annotations

from typing import Any

from channel.replies import ReplySpec
from mesiri_ai.models import ToolRunResult
from runtime.agent import draft as dr
from runtime.agent import runner as composer
from runtime.agent.reply_clean import clean_model_text
from runtime.agent.reply_text import sentences, without_engineer_promise, without_save_prompt
from runtime.agent.toolbox import AgentToolbox


def code_owns_it(toolbox: AgentToolbox) -> bool:
    """The turns whose reply is the code's on purpose (its own line, in the sender's language)."""
    entries = composer._entries(toolbox)
    return bool(
        composer._report_only(toolbox) is not None
        or toolbox.parked_site
        or (toolbox.module_off_line and not entries)
        or (toolbox.equipment_noted and not entries)
        or (getattr(toolbox.gateway, "draft_mode", False) is True and toolbox.failed > 0 and not entries
            and toolbox.parked is None and not toolbox.answers)
    )


def honest(text: str, toolbox: AgentToolbox, sources: list[str]) -> str:
    """The model's words with only what may not go out taken away."""
    text = clean_model_text((text or "").strip())
    if composer._CODE_WORD.search(text):
        return ""
    if composer._entries(toolbox) or composer._save_card(toolbox.parked):
        text = composer.without_saved_claims(text)  # nothing is kept before the Save tap
    text = composer.without_tool_talk(text)
    if not composer._questions_line(toolbox) and not composer._engineer_card(toolbox):
        text = without_engineer_promise(text)
    if unbacked := composer.unbacked_numbers(text, sources):
        # Only the sentences carrying the figure go; a short greeting left on its own stays.
        text = "".join(p for p in sentences(text) if p and not (composer._numbers(p) & unbacked))
        if composer._numbers(text) & unbacked:  # a figure split across "sentences" ("12.5")
            return ""
    return composer._without_echoed_questions(composer._without_saved_block(text), toolbox).strip()


def compose(classic: Any, run: ToolRunResult, toolbox: AgentToolbox, sources: list[str], correlation_id: str | None) -> ReplySpec:
    """The reply of one v2 turn."""
    if toolbox.parked is not None:
        toolbox.drop_actions()
    text = honest(run.text or "", toolbox, sources) if not code_owns_it(toolbox) else ""
    if not text:
        # The model wrote nothing usable (or the turn is the code's): today's composer, as before.
        return classic._compose(run, toolbox, sources, correlation_id)
    if not classic._save_attached(toolbox):
        text = without_save_prompt(text)  # no Save button under it
    tail = [composer._saved_block(toolbox), composer._report_line(toolbox), composer._questions_line(toolbox)]
    if (waiting := composer._choice_line(toolbox)) is not None and not classic._save_attached(toolbox):
        tail.append(waiting)
    tail += [line for line in toolbox.system_lines if line not in text]
    tail = [t for t in dict.fromkeys(tail) if t]
    if composer._entries(toolbox) and not composer._open_draft(toolbox) and "undo" not in (text + "".join(tail)).casefold():
        tail.append(composer.UNDO_LINE)
    text = composer._within_cap(text, tail)
    parked = toolbox.parked
    if parked is None:
        return composer._with_card(ReplySpec(text=text), toolbox)
    draft = composer._open_draft(toolbox)
    if draft is not None and dr.card_rows(draft):
        # A question never pushes the lines out: its options stay in the words.
        from runtime.agent.save_button import question_as_text

        asked = question_as_text(parked)
        return composer._with_card(ReplySpec(text=text if asked.text in text else f"{text}\n\n{asked.text}"), toolbox)
    if toolbox.parked_confirm:
        details = composer._card_details(parked.text)
        if details and details not in text:
            text = f"{text}\n\n{details}"
    elif "?" not in text and "？" not in text:
        text = f"{text}\n\n{parked.text}"  # the buttons never hang in the air
    return ReplySpec(text=text, list_button_label=parked.list_button_label, list_rows=parked.list_rows, buttons=parked.buttons)
