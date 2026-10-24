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
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from channel.replies import ListRow, ReplySpec
from mesiri_ai.models import ToolOutcome
from runtime.save_first import DRAFT_NOTE

from .cards import CardItem, merge_changes
from .equipment import EQUIPMENT_LINE, is_equipment_only
from .gateway import StepResult, WorkflowGateway
from .later import LaterItem, held_item
from .tools import (
    ASK_USER,
    NOTE_FOR_ENGINEER,
    QUERY_MATERIALS,
    REPORT_ISSUE,
    REQUEST_DPR,
    SAVE_LABOUR,
    SAVE_WORK_DONE,
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

_log = logging.getLogger("mesiri.agent")

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


def _tool_fields(tool: str) -> set[str]:
    """The argument names a save tool takes: what a card change may touch."""
    for spec in tool_specs():
        if spec.name == tool:
            return set((spec.parameters or {}).get("properties", {}))
    return set()


def _title(option: str) -> str:
    option = " ".join(str(option).split())
    return option if len(option) <= _TITLE_MAX else option[: _TITLE_MAX - 1] + "…"


def question_reply(question: str, options: list[str]) -> ReplySpec:
    """The one question as a message: buttons for up to three options, a list
    for up to ten, plain text otherwise."""
    options = [o for o in (str(o).strip() for o in options) if o][:MAX_LIST_ROWS]
    rows = tuple(ListRow(f"agent_opt_{i}", _title(o)) for i, o in enumerate(options, 1))
    if 0 < len(rows) <= MAX_BUTTONS:
        return ReplySpec(text=question, buttons=rows)
    if rows:
        return ReplySpec(text=question, list_button_label="Choose one", list_rows=rows)
    return ReplySpec(text=question)


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
    #: Request 83: what request_dpr answered, for the one "draft so far" line a
    #: message that also saves entries gets under its card.
    report_text: str | None = None
    #: Request 104: the message is only about equipment, which WhatsApp does not
    #: record yet; its reply is the one plain line, never a Save.
    equipment_noted: bool = False
    #: The last reply offered to ask their engineer, so a bare "yes" asks it.
    engineer_offered: bool = False
    #: Request 88: lines the system adds under the model's words, from the
    #: data ("Removed: 2 painters (today)").
    system_lines: list[str] = field(default_factory=list)
    #: Request 88: items of the open card that follow the one being changed.
    _carry_after: list[SavedItem] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)
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
        self.calls += 1
        if self.calls > MAX_CALLS:
            return ToolOutcome(
                content={"status": "skipped", "reason": "too many actions in one message"}
            )
        if name == ASK_USER:
            return self._ask(args)
        if name == SET_WORK_SITE:
            return await self._set_work_site(args)
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
        signature = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        if signature in self._seen and name in WRITE_TOOLS:
            return ToolOutcome(
                content={"status": "duplicate_ignored", "reason": "already done in this message"}
            )
        self._seen.add(signature)
        if name in WRITE_TOOLS:
            self.attempted_writes += 1
        try:
            step = await self._run(name, args)
        except Exception:  # noqa: BLE001 — the model is told; the trace keeps the cause
            _log.exception("agent.tool_failed tool=%s", name)
            self.failed += 1
            return ToolOutcome(content={"status": "error", "message": "that action failed"})
        return self._outcome(name, step)

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
        self.parked = question_reply(question, options if isinstance(options, list) else [])
        self.parked_by = "ask"
        # WA-58: what the question leaves aside is taken up next.
        self._note_later(args.get("other_parts"))
        return ToolOutcome(
            content={
                "status": "question_sent",
                "instruction": "Your final message must end with this question.",
            }
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
        if name == UNDO_LAST and str(args.get("what") or "latest_update") == "latest_update":
            return await self._undo(args)
        if name == UPDATE_PENDING_CARD:
            return await self._update_card(args)
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
        undo_card = getattr(self.gateway, "undo_card", None)
        if undo_card is None:
            return StepResult("info", text="Nothing to undo from your last card.")
        targets = args.get("targets")
        refs = [str(t) for t in targets] if isinstance(targets, list) else []
        return await undo_card(refs)

    async def _update_card(self, args: dict[str, Any]) -> StepResult:
        """Request 88: change one item of the open card. The old draft is
        withdrawn and the new one saved through the item's own save tool, so
        every check of that tool runs again; the card is then shown again."""
        gateway = self.gateway
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

    def _carry_after_flush(self) -> None:
        self.saved.extend(self._carry_after)
        self._carry_after = []

    def _outcome(self, name: str, step: StepResult) -> ToolOutcome:
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
            return ToolOutcome(
                content={
                    "status": "waiting_for_user",
                    "question": question.text,
                    "instruction": "Your final message must end with this question.",
                }
            )
        if step.status == "choose" and step.reply is not None:
            # ARCH-04: the sender must pick (material, project, site, add it?).
            # The options go out as buttons whatever the model writes; its
            # own ask_user, if it also calls one, is the one question.
            if self.parked is None:
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
            self.answers.append(step.text)
            return ToolOutcome(
                content={
                    "status": "answer",
                    "text": step.text,
                    "instruction": (
                        "If this same message also saves entries, the system adds one 'Today's draft so "
                        "far' line under them: do not describe this report, do not list any items, and "
                        "do not ask for details that are already in the entries."
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
