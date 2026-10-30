# Request 159: updated plan (replaces 152–158; folds in 157)

Written 30 Oct 2026 from the code at `b5aea49`. Source: live chats of midlaj (SITE_ENGINEER) and
Ilan (ADMIN), Paraclette, 30 Oct 11:05–11:19 IST.

**Owner decision already taken:** site engineers add materials themselves. This is live in code as
`c5b9691`: `whatsapp_material_create_roles` defaults to ADMIN, PROJECT_MANAGER, SITE_ENGINEER, and an
org that saved its own list keeps it. So the admin approval card from plan 158 is **not built**.
The admin gets an FYI instead (part D).

Each part is its own commit and pushes when its own tests pass. Order: **A → D → C → B → E**.
A comes first because the "answer a question on the card" mechanism is what D and E reuse.

---

## A. A question at Save time is asked on the card, never thrown away (was 152) 🔴

**Root cause (code):** `runtime/agent/draft_flow.py::_write`. Any workflow step that is not `saved`
calls `abandon_question()` and raises `_Failed(item, _clean(step.text))`. `_clean` cuts the text to
160 characters, so "Which account did you pay from? 1. Office Cash … or just t" becomes an error.
The question is gone. The user's answer ("Office cash") then reads as a new message, and the model
calls `save_expense` again with `account` set. `draft.duplicate_of` only matches identical args, so
the card gets a **second** ₹140 line. On Save, both lines hit the same question again: a loop.

**Class:** every workflow that can stop and ask at confirm time. That covers the expense account,
the material unit and material choice, the labour trade/site, and an "earlier question still waiting"
(`BLOCKED_PENDING_CONFIRMATION`). It applies to typed, voice and photo input alike.

**Fix (one place, `draft_flow._write` + `draft.py`):**
- A step that asks (`needs_input` / a slot prompt) becomes item state `WAITING` instead of `_Failed`.
  The item keeps the slot name, the question and its options.
- The card shows the question with buttons (list rows when there are more than 3 options). Example:
  "❓ Paid from? [Office cash] [Site cash] [Own pocket]". The rest of the card still saves.
- The answer (tap, or typed text matched to an option) fills that item's args. Save then resumes
  that item, with no new line. A typed answer while a card item is `WAITING` is read as the answer
  first (the same path as D's "TMT steel").
- `duplicate_of` also treats a line as the same when only the field just asked about differs, so the
  same expense is never added twice.
- **Future dates:** an `occurred_date` after today (the bill read as "30 Dec" on 30 Oct) becomes a
  `WAITING` question: "Date 30 Dec is in the future. [Today 30 Oct] [Change]".

**Guards:** a card with no question still saves in one tap. A real second expense (different
amount or date) is still its own line.
**Tests:** a replay of Ilan's 11:15 flow (expense → Save → "Office cash" → Save = one ₹140 saved),
the material-unit sibling, the future-date case, and the two-different-expenses guard.

## D. New materials: the rest of the experience (was 155 / 158 D) 🟠

Done: `c5b9691` (site engineers may add).

**Root causes still open (code):**
- `material_entry._material` asks "Add it / No". A typed "Add Tmt steel bars material" or "TMT steel"
  is not read as the answer (live 11:14–11:15: "That wasn't saved…", then the same question again).
- `material_catalog_query.closest_materials` ranks by spelling (`difflib`) and recent use only, so
  "Tmt steel bars" got *Fevi Stick / fevicol / sand*. There is no store of local words (kambi,
  mannu); a grep found no material alias table.

**Fix:**
- One question: up to 3 closest real materials, then **➕ Add new: TMT steel bars (ton)**, with the
  name tidied and the unit and type taken from what was said. One tap adds the material and keeps the
  line on the card. **✏️ Change** edits the name or unit.
- Before adding, a close existing name asks "Same as Steel rods 8mm?" first.
- **Local words:** a new `material_aliases` table (org, alias, material_id). This is an **additive
  migration**. A pick or an add stores the word that was said, so "kambi" is never asked again. A
  seed list of common Malayalam/Manglish words (kambi→steel, mannu→sand, chaakku→bags) helps
  ranking only and never decides on its own.
- A typed answer to the open material question is read as the answer (the WAITING path from A).
- "add material TMT steel bars, ton" works at any time. A bill with 3 new items asks once for all 3.
- **Admin FYI** (instead of approval): "midlaj added *TMT steel bars* (ton)" with
  [OK] [Merge into…]. Merge moves the records to the existing material. The add itself is never
  held up.

**Guards:** an exact or alias match never asks. A role outside the org's list still gets the
pick-list only.

## C. Already saved today, delivery cost, loss sheet (was 154) 🔴

**Root cause:** `draft.duplicate_of` compares only within the open card. Nothing compares a new card
with what was saved earlier today, so the 11:09 repeat saved 100 in / 20 used a second time.

**Fix:**
- At card time, compare each line with today's saves for the same sender and site. The save journal
  (`journal.py`, migration 0493) has the facts. A match shows "Already saved at 11:05" and leaves
  the line off unless they tap **Add again**, which covers a real second delivery.
- **Delivery cost:** add `total_cost` / `unit_cost` to the `save_material_receipt` tool. The
  `material_receipts` columns already exist (`unit_cost`, `total_cost`, written by
  `materials/invoices.py`), so **no migration** is needed. "100 bags for ₹10,000" = ₹100 a bag. A
  cost said for a delivery already saved today fills that record and does not add one.
- **Loss / waste sheet:** "loss sheet" or "nashtam ethra" gives in − used − in stock per material,
  with the cost from the receipts (80 bags × ₹100 = ₹8,000), as text plus the existing sheet export.
  To verify first: whether material usage can carry a reason (wasted / thrown). If it can't, waste is
  recorded as usage with a reason in a small **additive** column, which needs a migration
  head check.

**Guards:** two different deliveries of the same material on one day still save after one tap.
**Data:** midlaj's doubled cement records (11:10) stay until the owner decides. This is an ops step,
not code.

## B. Every photo in a group is read (was 153) 🟠

**Root cause:** `runtime/message_journey.py::_photos_for_purpose` uses `held_batch[0]` for
expense and attendance, then sends `render_batch_overflow_reply` ("only processing 1 of your 5").
Site-update photos already attach the whole batch.

**Fix:** the agent reads all held photos into **one card**. The reads run in parallel, so reply
time stays about that of one photo. The same bill seen twice (same amount, date and vendor) is one
line. A different bill is its own line. It works with 151 (a typed purpose such as "Tea bill").

**⚠️ Needs Alan:** attendance register pages read together changes Labour/Attendance behaviour.
Expense photos ship first. Attendance stays on the current path until approved.

## E. Amounts never dropped; Cancel tells the truth (was 157) 🟠

**Root causes:**
- The model picks which numbers go on the card, and nothing checks that every amount said is there.
  "Their wage is ₹3000" had no field (the labour tool only has a per-line `daily_wage`), so it was
  dropped silently. The ₹10,000 cement cost in C is the same class.
- `save_button.tap_reply` always says `CANCELLED_DONE` ("nothing saved"), even after
  `Saved 1 · still need …` had already saved the 30 workers.

**Fix:**
- **Unkept-amount check (code, no AI call):** take the ₹ amounts and number+unit pairs from the
  message and compare them with the card's args. Any that are missing show on the card as
  "❓ Not kept: ₹3000. Wage?", using the WAITING question from A. Nothing is dropped silently.
- **Cancel:** when the card is the rest of a partly saved draft, say "Cancelled the rest. Already
  saved: 30 workers."
- **⚠️ Needs Alan (Labour/Payroll):** a group total wage on labour, asked as
  [₹3000 total] [₹3000 each]. Until approved, the amount is asked about and kept on the line's note,
  not written to wages. He also needs to decide whether today's ₹3000 is added to midlaj's 30 saved
  workers.

---

## Files expected to change

`runtime/agent/draft_flow.py`, `draft.py`, `save_button.py`, `material_entry.py`, `tools.py`,
`toolbox.py`, `runtime/material_catalog_query.py`, `runtime/message_journey.py`,
`channel/replies.py`, the material catalog repository and migration (aliases), the inventory query
(loss sheet), and the tests under `apps/whatsapp-assistant/tests/unit/`.

## Database

| Part | Migration |
|------|-----------|
| D | Additive `material_aliases` |
| C | Possibly an additive usage-reason column |
| A, B, E | None |

Check the head (`0493`) right before writing, and confirm the chain has no fork.

## Risks

- A touches the shared save path that every card uses. The replay tests for every record kind run
  before push.
- B adds model reads per photo. Running them in parallel keeps reply time flat, and the latency is
  measured before push.
- E's number check could flag a figure that isn't an amount (a phone number, "Tower 2"). It is
  limited to ₹ and number+unit, and every false flag is a question, never a block.

## Testing

Per part: the reported conversation as a replay test, plus one sibling and one guard
(FIX_APPROACH). The full WhatsApp suite (with PYTHONPATH) and the backend suite run before every
push. Then a live re-test on WhatsApp by the team.

## Rollback

`git revert <part commit>`. The aliases migration has a downgrade that drops the table. The material
rights setting reverts with `c5b9691`.

## Needs Alan before building

- **B:** attendance register pages read together (Labour/Attendance).
- **E:** labour group total wage, and whether to add ₹3000 to midlaj's 30 workers (Labour/Payroll).
- **Ops:** remove midlaj's doubled cement records from 11:10, or leave them.

## Success criteria

The four live chats replayed give:
- one ₹140 expense saved after "Office cash";
- 5 photos on one card;
- the 11:09 repeat shown as "Already saved at 11:05" with the cost kept;
- "TMT steel bars (ton)" added in one tap, with "kambi" known next time;
- ₹3000 asked about, not dropped;
- Cancel naming the 30 workers that stayed saved.

---

## Status, 30 Oct (WA-96)

Built and pushed in WA-96:
- **A:** the mechanism shared by every workflow:
  - questions at Save go on the card line;
  - typed answers are read by code;
  - the Save goes on by itself after the answer;
  - every check question sits on its line;
  - future dates are asked about.
- **D:**
  - every role may add a material by default (owner, 30 Oct; this replaces the admin approval card);
  - the button is "➕ Add <name>";
  - typed answers count as the answer.
- **C:** the "already saved at …" check, with [➕ Save again] [Remove].
- **E:** Cancel says what stayed saved.

Still open, and why:

| Item | Why it's open |
|------|---------------|
| B (photo groups) | Attendance pages change Labour behaviour |
| E total wage | Labour/Payroll change |
| C delivery cost | Touches the shared contracts and the backend materials command, a shared component |
| Loss sheet | Needs a waste reason on material use |
| Material word memory (kambi) | Needs an additive migration |
| Admin FYI of new materials | Not built yet |
| Doubled 11:10 cement rows | Ops decision |
