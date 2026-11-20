# Episode 4, "Cement runs short": the plan

> Asked 20 Nov 2026 (Ilan): "plan episode 4". Status: **draft for Ilan's review**. Scripted 20 Nov (asked: "start episode 4 script") on section 7's
> recommended answers: `episode-04.json`, readable `scripts/episode-04.md`. Not filmed. Series objective and the episode's row: [SERIES_PLAN.md](SERIES_PLAN.md)
> section 5. Recording rules: [RECORDING.md](RECORDING.md) (real entries only). Tracker: LRN-F17.

## 1. Objective

From the series plan, unchanged:

> By the end you can walk a material chain across all four people: request → quotation and rate → order → delivery
> (and a short or damaged load returned) → stock and use → supplier bill checked against order and delivery →
> payment; and a month-end stock count.

Said as the viewer's test: *given a site that is short of cement, say who does what next, in what order, what paper
each step leaves, where it is in Mesiri, and what money is lost if a step is skipped.*

Length: about 9 minutes (the series allows 6 to 10). It is the longest chain in the series, so it gets no extra
side stories.

## 2. What we found planning it: the papers and the played days tell two different stories

Episode 3 ends on day 2 with Ravi asking for 100 bags for the Main block. From there the two sources disagree:

| Step | The sample company's 62 days (`sample_plan.py`) | The starter kit's papers (`make_kit.py`, `green_villa.RETURN`) |
|---|---|---|
| Quotes | none: Anil orders on day 3 | three quotes, 18 Nov (day 4): 300 bags cement + 2,000 kg steel, "for Main block"; Malabar ₹400/72, Kerala Steels ₹412/66, Sri Hardwares ₹408/70 |
| Order | 100 bags, Malabar, ₹410, day 3 | an order for 200 bags (the challan's "ordered") |
| Delivery | all 100 on day 5 | 190 of 200 on 20 Nov (day 6): 10 still to come |
| Damaged | none | 6 bags torn and set hard, refused at the gate: return note GV/RN/014, debit note ₹2,400 |
| Bill | ₹41,000, matches the order, day 7 | MCA/INV/2611, 22 Nov (day 8, a Sunday): 190 bags at ₹410 against the order's ₹400 |
| Payment | ₹82,000 for 2 bills, day 14 | not in the kit |
| Stock count | none (batch 2) | none (counted on the phone) |

The played days have no quotation, no short load, no return, no wrong rate and no count: the episode's whole
lesson. The papers have all of it but were never played, so no screen shows them. **The episode cannot be filmed
from real entries until the Main block's cement chain in the 62 days is the kit's chain.** That is the materials half
of story batch 2 (SERIES_PLAN section 7), and it is the first piece of work (section 6 below).

Two smaller mismatches:

- The kit's quotation asks for 2,000 kg of steel "for Main block", but the Main block is up to its parapet: it is
  plastering and laying conduits, and uses no steel in the played days. The Annex (plinth beam, then columns) does.
- Day 8, the bill's date, is a Sunday. That is fine for a supplier's invoice; Meera books it on Monday, day 9.

## 3. The story (proposed; dates are the sample company's: day 2 is Monday 16 Nov)

| Day | Who | What happens | Where in Mesiri | Real entry |
|---|---|---|---|---|
| 2 · Mon 16 | Ravi | Main block has 2 bags; asks for 100 (end of episode 3, already recorded) | WhatsApp → Materials: Requests | capture (reuse ep 3's) |
| 3 · Tue 17 | Anil | Sees the request first thing. Two moves: **20 bags from the Annex** today so the conduit work goes on, and the real need priced: the material plan says the Main block's plastering needs about 300 bags this month | Requests; Stock (the page's own "move from the Annex" suggestion); Material plan | capture (Ravi says the transfer) + steps (request seen, approved) |
| 3 · Tue 17 | Anil | Asks three suppliers to quote: 300 bags cement (and the steel, see decision 2) | Procurement: Quotations, a request to three | steps |
| 4 · Wed 18 | Anil | Three quotes come (the kit's papers). Compare: Malabar cheapest for cement, Kerala Steels for steel. **Orders 200 bags, not 300**: the site store holds about 200, and cement kept too long goes hard. The rest when the store has room | Quotations: compare, award → Purchase orders | paper + steps |
| 6 · Fri 20 | Ravi | Malabar's lorry: the challan says 190 sent, 10 to follow; 6 bags torn and set hard, refused at the gate | WhatsApp: the delivery goes on the order by itself (PRC-23); 10 still to come | capture |
| 6 · Fri 20 | Anil | The 6 torn bags sent back: return note GV/RN/014, debit note ₹2,400 off what is owed to Malabar at once | Procurement: Returns, from the delivery | paper + steps (or capture: `return_to_supplier` works on WhatsApp too) |
| 9 · Mon 23 | Meera | Malabar's bill MCA/INV/2611: 190 bags at ₹410. Mesiri puts it beside the order (₹400) and the delivery (184 kept, 6 returned): ₹1,900 more than ordered, before GST. Meera holds the difference and calls Malabar | Finance: Suppliers, the bill matched to the order and delivery | paper + steps |
| 9 to 14 | Ravi | Plastering: 14 bags a day. Stock comes down; Pending deliveries still shows the 10 bags; Stock says days left | Stock, Pending deliveries | screen |
| 10 · Tue 24 | Ravi | The 10 bags come | WhatsApp: closes the order | capture |
| 12 · Thu 26 | Anil | Store has room: orders the other 100 at the quoted ₹400 (the quote's 7 days are over: decision 4) | Purchase orders | steps or played |
| 14 · Sat 28 | Meera | Pays Malabar: the bill at the order's rate, less the debit note | Finance: Suppliers, pay | capture (`pay_supplier`) or steps |
| 16 · Mon 30 | Ravi, Owner | Month end: Ravi counts the Main block's cement on the phone; it is a few bags short of the book; the owner approves the difference with a reason | Materials: Stock count (counted on WhatsApp, approved on the website) | capture + steps |

What the viewer should be able to retell: one shortage, **four people, eight papers** (request, quotes, order,
challan, return note and debit note, bill, payment, count), and three places money leaks and is caught (the 6
torn bags, the ₹10 a bag on the bill, the count).

## 4. Scenes (to become `episode-04.json`)

Same shape as every episode (SERIES_PLAN section 4). About 15 scenes, ~1,300 words of narration.

| # | Part | Scene | Kind | Shows |
|---|---|---|---|---|
| 1 | Cold open | Two bags left | title | Monday dusk at the Main block; "Need 100 bags cement" |
| 2 | On a real site | How a site buys material | story | request → quote → order → delivery → bill → pay; who signs each paper |
| 3 | On a real site | Why not just order 300 from the usual shop | story | quotes keep the rate honest; storage and shelf life decide how much at once; what "short" and "damaged" look like at the gate |
| 4 | In Mesiri | The request on Anil's desk, and 20 bags tonight | steps + chat | Requests; the transfer said on WhatsApp |
| 5 | In Mesiri | Three quotes | paper → steps | the kit's three quotations, then Quotations: compare, cheapest per item, award |
| 6 | In Mesiri | 200 bags, not 300 | steps | the purchase order; Pending deliveries |
| 7 | In Mesiri | The lorry at the gate | paper → chat | the challan (190 of 200); Ravi's message; the card puts it on the order, 10 to come, 6 refused |
| 8 | In Mesiri | Sending back what is torn | paper → steps | return note; Returns: the debit note lowers what is owed at once |
| 9 | Who does what, when | Four people, one load of cement | people | the swimlane: Ravi asks and receives; Anil buys and returns; Meera checks and pays; the owner approves the count |
| 10 | In Mesiri | The bill is not the order | paper → steps | Malabar's bill; Suppliers: the bill beside order and delivery, ₹10 a bag more |
| 11 | In Mesiri | Came, minus used | screen | Stock: Main block's cement coming down 14 a day; days left; the 10 bags still to come |
| 12 | In Mesiri | Paying the right amount | steps or chat | the payment: the order's rate, less the debit note |
| 13 | In Mesiri | Month end: what is really there | chat + steps | the count on WhatsApp; the difference and its reason; approved |
| 13a | What the owner sees | Paying for what came | screen | as Ramesh: Suppliers, Malabar: the bill, the debit note and the ₹10 a bag held; what is owed now; then the count he approves (SERIES_PLAN 5a) |
| 14 | What can go wrong | Six ways a load of cement leaks | leaks | no quotes; ordered more than the store holds; signed for 200, got 190; torn bags kept; billed above the order and paid; never counted |
| 15 | Recap | Three questions | questions | e.g. "Who sends the torn bags back, and what does it change?", "What three things does Meera put side by side before she pays?", "Why order 200 when you need 300?"; next: Wages week |

Pages this episode covers (SERIES_PLAN section 6, episode 4): Materials Requests, Stock, Movements, Stock count;
Procurement Requests, Quotations, Purchase orders, Pending deliveries, Returns, Rates (the rate on the order);
Finance Suppliers (bills, payments). Stock value and Suppliers (the list) appear in passing.

## 5. Implementation plan (per the protocol)

- **Objective:** a recorded Episode 4 that teaches the material chain from real entries.
- **Scope:** (a) the Main block's cement days 2 to 16 in `sample_plan.py` replaced by the chain above; (b)
  `episode-04.json` + `scripts/episode-04.md`; (c) `steps-04.cjs`; (d) recording and build. Nothing else.
- **Business value:** the team learns the most-used chain (52 requests and 57 deliveries in the 62 days), and
  filming it tests Quotations, Returns, bill matching and Stock count on real screens for the first time.
- **Files expected to change:** `backend/src/mesiri/application/learn/sample_plan.py` (the cement chain, a stock
  count, the transfer), maybe `learn/green_villa.py` (one source for the quote, order, challan and bill figures, as
  `RETURN` already is) and `scripts/learn_kit/make_kit.py` (read them from there; rebuild the kit),
  `docs/plans/sample-plan.md` and `az-map/` (regenerated), the plan's tests; `docs/learning/film/episode-04.json`,
  `scripts/episode-04.md`, `steps-04.cjs`; RECORDING.md, LEARNING_PATH.md, V1_TRACKER.md.
- **Backend:** none beyond the sample plan (the learn module only). No product code: every step already has its
  route (quotations PRC rfqs, PRC-23 delivery on order, PRC-46 returns, vendor bill matching, PRC-48 stock count).
- **Frontend / API / Database:** none. No migration.
- **Risks:** (1) changing day 3 onwards must leave day 2 exactly as episode 3 recorded it; (2) the plan is played
  through the real API, so a step the API refuses (a return against a delivery, a count with a difference) shows up
  only when the 62 days are replayed; (3) recording needs the model key (episode 3's two scenes are still waiting
  on its cap); (4) resetting the sample company fails after Tell Mesiri (LRN-F16, blocked): use RECORDING.md's local
  workaround; (5) Tower B also orders from Malabar on the same days: keep its lines unchanged so the episode's
  Supplier screens are not confused by them, or say so on screen.
- **Testing:** the plan's unit tests (whole bags, the chain's order of steps, figures agree with `green_villa`);
  the 62 days played end to end through the API with no failure; the kit's tests (papers agree with the seed);
  `script_md.py 04`; `STILLS=beats build.mjs 04` checked picture by picture.
- **Rollback:** the sample plan change is one commit in the learn module; revert it and re-run the exporter. The
  episode files are new files.
- **Labour isolation:** no Labour, Attendance, Payroll or Workforce change.
- **Success criteria:** every number said is read off the sample company on that day; each of the twelve steps in
  section 3 is a real entry or a real screen; the three questions can be answered from the film alone.

## 6. Order of work

1. **This plan agreed** (Ilan), with section 7's decisions.
2. Story: the cement chain in `sample_plan.py` (one source in `green_villa.py`; the kit rebuilt from it), tests,
   62 days replayed, `sample-plan.md` and the A-to-Z map regenerated.
3. Script: `episode-04.json` from section 4, with `capture` on every chat scene and `steps` frames; `script_md.py`.
4. Record (`record.cjs 04`, `shoot.cjs 04` for papers and screens); words changed to the real cards.
5. Build, check stills and sound, send the `.mp4` and `.srt`; "What we found" to the tracker.

## 7. Decisions for Ilan

1. **Make the played days match the kit** (section 2): the Main block's cement becomes quotes → 200 ordered → 190
   came, 6 torn → bill at ₹410 vs ₹400 → paid less the return. *Recommended:* yes; the alternative (change the
   papers to fit the played days) loses every catch the episode teaches.
2. **The steel in the quotation:** keep "2,000 kg steel" but for the **Annex** (its columns use it), or drop steel and
   quote cement only. *Recommended:* keep it, for the Annex: comparing two items is what shows "cheapest per item
   beats cheapest in total".
3. **The ₹10 a bag on the bill:** Malabar agrees and Meera pays at ₹400 (the lesson: the order's rate rules), or
   Malabar sends a credit note later. *Recommended:* pays at ₹400, one step, one screen.
4. **The other 100 bags:** ordered on day 12 at the quoted ₹400 (the quote has expired: Rates shows it held), or
   left out of the episode. *Recommended:* one line of narration and the order on screen; it closes "why 200, not 300".
5. **The count's difference:** how many bags short, and why (spillage and hardened bags are the honest usual
   reasons; theft is the dramatic one). *Recommended:* 3 bags, "wastage", approved by the owner: small, normal, and
   the reason the count exists.
6. **The owner's part:** his beat is scene 13a (Suppliers, then approving the count); not also approving the 200-bag
   order: the product has no order approval step today. *Recommended:* as 13a, and say so in "What we found" if it
   should have one.
