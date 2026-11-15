"""What works (SA-38): the messages people sent, grouped by what they were about and how they ended.

Pure functions, no I/O and no AI. Reads what is already recorded for every message: its
``inbound_messages`` row (the text, the reply, who sent it and how) and its v3 turn trace
(``journey_traces`` stage ``agent_api_turn``: the tools the assistant called and what each answered).

- **Section**: what the message was about. It is the first part of the API route of the tool the
  assistant used (``/materials/...`` -> Materials), read from ``agent_api.tools.ALLOWED``, so a tool
  added there is placed with no change here. The few tools the code handles itself (no route) are in
  ``CODE_TOOLS``.
- **Kind**: the tool (``record_receipt``) plus how the turn ended (ready on the card, saved, answered,
  refused and why, failed, passed to the team because Mesiri cannot do it yet).
- **State**: ``works``, ``broken`` or ``unsure``. It is a reading of the record, not a judgement of
  the reply: a wrong answer that used a tool and replied counts as "works" until the person says so
  (then the assistant's ``tell_the_team`` call puts it under broken).

The same typed message sent ten times is one example with ``times`` 10.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from admin.review_export import CONVERSATION_GAP

WORKS, BROKEN, UNSURE = "works", "broken", "unsure"

#: A message still unanswered after this long was never answered.
NO_REPLY_AFTER = timedelta(minutes=5)

MAX_EXAMPLES = 25
MAX_TEXT_CHARS = 600
MAX_REPLY_CHARS = 1500
MAX_THREAD_MESSAGES = 40

#: First part of a tool's API route -> (section key, name on the page).
SECTIONS: dict[str, tuple[str, str]] = {
    "materials": ("materials", "Materials and stock"),
    "procurement": ("procurement", "Material requests and orders"),
    "labour": ("labour", "Labour"),
    "progress": ("progress", "Work done and issues"),
    "timeline": ("reports", "Reports and what happened"),
    "dpr": ("reports", "Reports and what happened"),
    "reports": ("reports", "Reports and what happened"),
    "projects": ("projects", "Projects, sites and people"),
    "expenses": ("money", "Expenses and payments"),
    "finance": ("money", "Expenses and payments"),
    "billing": ("money", "Expenses and payments"),
    "cost": ("cost", "Cost and budget"),
    "equipment": ("machines", "Machines"),
    "subcontracts": ("subcontracts", "Subcontractors"),
    "approvals": ("approvals", "Approvals"),
    "me": ("settings", "The person's own settings"),
    # Not from a route:
    "card": ("card", "The card: save, change, cancel"),
    "feedback": ("feedback", "Told the team (can't do it yet, complaints, ideas)"),
    "help": ("help", "Help and links"),
    "taps": ("taps", "Button taps the code answers"),
    "failed": ("failed", "No reply: failures and outages"),
    "other": ("other", "Talk and everything else"),
}

#: Tools the code handles itself (they have no API route) -> the section they belong to.
CODE_TOOLS: dict[str, str] = {
    "tell_the_team": "feedback",
    "send_report": "reports",
    "send_stock_list": "materials",
    "save_ready_entries": "card",
    "change_ready_entry": "card",
    "drop_ready_entries": "card",
    "correct_saved_entry": "card",
    "explain_mesiri": "help",
    "web_link": "help",
}
#: Calls that are only plumbing: never what a message was about.
PLUMBING = frozenset({"open_tools", "ask"})
FEEDBACK = "tell_the_team"

OUTCOMES: dict[str, tuple[str, str]] = {
    "saved": (WORKS, "Saved"),
    "ready": (WORKS, "Ready on the card, waiting for Save"),
    "sent": (WORKS, "Sent"),
    "answered": (WORKS, "Answered from the records"),
    "done": (WORKS, "Done"),
    "asked": (WORKS, "Asked one question first"),
    "duplicate": (WORKS, "Already saved earlier, not saved twice"),
    "tapped": (WORKS, "Tap answered"),
    "failed": (BROKEN, "Failed"),
    "no_reply": (BROKEN, "Never answered"),
    "save_failed": (BROKEN, "Save failed"),
    "refused": (BROKEN, "Could not do it"),
    "cannot_yet": (BROKEN, "Mesiri can't do this yet (passed to the team)"),
    "complaint": (BROKEN, "The person said the reply was bad or wrong"),
    "corrected": (BROKEN, "Did nothing, and the code had to correct the reply"),
    "idea": (UNSURE, "An idea, passed to the team"),
    "cancelled": (UNSURE, "The person cancelled"),
    "replied": (UNSURE, "Replied without using a tool"),
    "unknown": (UNSURE, "No record of what Mesiri did"),
}
_FEEDBACK_OUTCOME = {"missing_feature": "cannot_yet", "bad_ux": "complaint", "wrong_reply": "complaint", "idea": "idea"}
#: When several calls of a turn went well, the one the turn is filed under.
_GOOD_ORDER = ("ready", "sent", "answered", "done", "duplicate")

_tool_table: dict[str, tuple[str, str]] | None = None


def _tools() -> dict[str, tuple[str, str]]:
    """tool name -> (route prefix, what it is for), from the assistant's own tool table."""
    global _tool_table
    if _tool_table is None:
        from agent_api.tools import ALLOWED

        _tool_table = {a.name: (a.path.strip("/").split("/")[0], a.description) for a in ALLOWED}
    return _tool_table


def section_of(tool: str | None) -> str:
    """The section key a tool belongs to (``other`` when unknown)."""
    if not tool:
        return "other"
    prefix = CODE_TOOLS.get(tool) or _tools().get(tool, ("other", ""))[0]
    return SECTIONS.get(prefix, SECTIONS["other"])[0]


def _label(section: str) -> str:
    return next((label for key, label in SECTIONS.values() if key == section), section)


def human(tool: str) -> str:
    """``record_receipt`` -> ``Record receipt``."""
    words = tool.replace("_", " ").strip()
    return words[:1].upper() + words[1:]


# A quoted name; an apostrophe inside a word ("company's") does not open or close one.
_QUOTED = re.compile(r"(?<!\w)'[^']*'(?!\w)|\"[^\"]*\"|\*[^*]*\*")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f-]{22}\b")
_NUMBER = re.compile(r"\d+(?:[.:,]\d+)*")
_SENTENCE_END = re.compile(r"(?<=[.;?!])\s")


def reason_kind(text: Any) -> str:
    """A refusal with its particulars taken out, so the same refusal about two materials is one kind:
    "'TMT bars' is not in the company's materials. Nothing..." -> "… is not in the company's materials."."""
    out = str(text or "").strip()
    if out.startswith("the API answered"):
        return out
    out = _QUOTED.sub("…", out)
    out = _NUMBER.sub("N", _UUID.sub("…", out))
    return _SENTENCE_END.split(out, maxsplit=1)[0][:110].strip()


def _call_verdict(call: dict[str, Any]) -> tuple[str, str]:
    """How one tool call ended: (ready|sent|answered|done|duplicate|asked|refused, the status or refusal in
    its own words). A refusal that is a question for the person ("Which site is this for? ...") is ``asked``."""
    result = call.get("result") if isinstance(call.get("result"), dict) else {}
    if result.get("error"):
        said = str(result["error"])
        if said.lower().startswith("already saved"):
            return "duplicate", said
        return ("asked" if reason_kind(said).endswith("?") else "refused"), said
    status = result.get("status")
    if isinstance(status, int) and not isinstance(status, bool):
        return ("answered", str(status)) if status < 400 else ("refused", f"the API answered {status}")
    said = str(status or "")
    low = said.lower()
    if low.startswith("held"):
        return "asked", said
    if low.startswith("already saved"):
        return "duplicate", said
    if low == "unavailable" or low.startswith(("not prepared", "no link yet")):
        return "refused", said
    if low.startswith(("sent", "already sent")):
        return "sent", said
    if "not saved" in low and not low.startswith("not saved"):
        return "ready", said
    return "done", said


def _save_ok(save: dict[str, Any]) -> bool:
    status = save.get("status")
    return isinstance(status, int) and status < 400 and not save.get("reason")


def _real_calls(turn: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in turn.get("calls") or [] if isinstance(c, dict) and c.get("tool") and c["tool"] not in PLUMBING]


def _args(call: dict[str, Any]) -> dict[str, Any]:
    args = call.get("args") or call.get("arguments")
    return args if isinstance(args, dict) else {}


def classify(message: dict[str, Any], turn: dict[str, Any] | None, *, now: datetime) -> dict[str, Any] | None:
    """Where one message is filed: ``{section, tool, outcome, state, reason, note}``.

    None for a message that is still being answered (nothing to say about it yet)."""

    def filed(outcome: str, tool: str | None = None, *, section: str | None = None, reason: str = "",
              note: str = "") -> dict[str, Any]:
        return {"section": section or section_of(tool), "tool": tool, "outcome": outcome,
                "state": OUTCOMES[outcome][0], "reason": reason, "note": note}

    turn = turn if isinstance(turn, dict) else None
    calls = _real_calls(turn) if turn else []
    first_tool = calls[0]["tool"] if calls else None
    status = message.get("processing_status")
    reply = (message.get("assistant_reply") or "").strip()

    if status == "failed" or (turn and (turn.get("error") or turn.get("outage"))):
        why = message.get("error_code") or ("AI outage" if turn and turn.get("outage") else "error in the turn")
        return filed("failed", first_tool, section="failed", reason=str(why))
    if status == "pending" and not reply:
        if now - message["received_at"] < NO_REPLY_AFTER:
            return None
        return filed("no_reply", first_tool, section="failed")

    if turn is None:
        if message.get("message_type") == "interactive" and reply:
            return filed("tapped", section="taps")
        return filed("unknown" if reply else "no_reply", section="other" if reply else "failed")

    saves = [s for key in ("save_results", "saved") for s in turn.get(key) or [] if isinstance(s, dict)]
    bad = [s for s in saves if not _save_ok(s)]
    if bad:
        return filed("save_failed", bad[0].get("tool"), reason=reason_kind(bad[0].get("reason") or bad[0].get("status")),
                     note=str(bad[0].get("reason") or "")[:300])
    if saves:
        return filed("saved", saves[0].get("tool"))

    feedback = [c for c in calls if c["tool"] == FEEDBACK]
    if feedback:
        args = _args(feedback[0])
        outcome = _FEEDBACK_OUTCOME.get(str(args.get("kind")), "idea")
        if OUTCOMES[outcome][0] == BROKEN or len(feedback) == len(calls):
            note = " · ".join(str(args[k]) for k in ("about", "why") if args.get(k))
            return filed(outcome, FEEDBACK, note=note[:300])
        calls = [c for c in calls if c["tool"] != FEEDBACK]
    if turn.get("cancelled") or turn.get("nothing_to_cancel"):
        return filed("cancelled", section="card")

    verdicts = [(c["tool"], *_call_verdict(c)) for c in calls]
    for wanted in _GOOD_ORDER:
        for tool, verdict, _said in verdicts:
            if verdict == wanted:
                return filed(wanted, tool)
    if turn.get("asked") or any(v == "asked" for _t, v, _s in verdicts):
        return filed("asked", first_tool)
    for tool, verdict, said in verdicts:
        if verdict == "refused":
            return filed("refused", tool, reason=reason_kind(said), note=said[:300])
    if turn.get("ready") or turn.get("pending"):
        return filed("ready", section="card")  # nothing new prepared: the card from before is still waiting
    if turn.get("reply_fixed"):
        return filed("corrected", first_tool, section=None if first_tool else "other")
    if message.get("message_type") == "interactive" and reply:
        return filed("tapped", section="taps")
    return filed("replied" if reply else "no_reply", section="other" if reply else "failed")


def _cut(text: Any, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + " …"


def _same_text(text: str | None) -> str:
    return " ".join((text or "").casefold().split())


def _phone_tail(wa_id: Any) -> str:
    digits = re.sub(r"\D", "", str(wa_id or ""))
    return digits[-4:]


def build_map(messages: list[dict[str, Any]], turns: dict[str, dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    """Sections -> kinds of message -> examples, from message rows (any order) and their turns by correlation id."""
    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    totals: Counter[str] = Counter()
    people: set[str] = set()

    for m in sorted(messages, key=lambda row: row["received_at"], reverse=True):
        filed = classify(m, turns.get(m["correlation_id"]), now=now)
        if filed is None:
            continue
        totals[filed["state"]] += 1
        people.add(str(m.get("sender_wa_id")))
        key = (filed["section"], filed["tool"] or "", filed["outcome"], filed["reason"])
        group = groups.get(key)
        if group is None:
            tool = filed["tool"]
            group = groups[key] = {
                "key": "|".join(key), "section": filed["section"], "state": filed["state"], "tool": tool,
                "title": human(tool) if tool else OUTCOMES[filed["outcome"]][1],
                "hint": _tools().get(tool, ("", ""))[1] if tool else "",
                "outcome": filed["outcome"], "outcome_label": OUTCOMES[filed["outcome"]][1],
                "reason": filed["reason"], "count": 0, "last_at": m["received_at"],
                "how": Counter(), "_people": set(), "_companies": Counter(), "_examples": {},
            }
        group["count"] += 1
        group["how"][str(m.get("message_type") or "unknown")] += 1
        group["_people"].add(str(m.get("sender_wa_id")))
        if m.get("organization_name"):
            group["_companies"][m["organization_name"]] += 1
        # A tap's text is its button ("Save"): every tap is its own example. Typed words are one example each.
        same = (str(m["id"]) if m.get("message_type") == "interactive"
                else _same_text(m.get("body_text")) or f"({m.get('message_type')})")
        example = group["_examples"].get(same)
        if example is not None:
            example["times"] += 1
        elif len(group["_examples"]) < MAX_EXAMPLES:
            group["_examples"][same] = {
                "id": str(m["id"]), "correlation_id": m["correlation_id"],
                "text": _cut(m.get("body_text"), MAX_TEXT_CHARS), "reply": _cut(m.get("assistant_reply"), MAX_REPLY_CHARS),
                "at": m["received_at"], "type": m.get("message_type"),
                "sender": m.get("sender_name"), "role": m.get("sender_role"), "company": m.get("organization_name"),
                "phone_tail": _phone_tail(m.get("sender_wa_id")), "note": filed["note"], "times": 1,
            }

    sections: dict[str, dict[str, Any]] = {}
    for group in sorted(groups.values(), key=lambda g: -g["count"]):
        section = sections.setdefault(group["section"], {
            "key": group["section"], "label": _label(group["section"]), WORKS: 0, BROKEN: 0, UNSURE: 0, "groups": []})
        section[group["state"]] += group["count"]
        group["people"] = len(group.pop("_people"))
        group["companies"] = [name for name, _n in group.pop("_companies").most_common(6)]
        group["examples"] = list(group.pop("_examples").values())
        group["how"] = dict(group["how"].most_common())
        section["groups"].append(group)
    ordered = sorted(sections.values(), key=lambda s: -(s[WORKS] + s[BROKEN] + s[UNSURE]))
    return {
        "totals": {"messages": sum(totals.values()), WORKS: totals[WORKS], BROKEN: totals[BROKEN],
                   UNSURE: totals[UNSURE], "people": len(people)},
        "sections": ordered,
    }


def _did(turn: dict[str, Any] | None) -> list[str]:
    """What the assistant did in a turn, one short line per step, for under the reply."""
    if not turn:
        return []
    lines = [f"{human(c['tool'])}: {_cut(_call_verdict(c)[1], 90) or 'done'}" for c in _real_calls(turn)]
    for save in (s for key in ("save_results", "saved") for s in turn.get(key) or [] if isinstance(s, dict)):
        mark = "Saved" if _save_ok(save) else "NOT saved"
        lines.append(f"{mark}: {_cut(save.get('summary') or human(str(save.get('tool') or 'entry')), 90)}"
                     + ("" if _save_ok(save) else f" ({_cut(save.get('reason'), 120)})"))
    if turn.get("asked"):
        lines.append(f"Asked: {_cut(turn['asked'], 120)}")
    # Two deliveries in one message are two identical lines: say it once, with the count.
    return [line if n == 1 else f"{line} (×{n})" for line, n in Counter(lines).items()][:8]


def build_thread(messages: list[dict[str, Any]], turns: dict[str, dict[str, Any]], *, message_id: str,
                 now: datetime) -> list[dict[str, Any]]:
    """The conversation one message was part of, oldest first, for the WhatsApp view: this person's messages
    around it with no silence longer than ``CONVERSATION_GAP`` between two of them."""
    rows = sorted(messages, key=lambda row: row["received_at"])
    at = next((i for i, row in enumerate(rows) if str(row["id"]) == str(message_id)), None)
    if at is None:
        return []
    start = end = at
    while start > 0 and rows[start]["received_at"] - rows[start - 1]["received_at"] <= CONVERSATION_GAP:
        start -= 1
    while end + 1 < len(rows) and rows[end + 1]["received_at"] - rows[end]["received_at"] <= CONVERSATION_GAP:
        end += 1
    half = MAX_THREAD_MESSAGES // 2
    start, end = max(start, at - half), min(end, at + half)

    thread = []
    for row in rows[start:end + 1]:
        turn = turns.get(row["correlation_id"])
        filed = classify(row, turn, now=now)
        thread.append({
            "id": str(row["id"]), "correlation_id": row["correlation_id"], "at": row["received_at"],
            "replied_at": row.get("processed_at"), "type": row.get("message_type"),
            "text": row.get("body_text") or "", "reply": row.get("assistant_reply") or "",
            "state": filed["state"] if filed else None,
            "outcome_label": OUTCOMES[filed["outcome"]][1] if filed else "Still answering",
            "reason": filed["reason"] if filed else "", "did": _did(turn),
            "selected": str(row["id"]) == str(message_id),
        })
    return thread
