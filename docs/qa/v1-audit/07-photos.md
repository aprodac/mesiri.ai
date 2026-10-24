# 07 · Photos — V1 audit

10 problems found in Photos; the biggest is that a progress photo is never attached to the
work: tapping "Site Update" always answers "there's no activity in progress right now",
even straight after the work was reported.

- **Audited:** 24 Oct 2026, `main` at `20bf7740` · **Original sheet:** [Photos — WhatsApp test sheet](https://claude.ai/artifact/K6cggQMG3hK7NwFQ9ee2aL)
- **Not verified:** the live AI reading a photo (no AI key locally), PDF bills, and real photo storage on the server.

## Code path

```
photo arrives (InputModality.IMAGE)
  → apps/whatsapp-assistant/src/runtime/message_journey.py
      1. completion-photo hint  (interactions/completion_photo_hint.py)  → attach to that activity
      2. team-photo hint        (interactions/team_photo_hint.py)        → attach to attendance
      3. try_hold_new_image_for_purpose_picker (interactions/image_purpose.py)
           → PendingMediaStore (interactions/pending_media.py, 10 min, max 20)
           → "📷 What is this photo for?" (channel/replies.py IMAGE_PURPOSE_ROWS)
  → tap img_site_update      → activity_query.find_open_activity(site_id=None, …) → evidence_query.attach_photos
  → tap material / expense / attendance → _run_agent(first photo only) + render_batch_overflow_reply
      → runtime/agent/turn.py describe_media → "(They sent a photo … It shows: …)"
      → entry_base.ready() puts media_object_key in the fields
```

A PDF or document bill skips the picker and goes straight to the agent.

## Summary

| ID | Problem | Severity | Approval | Verified |
| --- | --- | --- | --- | --- |
| PHO-01 | "Site Update" photos are never attached; caption dropped | Serious | None | Scripted run |
| PHO-02 | The DPR shows a photo count, never the photos | Serious | None | Code read |
| PHO-03 | A bill photo is not kept with the material receipt | Serious | None | Code read |
| PHO-04 | Only the first photo of a bill or register is read | Serious | Alan: Labour (registers) | Scripted run |
| PHO-05 | Photos are lost when the server restarts | Serious | Ops (INF-09) | Tracker |
| PHO-06 | Untapped photos vanish after 10 minutes, silently | Other | None | Scripted run |
| PHO-07 | A caption that says what it is still gets the question | Other | None | Scripted run |
| PHO-08 | "Expense" offered though expenses are off in V1 | Other | None | Scripted run |
| PHO-09 | "20 photos held" repeats; extras dropped | Other | None | Scripted run |
| PHO-10 | After some saves, the next photo skips the question | Other | Alan: Labour (team photo part) | Code read |

## Before you test

One Site Engineer phone on a project with Site A, and these photos in the gallery:

- 3 site photos (any wall or slab)
- a material bill or challan with 2 or 3 pages, photographed page by page
- a photo of an attendance register
- the company has Finance switched off (the V1 default)

After each step check: Mesiri's reply; Dashboard → Daily Reports → today (Evidence Photos
number and the photos in the day's sources); Dashboard → Materials (is the bill photo with
the receipt?).

## Problems

### PHO-01 · "Site Update" photos are never attached

- **Severity:** Serious · **Approval:** None
- **Repro:** `Started plastering 2nd floor` → Save. Then 3 site photos, the first with the caption "2nd floor plastering". Tap **Site Update**.
- **Actual:** "📷 Got your photo(s), but there's no activity in progress right now to attach them to. Describe the work first (e.g. "started plastering Block A"), then resend the photos." Evidence Photos stays 0. The evening reminder ("No photos yet either. Send one or two if you can.") sends people round the same loop.
- **Code:** `message_journey.py` (the `img_site_update` branch) calls `activity_query.find_open_activity(organization_id=…, site_id=None, reported_by_user_id=…)`; `ActivityQueryService.find_open_activity` (`apps/whatsapp-assistant/src/runtime/activity_query.py`) starts with `if not site_id or not reported_by_user_id: return None`. The caption (`held_batch[0].text`) is never read on this branch.
- **Evidence (scripted run):** real `build_message_handlers` + real `PendingMediaStore` + real `ActivityQueryService` with a database that raises on any use: the database was never touched, `attach_photos` called 0 times, reply as above.
- **Fix direction:** pass today's site (WA-45 work site) or the sender's site; when the caption describes work, save it as work done and attach the photos to it.

### PHO-02 · The DPR shows a photo count, never the photos

- **Severity:** Serious · **Approval:** None
- **Repro:** after any photo is attached (PHO-10 is the one way that works today), `today's DPR?`
- **Actual:** the PDF has an "Evidence Photos" number and a "Photos" column, but no pictures.
- **Code:** `apps/whatsapp-assistant/src/channel/dpr_document/template.py` renders only `evidence_count`; the payload (`assembly.py`) carries counts, not object keys. Attendance photos aren't counted at all.
- **Fix direction:** a photo strip per activity (thumbnails as data URIs, as the letterhead logo is), capped per page.

### PHO-03 · A bill photo is not kept with the material receipt

- **Severity:** Serious · **Approval:** None
- **Repro:** bill photo → tap **Material Delivery** → Save.
- **Expected (V1 scope):** "Bill photo attached to a material receipt" (Keep in V1).
- **Actual:** the receipt is on the Materials page, but no bill photo can be opened from it.
- **Code:** `entry_base.ready()` adds `media_object_key` to the fields, but `backend/src/mesiri/application/materials/mapper.py` never reads it, and nothing writes `material_invoice_attachments` from WhatsApp (only the dashboard routes in `backend/src/mesiri/domains/materials/router.py`). Labour does read it (`backend/src/mesiri/application/labour/mapper.py` `_attachment_object_keys`).

### PHO-04 · Only the first photo of a bill or register is read

- **Severity:** Serious · **Approval:** Alan: Labour (for attendance registers)
- **Repro:** 3 pages of one challan in a row → tap **Material Delivery**.
- **Actual:** "(I'm only processing 1 of your 3 photos right now — please resend the other 2 photos once this one is confirmed.)" Items from pages 2 and 3 are missing. Under save-first there is nothing to confirm, and resending asks "What is this photo for?" again.
- **Code:** `message_journey.py` runs `_run_agent(held_batch[0], …)`; `render_batch_overflow_reply` in `apps/whatsapp-assistant/src/channel/replies.py`.
- **Fix direction:** read all pages in one vision call (one bill) or one agent turn per photo.

### PHO-05 · Photos are lost when the server restarts

- **Severity:** Serious · **Approval:** Ops (INF-09)
- **Repro:** send a photo, have the Mesiri team restart the app, open it on the dashboard.
- **Actual:** the photo no longer opens; `/health` says `media_storage: fake`.
- **Fix:** switch the object-storage provider in `/opt/mesiri/.env` (`MESIRI_OBJECT_STORAGE__PROVIDER`; VPS disk was decided 13 Oct). Exact settings: tracker INF-09.

### PHO-06 · Untapped photos vanish after 10 minutes

- **Severity:** Other · **Approval:** None
- **Repro:** 1 photo, don't tap. Send `5 masons today`. Send another photo. Wait 11 minutes, then tap Site Update on the old list.
- **Actual:** the second photo gets no reply (it joins the held batch). The late tap says "That photo has expired — please resend it." Nothing warned before.
- **Code:** `_DEFAULT_TTL_SECONDS = 600` in `apps/whatsapp-assistant/src/interactions/pending_media.py`; a later photo with a batch open returns no reply (`image_purpose.py`).

### PHO-07 · A caption that says what it is still gets the question

- **Severity:** Other · **Approval:** None
- **Repro:** 1 photo with the caption `cement bill 50 bags`
- **Actual:** "📷 What is this photo for?" instead of reading the bill.
- **Fix direction:** skip the picker when the caption names the purpose (bill, challan, attendance, work words).

### PHO-08 · "Expense" offered though expenses are off in V1

- **Severity:** Other · **Approval:** None
- **Repro:** 1 photo → tap **Expense**.
- **Actual:** the list shows Expense; the reply is "Expenses aren't switched on for your company yet, so I didn't record this. Ask your admin to turn them on." The scope asks for "Expense tracking is coming soon".
- **Code:** static `IMAGE_PURPOSE_ROWS` and `render_module_disabled_reply` in `apps/whatsapp-assistant/src/channel/replies.py`.
- **Fix direction:** build the rows from the enabled modules.

### PHO-09 · "20 photos held" repeats; extras dropped

- **Severity:** Other · **Approval:** None
- **Repro:** 25 photos in one go.
- **Actual:** "📷 That's 20 photos held — that's as many as I can take at once…" arrives 6 times; photos 21–25 are gone.
- **Code:** `PendingMediaStore.add_pending` returns `capped=True` for every photo past the cap, and the caller sends the line each time.

### PHO-10 · After some saves, the next photo skips the question

- **Severity:** Other · **Approval:** Alan: Labour (team-photo part) · **Code read**
- **Repro:** `2nd floor plastering finished` (for work reported earlier) → Save. Within 15 minutes, send a cement bill photo.
- **Actual:** "📷 1 photo attached to your current activity." The bill is now a plastering photo and no material was saved. The same happens for 15 minutes after an attendance save ("Want to add a team photo?").
- **Code:** `completion_photo_hint_store.set_hint` in `apps/whatsapp-assistant/src/interactions/handler.py` (after an `ADD_PROGRESS_UPDATE` with `COMPLETED`); team photo hint set in `_offer_team_photo` (`runtime/inbound_journey/seeding.py`); both popped in `message_journey.py` before the picker. TTL 900 s. In agent mode the "Want to attach a completion photo?" line may not be shown at all.

## Already works

A burst of photos gets one question, not one per photo; a photo skips the morning "Where
are you working today?" question; an attendance register photo is read and kept with the
attendance; a bill is read into materials after Material Delivery; a late tap on an
expired list says so plainly; a PDF bill goes straight to reading without the photo question.

## Test results

| ID | Problem | Result | What Mesiri replied |
| --- | --- | --- | --- |
| PHO-01 | Site Update photos never attached | Not tested | |
| PHO-02 | DPR shows a photo count, no photos | Not tested | |
| PHO-03 | Bill photo not kept with the receipt | Not tested | |
| PHO-04 | Only page 1 of a bill or register read | Not tested | |
| PHO-05 | Photos lost on server restart | Not tested | |
| PHO-06 | Untapped photos vanish after 10 minutes | Not tested | |
| PHO-07 | Caption ignored, question still asked | Not tested | |
| PHO-08 | Expense offered though it is off | Not tested | |
| PHO-09 | "20 photos held" repeats, extras dropped | Not tested | |
| PHO-10 | Next photo after a save skips the question | Not tested | |
