# What works (SA-38)

Control panel > WhatsApp > **What works**. One page that answers "what can people say to Mesiri today,
what does it reply, and where does it fall short", from the messages people really sent.

## What the page shows

- **Sections**: what a message was about (Materials and stock, Labour, Reports, ...).
- **Kinds** inside a section: the tool the assistant used plus how the turn ended, e.g. *Record receipt ·
  Ready on the card*, *Record receipt · Could not do it: … is not in the company's material list*.
- Three tabs: **Works**, **Doesn't work**, **Not sure**. Each kind opens to the messages sent (the same
  words sent again are one row, "sent 4 times"), with who sent it (name, role, company), how (typed, voice
  note, photo, button tap), when, and the reply.
- Picking a message shows, on the right, the **WhatsApp conversation** it was part of: the person's
  messages, Mesiri's replies, and under each reply what Mesiri did in that turn (only this page shows that).
- Filters: last 1 / 7 / 14 / 30 days, one company, a search over messages, replies and people. They live
  in the address, so a view can be shared.

## Where it reads from (nothing new is stored)

| Data | Source |
| --- | --- |
| The message, the reply, sender, type, status | `inbound_messages` (`message_logger.list_for_map`, `list_around`) |
| What the assistant did | `journey_traces`, stage `agent_api_turn` (`trace_logger.get_turns`) |
| Which section a tool belongs to | the first part of its API route in `agent_api/tools.py` `ALLOWED` |

Routes (platform admins only, read-only): `GET /admin/message-map?days=&organization_id=` and
`GET /admin/message-map/thread/{message_id}`. The grouping is `apps/whatsapp-assistant/src/admin/message_map.py`
(pure functions; tests in `tests/unit/test_message_map.py`).

## How a message is filed

First rule that fits:

1. Failed, an AI outage, or never answered (5 minutes) -> **doesn't work**.
2. A Save: every line saved -> works; any line refused -> doesn't work (with the reason).
3. `tell_the_team`: "can't do this yet" / "the reply was bad or wrong" -> doesn't work; an idea -> not sure.
4. A cancel -> not sure.
5. Any tool that went well (ready on the card, sent, answered from the records, done, a duplicate the
   code blocked) -> works, filed under that tool.
6. A question for the person ("which site?") -> works.
7. Only refusals -> doesn't work, with the refusal (names and numbers taken out, so the same refusal about
   two materials is one kind).
8. A card still waiting -> works; a reply the code had to correct with nothing done -> doesn't work;
   a tap the code answered -> works; a reply with no tool -> not sure.

## Limits (read before trusting a number)

- **"Works" means the record shows Mesiri did something, not that it was right.** A wrong answer that used
  a tool counts as works until the person says so (then rule 3 moves it).
- Only v3 turns (`agent_api_turn`, since 2 Nov 2026) say what was done. A classic-assistant message shows
  under *Not sure: no record of what Mesiri did*.
- Reply buttons and card pictures are not stored, so the chat shows the reply text and the person's taps,
  not the buttons themselves.
- At most the newest 5,000 messages of the window are read (the page says when it was cut); a kind shows
  at most 25 different messages.
- A new first path part in `ALLOWED` needs a name in `SECTIONS` (a test fails until it has one). A new
  tool handled by the code (no route) goes in `CODE_TOOLS`, else it shows under *Talk and everything else*.

## Version 2, phase 1: intents (SA-39)

The page itself is still version 1; phase 2 builds the new one on this. Plan: [WHAT_WORKS_V2_PLAN.md](../plans/WHAT_WORKS_V2_PLAN.md).

`GET /admin/message-map/intents?days=&organization_id=` (platform admins only, read-only) judges
**conversations** (one person, no silence over 30 minutes) split into **intents**: a message that starts
something plus the taps, answers and changes that continue it. Rules: `apps/whatsapp-assistant/src/admin/intents.py`
(pure; tests in `tests/unit/test_message_intents.py`). Each message is still filed by version 1's `classify`
first; intents only link them.

How a message is linked (first rule that fits):

1. A Save or Cancel, or a turn that only changes the card, continues the intents whose lines are on the card.
   **The card is shared**: one Save ends every intent waiting on it (a refused save line fails only the intent
   that prepared that tool).
2. A tap continues the latest intent with a card or a question waiting, else the latest intent.
3. Right after Mesiri asked a question, a message that calls no tool, or a tool the intent already called,
   is the answer.
4. Messages with no trace in a row (sign-up, classic, taps the code answers) are one intent.
5. Anything else starts an intent.

An intent ends as: **finished**, **finished after a question**, **left without Save** (a card or a question
waiting when the conversation ended), **cancelled**, **failed** (no reply, outage, refusal, a refused save),
**complained** (`tell_the_team` wrong_reply / bad_ux / missing_feature), **not sure** (with the reason from
the record: replied with a question of its own, replied with no tool, the code took a question out, a card
was waiting and nothing changed, a voice note with no words, no trace), or **still going** (the
conversation's last message is under 30 minutes old: left out of every count). Something put on the card
finishes only by a Save; a read in the same message does not finish it.

Journeys (an intent can have several): one thing then Save, several things in one message, Mesiri asks and
the person answers, changed before saving, corrected after saving (`correct_saved_entry`, `correct_work`,
`undo_*`; the intent it corrected is marked `corrected_later`), a follow-up that leans on memory (typed words
that change the card or answer the question; a typed Save or Cancel does not count), a question answered from
the records, voice note, photo, cancelled.

A capability is named from the tool's description (`agent_api.tools.plain_line`, the line `what_mesiri_does`
shows the model, without "Prepare"). The answer also carries the funnel (asked -> a tool was called -> ready
on the card or answered -> finished, with the widest drop), per module the previous window of the same
length, and `links` (`continued`, `shared_card`, `unlinked`).

**Checked on production (15 Nov, 11 days, 620 messages):** 395 intents; 225 messages continued an intent;
no tap was left without an intent to continue; 14 of 122 Saves/Cancels closed a card shared by more than one
intent. Version 1 called 370 of those messages "works"; as intents, 159 finished, 31 were cancelled and 9
were left without Save. "Not sure" is 104 of 395 (26%), every one with its reason: mostly a reply with a
question of its own or a reply with no tool. A hand count of one day (13 Nov, 70 messages, 41 intents)
matched the code on every intent and every ending. 5,000 messages take about 0.2 s.
