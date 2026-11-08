# Progress by place: floors and rooms as places on site (Nov 2026)

> **Status:** LP-01..LP-05 built 8 Nov 2026 (tracker has the commits); LP-06, LP-07 to do. One of three independent plans split from
> [connected-project-plan.md](connected-project-plan.md); tracker section **LP** in [V1_TRACKER.md](V1_TRACKER.md).
> **Does not wait on the material plan (MP) or the drawing reader (DR).** Places are typed or made from a template
> (floors × rooms); the drawing reader can fill them later through the same table.

## 1. The problem

Site says "first floor Room-2 plastering done" or "ground floor toilets tiled". Mesiri records the work and its
quantity against a BOQ line, but not **where**. So nobody can answer "what's left on the first floor?", see the
building coloured by progress, or find the photos of one room. A revised drawing that moves something already built
is caught on site, after the rework.

## 2. Investigation (Phase 1, `main` at `e536b87`)

| Area | Exists | Reuse |
|---|---|---|
| Places | `location_nodes` (0410): a tree per project / site, free-text `level_label` (Block, Floor, Room, Chainage), `path`; **no rows, no API, no screen** | The places, as designed: no new table |
| Where work happened | `activities.location_id` (0430), `work_packages.location_id` (0420): nullable, never written | Written when site names a place |
| Photos | `progress_attachments` on activities | A photo of an activity with a place is a photo of the place |
| Work updates on WhatsApp | v3 `record_activity` (CC-04 takes a BOQ item in words) | Takes a place in words the same way |
| RLS | `location_nodes` covered by 0484 | Nothing to add |

## 3. Items

| ID | What | Size |
|---|---|---|
| **LP-01** | **Places API + setup:** `GET/POST/PATCH/DELETE /projects/{id}/places`; quick setup "Basement, Ground, First, Second × rooms" (template: floors with the same rooms, renamable); Planning › Places page (tree, add / rename / move / archive) | M |
| **LP-02** | **Work at a place:** `record_activity` and the dashboard's work entry take a place (by words: "first floor Room-2", "FF R2", Malayalam / Manglish floor words); `activities.location_id` written; asked once with buttons when unclear | M |
| **LP-03** | **Progress by place:** `GET /projects/{id}/places/progress`: per place, work recorded (by BOQ line / work type), last update, photo count; Places page shows a floor × work grid (brickwork, plaster, flooring …) coloured done / in progress / not started | M |
| **LP-04** | **"What's left on the first floor?"** on WhatsApp: v3 read route in `ALLOWED` + SOP rule; answers place by place | S |
| **LP-05** | **Photos per place:** place panel with the photo history of its activities; gallery filter by place | S |
| **LP-06** | **Places from drawings:** when the drawing reader (DR-02) exists, "Make places from this drawing" fills floors and rooms (preview, confirm) | S |
| **LP-07** | **Rework catcher:** a drawing revision (DRW-11) that moves something recorded done at a place is flagged to the PM | M (Later) |

## 4. Implementation plan (Phase 2)

**Objective.** Every work update can say where it happened, and the project shows progress floor by floor and room by
room, with the photos, without any extra typing for site.

**Database.** None for LP-01..05: `location_nodes`, `activities.location_id` exist. Archive = a nullable
`archived_at` on `location_nodes` (additive) if needed.

**Backend.** `domains/places/` (store, router, pure progress roll-up). Place matching from words in one resolver
(the same pattern as BOQ items and material categories), never a word list in the assistant.

**Frontend.** Planning › Places: tree on the left, grid of floors × work on the right, colours from LP-03; a place
panel with its updates and photos. Work entry (dashboard): an optional place picker.

**Risks.** Site will not name places if it is extra work: the place is optional, inferred from the words when present,
asked only when the BOQ line is per-floor. Too many rooms: the grid starts at floors, rooms on expand.

**Testing.** Store and route tests on a seeded tree; resolver tests in English / Manglish; v3 contract test for the
read route and for `record_activity` with a place; dashboard checks.

**Rollback.** Revert the commits; place ids written on activities are nullable and ignored by everything else.

**Labour isolation.** No Labour, Attendance, Payroll or Workforce code. (Attendance could later name a place: not in
this plan.)

**Success criteria.** On a test project: set up 4 floors × 5 rooms in under a minute; "first floor Room-2 plastering
done" lands on that room; the grid and "what's left on the first floor?" agree.

## 5. Decisions (defaults used until answered)

| # | Question | Default |
|---|---|---|
| D-LP1 | Who sets up places | Owner, admin, PM; site can only use them |
| D-LP2 | Asking for a place | Only when the BOQ line is split by floor, or the project has places and the words name none and the work is a finishing trade; never for labour or material |
