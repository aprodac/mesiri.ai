"""Live's demo deck (WEB-84; plan: docs/plans/live-value-plan.md, section 6): five short stories a presenter can
run on Live, each a few ready messages and the line to say before each.

One table, ``STORIES``. A step is a line to say and either a message to send (``send``: it goes through Tell
Mesiri, the same handler as WhatsApp, as the signed-in person) or something the presenter does by hand (``do``: a
bill photo from their phone, Replay the day). ``{site}`` and ``{other}`` in a message are the demo's own two sites.

**Demo companies only,** and the companies the Mesiri team switched ``live_ready_messages`` on for (its own test
company). A ready message is a real entry once sent, so the deck is given only to a company the Mesiri team marked as
a demo (``demo_company``, the same mark the one-tap reset needs) or set that switch for. Any other company gets no
stories at all: there is nothing on its Live to tap by mistake.

``TEST`` (asked in session, 14 Nov 2026): one more "story", the test list: one ready message for every kind of
message Live shows (``live_feed.KIND_LABELS``), each with what to look for on the screen. For testing Live without a
phone; it is not printed on the presenter's sheet.
"""

from __future__ import annotations

from typing import Any

#: The stories, in the order they are presented. ``ends_on``: the owner's question the story lands on (board key).
STORIES: tuple[dict[str, Any], ...] = (
    {
        "key": "delivery", "title": "A delivery day", "minutes": 2, "ends_on": "leaks",
        "steps": (
            {"say": "A lorry reaches the site. The supervisor sends one line on WhatsApp.",
             "send": "50 bags cement came at {site} today, rate 400 per bag"},
            {"say": "Watch what one message changed: the stock, the rate against last time, what the supplier is "
                    "owed, and it is already in tonight's report.", "do": "Let the cards play. Space holds one, → moves on."},
            {"say": "Now the supplier's bill. Nobody types it.",
             "do": "From a phone: scan the QR and send a photo of the supplier's bill."},
            {"say": "Mesiri read the bill and checked it against what arrived. Anything that differs is caught here.",
             "do": "Point at “Is anything leaking?” on the owner's board."},
        ),
    },
    {
        "key": "day", "title": "The site's day", "minutes": 2, "ends_on": "owed",
        "steps": (
            {"say": "Morning: who is on site. One line, in any language.",
             "send": "{site} today 6 mason 8 helper 2 carpenter"},
            {"say": "The day's wages and the week's wage bill are already added up. No Saturday counting.",
             "do": "Let the cards play."},
            {"say": "Evening: what got done.", "send": "Plastering 120 sqm done at {site} today"},
            {"say": "Work that is counted on its estimate line is work you can bill the client for. Mesiri suggests "
                    "the line; one tap by a person counts it.", "do": "Point at “What do I owe, and who owes me?”."},
        ),
    },
    {
        "key": "wrong", "title": "Something is wrong", "minutes": 2, "ends_on": "stops",
        "steps": (
            {"say": "Somebody types one zero too many.", "send": "5000 bags cement used at {other} today"},
            # Run on the real assistant, 13 Nov: it saves what the site said (it does not refuse it), and the
            # entry is marked as more than the site had. The story says that, not "Mesiri stops it".
            {"say": "Mesiri records what the site said and marks it at once: more used than the site ever had. A "
                    "mistake does not hide in the books.",
             "do": "Tap Save on the card, and let Live's warning show."},
            {"say": "And one message takes it back. No office visit, no register corrected by hand.",
             "send": "That 5000 bags cement used at {other} was a mistake, take it back"},
            {"say": "A real one now: the day's use.", "send": "30 bags cement used at {site} today"},
            {"say": "The stock went down, and you hear it is running out before the site stops.",
             "do": "Point at “What will stop work tomorrow?”."},
        ),
    },
    {
        "key": "asks", "title": "The owner asks", "minutes": 2, "ends_on": "money",
        "steps": (
            {"say": "You are the owner. Ask from your own phone.", "do": "Scan the QR and send: Stock at {site}?"},
            {"say": "Or ask from here.", "send": "How much cement is at {site}?"},
            {"say": "The answer on WhatsApp and the number on the board are the same number, from the same records.",
             "send": "How many workers are on site today?"},
        ),
    },
    {
        "key": "night", "title": "9 pm", "minutes": 1, "ends_on": "proof",
        "steps": (
            {"say": "Nine o'clock. Nobody opened an app all day.", "do": "Press “Replay the day” to run the day again."},
            {"say": "The report writes itself and goes out, with the photos.",
             "send": "Send today's report for {site}"},
            {"say": "Read the bottom of the screen: the messages today, and the things you now know.",
             "do": "Point at the totals."},
        ),
    },
)

#: The test list: one ready message per kind Live shows, and what to look for. ``kind`` is the kind the message
#: should come back as (``live_feed.KIND_LABELS``), so a test can hold the list to every kind with a ripple.
TEST: dict[str, Any] = {
    "key": "test", "title": "Test every kind", "minutes": 5, "ends_on": "proof",
    "steps": (
        {"kind": "attendance", "say": "Attendance: who is on site, the day's wages, lands on “What do I owe”.",
         "send": "{site} today 5 mason 6 helper 2 carpenter"},
        {"kind": "correction", "say": "A correction: the number changes on the report (5 → 4), nothing is counted twice.",
         "send": "Sorry, not 5 mason, 4 mason at {site} today"},
        {"kind": "work", "say": "Work done: the day's progress, the floor, the schedule, the estimate line.",
         "send": "Brick work 40 sqm done on the first floor at {site} today"},
        {"kind": "delivery", "say": "Material came: the stock, the order, the rate against last time, the supplier.",
         "send": "20 bags cement came at {site} today, rate 410 per bag"},
        {"kind": "usage", "say": "Material used: the stock goes down, and how many days it lasts.",
         "send": "10 bags cement used at {site} today"},
        {"kind": "transfer", "say": "A transfer: the stock moves from one site to the other.",
         "send": "Sent 5 bags cement from {site} to {other} today"},
        {"kind": "expense", "say": "An expense, typed: on the books with who it went to (money roles only).",
         "send": "Paid 1500 for diesel at {site} today"},
        {"kind": "expense", "say": "A bill photo: Mesiri reads it and checks it against what arrived.",
         "do": "From a phone: scan the QR and send a photo of a supplier's bill."},
        {"kind": "issue", "say": "An issue: open on the site, somebody's job, lands on “What will stop work”.",
         "send": "Water leaking from the roof slab at {site}, need a plumber"},
        {"kind": "machine", "say": "A machine's day: hours, breakdown, what the hire comes to.",
         "send": "JCB worked 6 hours at {site} today, 1 hour breakdown"},
        {"kind": "question", "say": "A question: the answer, what Mesiri read, and today's messages it was built from.",
         "send": "How much cement is at {site}?"},
        {"kind": "question", "say": "Another question: the same number as the board.",
         "send": "How many workers are on site today?"},
        {"kind": "undo", "say": "A take-back: the line crumbles, the stock goes back up.",
         "send": "That 10 bags cement used at {site} was a mistake, take it back"},
        {"kind": "report", "say": "The report: the sheet folds into its PDF and goes out.",
         "send": "Send today's report for {site}"},
    ),
}

#: The short show (three minutes): the first and the last story.
SHORT_SHOW: tuple[str, ...] = ("delivery", "night")


def stories(sites: list[str], *, test: bool = False) -> list[dict[str, Any]]:
    """The stories with the demo's own site names in their messages. With one site, both names are that site.
    ``test``: the test list (``TEST``) comes last, marked ``test``."""
    site = sites[0] if sites else "the site"
    other = sites[1] if len(sites) > 1 else site
    out = []
    for story in (*STORIES, TEST) if test else STORIES:
        steps = []
        for step in story["steps"]:
            filled = {k: (v.format(site=site, other=other) if k in ("send", "do") else v) for k, v in step.items()}
            steps.append({"say": filled["say"], "send": filled.get("send"), "do": filled.get("do"),
                          "kind": filled.get("kind")})
        out.append({"key": story["key"], "title": story["title"], "minutes": story["minutes"],
                    "ends_on": story["ends_on"], "short": story["key"] in SHORT_SHOW, "test": story is TEST,
                    "steps": steps})
    return out
