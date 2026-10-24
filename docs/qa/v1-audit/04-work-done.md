# 04 · Work done & Progress — V1 audit

7 problems found in Work done & Progress; the biggest is that work continuing from an
earlier day never reaches the DPR.

- **Audited:** 23 Oct 2026 · **Original sheet:** [Work done — WhatsApp test sheet](https://claude.ai/artifact/JGJiutqTtxzFVyd9Cbj4gC)
- **Main code:** WhatsApp entry `apps/whatsapp-assistant/src/runtime/agent/site_entry.py`
  (`SITE_UPDATE`); workflow `apps/whatsapp-assistant/src/workflows/site_update/`; DPR
  assembly `backend/src/mesiri/application/dpr/assembly.py` and
  `backend/src/mesiri/infrastructure/postgres/repositories/dpr.py` (`assemble_site_report_payload`).
- **Verified:** by reading the DPR code and the unit list; a phone test confirms them live.

## Summary

| ID | Problem | Severity | Approval |
| --- | --- | --- | --- |
| WRK-01 | Work continued on a later day never reaches the DPR | Serious (missing data) | None |
| WRK-02 | Common units refused (metres, rft, "sq ft", m2, m3), nothing saved | Serious (lost entry) | None |
| WRK-03 | "What was done yesterday?" answers today | Serious (wrong answer) | None |
| WRK-04 | Only 6 open jobs are tracked | Other | None |
| WRK-05 | Multi-site workers lose the link to open work | Other | None |
| WRK-06 | A correction only works in the same chat session | Other | None |
| WRK-07 | Work photos lost on restart | Other | Ops (INF-09) |

## Before you test

Use a **Site Engineer** number with **one site**. WRK-01 runs over **two days**, so start it first.

- Tap **Save** on every card.
- DPR: `send today's report`; yesterday's: `yesterday's report`.
- Check the dashboard **Today** page as well as the DPR.

## Problems

### WRK-01 · Work continued on a later day never reaches the DPR

- **Severity:** Serious · **Approval:** None
- **Repro:** Day 1: `started brickwork ground floor`. Day 2: `brickwork 60% done`, then `brickwork finished`.
- **Expected:** day 2's DPR lists brickwork at 60% and then finished.
- **Actual:** day 2's DPR has **no** brickwork at all.
- **Code:** the DPR lists only activities whose `activity_date` is the report date; the day's `progress_updates` rows are never read. The same rule drives the Today page's `work_items` (`list_site_days` in `dpr.py`), so the site also shows "hasn't reported today" (see DSH-04).
- **Fix direction:** include activities with a progress update on the report date, showing that day's update.

### WRK-02 · Common units refused, nothing saved

- **Severity:** Serious · **Approval:** None
- **Repro:** each alone: `50 meter wiring done`, `120 rft skirting done`, `200 sq ft tiling done`, `20 m3 concreting done`
- **Actual:** Mesiri says it isn't saved ("not a recognized unit"). Known units: sqm, sqft, cum, cft, nos, load, bags, kg. No metres or running feet, and no "sq ft", "m2", "m3" spellings.
- **Fix direction:** add rm/m/metre, rft/running feet, and spelling aliases (sq ft, sq.ft, m2, m², m3, m³).

### WRK-03 · "What was done yesterday?" answers today

- **Severity:** Serious · **Approval:** None
- **Repro:** after saving work today: `what work was done yesterday?`
- **Actual:** the answer lists **today's** work.
- **Code (start here):** `_seed_activity_search` in `apps/whatsapp-assistant/src/runtime/inbound_journey/seeding.py`; `date_range` of `query_work_log` in `apps/whatsapp-assistant/src/runtime/agent/tools.py`. Same pattern as ATT-04.

### WRK-04 · Only 6 open jobs are tracked

- **Severity:** Other · **Approval:** None
- **Repro:** start 7 jobs (`started plastering 1st floor`, `started wiring`, …), then `<7th job> finished`.
- **Actual:** a **second** entry for the 7th job is made instead of finishing it.

### WRK-05 · Multi-site workers lose the link to open work

- **Severity:** Other · **Approval:** None
- **Repro:** give the engineer 2 sites, don't pick today's site: `started plastering`, then later `plastering finished`.
- **Actual:** two separate plastering entries.

### WRK-06 · A correction only works in the same chat session

- **Severity:** Other · **Approval:** None
- **Repro:** `180 sqm plastering 2nd floor`; next day `correction, that was 150 sqm`
- **Actual:** Mesiri says there is nothing to correct.
- **Code:** `apps/whatsapp-assistant/src/runtime/agent/change_entry.py` (`_correct`: only the activity this conversation last touched).

### WRK-07 · Work photos lost on restart

- **Severity:** Other · **Approval:** Ops (INF-09)
- **Repro:** send a progress photo for an entry; check it after the next deploy.
- **Actual:** the photo no longer opens. (Also see PHO-01: progress photos are not attached at all.)

## Already works

`yesterday 20 sqm …` is dated yesterday; the floor is kept (`2nd floor`); `started` then
`finished` on the same day joins into one entry; a percentage below 100 is never marked
finished; the same work reported twice on one day is flagged in the DPR for the engineer.

## Test results

| ID | Problem | Result | What Mesiri replied, or what the DPR showed |
| --- | --- | --- | --- |
| WRK-01 | Later-day work missing from DPR | Not tested | |
| WRK-02 | Common units refused | Not tested | |
| WRK-03 | "Yesterday" answers today | Not tested | |
| WRK-04 | Only 6 open jobs tracked | Not tested | |
| WRK-05 | Multi-site loses open-work link | Not tested | |
| WRK-06 | Correction only same session | Not tested | |
| WRK-07 | Work photos lost on restart | Not tested | |
