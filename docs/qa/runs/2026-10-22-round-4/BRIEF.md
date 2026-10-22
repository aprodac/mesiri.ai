# WhatsApp test, round 4 (22 Oct 2026): brief for the tester

What changed since round 3: every WhatsApp message now goes to the AI assistant, which
saves straight to the workflows (the old pipeline is deleted). Labour, lookups, transfers,
site/project creation, undo, photos and bills all moved. Production is on `main` 038ac47
(deploy 952) or later.

Use the bot's test number through `test_assistant`, as in round 3, on **Mesiri Test
Builders** (site Green Villa). Send each message on its own, wait for the full reply
(up to ~90 s), and screenshot the reply (redraw from the real reply text, as in round 3).
Write the results to `docs/qa/runs/2026-10-22-round-4/README.md` in round 3's format: a table of
`# | Message | Result (PASS / PARTIAL FAIL / FAIL / NOT TESTABLE) | What happened`, then
the screenshots. Note the bot's role ("who am I") at the top.

**What every reply must do (check on all tests):**
- Replies in the language and letters of the message (Manglish gets Manglish, Malayalam
  script gets Malayalam script).
- Never says "saved" before Save is tapped. Saved entries show a card with Save / Cancel.
- No code words, field names, ids or "[options: ...]" in the text.
- A question always comes with buttons or a list when there are choices.

## A. Work done, issues, labour (direct now)

| # | Send | Expect |
|---|---|---|
| 1 | `180 sqm plastering done on 2nd floor` | Card: work done, plastering, 2nd floor, 180 sqm. |
| 2 | `started brickwork on ground floor` | A new work entry (brickwork, started). |
| 3 | `brickwork finished` (right after 2) | Continues the brickwork from 2, does **not** create a second brickwork. |
| 4 | `yesterday 20 m3 slab concreting done` | Dated yesterday, not today. |
| 5 | `JCB breakdown aayi, pani nirthi` | Site issue (equipment breakdown); Manglish reply. |
| 6 | `innu 4 mason, 8 helper vannu` | Labour card: 4 masons, 8 helpers. |
| 7 | `Ravi and Suresh came today, both masons` | Labour with the two names. |
| 8 | `pani nadakkunnu` | One question back ("which work?"), nothing saved. Your next reply (`plastering 2nd floor`) should be understood as the answer. |

## B. Materials, lookups, money

| # | Send | Expect |
|---|---|---|
| 9 | `50 bag cement vannu` | Card "Cement in: 50 bags". |
| 10 | `cement stock ethra und?` | A stock answer, no card, no "Undo". |
| 11 | `cement stock PDF ayakku` | The stock answer **and a PDF** file. |
| 12 | `send today's report` | The day so far (draft) or the DPR PDF, never "being prepared, ask again" forever. |
| 13 | `how much did we spend this week?` | An expenses answer, or a plain line that expenses are off. |
| 14 | `paid 1200 for diesel` | Expense waits on Yes / No (not saved until Yes). |
| 15 | `undo the last expense` | Asks to confirm reversing it. |
| 16 | `create a new site called Block C in Green Villa` | Admin: asks to confirm creating the site. |

## C. Photos and bills (new: the AI reads them)

Send a real photo each time; tap the purpose button when asked ("What is this photo for?").

| # | Send | Expect |
|---|---|---|
| 17 | A fuel/petrol bill photo -> tap **Expense** | Expense with the bill's amount, waiting on Yes / No. |
| 18 | A cement or steel bill/challan photo -> tap **Material Delivery** | Material received with the bill's quantity, even if the bill says "OPC 53 grade" / "TMT 12mm". |
| 19 | An attendance register photo -> tap **Attendance** | Labour card with the names or counts on the sheet. |
| 20 | Three photos in a row (a burst) | **One** "What is this photo for?" question, not three. |
| 21 | A PDF invoice (as a document, no button) | Read and saved as received material (or one clear question). |
| 22 | A blurry/unreadable photo -> tap Expense | Asks for the amount; nothing saved. |

## D. Back today (test only after Claude says "features 2-4 deployed")

| # | Send | Expect |
|---|---|---|
| 23 | `add Ravi Kumar to Green Villa as supervisor` (a new person) | Asks for his phone number, then confirms creating him and adding him to the project. |
| 24 | `plastering 2nd floor, another 40 sqm done` then `correction, that was 30 sqm` | Asks Yes/No to change that 40 sqm to 30 sqm. (A brand-new entry is fixed with Cancel/UNDO instead: the correction changes the last quantity added to ongoing work.) |
| 25 | `JCB is fixed` (after test 5) | Closes the JCB breakdown issue, asks to confirm. |

## Report back

Say plainly what could not be tested and why (role, module off, no photo to send). A test
that could not run is NOT TESTABLE, not a pass. List anything odd even on a PASS (wording,
slowness, a wrong number).
