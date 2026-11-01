"""The general skill's tools.

Request 194: taking back or correcting something already SAVED, whatever its module. Today's
tools under their own names and specs (runtime/agent/tools.py): a removal is confirmed with a
Yes card first; a change of a saved entry is a Change line saved by tap. Nothing is removed or
changed before the tap.

TM-18 (Ilan, 1 Nov: "if a feature is not there it should understand, add it, and come back"):
``tell_the_team`` is v2's own tool (no toolbox, no write path, no table). It records nothing by
itself: the call is in the turn's ``agent_v2_live`` trace (``journey_traces``), which the team
bot's production watch reads with one free SELECT, and the bot builds the change and tells the
person when it is live. Its result tells the model what to say: it is not built yet, it has been
passed on, and (for bad UX with no reason given) one short question about what was bad.
"""

from __future__ import annotations

from typing import Any

from mesiri_ai.models import ToolSpec
from runtime.agent import tools as classic

WRITE_TOOLS = frozenset({classic.CHANGE_OR_UNDO, classic.UNDO_LAST})
READ_TOOLS: frozenset[str] = frozenset()

TELL_THE_TEAM = "tell_the_team"
#: What the feedback is about. The watch reads these words from the trace: keep them stable.
FEEDBACK_KINDS = ("missing_feature", "bad_ux", "wrong_reply", "idea")

_DESCRIPTION = (
    "Pass feedback to the team that builds Mesiri; they build or fix it and Mesiri tells this person when it works. "
    "Call it when: (1) they ask for something Mesiri cannot do here yet (adding a member, "
    "any feature you have no tool for): kind missing_feature; (2) they say a reply, the buttons, the card or the way "
    "you answered was bad, confusing, too long, annoying ('bad UX', 'this is confusing', 'too many buttons', 'ithu "
    "sheriyalla', 'enthaanu ithu'): kind bad_ux; (3) they say a reply was wrong in a way you cannot fix now: kind "
    "wrong_reply; (4) they suggest an improvement: kind idea. Also call it again when they answer your question about "
    "WHY something was bad: same kind, with `why`. Saves nothing and changes no record; do every other part of the "
    "message with its own tools as well."
)

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(FEEDBACK_KINDS)},
        "about": {
            "type": "string",
            "description": (
                "In English, one line: what they wanted, or what was bad and in which reply ('add a member from "
                "WhatsApp', 'the Save / Cancel buttons under the stock answer')."
            ),
        },
        "why": {
            "type": "string",
            "description": "In English: their reason, in their own terms, when they gave one. Leave out when they did not.",
        },
    },
    "required": ["kind", "about"],
}


def specs() -> list[ToolSpec]:
    """v2's own general tools (handled in agents/main.py, never by the toolbox)."""
    return [ToolSpec(name=TELL_THE_TEAM, description=_DESCRIPTION, parameters=_PARAMETERS)]


def feedback_instruction(args: dict[str, Any]) -> str:
    """What the model is told after ``tell_the_team``: the words of the reply, never a template."""
    kind = str(args.get("kind") or "")
    has_reason = bool(str(args.get("why") or "").strip())
    if kind == "missing_feature":
        return (
            "Passed to the team. In your reply say plainly, in one or two short sentences, that Mesiri cannot do this "
            "here yet, that you have passed it to the team to build, and that you will message them here when it "
            "works. If there is a way to do it today (the web dashboard), name it in a few words as the way for now. "
            "Do every other part of their message as usual."
        )
    if kind == "bad_ux" and not has_reason:
        return (
            "Passed to the team. In your reply: sorry in a few words, say you have passed it on to be fixed, and ask "
            "ONE short question: what was not good about it (the words, the buttons, too long, the wrong thing, or "
            "something else). Do not repeat the reply they complained about."
        )
    return (
        "Passed to the team. Thank them in a few words and say you have passed it on to be fixed; you will message "
        "them here when it is better. Do not repeat the reply they complained about; do what they actually asked."
    )
