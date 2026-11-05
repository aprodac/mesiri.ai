"""WA-119: one model, one SOP, the dashboard's API as its tools.

A turn: the model reads the message with the SOP and the tools, looks things up
(``GET`` routes run at once), and prepares entries (any other route is held, not
sent). The turn returns the model's own reply and the held entries; the caller
shows them and calls ``confirm`` when the person says yes. That is the only
place a write reaches the API, with an ``Idempotency-Key`` so a repeated
confirmation cannot record twice.

No classifier, no workflow, no word list, no reply rewriting.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from agent_api.feedback import TELL_THE_TEAM, feedback_instruction
from agent_api.feedback import specs as feedback_specs
from agent_api.links import WEB_LINK, build_link
from agent_api.links import spec as web_link_spec
from mesiri.domains.materials.names import alias_key
from mesiri_ai.models import ChatMessage, ToolOutcome, ToolSpec
from runtime.agent.reply_text import asks_to_tap_save
from runtime.ai_outage import is_budget_error

from .client import ApiClient, new_idempotency_key
from .fill import (
    NARRATIVE_REFUSAL,
    fill_body,
    missing_in_body,
    not_english,
    to_english,
    translate_body,
)
from .materials import (
    ADD_TOOL,
    CATEGORY_NOTE,
    NEW,
    already_listed,
    catalogue,
    known_vendor,
    material_name,
    pending_ref,
    settle_category,
    settle_material,
    without_category_note,
)
from .reply_guard import (
    claims_cannot,
    claims_saved,
    read_tools_for,
    unbacked_figures,
    without_ids,
    without_internals,
    without_saved_claims,
)
from .tools import CONFIRM_ARG, MATERIAL_SAID, ApiTool, what_mesiri_does
from .units import (
    is_stock_unit_refusal,
    is_uuid,
    plain_refusal,
    resolve_unit,
    unit_choices,
    unit_rows,
)

SOP = (Path(__file__).with_name("SOP.md")).read_text(encoding="utf-8")

MAX_STEPS = 8
TIMEOUT_SECONDS = 40.0
#: A read's JSON is cut to this many characters before the model sees it.
READ_LIMIT = 8000


@dataclass(frozen=True)
class PendingWrite:
    """An entry the model prepared; reaches the API only through ``confirm``."""

    tool: str
    method: str
    path: str
    params: dict[str, Any]
    body: dict[str, Any]
    summary: str
    idempotency_key: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PendingWrite:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class WriteResult:
    pending: PendingWrite
    status: int
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass
class ApiTurn:
    reply: str
    #: Entries waiting for the person's confirmation after this turn: the ones
    #: still waiting from before (not saved or dropped) followed by the new ones.
    pending: list[PendingWrite] = field(default_factory=list)
    #: Entries saved during this turn because the person said to (``save_ready_entries``).
    saved: list[WriteResult] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "answered"
    #: A question the model asked with ``ask``: its options become buttons (one tap).
    question: str = ""
    options: list[str] = field(default_factory=list)
    #: WA-154: fingerprints of creates the person was just asked about ("already saved at 22:44, another?").
    repeat_asked: list[str] = field(default_factory=list)
    #: [219]: the open question this message did not answer (dropped; the model was told it is a new request).
    dropped_question: str = ""
    #: WA-166: sizes this person told ("1 load M-sand = 60 bags") who may not set one for the company: kept for them,
    #: so the code converts their lines and never asks again ({"<material_id>:<unit_id>": size}).
    sizes_said: dict[str, float] = field(default_factory=dict)
    #: WA-168: lines that need a size nobody gave yet ({material_id, from_unit_id, path, body, summary, key}); a
    #: "Don't know" next holds them for the admin (``POST /materials/size-requests``).
    size_needed: list[dict[str, Any]] = field(default_factory=list)
    #: [229]: the model said something was ready (or to tap Save) but nothing is held, even after one more try.
    nothing_held: bool = False
    #: [248]: lines (their card words) refused for their material and still not held after one more try: the reply
    #: says plainly they are not on the card, never "ready".
    not_held: list[str] = field(default_factory=list)
    #: WA-193: what the code took out of the model's words ("saved", "internals"), kept in the trace.
    reply_fixed: list[str] = field(default_factory=list)
    #: [243]: the reply language set this turn by the code ("auto" = cleared), "" when none was set.
    language_set: str = ""


#: WA-154 (3 Nov, Paraclette: "Rana Mart" re-sent three times made three empty projects): a create the same person
#: already saved, the same within this many hours, is asked about once before it is prepared again.
REPEAT_WINDOW_S = 24 * 3600
#: Body fields that say how or when it was sent, not what it is.
_NOT_WHAT = frozenset({"channel", "source", "photo_object_key", "receipt_photo_key", "notes", "client_ref"})


def create_fingerprint(tool: str, method: str, path: str, body: dict[str, Any]) -> str | None:
    """What a create IS (tool, route, its fields; text case- and space-insensitive), or None for anything that isn't a
    create. Two prepares with the same fingerprint make the same record twice."""
    if method != "POST":
        return None

    def norm(v: Any) -> Any:
        if isinstance(v, str):
            return " ".join(v.casefold().split())
        if isinstance(v, dict):
            return {k: norm(x) for k, x in sorted(v.items()) if k not in _NOT_WHAT}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v

    return json.dumps([tool, path, norm(body)], sort_keys=True, default=str, ensure_ascii=False)


def remember_saves(recent: list[dict[str, Any]] | None, results: list[WriteResult], now: float) -> list[dict[str, Any]]:
    """The person's saved creates of the last REPEAT_WINDOW_S, newest last (kept in the conversation state)."""
    kept = [r for r in (recent or []) if now - float(r.get("at") or 0) < REPEAT_WINDOW_S]
    for r in results:
        fp = create_fingerprint(r.pending.tool, r.pending.method, r.pending.path, r.pending.body) if r.ok else None
        if fp:
            kept.append({"fp": fp, "summary": r.pending.summary, "at": now})
    return kept[-30:]


@dataclass(frozen=True)
class Place:
    """A site (or a project with no site) an entry is reported to."""

    site_id: str | None
    project_id: str | None
    name: str


@dataclass(frozen=True)
class Places:
    """[213] (re-opens [209], 3 Nov: "Puthiya project undaakku, peru Zeta Plaza", then "20 bag cement vannu" went to the
    new, empty Zeta Plaza): the person's projects and sites, and the site they last reported to, so the CODE decides
    where an update goes. ``projects``: (id, name); ``sites``: (id, name, project_id)."""

    projects: tuple[tuple[str, str], ...]
    sites: tuple[tuple[str, str, str], ...]
    working: Place | None = None
    #: [215]: site / project ids they reported to, newest first (the order the site buttons come in).
    recent: tuple[str, ...] = ()

    def place(self, site_id: Any, project_id: Any) -> Place | None:
        for sid, name, pid in self.sites:
            if site_id and sid == str(site_id):
                return Place(sid, pid, name)
        for pid, name in self.projects:
            if project_id and pid == str(project_id):
                return Place(None, pid, name)
        return None


def site_scoped(tool: ApiTool) -> bool:
    """A write that reports something at a site (a receipt, labour, work, an issue, an expense, conditions); not one
    that creates or changes a project or site itself."""
    return tool.is_write and ("site_id" in tool.body_fields or tool.path_params == ("site_id",))


def _named(name: str, said: str) -> bool:
    whole = " ".join(name.casefold().split())
    return any(len(n) >= 3 and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", said)
               for n in {whole, whole.split(",")[0].strip()})


def decide_site(text: str, places: Places, site_id: Any, project_id: Any, working: Place | None) -> Place | list[str]:
    """Where an update goes, decided by the code: the site or project named in this message, else the one they last
    reported to (``working``), else their only site; else the names to ask about (buttons). Creating or naming a
    project in an earlier message never makes it the reporting site."""
    said = " ".join(text.casefold().split())
    chosen = places.place(site_id, project_id)
    sites = [Place(sid, pid, name) for sid, name, pid in places.sites]
    named_sites = [s for s in sites if _named(s.name, said)]
    named_projects = [Place(None, pid, name) for pid, name in places.projects if _named(name, said)]
    if named_sites or named_projects:
        if chosen and chosen.site_id and chosen.site_id in {s.site_id for s in named_sites}:
            return chosen
        if len(named_sites) == 1:
            return named_sites[0]
        if len(named_projects) == 1 and not named_sites:
            project = named_projects[0]
            inside = [s for s in sites if s.project_id == project.project_id]
            if chosen and chosen.site_id and chosen.project_id == project.project_id:
                return chosen
            if len(inside) <= 1:
                return inside[0] if inside else project
            return [s.name for s in inside]
        return [s.name for s in named_sites] or [p.name for p in named_projects]
    if working is not None:
        return working
    # [215]: a project with no site yet is a place too; the ones they reported to recently come first.
    with_site = {s.project_id for s in sites}
    every = sites + [Place(None, pid, name) for pid, name in places.projects if pid not in with_site]
    if len(every) == 1:
        return every[0]
    rank = {pid: i for i, pid in enumerate(places.recent)}
    every.sort(key=lambda p: rank.get(p.site_id or p.project_id or "", len(rank)))
    return [p.name for p in every]


#: [219]: a reply this short answers the open question ("the second one", "yes", "randaamathe").
SHORT_ANSWER_WORDS = 4


def answers_question(text: str, question: dict[str, Any] | None) -> bool:
    """[219]: whether this message answers the question Mesiri asked last ({question, options}), decided by the code: a
    tap (it comes as the option's title), a reply naming one of its options, or a short reply. Anything else is a new
    request, and the open question is dropped ("Add Mohanlal to Live Mart B…" is not "which Rana Mart?")."""
    if not question or not (question.get("question") or question.get("options")):
        return True
    said = " ".join(text.casefold().split())
    if any(_named(str(o), said) or said == " ".join(str(o).casefold().split()) for o in question.get("options") or []):
        return True
    return len(said.split()) <= SHORT_ANSWER_WORDS


def question_left_open(question: str, options: list[str], reply: str) -> dict[str, Any] | None:
    """The question this turn leaves open: one asked with ``ask`` (or buttons the code built), else a reply that ends
    with a question (a plain-text "another one?")."""
    if question or options:
        return {"question": question or reply, "options": list(options)}
    last = (reply or "").strip().splitlines()[-1:] or [""]
    return {"question": last[0], "options": []} if last[0].rstrip("* _").endswith("?") else None


def same_name(name: Any, places: Places | None) -> list[str]:
    """[219]: the person's projects already called ``name`` (case and spacing aside)."""
    key = " ".join(str(name or "").casefold().split())
    return [n for _, n in (places.projects if places else ()) if key and " ".join(n.casefold().split()) == key]


#: [215]: at most this many sites as buttons, then "Other" (they say the site in words).
SITE_BUTTONS = 3
OTHER_SITE = "Other"


def site_options(names: list[str]) -> list[str]:
    return names if len(names) <= SITE_BUTTONS else [*names[:SITE_BUTTONS], OTHER_SITE]


def working_place(places: Places | None, entries: list[PendingWrite]) -> Place | None:
    """The site they are reporting to now: the last one in the ready list, else the last one they saved to."""
    if places is None:
        return None
    for e in reversed(entries):
        found = places.place(e.body.get("site_id") or _path_site(e.path), e.body.get("project_id"))
        if found is not None:
            return found
    return places.working


def last_reported(results: list[WriteResult], old: dict[str, Any] | None, day: str | None = None) -> dict[str, Any] | None:
    """The site of the last saved report ({site_id, project_id, date, recent}), kept in the conversation state.
    Creating a project, adding a site or a member (routes under /projects) never changes it ([215])."""
    for r in reversed(results):
        if not r.ok or (r.pending.path or "").startswith("/projects"):
            continue
        site, project = r.pending.body.get("site_id") or _path_site(r.pending.path), r.pending.body.get("project_id")
        if site or project:
            key = str(site or project)
            recent = [key, *(k for k in (old or {}).get("recent") or [] if k != key)][:10]
            return {"site_id": str(site) if site else None, "project_id": str(project) if project else None,
                    "date": day, "recent": recent}
    return old


def _path_site(path: str) -> str | None:
    m = re.match(r"^/dpr/site-days/([^/]+)/", path or "")
    return m.group(1) if m else None


SAVE_READY = "save_ready_entries"
#: The language of the person's message (``runtime.agent.wording.language_of``) as told to the model.
#: [243]: set at once by the code, never held on the card.
LANGUAGE_TOOL = "set_reply_language"
LANGUAGE_LINES = {
    "english": "English",
    "manglish": "Manglish (Malayalam words in Latin letters; never Malayalam script)",
    "malayalam": "Malayalam script",
    "hinglish": "Hinglish (Hindi words in Latin letters; never Devanagari)",
    "hindi": "Hindi in Devanagari script",
}
ASK = "ask"
#: Body field the code fills with the photo of this message (a bill), never the model.
PHOTO_FIELD = "media_object_key"
#: WA-135: the channel value the tools fix (``recorded_via`` / ``source``) is replaced by the one
#: the message really came by, so a sheet photo or a voice note is not recorded as typed text.
TEXT_CHANNEL = "whatsapp_text"
CHANNELS = frozenset({TEXT_CHANNEL, "whatsapp_voice", "whatsapp_image"})
#: PRC-02: the tool that changes a material in the list (its category in words, among others).
UPDATE_MATERIAL_TOOL = "update_material"
_ASK_TOOL = ToolSpec(name=ASK, description=(
    "Ask the person ONE short question you cannot work out yourself. With options (2-3 short "
    "choices) they answer with one tap. Put the question in your reply too."), parameters={
    "type": "object", "required": ["question"],
    "properties": {"question": {"type": "string"},
                   "options": {"type": "array", "items": {"type": "string"}, "description": "2-3 short choices"}},
})
DROP_READY = "drop_ready_entries"
#: 2 Nov ([205], Paraclette: a project renamed by voice vanished from the list): a correction to a waiting entry
#: is ONE step the code applies in place. Drop-then-prepare let the model stop halfway and still say "ready".
CHANGE_READY = "change_ready_entry"
_CHANGE = {
    "type": "object", "required": ["number", "changes", "confirm_line"],
    "properties": {
        "number": {"type": "integer", "description": "The entry number from the ready list."},
        "changes": {"type": "array", "description": "Only the fields that change (field names as in the entry).",
                    "items": {"type": "object", "required": ["field", "value"],
                              "properties": {"field": {"type": "string"}, "value": {"type": "string"}}}},
        "confirm_line": {"type": "string", "description": "The entry's new one-line summary in their words."},
    },
}
_NUMBERS = {
    "type": "object",
    "properties": {"numbers": {"type": "array", "items": {"type": "integer"},
                               "description": "The entry numbers from the ready list; leave out for all."}},
}
_READY_TOOLS = (
    ToolSpec(name=SAVE_READY, parameters=_NUMBERS, description=(
        "Save entries from the ready list. Only when the person clearly says to save or confirm them.")),
    ToolSpec(name=DROP_READY, parameters=_NUMBERS, description=(
        "Remove entries from the ready list: only when the person cancels them. To correct one, use change_ready_entry.")),
    ToolSpec(name=CHANGE_READY, parameters=_CHANGE, description=(
        "Correct ONE entry in the ready list in place (a new name, quantity, site, unit, date ...): it stays in the "
        "list with the changes. Use this for every correction of a waiting entry; never drop it to correct it.")),
)


class ApiAgent:
    def __init__(self, provider: Any, tools: dict[str, ApiTool], *, sop: str = SOP,
                 max_steps: int = MAX_STEPS, timeout_seconds: float = TIMEOUT_SECONDS,
                 capability: str | None = None) -> None:
        self._provider = provider
        self._tools = tools
        self._sop = sop
        self._max_steps = max_steps
        self._timeout = timeout_seconds
        #: The control-panel route the provider resolves the model by ("api_agent").
        self._capability = capability

    def system_prompt(self, *, sender_name: str, today: dt.date, ready: list[PendingWrite] | None = None,
                      facts: str = "") -> str:
        who = f"You are talking to {sender_name}. " if sender_name else ""
        prompt = f"{self._sop}\n\n{what_mesiri_does(self._tools)}\n{who}Today is {today.isoformat()} ({today.strftime('%A')})."
        if facts:
            prompt += f"\n\n{facts}"
        if ready:
            listed = "\n".join(f"{i}. {e.summary}  ({e.tool}: {json.dumps(e.body, ensure_ascii=False, default=str)[:400]})"
                               for i, e in enumerate(ready, 1))
            prompt += f"\n\nReady, waiting for the person's confirmation (not saved):\n{listed}"
        return prompt

    async def run(self, client: ApiClient, text: str, *, history: list[ChatMessage] | None = None,
                  ready: list[PendingWrite] | None = None, sender_name: str = "",
                  timezone: str = "Asia/Kolkata", correlation_id: str | None = None,
                  facts: str = "", photo_key: str | None = None, language: str | None = None,
                  actions: dict[str, tuple[ToolSpec, Any]] | None = None,
                  channel: str = TEXT_CHANNEL, recent_saves: list[dict[str, Any]] | None = None,
                  repeat_ok: list[str] | None = None, places: Places | None = None,
                  open_question: dict[str, Any] | None = None, sizes: dict[str, Any] | None = None,
                  may_set_sizes: bool = True, language_chosen: bool = False) -> ApiTurn:
        """``facts``: what the agent starts from (projects, sites, materials, units), read
        before the model runs. ``photo_key``: the photo this message carried; a write that
        takes a photo (an expense) gets it attached by the code. ``actions``: tools the caller
        runs itself, by name: ``(spec, async handler(arguments) -> content)``. ``channel``: how the
        message came (``whatsapp_text`` | ``whatsapp_voice`` | ``whatsapp_image``), recorded on the entry.
        ``places``: the person's projects and sites; with it, the code decides the site of every report ([213]).
        ``open_question``: the question Mesiri asked last ({question, options}); a message that does not answer it
        drops it ([219]). ``sizes``: the sizes this person told before (WA-166); ``may_set_sizes``: whether they may
        set a size for the whole company (an admin or a project manager); if not, their size converts their own lines."""
        channel = channel if channel in CHANNELS else TEXT_CHANNEL
        today = dt.datetime.now(ZoneInfo(timezone or "Asia/Kolkata")).date()
        waiting: list[PendingWrite | None] = list(ready or [])  # None = saved or dropped this turn
        new: list[PendingWrite] = []
        saved: list[WriteResult] = []
        asked: dict[str, Any] = {}
        acted: list[str] = []
        unit_ask: list[str] = []  # buttons for a unit (or a person, [207]) nobody could settle; cleared once settled
        links: list[str] = []  # WA-141: dashboard links built this turn
        changed: list[int] = []  # [205]: waiting entries corrected in place this turn
        repeat_asked: list[str] = []  # WA-154: creates asked about this turn
        code_told: list[dict[str, Any]] = []  # WA-155: passed to the team by the code
        site_ask: list[str] = []  # [213]: site names to ask about when the code cannot tell the site
        exists: list[str] = []  # [219]: what the code says about a project that already exists
        sizes_said: dict[str, float] = {}  # WA-166: sizes told this turn by someone who may not set the company's
        size_needed: list[dict[str, Any]] = []  # WA-168: lines waiting for a size nobody gave yet
        dropped = "" if answers_question(text, open_question) else str(
            (open_question or {}).get("question") or " / ".join((open_question or {}).get("options") or []))
        decides_site = places is not None and (len(places.sites) > 1 or len(places.projects) > 1)
        tz = ZoneInfo(timezone or "Asia/Kolkata")
        their_words = " ".join([*(m.text or "" for m in history or [] if m.role == "user"), text])
        tries: dict[str, int] = {}  # [243]: a body Mesiri could not translate is sent back to the model once per tool

        async def english(word: str) -> str:
            """[248]: Mesiri's own English for a word the person said ("സിമൻ്റ്" -> "Cement"), or ""."""
            return (await to_english(self._provider, [word], correlation_id, latin=True)).get(word, "")
        reply_in = LANGUAGE_LINES.get(language or "", "their language")
        language_set: list[str] = []

        def chosen(arguments: dict) -> list[int]:
            numbers = arguments.get("numbers") or range(1, len(waiting) + 1)
            return [n for n in (int(x) for x in numbers) if 1 <= n <= len(waiting) and waiting[n - 1] is not None]

        async def resized(material_id: str, unit_id: str) -> int:
            """WA-197: a size was just given: each line held with that size unknown (" (1 Loads = how many Bags?)") is checked
            again, so it shows (and saves) what it is in stock. Never a second copy of the line. Returns how many."""
            count = 0
            for rows in (waiting, new):
                for i, e in enumerate(rows):
                    if (e is None or str(e.body.get("material_id") or "") != material_id
                            or str(e.body.get("unit_id") or "") != unit_id or not SIZE_UNKNOWN.search(e.summary)):
                        continue
                    body = dict(e.body)
                    problem, note = await settle_stock_unit(
                        client, body, [*waiting, *new], {**(sizes or {}), **sizes_said}, sender_name)
                    if problem:
                        continue
                    rows[i] = replace(e, body=body, summary=SIZE_UNKNOWN.sub("", e.summary) + note)
                    size_needed[:] = [x for x in size_needed if x["key"] != e.idempotency_key]
                    count += 1
            return count

        async def change_entry(arguments: dict) -> dict[str, Any]:
            try:
                n = int(arguments.get("number") or 0)
            except (TypeError, ValueError):
                n = 0
            if not 1 <= n <= len(waiting) or waiting[n - 1] is None:
                return {"error": f"there is no waiting entry {arguments.get('number')}"}
            entry = waiting[n - 1]
            tool = self._tools.get(entry.tool)
            raw = arguments.get("changes") or []
            pairs = raw.items() if isinstance(raw, dict) else ((c.get("field"), c.get("value")) for c in raw if isinstance(c, dict))
            changes = {str(k): _typed(entry.body.get(str(k)), v) for k, v in pairs if k}
            unknown = [k for k in changes if tool is None or k not in tool.body_fields]
            if unknown or not changes:
                return {"error": f"cannot change {', '.join(unknown) or 'nothing'}; fields: {', '.join(tool.body_fields) if tool else '-'}"}
            body = {**entry.body, **changes}
            if "material_id" in changes:  # [210]: a corrected material is checked like a new line
                problem, buttons = await settle_material(client, body, "", text, [])
                if problem:
                    unit_ask[:] = buttons
                    return {"error": problem}
            if "unit_id" in body and ("unit_id" in changes or "unit" in changes):
                problem = await settle_unit(client, body)
                if problem:
                    unit_ask[:] = await unit_buttons(client)
                    return {"error": problem}
            unit_note = ""
            size_note = ""
            category_note = ""
            if entry.tool in (ADD_TOOL, UPDATE_MATERIAL_TOOL) and {"name", "category"} & set(changes):
                # PRC-02: a waiting material renamed or moved gets its category worked out again, never the old one.
                if entry.tool == ADD_TOOL or "category" in changes:
                    body.pop("category_id", None)
                    label, _ = await settle_category(client, body, ask=False)
                    category_note = f"{CATEGORY_NOTE}{label}" if label else ""
            if "unit_id" in body and {"unit_id", "unit", "material_id", "quantity"} & set(changes):
                # WA-165: a corrected unit, material or quantity is checked against the stock unit like a new line.
                problem, unit_note = await settle_stock_unit(
                    client, body, [*waiting, *new], {**(sizes or {}), **sizes_said}, sender_name)
                if problem:  # WA-197: the change goes through; the size is asked beside it
                    size_note = problem
            summary = (str(arguments.get("confirm_line") or "").strip() + unit_note) or entry.summary
            if entry.tool in (ADD_TOOL, UPDATE_MATERIAL_TOOL) and {"name", "category"} & set(changes):
                summary = without_category_note(summary) + category_note
            key = new_idempotency_key()
            waiting[n - 1] = PendingWrite(tool=entry.tool, method=entry.method, path=entry.path, params=entry.params,
                                          body=body, summary=summary, idempotency_key=key)
            if size_note:
                size_needed[:] = [x for x in size_needed if x["key"] != entry.idempotency_key]
                size_needed.append({"material_id": body["material_id"], "from_unit_id": body["unit_id"],
                                    "path": entry.path, "body": dict(body), "key": key, "summary": summary})
            changed.append(n)
            before, after = str(entry.body.get("material_id") or ""), str(body.get("material_id") or "")
            moved = moved_off_new(waiting, before, after, self._tools.get(ALIAS_TOOL),
                                  await material_name(client, after) if before.startswith(NEW) and is_uuid(after) else "")
            return {"status": "changed in the ready list, NOT saved", "entry": n, "now": summary, **moved,
                    **({"size": size_note.strip()} if size_note else {})}

        async def handler(name: str, arguments: dict) -> ToolOutcome:
            if name == TELL_THE_TEAM:
                # TM-18 / WA-126: the same feedback tool as v2. It writes nothing: the call is in the
                # turn's trace, which the team bot's production watch reads, builds, and reports back.
                return ToolOutcome(content={"status": feedback_instruction(arguments)})
            if name == WEB_LINK:
                # WA-141: the dashboard address is built by the code, never written by the model.
                built = build_link(arguments, today=today.isoformat())
                if "url" in built:
                    links.append(built["url"])
                return ToolOutcome(content=built)
            if name == ASK:
                asked["question"] = str(arguments.get("question") or "").strip()
                asked["options"] = [str(o).strip()[:20] for o in (arguments.get("options") or []) if str(o).strip()][:3]
                return ToolOutcome(content={"status": "the options are shown as buttons under your reply"})
            if name == SAVE_READY and waiting:
                numbers = chosen(arguments)
                results = await confirm(client, [waiting[n - 1] for n in numbers], _place_names(places))  # type: ignore[misc]
                saved.extend(results)
                for n in numbers:
                    waiting[n - 1] = None
                return ToolOutcome(content={"results": [
                    {"entry": n, "summary": r.pending.summary, "saved": r.ok and not held(r),
                     **({"held": "for the admin to give the size; saves by itself then"} if held(r) else {}),
                     **({} if r.ok else {"refused": _detail(r.body)})} for n, r in zip(numbers, results, strict=True)]})
            if name == DROP_READY and waiting:
                numbers = chosen(arguments)
                for n in numbers:
                    waiting[n - 1] = None
                return ToolOutcome(content={"dropped": numbers})
            if name == CHANGE_READY and waiting:
                return ToolOutcome(content=await change_entry(arguments))
            if actions and name in actions:
                acted.append(name)
                return ToolOutcome(content=await actions[name][1](arguments))
            tool = self._tools.get(name)
            if tool is None:
                return ToolOutcome(content={"error": f"no tool named {name}"})
            if name == LANGUAGE_TOOL:
                # [243]: a reply-language choice is not a record: the code sets it at once, never a Ready-to-save line.
                response = await client.call(tool.method, tool.path, json={
                    f: arguments[f] for f in tool.body_fields if f in arguments})
                acted.append(name)
                if response.ok:
                    language_set[:] = [str(arguments.get("reply_language") or "")]
                return ToolOutcome(content={"status": (
                    "set now (not on the card, nothing to save); reply in that language from this reply on" if response.ok
                    else f"not set: {_detail(response.body)}")})
            site_note = ""
            unit_note = ""  # WA-166: "(= 60 bags)" -- what a line in another unit is in stock, seen before Save
            size_hint = ""  # WA-166: a held line for a new material that needs its size asked in this turn
            filled_unit = ""  # WA-197: the unit the code filled in (none was said), shown on the line
            line_key = ""  # WA-197: the key of a line held with its size asked (the "Don't know" hold uses it)
            if decides_site and site_scoped(tool):
                # [213]: the code decides where a report goes, never the model (it took the project just created).
                working = working_place(places, [e for e in waiting if e is not None] + new)
                place = decide_site(text, places, arguments.get("site_id"), arguments.get("project_id"), working)  # type: ignore[arg-type]
                if isinstance(place, list) or (place.site_id is None and "site_id" in tool.required):
                    names = place if isinstance(place, list) else [place.name]
                    site_ask[:] = site_options(names)
                    return ToolOutcome(content={"error": (
                        "Which site is this for? Nothing was prepared. Ask the person with `ask`, these as the options: "
                        + ", ".join(site_ask))})
                arguments = {k: v for k, v in arguments.items() if k != "site_id"}
                if place.site_id:
                    arguments["site_id"] = place.site_id
                if "project_id" in tool.body_fields and place.project_id:
                    arguments["project_id"] = place.project_id
                if working is not None and place != working:
                    site_note = f" · 📍 *{place.name}* (not {working.name})"
            new_ref = None
            if tool.is_write and name != ADD_TOOL and "material_id" in (*tool.body_fields, *tool.path_params):
                # [217]: a line for a material waiting in the list to be added names it new:<name>; Save fills the id.
                adding = [str(e.body.get("name") or "") for e in [*waiting, *new] if e is not None and e.tool == ADD_TOOL]
                new_ref = pending_ref(arguments.get("material_id"), adding) or pending_ref(arguments.get(MATERIAL_SAID), adding)
                said = str(arguments.get(MATERIAL_SAID) or "").strip()
                if not new_ref and adding and said and not pending_ref(said, adding):
                    # [248] (5 Nov, New India: "20 wash basins" said as "വാഷ് ബേസിൻ" right after adding Wash Basin; the
                    # model gave the line a made-up id, it was refused, and the 20 were lost): their word in English
                    # names the material being added in this message, so the line goes on it.
                    new_ref = pending_ref(await english(said), adding)
                if new_ref:
                    arguments = {**arguments, "material_id": new_ref}
            if name == ADD_TOOL and not arguments.get("default_unit_id"):
                from mesiri.domains.materials.unit_conversion import natural_stock_unit

                if natural := natural_stock_unit(str(arguments.get("name") or "")):  # WA-166: filled by the code below
                    arguments = {**arguments, "default_unit_id": natural}
            if tool.is_write:
                # [229]: a date nobody said is the message's date, filled by the code (company timezone); a date
                # question for "today" cost Ilan's 3-update voice note its whole card.
                arguments = {**arguments, **{
                    r: today.isoformat() for r in tool.required if arguments.get(r) in (None, "")
                    and (tool.spec.parameters["properties"].get(r) or {}).get("format") == "date"}}
            if (tool.is_write and name != CONVERSION_TOOL and "unit_id" in tool.body_fields
                    and arguments.get("unit_id") in (None, "") and arguments.get("material_id")):
                # WA-197: no unit said ("50 cement vannu"): the material's own unit, shown on the line; never a question.
                if stock := await stock_unit(client, str(arguments["material_id"]), [*waiting, *new]):
                    arguments = {**arguments, "unit_id": stock[0]}
                    filled_unit = f" · {stock[1]}"
            missing = [r for r in tool.required if arguments.get(r) in (None, "")]
            if missing:
                return ToolOutcome(content={"error": f"missing: {', '.join(missing)}"})
            path = tool.path
            for p in tool.path_params:
                path = path.replace("{" + p + "}", str(arguments[p]))
            params = {q: arguments[q] for q in tool.query_params if arguments.get(q) not in (None, "")}
            body = {f: arguments[f] for f in tool.body_fields if f in arguments}
            if tool.is_write:
                # [248]: Mesiri translates a free-text field left in another script itself, before any check reads it
                # (a new material "സിമന്റ്" is then "Cement", already in the list, never a second one).
                await translate_body(self._provider, tool.spec.parameters, body, correlation_id)
            body.update({k: (channel if v == TEXT_CHANNEL else v) for k, v in tool.fixed})
            for shop_field in ("vendor_text", "supplier"):
                # WA-201 (basic 5, no duplicates): "ravi trader" for the listed "Ravi Traders" is that vendor, not a
                # new one; PRC-04: a delivery's supplier the same way (the API links it to that vendor).
                if not (tool.is_write and str(body.get(shop_field) or "").strip()):
                    continue
                if (listed := await known_vendor(client, str(body[shop_field]))) and listed != body[shop_field]:
                    body[shop_field] = listed
            if tool.is_write and (sum_ := worked_out(own_words(text), body)) and not tries.get(f"{name}:sum"):
                # WA-200 (basic 4, never change their data): "2 drum primer" held as 40 litres (2 x 20), the model's
                # arithmetic. The quantity is the number they said, in their unit; the code converts. Once: a number
                # they did mean (a total they worked out themselves) goes through when it comes back the same.
                tries[f"{name}:sum"] = 1
                return ToolOutcome(content={"error": sum_})
            said_key = f"{name}:said:{body.get('material_id')}:{body.get('quantity')}:{body.get('unit_cost')}"
            if tool.is_write and (invented := made_up(their_words, body)) and not tries.get(said_key):
                # [248]: a quantity nobody said is never held (a rate read as "1 bag"). Once per line, like WA-200: the
                # same line sent again (they said it as a word) goes through.
                tries[said_key] = 1
                return ToolOutcome(content={"error": invented})
            if tool.is_write and (clash := number_clash(text, body, [e.body for e in new])):
                # [229]: "20 bag cement, aaru mason" became 20 masons: a number said once cannot count two things.
                return ToolOutcome(content={"error": clash})
            if photo_key and tool.is_write and PHOTO_FIELD in tool.hidden and PHOTO_FIELD not in body:
                body[PHOTO_FIELD] = photo_key
            if tool.is_write and "material_id" in tool.body_fields and body.get("material_id") and not new_ref:
                # [210]: the id must be the material they named (or a name the company taught it), never a near one.
                taught = [(e.path.split("/")[2], str(e.body.get("alias") or "")) for e in [*waiting, *new]
                          if e is not None and e.tool == ALIAS_TOOL]
                problem, buttons = await settle_material(
                    client, body, str(arguments.get(MATERIAL_SAID) or ""), their_words, taught, english)
                if problem:
                    unit_ask[:] = buttons
                    return ToolOutcome(content={"error": problem})
            if tool.is_write and "unit_id" in tool.body_fields:
                problem = await settle_unit(client, body)
                if problem:
                    unit_ask[:] = await unit_buttons(client)
                    return ToolOutcome(content={"error": problem})
                unit_ask.clear()
                if body.get("material_id") and not new_ref:  # WA-165: a unit the material cannot be saved in
                    problem, unit_note = await settle_stock_unit(
                        client, body, [*waiting, *new], {**(sizes or {}), **sizes_said}, sender_name)
                    if problem:
                        # WA-197: never a blocker: the line is held with its size asked beside it; "Don't know" or a
                        # Save with no answer holds it for the admin (WA-168), and it saves itself when they answer.
                        size_hint = problem
                        line_key = new_idempotency_key()
                        size_needed[:] = [n for n in size_needed if n["summary"] != str(arguments.get(CONFIRM_ARG) or "")]
                        size_needed.append({"material_id": body["material_id"], "from_unit_id": body["unit_id"],
                                            "path": path, "body": dict(body), "key": line_key,
                                            "summary": str(arguments.get(CONFIRM_ARG) or "").strip()})
                elif new_ref and not await adopt_line_unit(client, body, new_ref, waiting, new):
                    # WA-166: a line for a material waiting to be added, in a unit it will not be counted in
                    size_hint = await settle_new_line_unit(client, body, new_ref, [*waiting, *new])
            if tool.is_write and "from_unit_id" in tool.body_fields:
                problem = await settle_unit(client, body, "from_unit_id")
                if problem:
                    unit_ask[:] = await unit_buttons(client)
                    return ToolOutcome(content={"error": problem})
            if name == STANDARD_CATEGORIES_TOOL and not may_set_sizes:
                # PRC-02c: the company's category list is set up by an admin or a project manager (as on the dashboard).
                return ToolOutcome(content={"error": (
                    "Only an admin or a project manager sets up the company's categories. Nothing was prepared. Say so "
                    "in one line and that their admin can send 'set up categories'.")})
            if (name == ANSWER_SIZE_TOOL and (size := _decimal(body.get("one_unit_equals"))) is not None
                    and not said_number(their_words, size)):
                # [248]: an admin's size answer is their number, never one the model made up (it is for the company).
                return ToolOutcome(content={"error": (
                    f"{_amount(size)} is not a size they said. Nothing is prepared. Ask them for the size in one question.")})
            if name == CONVERSION_TOOL:
                material_id = str(arguments.get("material_id") or "")
                size = _decimal(body.get("one_unit_equals"))
                check = await size_check(client, material_id, str(body.get("from_unit_id") or ""), size, their_words)
                if check.get("error"):
                    return ToolOutcome(content={"error": check["error"]})
                if not may_set_sizes and is_uuid(material_id) and size is not None:
                    # WA-166: only an admin or a project manager sets a size for the company (a Save of it was refused
                    # for everyone else, so their line was refused again). Their size converts their own lines.
                    sizes_said[size_key(material_id, body.get("from_unit_id"))] = float(size)
                    try:  # WA-168: and proposed to the company: the admin confirms it with one tap
                        await client.call("POST", "/materials/size-requests", json={
                            "material_id": material_id, "from_unit_id": body.get("from_unit_id"),
                            "one_unit_equals": float(size)})
                    except Exception:  # noqa: BLE001 -- their own lines are converted either way
                        pass
                    if await resized(material_id, str(body.get("from_unit_id") or "")):
                        return ToolOutcome(content={"status": (
                            "Noted for this person's own lines; the waiting line is converted with it. Do not prepare "
                            "it again. Do not talk about company settings.")})
                    return ToolOutcome(content={"status": (
                        "Noted for this person's own lines (only an admin or a project manager can set a size for the "
                        "whole company). Now prepare the line exactly as they said it: the code converts it with this "
                        "size. Do not talk about company settings.")})
                if check.get("line"):
                    arguments = {**arguments, CONFIRM_ARG: check["line"]}  # drawn by the code, never the model's
            if name == ADD_TOOL:
                if (listed := await already_listed(client, str(body.get("name") or ""))) and " or " in listed:
                    # [254]: "Metal" is the listed aggregate of either size: one question, never a new material.
                    unit_ask[:] = [n.split(" (material_id")[0] for n in listed.split(" or ")][:3]
                    return ToolOutcome(content={"error": (
                        f"{body.get('name')!r} is what sites call {listed}, already in the company's list. Nothing was "
                        "prepared. Do not add it: ask ONE question with `ask`, in their language, which one it is; "
                        "then prepare the line on that material_id.")})
                if listed:
                    # [243]: a material the company has is never added again; the line goes on the listed one.
                    return ToolOutcome(content={"error": (
                        f"{listed} is already in the company's list. Nothing was prepared. Do not add it: prepare the "
                        "line itself on that material_id.")})
                problem, counted = await settle_new_material_unit(client, body)
                if problem:
                    unit_ask[:] = await unit_buttons(client)
                    return ToolOutcome(content={"error": problem})
                if counted:
                    unit_note = f" · counted in {counted}"
                label, problem = await settle_category(client, body, ask=not tries.get(f"{name}:category"))
                if problem:  # PRC-02: the model's category is not theirs: their own list, once
                    tries[f"{name}:category"] = 1
                    return ToolOutcome(content={"error": problem})
                if label:  # shown on the Save card
                    unit_note += f"{CATEGORY_NOTE}{label}"
            if name == UPDATE_MATERIAL_TOOL and str(body.get("category") or "").strip():
                # PRC-02: "put it in Plumbing" moves the material to one of their categories (in words, never an id).
                label, problem = await settle_category(client, body, ask=not tries.get(f"{name}:category"))
                if problem:
                    tries[f"{name}:category"] = 1
                    return ToolOutcome(content={"error": problem})
                if label:
                    unit_note += f"{CATEGORY_NOTE}{label}"
            if name == MEMBER_TOOL:
                problem, buttons = await settle_member(client, path, body)
                if problem:
                    unit_ask[:] = buttons
                    return ToolOutcome(content={"error": problem})
                unit_ask.clear()
            if name == PROJECT_TOOL and (twins := same_name(body.get("name"), places)):
                # [219]: a project they already have is said by the code, in their language; never "I made a mistake",
                # never an offer to make a second one with the same name.
                exists[:] = [_project_exists(twins, language)]
                if len(twins) > 1:
                    # [221] (3 Nov: "3 of them: please tidy them up on the dashboard"): tidied here. The copies are listed
                    # with their sites and records; empty copies are held for archiving (Save), never deleted.
                    line, archive = await tidy_twins(client, str(body.get("name") or ""), places, language)
                    exists[:] = [line]
                    new.extend(archive)
                    numbered = "; ".join(f"{i}. project_id {pid}" for i, pid in enumerate(
                        twin_ids(str(body.get("name") or ""), places), 1))
                    return ToolOutcome(content={"status": (
                        f"{twins[0]} already exists {len(twins)} times; nothing new was prepared. The code lists them "
                        f"for the person ({numbered}) and holds archiving the empty copies, if any. Say nothing about "
                        "it. If they later say which number to keep, prepare update_project status \"archived\" for "
                        "the OTHER numbers (never delete).")})
                return ToolOutcome(content={"status": (
                    f"{twins[0]} already exists; nothing was prepared. The code tells the person; say nothing about "
                    "it and do not offer to create another one with the same name.")})
            if tool.is_write:
                fp = create_fingerprint(name, tool.method, path, body)
                same = next((r for r in reversed(recent_saves or []) if fp and r.get("fp") == fp), None)
                if same and fp not in (repeat_ok or []) and fp not in repeat_asked:
                    repeat_asked.append(fp)
                    when = dt.datetime.fromtimestamp(float(same.get("at") or 0), tz).strftime("%H:%M")
                    return ToolOutcome(content={"error": (
                        f"Already saved at {when}: {same.get('summary') or 'the same thing'}. Ask the person whether they "
                        "want another one; nothing was prepared. If they say yes, prepare it again (it then goes through).")})
                # [233]: what the code can derive is filled before the line is held (a work update with no narrative
                # takes the entry's own words), and a body the API would refuse for a missing field is not held.
                body = fill_body(name, body, str(arguments.get(CONFIRM_ARG) or ""), _place_names(places))
                if gaps := missing_in_body(tool.spec.parameters, body):
                    return ToolOutcome(content={"error": f"missing: {', '.join(gaps)}. Nothing was prepared. Ask the "
                                                         "person for it in this reply (one question)."})
                if (foreign := not_english(tool.spec.parameters, body)) and (tries.get(name, 0) < 1 or name == ADD_TOOL):
                    # A material's own name is never added in another script (it would be the company's list entry).
                    # [243]: everything Mesiri saves is English; the card line and the reply stay in theirs.
                    # [248]: Mesiri translates the fields itself first; only what it could not is sent back to the
                    # model, once. After that the line is held as it is: translating is never the person's job.
                    tries[name] = tries.get(name, 0) + 1
                    return ToolOutcome(content={"error": (
                        f"write body fields in English; keep the reply in {reply_in}. Not English: {', '.join(foreign)}. "
                        "Nothing was prepared: call it again now with those fields translated to English yourself "
                        "(names of people and places as they are, in English letters); confirm_line stays in their "
                        "language. Never ask the person to say anything in English.")})
                if (language in LATIN_LANGUAGES and SCRIPT.search(str(arguments.get(CONFIRM_ARG) or ""))
                        and tries.get(f"{name}:line", 0) < 1):
                    # [252] (5 Nov, Adarsh): card lines written in Malayalam script were turned into Latin letter by
                    # letter ("simantu sairril labhichchu"). The line is written in Manglish by the model, once.
                    tries[f"{name}:line"] = tries.get(f"{name}:line", 0) + 1
                    return ToolOutcome(content={"error": (
                        f"confirm_line must be in {reply_in}: Latin letters only, with material, work and site words in "
                        "English (\"30 bags cement, Green Villa\"). Nothing was prepared: call it again now with "
                        "confirm_line rewritten that way.")})
                if name == "update_project" and body.get("description"):
                    body = await kept_description(client, path, body)
                said_line = str(arguments.get(CONFIRM_ARG) or "").strip()
                if name in PROJECT_LINE_TOOLS:
                    # [257]: a project line the model wrote named a contract value and payment terms the body never
                    # carried; the card line is drawn from the fields that will be saved.
                    said_line = project_line(name, body, places, path) or said_line
                if name in SEND_LINE_TOOLS:
                    # [264] (5 Nov, Adarsh: "Send todays report" -> "OK." and a card line "Today's DPR report"): the
                    # line of a report send is drawn by the code and names the project it goes out for.
                    said_line = send_line(path, places, language) or said_line
                entry = PendingWrite(
                    tool=name, method=tool.method, path=path, params=params, body=body,
                    summary=said_line + filled_unit + unit_note + site_note,
                    idempotency_key=line_key or new_idempotency_key(),
                )
                new.append(entry)
                note = "It saves when the person confirms. Do not say it is saved."
                if name == CONVERSION_TOOL and await resized(str(arguments.get("material_id") or ""),
                                                             str(body.get("from_unit_id") or "")):
                    note += " The waiting line now converts with this size: do not prepare it again."
                if name == CONVERSION_TOOL and (old := await saved_with_old_size(
                        client, str(arguments.get("material_id") or ""), str(body.get("from_unit_id") or ""))):
                    note += old
                if name == ADD_TOOL and body.get("name"):
                    note += (f" Lines for it (what came, a unit size) name it material_id \"{NEW}{body['name']}\": "
                             "prepare them now, in this turn; they save after it.")
                return ToolOutcome(content={"status": "ready, NOT saved", "note": note + size_hint})
            response = await client.call(tool.method, path, params=params)
            content = json.dumps(response.body, default=str, ensure_ascii=False)
            if len(content) > READ_LIMIT:
                content = content[:READ_LIMIT] + " ...(cut)"
            return ToolOutcome(content={"status": response.status, "result": content})

        specs = [t.spec for t in self._tools.values()] + [_ASK_TOOL, *feedback_specs(), web_link_spec()] + (
            list(_READY_TOOLS) if waiting else [])
        specs += [spec for spec, _ in (actions or {}).values()]
        system = self.system_prompt(sender_name=sender_name, today=today, ready=list(ready or []), facts=facts)
        if language in LANGUAGE_LINES and language_chosen:
            # WA-169: the language they chose (users.reply_language) wins over the language of this message.
            system += (f"\n\nThis person chose to always get replies in {LANGUAGE_LINES[language]}. Reply in exactly "
                       "that, whatever language this message is in.")
        elif language in LANGUAGE_LINES:
            # Decided by the code from their words (the model mixed scripts on 1 Nov).
            system += f"\n\nThis message is in {LANGUAGE_LINES[language]}. Reply in exactly that."
        if dropped:
            # [219]: decided by the code; the question only lived in the history, so the model took any message as its answer.
            system += (f"\n\nThis message is NOT an answer to your last question (\"{dropped}\"): that question is dropped. "
                       "It is a new, separate request: do exactly what it asks. Do not ask that question again unless "
                       "this new request needs it.")
        messages =[*(history or []), ChatMessage(role="user", text=text)]
        extra = {"capability": self._capability} if self._capability and _takes(self._provider, "capability") else {}

        def nothing_done() -> bool:
            return (not new and not saved and not asked and not acted and not changed and not exists
                    and len(waiting) == len(ready or []))

        async def ask_model(msgs: list[ChatMessage]) -> Any:
            return await self._provider.run_tools(
                system, msgs, specs, handler, max_steps=self._max_steps, timeout_seconds=self._timeout,
                correlation_id=correlation_id, **extra)

        again_asked = False  # WA-198: one corrective retry per turn at most (reply time)
        try:
            result = await ask_model(messages)
        except Exception as exc:
            # A model error before anything was prepared or saved: one more try (compare run of
            # 1 Nov: one expense message failed on the first call). After an effect, never again;
            # nor when the AI budget is used up (WA-143): the same refusal would come back.
            if not nothing_done() or is_budget_error(exc):
                raise
            result = await ask_model(messages)
        if not result.calls and SAVE_WORD in (result.text or "").casefold() and nothing_done():
            # 2 Nov (Ilan, 23:10, three times): "ready, tap Save" with no tool called, so nothing was prepared.
            # The code checks: one more try, told plainly that nothing is in the list.
            again = await ask_model([*messages, ChatMessage(role="model", text=result.text or ""), ChatMessage(
                role="user", text="(You called no tool, so nothing is in the list: nothing can be saved. Do what my "
                                  "message asks now with the tools, or say plainly what you need.)")])
            result = again.model_copy(update={"calls": [*result.calls, *again.calls]})
            again_asked = True
        if claims_team(result.text) and not told(result.calls):
            # WA-155 (3 Nov): nothing checked that "I've told the team" was true. One more try, told plainly; if it
            # still says so without calling, the code passes it on itself, so what the person was told is true.
            again = await ask_model([*messages, ChatMessage(role="model", text=result.text or ""), ChatMessage(
                role="user", text="(You said the team was told, but you did not call tell_the_team, so nobody was told. "
                                  "If I asked for something you can't do, or complained, call tell_the_team now; "
                                  "otherwise answer without saying the team was told.)")])
            result = again.model_copy(update={"calls": [*result.calls, *again.calls]})
            again_asked = True
            if claims_team(result.text) and not told(result.calls):
                code_told.append({"tool": TELL_THE_TEAM, "by": "code", "arguments": {
                    "kind": "missing_feature", "about": f"Mesiri told them the team was told; passed on by the code: {text[:300]}"},
                    "result": {"status": "passed on by the code (WA-155)"}})
        fixed: list[str] = []  # WA-193
        if not result.calls and nothing_done() and claims_saved(result.text):
            # "Saved" with no tool called: nothing happened. One more try. Answering about an earlier record takes a
            # look-up here, which is how the check below tells that apart from a false "saved".
            again = await ask_model([*messages, ChatMessage(role="model", text=result.text or ""), ChatMessage(
                role="user", text="(You called no tool, so nothing was saved in this turn. Do what my message asks now "
                                  "with the tools. If you were telling me about an earlier record, look it up with a "
                                  "tool and answer from that.)")])
            result = again.model_copy(update={"calls": [*result.calls, *again.calls]})
            again_asked = True
        if not result.calls and not again_asked and claims_cannot(result.text) and not told(result.calls):
            # WA-199 (basic 10, never a dead end): "I can't" from memory, with no tool looked at (the same refusal went
            # out four times on 3 Nov, WA-196). One more try: the tools first; if none does it, the team builds it.
            again = await ask_model([*messages, ChatMessage(role="model", text=result.text or ""), ChatMessage(
                role="user", text="(You said it can't be done, but you looked at no tool. Check your tools first: if one "
                                  "does what I asked, do it now" + hint_reads(read_tools_for(f"{text} {result.text}", self._tools))
                                  + ". If none does, call tell_the_team (missing_feature) and "
                                  "tell me the way for now, or what you can do instead. Never just say no.)")])
            result = again.model_copy(update={"calls": [*result.calls, *again.calls]})
            again_asked = True
            if claims_cannot(result.text) and not told(result.calls):
                # Still "can't", still not passed on: the code passes it on, so what they asked gets built.
                code_told.append({"tool": TELL_THE_TEAM, "by": "code", "arguments": {
                    "kind": "missing_feature", "about": f"Mesiri said it cannot do this; passed on by the code: {text[:300]}"},
                    "result": {"status": "passed on by the code (WA-199)"}})
        if not result.calls and not again_asked and nothing_done() and (
                unbacked := unbacked_figures(result.text, text, f"{facts} {' '.join(e.summary for e in ready or [])}")):
            # [260] (basic 2/3, honest answers): figures about what is recorded with nothing looked up. The conversation
            # holds lines that were cancelled or never saved, so a figure must come from a tool or today's records.
            again = await ask_model([*messages, ChatMessage(role="model", text=result.text or ""), ChatMessage(
                role="user", text=f"(You gave figures ({', '.join(unbacked[:3])}) without looking anything up. What is "
                                  "recorded comes only from a tool or today's records above; the conversation can hold "
                                  "lines that were cancelled or never saved. Look it up now"
                                  + hint_reads(read_tools_for(f"{text} {result.text}", self._tools))
                                  + " and answer from what it returns; if nothing is recorded, say so plainly. Figures that "
                                  "are not about their records (an example message, general construction knowledge) "
                                  "stay: then give the same answer.)")])
            result = again.model_copy(update={"calls": [*result.calls, *again.calls]})
            again_asked = True
        looked = lambda calls: any(getattr(self._tools.get(c.name), "is_write", True) is False for c in calls)  # noqa: E731
        if told(result.calls) and not looked(result.calls) and not again_asked:
            # [247] (Ilan, 5 Nov): "how far is the project / what can Mesiri do" went to the team as a missing feature
            # while work_progress, list_issues and day_summary were there. The topic is the model's own (what it told
            # the team); a read tool that shares it makes the turn run once more, told which. If that reads, the
            # team is not told (nothing is missing); if it does not, the team stays told.
            asked_about = " ".join(f"{c.arguments.get('about', '')} {c.arguments.get('why', '')}" for c in result.calls
                                   if c.name == TELL_THE_TEAM)
            reads = read_tools_for(f"{asked_about} {result.text}", self._tools)
            if reads:
                again = await ask_model([*messages, ChatMessage(role="model", text=result.text or ""), ChatMessage(
                    role="user", text="(You passed this to the team, but you read nothing" + hint_reads(reads) + ". "
                                      "If one of them answers my message, use it now and answer from what it returns; "
                                      "if nothing is recorded, say so and give an example message to send. Do not call "
                                      "tell_the_team for something these tools answer.)")])
                again_asked = True
                if looked(again.calls):
                    result = again.model_copy(update={"calls": [c for c in result.calls if c.name != TELL_THE_TEAM] + again.calls})
                else:  # nothing read: the team stays told once, not twice
                    result = again.model_copy(update={"calls": [*result.calls, *[c for c in again.calls if c.name != TELL_THE_TEAM]]})
        lost = left_over(own_words(text), " ".join([
            kept_texts(result.calls, [e for e in waiting if e is not None] + new, asked, result.text),
            *_place_names(places)])) if (new or changed) and not again_asked else []  # "Tower 2" is a name
        if lost:
            # WA-198 (basic 2, lose nothing): a number they said is in nothing this turn prepared, asked or answered
            # ("20 bag cement, 6 mason" with only the cement on the card). One more try, told which; never a loop.
            again = await ask_model([*messages, ChatMessage(role="model", text=result.text or ""), ChatMessage(
                role="user", text=(f"(My message also said {', '.join(lost)}, and nothing you prepared, asked or "
                                   "answered has it. Every part of my message is prepared or asked about: prepare that "
                                   "part now, or ask about it in one question. Keep everything already prepared. If "
                                   "it is not an update (a phone number, a time), just answer.)"))])
            result = again.model_copy(update={"calls": [*result.calls, *again.calls]})
        lines_lost = not_held(result.calls, new) if not asked and not site_ask else []
        if lines_lost and not lost and not again_asked:
            # [248] (5 Nov, New India: three new materials on the card, their 20 + 20 + 30 + 1 load dropped, and the
            # reply said all were ready): a line refused for its material and never held after. One more try.
            again = await ask_model([*messages, ChatMessage(role="model", text=result.text or ""), ChatMessage(
                role="user", text=(f"(These lines are NOT on the card: {'; '.join(lines_lost)}. Their material was refused "
                                   "(read the error of that call). Prepare each now as the error says: a material "
                                   "being added in this message is material_id \"new:<its name>\". Keep everything "
                                   "already prepared.)"))])
            result = again.model_copy(update={"calls": [*result.calls, *again.calls]})
            lines_lost = not_held(result.calls, new)
        false_saved = (claims_saved(result.text) and not any(r.ok for r in saved) and not told(result.calls)
                       and bool(new or changed or saved or not result.calls))
        if false_saved:  # WA-193: code decides; what is held stays held and the ready list says so
            result = result.model_copy(update={"text": without_saved_claims(result.text or "")})
            fixed.append("saved")
        claimed_ready = nothing_done() and (false_saved or asks_to_tap_save(result.text or ""))  # [229]
        if (not (result.text or "").strip() and not new and not asked and not saved and not acted and not exists
                and not false_saved):
            # It looked something up and said nothing ("OK."): ask once for the answer in words.
            again = await ask_model([*messages, ChatMessage(role="model", text="(looked it up)"),
                                     ChatMessage(role="user", text="(answer my message now, in words)")])
            result = again.model_copy(update={"calls": [*result.calls, *again.calls]})
        calls = [{"tool": c.name, "arguments": c.arguments, "result": c.outcome.content if c.outcome else None}
                 for c in result.calls] + code_told
        still = [e for e in waiting if e is not None]
        # [217]: a question asked with no options still gets the buttons the code built (the near-match ones).
        options = asked.get("options", []) or unit_ask or site_ask
        if size_needed:  # WA-168: one tap when nobody on site knows the size
            dont_know = DONT_KNOW.get(language or "", DONT_KNOW["english"])
            # WA-197: the line is on the list, so Save comes third (WhatsApp shows 3 buttons): one size option at most.
            options = [o for o in options if o != dont_know][:1] + [dont_know]
        reply = (result.text or "").strip()
        missing = [u for u in dict.fromkeys(links) if u not in reply]
        if missing:  # WA-141: a link the code built always reaches the person, even if the model left it out
            reply = "\n".join([reply, *missing]).strip()
        if exists:  # [219]: the code's line; the model's words only when it did something else too
            busy = bool(new or saved or acted or changed)
            reply = "\n\n".join([exists[0], reply] if busy and reply else [exists[0]])
            if not busy:
                asked.clear()
                options = []
        if claimed_ready and not still and not new and not asked and not exists and not options:
            reply = ""  # [229]: "ready, tap Save" with nothing held: the code says what is true instead
        clean = without_internals(reply)  # WA-193: last, so a line the code added is checked too
        if clean != reply.strip():
            fixed.append("internals")
            reply = clean or (plain_refusal("", language) if not still and not new else "")
        return ApiTurn(reply=reply, pending=still + new, saved=saved, calls=calls,
                       nothing_held=bool(claimed_ready and not reply and not still and not new),
                       not_held=lines_lost,
                       stop_reason=result.stop_reason, question=without_internals(asked.get("question", "")),
                       options=[without_ids(o) for o in options], reply_fixed=fixed,
                       repeat_asked=repeat_asked, dropped_question=dropped, sizes_said=sizes_said,
                       size_needed=size_needed, language_set=next(iter(language_set), ""))


_NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])")


def entry_numbers(body: dict[str, Any]) -> list[float]:
    """The counts and quantities an entry carries: a labour line's headcount, a receipt's quantity, a work entry's
    measured quantities."""
    found: list[Any] = [body.get("quantity")]
    found += [line.get("headcount") for line in body.get("lines") or [] if isinstance(line, dict)]
    found += [q.get("quantity") for q in body.get("quantities") or [] if isinstance(q, dict)]
    out = []
    for v in found:
        try:
            if v not in (None, ""):
                out.append(float(v))
        except (TypeError, ValueError):
            pass
    return out


def worked_out(text: str, body: dict[str, Any]) -> str:
    """WA-200: a quantity in ``body`` that is not a number they said but two of their numbers multiplied or added
    ("2 drum, 20 litre each" -> 40). Returns what to tell the model, or "". Word numbers ("aaru") are not in digits
    and are never checked."""
    said = [float(n) for n in _NUMBER.findall(_NOT_AN_AMOUNT.sub(" ", text or ""))]
    if len(said) < 2:
        return ""
    for n in dict.fromkeys(entry_numbers(body)):
        if n in said:
            continue
        pairs = [(a, b) for i, a in enumerate(said) for b in said[i + 1:]]
        hit = next(((a, b, op) for a, b in pairs for op, v in (("x", a * b), ("+", a + b)) if abs(v - n) < 1e-9), None)
        if hit:
            a, b, op = hit
            return (f"{n:g} is not a number they said: it is {a:g} {op} {b:g}, worked out. Nothing was prepared. Use the "
                    f"number they said, in the unit they said (\"2 drum\" stays 2 drum): the code converts it to the stock "
                    "unit and shows it on the line. If a size is part of it (\"20 litre drum\"), prepare "
                    "`set_unit_conversion` for it too.")
    return ""


def made_up(text: str, body: dict[str, Any]) -> str:
    """[248] (5 Nov, a voice note giving three suppliers' rates: "310 a bag" became a receipt of 1 bag): a line whose
    rate is a number in their words but whose quantity is not. That is a rate read as a quantity. Only lines that carry
    a rate (``unit_cost``): a quantity carried from earlier, converted or corrected is never checked here (WA-200 and
    [229] own those). Returns what to tell the model, or "". Sent back once: a number they said in words ("oru" /
    ഒരു = 1) goes through when it comes back the same."""
    said = {float(n) for n in _NUMBER.findall(_NOT_AN_AMOUNT.sub(" ", text or ""))}
    try:
        rate = float(body.get("unit_cost"))  # type: ignore[arg-type]
        quantity = float(body.get("quantity"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if rate not in said or quantity in said:
        return ""
    return (f"{rate:g} is a rate they said, but the quantity {quantity:g} is not in their words. Nothing was prepared. "
            "If they said the quantity as a word (oru/ഒരു = 1, aaru/ആറ് = 6), prepare it again unchanged. If not, "
            "never make it up: a message that gives rates and asks something (which is better, is this rate ok) is a "
            "question: answer it and prepare nothing; else ask for the quantity in your one question.")


def number_clash(text: str, body: dict[str, Any], others: list[dict[str, Any]]) -> str:
    """[229] (4 Nov: "20 bag cement … aaru masonmar": the masons became 20, the cement's number): each number stays with
    its own item. A number written in digits once in their words cannot count for two entries of one message.
    Returns what to tell the model, or "" when all is well (word numbers like "aaru" are never in digits: no check)."""
    said = [float(n) for n in _NUMBER.findall(text or "")]
    for n in dict.fromkeys(entry_numbers(body)):
        used = sum(1 for o in others if n in entry_numbers(o))
        if used and said.count(n) < used + 1 and n in said:
            return (f"{n:g} is written once in the person's words and another entry of this message already uses it. "
                    "Nothing was prepared. Use the number they said for THIS item (a number word counts: "
                    "aaru/ആറ് = 6, anchu/അഞ്ച് = 5, pathu = 10), or ask for it with `ask` if you cannot tell.")
    return ""


#: WA-198: numbers that are not amounts: times (10:30, 10am), dates (5/11, 05-11-2026), ordinals and floors (2nd,
#: 3rd), refs (#123, [243]), and long digit runs (phone numbers, ids).
_NOT_AN_AMOUNT = re.compile(
    r"\d{1,2}[:.]\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm)\b|\d{1,4}[/-]\d{1,2}(?:[/-]\d{2,4})?"
    r"|\d+(?:st|nd|rd|th)\b|[#\[]\d+\]?|\d{6,}", re.IGNORECASE)


#: WA-198: ids in what a turn kept (uuids, hex keys): their digits are not amounts ("4b2e5df7-4..." holds a "4").
_IDS = re.compile(r"\b(?=[0-9a-f-]*[a-f])[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b|\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)"
                  r"[0-9a-f]{12,}\b", re.IGNORECASE)


def said_number(text: str, value: Any) -> bool:
    """[248]: ``value`` is a number written in ``text`` (a size: "0.33", "2.83" are numbers here, never times)."""
    try:
        wanted = float(value)
    except (TypeError, ValueError):
        return False
    return any(abs(float(n) - wanted) < 1e-9 for n in _NUMBER.findall(text or ""))


def left_over(text: str, kept: str) -> list[str]:
    """WA-198: the numbers written in ``text`` (their message) that appear nowhere in ``kept`` (everything the turn
    prepared, asked, answered or looked up). Times, dates, ordinals, refs and phone numbers are not amounts."""
    said = _NUMBER.findall(_NOT_AN_AMOUNT.sub(" ", text or ""))
    have = {float(n) for n in _NUMBER.findall(_IDS.sub(" ", kept or ""))}
    return list(dict.fromkeys(n for n in said if float(n) not in have))


def own_words(text: str) -> str:
    """WA-198: the person's own words: a photo's reading (added by the code, a bill's GST and invoice numbers) is not."""
    return (text or "").split(PHOTO_SHOWS, 1)[0]


#: How the code adds a photo's reading to the message (``whatsapp._photo_text``).
PHOTO_SHOWS = "\nWhat the photo shows:"


#: [248]: refusals of a line's MATERIAL (settle_material): the line is meant to come back prepared differently.
_MATERIAL_REFUSALS = ("is not in the company's material list", "material_said is not in English",
                      "say which material they named")


def not_held(calls: list[Any], held: list[PendingWrite]) -> list[str]:
    """[248]: the card words of write lines refused for their material in this turn that no held line of the same tool
    took up after (same quantity, or the same card words). Other refusals (a question to ask, "already saved", a rate
    that is not a quantity) are meant: not listed."""
    out: list[str] = []
    for call in calls:
        content = call.outcome.content if getattr(call, "outcome", None) else None
        error = str(content.get("error") or "") if isinstance(content, dict) else ""
        if not any(r in error for r in _MATERIAL_REFUSALS):
            continue
        line = str(call.arguments.get(CONFIRM_ARG) or "").strip()
        quantity = call.arguments.get("quantity")
        taken = any(e.tool == call.name and (
            (line and e.summary.startswith(line))
            or (quantity is not None and str(e.body.get("quantity")) in (str(quantity), str(float(quantity))))
        ) for e in held)
        if line and not taken and line not in out:
            out.append(line)
    return out


def kept_texts(calls: list[Any], held: list[PendingWrite], asked: dict[str, Any], reply: str | None) -> str:
    """WA-198: what a turn did with the message, as text: the held entries (bodies and lines), the question and its
    options, the reply, and the arguments of every call. A call the code refused counts too: the model did use the
    number, and the refusal tells it what to do with it ("Already saved", a number said once)."""
    parts = [json.dumps(e.body, default=str, ensure_ascii=False) + " " + e.summary for e in held]
    parts += [str(asked.get("question") or ""), " ".join(asked.get("options") or []), reply or ""]
    for c in calls:
        if c.name in (SAVE_READY, DROP_READY, CHANGE_READY):
            continue  # entry numbers, not their amounts
        parts.append(json.dumps(c.arguments, default=str, ensure_ascii=False))
    return " ".join(parts)


def _typed(old: Any, value: Any) -> Any:
    """A changed value as the field had it (a quantity stays a number; the tool's values come as text)."""
    if isinstance(old, bool) or not isinstance(value, str):
        return value
    try:
        if isinstance(old, int):
            return int(value) if value.strip().lstrip("-").isdigit() else float(value)
        if isinstance(old, float):
            return float(value)
    except ValueError:
        return value
    return value


def _takes(provider: Any, name: str) -> bool:
    """Whether ``provider.run_tools`` accepts ``name``: the model router takes ``capability``
    (the control-panel row), a single provider (Gemini) does not."""
    import inspect

    try:
        params = inspect.signature(provider.run_tools).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def held(result: WriteResult) -> bool:
    """WA-197: the line was held for the admin's size, not saved yet."""
    return isinstance(result.body, dict) and bool(result.body.get(HELD_FOR_SIZE))


def _detail(body: Any) -> str:
    """The API's own reason for a refusal, short."""
    if isinstance(body, dict):
        detail = body.get("detail", body)
        if isinstance(detail, dict):
            detail = detail.get("message") or detail
        if isinstance(detail, list):  # FastAPI validation errors
            detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
        return str(detail)[:200]
    return str(body)[:200]


async def settle_unit(client: ApiClient, body: dict[str, Any], field: str = "unit_id") -> str:
    """Make ``body[field]`` the id of an active unit (it may be "bags", a code or a wrong id). ``field`` is
    ``unit_id`` on a line, ``from_unit_id`` on a unit conversion (WA-165: "load" there was refused at Save).
    Returns "" when it is settled, else what to tell the model (it then asks one question)."""
    try:
        response = await client.call("GET", "/materials/units-of-measure")
    except Exception:  # noqa: BLE001 -- the API's own check still decides
        return ""
    units = unit_rows(response.body) if response.ok else []
    if not units:
        return ""
    unit = resolve_unit(units, body.get(field))
    if unit is None:
        return (f"{field} {str(body.get(field))[:40]!r} is not one of the company's units. Use the id of one of: "
                f"{unit_choices(units)}. If you cannot tell which unit they mean, ask them with `ask` and those units as options.")
    body[field] = str(unit["id"])
    return ""


CONVERSION_TOOL = "set_unit_conversion"
#: PRC-02c: the builder's standard category list, applied from WhatsApp (an admin or a project manager).
STANDARD_CATEGORIES_TOOL = "add_standard_categories"
#: WA-168: an admin answering "📏 Sizes needed".
ANSWER_SIZE_TOOL = "answer_size_request"
#: WA-197: the note on a held line whose size is not known yet (" (1 Loads = how many Bags?)").
SIZE_UNKNOWN = re.compile(r" \(1 [^()]* = how many [^()]*\?\)")
#: WA-168: the button under a size question when nobody on site knows it (WhatsApp titles: 20 characters).
DONT_KNOW = {"english": "🤷 Don't know", "manglish": "🤷 Ariyilla", "malayalam": "🤷 അറിയില്ല",
             "hinglish": "🤷 Pata nahi", "hindi": "🤷 पता नहीं"}


def _size_waiting(entry: PendingWrite | None, material_id: str, unit_id: str) -> Decimal | None:
    """The size in a waiting ``set_unit_conversion`` for this material from this unit (it saves first, so the line
    converts at Save), else None."""
    if (entry is None or entry.tool != CONVERSION_TOOL or f"/materials/{material_id}/" not in entry.path
            or str(entry.body.get("from_unit_id") or "") != unit_id):
        return None
    return _decimal(entry.body.get("one_unit_equals"))


def _decimal(value: Any) -> Decimal | None:
    try:
        found = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return found if found > 0 else None


def size_key(material_id: Any, unit_id: Any) -> str:
    return f"{material_id}:{unit_id}"


def _amount(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.001')).normalize():f}"


async def settle_stock_unit(client: ApiClient, body: dict[str, Any], others: list[PendingWrite | None],
                            sizes: dict[str, Any] | None = None, who: str = "") -> tuple[str, str]:
    """WA-165 / WA-166: a line in a unit its material is not counted in. The API says whether that unit can be
    recorded (``GET /materials/{id}/unit-check``, the decision saving makes). Returns ``(problem, note)``:

    - it can (the stock unit, or the company knows the size), or a size for it waits in the list: ("", " (= 60 bags)")
      -- the note goes on the ready line, so a wrong size is seen before Save;
    - the person told their own size before (``sizes``: they may not set one for the company): the code converts
      the line itself into the stock unit, their words kept in its notes: ("", note);
    - no size is known: WA-197, the line is still held (never a blocker), with " (1 Loads = how many Bags?)" on it, and this
      is what to tell the model: ask the size once; Save without an answer holds the line for the admin;
    - the API cannot tell: ("", ""), and its own check decides at Save."""
    material_id, unit_id = str(body.get("material_id") or ""), str(body.get("unit_id") or "")
    if not (is_uuid(material_id) and is_uuid(unit_id)):
        return "", ""
    try:
        response = await client.call("GET", f"/materials/{material_id}/unit-check", params={"unit_id": unit_id})
    except Exception:  # noqa: BLE001
        return "", ""
    found = response.body if response.ok and isinstance(response.body, dict) else {}
    if not found:
        return "", ""
    material, stock, said = found.get("material"), found.get("stock_unit_name"), found.get("unit_name")
    quantity = _decimal(body.get("quantity"))
    if found.get("unit") == found.get("stock_unit"):
        return "", ""
    size = next((z for e in others if (z := _size_waiting(e, material_id, unit_id)) is not None), None)
    if size is None and found.get("fits"):
        size = _decimal(found.get("one_unit_equals"))
    if size is not None:
        return "", f" (= {_amount(quantity * size)} {stock})" if quantity else ""
    own = _decimal((sizes or {}).get(size_key(material_id, unit_id)))
    if own is not None and found.get("stock_unit_id"):
        # Converted here, as the person said it: the API records the stock unit; their words stay in the notes.
        reported = f"reported as {_amount(quantity) if quantity else ''} {said} (1 {said} = {_amount(own)} {stock}" + (
            f", as {who} said)" if who else ")")
        if quantity:
            body["quantity"] = float(quantity * own)
        if _decimal(body.get("unit_cost")):
            body["unit_cost"] = float((_decimal(body["unit_cost"]) / own).quantize(Decimal("0.01")))  # type: ignore[operator]
        body["unit_id"] = str(found["stock_unit_id"])
        body["notes"] = f"{body['notes'].strip()} ({reported})" if str(body.get("notes") or "").strip() else reported
        return "", f" (= {_amount(quantity * own)} {stock})" if quantity else ""
    return (f" It is held, but {material} is counted in {stock} in their stock and how many {stock} one {said} is "
            f"is not known yet. Ask ONE question with `ask` now, in their language, in their direction: \"1 {said} "
            f"{material} = how many {stock}?\" (for steel bars, the bar size is enough: use the sizes in your "
            f"instructions as options), and say that if they don't know they can just tap Save and their admin is "
            f"asked. When they answer, prepare ONLY `set_unit_conversion` (material_id {material_id}, from_unit_id "
            f"{unit_id}, one_unit_equals their number): this line is already waiting and saves converted; never "
            f"prepare it again."), f" (1 {said} = how many {stock}?)"


async def stock_unit(client: ApiClient, material_id: str, others: list[PendingWrite | None]) -> tuple[str, str] | None:
    """WA-197: (id, name) of the unit ``material_id`` is counted in: a listed material's, or the one a material waiting
    to be added (``new:<name>``) will have. None when it cannot be told (the model then asks, as before)."""
    if material_id.startswith(NEW):
        adding = next((e for e in others if e is not None and e.tool == ADD_TOOL
                       and alias_key(str(e.body.get("name") or "")) == alias_key(material_id.removeprefix(NEW))), None)
        unit_id = str((adding.body if adding else {}).get("default_unit_id") or "")
    else:
        unit_id = next((str(r.get("default_unit_id") or "") for r in await catalogue(client)
                        if str(r["id"]) == material_id), "")
    if not is_uuid(unit_id):
        return None
    unit = next((u for u in await _units(client) if str(u["id"]) == unit_id), None)
    return (unit_id, str(unit.get("display_name") or unit.get("code"))) if unit else None


async def _units(client: ApiClient) -> list[dict[str, Any]]:
    try:
        response = await client.call("GET", "/materials/units-of-measure")
    except Exception:  # noqa: BLE001
        return []
    return unit_rows(response.body) if response.ok else []


async def saved_with_old_size(client: ApiClient, material_id: str, from_unit_id: str, days: int = 30) -> str:
    """[248] (5 Nov, New India: "1 load M-sand = 60 cum" saved, then to be corrected): a new size changes lines saved
    from now on, never the ones already saved with the old size ("60 cum, reported as 1 Loads"). Those receipts (last
    ``days`` days, not taken back) are named for the model, which offers to redo them with the new size in the same
    Save. "" when there are none (or they cannot be read)."""
    if not (is_uuid(material_id) and is_uuid(from_unit_id)):
        return ""
    try:
        check = await client.call("GET", f"/materials/{material_id}/unit-check", params={"unit_id": from_unit_id})
        unit = str(check.body.get("unit_name") or "") if check.ok and isinstance(check.body, dict) else ""
        since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        found = await client.call("GET", "/materials/inflows",
                                  params={"material_id": material_id, "date_from": since, "limit": 100})
    except Exception:  # noqa: BLE001 -- nothing named; the size itself is unchanged
        return ""
    items = found.body.get("items") if found.ok and isinstance(found.body, dict) else None
    reported = re.compile(rf"reported as\s+([\d.]+)\s+{re.escape(unit)}\b", re.IGNORECASE) if unit else None
    old = []
    for row in items or []:
        if not isinstance(row, dict) or row.get("is_reversed") or row.get("reverses_movement_id"):
            continue
        said = reported.search(str(row.get("notes") or "")) if reported else None
        if said:
            old.append(f"receipt_id {row.get('id')}: {row.get('occurred_date')}, {_amount(_decimal(row.get('quantity')))} "
                       f"{row.get('unit')} saved for {said.group(1)} {unit} (supplier {row.get('supplier') or '-'})")
    if not old:
        return ""
    return (" Already SAVED with the old size (this size does not change them): " + "; ".join(old) + ". In ONE line "
            "of your reply, in their language, say these were saved with the old size and ask whether to redo them; "
            "when they say yes, prepare `undo_receipt` for each and `record_receipt` again with the quantity in "
            f"{unit} as they reported it (same site, date and supplier), all in one Save.")


async def size_check(client: ApiClient, material_id: str, from_unit_id: str, size: Decimal | None,
                     said: str | None = None) -> dict[str, str]:
    """WA-166: a size ("1 load = 60 bags") before it is held. ``{"error": ...}`` for one that cannot be right (none
    given, the material is already counted in that unit, or fewer than one piece in a load of a counted material:
    Paraclette's "1 load holobricks = 0.33 nos"); else ``{"line": "📏 1 Loads എംസാന്റ് = 60 Bags"}``, the ready line
    the code draws, so the person sees the size the company will use.

    [248] (5 Nov, New India): "one load = one truck of M-sand" was saved as "1 load M-sand = 60 cum", a size nobody
    said, for the whole company. ``said`` (their words, the conversation included): a size that is not a number in it
    is never held. And a conversion the code already knows (1 ton = 1000 kg, 1 brass = 100 cft, a cement bag = 50 kg)
    is never held or asked: the line converts by itself."""
    from mesiri.domains.materials.unit_conversion import COUNT_UNITS, built_in_per_stock_unit

    if size is None:
        return {"error": "one_unit_equals must be the number they said: how many of the stock unit are in ONE of theirs."}
    if not (is_uuid(material_id) and is_uuid(from_unit_id)):
        return {}
    try:
        response = await client.call("GET", f"/materials/{material_id}/unit-check", params={"unit_id": from_unit_id})
    except Exception:  # noqa: BLE001
        return {}
    found = response.body if response.ok and isinstance(response.body, dict) else {}
    if not found:
        return {}
    material, unit, stock = found.get("material"), found.get("unit_name"), found.get("stock_unit_name")
    if found.get("unit") == found.get("stock_unit"):
        return {"error": f"{material} is already counted in {stock}: no size is needed. Prepare the line in {stock}."}
    if built_in_per_stock_unit(str(found.get("unit") or ""), str(found.get("stock_unit") or ""), str(material or "")):
        return {"error": (f"The code already converts {unit} to {stock} for {material} (a standard measure). Nothing "
                          f"is prepared: never set or ask this size. Prepare the line in {unit}, as they said.")}
    if str(found.get("stock_unit") or "").lower() in COUNT_UNITS and size < 1:
        return {"error": (f"1 {unit} of {material} cannot be less than 1 {stock}: the size is the wrong way round. "
                          f"Nothing is prepared. Ask again, in their language: how many {stock} are in 1 {unit}?")}
    if said is not None and not said_number(said, size):
        return {"error": (f"{_amount(size)} is not a size they said: never make one up (it would be used for the whole "
                          f"company). Nothing is prepared. Prepare the line in {unit} as they said, without "
                          "`set_unit_conversion`: the code holds it and asks the size beside it.")}
    return {"line": f"📏 1 {unit} {material} = {_amount(size)} {stock}"}


async def settle_new_material_unit(client: ApiClient, body: dict[str, Any]) -> tuple[str, str]:
    """WA-166 (Paraclette, 31 Oct: "1 load TMT" made TMT a material counted in loads): a new material is counted in
    the unit its kind is counted in (TMT -> kg, M-sand -> cft, cement -> bags), not the unit of the first message;
    lines in other units convert into it. Unknown kinds keep the unit given. Returns (problem, the unit's name)."""
    from mesiri.domains.materials.unit_conversion import natural_stock_unit

    code = natural_stock_unit(str(body.get("name") or ""))
    unit = next((u for u in await _units(client) if code and str(u.get("code")).lower() == code), None)
    if unit is not None:
        body["default_unit_id"] = str(unit["id"])
        return "", str(unit.get("display_name") or code)
    if body.get("default_unit_id"):
        return await settle_unit(client, body, "default_unit_id"), ""
    return "", ""


#: [254]: units a delivery comes in that are never how a material is counted (a lorry load, a drum of a size nobody
#: said): a new material's line in one of these keeps the material's natural unit and asks the size (WA-166).
NOT_A_STOCK_UNIT = frozenset({"load", "trip", "truck", "lorry", "drum", "tin", "bucket", "bundle"})
_COUNTED_IN = re.compile(r" · counted in [^·]*?(?= · |\s*$)")


async def adopt_line_unit(client: ApiClient, body: dict[str, Any], ref: str, waiting: list[PendingWrite | None],
                          new: list[PendingWrite]) -> bool:
    """[254] (5 Nov, Adarsh: "10 bags metal" held "Add Metal · counted in Cubic Feet", and "I don't need cubic feet"
    kept it in cft): a new material is counted in the unit of its own line (bags), not a unit nobody said. The held
    add is changed in place (its unit and its card note, once). False when the line's unit is a delivery unit
    (``NOT_A_STOCK_UNIT``: WA-166's "1 load TMT"), already the material's, or unknown: then the size is asked as before."""
    name = alias_key(ref.removeprefix(NEW))
    unit_id = str(body.get("unit_id") or "")
    for entries in (new, waiting):
        for i, e in enumerate(entries):
            if e is None or e.tool != ADD_TOOL or alias_key(str(e.body.get("name") or "")) != name:
                continue
            if not is_uuid(unit_id) or str(e.body.get("default_unit_id") or "") == unit_id:
                return False
            unit = next((u for u in await _units(client) if str(u.get("id")) == unit_id), None)
            if unit is None or str(unit.get("code") or "").casefold() in NOT_A_STOCK_UNIT:
                return False
            label = str(unit.get("display_name") or unit.get("code"))
            head, mark, category = _COUNTED_IN.sub("", e.summary).rstrip().partition(CATEGORY_NOTE)
            summary = f"{head.rstrip()} · counted in {label}" + (f"{mark}{category}" if mark else "")
            entries[i] = replace(e, body={**e.body, "default_unit_id": unit_id}, summary=summary)
            return True
    return False


async def settle_new_line_unit(client: ApiClient, body: dict[str, Any], ref: str, others: list[PendingWrite | None]) -> str:
    """WA-166: a line for a material waiting to be added ([217]), in a unit the new material will not be counted in,
    with no size waiting and no fixed one. The line is held (the new material and its line stay together); this is
    what to tell the model: ask the size now, in the same reply. "" when nothing is missing."""
    from mesiri.domains.materials.unit_conversion import built_in_per_stock_unit

    name = ref.removeprefix(NEW)
    adding = next((e for e in others if e is not None and e.tool == ADD_TOOL
                   and alias_key(str(e.body.get("name") or "")) == alias_key(name)), None)
    unit_id, stock_id = str(body.get("unit_id") or ""), str((adding.body if adding else {}).get("default_unit_id") or "")
    if not (is_uuid(unit_id) and is_uuid(stock_id)) or unit_id == stock_id:
        return ""
    if any(_size_waiting(e, ref, unit_id) is not None for e in others):
        return ""
    units = {str(u["id"]): u for u in await _units(client)}
    unit, stock = units.get(unit_id), units.get(stock_id)
    if unit is None or stock is None or built_in_per_stock_unit(str(unit["code"]), str(stock["code"]), name):
        return ""
    said, counted = unit.get("display_name"), stock.get("display_name")
    return (f" {name} will be counted in {counted} (how it is counted everywhere), and how many {counted} one {said} is "
            f"is not known yet: unless a set_unit_conversion for it is prepared in this turn, ask ONE question with `ask` "
            f"now, in their language: \"1 {said} {name} = how many {counted}?\". When they answer, prepare "
            f"`set_unit_conversion` (material_id \"{ref}\", from_unit_id {unit_id}, one_unit_equals their number); "
            f"this line stays waiting and saves converted.")


MEMBER_TOOL = "add_project_member"
ALIAS_TOOL = "add_material_alias"


def moved_off_new(waiting: list[PendingWrite | None], before: str, after: str, alias_tool: Any,
                  after_name: str = "") -> dict[str, Any]:
    """WA-194: a line for a material waiting to be added (``new:<name>``) was moved to one in the list ("it's
    Paint"). With no line left on it, the new material and its settings leave the ready list (never a stray catalogue
    entry), and the word is remembered as that material's name (an ``add_material_alias`` entry), so it is matched
    next time. ``after_name``: the listed name of ``after`` ("Paint"), for the card line. Returns what to tell
    the model."""
    if not before.startswith(NEW) or after == before or after.startswith(NEW):
        return {}
    if any(e is not None and str(e.body.get("material_id") or "") == before for e in waiting):
        return {}
    name = before.removeprefix(NEW)
    dropped = [i for i, e in enumerate(waiting) if e is not None and (
        (e.tool == ADD_TOOL and alias_key(str(e.body.get("name") or "")) == alias_key(name))
        or f"/materials/{before}/" in e.path)]
    for i in dropped:
        waiting[i] = None
    out: dict[str, Any] = {"also": f"{name} is no longer added as a new material (nothing else used it)."}
    if alias_tool is not None and is_uuid(after) and not any(
            e is not None and e.tool == ALIAS_TOOL and e.path.split("/")[2] == after for e in waiting):
        waiting.append(PendingWrite(
            tool=ALIAS_TOOL, method=alias_tool.method, path=alias_tool.path.replace("{material_id}", after),
            params={}, body={"alias": name},
            summary=f"🏷️ {name} = {after_name or 'the same material'} from now on",
            idempotency_key=new_idempotency_key()))
        out["also"] += f" {name} is remembered as that material's name (on the list; saves with Save)."
    return out
PROJECT_TOOL = "create_project"
#: [252]: reply languages written in Latin letters; a card line in Malayalam or Devanagari script is sent back once.
LATIN_LANGUAGES = frozenset({"manglish", "hinglish"})
SCRIPT = re.compile(r"[\u0900-\u097f\u0d00-\u0d7f]")
#: [257]: project entries whose card line the code draws from the body (no picture card shows their values).
PROJECT_LINE_TOOLS = frozenset({PROJECT_TOOL, "update_project"})
#: The project fields a card line names, in this order, with their label.
_PROJECT_FIELDS = (("client", "client"), ("location", "location"), ("code", "code"), ("status", "status"),
                   ("description", "details"))


async def kept_description(client: ApiClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """[257]: a project's details are added to, never replaced: the description already saved stays in front of
    what this update brings (unless the new text already holds it). Unchanged when the project can't be read."""
    try:
        current = await client.call("GET", path)
    except Exception:  # noqa: BLE001 -- the update goes as prepared
        return body
    old = str((current.body or {}).get("description") or "").strip() if current.ok and isinstance(
        current.body, dict) else ""
    new = str(body.get("description") or "").strip()
    if not old or old.casefold() in new.casefold():
        return body
    return {**body, "description": f"{old.rstrip('. ')}. {new}"}


def project_line(tool: str, body: dict[str, Any], places: Places | None, path: str = "") -> str:
    """[257]: "New project *Supermarket Kerala*: client Supermarket; location Kerala; details ..." or
    "*Supermarket Kerala*: client Day to Day Supermarket", from the body only: what Save will store, nothing else.
    Empty when the body has nothing to show (the model's line then stays)."""
    parts = []
    for key, label in _PROJECT_FIELDS:
        value = re.sub(r"\s+", " ", str(body.get(key) or "")).strip()
        if value:
            parts.append(f"{label} {value[:80] + '…' if len(value) > 80 else value}")
    if tool == PROJECT_TOOL:
        named = str(body.get("name") or "").strip()
        return f"New project *{named}*" + (f": {'; '.join(parts)}" if parts else "") if named else ""
    current = ""
    project_id = str(body.get("project_id") or path.rstrip("/").rsplit("/", 1)[-1])
    for pid, pname in (places.projects if places else ()):
        if pid == project_id:
            current = pname
    renamed = str(body.get("name") or "").strip()
    if renamed and renamed != current:
        parts.insert(0, f"name {renamed}")
    if not parts:
        return ""
    return f"*{current or 'Project'}*: {'; '.join(parts)}"


#: [264] Writes that send something out (not a record): their card line is drawn by the code.
SEND_LINE_TOOLS = frozenset({"send_dpr"})


def send_line(path: str, places: Places | None, language: str | None) -> str:
    """[264]: "📤 Today's report for *Green Villa*" in their language, from the project in the send's path.
    Empty when the project is not one of theirs (the model's line then stays)."""
    from runtime.agent.wording import say

    m = re.search(r"/projects/([^/]+)/send", path or "")
    name = next((pname for pid, pname in (places.projects if places else ()) if m and pid == m.group(1)), "")
    return say("api.send_line", language or "english", project=name) if name else ""


def twin_ids(name: str, places: Places | None) -> list[str]:
    """[221]: the ids of the person's projects called ``name`` (case and spacing aside), in their list's order."""
    key = " ".join(name.casefold().split())
    return [pid for pid, pname in (places.projects if places else ()) if " ".join(pname.casefold().split()) == key]


async def _records(client: ApiClient, project_id: str) -> int | None:
    """[221]: how many records a project has (its timeline's total), or None when it can't be read."""
    try:
        response = await client.call("GET", "/timeline", params={"project_id": project_id, "limit": 1})
    except Exception:  # noqa: BLE001
        return None
    body = response.body if response.ok and isinstance(response.body, dict) else {}
    total = body.get("total")
    return int(total) if isinstance(total, int) else None


async def tidy_twins(client: ApiClient, name: str, places: Places | None,
                     language: str | None) -> tuple[str, list[PendingWrite]]:
    """[221]: the person's projects called ``name``, listed ("1. Rana Mart · 2 sites · 14 records"), and the empty
    copies held for archiving (the dashboard's own status, through update_project): Save tidies them, nothing is
    deleted. When more than one copy has records, nothing is held: they say which to keep. A copy whose records
    can't be read counts as having some (never archived on a guess)."""
    import asyncio

    from runtime.agent.wording import say

    lang = language or "english"
    twins = [(pid, pname) for pid, pname in (places.projects if places else ()) if pid in twin_ids(name, places)]
    counts = await asyncio.gather(*(_records(client, pid) for pid, _ in twins))
    sites = {pid: sum(1 for s in (places.sites if places else ()) if s[2] == pid) for pid, _ in twins}
    lines = [say("api.twin_line", lang, number=str(i), name=pname, sites=str(sites[pid]),
                 records="—" if n is None else str(n)) for i, ((pid, pname), n) in enumerate(zip(twins, counts, strict=True), 1)]
    head = say("api.project_twins_found", lang, name=twins[0][1] if twins else name, count=str(len(twins)))
    used = [i for i, n in enumerate(counts) if n != 0]
    if len(used) > 1:
        return "\n".join([head, *lines, "", say("api.project_twins_pick", lang)]), []
    keep = used[0] if used else 0
    archive = [PendingWrite(tool="update_project", method="PUT", path=f"/projects/{pid}", params={},
                            body={"status": "archived"},
                            summary=say("api.twin_archive", lang, number=str(i), name=pname),
                            idempotency_key=new_idempotency_key())
               for i, (pid, pname) in enumerate(twins, 1) if i - 1 != keep]
    tail = say("api.project_twins_archive", lang, number=str(keep + 1))
    return "\n".join([head, *lines, "", tail]), archive


def _project_exists(twins: list[str], language: str | None) -> str:
    """[219]: "Rana Mart already exists ✅", and when there are several, that they can tidy them up on the dashboard."""
    from runtime.agent.wording import say

    lang = language or "english"
    line = say("api.project_exists", lang, name=twins[0])
    return f"{line} {say('api.project_twins', lang, count=str(len(twins)))}" if len(twins) > 1 else line


async def settle_member(client: ApiClient, path: str, body: dict[str, Any]) -> tuple[str, list[str]]:
    """[207]: make ``body["userId"]`` the id of a person already in the company (the model passes the name
    they said) and ``body["role"]`` a role code ("site engineer" -> SITE_ENGINEER, classic's own role words).
    Never creates a person. Returns ("", []) when settled, else what to tell the model and the buttons to show
    (the closest names, when more than one person could be meant). The API decides who may add (admin or
    this project's manager) and which role they may give."""
    from runtime.entity_resolution.name_matching import NamedCandidate, resolve_name_hint
    from workflows.entities import Ambiguous, Resolved
    from workflows.role_words import normalize_role

    body["role"] = normalize_role(body.get("role"))
    response = await client.call("GET", path.removesuffix("/members") + "/member-candidates")
    if not response.ok:
        return f"refused: {_detail(response.body)}. Tell them plainly; do not prepare it.", []
    people = [NamedCandidate(entity_id=str(p.get("userId")), display_name=str(p.get("fullName") or ""))
              for p in response.body if isinstance(p, dict)] if isinstance(response.body, list) else []
    said = str(body.get("userId") or "").strip()
    if any(p.entity_id == said for p in people):
        return "", []
    outcome = resolve_name_hint(said, people)
    if isinstance(outcome, Ambiguous) and len(outcome.candidates) == 1 and said.casefold() in (
            outcome.candidates[0].display_name.casefold().split()):
        outcome = Resolved(entity_id=outcome.candidates[0].entity_id, display_name=outcome.candidates[0].display_name)
    if isinstance(outcome, Resolved):
        body["userId"] = outcome.entity_id
        return "", []
    if isinstance(outcome, Ambiguous):
        names = [c.display_name for c in outcome.candidates]
        return (f"{said!r} could be: {', '.join(names)}. Ask which one with `ask`, those names as options; "
                "nothing is prepared yet.", [n[:20] for n in names[:3]])
    return (f"no one called {said!r} is in the company. People join the company on the web dashboard (Team) "
            "first; say so plainly. Do not prepare it.", [])


UNIT_UNSETTLED = "unit_id is not a valid active unit"
#: Writes that change how other entries are read; saved first in one Save (after a new material, [217]).
SETTINGS_FIRST = frozenset({"set_unit_conversion", ALIAS_TOOL})
#: The name of the Save button, as every reply about a ready list says it (any language).
SAVE_WORD = "save"
#: WA-155: a reply that says the team (or "our team", in Malayalam / Hindi script too) was told / will look at it.
_TEAM = re.compile(r"\b(?:team|teamine|teamil|teaminu)\b|ടീ[മം]|टीम", re.IGNORECASE)
_TOLD = re.compile(r"\b(?:told|tell|inform\w*|pass\w*|forward\w*|report\w*|notif\w*|looking|look into|fix|ariyich\w*|"
                   r"paranj\w*|bata\w*|bhej\w*)\b|അറിയിച്ച|പറഞ്ഞ|बता|भेज", re.IGNORECASE)


def claims_team(text: str | None) -> bool:
    """The reply says the team was told (or is on it)."""
    return bool(text) and bool(_TEAM.search(text)) and bool(_TOLD.search(text))


def told(calls: list[Any]) -> bool:
    return any(getattr(c, "name", None) == TELL_THE_TEAM for c in calls)


def hint_reads(names: list[str]) -> str:
    """[247] ", a read tool exists: a, b" for the corrective retries; nothing when no tool matched."""
    return f". A read tool exists for this: {', '.join(names[:6])}" if names else ""


async def unit_from_summary(client: ApiClient, entry: PendingWrite) -> str:
    """A held line whose unit id cannot be settled (the model wrote something else) still says its
    unit in its words ("10 TMT steel bars"): try each word through the same resolver. "" = settled."""
    try:
        response = await client.call("GET", "/materials/units-of-measure")
    except Exception:  # noqa: BLE001
        return "no units"
    units = unit_rows(response.body) if response.ok else []
    for word in re.findall(r"[^\W\d_]+", entry.summary or ""):
        unit = resolve_unit(units, word)
        if unit is not None:
            entry.body["unit_id"] = str(unit["id"])
            return ""
    return "no unit in the words"


async def unit_buttons(client: ApiClient) -> list[str]:
    """Up to three unit buttons (nos / kg / tons first) for a unit the code could not settle, so the
    person taps one before Save instead of meeting a refusal after it."""
    try:
        response = await client.call("GET", "/materials/units-of-measure")
        units = unit_rows(response.body) if response.ok else []
    except Exception:  # noqa: BLE001
        return []
    codes = [str(u.get("code") or u.get("display_name")) for u in units]
    first = [c for want in ("nos", "kg", "tons") for c in codes if c.casefold() == want]
    return (first + [c for c in codes if c not in first])[:3]


async def confirm(client: ApiClient, pending: list[PendingWrite], names: tuple[str, ...] = ()) -> list[WriteResult]:
    """Send the held entries to the API, in order: a new material first, then settings (a unit conversion, an
    alias: often prepared after the lines they let through), then the rest ([217]). A line naming a new material
    (``new:<name>``) gets its id once it is saved; if adding it failed, the line says so and stays waiting. The
    API's own checks (access, validation, stock guard) decide; a refusal comes back as-is. Results come back in the
    order given."""
    def rank(i: int) -> int:
        return 0 if pending[i].tool == ADD_TOOL else 1 if pending[i].tool in SETTINGS_FIRST else 2

    created: dict[str, str] = {}  # the new material's name (alias_key) -> its id
    done: dict[int, WriteResult] = {}
    for i in sorted(range(len(pending)), key=rank):
        entry = pending[i]
        ref = _new_ref(entry)
        if ref is not None:
            material_id = created.get(alias_key(ref.removeprefix(NEW)))
            if material_id is None:
                done[i] = WriteResult(entry, 424, {"detail": f"{ref.removeprefix(NEW)} is not in the material list "
                                                             "yet (adding it did not save)"})
                continue
            entry = _with_material(entry, ref, material_id)
        done[i] = await _confirm_one(client, entry, names)
        if entry.tool == ADD_TOOL and (existing := _already_there(done[i])):
            # [246]: added elsewhere while the card waited (the dashboard, another message): the material is in the
            # list, so the add counts as done and its lines go on the one already there, never refused with it.
            done[i] = WriteResult(done[i].pending, 200, {"id": existing, "already_listed": True})
        if entry.tool == ADD_TOOL and done[i].ok and isinstance(done[i].body, dict) and done[i].body.get("id"):
            created[alias_key(str(entry.body.get("name") or ""))] = str(done[i].body["id"])
    return [done[i] for i in range(len(pending))]


def _already_there(result: WriteResult) -> str:
    """[246]: the id of the material an add found already listed (the API's 409 carries it), or ""."""
    body = result.body if isinstance(result.body, dict) else {}
    return str(body.get("existing_id") or "") if result.status == 409 else ""


def _new_ref(entry: PendingWrite) -> str | None:
    if entry.tool == ADD_TOOL:
        return None
    value = str(entry.body.get("material_id") or "")
    if value.startswith(NEW):
        return value
    m = re.match(r"^/materials/(new:[^/]+)", entry.path or "")
    return m.group(1) if m else None


def _with_material(entry: PendingWrite, ref: str, material_id: str) -> PendingWrite:
    body = {**entry.body, "material_id": material_id} if entry.body.get("material_id") == ref else entry.body
    return PendingWrite(tool=entry.tool, method=entry.method, path=entry.path.replace(ref, material_id),
                        params=entry.params, body=body, summary=entry.summary, idempotency_key=entry.idempotency_key)


def _place_names(places: Places | None) -> tuple[str, ...]:
    if places is None:
        return ()
    return tuple(n for _, n in places.projects) + tuple(n for _, n, _ in places.sites)


async def _confirm_one(client: ApiClient, entry: PendingWrite, names: tuple[str, ...] = ()) -> WriteResult:
    # [233]: a line held before the fill existed gets it now (same rule as when it is held).
    filled = fill_body(entry.tool, entry.body, entry.summary, names)
    if filled is not entry.body:
        entry = replace(entry, body=filled)
    if "unit_id" in entry.body:  # an entry held before this check, or an id gone stale
        problem = await settle_unit(client, entry.body)
        if problem:
            problem = await unit_from_summary(client, entry)  # "10 TMT steel bars": bars -> nos
        if problem:
            return WriteResult(entry, 422, {"detail": UNIT_UNSETTLED})
    response = await client.call(entry.method, entry.path, params=entry.params, json=entry.body,
                                 idempotency_key=entry.idempotency_key)
    if response.status == 422 and NARRATIVE_REFUSAL.search(_detail(response.body)):
        # [233]: the refusal names a field the code can fill: fill it and try once more in the same Save.
        retry = fill_body(entry.tool, {k: v for k, v in entry.body.items() if k != "narrative"}, entry.summary, names)
        if retry.get("narrative"):
            entry = replace(entry, body=retry, idempotency_key=new_idempotency_key())
            response = await client.call(entry.method, entry.path, params=entry.params, json=entry.body,
                                         idempotency_key=entry.idempotency_key)
    if response.status == 422 and entry.body.get("category_id") and CATEGORY_REFUSAL in _detail(response.body):
        # PRC-02: the category was switched off (or removed) while the line waited: the material is saved without it,
        # never refused with the delivery that waits on it. The card said the category; the result line says it did not.
        entry = replace(entry, body={k: v for k, v in entry.body.items() if k != "category_id"},
                        summary=without_category_note(entry.summary), idempotency_key=new_idempotency_key())
        response = await client.call(entry.method, entry.path, params=entry.params, json=entry.body,
                                     idempotency_key=entry.idempotency_key)
    if not response.ok and is_stock_unit_refusal(_detail(response.body)):
        return await _held_for_size(client, entry) or WriteResult(entry, response.status, response.body)
    return WriteResult(entry, response.status, response.body)


#: PRC-02: the API's refusal of a category that is not (or no longer) one of the company's switched-on ones
#: (``materials/router.py`` ``_require_category``).
CATEGORY_REFUSAL = "category_id is not one of this company's categories"


#: WA-197: the result of a line held for the admin's size (``WriteResult.body``): saved by itself when they answer.
HELD_FOR_SIZE = "held_for_size"


async def _held_for_size(client: ApiClient, entry: PendingWrite) -> WriteResult | None:
    """WA-197: Save on a line whose size nobody gave holds it for the company's admin (the WA-168 size request: asked
    once a day, it saves by itself when they answer), instead of refusing it and waiting on the person. None when the
    hold itself failed (the refusal then stands, and the line stays waiting)."""
    material_id, unit_id = str(entry.body.get("material_id") or ""), str(entry.body.get("unit_id") or "")
    if not (is_uuid(material_id) and is_uuid(unit_id)):
        return None
    try:
        response = await client.call("POST", "/materials/size-requests", json={
            "material_id": material_id, "from_unit_id": unit_id, "line_path": entry.path, "line_body": entry.body,
            "line_summary": SIZE_UNKNOWN.sub("", entry.summary), "line_key": entry.idempotency_key})
    except Exception:  # noqa: BLE001
        return None
    if not response.ok:
        return None
    return WriteResult(entry, 202, {HELD_FOR_SIZE: True})
