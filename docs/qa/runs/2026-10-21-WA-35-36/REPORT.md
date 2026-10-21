# WA-35 / WA-36 live test, 21 Oct 2026

> **TEMPORARY test evidence: delete this folder once the WA-35/36 follow-up fixes are verified live** (`git rm -r docs/qa/runs/2026-10-21-WA-35-36`).

- **Date:** 21 Oct 2026
- **Company:** Mesiri Test Builders (agent mode); **site:** Green Villa, Kakkanad
- **Tester:** the team bot, via `test_assistant`; 25 sends
- **Screenshots:** [1-save-button.png](1-save-button.png), [2-materials-stock.png](2-materials-stock.png), [3-general-malayalam.png](3-general-malayalam.png). They are redrawn from the assistant's real replies (`preview_html`), **not** phone captures.

## Passed

| Step | Result |
|---|---|
| "Innu 6 mason, 10 helper vannu. 20 bag cement use cheythu." | PASS: card "📝 To save: 16 workers (6 mason, 10 helper) / Cement used: 20 bags" with Save / Cancel / team photo |
| Tap Save | PASS: "✅ Saved." |
| Tap Save again | PASS: "That one is already done." |
| Cancel after Save | PASS: "Couldn't cancel 2 of them: it was already saved; fix it on the dashboard." (wording clumsy) |
| "3 carpenters today", then Cancel | PASS: card, then "❌ Cancelled. Nothing from that message was kept. Send it again the right way." |
| "How many workers today?" | PASS: "Today, 16 workers were on site: masons and helpers." (carpenters not counted) |
| "Received 50 bags cement", then typed "save" | PASS: "✅ Saved." |
| "സിമന്റ് സ്റ്റോക്ക് എത്ര ഉണ്ട്?" | PASS: "ഇപ്പോൾ 338 ചാക്ക് സിമന്റ് സ്റ്റോക്കുണ്ട്." (no Save button) |
| "cement vannu" | PASS: "എത്ര ചാക്ക് സിമന്റ് ആണ് വന്നത്?" |
| "ente peru ariyamo?" | PASS: name given |

## Failed

1. **FAIL 1: stock questions about the slab become engineer questions.** "nale slab-inu cement mathiyo?" and "is there enough cement for tomorrow's slab?" gave "📝 To save: Question for your engineer…" instead of an answer using the stock (338).
2. **FAIL 2: "saved" / "Recorded" before Save was tapped.** The engineer-question card says "…has been saved" / "സേവ് ചെയ്തിട്ടുണ്ട്"; the slab card's second message says "Material used: Recorded".
3. **FAIL 3: two replies to one message.** "slab-inu 20 bag cement use cheythu" gave the card plus "Not saved yet. Which site is this for? … 2. Work done (“slab”): Not saved yet", although the sender has only one site.
4. **FAIL 4: weather note saved without Save.** "ഇന്ന് മഴയാണ്, പണി കുറവാണ്" was saved straight away: "✅ Saved: Issue reported: WEATHER today, പണി കുറവാണ് … Wrong? Reply UNDO." (raw enum, old UNDO).

## Minor

- Supplier "Sharma Traders" is missing from the "Cement in: 100 bag" card.
- "50 bags cement" was assumed to be received (a received/used question was expected).
- "10 bag cement balance und, kooduthal venam" gave a good shortage card with stock 338/575/237, but no flag for worker's 10 vs system's 338.
- English "thanks bro 👍" got a Malayalam reply.

## Not verified

- The dashboard (today's report; stock page vs 338).
- Whether `4bcd6df` was the running build (GitHub runs are not reachable from the bot; the WA-35 behaviour was observed live).
