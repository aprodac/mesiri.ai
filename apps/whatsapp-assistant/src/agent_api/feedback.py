"""``tell_the_team``: feedback passed to the team that builds Mesiri (TM-18, WA-126).

Moved from v2's general skill when v2 was retired (WA-134); unchanged. It records nothing by
itself: the call is in the turn's ``agent_api_turn`` trace (``journey_traces``), which the team
bot's production watch reads with one free SELECT, and the bot builds the change and tells the
person when it is live. Its result tells the model what to say: it is not built yet, it has been
passed on, and (for bad UX with no reason given) one short question about what was bad.
"""

from __future__ import annotations

from typing import Any

from mesiri_ai.models import ToolSpec

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
    """The feedback tool (handled by ``agent.ApiAgent``; it calls no API route)."""
    return [ToolSpec(name=TELL_THE_TEAM, description=_DESCRIPTION, parameters=_PARAMETERS)]


def feedback_instruction(args: dict[str, Any]) -> str:
    """What the model is told after ``tell_the_team``: the words of the reply, never a template."""
    return f"{_instruction(args)} {_SCRIPT_RULE}"


#: The "told the team" sentence slipped into Malayalam script for a person who chose Manglish (4 Nov, [231]).
_SCRIPT_RULE = ("Write this in the language and script of the system line above, never copying the script of earlier "
                "replies: for Manglish or Hinglish, Latin letters only (\"Team-ine ariyichittund\"). Do not write a Ref "
                "number: the code adds it.")


def _instruction(args: dict[str, Any]) -> str:
    kind = str(args.get("kind") or "")
    has_reason = bool(str(args.get("why") or "").strip())
    if kind == "missing_feature":
        return (
            "Passed to the team. In your reply say plainly, in one or two short sentences, that Mesiri cannot do this "
            "here yet, that you have passed it to the team to build, and that you will message them here when it "
            "works. If there is a way to do it today (the web dashboard), name it in a few words as the way for now "
            "(with `web_link` when there is a page for it). If what they want could mean two different things, ask "
            "ONE short question with `ask` and 2-3 options, and pass their answer on with `tell_the_team` again "
            "(same kind, with `why`), so the team builds the right thing. Do every other part of their message as usual."
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
