# 27 Oct 2026 — WhatsApp assistant live test rounds

Eight live test rounds against the WhatsApp assistant, run by the bot (Claude Code driving the
`assistant-test` chat) in the **TEST company only** ("Mesiri Test Builders"). Requested by Ilan in the
team group "Mesiri group with ai" (#3979: "message tests of various modules, up to 10 screenshots"), and
put in git at Ilan's request (#4367) so the rounds can be researched with Claude Code.

| File | What it is |
|---|---|
| [`screenshots/`](screenshots/) | 19 rendered chat screenshots the bot posted to the team group, numbered in posting order |
| [`transcripts.md`](transcripts.md) | Every message of the test chat for 27 Oct, per round, bot replies verbatim incl. buttons |
| this README | Pass/fail per round, where each failure went, root cause, reply times, open items |

Message numbers like `#4053` are the team group's / test chat's message ids (`python3 teammate/inbox.py show <n>`).

**Privacy.** TEST company only, no customer data. Phone numbers are cut to the last 4 digits. The message in
which the admin login was pasted into the group (#4084) is deliberately **not** included, nor any credential.
(That password is still in the group's history; it should be changed.)

**Notes on evidence**
- The screenshots are *renderings* of the chat made by the bot (`teammate/chat_image.py`), with ✅/❌ notes the bot
  added. They are the bot's reading of the transcript, not WhatsApp screen captures.
- The "+N s" per-reply timings were measured by the test tool live and are **not** stored in the inbox, so
  `transcripts.md` has no `+N s`. The measured numbers are in the [reply-time table](#reply-times) below.
- The bot's findings messages for rounds 1 and 2 were posted as #4057 and #4134; later rounds' summaries
  are #4168, #4202, #4253, #4285, #4318, #4356 (the numbers listed in the request, #4053 / #4128 / #4161 / #4199 /
  #4246 / #4283 / #4313 / #4353, are not in the inbox; these are the nearest actual ones).

## Timeline and plans

| Time (IST) | Plan | What |
|---|---|---|
| 11:26 | — | Ilan asks for message tests; test plan #3980; "Go start" #3983 |
| 11:43 | [122] | Round 1 findings (#4057). Patch plan for items 1–5 (touches Labour) |
| 12:08 | [123] | Ilan asks for an architecture-level fix, not patches. Root cause: one design flaw. **[123] P0**: ADR + golden tests (docs/tests only) |
| 12:15 | [123] P0 | Pushed `7fda65b`; ADR [`docs/architecture/ADR-draft-per-message.md`](../../../architecture/ADR-draft-per-message.md) |
| 12:17–13:04 | [124] | **P1**: `MessageDraft`, one card, Save in one transaction (labour, materials, work, issues), TEST company only behind flag `draft_v2`. Migration 0491 (additive). Deployed, run 1103 |
| 13:23–15:22 | [125], [126] | Turning `draft_v2` on needed platform-admin; the session was blocked by the permission guard, so [126] added an On/Off switch for `draft_v2` in the control panel (Companies → Settings) |
| 15:40 | | Round 2: P1 live with `draft_v2` ON |
| 15:48 | [127] | Round 3 (re-test); **P2**: corrections on drafts, one day-figures read path, P1 polish. Deployed `5da06ff`, run 1115 |
| 16:39 | [128]→[129] | Round 4: P2 live. [128] replaced by [129] after Ilan questioned "last saved site today" |
| 16:50 | [130] | Round 5 extra tests; [130] polish plan (later folded into [131], then [132]) |
| 17:03 | [129] | Pushed `a3945b8` (steel-unit line, 3 h site window + Change site button, wording) |
| 17:20 | [131]→[132] | Round 6: [129] live re-test. Ilan asked "why at root level?" → #4287. [131] replaced by **[132] (P2.5)** |
| 17:28 | [117] | Bot upgrade: test tool reports reply time per message; pushed `0ca56e2` |
| 17:36 | | Round 7: timing + regression found |
| 17:49 | [132] | Pushed `7179a33`, run 1118 (scripted-AI tests only) |
| 18:09 | [133] | Round 8: [132] live re-test, 3 pass / 4 fail → [133] (fix + "must pass LIVE before done" rule) |
| 19:52 | [134] | This folder |

## Round by round

### Round 1 — old flow, before any fix (11:29–11:43, screenshots 01–08)
Tests 1–8 below, ~30 messages. Test chat #3985–4052, findings #4057.

| # | Test | Result | Screenshot |
|---|---|---|---|
| 1 | Labour: "8 mason 5 helper vannu" → Save → "alla, 6 mason aanu" | ❌ Save works; the correction says "6 mason aakki" but nothing changes (still 8) | [01](screenshots/01-test1-labour.png) |
| 2 | Materials: "20 rod steel used" + cement arrived | ❌ Steel vanished from the card; only cement offered | [02](screenshots/02-test2-materials.png) |
| 3 | Work progress: plastering % + "120 rft skirting" | ❌ Floor/% understood; skirting dropped | [03](screenshots/03-test3-work-progress.png) |
| 4 | Full 4-part site note | ❌ Worst: labour saved **without a tap** and **replaced** the earlier count; cement + breakdown lost; Cancel says "nothing recorded" (untrue) | [04](screenshots/04-test4-site-note.png) |
| 5 | Issues: "mixer breakdown aayi", then "mixer ready aayi" | ❌ Closing works; **reporting** gives a friendly reply, nothing saved | [05](screenshots/05-test5-issues.png) |
| 6 | Questions and reports | ❌ Past-day reports work; labour figures disagree (today 8, report 13, yesterday 13); "what was done today" empty | [06](screenshots/06-test6-questions-reports.png) |
| 7 | Team and setup | ❌ Report time can't be changed; can't list the team; "make Rajesh supervisor at Site B" → wrong role (Site Engineer) and wrong place | [07](screenshots/07-test7-team-setup.png) |
| 8 | Edge cases | ✅ undo, Malayalam script, switched-off expense module · ⚠️ chit-chat and "who's on my team" get the odd "I only give join codes" | [08](screenshots/08-test8-edge-cases.png) |

Not tested: photos (no test image), voice (→ [117]). Plan: the 5 data problems → **[122]**, replaced by the architecture plan **[123]**.
Items 6–8 (report time, team list, wrong role) went to **P3** (not built, see open items).

### Round 2 — P1 live, `draft_v2` ON (15:40, screenshots 09–10)
Test chat #4100–4127, findings #4134 ("P1 works").

| Check | Result | Screenshot |
|---|---|---|
| 4-part note → one card with all items | ✅ | [09](screenshots/09-p1-live-note.png) |
| Nothing written before Save; Cancel is true | ✅ today's labour unchanged after Cancel | 09 |
| Plastering + skirting both on the card | ✅ | 09 |
| "Mixer breakdown aayi" → issue card → saved → in "open issues?" | ✅ | [10](screenshots/10-p1-live-continued.png) |
| 2nd labour count → "Already 13, replace or add?" → Replace → "Mason 8 → 6, Helper 5 → 2"; "innu ethra labour?" = 8 | ✅ | 10 |
| Replace/Add question shown twice in one message | ❌ small | 10 |
| Steel waiting for its unit asked in text but not listed on the card | ❌ small | 10 |
| Replies in English to Manglish | ❌ ([116]) | — |

Next plan: **[127]** (P2). Corrections and "yesterday" not yet tested here.

### Round 3 — re-test of screenshots 1, 6, 7, 8 with `draft_v2` ON (15:48, screenshot 11)
Test chat #4136–4160, findings #4168 (asked by Ilan in #4135: "did you test the same questions?").

| Check | Result |
|---|---|
| Labour figures agree ("today" and report both 8) | ✅ (was 8 vs 13) |
| "Yesterday" no longer returns today's figure | ✅ |
| A correction no longer *claims* a change it didn't make | ✅ |
| Chit-chat gets a natural answer ("I don't check cricket scores, only site things") | ✅ |
| Correction after Save ("alla, 5 mason") not possible, wrongly says "tap Cancel" | ❌ → [127] |
| Report says 1 open issue, there are 2 | ❌ → [127] |
| "What was done today?" leaves out today's 8 workers | ❌ → [127] |
| Malayalam labour message went to **Site B** without asking (site taken from the Rajesh message) | ❌ → [127] |
| Replace/Add shown twice, steel unit not on card | ❌ → [127] |
| Wrong role for "supervisor", "Reply YES" card, report time, team list | ❌ → P3 |

Screenshot: [11](screenshots/11-retest-1-6-7-8.png).

### Round 4 — P2 live re-test (16:39, screenshot 12)
Test chat #4176–4198, findings #4202.

| # | Check | Result |
|---|---|---|
| 1 | Correction "alla, 5 mason" → card "mason 6 → 5 (total 7)" → Save → 7 workers | ✅ |
| 2 | "What was done today", report, "open issues" agree: 7 workers, 2 issues | ✅ |
| 3 | Replace/Add shown once | ✅ |
| 4 | Steel unit: "Ethra kg aanu 20 rod?" asked, but steel **still not on the card** | ❌ → [129] |
| 5 | Site guessing: Malayalam "4 mason" after the Rajesh/Site B message again went to **Site B** unasked (Yes/No warning shows) | ❌ (half) → [129] |
| – | Wording: before Save a correction says "maatti…aakki" (changed); the warning is English inside a Malayalam reply; Replace/Add card says "tap Save" with no Save button | ⚠️ → [129] |

Screenshot: [12](screenshots/12-p2-live-retest.png). Plan **[128]** (steel, site, wording) was replaced by **[129]** after Ilan
questioned the "last *saved* site today" rule (#4203/#4205). [129]'s rule: one site → that site; named in message → that site;
saved update in last 3 h → that site **shown on the card with a "📍 Change site" button**; otherwise ask "Which site?"; never from
cancelled cards or team messages.

### Round 5 — extra tests A/B/C while [129] was built (16:50, screenshots 13–15)
Test chat #4211–4245, findings #4253. ~20 messages.

| | Works | Found |
|---|---|---|
| A ([13](screenshots/13-extra-a-merge-undo.png)) | Two messages in a row → **one card**; undo after Save per item or all, figures go back | Asked "which site?" though the message said Green Villa; stray "Not saved (…):" line |
| B ([14](screenshots/14-extra-b-transfers.png)) | Transfer "20 bags cement Green Villa → Site B" perfect; English site note; Hindi "mistri" = mason | Plywood "10 sheets in nos?" pointless and plywood left off the card; Hindi message got an English/Manglish reply and a "select" that doesn't exist; holiday card doesn't name the site |
| C ([15](screenshots/15-extra-c-questions-help.png)) | Manglish + Malayalam questions answered well; week summary short and useful | Help offers expenses (switched off), no examples; a rain issue from 24 Oct called "rain today" |

Seven findings → plan **[130]**, later replaced by **[131]**, then **[132]**.

### Round 6 — [129] live re-test (17:20, screenshot 16)
Test chat #4256–4282, findings #4285.

| Check | Result |
|---|---|
| 📍 Change site button moves everything on the card | ✅ |
| Typed "cancel" works | ✅ |
| Yes/No warning in Malayalam | ✅ |
| Site B still picked after the Rajesh message (nothing saved on Site B today) | ❌ |
| "Green Villa ground floor tiling…" still asks which site | ❌ |
| Steel in rods can't be saved: button "1 rod = X kg"; after 12 kg: no Save button and "for Unknown purpose"; internal note leaks ("(closed: not to be asked again…)"); typing "save" → "I don't know the unit rod" | ❌ |

Screenshot: [16](screenshots/16-129-live-retest.png). Plan [131], replaced by **[132]** after the root-cause question (below).

### Round 7 — reply times and a regression (17:33–17:36, screenshots 17–18)
Test chat #4300–4312, findings #4318. See [Reply times](#reply-times).

The same 4-part note that worked in Round 2 now **regressed after [129]**: drops the mixer breakdown, asks "which site?" inside a
card that already says Green Villa, and the card is thrown away on the next message. Screenshot: [18](screenshots/18-regression-after-129.png).
Handed to [132] ("also fix the 4-part note regression from #4298").

### Round 8 — [132] live re-test (18:09, screenshot 19)
Test chat #4324–4354, findings #4356 / #4357. [132] was tested only with a *scripted* AI before this.

| Check | Result |
|---|---|
| Site B no longer guessed after the Rajesh message; asks which site | ✅ |
| Holiday card names the site | ✅ |
| Hindi gets a Hindi reply | ✅ |
| "4 mason" merged with the 4-part note from 30 min earlier (a card the worker had thrown away) | ❌ stale card revived |
| "Green Villa ground floor tiling 70% aayi" → "no card is open"; treated as an edit, nothing saved | ❌ |
| Steel: line on the card but only a Cancel button; "12 kg" answer ignored; line shown **twice**; cannot save | ❌ |
| Help shows the old menu incl. switched-off Money and Reminders | ❌ |

Screenshot: [19](screenshots/19-132-live-retest.png). → plan **[133]**: fixes the 4 above, plus a new rule: *a WhatsApp fix only counts as done
after it passes against the real AI with the exact test messages, replies in the report.*

## Where each failure went

| Plan | Covers | Status at 20:00 |
|---|---|---|
| [122] | Round 1 patch plan (items 1–5) | dropped, superseded by [123] |
| [123] P0 | ADR + golden tests (4 failing by design) | done, `7fda65b` |
| [124] (P1) | One draft/card per message, nothing before Save, issue cards, Replace/Add (flag `draft_v2`, TEST company) | done, deployed run 1103 |
| [126] | Control-panel switch for `draft_v2` | done |
| [127] (P2) | Corrections on drafts, one day-figures read path, small P1 polish | deployed `5da06ff`; items 4–5 failed live |
| [128] | Steel unit, never guess site | replaced by [129] |
| [129] | Steel-unit line, 3 h site window + Change site, wording | deployed `a3945b8`; 3 still failed live, regression found |
| [130], [131] | Polish list; [129] re-test failures | folded into [132] |
| [132] (P2.5) | Draft owns site + questions; code renders every card; model can't fake cards | deployed `7179a33`; 4 still failed live |
| [133] | Stale card revived, update seen as edit, steel answer, help menu, + "must pass LIVE" rule | **in progress** at the time of writing |
| [117] | Test tool reports reply time per message, can send voice notes | done `0ca56e2` |

## Root-cause notes

Bot message #4060 (after Round 1), #4287 (after Round 6) and the ADR
[`docs/architecture/ADR-draft-per-message.md`](../../../architecture/ADR-draft-per-message.md).

**After Round 1 (#4060): one design flaw, not five bugs.**
- It *saves first and asks after*: each item is written straight away, "Save" only confirms, "Cancel" deletes it. So when a step slips, labour stays saved and Cancel says "nothing recorded".
- Only **one** item can wait per person (the old flows allow one pending question). Everything else is parked, comes back one at a time, or is lost: steel, skirting, cement, breakdown.
- Waiting items live in **5 different places**, so a correction can't find what to change.
- Each question computes day figures **its own way** (8 vs 13).
- The upgrade: one draft per message on one card; written only on Save; questions as buttons on the card; one read path for day figures; then delete the old YES/NO flows.

**After Round 6 (#4287): P1/P2 moved only the *saving* onto the draft; the *understanding* side still had its own memory.**
1. *Site B:* a separate "current site" memory. Any site mention, even a team message ("make Rajesh supervisor at Site B"), is remembered until midnight and a later save on another site doesn't override it. The "which site?" question also had its own name matching, so "Green Villa *ground floor*…" wasn't recognised.
2. *Steel:* "How many kg per rod?" was asked *before* steel is on the card, so steel never got a line and the 12 kg answer attached to nothing.
3. *Leaked note:* old questions are marked "(closed: not to be asked again…)" in the history the AI reads; the AI copied it. It also wrote its own "To save…" text with no real card behind it, so no Save button.
- Fix [132]: the **site is part of the draft**, decided in one place; **questions are lines on the card**; **only code draws cards** (AI says one sentence; fake card text and internal notes are filtered); the AI gets a clean draft summary, not raw history.

**After Round 8 (#4356):** every fix passed the developer's tests because those use a *scripted* AI, not the real one. Hence the [133] rule.

## Reply times

Measured by the test tool (screenshot [17](screenshots/17-reply-times.png), message #4318), whole-second WhatsApp timing, 27 Oct 17:33.
An earlier "20–25 s" stopwatch figure was wrong (it included the tester's own overhead).

| Message | First reply |
|---|---|
| Button tap (Replace / Cancel) | 2.6 – 2.7 s |
| "hi" (menu) | 3.6 s |
| Long 4-part site note | 8.1 s |
| Question ("cement stock?") | 8.4 s |
| Labour message | 8.5 s |
| Past-day report (PDF + text) | 6.0 s / 10.1 s |
| Voice note | not measured (tool needed a restart to send audio) |

At Round 8 (#4356): taps ~2.5 s, AI messages 6–8 s. Anything through the AI is ~8 s; making that faster needs a faster model/step and production step timings.

## Open items (end of day 27 Oct)

1. **[133]** — the four Round 8 failures + "must pass LIVE" rule (in progress).
2. **P3 — Team & setup** (needs its own ok: user and role changes): "supervisor" becomes Site Engineer; adding a person takes 3 Yes taps; old "Reply YES" cards; can't list the team; can't set the report time.
3. **[116]** — one language per reply; Malayalam/Manglish wording list (remaining parts).
4. **P4** — switch `draft_v2` on for real customers; delete the old YES/NO flows.
5. **Not yet checked:** correction says "maatti" (changed) before Save; Replace/Add card says "tap Save" without a Save button (probably fixed by [129]).
6. **[117] follow-up** — voice notes untested; the bot's read access to production is still blocked (needed for step timings).
7. **Photos** never tested (no test image).
8. **Overnight downtime** of 27 Oct (down 05:01 IST, up 07:53, cause unknown, the alarm ran only 4× in 12 h) — see #3972/#3973.
9. **Security:** the admin password pasted in the group (#4084) is still in history; change it and keep it as a server secret only.
10. A pending reminder before report time when a card hasn't been saved (suggested in #4069) is not built.

## Data left in the TEST company

Green Villa today: 7 workers (5 mason, 2 helper), 2 issues (incl. "mixer breakdown"), "tiling ground floor 50%". Everything else was cancelled or undone.
