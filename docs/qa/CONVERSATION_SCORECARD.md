# Conversation scorecard — the WhatsApp assistant

A fixed set of 25 messages a site engineer really sends, scored **0–2** each, so
"how good is the assistant" is a number we can compare before and after a change
(request 57, A1). Run it by hand on the live number after a deploy (about 10
minutes; mind the 10-messages-per-hour test limit — send them in two batches) and
write the total at the bottom. The rows marked **offline** are also run in
`apps/whatsapp-assistant/tests/replay/test_conversation_scorecard.py` and
`tests/unit/`, with the model scripted, so a regression in what a reply *says*
fails the build before it reaches a phone.

## How to score one message

| Score | Means |
|---|---|
| **2** | Right thing saved/answered **and** the reply says exactly what was saved from the saved data (not the worker's raw words), in the worker's language and letters. One message, no repeat. |
| **1** | Right outcome, but the reply is vague ("Recorded"), repeats the worker's words, uses the wrong script, or needs a second message to be understood. |
| **0** | Wrong or missing record, a wrong "finished", a question echoed back and lost, an error text for a normal request, a double message, or silence. |

Total out of **50**. Baseline before request 57 (Ilan's live test, 19 Oct): **6.5 / 10 ≈ 33 / 50**.
Target after: **≥ 42 / 50**, with no 0 in rows 1–10 (the daily basics).

## The 25 messages

| # | Message (as typed) | What must happen | Offline test |
|---|---|---|---|
| 1 | `6 mason, 10 helper vannu` | `✅ Saved: 16 workers (6 mason, 10 helper)` — English letters back (Manglish) | `test_scorecard_1_labour_manglish` |
| 2 | `ഇന്ന് 3 മേസൺ പണിക്ക് വന്നു` | Saved list with Malayalam label words, numbers/trade unchanged | `test_a_malayalam_note_gets_the_saved_list_then_the_models_own_words` |
| 3 | `12 masons and 5 helpers today` | `16`-style total with per-trade split; one reply | `test_scorecard_3_labour_english` |
| 4 | `Plastering 2nd floor 40% aayi` | Activity at **40%**, never "finished"; reply `Plastering, 2nd floor: 40%`; card `Plastering · 2nd floor · 40%` | `test_scorecard_4_percentage_is_progress_not_finished` |
| 5 | `180 sqm plastering done on second floor` | `Plastering, second floor: 180 sqm` | `test_a_four_part_note_is_four_saves_one_reply_and_no_site_question` |
| 6 | `plastering finished 2nd floor` | Saved as **completed** (100%) — the one case "finished" is right | `test_scorecard_6_finished_is_completed` |
| 7 | `started shuttering 3rd floor` | `Shuttering, 3rd floor` saved as started | live only |
| 8 | `25 bags cement vannu` | `Cement in: 25 bags` | `test_scorecard_8_material_in` |
| 9 | `5 bags cement use cheythu slab ku` | `Cement used: 5 bags` | `test_scorecard_9_material_used` |
| 10 | `rain stopped work 2 hours` | `Issue (weather): …`, delay recorded | covered in the 4-part test |
| 11 | `paid 4500 for tipper hire` | asks Yes/No once; after Yes `Expense ₹4500 (…)` — **one** message each time | `test_confirm_reply_executes_domain_write_and_replies_recorded` |
| 12 | `Yes` (after 11) | one saved reply with the amount, no second message | `test_confirm_reply_executes_domain_write_and_replies_recorded` |
| 13 | `6 mason, 10 helper vannu. Nale slab concrete cheyyan pattumo?` | labour saved **and** the question saved: `Question for your engineer: …`; the question is not just echoed | `test_scorecard_13_question_in_a_note_is_noted` |
| 14 | `can we pour the slab tomorrow?` (alone) | a real answer or an honest "noted for your engineer" | live only |
| 15 | `what did I log today?` | answer from the site log (existing query) | live only |
| 16 | `how many workers today?` | answer from attendance records | live only |
| 17 | `how much cement is left?` | stock answer | live only |
| 18 | `Send me today's report` | the PDF, or "being prepared", or "no report yet" — **never** "I can't look up today's report" for a normal worker | `test_level_is_compared_as_the_postgres_enum_not_as_varchar` |
| 19 | `send yesterday's report` | that day's report; names the day | `test_a_named_past_day_looks_up_that_day_and_says_which_day` |
| 20 | `send me the report for last friday` | asks which day (does not send today's) | `test_an_unreadable_or_future_day_is_asked_about_not_answered_with_today` |
| 21 | `undo` | removes the last saved update, says which | live only |
| 22 | a 4-part note (labour, work, cement, rain) | **one** reply, one bullet per record, no "which site?" | `test_a_four_part_note_is_four_saves_one_reply_and_no_site_question` |
| 23 | a voice note in Malayalam | transcribed, saved, reply in Malayalam script | live only |
| 24 | a photo of a bill | expense draft from the bill | live only |
| 25 | `hi` | a one-line greeting in the worker's language, no menu wall | live only |

## What the card must show (rows 4, 5, 8, 11)

Header says the place **once** (`Green Villa, Kakkanad`, not twice when project and
site share a name). Work row `Plastering · 2nd floor · 40%`. Checked offline in
`tests/unit/test_progress_percent.py`; on a phone it still needs a screenshot.

## Result log

| Date | Build | Score /50 | Notes |
|---|---|---|---|
| 2026-10-19 | `5a0bb2e` (before request 57) | ≈ 33 | Ilan's live test: report error, question echoed, raw words in bullets, "finished" at 40%, name twice. |
| _after deploy_ | _fill in_ | | |
