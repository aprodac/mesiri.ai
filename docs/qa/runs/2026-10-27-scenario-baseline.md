# 27 Oct 2026 — live scenario baseline (before phases 2–4)

WA-80's first run of [`scenarios_27oct.json`](../../../apps/whatsapp-assistant/tests/live/scenarios_27oct.json)
against the **real** assistant (TEST company, `assistant-test` chat), on the code **before** WA-81/82/83:
Claude ops run 40547971909, commit `05399dd`, 17:10–17:32 UTC, one run.

## What counts and what does not

- **Valid:** S01–S08 and S09 step 1 (old code, real model).
- **Not valid: S09 step 2 to S11.** The TEST company reached its **daily free-trial limit** (`trial_guardrails`:
  200 WhatsApp messages or ₹50 of AI a day, India time) and every message after it was answered "You've reached
  today's free-trial limit". Checks on those refusals measured nothing (some "passed"). The runner now stops on it.
- The deploy of WA-81..83 finished 17:32:06, after the last valid step (S09 step 1 ran before 17:31).
- Four checks were wrong and are fixed for the next run: the report is a PDF now (M18, M31 cannot be read from
  its text); "ethra open issues und?" returned the stock picture (M31 captured "207"); M22 and M24 passed on
  wording they should fail ("Sorry, … list tharunnilla", "Confirm cheyyan YES"). The two-message reset
  ("no", "cancel") was cut to "cancel": it cost trial messages and drew stray replies.

## Result (valid part)

| Result | Marks |
|---|---|
| **Fail** (bug confirmed live on the old code) | M01, M02, M30, M34 (blocked: "Green Villa: 8 mason 5 helper vannu" asked *which site?* although it names Green Villa) · M09, M12 (site question instead of the card) · M10, M50, M51 (the 4-part note was swallowed by "holding 4 messages… which site?") · M11, M53, M54 (follow-ons) · M45, M47, M48, M56, M57 ("oru rod 12 kg" → "holding 2 messages… which site?" → "I don't know the unit rod", steel lost) · M49 (11.2 s for the kg answer) · M20, M21, M23 (team & setup, W8) · M25 ("Sorry, I don't understand", no example) |
| **Fail, check was wrong** | M18, M31 (see above) |
| **Pass** | M03, M04, M05, M06, M07, M08, M13, M14, M15, M16, M17, M28, M29, M32, M41, M44, M46, M52 |
| **Pass, check was wrong** | M22, M24 (the answers were refusals) |
| **Observed** | M19: today's report comes as a PDF plus "Today's DPR is attached." |
| **Not measured (trial limit)** | M26, M27, M33, M35, M36, M37, M38, M39, M40, M42, M43, M55, M58 |

## What the old code did, in its own words (from the run)

- `20 rod steel use cheythu, 100 bags cement vannu` → card with cement and "Steel used: 20 rod (❓ How many kg is 20
  rod?)"; then `oru rod 12 kg` → "Got it 👍 I'm holding 2 message(s) until you pick the site. Which site is this
  for?"; then `save` → "I don't know the unit "rod". Not saved, because no site was picked: “oru rod 12 kg”, “oru rod
  12 kg”." — the two stores of 27 Oct (draft card and site queue) disagreeing, live.
- The 4-part note after a saved count → "site select cheyyunnath vare 4 message njan pidichu vachittund. Ee update
  ethu site-inte aanu?" — nothing on the card; next message: "Not saved, because no site was picked: …" four times.
- `asdfgh kkkk` → "Sorry, I don't understand "asdfgh kkkk". Is it about site work?"
- `report time 7 pm aakku` → "Sorry, I can't change report timings yet." (English to Manglish).
