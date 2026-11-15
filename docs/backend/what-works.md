# What works (SA-38)

Control panel > WhatsApp > **What works**. One page that answers "what can people say to Mesiri today,
what does it reply, and where does it fall short", from the messages people really sent.

## What the page shows

Four views on a segmented control at the top (the view, window, company and selection live in the address):

**Health** (the default, SA-39 phase 2) judges *requests*, not single messages (see "Version 2" below):

- One line for the window: the share of requests that finished, a bar of how all of them ended (finished,
  finished after a question, left without Save, cancelled, failed, complaint or 'not yet', not sure), and the
  change against the window of the same length before it.
- **Fix these first**: the five largest problems of the window across every module, one line each in plain
  words with its count ("29 requests failed: AI unavailable"; the capabilities it hit on hover).
- **By module**: one row per section with its bar, its finished share and count, and the change. A row opens
  to its **capabilities** (what a person can ask for, named from the tool's own description, the tool name in
  small grey text): how often it was asked, the share that finished, its top failure reason.
- A capability card or a problem opens the **panel** on the right (below on a phone): its requests, the ones
  that did not finish first (a problem: newest first), and the WhatsApp conversation of the one picked with
  every message of that request highlighted. The worst one is open already: two clicks from the page to a
  real conversation.

**Playbook** (SA-39 phase 3) shows how each module should work. Per module, per thing people ask for, one
row per journey it was really used in (one thing then Save, several things in one message, Mesiri asks and the
person answers, changed before saving, corrected after saving, a follow-up that needs memory, a question
answered from the records, voice note, photo, cancelled). Each row has its **best case**: the cleanest *real*
request of the window (never written by hand, decision D2), and beside it how many real requests of that
journey end the same way. A row with no clean run is amber and says so. Picking a row shows the conversation
on the right with the request highlighted.

The best case is picked in `admin/intents_playbook.py`: the request must end the way the journey should
(finished; cancelled for "Cancelled"), must not have been corrected later, and must not have had a question
the journey does not need. Among those: the one whose own messages hold its Save or Cancel (on a shared card
another request may hold the tap), then the fewest refusals the model recovered from, the fewest messages, the
fastest slowest reply, the newest. "One message, one thing" and "several things" count only what the first
message put on the card. Nothing in the record says a message was rude: a best case can be a message nobody
would pick by hand; pinning (phase 5, decision D3) is the way to override it.

**Patterns** (SA-39 phase 4) shows the connections between failures (`admin/intents_patterns.py`):

- **Same cause**: every problem once, wherever it happened ("3 places"), with its trend against the window before
  (new / growing / shrinking) and how many causes of the window before are gone. A cause opens its requests and
  the fix actions: copy the replay command (`python3 scripts/replay_to_test.py <correlation id>`, the start of
  every fix), copy all its correlation ids, and the team request references when Mesiri passed one on. The
  reference is `release_notes.request_ref` of the message's correlation id: the same "#a83f12" the team's
  request log and group show (TM-21), so it is matched by id, never by text. The nightly review findings table
  is empty on production (15 Nov), so nothing is linked from it.
- **Where it leaks**: per thing people ask for, asked -> a tool was called -> on the card or answered ->
  finished ("26 -> 26 -> 25 -> 11"), and the step that loses most.
- **What makes it worse**: the finished share by how it was sent, the script of the words (read from the
  letters: Latin, Malayalam, Devanagari, ...), who sent it, the company. A group shows only with 10 requests or
  more, and a split only when two groups pass that.
- **After a failure**: what the person did next in the same conversation: sent it again, said it was wrong,
  asked something else, stopped. "Sent it again" and "said it was wrong" are `admin/friction.py`'s signals (the
  nightly reviewer's), not new rules.

**Short on purpose** (asked 15 Nov: "too much descriptions ... unreadable"): the page shows labels and numbers;
explanations are tooltips (the ⓘ beside a heading, the endings in the legend, a journey's row). The answer still
carries phrasings and how people sent each request; the page does not show them on the cards.

**Every message** is version 1, kept for its search: every kind of message, one message at a time.

The rest of this section describes that view.

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

## Version 2: intents (SA-39)

Phase 1 built this; phase 2's Health view shows it (`apps/control-panel/src/WhatWorksHealth.tsx`). Plan: [WHAT_WORKS_V2_PLAN.md](../plans/WHAT_WORKS_V2_PLAN.md).

`GET /admin/message-map/intents?days=&organization_id=` (platform admins only, read-only) judges
**conversations** (one person, no silence over 30 minutes) split into **intents**: a message that starts
something plus the taps, answers and changes that continue it. Rules: `apps/whatsapp-assistant/src/admin/intents.py`
(pure; the page's summary and "Fix these first" in `admin/intents_summary.py`; tests in `tests/unit/test_message_intents.py`). Each message is still filed by version 1's `classify`
first; intents only link them.

How a message is linked (first rule that fits):

1. A Save or Cancel, or a turn that only changes the card, continues the intents whose lines are on the card.
   **The card is shared**: one Save ends every intent waiting on it (a refused save line fails only the intent
   that prepared that tool).
2. A tap continues the latest intent with a card or a question waiting, else the latest intent.
3. Right after Mesiri asked a question (the trace says so, or the reply ends in "?" with no card waiting), a
   message that calls no tool, or a tool the intent already called, is the answer.
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
