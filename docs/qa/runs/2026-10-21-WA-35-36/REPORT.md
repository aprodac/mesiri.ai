# WA-35 / WA-36 live test, round 2, 21 Oct 2026

> **TEMPORARY test evidence: delete this folder once the follow-up fixes are verified live** (`git rm -r docs/qa/runs/2026-10-21-WA-35-36`).

- **Date:** 21 Oct 2026, ~13:10-13:35 IST (round 2)
- **Company:** Mesiri Test Builders (agent mode); **site:** Green Villa, Kakkanad
- **Tester:** the team bot, via `test_assistant`; 37 sends
- **Screenshots:** [1](1-save-button.png), [2](2-materials.png), [3](3-stock-questions.png), [4](4-general-chat.png), [5](5-issues-reports-multipart.png). They are redrawn from the assistant's real replies (`preview_html`), **not** phone captures.
- **Replaces round 1** (morning, 25 sends); round 1 is in git history at `b3549d1`.

## Fixed since round 1

- Supplier is shown: "Cement in: 100 bag (Sharma Traders)".
- "slab-inu 20 bag cement use cheythu" gives one card "Cement used: 20 bag (slab)", no "Which site?".
- "50 bags cement" asks Received / Used.
- The rain note now uses the Save card.
- The Manglish greeting varies.
- The 3-part note "2nd floor plastering 50% aayi, 4 mason vannu, 15 bag cement use cheythu" gives one card with 3 lines.

## Results per group

### 1. Save button (screenshot 1): PASS
- Card with Save; Save again -> "That one is already done."
- Cancel after Save -> "Couldn't cancel 2 of them: it was already saved; fix it on the dashboard."
- "3 carpenters today", then Cancel -> "❌ Cancelled…"
- "How many workers today?" -> 16 (carpenters not counted).
- **WARN:** English messages are answered in Malayalam.

### 2. Materials (screenshot 2)
- PASS: supplier shown, slab purpose kept, Received / Used question.
- **FAIL:** garbled text "സ്ല clientIdb-ന്" in the slab reply.
- **FAIL:** "Received 40 bags sand from Kerala Sands" -> asks about cubic metres; answering "No" -> "No problem — please resend the report with the correct unit." The entry is dropped; it should save 40 bags.

### 3. Stock (screenshot 3)
- PASS: "സിമന്റ് സ്റ്റോക്ക് എത്ര ഉണ്ട്?" -> 318 (338 − 20 used today); "sand stock?" -> none recorded.
- **FAIL:** "nale slab-inu cement mathiyo?" and "is there enough cement for tomorrow's slab?" are saved immediately as a SITE ISSUE "Other" (receipt card "SAVED · DRAFT", SI-211026-4C64 / SI-211026-1E99) with no Save button and no stock-based answer. The English one repeats the "📨 Question for your engineer" line twice.
- **WARN:** "innale ethra cement use cheythu?" -> "total used 427" does not match the stock card (received 575 / used 237, so ~257 now).

### 4. General chat (screenshot 4): PASS
- "enthokke und vishesham?", "ningal aara?", "bore adikkunnu", "tell me a joke" (brick joke), "are you hardcoded", "thanks bro 👍" -> "Anytime! 👍".
- Note: Manglish is answered in Malayalam script.

### 5. Issues / reports / multi-part (screenshot 5)
- PASS: the rain Save card (**WARN:** says "രേഖപ്പെടുത്തിയിട്ടുണ്ട്" / recorded before Save); the 3-part card; "how many workers yesterday?" -> 16.
- **FAIL:** "10 bag cement balance und, kooduthal venam" says "tap Save" but has no button; already saved as an engineer question SI-211026-BBCE, with no 10-vs-318 check.
- **FAIL:** "innathe report ayakku" -> "today's DPR not prepared yet" despite today's saves ([67]).

## Open problems

1. Stock-sufficiency questions ("is there enough cement for the slab?", Malayalam and English) are saved as a site issue instead of answered from stock (318 bags); English one shows the engineer line twice.
2. "10 bag balance, kooduthal venam" says "tap Save" with no button; saved as an engineer question without a stock check.
3. Garbled word "സ്ല clientIdb-ന്" (a code word leaked into a reply).
4. Sand "No" (keep bags) -> "please resend"; the entry is dropped.
5. "innathe report ayakku" -> no DPR yet today, even with saves today ([67]).

Smaller: English messages get Malayalam replies; "recorded" said before Save on the rain card; "total used 427" disagrees with the stock card (~257).

## Test data left in Test Builders

- Site issues SI-211026-4C64, SI-211026-1E99, SI-211026-BBCE.
- Today's saved labour (16) and cement (used 20 at ~13:10, plus the round-1 saves).

## Not verified

- The dashboard (report, stock page).
- Which commit the VPS runs (GitHub runs are not reachable from the bot).
