"""A question nobody answered is closed, not asked again.

Found live (24 Oct): an old unit question ("... The amount in cubic meters")
came back after an unrelated Save, because the short history the model reads
still ended its turn with the question and its buttons. A question is open
only while it is the last thing said and recent; any earlier one has been
answered or passed over, and a later one that nobody touched for a while has
gone cold. The model is shown such a turn without the question's options and
with a note that it is closed.
"""

from __future__ import annotations

from dataclasses import replace

from .prompt import Turn

#: A last question nobody answered for this long is closed.
STALE_SECONDS = 15 * 60

CLOSED = " (closed: not to be asked again unless the sender brings it up)"


def _open_question(reply: str) -> bool:
    before_options = reply.split("\n[options:", 1)[0].rstrip()
    return "\n[options:" in reply or before_options.endswith("?")


def close_stale_questions(turns: tuple[Turn, ...], now: float) -> tuple[Turn, ...]:
    """The turns, each question that is no longer open shown as closed."""
    out: list[Turn] = []
    for index, turn in enumerate(turns):
        last = index == len(turns) - 1
        cold = bool(turn.at) and now - turn.at > STALE_SECONDS
        reply = turn.assistant_reply
        if reply and _open_question(reply) and (not last or cold):
            reply = reply.split("\n[options:", 1)[0].rstrip() + CLOSED
            turn = replace(turn, assistant_reply=reply)
        out.append(turn)
    return tuple(out)
