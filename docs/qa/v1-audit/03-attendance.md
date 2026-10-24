# 03 · Attendance — V1 audit

10 problems found in Attendance; 6 put a wrong headcount in the DPR or the WhatsApp
answer. **All fixes are in the protected Labour module, so every one needs Alan's
approval before work starts.**

- **Audited:** 23 Oct 2026 · **Original sheet:** [Attendance — WhatsApp test sheet](https://claude.ai/artifact/PytQSqceGCxsykUk2rvy7w)
- **Main code:** WhatsApp entry `apps/whatsapp-assistant/src/runtime/agent/labour_entry.py`;
  backend `backend/src/mesiri/application/labour/` (mapper, repository);
  counting rules `backend/src/mesiri/infrastructure/postgres/repositories/workforce.py`
  (`live_report_sql`, `counted_line_sql`), used by the DPR and the Today page
  (`backend/src/mesiri/infrastructure/postgres/repositories/dpr.py`).
- **Verified:** ATT-01..06 by scripted runs of the real labour code; the phone test shows whether the live AI hits them.

## Summary

| ID | Problem | Severity | Approval |
| --- | --- | --- | --- |
| ATT-01 | Absent workers counted as present | Serious (wrong number) | Alan: Labour |
| ATT-02 | Same trade, different spelling, counted twice | Serious (wrong number) | Alan: Labour |
| ATT-03 | "0 helpers" saved as 1 | Serious (wrong number) | Alan: Labour |
| ATT-04 | "Workers yesterday?" answers today | Serious (wrong number) | Alan: Labour |
| ATT-05 | Two contractors in one message mixed up | Serious (wrong number) | Alan: Labour |
| ATT-06 | Same crew with and without contractor counted twice | Serious (wrong number) | Alan: Labour |
| ATT-07 | Mesiri still asks for worker names (V1 says off) | Other | Alan: Labour (already in scope list) |
| ATT-08 | Attendance sheet photos lost on restart | Other | Ops (INF-09) |
| ATT-09 | Labour with no site misses the site DPR | Other | Alan: Labour |
| ATT-10 | Wages accepted though V1 has no wages | Other | Alan: Labour |

## Before you test

Use a **Site Engineer** number with **one site** in the test company, so no site question
gets in the way. After each **Save**, write down three numbers; several problems show up as
these three disagreeing:

1. WhatsApp: `how many workers today?`
2. Dashboard **Attendance** page for today.
3. `send today's report` → the labour section of the draft DPR.

- Use a fresh day, or a site with no labour saved yet today.
- Tap **Save** on every card, or the entry isn't counted.

## Problems

### ATT-01 · Absent workers counted as present

- **Severity:** Serious · **Approval:** Alan: Labour
- **Repro:** `10 masons present, 2 masons absent, 1 helper half day` → Save.
- **Expected:** 10.5 (or 10 present + 1 half day) everywhere.
- **Actual:** the WhatsApp answer and the DPR say **13**; the Attendance page says 10.5.
- **Code:** the DPR / WhatsApp count ignores the attendance status the Attendance page weights (absent 0, half day 0.5). Make all three use one rule in `workforce.py`.

### ATT-02 · Same trade, different spelling, counted twice

- **Severity:** Serious · **Approval:** Alan: Labour
- **Repro:** `10 masons`, then `sorry, 12 mason`. Also try `10 mistri`.
- **Actual:** the total is **22**, not 12; the DPR shows "Masons 10" and "mason 12" as two rows.
- **Fix direction:** normalise trade names (plural, case, local words like mistri) before replacing or adding.

### ATT-03 · "0 helpers" saved as 1

- **Severity:** Serious · **Approval:** Alan: Labour
- **Repro:** `12 masons 5 helpers`, then `no helpers today, 0 helpers`.
- **Actual:** helpers show **1**; helpers can't be brought to 0.
- **Code:** `COALESCE(NULLIF(lal.headcount, 0), 1)` in the labour counts (e.g. `list_site_days` in `backend/src/mesiri/infrastructure/postgres/repositories/dpr.py`): a headcount of 0 is read as "no headcount", which counts as one person.

### ATT-04 · "Workers yesterday?" answers today

- **Severity:** Serious · **Approval:** Alan: Labour
- **Repro:** after saving some labour today: `how many workers yesterday?`
- **Actual:** the answer is **today's** count, labelled "today".
- **Code (start here):** the labour query seed `_seed_labour_query` in `apps/whatsapp-assistant/src/runtime/inbound_journey/seeding.py` and `resolve_date_range` in `apps/whatsapp-assistant/src/runtime/labour_query_service.py`.

### ATT-05 · Two contractors in one message

- **Severity:** Serious · **Approval:** Alan: Labour
- **Repro:** `Ravi contractor 12 mason, Kumar contractor 8 helper`
- **Actual:** the Attendance page puts Kumar's 8 helpers under **Ravi**, or both under no contractor.
- **Note:** `save_labour` takes one `contractor` per call (`apps/whatsapp-assistant/src/runtime/agent/tools.py`); two contractors need two calls or a per-line contractor.

### ATT-06 · Same crew with and without contractor counted twice

- **Severity:** Serious · **Approval:** Alan: Labour
- **Repro:** `12 masons`, then `Ravi's 12 masons`
- **Actual:** the total is **24**: the same crew counted with and without a contractor.

### ATT-07 · Mesiri still asks for worker names

- **Severity:** Other · **Approval:** Alan: Labour (listed in the V1 scope as "turn off worker promotion")
- **Repro:** `Ravi and Suresh came today, both masons` → Save.
- **Actual:** Mesiri asks to add Ravi and Suresh to the workers list.
- **Code:** `apps/whatsapp-assistant/src/workflows/worker_promotion/`.

### ATT-08 · Attendance sheet photos lost on restart

- **Severity:** Other · **Approval:** Ops (INF-09)
- **Repro:** send a register photo, tap **Attendance**, Save. Check the photo after the next deploy.
- **Actual:** the photo no longer opens (production photo storage is still in memory).

### ATT-09 · Labour with no site misses the site DPR

- **Severity:** Other · **Approval:** Alan: Labour
- **Repro:** a number on a project but on none of its sites: `6 masons today`
- **Actual:** saved, but not in any site's DPR labour section.

### ATT-10 · Wages accepted though V1 has no wages

- **Severity:** Other · **Approval:** Alan: Labour
- **Repro:** `12 masons at 800 per day`
- **Actual:** a labour cost appears on the card or DPR. (See also DPR-06, DSH-05: "Total cost" shown everywhere.)

## Already works

`sorry, 14 masons` after `12 masons` replaces it (14, not 26); a second crew of a different
trade adds on; a forwarded attendance message is marked as forwarded; the Attendance page
weights absent as 0 and half day as 0.5.

## Test results

Write the three numbers for ATT-01..06: WhatsApp answer / Attendance page / DPR.

| ID | Problem | Result | WhatsApp / Attendance / DPR, or what Mesiri replied |
| --- | --- | --- | --- |
| ATT-01 | Absent counted as present | Not tested | |
| ATT-02 | Trade spelling counted twice | Not tested | |
| ATT-03 | Zero becomes one | Not tested | |
| ATT-04 | "Yesterday" answers today | Not tested | |
| ATT-05 | Two contractors in one message | Not tested | |
| ATT-06 | With / without contractor counted twice | Not tested | |
| ATT-07 | Still asks for worker names | Not tested | |
| ATT-08 | Sheet photos lost on restart | Not tested | |
| ATT-09 | Site-less labour misses DPR | Not tested | |
| ATT-10 | Wages accepted | Not tested | |
