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
