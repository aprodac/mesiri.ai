"""One reply per site message, in the form that fits (request [45]).

While a message is handled, several things can want to be said to the sender:
what was saved, a question the record needs (promote these workers?), the
team-photo offer, the project/site setup offer, today's setup question. Sent
one by one that is a wall of messages for a person standing on a site. This
module takes the main text and every candidate follow-up and returns the ONE
ReplySpec to send:

    nothing to ask      -> plain text
    1-3 choices         -> reply buttons
    4-10 choices        -> list message
    more than 10        -> numbered text (answered by number or words)

When candidates compete the order is: a question the record needs, then the
project/site setup offer, then the team photo, then the setup question. The
losers are dropped (the caller decides whether to hold them for later).

Pure: no I/O. The caller sends the spec (runtime/reply_dispatch.py, which
falls back to numbered text if an interactive send fails) and remembers the
choices so a typed "undo" / "photo" / "2" works like the tap
(interactions/offered_choices.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from channel.replies import TEAM_PHOTO_BUTTONS, ListRow, ReplySpec

#: Reply-button limits (Meta); the sender enforces them again at the boundary.
BUTTON_TITLE_MAX = 20
BODY_MAX = 1024
MAX_BUTTONS = 3
MAX_LIST_ROWS = 10

#: Offer kinds, in priority order (lowest number wins).
QUESTION = "question"  # a question the record needs; plain text, no buttons
SETUP_OFFER = "setup_offer"  # "add a site / teammate now?" after a project/site is created
TEAM_PHOTO = "team_photo"
SETUP_QUESTION = "setup_question"  # the daily owner setup question (SS-14)
_PRIORITY = {QUESTION: 0, SETUP_OFFER: 1, TEAM_PHOTO: 2, SETUP_QUESTION: 3}

PHOTO_ROW = ListRow("team_photo_upload", "📷 Add team photo")
UNDO_ROW = ListRow("save_undo", "↩️ Undo")
PHOTO_LINE = "📷 Add a team photo for today's attendance?"

#: What else a worker may type for a tapped row (besides its title or number).
TYPED_ALIASES: dict[str, tuple[str, ...]] = {
    "team_photo_upload": ("photo", "team photo", "add photo", "upload photo", "add team photo"),
    "team_photo_skip": ("skip", "no photo"),
    "save_undo": ("undo",),
}


@dataclass(frozen=True, slots=True)
class Offer:
    """One candidate follow-up gathered while the message was handled."""

    kind: str
    #: A ready ReplySpec (its text joins the reply; its buttons/list_rows are the choices).
    spec: ReplySpec | None = None
    #: A plain question appended to the reply (QUESTION offers).
    text: str | None = None


def _options_of(spec: ReplySpec) -> list[ListRow]:
    return list(spec.buttons or spec.list_rows or ())


def numbered(text: str, options: list[ListRow]) -> str:
    lines = "\n".join(f"{i}. {row.title}" for i, row in enumerate(options, start=1))
    return f"{text}\n\n{lines}\n\nReply with the number or the words."


def _clip(text: str) -> str:
    return text if len(text) <= BODY_MAX else text[: BODY_MAX - 1].rstrip() + "…"


def pick_form(text: str, options: list[ListRow], *, list_label: str = "Choose one") -> ReplySpec:
    """The WhatsApp form for ``text`` with ``options`` to choose from."""
    if not options:
        return ReplySpec(text=text)
    if len(options) <= MAX_BUTTONS:
        return ReplySpec(
            text=_clip(text),
            buttons=tuple(
                ListRow(row.id, row.title[:BUTTON_TITLE_MAX], row.description) for row in options
            ),
        )
    if len(options) <= MAX_LIST_ROWS:
        return ReplySpec(text=_clip(text), list_button_label=list_label, list_rows=tuple(options))
    return ReplySpec(text=numbered(text, options))


def compose(main: str, offers: list[Offer], *, saved: bool = False) -> ReplySpec:
    """The one reply: ``main`` plus the winning follow-up, in the fitting form.

    ``saved`` says ``main`` reports a draft the sender can still undo, which
    adds the Undo choice. A setup question never follows a reply that saved
    data (it waits for a light message), so it is dropped here too.
    """
    candidates = [o for o in offers if not (o.kind == SETUP_QUESTION and saved)]
    candidates.sort(key=lambda o: _PRIORITY.get(o.kind, 99))
    winner = candidates[0] if candidates else None

    if winner is not None and winner.kind == QUESTION:
        # The record needs an answer: it is the one thing on screen.
        questions = [o.text for o in candidates if o.kind == QUESTION and o.text]
        return ReplySpec(text="\n\n".join([main, *questions]))

    options: list[ListRow] = []
    body = main
    if winner is not None and winner.spec is not None:
        if winner.kind == TEAM_PHOTO:
            body = f"{main}\n\n{PHOTO_LINE}"
            options = [PHOTO_ROW]
        else:
            body = f"{main}\n\n{winner.spec.text}"
            options = _options_of(winner.spec)
    if saved and (winner is None or winner.kind == TEAM_PHOTO):
        options = [*options, UNDO_ROW]
    return pick_form(body, options)


def normalise(text: str) -> str:
    """Lower-case words only: "↩️ Undo!" and "undo" compare equal."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower().replace("_", " ")).split())


def resolve_choice(text: str, options: list[ListRow]) -> ListRow | None:
    """Which offered row a typed reply means: its number, its title, or an
    alias ("photo", "undo"). None when it is something else."""
    said = normalise(text)
    if not said:
        return None
    if said.isdigit():
        index = int(said)
        return options[index - 1] if 1 <= index <= len(options) else None
    for row in options:
        if said == normalise(row.title) or said in TYPED_ALIASES.get(row.id, ()):
            return row
    return None


__all__ = [
    "PHOTO_ROW",
    "QUESTION",
    "SETUP_OFFER",
    "SETUP_QUESTION",
    "TEAM_PHOTO",
    "TEAM_PHOTO_BUTTONS",
    "UNDO_ROW",
    "Offer",
    "compose",
    "normalise",
    "numbered",
    "pick_form",
    "resolve_choice",
]
