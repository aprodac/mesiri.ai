# 06 · Issues & Conditions — V1 audit

15 problems found in Issues & Conditions; the biggest is that equipment, tomorrow's plan
and weather cannot be recorded on WhatsApp at all, so three DPR sections the V1 scope
promises stay empty or say "Not set".

- **Audited:** 24 Oct 2026, `main` at `20bf7740` · **Original sheet:** [Issues & Conditions — WhatsApp test sheet](https://claude.ai/artifact/NejmbHH71iLXuMu2cbDqYq)
- **Not verified:** the live AI's wording (no AI key locally). Rows marked "Needs live AI" depend on what the model chooses.

## Code path

```
WhatsApp message
  → apps/whatsapp-assistant/src/runtime/agent/tools.py        report_issue, update_issue, note_for_engineer
  → apps/whatsapp-assistant/src/runtime/agent/site_entry.py    SITE_ISSUE → SITE_ISSUE_REPORT workflow
  → apps/whatsapp-assistant/src/runtime/agent/change_entry.py  _issue(): picks the issue to close
  → apps/whatsapp-assistant/src/workflows/site_issue_report/, site_issue_close/
  → backend/src/mesiri/application/progress/mapper.py          build_report_site_issue_command
  → backend/src/mesiri/infrastructure/postgres/repositories/progress_execution.py  persist_report_site_issue_success
  → DPR: backend/src/mesiri/infrastructure/postgres/repositories/dpr.py (issues query)
         backend/src/mesiri/application/dpr/assembly.py (_conditions: weather, hours lost, plan)
  → PDFs: apps/whatsapp-assistant/src/channel/dpr_document/ (WhatsApp)
          backend/src/mesiri/domains/dpr/pdf.py (dashboard download)
```

Weather, site working and tomorrow's plan are written only by
`PATCH /dpr/site-days/{site_id}/conditions` (`backend/src/mesiri/domains/dpr/router.py`),
i.e. the dashboard. Equipment has no table: `dpr.py` returns `'[]'::json AS equipment_items`.

## Summary

| ID | Problem | Severity | Approval | Verified |
| --- | --- | --- | --- | --- |
| ISS-01 | Equipment cannot be recorded; DPR has no Equipment section | Serious | Decision (what to capture) | Code read |
| ISS-02 | Tomorrow's plan only on the dashboard; "tomorrow" is saved as today | Serious | None | Scripted run |
| ISS-03 | Weather and "site working" never filled from WhatsApp | Serious | None | Scripted run |
| ISS-04 | An open issue drops out of the next day's DPR | Serious | Decision | Code read |
| ISS-05 | "It's fixed" closes the newest open issue, not the one named | Serious | None | Scripted run |
| ISS-06 | Engineer questions never reach the engineer; print in the client DPR | Serious | None | Scripted run |
| ISS-07 | A Malayalam issue breaks the dashboard PDF download | Serious | None | Scripted run |
| ISS-08 | Hours lost double-counted and unlimited | Other | None | Scripted run |
| ISS-09 | "Saved:" line hides hours, date and severity | Other | None | Scripted run |
| ISS-10 | "Since afternoon" leaves Hours Lost empty, no question | Other | None | Needs live AI |
| ISS-11 | No issue type for leakage, quality or safety | Other | None | Code read |
| ISS-12 | Close card shows a code; one issue per message | Other | None | Scripted run |
| ISS-13 | Dashboard PDF shows codes and cuts notes at 42 letters | Other | None | Scripted run |
| ISS-14 | "Any open issues?" skips acknowledged ones, max 20 | Other | None | Code read |
| ISS-15 | Owner/PM on no site cannot save an issue | Other | None | Code read |

## Before you test

Two phones: one Site Engineer who sends the messages, and the Project Manager of the same
project, to see whether anything arrives.

- Phone 1: a Site Engineer on one project with two sites, Site A and Site B.
- Phone 2: the Project Manager of that project (ISS-06).
- On phone 1, pick Site A when Mesiri asks "Where are you working today?".
- Start on a day with no issues yet at Site A, so the newest issue is the one you just sent.

After each Save check: the WhatsApp reply and its "Saved:" line; Dashboard → Issues
("Open (not closed)"); today's DPR (`today's DPR?` on WhatsApp, and Dashboard → Daily
Reports → today → Download PDF).

## Problems

### ISS-01 · Equipment cannot be recorded

- **Severity:** Serious · **Approval:** Decision (what to capture: name, count, hours, idle?)
- **Repro:** `JCB worked 6 hours today`, then `2 mixers and 1 vibrator on site today`
- **Expected (V1 scope):** "Equipment: captured on WhatsApp and shown in the PDF; no separate dashboard page."
- **Actual:** no Save card for equipment; the DPR has no Equipment section. Note if the reply turns it into work done or an issue (needs live AI).
- **Code:** no equipment tool in `tool_specs()` (`apps/whatsapp-assistant/src/runtime/agent/tools.py`); `apps/whatsapp-assistant/src/workflows/equipment_usage/` and `backend/src/mesiri/application/equipment/` are empty packages; `dpr.py` hard-codes `'[]'::json AS equipment_items`; neither PDF template has an equipment section.
- **Fix direction:** an additive table + `save_equipment` tool + an Equipment section in both DPR renderers.

### ISS-02 · Tomorrow's plan can't be saved from WhatsApp; "tomorrow" becomes today

- **Severity:** Serious · **Approval:** None
- **Repro:** `Tomorrow plan: 2nd floor slab casting, need 15 workers`
- **Actual:** the DPR has no "Tomorrow's Plan" section, or today's work done shows "2nd floor slab casting" (card says "assumed today").
- **Code:** no tool writes `daily_reports.tomorrow_plan`; `parse_stated_date` in `apps/whatsapp-assistant/src/canonicalization/occurred_date.py` rejects future dates and `resolve_occurred_date` falls back to today.
- **Evidence (scripted run):** `resolve_occurred_date({"occurred_on": "tomorrow"})` → `2026-10-24 inferred_at_confirmation` (today).
- **Fix direction:** a `set_tomorrow_plan` tool calling `PostgresDprRepository.set_site_day_conditions`; prompt rule that a plan for tomorrow is never work done.

### ISS-03 · Weather and "site working" never filled from WhatsApp

- **Severity:** Serious · **Approval:** None
- **Repro:** `Rain since 2 pm, work stopped 2 hours`, then `only half day work today`
- **Actual:** the DPR header shows "Weather: Not set" and "Site Working: Not set" (Hours lost does show 2.0 h). Only the evening "Site closed today" button sets site working.
- **Evidence (scripted run):** payload with a WEATHER issue → `conditions = {weather: None, site_working: None, hours_lost: '6.0', hours_lost_source: 'issues'}`; `build_document_data` → `weather: Not set | site working: Not set`.
- **Fix direction:** set `weather = rainy` from a WEATHER issue when nothing was entered; a tool for weather / half day, using the same `set_site_day_conditions`.

### ISS-04 · An open issue drops out of the next day's DPR

- **Severity:** Serious · **Approval:** Decision (should open issues carry over?)
- **Repro:** day 1: `Crane breakdown, work stopped since morning`. Day 2: send nothing about the crane.
- **Actual:** day 2's DPR says "No issues reported for this date", Open Issues 0, while the Today page shows 1 open issue.
- **Code:** issues query in `dpr.py` filters `occurred_at::date = :report_date`; Today page's `list_site_days` counts every OPEN/ACKNOWLEDGED issue. Closing an issue is never reported in any DPR either.
- **Fix direction:** the DPR lists issues reported that day plus issues still open (and those closed that day), each with its age.

### ISS-05 · "It's fixed" closes the newest open issue, not the one named

- **Severity:** Serious · **Approval:** None
- **Repro:** `Crane breakdown, work stopped` → Save. `Cement running low, need 50 more bags` → Save. `Crane is repaired`.
- **Actual:** the card says "✅ Resolve Issue • Type: MATERIAL_SHORTAGE • Cement running low, need 50 more bags • Notes: crane repaired". You cannot pick another issue on WhatsApp.
- **Code:** `update_issue` takes only `action, notes, project, site` (`tools.py`); `ChangeEntry._issue` (`change_entry.py`) calls `find_latest_by_status` (`backend/src/mesiri/infrastructure/postgres/repositories/progress.py`), which is `ORDER BY created_at DESC LIMIT 1`.
- **Fix direction:** give `update_issue` an `issue` description; match it against open issues (shown to the model in its context); ask with buttons when more than one fits.

### ISS-06 · Engineer questions never reach the engineer

- **Severity:** Serious · **Approval:** None
- **Repro:** `Ask the engineer when the 2nd floor drawings will come`
- **Actual:** phone 2 gets nothing. The reply shows "📨 Question for your engineer: …". The DPR Site Issues table shows "Other | Low | Question for your engineer: when will the 2nd floor drawings come?" and Open Issues goes up by 1.
- **Code:** `note_for_engineer` → `question_note_candidate` (`apps/whatsapp-assistant/src/canonicalization/question_note.py`) saves a SITE_ISSUE (OTHER, LOW, prefix "Question for your engineer: "). The only consumer of `SiteIssueReported` is `backend/src/mesiri/events/consumers/timeline_projector.py`: no message is sent. The DPR assembly and both PDFs don't filter the prefix.
- **Fix direction:** actually message the site's engineer / PM (team notification); keep questions out of `issues`, `open_issue_count` and the PDFs.

### ISS-07 · A Malayalam issue breaks the dashboard PDF download

- **Severity:** Serious · **Approval:** None
- **Repro:** `ക്രെയിൻ കേടായി, രാവിലെ മുതൽ പണി നിർത്തി` → Save, then Dashboard → Daily Reports → today → Download PDF.
- **Actual:** an error. Also check the WhatsApp DPR PDF: do the Malayalam letters show, or boxes? (not tested)
- **Code:** `backend/src/mesiri/domains/dpr/pdf.py` uses the built-in Helvetica font; the issues table passes the narrative without `_latin1()`.
- **Evidence (scripted run):** `FPDFUnicodeEncodingException: Character "ക" at index 0 in text is outside the range of characters supported by the font used: "helvetica"`.
- **Fix direction:** add a Unicode font with Malayalam glyphs (e.g. Noto Sans Malayalam) to the fpdf renderer, or serve the HTML-rendered PDF for drafts too. Check Chromium on the server has Noto Malayalam.

### ISS-08 · Hours lost double-counted and unlimited

- **Severity:** Other · **Approval:** None
- **Repro:** `Rain stopped work 2 hours` → Save, then `Crane broke in the same rain, 4 hours lost` → Save. Next day: `Heavy rain, no work for 2 days`.
- **Actual:** the first DPR shows Hours Lost 6.0 h; the second shows 48.0 h for one day.
- **Code:** `_conditions` in `assembly.py` sums `delay_duration_minutes` of all the day's issues; `_delay_minutes` in `backend/src/mesiri/application/progress/mapper.py` has no limit (dashboard entries are capped at 24 by `site_day.validate_conditions`).
- **Evidence (scripted run):** 240 + 120 min → `hours_lost: '6.0'`; 2880 min → `'48.0'`.

### ISS-09 · "Saved:" line hides hours, date and severity

- **Severity:** Other · **Approval:** None
- **Repro:** `Yesterday heavy rain, work stopped 3 hours`
- **Actual:** the line reads only "Issue (weather): Heavy rain, work stopped", with no 3 hours and no date. The DPR then shows a severity the user never saw.
- **Code:** `summarise_draft` for `RECORD_SITE_ISSUE` in `apps/whatsapp-assistant/src/interactions/saved_summary.py`.

### ISS-10 · "Since afternoon" leaves Hours Lost empty

- **Severity:** Other · **Approval:** None · **Needs live AI**
- **Repro:** `Rain since afternoon, work stopped`
- **Actual:** the DPR shows Hours Lost "—" and Mesiri asked nothing. The prompt (`apps/whatsapp-assistant/src/runtime/agent/prompt.py`) has no rule to ask for hours lost.

### ISS-11 · No issue type for leakage, quality or safety

- **Severity:** Other · **Approval:** None (the enum change is an additive migration)
- **Repro:** `Worker fell from scaffolding, minor injury`, then `Water leakage in 2nd floor bathroom`
- **Actual:** Dashboard Issues and the DPR show Type "Other" for both.
- **Code:** issue types in `tools.py` (`REPORT_ISSUE` enum), `backend/src/mesiri/domains/progress/validation.py`, DB enum `site_issue_type` (migration 0430).

### ISS-12 · Close card shows a code; one issue per message

- **Severity:** Other · **Approval:** None
- **Repro:** `Both issues are fixed` (with 2 open issues)
- **Actual:** the card shows "Type: MATERIAL_SHORTAGE" and "Reply YES to confirm or NO to cancel."; only one of the two issues is closed.
- **Code:** `request_confirmation` in `apps/whatsapp-assistant/src/workflows/site_issue_close/nodes.py`.

### ISS-13 · Dashboard PDF shows codes and cuts notes at 42 letters

- **Severity:** Other · **Approval:** None
- **Repro:** `Crane breakdown, work stopped since morning` → Save → dashboard PDF.
- **Actual:** "EQUIPMENT_BREAKDOWN", "OPEN" and "Crane breakdown, work stopped since morni...". The WhatsApp PDF is fine ("Equipment Breakdown", full note).
- **Code:** issues table in `backend/src/mesiri/domains/dpr/pdf.py` (`_truncate(..., 42)`, raw enum values).

### ISS-14 · "Any open issues?" skips acknowledged ones

- **Severity:** Other · **Approval:** None
- **Repro:** mark one issue "seen, being handled" (acknowledge), then `any open issues?`
- **Actual:** the reply leaves out the acknowledged issue; the dashboard shows it as open. At most 20 are listed.
- **Code:** `apps/whatsapp-assistant/src/runtime/activity_search_service.py` (`site_issues.c.status == "OPEN"`, `_MAX_ROWS = 20`).

### ISS-15 · Owner/PM on no site cannot save an issue

- **Severity:** Other · **Approval:** None · **Code read only**
- **Repro:** from an owner who is on the project but on no site: `Drawings for Block B still pending from architect`
- **Actual:** "Sorry, that didn't go through" or similar; nothing on the Issues page.
- **Code:** `SiteEntry.prepare` settles with `site_required=False` for issues; `validate_report_site_issue` checks only the project; `persist_report_site_issue_success` raises `RuntimeError` when `site_id` is None.
- **Fix direction:** ask "Which site?" (with buttons) when there is no site, as work done does.

## Already works

An issue saves with its type and note; "yesterday" puts it on yesterday; a material running
low ("10 bag cement balance, need more") becomes an issue; the evening "Site closed today"
button marks the day as no work; "reopen" picks the issue just closed; an issue withdrawn as
a mistake drops out of the DPR; when no hours were typed, the DPR adds up the issue delays as
Hours Lost; "nothing to resolve" is said plainly; the WhatsApp PDF shows tidy labels and the
full note.

## Test results

| ID | Problem | Result | What Mesiri replied |
| --- | --- | --- | --- |
| ISS-01 | Equipment cannot be recorded | Not tested | |
| ISS-02 | Tomorrow's plan not saved, or saved as today's work | Not tested | |
| ISS-03 | Weather and site working stay "Not set" | Not tested | |
| ISS-04 | Open issue drops out of next day's DPR | Not tested | |
| ISS-05 | "Crane is repaired" closes the cement issue | Not tested | |
| ISS-06 | Engineer question never reaches the engineer | Not tested | |
| ISS-07 | Malayalam issue breaks the dashboard PDF | Not tested | |
| ISS-08 | Hours lost counted twice, no limit | Not tested | |
| ISS-09 | Saved line hides hours, date, severity | Not tested | |
| ISS-10 | "Since afternoon" leaves hours lost empty | Not tested | |
| ISS-11 | Accident and leakage filed as "Other" | Not tested | |
| ISS-12 | Close card shows a code; one issue per message | Not tested | |
| ISS-13 | Dashboard PDF shows codes, cuts notes | Not tested | |
| ISS-14 | "Any open issues?" skips acknowledged ones | Not tested | |
| ISS-15 | Owner on no site cannot save an issue | Not tested | |
