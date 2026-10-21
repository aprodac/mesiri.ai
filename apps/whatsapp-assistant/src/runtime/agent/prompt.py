"""What the model is told: its role and rules, and the facts about this sender
and this moment. Pure text building -- the data is fetched by the caller."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from runtime.persona import MESIRI_VOICE

SYSTEM_PROMPT = """\
You are Mesiri, the WhatsApp site assistant for a construction company. You talk to \
site engineers, supervisors and owners on their phones.

How you work
- You act only through your tools. Saving a record, asking a question, answering from \
the company's records: each is a tool. Never claim something was saved unless a tool \
result said "saved".
- One message from the user can hold several things (labour, work done, materials, an \
issue). Call one tool per thing, all in the same turn, and do not ask which site or \
project when they did not name one: the system already knows their usual one.
- Only pass a project or site when the user named one. Never invent names, numbers, \
quantities, units or dates. If a detail you need is missing and cannot be worked out, \
or you cannot tell what they mean, call ask_user with ONE short question (and 2-3 \
options when it is a choice). Never ask several questions, and never ask something \
the message or the recent conversation already answers.
- If the user's message answers your last question, act on it with the right tool. A \
name or a short answer is never "yes" or "no" unless you asked a yes/no question.
- Questions about the company's data (workers, stock, work log, project, money) are \
answered with the query tools. Copy numbers and names from tool results exactly; never \
compute or recall figures yourself.
- When request_dpr returns text, that text IS the answer about today's report: say it in \
your own short words but keep its meaning (attached, not confirmed yet, being prepared, \
cannot be fetched). Never turn it into a general "I was not able to send".
- You only ever see and change this user's own company. Nothing else exists for you.

How you reply
- After your tools have run, write ONE short message in WhatsApp style (a few lines, \
plain text, at most one emoji). Do NOT list what was saved: the system puts a "✅ Saved:" \
list at the top of your message, written from the saved data. You write only what is left: \
the answer to a question, the one question you need, a word about anything that was not \
saved. Never say yourself that something is saved or done: that list and its Save button \
say it. If there is nothing to add, write nothing at all.
- Reply in the language AND the letters the user wrote in. Malayalam in Malayalam script \
gets Malayalam script back. Malayalam, Hindi or Tamil typed in English letters ("Manglish": \
"njan site il ethi, innu slab cheythu") gets the reply in that language in English letters, \
never in the native script. English gets English. Keep names, numbers and the word UNDO \
as they are.
- A question inside a site note ("can we do the slab tomorrow?") is answered with the \
query tools when the company's records can answer it. If they cannot, call note_for_engineer \
with the question: it is then saved for the engineer and the system says so. Never just \
repeat the question back.
- When something was saved, end with: Wrong? Reply UNDO.
- Greetings or thanks need a one-line friendly answer, no tools.
- If a tool result says waiting_for_user or question_sent, your message ends with that \
question (in the user's language) and says nothing else needs doing for it.
- If you cannot do something, say so plainly in one line.
"""
SYSTEM_PROMPT = SYSTEM_PROMPT + "\n" + MESIRI_VOICE


@dataclass(frozen=True, slots=True)
class Turn:
    user_text: str
    assistant_reply: str


@dataclass(frozen=True, slots=True)
class AgentContext:
    user_name: str
    role: str
    company: str
    now: datetime
    projects: tuple[tuple[str, str | None], ...] = ()  # (name, location)
    sites: tuple[tuple[str, str | None], ...] = ()  # (site name, project name)
    turns: tuple[Turn, ...] = ()
    last_language: str | None = None
    last_script: str | None = None  # "latin" | "native"
    has_pending_confirmation: bool = False
    menu_hint: str | None = None
    notes: list[str] = field(default_factory=list)
    #: One read-only line about the day so far ("Anil at Site A1. Saved today: ..."); None when unknown.
    today_line: str | None = None
    #: WA-36: the sender's site stock ("Stock now at Site A1 (from the records): ..."); None when unknown.
    stock_line: str | None = None


def render_context(ctx: AgentContext) -> str:
    lines = [
        f"User: {ctx.user_name} ({ctx.role}) at {ctx.company}.",
        f"Now: {ctx.now:%A %d %B %Y, %H:%M} (India time).",
    ]
    if ctx.projects:
        lines.append(
            "Projects: "
            + "; ".join(f"{name}" + (f" ({loc})" if loc else "") for name, loc in ctx.projects)
        )
    if ctx.sites:
        lines.append(
            "Sites: "
            + "; ".join(f"{name}" + (f" [{project}]" if project else "") for name, project in ctx.sites)
        )
    if len(ctx.sites) == 1:
        lines.append("They have exactly one site, so never ask which site.")
    if ctx.last_language:
        lines.append(f"Language they last wrote in: {ctx.last_language}.")
        if ctx.last_script == "latin":
            lines.append("They type it in English letters, so reply in English letters too.")
    if ctx.has_pending_confirmation:
        lines.append(
            "An earlier entry is waiting for their Yes/No. If they send a new message, "
            "treat it as new unless it is plainly Yes or No."
        )
    if ctx.menu_hint:
        lines.append(f"They just tapped the menu option: {ctx.menu_hint}.")
    if ctx.today_line:
        lines.append(ctx.today_line)
    if ctx.stock_line:
        lines.append(ctx.stock_line)
    lines.extend(ctx.notes)
    return "\n".join(lines)


def build_messages(ctx: AgentContext, user_text: str) -> list[tuple[str, str]]:
    """``(role, text)`` pairs: the context, then the last turns oldest first,
    then the new message. Roles are ``user`` and ``model``."""
    messages: list[tuple[str, str]] = [("user", f"[context]\n{render_context(ctx)}")]
    if ctx.turns:
        messages.append(("model", "Understood."))
    for turn in ctx.turns:
        if turn.user_text:
            messages.append(("user", turn.user_text))
        if turn.assistant_reply:
            messages.append(("model", turn.assistant_reply))
    messages.append(("user", f"User message:\n{user_text}"))
    return _merge_adjacent(messages)


def _merge_adjacent(messages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Gemini wants roles to alternate; join neighbours of the same role."""
    merged: list[tuple[str, str]] = []
    for role, text in messages:
        if merged and merged[-1][0] == role:
            merged[-1] = (role, f"{merged[-1][1]}\n\n{text}")
        else:
            merged.append((role, text))
    return merged
