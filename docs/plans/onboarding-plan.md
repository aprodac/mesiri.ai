# Onboarding — how a new company gets onto Mesiri

> Agreed 15 Oct 2026. Tracker items: section **SS** (self-serve) and **SA-01/SA-02**
> (superadmin) in [V1_TRACKER.md](V1_TRACKER.md). This file is the "why" and the shape;
> the tracker is the status.

## The target experience

**The client never fills a form. They have a short WhatsApp chat, and the first daily
report arrives that evening.**

1. The owner taps a Mesiri link and says "Hi".
2. Three questions: company name, current site, "share your site supervisor's contact".
   About one minute. No app, no password, no website.
3. The supervisor gets a welcome message and reports the way they already do: text,
   voice note or photos.
4. That evening the owner gets the DPR PDF. This is what sells it.
5. Over the next days Mesiri asks **one setup question a day**, only when it helps:
   letterhead photo (name, address, GSTIN and logo read from it), who else should get
   the report, report time, more sites.
6. Before the trial ends: a reminder with what they got; conversion is manual for now.

A bigger client onboarded by our team gets the same thing from **one screen** in the
control panel (company name, owner phone, site names → Create). The owner then gets the
same WhatsApp welcome.

### Rules

1. WhatsApp, not forms.
2. Default everything (report time, one site, owner receives the report); ask only when
   it matters.
3. Contacts are shared, not typed.
4. A photo instead of data entry (reuse the existing OCR pipeline).
5. Value on day one, setup later, one question a day.
6. **Every path creates a company through the same step** (below).

Free-form WhatsApp messages are allowed only within 24 h of the client's last message, so
nudges and trial reminders need Meta-approved templates (SS-12). Apply early.

## Build order (coding only)

| # | Piece | Tracker |
| --- | --- | --- |
| 1 | One create-company step | SS-03 (**done**, includes BE-02) |
| 2 | Construction defaults seeded per new company | BE-24 |
| 3 | WhatsApp signup for unknown numbers | SS-04 |
| 4 | Add a team member by sharing a contact; welcome message | new, with SS-05 |
| 5 | One-screen create form + companies list in the control panel | SA-01, SA-02 |
| 6 | Daily setup questions (letterhead photo → branding, recipients, report time) | SS-07 + new |
| 7 | Trial reminders, expiry, limits, superadmin trial controls | SS-08 to SS-10 |

## The create-company step (SS-03, built 15 Oct)

`backend/src/mesiri/application/organizations/create_company.py`:
`create_company(conn, NewCompany(...))`.

- **Creates:** the company, its owner (`ADMIN`), and optionally the first project
  and its first site (the site defaults to the project's name).
- **Owner:** needs an email, a WhatsApp number, or both. The number is stored as
  digits with the country code; a bare 10-digit Indian mobile gets `91`. With no
  password, the owner gets an unusable one and can't log in to the dashboard (login
  by code is WEB-12/SS-06).
- **`start_as`:** `active` (the default) or `trial`. A trial's end date comes from the
  platform setting `trial_policy.trial_days` (default 7).
- **`signup_source`:** `superadmin`, `whatsapp`, `web` or `api`, for the trials
  funnel.
- **Timezone:** new companies and their first project default to `Asia/Kolkata`.
- **All-or-nothing:** it uses the caller's transaction and never commits. A taken
  email (any case) or WhatsApp number (compared as digits) is refused before anything
  is written (`CompanyCreationError`, `conflict=True` → HTTP 409).
- **WhatsApp visibility:** making the new rows visible to WhatsApp (context projection)
  is the caller's job after commit. The assistant's `/provision` does it.
- **BE-24 hook:** BE-24 seeds its defaults inside this function, in the same
  transaction.

**API:** `POST /admin/organizations/provision` (both the assistant copy, which is the
one deployed, and the backend copy) now calls this step.

- **Same request still works:** the six fields the control panel sends behave as
  before.
- **New optional fields:** `admin_whatsapp_number`, `project_name`, `site_name`,
  `start_as`. `admin_email` and `admin_password` are now optional.
- **Response:** adds `signup_source`, `timezone`, `trial_started_at`,
  `trial_ends_at`, `owner_user_id`, `project_id`, `site_id`.

**Not in this step (yet):** a new project's automatic DPR stays off (column default);
the WhatsApp signup (SS-04) decides whether a trial's first project switches it on.
