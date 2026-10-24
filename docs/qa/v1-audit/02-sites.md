# 02 · Sites — V1 audit

15 problems found in how Mesiri picks the site for an entry; 4 of them save to the
wrong site or lose the message.

- **Audited:** 23 Oct 2026 · **Original sheet:** [Sites — WhatsApp test sheet](https://claude.ai/artifact/DJ8nNXh2ygpAPJXf5mgqgv)
- **Main code:** the morning "Where are you working today?" question and today's site
  (WA-45): `apps/whatsapp-assistant/src/runtime/agent/work_site.py`; scope rules:
  `apps/whatsapp-assistant/src/runtime/agent/entry_base.py` (`settle`, `_scope`).
- **Not verified:** the live AI's wording.

## Summary

| ID | Problem | Severity | Approval |
| --- | --- | --- | --- |
| SIT-01 | A site name Mesiri can't match is saved to today's site | Serious (wrong data) | None |
| SIT-02 | A second message before tapping drops the first | Serious (lost message) | None |
| SIT-03 | Typing the site name loses the waiting message | Serious (lost message) | None |
| SIT-04 | A late tap loses the waiting message | Serious (lost message) | None |
| SIT-05 | One entry for another site moves the whole day there | UX | None |
| SIT-06 | Same site name in two projects shows identical buttons | UX | None |
| SIT-07 | "Good morning" at any hour | UX | None |
| SIT-08 | The site question is only in English | UX | None |
| SIT-09 | Only 10 sites shown | UX | None |
| SIT-10 | Multi-site workers get answers with less context | UX | None |
| SIT-11 | The text card doesn't say which site | UX | None |
| SIT-12 | The switch tip names a site they may not have | Small | None |
| SIT-13 | Site-name spotting is too loose ("main" in "maintenance") | Small | None |
| SIT-14 | PMs and Finance are asked every morning | Small | None |
| SIT-15 | Asked again just after midnight | Small | None |

## Before you test

Use one **Site Engineer** number in the test company with these sites (dashboard **Team** page):

| Project | Sites the engineer can report on |
| --- | --- |
| Project A | Site A, Tower 1 |
| Project B | Site A, Site B |

Two projects both having a **Site A** is on purpose (SIT-05, SIT-06).

- Start each "first message" test on a fresh day, or reset today's site.
- After every save, check on the dashboard **which site** the entry is under.
- Send each message on its own and wait for the full reply.

## Problems

### SIT-01 · An unmatched site name is saved to today's site

- **Severity:** Serious (wrong data) · **Approval:** None
- **Repro:** `now at Site B`. Then each: `5 masons at Site Z`, `5 masons at Sight B` (typo), `5 masons at Tower 9`.
- **Expected:** "Which site?" with their sites as buttons.
- **Actual:** each is saved under **Site B** with no question. Confirmed in code for 4 of 7 cases: unclear, misspelt, unknown, another company's site.
- **Code (start here):** `apps/whatsapp-assistant/src/runtime/agent/entry_base.py` (`settle` / `_scope`: where a named site that matches none of the sender's sites ends up on today's site).
- **Fix direction:** a site name that was said but not matched must be asked about, never replaced by today's site.

### SIT-02 · A second message before tapping drops the first

- **Severity:** Serious (lost message) · **Approval:** None
- **Repro (fresh day):** `50 bags cement arrived`. Don't tap. Send `12 masons today`, then tap a site.
- **Actual:** only the masons entry appears. The cement message is gone.
- **Code:** `apps/whatsapp-assistant/src/runtime/agent/work_site.py` (one held message per sender).
- **Fix direction:** hold every message sent before the tap and run them all after it, in order.

### SIT-03 · Typing the site name loses the waiting message

- **Severity:** Serious (lost message) · **Approval:** None
- **Repro (fresh day):** `50 bags cement arrived`. Type `Site B` instead of tapping.
- **Actual:** Mesiri switches to Site B, but the cement entry is never made.
- **Fix direction:** a typed site name that matches one of the list rows answers the question, and the held message runs.

### SIT-04 · A late tap loses the waiting message

- **Severity:** Serious (lost message) · **Approval:** None
- **Repro (fresh day):** `50 bags cement arrived`. Wait 2+ hours, then tap a site.
- **Actual:** "👍 Site B for today" and nothing else; the cement entry is never made.
- **Fix direction:** keep the held message for the whole day, or say plainly that it expired and ask them to resend.

### SIT-05 · One entry for another site moves the whole day there

- **Severity:** UX · **Approval:** None
- **Repro:** `now at Site B`, then `3 masons at Tower 1`, then `5 helpers`.
- **Actual:** the helpers go to **Tower 1**, and Mesiri never said it switched.

### SIT-06 · Same site name in two projects shows identical buttons

- **Severity:** UX · **Approval:** None
- **Repro:** `now at site a`
- **Actual:** buttons read "Site A", "Site A" with no project name.

### SIT-07 · "Good morning" at any hour

- **Severity:** UX · **Approval:** None
- **Repro (fresh day, after 7 PM):** `10 masons today`
- **Actual:** the question starts "Good morning" at night.

### SIT-08 · The site question is only in English

- **Severity:** UX · **Approval:** None
- **Repro (fresh day):** `innu 50 chakku cement vannu`
- **Actual:** "Where are you working today?" and the reply after the tap are in English.

### SIT-09 · Only 10 sites shown

- **Severity:** UX · **Approval:** None
- **Repro:** give the engineer 12 sites; fresh day: `cement came`
- **Actual:** only 10 sites in the list; typing the 11th loses the message (SIT-03).
- **Note:** WhatsApp lists allow 10 rows; the fix is a "Something else" row or typed-name matching.

### SIT-10 · Multi-site workers get answers with less context

- **Severity:** UX · **Approval:** None
- **Repro:** `now at Site B`, then `is there enough cement for tomorrow?`
- **Actual:** the answer has no stock figures, while a one-site worker's does.

### SIT-11 · The text card doesn't say which site

- **Severity:** UX · **Approval:** None
- **Repro:** any save, e.g. `5 masons`
- **Actual:** the "📝 To save" lines name no site; only the receipt image does.

### SIT-12 · The switch tip names a site they may not have

- **Severity:** Small · **Approval:** None
- **Repro:** tap a site on the morning list.
- **Actual:** the reply says `like "now at Site A"` even when they have no Site A.

### SIT-13 · Site-name spotting is too loose

- **Severity:** Small · **Approval:** None
- **Repro:** name a site "Main"; fresh day: `maintenance work done`
- **Actual:** no morning question ("main" was spotted inside "maintenance").
- **Fix direction:** match whole words only.

### SIT-14 · PMs and Finance are asked every morning

- **Severity:** Small · **Approval:** None
- **Repro:** a PM number with 2+ sites, fresh day.
- **Actual:** they get the morning question; only Admins are skipped.

### SIT-15 · Asked again just after midnight

- **Severity:** Small · **Approval:** None
- **Repro (after 12 AM):** `night shift done, 4 masons`
- **Actual:** the site question comes again (the day ended at midnight).

## Already works

One-site workers are never asked; exact or lower-case site names land correctly;
closed sites don't appear in lists; Admins aren't asked every morning.

**Still waiting on Alan (WA-46):** a PM with "selected sites only" can't report on a site they create.

## Test results

| ID | Problem | Result | What Mesiri replied |
| --- | --- | --- | --- |
| SIT-01 | Unmatched site name goes to today's site | Not tested | |
| SIT-02 | Second message drops the first | Not tested | |
| SIT-03 | Typed site name loses the message | Not tested | |
| SIT-04 | Late tap loses the message | Not tested | |
| SIT-05 | One entry moves the whole day | Not tested | |
| SIT-06 | Identical "Site A" buttons | Not tested | |
| SIT-07 | "Good morning" at night | Not tested | |
| SIT-08 | Site question only in English | Not tested | |
| SIT-09 | Only 10 sites shown | Not tested | |
| SIT-10 | No stock context for multi-site | Not tested | |
| SIT-11 | Text card names no site | Not tested | |
| SIT-12 | Tip names a site they lack | Not tested | |
| SIT-13 | Loose site-name spotting | Not tested | |
| SIT-14 | PMs asked every morning | Not tested | |
| SIT-15 | Asked again after midnight | Not tested | |
