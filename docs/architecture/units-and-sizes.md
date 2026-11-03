# Units and sizes: how a "load" becomes stock (WA-165 to WA-168, 3 Nov 2026)

People on site count the way they buy: a load of M-sand, a drum of thinner, ten bars of TMT. Stock is kept in one
unit per material (its stock unit). This is how the two meet without making anyone convert, approved by Alan on
3 Nov 2026 after Paraclette hit 21 unit dead ends in four days.

## The rules

1. **A material is counted in its kind's unit.** A material created from WhatsApp gets the unit its kind is counted
   in (`unit_conversion.natural_stock_unit`): steel / TMT / kambi / binding wire in kg, sand / M-sand / P-sand /
   metal in cft, cement in bags, bricks / blocks / laterite in nos, paint / primer / thinner in litres. Other kinds
   keep the unit the person used.
2. **A size converts every line.** "1 load M-sand = 60 bags" (`material_unit_conversions`, set once for the
   company) or a fixed fact (`built_in_per_stock_unit`: tonnes, brass, cement bags, steel bars by diameter). One
   decision, `_known_per_stock_unit` in `materials/router.py`, is used by saving and by
   `GET /materials/{id}/unit-check`.
3. **The question comes before Save, once, in the person's direction.** The assistant checks each line it prepares
   (`agent.settle_stock_unit`) and shows what it becomes in stock on the ready line: "1 load M-sand (= 60 Bags)".
   A size line is drawn by the code: "📏 1 Loads M-sand = 60 Bags". A size the wrong way round (less than one piece
   in a container of a counted material) is refused.
4. **Whoever answers, the line is never refused twice.**
   - An admin or project manager: the size is set for the company with the line.
   - Anyone else: their own line is converted by the code with their size (kept for them 180 days), and the size
     is proposed to the company (`material_size_requests`).
   - Nobody knows ("🤷 Don't know"): the line is held on a size request; everything else saves.
5. **The admin is asked once a day** (`runtime/size_requests_ask.py`, on the automation tick, through the
   notifications queue: 24-hour window, quiet hours, opt-outs). A proposal is one tap (`apiag:size:<id>`); anything
   else is a reply ("M-sand load 60", tool `answer_size_request`) or the dashboard (Materials -> Sizes). Answering
   sets the size and saves every held line as the person who reported it (their access decides), each in its own
   savepoint, and tells them.
6. **A Save that cannot work is never offered.** After a size refusal at Save, only Cancel is shown and the size is
   the open question.

## Units

Container units drum, tin, bucket, bundle (migration 0498). "Trip", "lorry", "tipper" are words for Loads
(`runtime/unit_words.py`), not a unit of their own.

## Not built

A company-wide size set by a site engineer directly (their size is a proposal); a size request for a material that
is itself waiting to be added (its line waits in the ready list with the size asked in the same turn, [217]);
templates for the daily ask outside the 24-hour window (it is skipped there until a template is approved).
