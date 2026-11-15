"""What works, version 2 (SA-39 phase 1): conversations judged as intents, not one message at a time.

Version 1 (``admin/message_map.py``) files each message alone, so "ready on the card" counts as working even
when nobody ever tapped Save. Here a person's **conversation** (no silence longer than ``CONVERSATION_GAP``) is
split into **intents**: a message that starts something, plus the taps, answers and changes that continue it.
Each intent gets one **ending** and the **journeys** it went through, under a **capability** (the tool it was
about, named in plain words from the tool's own description).

Pure functions, no I/O, no AI. The input is what version 1 reads (message rows and their ``agent_api_turn``
traces); each message is still filed by ``message_map.classify`` first, and this module only links them.

How a message is linked (first rule that fits):

1. A Save or Cancel (the turn has ``save_results``/``saved``/``cancelled``), or a turn whose only calls change
   the card (``change_ready_entry``, ``drop_ready_entries``), continues the intents whose lines are on the card.
   The card is shared: one Save ends every intent waiting on it (a save line is matched to the intent that
   prepared that tool; the rest of the waiting intents end with the Save as a whole).
2. A button tap continues the latest intent with a card or a question waiting, else the latest intent.
3. A message just after Mesiri asked a question continues that intent when it calls no tool, or calls a tool
   the intent already called (the answer).
4. A message with no trace right after another with no trace continues it (sign-up, classic, taps the code
   answers: one intent, not ten).
5. Anything else starts an intent.

"Finished" means the record shows a save, a send or an answer, not that the answer was right.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

from admin.message_map import (
    BROKEN,
    FEEDBACK,
    OUTCOMES,
    _args,
    _call_verdict,
    _real_calls,
    _save_ok,
    _tools,
    classify,
    human,
    reason_kind,
    section_of,
)
from admin.review_export import CONVERSATION_GAP

# ── endings ──────────────────────────────────────────────────────────────────

FINISHED = "finished"
FINISHED_AFTER_QUESTION = "finished_after_question"
ABANDONED = "abandoned"
CANCELLED = "cancelled"
FAILED = "failed"
COMPLAINED = "complained"
UNSURE = "unsure"
OPEN = "open"

ENDINGS: dict[str, str] = {
    FINISHED: "Finished",
    FINISHED_AFTER_QUESTION: "Finished after a question",
    ABANDONED: "Left without Save",
    CANCELLED: "Cancelled",
    FAILED: "Failed",
    COMPLAINED: "The person complained or Mesiri can't do it yet",
    UNSURE: "Not sure",
    OPEN: "Still going",
}
#: An ending that counts as the person getting what they came for.
GOOD_ENDINGS = frozenset({FINISHED, FINISHED_AFTER_QUESTION})

# ── journeys (an intent can go through several) ──────────────────────────────

ONE_THING = "one_thing"
SEVERAL_THINGS = "several_things"
ASKED_ANSWERED = "asked_answered"
CHANGED_BEFORE_SAVE = "changed_before_save"
CORRECTED_AFTER_SAVE = "corrected_after_save"
MEMORY = "memory"
READ_ANSWER = "read_answer"
VOICE = "voice"
PHOTO = "photo"
CANCELLED_JOURNEY = "cancelled"

JOURNEYS: dict[str, str] = {
    ONE_THING: "One message, one thing, Save",
    SEVERAL_THINGS: "One message, several things",
    ASKED_ANSWERED: "Mesiri asks, the person answers",
    CHANGED_BEFORE_SAVE: "Changed before saving",
    CORRECTED_AFTER_SAVE: "Corrected after saving",
    MEMORY: "Follow-up that needs memory",
    READ_ANSWER: "A question answered from the records",
    VOICE: "Voice note",
    PHOTO: "Photo",
    CANCELLED_JOURNEY: "Cancelled",
}

#: Tools that only change what is already on the card.
CARD_TOOLS = frozenset({"change_ready_entry", "drop_ready_entries"})
#: Tools that change something already saved.
CORRECTION_TOOLS = frozenset({"correct_saved_entry", "correct_work"})
CORRECTION_PREFIX = "undo_"
#: How ``tell_the_team`` kinds end an intent.
COMPLAINT_KINDS = frozenset({"missing_feature", "bad_ux", "wrong_reply"})

#: Capability keys for an intent no tool was called for (the key starts with ``_``; never a tool name).
NO_TOOL = {"replied": "_talk", "unknown": "_no_record", "failed": "_failed", "no_reply": "_failed",
           "tapped": "_taps", "corrected": "_talk", "cancelled": "_card", "idea": "_talk"}
NO_TOOL_NAMES = {"_talk": "Talk with no tool used", "_no_record": "No record of what Mesiri did (sign-up, classic)",
                 "_failed": "No reply: failures and outages", "_taps": "Button taps the code answers",
                 "_card": "Save, change or cancel with nothing waiting"}

#: A capability's name is cut to this many characters.
NAME_CHARS = 80
#: The first message of an intent, as shown in a list.
MAX_TEXT_CHARS = 240


def capability_name(tool: str) -> str:
    """What a person can ask for, in plain words, from the tool's own description (the same line
    ``agent_api.tools.what_mesiri_does`` shows the model). A tool with no description: its name in words."""
    if tool in NO_TOOL_NAMES:
        return NO_TOOL_NAMES[tool]
    description = _tools().get(tool, ("", ""))[1]
    if not description:
        return human(tool)
    from agent_api.tools import plain_line

    line = plain_line(description, set(_tools()), limit=1000)
    # Write tools say "Prepare a receipt ...": the person asks for the receipt, the card is how it is kept.
    if line.startswith("Prepare "):
        line = line[len("Prepare "):]
    if len(line) > NAME_CHARS:  # cut on a whole word, and say so
        line = line[: line.rfind(" ", 0, NAME_CHARS)].rstrip(",;:( ") + " …"
    return (line[:1].upper() + line[1:]) or human(tool)


def _is_correction(tool: str) -> bool:
    return tool in CORRECTION_TOOLS or tool.startswith(CORRECTION_PREFIX)


def _saves(turn: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not turn:
        return []
    return [s for key in ("save_results", "saved") for s in turn.get(key) or [] if isinstance(s, dict)]


def _closes_card(turn: dict[str, Any] | None) -> bool:
    return bool(turn and (_saves(turn) or turn.get("cancelled") or turn.get("typed_cancel")
                          or turn.get("nothing_to_cancel")))


def _only_card_tools(turn: dict[str, Any] | None) -> bool:
    calls = _real_calls(turn) if turn else []
    return bool(calls) and all(c["tool"] in CARD_TOOLS for c in calls)


def _new_intent(n: int, message: dict[str, Any], conversation: str) -> dict[str, Any]:
    return {
        "id": f"{conversation}:{n}", "conversation": conversation, "sender": str(message.get("sender_wa_id")),
        "started_at": message["received_at"], "first_type": str(message.get("message_type") or "unknown"),
        "organization_name": message.get("organization_name"),
        "text": " ".join(str(message.get("body_text") or "").split())[:MAX_TEXT_CHARS],
        "sender_name": message.get("sender_name"), "sender_role": message.get("sender_role"),
        "messages": [], "tools": [], "ready_tools": [], "ready_lines": 0,
        "waiting": False, "question": False, "had_question": False, "changed": False, "memory": False,
        "saved": False, "save_failed": None, "cancelled": False, "complained": None, "failed": None,
        "answered": False, "corrected": False, "corrected_later": False, "first_outcome": None, "_first": None,
        "_first_turn": {}, "_first_message": {},
    }


def _apply(intent: dict[str, Any], message: dict[str, Any], turn: dict[str, Any] | None,
           filed: dict[str, Any] | None, *, continues: bool) -> None:
    """One message's effect on the intent it belongs to."""
    intent["messages"].append(str(message["id"]))
    if filed is None:
        return
    outcome = filed["outcome"]
    if intent["first_outcome"] is None:
        intent["first_outcome"] = outcome
        intent["_first"] = filed
        intent["_first_turn"] = turn or {}
        intent["_first_message"] = message
    calls = _real_calls(turn) if turn else []
    if continues and str(message.get("message_type")) != "interactive" and (
            intent["question"] or (calls and all(c["tool"] in CARD_TOOLS for c in calls))):
        intent["memory"] = True  # typed or spoken words that change the card or answer the question: they lean on it
    for c in calls:
        tool = c["tool"]
        if tool not in intent["tools"] and tool != FEEDBACK:
            intent["tools"].append(tool)
        verdict, said = _call_verdict(c)
        if tool in CARD_TOOLS:
            intent["changed"] = True
        elif _is_correction(tool) and verdict not in ("refused",):
            intent["corrected"] = True
        if verdict == "ready" and tool not in CARD_TOOLS:
            intent["waiting"] = True
            intent["ready_lines"] += 1
            if tool not in intent["ready_tools"]:
                intent["ready_tools"].append(tool)
        elif verdict == "asked":
            intent["question"] = intent["had_question"] = True
        elif verdict in ("answered", "sent", "done", "duplicate") and tool != FEEDBACK:
            intent["answered"] = True
        if tool == FEEDBACK and str(_args(c).get("kind")) in COMPLAINT_KINDS:
            intent["complained"] = str(_args(c).get("kind"))
    verdicts = [_call_verdict(c)[0] for c in calls if c["tool"] != FEEDBACK]
    if (turn and turn.get("asked")) or "asked" in verdicts:
        intent["question"] = intent["had_question"] = True
    elif any(v in ("ready", "answered", "sent", "done", "duplicate") for v in verdicts):
        intent["question"] = False  # the question was answered: the step went on
    if filed["state"] == BROKEN and outcome not in ("cannot_yet", "complaint", "save_failed"):
        intent["failed"] = filed["reason"] or OUTCOMES[outcome][1]
    elif intent["answered"] or intent["waiting"]:
        intent["failed"] = None  # recovered in a later step


def _close_with(intents: list[dict[str, Any]], turn: dict[str, Any]) -> None:
    """A Save or Cancel ends every intent waiting on the card (the card is shared)."""
    saves = _saves(turn)
    cancelled = bool(turn.get("cancelled") or turn.get("typed_cancel"))
    for intent in intents:
        if not intent["waiting"]:
            continue
        if saves:
            mine = [s for s in saves if s.get("tool") in intent["ready_tools"]] or saves
            bad = [s for s in mine if not _save_ok(s)]
            if bad:
                intent["save_failed"] = reason_kind(bad[0].get("reason") or bad[0].get("status")) or "Save failed"
            else:
                intent["saved"] = True
                intent["failed"] = None
            intent["waiting"] = intent["question"] = False
        elif cancelled:
            intent["cancelled"] = True
            intent["waiting"] = intent["question"] = False


def _ending(intent: dict[str, Any], *, still_going: bool) -> str:
    if intent["complained"]:
        return COMPLAINED
    if intent["save_failed"]:
        return FAILED
    # Something put on the card finishes only by a Save; a read in the same message does not finish it.
    if intent["saved"] or (intent["answered"] and not intent["ready_tools"] and not intent["failed"]):
        return FINISHED_AFTER_QUESTION if intent["had_question"] else FINISHED
    if intent["cancelled"]:
        return CANCELLED
    if intent["waiting"] or intent["question"]:
        return OPEN if still_going else ABANDONED
    if intent["failed"]:
        return FAILED
    return UNSURE


def _journeys(intent: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if intent["corrected"]:
        out.append(CORRECTED_AFTER_SAVE)
    if intent["changed"]:
        out.append(CHANGED_BEFORE_SAVE)
    if intent["had_question"]:
        out.append(ASKED_ANSWERED)
    if intent["ready_lines"] >= 2:
        out.append(SEVERAL_THINGS)
    elif intent["ready_lines"] == 1 and intent["saved"] and not (intent["changed"] or intent["had_question"]
                                                                  or intent["corrected"]):
        out.append(ONE_THING)
    if intent["memory"]:
        out.append(MEMORY)
    if intent["answered"] and not intent["ready_tools"] and not intent["corrected"]:
        out.append(READ_ANSWER)
    if intent["cancelled"]:
        out.append(CANCELLED_JOURNEY)
    if intent["first_type"] == "voice":
        out.append(VOICE)
    elif intent["first_type"] == "image":
        out.append(PHOTO)
    return out


def _capability(intent: dict[str, Any]) -> str:
    """The tool the intent was about: what it put on the card, else what it called, else how it ended."""
    if intent["ready_tools"]:
        return intent["ready_tools"][0]
    first = intent["_first"] or {}
    tool = first.get("tool")
    if tool and tool != FEEDBACK:
        return tool
    for tool in intent["tools"]:
        if tool not in CARD_TOOLS:
            return tool
    if tool == FEEDBACK:
        return FEEDBACK
    return NO_TOOL.get(str(intent["first_outcome"]), "_talk")


_CODE = re.compile(r"^[A-Z][A-Z0-9_]+$")


def plain_reason(reason: str) -> str:
    """An error code in words (``AI_UNAVAILABLE`` -> ``AI unavailable``); any other reason as it is."""
    if not _CODE.match(reason or ""):
        return reason
    words = reason.split("_")
    return " ".join([words[0] if len(words[0]) <= 3 else words[0].capitalize(), *(w.lower() for w in words[1:])])


def _reason(intent: dict[str, Any], ending: str) -> str:
    if ending == FAILED:
        return plain_reason(str(intent["save_failed"] or intent["failed"] or ""))
    if ending == COMPLAINED:
        return OUTCOMES["cannot_yet" if intent["complained"] == "missing_feature" else "complaint"][1]
    if ending == ABANDONED:
        return "A question was never answered" if intent["question"] and not intent["waiting"] else "The card was never saved"
    if ending == UNSURE:
        return _unsure_reason(intent)
    return ""


#: Why an intent is "not sure", in the order they are checked. Read from the record only (no word lists).
UNSURE_REASONS = {
    "no_record": "No trace of what Mesiri did (sign-up, classic, a tap the code answered)",
    "greeting": "A greeting the code answered",
    "idea": "An idea, passed to the team",
    "card_waiting": "Mesiri replied while a card was waiting, and nothing changed",
    "dropped_question": "Mesiri replied, and the code took a question out of the reply",
    "asked_back": "Mesiri replied with a question of its own and used no tool",
    "voice_unread": "A voice note with no words recorded, and no tool used",
    "photo": "A photo, and no tool used",
    "talk": "Mesiri replied without using a tool",
}


def _unsure_reason(intent: dict[str, Any]) -> str:
    turn, message = intent["_first_turn"], intent["_first_message"]
    if intent["first_outcome"] in ("unknown", "tapped"):
        key = "no_record"
    elif turn.get("handled") == "greeting":
        key = "greeting"
    elif intent["first_outcome"] == "idea":
        key = "idea"
    elif turn.get("pending") or turn.get("ready"):
        key = "card_waiting"
    elif turn.get("dropped_question"):
        key = "dropped_question"
    elif str(message.get("assistant_reply") or "").rstrip().endswith("?"):
        key = "asked_back"
    elif message.get("message_type") == "voice" and not str(message.get("body_text") or "").strip():
        key = "voice_unread"
    elif message.get("message_type") == "image":
        key = "photo"
    else:
        key = "talk"
    return UNSURE_REASONS[key]


def _conversations(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """One person, no silence longer than ``CONVERSATION_GAP``; oldest first."""
    rows = sorted(messages, key=lambda m: (str(m.get("sender_wa_id")), m["received_at"]))
    out: list[list[dict[str, Any]]] = []
    for m in rows:
        last = out[-1][-1] if out else None
        if (last is None or str(last.get("sender_wa_id")) != str(m.get("sender_wa_id"))
                or m["received_at"] - last["received_at"] > CONVERSATION_GAP):
            out.append([m])
        else:
            out[-1].append(m)
    return out


def build_intents(messages: list[dict[str, Any]], turns: dict[str, dict[str, Any]], *,
                  now: datetime) -> dict[str, Any]:
    """Every intent of the window, plus how the links were made: ``{intents, links}``.

    ``links`` counts the messages that continued an intent, the Save/Cancel taps that ended more than one
    intent at once (a shared card), and the continuing messages with no intent to continue (started one)."""
    intents: list[dict[str, Any]] = []
    links: Counter[str] = Counter()
    for conversation in _conversations(messages):
        key = str(conversation[0]["id"])
        mine: list[dict[str, Any]] = []
        last_had_turn = True
        for m in conversation:
            turn = turns.get(m["correlation_id"])
            turn = turn if isinstance(turn, dict) else None
            filed = classify(m, turn, now=now)
            tap = str(m.get("message_type")) == "interactive"
            waiting = [i for i in mine if i["waiting"]]
            latest = mine[-1] if mine else None
            target: dict[str, Any] | None = None
            if _closes_card(turn) or _only_card_tools(turn):
                target = waiting[-1] if waiting else latest
                if len(waiting) > 1 and _closes_card(turn):
                    links["shared_card"] += 1
            elif tap:
                target = next((i for i in reversed(mine) if i["waiting"] or i["question"]), latest)
            elif latest is not None and latest["question"] and turn is not None:
                calls = [c["tool"] for c in _real_calls(turn)]
                if not calls or any(t in latest["tools"] for t in calls):
                    target = latest
            elif turn is None and not last_had_turn and latest is not None:
                target = latest
            last_had_turn = turn is not None
            if target is None:
                if _closes_card(turn) or tap:
                    links["unlinked"] += 1
                target = _new_intent(len(mine), m, key)
                mine.append(target)
                _apply(target, m, turn, filed, continues=False)
            else:
                links["continued"] += 1
                _apply(target, m, turn, filed, continues=True)
            if turn is not None and _closes_card(turn):
                _close_with(mine, turn)
            if turn is not None and any(_is_correction(c["tool"]) for c in _real_calls(turn)):
                earlier = [i for i in mine if i is not target and i["saved"]]
                if earlier:
                    earlier[-1]["corrected_later"] = True
        still_going = now - conversation[-1]["received_at"] < CONVERSATION_GAP
        for intent in mine:
            if intent["first_outcome"] is None:
                continue  # every message of it is still being answered
            ending = _ending(intent, still_going=still_going)
            tool = _capability(intent)
            intents.append({
                "id": intent["id"], "conversation": intent["conversation"], "sender": intent["sender"],
                "started_at": intent["started_at"], "how": intent["first_type"],
                "company": intent["organization_name"], "messages": intent["messages"], "text": intent["text"],
                "sender_name": intent["sender_name"], "sender_role": intent["sender_role"],
                "capability": tool, "section": section_of(tool) if not tool.startswith("_") else _no_tool_section(tool),
                "tools": intent["tools"], "ending": ending, "reason": _reason(intent, ending),
                "journeys": _journeys(intent), "reached_card": bool(intent["ready_tools"]),
                "called_tool": bool(intent["tools"]), "corrected_later": intent["corrected_later"],
            })
    return {"intents": intents, "links": dict(links)}


def _no_tool_section(key: str) -> str:
    return {"_failed": "failed", "_taps": "taps", "_card": "card"}.get(key, "other")
