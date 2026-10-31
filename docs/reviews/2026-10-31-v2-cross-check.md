# Cross-check of the assistant against real conversations, 27-31 Oct 2026 (request 185)

All 761 production messages of 27-31 Oct (Mesiri Test Builders and Paraclette, the only two
companies; 105 voice notes) read next to what Mesiri answered. Rows are referred to by
correlation id suffix; message text stays in production (control plane), not here.

Measured again with `python3 scripts/v2_replay.py baseline` on the 5-day corpus (786 turns,
35 conversations): **severe findings on 6.0% of turns, 19 of 35 conversations clean.**

## Failure families

| # | Family | Count | Mechanism (root) |
|---|---|---|---|
| 1 | Forgets what it said; denies its own replies; loses the question it asked | every long conversation (`…0c9b628c`, `…792aa88b`) | Memory: `runtime/agent/history.py` shows the model a ≤400-char gist of each reply and **drops every question**; 10 turns, Redis TTL |
| 2 | "I can't see that message" on a swipe-reply, then contradicts itself | 7 (`…2961f003`, `…fc42b75e`) | Quoted words only if kept in `sent_text` (a week); media replies never |
| 3 | Dead end "send it again in one line" after a plain answer ("TMT steel", "50 bag = 1 load") | 12 (`…a3df0bd2`, `…c6d45768`) | The answer to a card question had no tool (fixed in part by WA-106 `answer_question`); unit questions still end there |
| 4 | Same question asked again and again ("which project?" x5, "tap ചെങ്കല്ല്" x4) | 2 exact + loops with varied words (`…a9ec007b`, `…5d3a61f1`) | Tap carried less context than the message; the model never sees its own question (family 1) |
| 5 | Answers what was not asked (whole inventory, twice after "I never asked") | 2 (`…29ae695e`, `…d977e763`) | Code-drawn stock answer added under a reply whose message did not ask |
| 6 | Talks about a "card" the user cannot see | 83 replies | Internal word in the prose |
| 7 | Wrong figures shown (negative stock, "339 used today", a load with no count) | 3+ | Books shown raw; units saved without a count |
| 8 | Says it can't do something, then does it (image, reminder) | several | Capabilities not stated to the model |
| 9 | AI outage: "I'll process this in a few minutes", then "send it again" | 18 | Provider failures; retry reply loses the message |
| 10 | Bill photo expense stuck: account answer ignored, Save failed 3x, date read as 30 Dec | 1 flow (`…498dfbb7`) | Expense question not answerable by text; OCR date |

What works: plain receipts, usage and labour in Malayalam voice, stock questions, new materials,
material requests reaching managers.

## What follows

1. Replay test (request 185 step 1, this commit): the corpus, the checks above as code,
   production's numbers as the baseline, replay through any engine.
2. v2 on Google ADK with full conversation memory in Postgres (fixes families 1, 2, 4).
3. Skills for every module, each family above as an `evals.yaml` case.
4. Live comparison (Gemini / Claude) on the replay, gate, switch every company.
