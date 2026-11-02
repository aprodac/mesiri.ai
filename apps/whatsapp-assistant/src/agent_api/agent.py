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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from agent_api.feedback import TELL_THE_TEAM, feedback_instruction
from agent_api.feedback import specs as feedback_specs
from agent_api.links import WEB_LINK, build_link
from agent_api.links import spec as web_link_spec
from mesiri_ai.models import ChatMessage, ToolOutcome, ToolSpec

from .client import ApiClient, new_idempotency_key
from .tools import CONFIRM_ARG, ApiTool
from .units import resolve_unit, unit_choices, unit_rows

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


SAVE_READY = "save_ready_entries"
#: The language of the person's message (``runtime.agent.wording.language_of``) as told to the model.
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
_ASK_TOOL = ToolSpec(name=ASK, description=(
    "Ask the person ONE short question you cannot work out yourself. With options (2-3 short "
    "choices) they answer with one tap. Put the question in your reply too."), parameters={
    "type": "object", "required": ["question"],
    "properties": {"question": {"type": "string"},
                   "options": {"type": "array", "items": {"type": "string"}, "description": "2-3 short choices"}},
})
DROP_READY = "drop_ready_entries"
_NUMBERS = {
    "type": "object",
    "properties": {"numbers": {"type": "array", "items": {"type": "integer"},
                               "description": "The entry numbers from the ready list; leave out for all."}},
}
_READY_TOOLS = (
    ToolSpec(name=SAVE_READY, parameters=_NUMBERS, description=(
        "Save entries from the ready list. Only when the person clearly says to save or confirm them.")),
    ToolSpec(name=DROP_READY, parameters=_NUMBERS, description=(
        "Remove entries from the ready list (the person cancels them, or they are being corrected: "
        "drop the old one and prepare the corrected one).")),
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
        prompt = f"{self._sop}\n{who}Today is {today.isoformat()} ({today.strftime('%A')})."
        if facts:
            prompt += f"\n\n{facts}"
        if ready:
            listed = "\n".join(f"{i}. {e.summary}" for i, e in enumerate(ready, 1))
            prompt += f"\n\nReady, waiting for the person's confirmation (not saved):\n{listed}"
        return prompt

    async def run(self, client: ApiClient, text: str, *, history: list[ChatMessage] | None = None,
                  ready: list[PendingWrite] | None = None, sender_name: str = "",
                  timezone: str = "Asia/Kolkata", correlation_id: str | None = None,
                  facts: str = "", photo_key: str | None = None, language: str | None = None,
                  actions: dict[str, tuple[ToolSpec, Any]] | None = None,
                  channel: str = TEXT_CHANNEL) -> ApiTurn:
        """``facts``: what the agent starts from (projects, sites, materials, units), read
        before the model runs. ``photo_key``: the photo this message carried; a write that
        takes a photo (an expense) gets it attached by the code. ``actions``: tools the caller
        runs itself, by name: ``(spec, async handler(arguments) -> content)``. ``channel``: how the
        message came (``whatsapp_text`` | ``whatsapp_voice`` | ``whatsapp_image``), recorded on the entry."""
        channel = channel if channel in CHANNELS else TEXT_CHANNEL
        today = dt.datetime.now(ZoneInfo(timezone or "Asia/Kolkata")).date()
        waiting: list[PendingWrite | None] = list(ready or [])  # None = saved or dropped this turn
        new: list[PendingWrite] = []
        saved: list[WriteResult] = []
        asked: dict[str, Any] = {}
        acted: list[str] = []
        unit_ask: list[str] = []  # buttons for a unit nobody could settle (cleared once a line settles)
        links: list[str] = []  # WA-141: dashboard links built this turn

        def chosen(arguments: dict) -> list[int]:
            numbers = arguments.get("numbers") or range(1, len(waiting) + 1)
            return [n for n in (int(x) for x in numbers) if 1 <= n <= len(waiting) and waiting[n - 1] is not None]

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
                results = await confirm(client, [waiting[n - 1] for n in numbers])  # type: ignore[misc]
                saved.extend(results)
                for n in numbers:
                    waiting[n - 1] = None
                return ToolOutcome(content={"results": [
                    {"entry": n, "summary": r.pending.summary, "saved": r.ok,
                     **({} if r.ok else {"refused": _detail(r.body)})} for n, r in zip(numbers, results, strict=True)]})
            if name == DROP_READY and waiting:
                numbers = chosen(arguments)
                for n in numbers:
                    waiting[n - 1] = None
                return ToolOutcome(content={"dropped": numbers})
            if actions and name in actions:
                acted.append(name)
                return ToolOutcome(content=await actions[name][1](arguments))
            tool = self._tools.get(name)
            if tool is None:
                return ToolOutcome(content={"error": f"no tool named {name}"})
            missing = [r for r in tool.required if arguments.get(r) in (None, "")]
            if missing:
                return ToolOutcome(content={"error": f"missing: {', '.join(missing)}"})
            path = tool.path
            for p in tool.path_params:
                path = path.replace("{" + p + "}", str(arguments[p]))
            params = {q: arguments[q] for q in tool.query_params if arguments.get(q) not in (None, "")}
            body = {f: arguments[f] for f in tool.body_fields if f in arguments}
            body.update({k: (channel if v == TEXT_CHANNEL else v) for k, v in tool.fixed})
            if photo_key and tool.is_write and PHOTO_FIELD in tool.hidden and PHOTO_FIELD not in body:
                body[PHOTO_FIELD] = photo_key
            if tool.is_write and "unit_id" in tool.body_fields:
                problem = await settle_unit(client, body)
                if problem:
                    unit_ask[:] = await unit_buttons(client)
                    return ToolOutcome(content={"error": problem})
                unit_ask.clear()
            if tool.is_write:
                entry = PendingWrite(
                    tool=name, method=tool.method, path=path, params=params, body=body,
                    summary=str(arguments.get(CONFIRM_ARG) or "").strip(),
                    idempotency_key=new_idempotency_key(),
                )
                new.append(entry)
                return ToolOutcome(content={
                    "status": "ready, NOT saved",
                    "note": "It saves when the person confirms. Do not say it is saved.",
                })
            response = await client.call(tool.method, path, params=params)
            content = json.dumps(response.body, default=str, ensure_ascii=False)
            if len(content) > READ_LIMIT:
                content = content[:READ_LIMIT] + " ...(cut)"
            return ToolOutcome(content={"status": response.status, "result": content})

        specs = [t.spec for t in self._tools.values()] + [_ASK_TOOL, *feedback_specs(), web_link_spec()] + (
            list(_READY_TOOLS) if waiting else [])
        specs += [spec for spec, _ in (actions or {}).values()]
        system = self.system_prompt(sender_name=sender_name, today=today, ready=list(ready or []), facts=facts)
        if language in LANGUAGE_LINES:
            # Decided by the code from their words (the model mixed scripts on 1 Nov).
            system += f"\n\nThis message is in {LANGUAGE_LINES[language]}. Reply in exactly that."
        messages = [*(history or []), ChatMessage(role="user", text=text)]
        extra = {"capability": self._capability} if self._capability and _takes(self._provider, "capability") else {}

        def nothing_done() -> bool:
            return not new and not saved and not asked and not acted and len(waiting) == len(ready or [])

        async def ask_model(msgs: list[ChatMessage]) -> Any:
            return await self._provider.run_tools(
                system, msgs, specs, handler, max_steps=self._max_steps, timeout_seconds=self._timeout,
                correlation_id=correlation_id, **extra)

        try:
            result = await ask_model(messages)
        except Exception:
            # A model error before anything was prepared or saved: one more try (compare run of
            # 1 Nov: one expense message failed on the first call). After an effect, never again.
            if not nothing_done():
                raise
            result = await ask_model(messages)
        if not (result.text or "").strip() and not new and not asked and not saved and not acted:
            # It looked something up and said nothing ("OK."): ask once for the answer in words.
            again = await ask_model([*messages, ChatMessage(role="model", text="(looked it up)"),
                                     ChatMessage(role="user", text="(answer my message now, in words)")])
            result = again.model_copy(update={"calls": [*result.calls, *again.calls]})
        calls = [{"tool": c.name, "arguments": c.arguments, "result": c.outcome.content if c.outcome else None}
                 for c in result.calls]
        still = [e for e in waiting if e is not None]
        options = asked.get("options", []) or (unit_ask if not asked else [])
        reply = (result.text or "").strip()
        missing = [u for u in dict.fromkeys(links) if u not in reply]
        if missing:  # WA-141: a link the code built always reaches the person, even if the model left it out
            reply = "\n".join([reply, *missing]).strip()
        return ApiTurn(reply=reply, pending=still + new, saved=saved, calls=calls,
                       stop_reason=result.stop_reason, question=asked.get("question", ""), options=options)


def _takes(provider: Any, name: str) -> bool:
    """Whether ``provider.run_tools`` accepts ``name``: the model router takes ``capability``
    (the control-panel row), a single provider (Gemini) does not."""
    import inspect

    try:
        params = inspect.signature(provider.run_tools).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


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


async def settle_unit(client: ApiClient, body: dict[str, Any]) -> str:
    """Make ``body["unit_id"]`` the id of an active unit (it may be "bags", a code or a wrong id).
    Returns "" when it is settled, else what to tell the model (it then asks one question)."""
    try:
        response = await client.call("GET", "/materials/units-of-measure")
    except Exception:  # noqa: BLE001 -- the API's own check still decides
        return ""
    units = unit_rows(response.body) if response.ok else []
    if not units:
        return ""
    unit = resolve_unit(units, body.get("unit_id"))
    if unit is None:
        return (f"unit_id {str(body.get('unit_id'))[:40]!r} is not one of the company's units. Use the id of one of: "
                f"{unit_choices(units)}. If you cannot tell which unit they mean, ask them with `ask` and those units as options.")
    body["unit_id"] = str(unit["id"])
    return ""


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


async def confirm(client: ApiClient, pending: list[PendingWrite]) -> list[WriteResult]:
    """Send the held entries to the API, in order. The API's own checks
    (access, validation, stock guard) decide; a refusal comes back as-is."""
    results: list[WriteResult] = []
    for entry in pending:
        if "unit_id" in entry.body:  # an entry held before this check, or an id gone stale
            problem = await settle_unit(client, entry.body)
            if problem:
                results.append(WriteResult(entry, 422, {"detail": "unit_id is not a valid active unit"}))
                continue
        response = await client.call(entry.method, entry.path, params=entry.params, json=entry.body,
                                     idempotency_key=entry.idempotency_key)
        results.append(WriteResult(entry, response.status, response.body))
    return results
