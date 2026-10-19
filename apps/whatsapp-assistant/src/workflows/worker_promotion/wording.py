"""What the worker-promotion questions say (request [51]).

One place for the English wording, so runtime/reply_language.py can build its
Malayalam / Hindi patterns from the very same templates: change a sentence
here and its translation stops matching loudly in the tests, instead of
quietly falling back to English.

Every question says why it is asked ("so your worker list stays clean"),
about whom (the names, and the register entry they look like), and carries
buttons -- ids below. A tapped button arrives as its id (see
interactions/handler.py), so the buttons can be translated without the
workflow ever parsing a translation.
"""

from __future__ import annotations

#: Button ids. A tap is answered with the id itself.
ID_ADD_ALL = "promo_all"
ID_CHOOSE = "promo_choose"
ID_NOT_NOW = "promo_none"
ID_SAME = "dup_same"
ID_NEW = "dup_new"
ID_SKIP = "dup_skip"

TITLE_ADD_ONE = "Add"
TITLE_ADD_BOTH = "Add both"
TITLE_ADD_ALL = "Add all"
TITLE_CHOOSE = "Choose"
TITLE_NOT_NOW = "Not now"
TITLE_SAME = "Same person"
TITLE_NEW = "New person"
TITLE_SKIP = "Skip"

#: id -> the English word the node's text parser already understands, for a
#: tap that arrives without its id (an older client, a typed number).
ID_ANSWERS = {
    ID_ADD_ALL: "all",
    ID_CHOOSE: "choose",
    ID_NOT_NOW: "none",
    ID_SAME: "same",
    ID_NEW: "new",
    ID_SKIP: "skip",
}

INTRO = "Quick check so your worker list stays clean 👇"
OFFER_ONE = (
    "{names} is a new name. Add them to your permanent worker list so they're "
    "ready next time?"
)
OFFER_MANY = (
    "{names} are new names. Add them to your permanent worker list so they're "
    "ready next time?"
)
CHOOSE = "Which ones should I add? Reply with the names, e.g. {example}."
LOOKS_LIKE = (
    "{new} looks like {old} who's already in your list{detail}. Is it the same person?"
)
LOOKS_LIKE_NEXT = (
    "One more 👇\n\n{new} looks like {old} who's already in your list{detail}. "
    "Is it the same person?"
)
RETRY_OFFER = (
    "No worries. Just tap one: add {names} to your permanent worker list? "
    "If you're not sure, tap Not now. 🙂"
)
RETRY_CHOOSE = (
    "No worries. Reply with the names to add, e.g. {example}. "
    "If you're not sure, tap Not now. 🙂"
)
RETRY_LOOKS_LIKE = (
    "No worries. Just tap one: is the {new} who came today the same {old} from "
    "your list? If you're not sure, tap Skip. 🙂"
)
MADE_PERMANENT = "✅ Made permanent in your Worker Register: {names}"
NONE_ADDED = (
    "No problem — they stay as temporary workers. You can make them "
    "permanent any time from the Worker Register on the dashboard."
)
SAME_NOT_ADDED = "👍 Not adding {new} again — they're already in your list as {old}."
KEPT_SEPARATE = (
    "I'll keep {names} as a separate name for now. You can sort it out any "
    "time in the Worker Register."
)

#: Every template a translation table may cover.
TEMPLATES = (
    INTRO,
    OFFER_ONE,
    OFFER_MANY,
    CHOOSE,
    LOOKS_LIKE,
    LOOKS_LIKE_NEXT,
    RETRY_OFFER,
    RETRY_CHOOSE,
    RETRY_LOOKS_LIKE,
    MADE_PERMANENT,
    NONE_ADDED,
    SAME_NOT_ADDED,
    KEPT_SEPARATE,
)

BUTTON_TITLES = (
    TITLE_ADD_ONE,
    TITLE_ADD_BOTH,
    TITLE_ADD_ALL,
    TITLE_CHOOSE,
    TITLE_NOT_NOW,
    TITLE_SAME,
    TITLE_NEW,
    TITLE_SKIP,
)


def bold(name: object) -> str:
    return f"*{name}*"


def join_names(names: list[str]) -> str:
    """"*A*", "*A* and *B*", "*A*, *B* and *C*"."""
    marked = [bold(n) for n in names]
    if len(marked) <= 1:
        return "".join(marked)
    return f"{', '.join(marked[:-1])} and {marked[-1]}"
