"""Runs the model's tool calls and remembers what happened.

One `AgentToolbox` lives for one inbound message. It turns each call into a
`StepResult` through the `WorkflowGateway`, answers the model with a short
result, and keeps what the reply needs: what was saved, which answer a query
gave, and the one question (if any) the conversation is now parked on.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from channel.replies import ListRow, ReplySpec, is_module_disabled_reply
from mesiri_ai.models import ToolOutcome
from runtime.save_first import DRAFT_NOTE

from . import site_wait
from .actions import CLOSE_ISSUES, ENGINEER_QUESTION, MATERIAL_REQUEST, SITE_CONDITIONS
from .cards import CardItem, merge_changes
from .equipment import EQUIPMENT_LINE, is_equipment_only
from .gateway import StepResult, WorkflowGateway
from .later import LaterItem, held_item
from .material_direction import (
    DIRECTION_CANCEL,
    DIRECTION_OPTIONS,
    asks_direction,
    default_options,
    is_material_order,
    says_received,
)
from .save_button import SAVE_TITLE
from .site_match import short_title
from .tools import (
    ASK_USER,
    CHANGE_OR_UNDO,
    CORRECT_WORK_QUANTITY,
    GET_JOIN_CODE,
    NOTE_FOR_ENGINEER,
    QUERY_MATERIALS,
    REPORT_ISSUE,
    REQUEST_DPR,
    SAVE_LABOUR,
    SAVE_MATERIAL_USAGE,
    SAVE_WORK_DONE,
    SET_REPLY_LANGUAGE,
    SET_UNIT_CONVERSION,
    SET_WORK_SITE,
    STILL_TO_DO,
    UNDO_LAST,
    UPDATE_PENDING_CARD,
    WRITE_TOOLS,
    ScopeLookup,
    to_candidate,
    tool_specs,
)
from .wording import say

_log = logging.getLogger("mesiri.agent")

ACTION_KINDS = frozenset({ENGINEER_QUESTION, SITE_CONDITIONS, CLOSE_ISSUES, MATERIAL_REQUEST})

#: Most tool calls one message may make in total (steps are bounded separately
#: by the provider loop). A note with many parts is still a handful of calls.
MAX_CALLS = 8

#: WhatsApp reply buttons: three at most. More options go in a list.
MAX_BUTTONS = 3
MAX_LIST_ROWS = 10
_TITLE_MAX = 24  # WhatsApp button/row title limit


_RECORDED = re.compile(
    r"^\W*(?:recorded\.?(?:\s+thank you\.?)?|saved\s*:.*)\s*$", re.IGNORECASE | re.DOTALL
)


#: WA-82: update_pending_card with nothing to correct; the model saves it as new.
NOT_A_CORRECTION = "not_a_correction"


def per_stock_unit(args: dict[str, Any]) -> Decimal | None:
    """WA-61: set_unit_conversion's two amounts as the stored number -- how many
    of the unit make ONE stock unit. The model copies what was said ("1 load is
    300 nos": 1 and 300) and the code divides; asked for that number directly,
    "how many loads make 1 nos?" was unanswerable and saved upside down (live
    23 Oct: 1 load of holobricks became 0.333 nos)."""
    try:
        unit_amount = Decimal(str(args.get("unit_amount", 1)))
        stock_amount = Decimal(str(args.get("stock_amount")))
    except (InvalidOperation, ValueError):
        return None
    if unit_amount <= 0 or stock_amount <= 0:
        return None
    return unit_amount / stock_amount


def _without_recorded(text: str) -> str:
    """A saved step's words without the bare "Recorded. Thank you." line or
    the "confirm it with tonight's report" draft note -- the reply's Save
    button says how it is kept (WA-35); what is left (a stock warning, a late
    entry) is worth the model knowing."""
    text = (text or "").replace(DRAFT_NOTE, "")
    kept = [p.strip() for p in text.split("\n\n") if p.strip() and not _RECORDED.match(p.strip())]
    return "\n\n".join(kept)


#: The sender asking for their engineer, in the languages the sites write in.
_ENGINEER = re.compile(r"engin|\bengg?\b|എഞ്ചിനീ|എൻജിനീ|ഇഞ്ചിനീ|इंजीनियर|इंजिनियर", re.IGNORECASE)


def asks_for_engineer(text: str) -> bool:
    """Whether the message mentions their engineer ("engineer-inodu chodikku",
    "ask the engineer"): the only case a question is passed on."""
    return bool(_ENGINEER.search(text or ""))


def offers_engineer(reply: str) -> bool:
    """Whether a reply offered to ask their engineer ("Shall I ask your
    engineer?"), so a "yes" to it passes the question on. The "📨 Question for
    your engineer: ..." line of a question already passed on is no offer."""
    return any(
        "?" in line and asks_for_engineer(line)
        for line in (reply or "").splitlines()
        if not line.lstrip().startswith("📨")
    )


#: WA-52: a question whether a material is in stock or will last. Both parts
#: are needed: a stock word, and a question ("10 bag cement balance und,
#: kooduthal venam" is a shortage, not a question).
_STOCK_WORD = re.compile(
    r"\bstock\b|\benough\b|\bmathi\w*|\bbalance\b|\bkaa?fi\b|\bbacha\b|സ്റ്റോക്ക്|മതി|स्टॉक|काफ़?ी|बचा",
    re.IGNORECASE,
)
_QUESTION = re.compile(
    r"\?|\b(?:undo|ondo|mathiyo|aakumo|aavumo|kya|ethra|kitna|how much|is there|do we have)\b"
    r"|ഉണ്ടോ|മതിയോ|ആകുമോ|എത്ര|क्या|कितना",
    re.IGNORECASE,
)
#: Words that it ran out or work is held up: then a shortage issue is right.
_RAN_OUT = re.compile(
    r"\btheer\w*|\bkazhinj\w*|\bran out\b|\brunning out\b|\bout of\b|\bfinished\b|\bstopp?\w*"
    r"|\bnilach\w*|\bnin(?:nu|ni)\b|\bkhatam\b|\bkhatm\b|തീർന്ന|കഴിഞ്ഞ|നിന്നു|खत्म|रुक",
    re.IGNORECASE,
)
_MATERIAL_WORDS = (
    ("cement", re.compile(r"cement|സിമന്റ|സിമെന്റ|सीमेंट", re.IGNORECASE)),
    ("sand", re.compile(r"\b(?:m-?|p-?)?sand\b|മണൽ|रेत|बालू", re.IGNORECASE)),
    ("steel", re.compile(r"\bsteel\b|\btmt\b|\brods?\b|കമ്പി|सरिया", re.IGNORECASE)),
    ("brick", re.compile(r"\bbricks?\b|ഇഷ്ടിക|ईंट", re.IGNORECASE)),
    ("block", re.compile(r"\bblocks?\b", re.IGNORECASE)),
    ("aggregate", re.compile(r"\baggregate\b|\bjelly\b|\bmetal\b|മെറ്റൽ|गिट्टी", re.IGNORECASE)),
)


def asks_about_stock(text: str) -> bool:
    """Whether the message asks if a material is in stock or will be enough
    ("nale slab-inu cement mathiyo?", "nale 10 bag cement venam, ath stock undo?")."""
    text = text or ""
    return bool(_STOCK_WORD.search(text) and _QUESTION.search(text))


def material_named(text: str) -> str | None:
    """The one common material the message names, for the stock lookup; None
    when it names none or several (the lookup then lists all)."""
    found = [name for name, pattern in _MATERIAL_WORDS if pattern.search(text or "")]
    return found[0] if len(found) == 1 else None


#: "Tomorrow plan: 2nd floor slab casting, need 15 workers" -- the plan is what follows.
_TOMORROW_PLAN = re.compile(
    r"(?:tomorrow'?s?\s+plan|plan\s+for\s+tomorrow|plan\s+tomorrow|nale(?:yude|thhe|the)?\s+plan"
    r"|നാളത്തെ\s+പ്ലാൻ|कल\s+का\s+(?:प्लान|plan))\s*[:\-–]?\s*(?P<plan>.+)",
    re.IGNORECASE | re.DOTALL,
)


def tomorrow_plan_text(text: str) -> str | None:
    """The plan in a "Tomorrow plan: ..." message, else None (request 104, B)."""
    found = _TOMORROW_PLAN.search(text or "")
    plan = " ".join(found.group("plan").split())[:500] if found else ""
    return plan or None


#: Request 104, D2: "rain since afternoon, work stopped" says when it began, not
#: how long: the hours lost are asked once.
HOURS_QUESTION = "About how many hours were lost?"
HOURS_OPTIONS = ["2 hours", "4 hours", "Full day"]
_SINCE = re.compile(
    r"\bsince\s+(?:the\s+)?(?:morning|afternoon|evening|noon|lunch)\b"
    r"|\bfrom\s+(?:the\s+)?(?:morning|afternoon)\b"
    r"|\b(?:morning|afternoon|raavile|ucha)\s*(?:muthal|mudal|mutal)\b"
    r"|രാവിലെ\s*മുതൽ|ഉച്ച\w*\s*മുതൽ|सुबह\s*से|दोपहर\s*से",
    re.IGNORECASE,
)
_STOPPED = re.compile(
    r"\bstop+\w*|\bhalt\w*|\bnirth\w*|\bnilach\w*|\bno work\b|നിർത്ത|നിന്ന|बंद|रुक",
    re.IGNORECASE,
)
_HOURS_GIVEN = re.compile(r"\d\s*(?:hours?|hrs?|h\b|minutes?|mins?|മണിക്കൂർ|घंटे)|\bfull day\b|\bhalf day\b", re.IGNORECASE)


_PEOPLE = r"(?:worker|labour|labourer|mason|helper|person|man|woman|someone|painter|electrician|carpenter|plumber|supervisor)"
_SAFETY = re.compile(
    r"\binjur\w*|\baccident\w*|\bhurt\b|\bambulance\b|\bhospital\b|\bbleed\w*|\bshock(?:ed)?\b"
    rf"|\b{_PEOPLE}s?\s+(?:\w+\s+){{0,2}}(?:fell|fallen|slipped|collapsed)\b"
    r"|പരിക്ക്|അപകടം|चोट|हादसा|दुर्घटना|\bghayal\b|\bchot\b|\bapakadam\b|\bparikk\w*",
    re.IGNORECASE,
)
_QUALITY = re.compile(
    r"\bleak\w*|\bseepage\b|\bcracks?\b|\bcracked\b|\bdampness\b|ചോർച്ച|വിള്ളൽ|रिसाव|दरार|\bchoorch\w*",
    re.IGNORECASE,
)
_RAISE_TO_HIGH = {"", "LOW", "MEDIUM"}


def classify_issue(text: str, args: dict[str, Any]) -> dict[str, Any]:
    """Request 104, D3: "worker fell / injury / accident" is SAFETY (severity at
    least HIGH); "leak / seepage / crack", filed as OTHER, is QUALITY. The model
    picks the type; this only corrects the two cases it left in OTHER."""
    said = f"{text or ''} {args.get('narrative') or ''}"
    kind = str(args.get("issue_type") or "").upper()
    if _SAFETY.search(said) and kind != "SAFETY":
        severity = str(args.get("severity") or "").upper()
        return {**args, "issue_type": "SAFETY", "severity": "HIGH" if severity in _RAISE_TO_HIGH else severity}
    if kind == "SAFETY":
        severity = str(args.get("severity") or "").upper()
        return {**args, "severity": "HIGH" if severity in _RAISE_TO_HIGH else severity}
    if kind in ("", "OTHER") and _QUALITY.search(said):
        return {**args, "issue_type": "QUALITY"}
    return args


def needs_hours_question(text: str, args: dict[str, Any]) -> bool:
    """A work-stopping issue that says when it began but not for how long."""
    if args.get("delay_duration_minutes") not in (None, "", 0):
        return False
    text = text or ""
    return bool(_SINCE.search(text) and _STOPPED.search(text) and not _HOURS_GIVEN.search(text))


def _tool_fields(tool: str) -> set[str]:
    """The argument names a save tool takes: what a card change may touch."""
    for spec in tool_specs():
        if spec.name == tool:
            return set((spec.parameters or {}).get("properties", {}))
    return set()


def _title(option: str) -> str:
    option = " ".join(str(option).split())
    return option if len(option) <= _TITLE_MAX else option[: _TITLE_MAX - 1] + "…"


def rejoin_names(options: list[Any], known: list[str]) -> list[str]:
    """``options`` with a name that holds a comma put back together: a model
    that read "Green Villa, Kakkanad" as two options gave two buttons (live,
    24 Oct). Only a run of options that spells one of their own names is joined."""
    items = [str(o).strip() for o in options if str(o).strip()]
    if not known:
        return items
    wanted = {" ".join(name.casefold().split()): name for name in known}
    out: list[str] = []
    i = 0
    while i < len(items):
        for size in range(min(len(items) - i, 4), 1, -1):
            joined = ", ".join(items[i : i + size])
            hit = wanted.get(" ".join(joined.casefold().split()))
            if hit is not None:
                out.append(hit)
                i += size
                break
        else:
            out.append(items[i])
            i += 1
    return out


#: WhatsApp cuts a reply button's title at 20 characters (a list row's at 24).
_BUTTON_TITLE_MAX = 20


def _choice_reply(question: str, options: list[str], list_label: str) -> ReplySpec:
    """The one question as a message. Up to three options that all fit a
    button (20 characters) are buttons; anything else is a list, whose rows
    carry a title cut only between words and the full option underneath --
    never a button cut mid-sentence ("The amount in cubic", live 24 Oct)."""
    labels = [" ".join(str(o).split()) for o in options if str(o).strip()][:MAX_LIST_ROWS]
    if 0 < len(labels) <= MAX_BUTTONS and all(len(o) <= _BUTTON_TITLE_MAX for o in labels):
        return ReplySpec(text=question, buttons=tuple(ListRow(f"agent_opt_{i}", o) for i, o in enumerate(labels, 1)))
    rows = []
    for i, label in enumerate(labels, 1):
        title = short_title(label, _TITLE_MAX)
        rows.append(ListRow(f"agent_opt_{i}", title, label[:72] if title != label else ""))
    return ReplySpec(text=question, list_button_label=list_label, list_rows=tuple(rows)) if rows else ReplySpec(text=question)


def site_reply(question: str, options: list[str]) -> ReplySpec:
    """The site question ([111])."""
    return _choice_reply(question, options, "Choose site")


def question_reply(question: str, options: list[str], *, awaiting: str = "", rows: tuple[Any, ...] = ()) -> ReplySpec:
    """The one question as a message: buttons when the options are short
    (up to three), a list otherwise (up to ten), plain text with none. ``rows``
    (request 142) are rows the code made, with ids it reads back: sent as they are."""
    if rows:
        return ReplySpec(text=question, list_button_label="Choose one", list_rows=tuple(rows)[:MAX_LIST_ROWS])
    if awaiting == "site":
        return site_reply(question, options)
    return _choice_reply(question, options, "Choose one")


@dataclass(slots=True)
class SavedItem:
    tool: str
    text: str
    #: What was saved in a few words, from the saved data; the reply's
    #: "Saved:" list is built from these, never from the user's own words.
    summary: str | None = None
    #: An item of the open card this turn changed that was not itself changed:
    #: it stays on the card and its "To save:" line, but the model's sentence
    #: need not name it.
    carried: bool = False


@dataclass(slots=True)
class AgentToolbox:
    gateway: WorkflowGateway
    scope: ScopeLookup
    user_text: str
    #: Request 143: the turn's reply language, decided once (``wording.decide``):
    #: every line the code writes this turn is in it.
    language: str = "english"
    saved: list[SavedItem] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: The one question the conversation is parked on, if any.
    parked: ReplySpec | None = None
    #: "gate": the pipeline itself needs an answer or a Yes/No before it can go
    #: on, so no further record may be filed this turn (it keeps ONE waiting
    #: state per sender). "ask": the model's own question -- the message's other
    #: parts are independent and still get saved.
    parked_by: str | None = None
    #: The parked question is a record waiting on Yes/No (confirm-first): its
    #: details are always shown with the buttons, whatever the model wrote.
    parked_confirm: bool = False
    #: Tool calls not run because a gate was waiting (named for the reply).
    held: list[str] = field(default_factory=list)
    #: WA-57: parts of the message still to do (held calls and the model's
    #: still_to_do notes), kept for the sender's next turns (runtime/agent/later.py).
    later: list[LaterItem] = field(default_factory=list)
    #: WA-58: numbers of listed parts the model said are done or not needed.
    later_drop: set[int] = field(default_factory=set)
    attempted_writes: int = 0
    calls: int = 0
    #: B-7: the journey's lap stopwatch; time before a tool call is the
    #: model's ("agent_model"), time in it is the tool's ("agent_tools").
    lap: Callable[[str], None] | None = None
    #: B-7: called after every tool call, so the receipt card can be made
    #: while the model writes the reply.
    after_tool: Callable[[], None] | None = None
    failed: int = 0
    #: Request 143: what request_dpr answered (the code's sentence, in the sender's
    #: language) and how many PDFs it sent. The reply says it, never the model.
    report_text: str | None = None
    report_documents: int = 0
    #: Request 104: the card lines this turn prepared for pending actions.
    _action_summaries: list[str] = field(default_factory=list)
    #: Request 104, D2: the hours-lost question was the last thing asked.
    hours_asked: bool = False
    #: MAT-07: a "used" save for a message that says the material arrived was
    #: sent back once (to save_material_receipt).
    direction_redirected: bool = False
    #: Request 104: every tool the model called this message (even a refused one).
    called: set[str] = field(default_factory=set)
    #: Request 104: the message is only about equipment, which WhatsApp does not
    #: record yet; its reply is the one plain line, never a Save.
    equipment_noted: bool = False
    #: WA-84: a request for a module the company has switched off: the code's one line
    #: is the reply (in the sender's language), not the model's English retelling of it.
    module_off_line: str = ""
    #: The last reply offered to ask their engineer, so a bare "yes" asks it.
    engineer_offered: bool = False
    #: Request 88: lines the system adds under the model's words, from the
    #: data ("Removed: 2 painters (today)").
    system_lines: list[str] = field(default_factory=list)
    #: Request 88: items of the open card that follow the one being changed.
    _carry_after: list[SavedItem] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)
    #: [111] (runtime/agent/site_wait.py): save calls from earlier messages that
    #: are waiting on the site answer, oldest first, as loaded for this turn...
    site_queue: list[dict[str, Any]] = field(default_factory=list)
    #: ...and the ones this turn's own site question now holds.
    site_new: list[dict[str, Any]] = field(default_factory=list)
    #: The waiting calls were released (saved at the answered site) this turn.
    site_released: bool = False
    #: The parked question is the code's own site question: it is sent as
    #: worded in code, in the sender's language, whatever the model wrote.
    parked_site: bool = False
    #: Live 29 Oct: ``(language | None) -> kept?``, keeps the sender's reply
    #: language (runtime/agent/turn.py); None: ``set_reply_language`` is refused.
    reply_language_setter: Callable[[str | None], Awaitable[bool]] | None = None
    #: ``set_reply_language`` ran this message, and what it set (None: auto).
    language_changed: bool = False
    language_choice: str | None = None
    #: WA-52: what the stock lookup answered this message, if it ran.
    _stock_answer: str | None = None
    _inflight: set[asyncio.Task[Any]] = field(default_factory=set)

    async def handle(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        """The provider's tool handler. Shielded: if the run's deadline cancels
        the model loop while a save is in flight, the save still finishes and
        is recorded here, so the reply never forgets (or repeats) it."""
        if self.lap is not None:
            self.lap("agent_model")
        task = asyncio.ensure_future(self._dispatch(name, args))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        try:
            return await asyncio.shield(task)
        finally:
            if self.lap is not None:
                self.lap("agent_tools")
            if self.after_tool is not None:
                try:
                    self.after_tool()
                except Exception:  # noqa: BLE001 -- a speed-up, never a failure
                    _log.warning("agent.after_tool_failed", exc_info=True)

    def drop_actions(self) -> None:
        """Request 104: a reply that ends on a question carries no Save card, so
        the cards prepared in the same turn are withdrawn -- the reply never
        lists them as waiting."""
        discard = getattr(self.gateway, "discard_actions", None)
        if discard is None or not getattr(self.gateway, "action_items", None):
            return
        gone = {i.fact_id for i in self.gateway.action_items}
        discard()
        self.saved = [i for i in self.saved if not any(i.summary == s for s in self._action_summaries)]
        self._action_summaries = []
        _log.info("agent.cards_dropped count=%s", len(gone))

    async def settle(self, timeout: float = 5.0) -> None:
        """Wait for tool calls still running after the model loop was cut off."""
        if self._inflight:
            await asyncio.wait(list(self._inflight), timeout=timeout)

    async def _dispatch(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        if name == STILL_TO_DO:
            return self._still_to_do(args)
        if self.parked_by == "gate":
            self.held.append(name)
            if name in WRITE_TOOLS:
                self.later.append(held_item(name, args))
            elif name == ASK_USER:
                self._note_later(args.get("other_parts"))
            return ToolOutcome(
                content={
                    "status": "held",
                    "reason": (
                        "waiting for the user's answer to another question first; "
                        "tell them this part still needs doing afterwards"
                    ),
                }
            )
        self.called.add(name)
        self.calls += 1
        if self.calls > MAX_CALLS:
            await self._note_lost(name, args, "too many in one message")
            return ToolOutcome(
                content={"status": "skipped", "reason": "too many actions in one message"}
            )
        if name == ASK_USER and asks_direction(str(args.get("question") or "")) and says_received(self.user_text):
            # MAT-07: it says the material came; that is a receipt, not a question.
            _log.warning("agent.direction_question_refused")
            return ToolOutcome(
                content={
                    "status": "not_asked",
                    "reason": "the message says the material arrived, so it was received",
                    "instruction": (
                        "Do not ask 'Received or used?'. Call save_material_receipt now with the "
                        "material, quantity and unit from the message."
                    ),
                }
            )
        if name == SAVE_MATERIAL_USAGE and says_received(self.user_text) and not self.direction_redirected:
            # The same words, the wrong tool: arrived material is not a usage.
            self.direction_redirected = True
            return ToolOutcome(
                content={
                    "status": "not_saved",
                    "reason": "the message says the material arrived, so it was received, not used",
                    "instruction": "Nothing was saved. Call save_material_receipt with the same material, quantity and unit.",
                }
            )
        if name == ASK_USER:
            return self._ask(args)
        if name == SET_WORK_SITE:
            return await self._set_work_site(args)
        if name == SET_REPLY_LANGUAGE:
            return await self._set_reply_language(args)
        if name == NOTE_FOR_ENGINEER and not (self.engineer_offered or asks_for_engineer(self.user_text)):
            # Ilan, 21 Oct: a question goes to the engineer ONLY when the
            # sender asks for that. The live model passed "is there enough
            # cement for tomorrow's slab?" on instead of answering it.
            # WA-52: telling it to look the stock up was not enough (23 Oct it
            # still said "I'll ask your engineer"), so a stock question gets
            # the stock looked up here and handed back with the refusal.
            stock = await self._stock_for_question()
            if stock:
                return ToolOutcome(
                    content={
                        "status": "not_asked_to_pass_on",
                        "stock": stock,
                        "instruction": (
                            "They did not ask you to ask their engineer. Answer their question "
                            "yourself from these stock figures, copying the numbers. Do not say "
                            "you will ask anyone."
                        ),
                    }
                )
            return ToolOutcome(
                content={
                    "status": "not_asked_to_pass_on",
                    "instruction": (
                        "They did not ask you to ask their engineer, so answer it yourself: "
                        "use the facts you were given or the query tools (query_materials for "
                        "stock). If the records cannot answer it, say so plainly in one line "
                        "and offer to ask their engineer."
                    ),
                }
            )
        if name == REPORT_ISSUE and asks_about_stock(self.user_text) and not _RAN_OUT.search(self.user_text):
            # WA-52: "nale 10 bag cement venam, ath stock undo?" asks whether
            # it is in stock; the live model filed it as a Material Shortage
            # card. A question is answered, never saved as a problem.
            stock = await self._stock_for_question()
            return ToolOutcome(
                content={
                    "status": "not_saved",
                    "reason": "they asked whether it is in stock: a question, not a problem on site",
                    "stock": stock or "",
                    "instruction": (
                        "Nothing was saved and nothing needs saving. Answer their question from "
                        "these stock figures, copying the numbers. Do not report an issue for it "
                        "and do not say you will ask anyone."
                    ),
                }
            )
        if name in (SAVE_WORK_DONE, SAVE_LABOUR) and is_equipment_only(self.user_text):
            _log.warning("agent.equipment_not_recorded tool=%s", name)
            self.equipment_noted = True
            return ToolOutcome(
                content={
                    "status": "not_saved",
                    "reason": "equipment is not recorded on WhatsApp yet",
                    "instruction": f"Nothing was saved. Say exactly: {EQUIPMENT_LINE}",
                }
            )
        if name == REPORT_ISSUE and is_material_order(self.user_text) and not _RAN_OUT.search(self.user_text):
            # Request 143 (E): "50 bag cement order cheyyanam" is material to order, not a problem
            # on site. Nothing is filed as an issue; the model is told to make the request.
            return ToolOutcome(
                content={
                    "status": "not_saved",
                    "reason": "an order for material is a material request, not a site issue",
                    "instruction": "Nothing was saved. Call request_material with the material, quantity, unit and when it is needed.",
                }
            )
        if name == REPORT_ISSUE:
            args = classify_issue(self.user_text, args)
        if (
            name == REPORT_ISSUE
            and not self.hours_asked
            and self.parked is None
            and needs_hours_question(self.user_text, args)
        ):
            self.parked = question_reply(HOURS_QUESTION, HOURS_OPTIONS)
            self.parked_by = "ask"
            return ToolOutcome(
                content={
                    "status": "question_sent",
                    "reason": "the hours lost are not said, so the issue is not saved yet",
                    "instruction": (
                        f"Nothing was saved yet. End your message with: {HOURS_QUESTION} (its options "
                        "are shown as buttons). When they answer, call report_issue again with the same "
                        "issue and delay_duration_minutes (2 hours = 120, 4 hours = 240, Full day = 480)."
                    ),
                }
            )
        signature = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        if signature in self._seen and name in WRITE_TOOLS:
            return ToolOutcome(
                content={"status": "duplicate_ignored", "reason": "already done in this message"}
            )
        self._seen.add(signature)
        if name in WRITE_TOOLS:
            self.attempted_writes += 1
        earlier: list[str] = []
        behind: list[dict[str, Any]] = []
        site = None
        if name in WRITE_TOOLS and self.site_queue and not self.site_released:
            site = self._answered_site(args)
            if site:
                ahead, behind = self._split_site_queue(name, args)
                earlier = await self._replay_site(ahead, site, args.get("project"))
        try:
            step = await self._run(name, args)
        except Exception:  # noqa: BLE001 — the model is told; the trace keeps the cause
            _log.exception("agent.tool_failed tool=%s", name)
            self.failed += 1
            await self._note_lost(name, args, "that action failed")
            return ToolOutcome(content={"status": "error", "message": "that action failed"})
        if step.status == "choose" and step.awaiting == "site" and name in WRITE_TOOLS:
            self._hold_for_site(name, args)
        outcome = self._outcome(name, step)
        if behind and site:
            earlier += await self._replay_site(behind, site, args.get("project"))
        if earlier:
            outcome.content["also_saved_from_earlier_messages"] = earlier
            outcome.content["instruction"] = (
                "These earlier messages were waiting for the site and are now on the same card. "
                "Do not save them again and do not ask about them."
            )
        return outcome

    @property
    def draft_mode(self) -> bool:
        """Request 124: the company holds messages as one draft card."""
        return getattr(self.gateway, "draft_mode", False) is True

    async def _note_lost(self, name: str, args: dict[str, Any], reason: str) -> None:
        """A save call that will not become a line on the card is listed on it
        as "Couldn't read: ...", never dropped silently (ADR section 2.6)."""
        from .draft import DRAFT_TOOLS

        if not (self.draft_mode and name in DRAFT_TOOLS):
            return
        try:
            from . import draft_flow

            await draft_flow.note_lost(self.gateway, name, args, reason)
        except Exception:  # noqa: BLE001 -- the card then lacks the line; the call is still logged
            _log.warning("agent.note_lost_failed tool=%s", name, exc_info=True)

    # -- [111] saves waiting on the site answer ---------------------------------

    @staticmethod
    def _bare(args: dict[str, Any]) -> str:
        return json.dumps({k: v for k, v in args.items() if k not in ("site", "project")}, sort_keys=True, default=str)

    def _hold_for_site(self, name: str, args: dict[str, Any]) -> None:
        """This save ended in the site question: keep it, so the answer saves it
        (and the ones before it) instead of the newest question replacing them."""
        bare = self._bare(args)
        if any(i["tool"] == name and self._bare(i["args"]) == bare for i in [*self.site_queue, *self.site_new]):
            return
        note = " ".join(self.user_text.split())[:120]
        self.site_new.append({"tool": name, "args": dict(args), "note": note})

    def _answered_site(self, args: dict[str, Any]) -> str | None:
        """The site a save names when it is one of the sender's own: the answer
        to the site question (a tap or a typed name, passed on by the model)."""
        site = str(args.get("site") or "").strip()
        if not site:
            return None
        project = str(args.get("project") or "").strip()
        project_id = self.scope.project_id(project) if project else None
        return site if self.scope.site_id(site, project_id) is not None else None

    def _split_site_queue(self, name: str, args: dict[str, Any]) -> tuple[list[dict], list[dict]]:
        """The waiting calls before and after the one being made now (which
        covers its own entry), so the card keeps the order they came in. A call
        that is none of them leaves everything ahead of it."""
        queue, self.site_queue = self.site_queue, []
        self.site_released = True
        bare = self._bare(args)
        for n, item in enumerate(queue):
            if item["tool"] == name and self._bare(item["args"]) == bare:
                return queue[:n], queue[n + 1 :]
        return queue, []

    async def _replay_site(self, items: list[dict[str, Any]], site: str, project: Any) -> list[str]:
        """Save each waiting call at ``site``, in order. They land on the same
        card; what cannot be saved is said, never dropped."""
        done: list[str] = []
        for item in items:
            args = {k: v for k, v in item["args"].items() if k not in ("site", "project")}
            args["site"] = site
            if project:
                args["project"] = project
            signature = f"{item['tool']}:{json.dumps(args, sort_keys=True, default=str)}"
            if signature in self._seen:
                continue
            self._seen.add(signature)
            self.attempted_writes += 1
            try:
                step = await self._run(item["tool"], args)
            except Exception:  # noqa: BLE001 -- said below; the trace keeps the cause
                _log.exception("agent.site_release_failed tool=%s", item["tool"])
                self.failed += 1
                step = StepResult("error", text="That action failed.")
            if step.status in ("saved", "drafted"):
                # Request 132: on a draft card the call became a line of the card; it
                # was left as "Not saved (...):" with nothing after it, beside the line.
                self._outcome(item["tool"], step)
                done.append(step.summary or step.text)
            elif step.text:
                self.system_lines.append(f"Not saved ({item.get('note') or item['tool']}): {step.text}".strip())
        return done

    async def finish_site_queue(self) -> None:
        """End of the turn: waiting calls the model did not release. A reply that
        is just a site's name still releases them; any other message that did
        not ask the site again leaves them unsaved, and the sender is told."""
        if not self.site_queue or self.site_released or self.parked is not None:
            return
        typed = " ".join(self.user_text.split())
        site = typed if 0 < len(typed.split()) <= 6 and self.scope.site_id(typed) is not None else None
        if site:
            ahead, _ = self._split_site_queue("", {})
            await self._replay_site(ahead, site, None)
            return
        from .work_site import _language_of, _say

        items = ", ".join(f"“{i['note'][:40]}”" if i.get("note") else i["tool"] for i in self.site_queue)
        self.system_lines.append(_say(_language_of(self.user_text), "dropped", items=items))
        self.site_queue = []

    def site_queue_after(self) -> list[dict[str, Any]]:
        """What still waits on the site answer after this turn."""
        out = list(self.site_queue)
        for item in self.site_new:
            if len(out) >= site_wait.MAX_WAITING:
                line = "I'm already holding too many updates. Please pick the site first, then send the rest."
                if line not in self.system_lines:
                    self.system_lines.append(line)
                break
            out.append(item)
        return out

    def site_hold_line(self) -> str | None:
        waiting = len(self.site_queue_after())
        if waiting < 2:
            return None
        from .work_site import _language_of, _say

        return _say(_language_of(self.user_text), "hold", n=waiting)

    def answers_only_stock(self) -> bool:
        """Request 143: the turn's answers are the stock answer and nothing else, so
        the Stock card is its picture. A week summary that also looked at stock is
        not a stock answer: no Stock card on it."""
        return bool(self._stock_answer) and all(a == self._stock_answer for a in self.answers)

    async def _stock_for_question(self) -> str | None:
        """WA-52: the stock answer for a message asking whether a material is
        in stock or will be enough -- the one the model already got this
        message, else looked up now (the named material, else all of them).
        None when the message asks no such thing or the lookup fails."""
        if self._stock_answer is not None:
            return self._stock_answer
        if not asks_about_stock(self.user_text):
            return None
        return await self.look_up_stock()

    async def look_up_stock(self) -> str | None:
        """The stock lookup (``query_materials``) for this message: the named
        material, else all of them. Its answer is recorded like the model's own
        call; its Stock card is drawn by the query entry. None when it fails."""
        material = material_named(self.user_text)
        for args in ([{"material": material}] if material else []) + [{}]:
            try:
                step = await self._run(QUERY_MATERIALS, args)
            except Exception:  # noqa: BLE001 -- the refusal still goes back without figures
                _log.exception("agent.stock_lookup_failed")
                return None
            if step.status == "answer" and step.text:
                self.answers.append(step.text)
                self._stock_answer = step.text
                return step.text
        return None

    def _still_to_do(self, args: dict[str, Any]) -> ToolOutcome:
        """WA-57: the parts the model cannot record this turn, kept for later;
        WA-58: listed parts it says are done or not needed, dropped."""
        noted = self._note_later(args.get("items"))
        dropped = {n for n in args.get("drop") or [] if isinstance(n, int) and n > 0}
        self.later_drop |= dropped
        if not noted and not dropped:
            return ToolOutcome(content={"status": "error", "message": "nothing to note"})
        return ToolOutcome(
            content={
                "status": "noted",
                "instruction": "It is asked after this. Do not mention this note in your reply.",
            }
        )

    def _note_later(self, rows: Any) -> int:
        noted = 0
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            what = str(row.get("what") or "").strip()
            tool = str(row.get("tool") or "").strip()
            if what:
                self.later.append(LaterItem(tool if tool in WRITE_TOOLS else "", what))
                noted += 1
        return noted

    def _ask(self, args: dict[str, Any]) -> ToolOutcome:
        question = str(args.get("question") or "").strip()
        if not question:
            return ToolOutcome(content={"status": "error", "message": "no question given"})
        if self.parked is not None:
            return ToolOutcome(
                content={"status": "skipped", "reason": "one question per message"}
            )
        options = args.get("options") or []
        options = rejoin_names(options if isinstance(options, list) else [], self._known_names())
        if asks_direction(question):
            # Request 143: "Received or used?" is the code's question, in their language,
            # and it can be cancelled.
            what = " ".join(self.user_text.split())[:40]
            question = say("material.direction", self.language, what=what)
            options = [*DIRECTION_OPTIONS, DIRECTION_CANCEL]
        if not options:
            # MAT-08: "cement vannu" -> "How many?" came with no buttons.
            options = list(default_options(question, self.user_text))
        self.parked = question_reply(question, options)
        self.parked_by = "ask"
        # WA-58: what the question leaves aside is taken up next.
        self._note_later(args.get("other_parts"))
        return ToolOutcome(
            content={
                "status": "question_sent",
                "instruction": "Your final message must end with this question.",
            }
        )

    def _known_names(self) -> list[str]:
        """Their project and site names that hold a comma."""
        names = [name for _pid, name in self.scope.projects] + [name for _sid, name, _pid in self.scope.sites]
        return [name for name in names if "," in name]

    async def _set_reply_language(self, args: dict[str, Any]) -> ToolOutcome:
        """Live 29 Oct: the sender sets the language every reply is in ("type
        Manglish, answer in Malayalam"). Kept by the turn's ``reply_language_setter``;
        this message's own reply follows it at once."""
        from .prompt import PREFERRED_LANGUAGES

        choice = str(args.get("language") or "").strip().lower()
        preference = choice if choice in PREFERRED_LANGUAGES else None
        if choice not in (*PREFERRED_LANGUAGES, "auto"):
            return ToolOutcome(content={"status": "error", "reason": f"unknown language {choice!r}"})
        if self.reply_language_setter is None or not await self.reply_language_setter(preference):
            return ToolOutcome(
                content={"status": "not_saved", "instruction": "Say in one line that the language could not be changed now."}
            )
        # The tool runs in its own task (``handle``): the runner applies it to the turn.
        self.language_changed, self.language_choice = True, preference
        said = (
            f"Every reply is now in {preference.title()}, whatever language they type in."
            if preference
            else "Replies now follow the language of each message again."
        )
        return ToolOutcome(
            content={"status": "done", "result": said, "instruction": "Confirm it in one short line, in that language."}
        )

    async def _set_work_site(self, args: dict[str, Any]) -> ToolOutcome:
        """WA-45: "now at Site B". One of their sites -> today's site; anything
        else -> their sites as the one question (never a guess)."""
        project = str(args.get("project") or "").strip()
        project_id = self.scope.project_id(project) if project else None
        site_id = self.scope.site_id(str(args.get("site") or ""), project_id)
        if site_id is None:
            names = [name for _sid, name, pid in self.scope.sites if project_id in (None, pid)]
            if self.parked is None and names:
                self.parked = question_reply("Which site are you at?", names)
                self.parked_by = "ask"
            return ToolOutcome(
                content={
                    "status": "choose",
                    "message": "That is not one of their sites.",
                    "instruction": (
                        "Nothing was changed. End your message asking which of their sites they are "
                        "at (the options are shown as buttons). If it is a new site, they can ask you "
                        "to create it."
                    ),
                }
            )
        if getattr(self.gateway, "draft_mode", False) is True:
            # Request 132: only a plain "now at Site B" moves the sender; a site named
            # while setting up the team or asking something says where it IS.
            from .draft_site import is_location_statement

            site_name = next((name for sid, name, _pid in self.scope.sites if str(sid) == str(site_id)), "")
            if not is_location_statement(self.gateway.actor, self.user_text, site_name):
                return ToolOutcome(
                    content={
                        "status": "not_a_move",
                        "message": "Their message names that site but does not say they are working there.",
                        "instruction": (
                            "Nothing was changed. Do not call set_work_site for this message; handle its "
                            "parts with the other tools, naming the site in them where it matters."
                        ),
                    }
                )
        try:
            label = await self.gateway.set_work_site(project_id=project_id, site_id=site_id)
        except Exception:  # noqa: BLE001 -- the model is told; the trace keeps the cause
            _log.exception("agent.set_work_site_failed")
            self.failed += 1
            return ToolOutcome(content={"status": "error", "message": "could not switch the site"})
        return ToolOutcome(
            content={
                "status": "work_site_set",
                "site": label,
                "instruction": (
                    f"Say in one short line that you will use {label} for the rest of today. "
                    "Nothing needs saving for this."
                ),
            }
        )

    async def _run(self, name: str, args: dict[str, Any]) -> StepResult:
        if name == CHANGE_OR_UNDO:
            return await self._change_or_undo(args)
        if name == UNDO_LAST and str(args.get("what") or "latest_update") == "latest_update":
            return await self._undo(args)
        if name == UPDATE_PENDING_CARD:
            return await self._update_card(args)
        if name == CORRECT_WORK_QUANTITY and self.draft_mode:
            return await self._correct_work(args)
        if name == GET_JOIN_CODE:
            return await self.gateway.share_join_code()
        if name == SET_UNIT_CONVERSION:
            return await self.gateway.set_unit_conversion(
                material=str(args.get("material") or ""),
                unit=str(args.get("unit") or ""),
                count=per_stock_unit(args),
            )
        candidate = to_candidate(name, args, self.scope)
        if candidate is None:
            return StepResult(status="error", text=f"unknown tool {name}")
        return await self._run_candidate(name, args, candidate)

    async def _run_candidate(self, name: str, args: dict[str, Any], candidate: Any) -> StepResult:
        """A save through the gateway, noting which tool and arguments made the
        record so its card can undo or change it later (request 88)."""
        try:
            self.gateway.current_call = (name, args)  # type: ignore[attr-defined]
        except AttributeError:  # a gateway without cards
            pass
        return await self.gateway.run(candidate, text=self.user_text)

    async def _undo(self, args: dict[str, Any]) -> StepResult:
        """Request 88: undo the entries of the latest card. The model may only
        name ids the code listed; the gateway rejects any other."""
        if self.draft_mode:
            draft = await self.gateway.open_draft()
            if draft is not None and draft.live:
                # Request 124: the open card is a draft -- cancelling it removes
                # it whole, and nothing was ever written.
                from . import draft as dr

                lines = "; ".join(i.line for i in draft.items if i.state != dr.UNREADABLE)
                reply = await self.gateway.cancel_draft(draft)
                if reply.text != dr.CANCELLED:
                    return StepResult("info", text=reply.text)
                return StepResult("undone", text=f"Removed from the card: {lines}. Nothing was saved.")
        if getattr(self.gateway, "journal_mode", False) is True:
            # Request 142 (B): what was saved is undone from the journal, after a confirm card.
            step = await self.gateway.change_or_undo("last")
            from .journal import NOTHING

            if step.text != NOTHING:
                return step
        undo_card = getattr(self.gateway, "undo_card", None)
        if undo_card is None:
            return StepResult("info", text="Nothing to undo from your last card.")
        targets = args.get("targets")
        refs = [str(t) for t in targets] if isinstance(targets, list) else []
        return await undo_card(refs)

    async def _change_or_undo(self, args: dict[str, Any]) -> StepResult:
        """Request 142 (B): the one tool to take back or correct something. A card
        not saved yet is cancelled / edited as before; anything saved goes through
        the journal, with a confirm card for a removal."""
        target = str(args.get("target") or "last").strip()
        changes = args.get("changes")
        changes = changes if isinstance(changes, dict) and [v for v in changes.values() if v is not None] else None
        if getattr(self.gateway, "journal_mode", False) is not True:
            return await self._undo({})
        if changes:
            return await self.gateway.change_or_undo(target, changes)
        if target.casefold() in ("", "last", "latest", "that", "it", "this"):
            return await self._undo({})
        step = await self.gateway.change_or_undo(target)
        return step

    async def _update_card(self, args: dict[str, Any]) -> StepResult:
        """Request 88: change one item of the open card. The old draft is
        withdrawn and the new one saved through the item's own save tool, so
        every check of that tool runs again; the card is then shown again."""
        gateway = self.gateway
        if self.draft_mode:
            return await self._update_draft(args)
        open_card = getattr(gateway, "open_card", None)
        card = await open_card() if open_card is not None else None
        if card is None:
            return StepResult("info", text="There is no open card of theirs to change. If it is already saved, it can be undone and sent again.")
        if str(args.get("card_id") or "") != card.id:
            return StepResult("error", text="That card is not their open card, so nothing was changed.")
        try:
            index = int(args.get("item_index"))
        except (TypeError, ValueError):
            index = 0
        if not 1 <= index <= len(card.items):
            return StepResult("error", text="That item is not on their open card, so nothing was changed.")
        changes = args.get("changes")
        item: CardItem = card.items[index - 1]
        allowed = _tool_fields(item.tool)
        if not isinstance(changes, dict) or not changes:
            return StepResult("error", text="No change was given, so nothing was changed.")
        unknown = sorted(set(changes) - allowed)
        if unknown:
            return StepResult("error", text=f"{', '.join(unknown)} cannot be changed on this kind of entry, so nothing was changed.")
        merged = merge_changes(item.tool, item.args, changes)
        candidate = to_candidate(item.tool, merged, self.scope)
        if candidate is None:
            return StepResult("error", text="That item cannot be changed here.")
        before, after = card.items[: index - 1], card.items[index:]
        if not await gateway.withdraw_card_item(item):
            return StepResult("error", text="Couldn't change it: that entry could not be taken back. Nothing was changed.")
        step = await self._run_candidate(item.tool, merged, candidate)
        if step.status == "saved":
            gateway.carry_card_items(before, after)
            self.saved.extend(SavedItem(i.tool, i.summary, i.summary, carried=True) for i in before)
            self._carry_after = [SavedItem(i.tool, i.summary, i.summary, carried=True) for i in after]
            return step
        if step.status in ("needs_confirmation", "needs_answer", "choose"):
            # The tool's own question is now the one the conversation waits on,
            # with the merged arguments; the other items stay on the card.
            gateway.carry_card_items(before, after)
            return step
        # Refused: put the old entry back, so a failed change loses nothing.
        restored = await self._run_candidate(item.tool, item.args, to_candidate(item.tool, item.args, self.scope))
        if restored.status == "saved":
            gateway.carry_card_items(before, after)
            self.saved.extend(SavedItem(i.tool, i.summary, i.summary, carried=True) for i in before)
            self.saved.append(SavedItem(item.tool, restored.text, restored.summary))
            self._carry_after_flush()
            return StepResult("error", text=f"{step.text} The card is as it was.".strip())
        return StepResult(
            "error", text="The change did not go through and the old entry could not be put back: they need to send it again."
        )

    async def _correct_work(self, args: dict[str, Any]) -> StepResult:
        """Request 137 (C): a correction of saved work, resolved in code against the
        day's saved facts (``day_facts``: the database, with the saved card on top).
        A percent that is not a correction ("tiling 80% aayi") is progress, a new
        line; an explicit one ("alla, 75%") or a corrected amount ("it was 150 not
        180") becomes a "Change ..." line for the saved entry, found by its fact id.
        For draft_v2 senders this replaces the old lookup (``find_correction_target``),
        which needed a quantity and only knew the last one logged."""
        from runtime import day_facts as df

        value, unit = args.get("new_quantity"), args.get("unit")
        gateway = self.gateway
        saved = await gateway.saved_card()
        card_items = list(saved.items) if saved is not None else []
        facts = df.merged(df.work_facts(card_items), await gateway.saved_work_today())
        if df.is_percent(value, unit, self.user_text):
            resolved = df.resolve_percent(facts, value, self.user_text)
            changes: dict[str, Any] = {"progress_percent": value}
        else:
            resolved = df.resolve_quantity(facts, value, unit, self.user_text)
            changes = {}
        if resolved.action == df.NEW_LINE:
            return StepResult(NOT_A_CORRECTION, text="A new percentage for the work is progress, not a correction.")
        if resolved.action == df.NOTHING or resolved.fact is None:
            return StepResult("error", text=f"Nothing was changed: {resolved.reason}.")
        target = df.card_item_for(resolved.fact, card_items)
        if not changes:
            fact = resolved.fact
            changes = {
                "quantities": [{"work_type": fact.work_type, "quantity": value, "unit": unit or fact.unit}],
                # The old note carried the old figure ("plastering 50 sq ft").
                "narrative": ", ".join(p for p in (fact.work_type, fact.location) if p),
            }
        return await gateway.change_saved_item(target, changes)

    async def _update_draft(self, args: dict[str, Any]) -> StepResult:
        """Request 127 (P2): a correction under draft cards. On the open card the
        line is edited in place; on a card they already saved it becomes a
        'Change ...' line on a new card, saved by tap. The reply is built from
        what this returns: a change is claimed only when it was made."""
        gateway = self.gateway
        changes = args.get("changes")
        if not isinstance(changes, dict) or not [v for v in changes.values() if v is not None]:
            return StepResult("error", text="No change was given, so nothing was changed.")
        from .actions import ACTION_FACT
        from .draft import DRAFT_TOOLS

        draft = await gateway.open_draft()
        draft = draft if draft is not None and draft.live else None
        saved = await gateway.saved_card()
        wanted = str(args.get("card_id") or "").strip().lower()
        # Which card they mean: the saved one when its id was passed (or there is no
        # open card), else the open one.
        on_saved = saved is not None and (draft is None or wanted == saved.id)
        if draft is None and saved is None:
            # WA-82 (live 27 Oct, #4335): "tiling 70% aayi" after the card was cancelled
            # was taken as a correction of nothing and dead-ended. Nothing to correct means
            # it is new information.
            return StepResult(NOT_A_CORRECTION, text="There is no card line to change.")
        lines = saved.items if on_saved else draft.items
        try:
            index = int(args.get("item_index"))
        except (TypeError, ValueError):
            index = 1 if len(lines) == 1 else 0
        if not 1 <= index <= len(lines):
            return StepResult(NOT_A_CORRECTION, text="That item is not on the card.")
        target = lines[index - 1]
        refused = target.tool not in DRAFT_TOOLS or (
            target.fact_type == ACTION_FACT if on_saved else (target.pending_answer or not target.ready)
        )
        if refused:
            return StepResult("error", text="That line cannot be changed this way, so nothing was changed.")
        unknown = sorted(set(changes) - _tool_fields(target.tool))
        if unknown:
            return StepResult(
                "error", text=f"{', '.join(unknown)} cannot be changed on this kind of entry, so nothing was changed."
            )
        if on_saved:
            from runtime import day_facts as df

            if set(changes) == {"progress_percent"} and df.work_fact_of(target) is not None and not df.is_correction(
                self.user_text
            ):
                # Request 137: a newer percentage for saved work is progress, a new line.
                return StepResult(NOT_A_CORRECTION, text="A new percentage for the work is progress, not a correction.")
            return await gateway.change_saved_item(target, changes)
        return await gateway.edit_draft_item(draft, target, changes)

    def _carry_after_flush(self) -> None:
        self.saved.extend(self._carry_after)
        self._carry_after = []

    def _outcome(self, name: str, step: StepResult) -> ToolOutcome:
        if step.status == "info" and step.line_key:
            # Request 143: a line of the code's, worded in the turn's language.
            self.module_off_line = say(step.line_key, self.language, **step.line_values)
        elif step.status == "info" and is_module_disabled_reply(step.text or ""):
            self.module_off_line = (step.text or "").split("\n\n", 1)[0]
        if step.status == NOT_A_CORRECTION:
            return ToolOutcome(
                content={
                    "status": NOT_A_CORRECTION,
                    "reason": step.text,
                    "instruction": (
                        "Nothing was changed because there is nothing of theirs to correct: this is NEW "
                        "information. Call the save tool for it now (save_work_done, save_labour, "
                        "save_material_receipt, save_material_usage or report_issue) with the full details "
                        "from their message. Do not tell them there is no card."
                    ),
                }
            )
        if step.status == "saved" and step.workflow_key in ACTION_KINDS:
            self._action_summaries.extend(step.summaries or ([step.summary] if step.summary else []))
        if step.status == "info" and name == NOTE_FOR_ENGINEER and step.text not in self.system_lines:
            # Nobody to send it to: said plainly, whatever the model wrote.
            self.system_lines.append(step.text)
        if step.status == "saved" and name == NOTE_FOR_ENGINEER:
            # Request 104: a card, not a message sent: the Send tap messages the
            # engineer. Nothing has gone yet, and the reply must not say it did.
            self.saved.append(SavedItem(name, step.text, step.summary))
            self._carry_after_flush()
            return ToolOutcome(
                content={
                    "status": "saved",
                    "saved_as": step.summary,
                    "instruction": (
                        "Nothing is sent yet: a Send card is shown. Say in one short line what you "
                        "will send to their engineer and ask them to check it and tap Send. Never "
                        "say it was sent or passed on."
                    ),
                }
            )
        if step.status == "drafted":
            # Request 124: the call became a line of the card, or a question on it.
            # Nothing is written until the Save tap, and the reply must not say it was.
            line = step.summary or ""
            self.saved.append(SavedItem(name, line, line))
            self._carry_after_flush()
            if step.text and step.text != "already on the card" and step.text not in self.system_lines:
                # Request 127: an old-style Yes / No question still waits: said under the reply.
                self.system_lines.append(step.text)
            if step.awaiting == "answer":
                content = {
                    "status": "waiting_for_answer",
                    "on_card": line,
                    "instruction": (
                        "Nothing is saved. A question about this is on the card, with buttons: do not "
                        "write the question yourself. Say in one short line what you understood and ask "
                        "them to answer it on the card, then tap Save. Never say it is saved, written or noted."
                    ),
                }
                if step.hint:
                    # How a typed answer is taken (the entry's own words).
                    content["if_they_type_the_answer"] = step.hint
                return ToolOutcome(content=content)
            instruction = (
                "Nothing is saved yet: it is a line on a Save / Cancel card shown under your words. "
                "Say in one short line what you understood, in the language of their message, and "
                "ask them to check it and tap Save. Never say it is saved, written or noted. Do "
                "not copy the card."
            )
            if step.changed:
                # Request 129: "labour maatti: mason 6 ninnu 5 aakki" said it was done.
                instruction += (
                    " This is a CHANGE that waits for their Save tap, not a change made: say it as pending "
                    "('maattanam: mason 6 → 5. Save tap cheyyu', 'will change mason 6 → 5 once you save'), "
                    "never in the past tense (not 'changed', 'maatti', 'aakki', 'updated', 'corrected')."
                )
            return ToolOutcome(
                content={"status": "waiting_for_save", "on_card": line, "instruction": instruction}
            )
        if step.status == "undone":
            self.system_lines.append(step.text)
            return ToolOutcome(
                content={
                    "status": "undone",
                    "instruction": (
                        "Say in one short line that it is removed. The system puts the exact "
                        "'Removed: ...' line under your words: do not list what was removed."
                    ),
                }
            )
        if step.status == "saved":
            if step.summaries:
                self.saved.extend(SavedItem(name, line, line) for line in step.summaries)
            else:
                self.saved.append(SavedItem(name, step.text, step.summary))
            self._carry_after_flush()
            content: dict[str, Any] = {"status": "saved"}
            if step.summaries:
                content["saved_as"] = "; ".join(step.summaries)
            elif step.summary:
                content["saved_as"] = step.summary
            # B-9: not the pipeline's "✅ Recorded. Thank you." -- the model
            # copied it onto every line ("Recorded 12 masons present today.")
            # or sent it alone, without saying what was saved.
            note = _without_recorded(step.text)
            if note:
                content["note"] = note
            return ToolOutcome(content=content)
        if step.status in ("needs_confirmation", "needs_answer"):
            question = step.reply or ReplySpec(text=step.text)
            if self.parked is None or self.parked_by == "ask":
                # The pipeline's own question replaces the model's: its answer
                # is what the stored waiting state expects.
                self.parked = question
                self.parked_by = "gate"
                self.parked_confirm = step.status == "needs_confirmation"
            if any(row.title == SAVE_TITLE for row in question.buttons or ()):
                # Request 114: a Save / Cancel card, not a question. Nothing is kept yet.
                return ToolOutcome(
                    content={
                        "status": "waiting_for_save",
                        "to_save": question.text,
                        "instruction": (
                            "Nothing is saved yet: a Save / Cancel card is shown under your words. Say in "
                            "one short line what you understood, in the language of their message, and "
                            "ask them to check it and tap Save. Never say it is saved, written or noted. "
                            "Do not copy the card."
                        ),
                    }
                )
            return ToolOutcome(
                content={
                    "status": "waiting_for_user",
                    "question": question.text,
                    "instruction": "Your final message must end with this question.",
                }
            )
        if step.status == "choose" and step.awaiting == "confirm_undo" and step.reply is not None:
            # Request 142 (B): a removal is asked first. Nothing is removed before the Yes tap.
            if self.parked is None:
                # parked_confirm: the lines go under the model's words, whatever it wrote.
                self.parked, self.parked_by, self.parked_confirm = step.reply, "ask", True
            return ToolOutcome(
                content={
                    "status": "waiting_for_confirmation",
                    "instruction": (
                        "Nothing is removed yet: a confirm card with Yes / Keep buttons is shown under your "
                        "words, listing what would go. Say in one short line that you will remove it if they "
                        "confirm, in the language of their message. Never say it is removed. Do not list it."
                    ),
                }
            )
        if step.status == "choose" and step.reply is not None:
            # ARCH-04: the sender must pick (material, project, site, add it?).
            # The options go out as buttons whatever the model writes; its
            # own ask_user, if it also calls one, is the one question.
            if step.awaiting == "site" and self.parked_by != "gate":
                # [111]: the code's own site question, with only real sites; it
                # replaces any site question the model wrote.
                self.parked = step.reply
                self.parked_by = "ask"
                self.parked_site = True
            elif self.parked is None:
                self.parked = step.reply
                self.parked_by = "ask"
            return ToolOutcome(
                content={
                    "status": "choose",
                    "message": step.text,
                    "instruction": (
                        "Nothing was saved. End your message with this question; its options are "
                        f"shown as buttons: {step.reply.text}"
                    ),
                }
            )
        if step.status == "answer" and name == REQUEST_DPR:
            self.report_text = step.text
            self.report_documents = step.documents
            self.answers.append(step.text)
            return ToolOutcome(
                content={
                    "status": "answer",
                    "text": step.text,
                    "instruction": (
                        "The system has already sent the report (a PDF when the day has entries) and puts "
                        "this line under your words itself. Do not describe the report, list anything from "
                        "it or repeat this line. If the message asked for nothing else, write nothing."
                    ),
                }
            )
        if step.status == "answer":
            self.answers.append(step.text)
            if name == QUERY_MATERIALS:
                self._stock_answer = step.text
            return ToolOutcome(content={"status": "answer", "text": step.text})
        if step.status == "error":
            self.failed += 1
        if step.text and step.text not in self.notes:
            self.notes.append(step.text)
        return ToolOutcome(content={"status": step.status, "message": step.text})
