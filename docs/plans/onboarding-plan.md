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
| 2 | Starter materials seeded per new company | BE-24 (**done**); `cft`/`load` units BE-39 |
| 3 | WhatsApp signup for unknown numbers | SS-04 (**done**, off until switched on) |
| 3b | Web signup and dashboard login by WhatsApp code | SS-06 + WEB-12 (**done**, off until switched on) |
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
- **Starter materials (BE-24):** every new company gets 19 common materials, each
  with its stock unit (`domains/materials/defaults.py`), seeded in the same
  transaction and recorded as created by the owner. Without them, a supervisor's
  first "40 bags cement" gets "ask your admin", because only ADMIN/PM may add
  materials from WhatsApp. Names are plain words because WhatsApp only resolves
  a material silently on an exact name match. Seeding is safe to re-run (it skips
  names the company has). Units, issue types and trades are platform-wide already,
  so nothing else is seeded per company. Existing companies were not backfilled.

**API:** `POST /admin/organizations/provision` (both the assistant copy, which is the
one deployed, and the backend copy) now calls this step.

- **Same request still works:** the six fields the control panel sends behave as
  before.
- **New optional fields:** `admin_whatsapp_number`, `project_name`, `site_name`,
  `start_as`. `admin_email` and `admin_password` are now optional.
- **Response:** adds `signup_source`, `timezone`, `trial_started_at`,
  `trial_ends_at`, `owner_user_id`, `project_id`, `site_id`, `materials_seeded`.

`auto_dpr=True` switches the first project's automatic DPR on (cutoff 18:00 and
send by 21:00 keep their defaults); the WhatsApp signup uses it, the superadmin's
`/provision` doesn't.

## WhatsApp signup (SS-04, built 15 Oct)

- **Code:** `apps/whatsapp-assistant/src/runtime/signup_journey.py`, with its state in
  `interactions/signup_state.py` (Redis, keyed by WhatsApp number, 24 h).
- **When it runs:** called from the unknown-number branch of `runtime/message_journey.py`,
  only when the platform setting `self_serve.signup_enabled` is on. It's **off by
  default**, and while off the old "not registered" reply is unchanged. Reading the
  setting fails closed.
- **The conversation:**
  1. Welcome with buttons: **Start free trial** / **I'm in a company**.
  2. "I'm in a company": ask your admin to add this number (join codes are SS-05).
  3. "Start free trial": company name, then site name. The owner's name comes from
     their WhatsApp profile and is asked only when the profile has none.
  4. The company is created as a trial, source `whatsapp`, with the first site's
     automatic DPR on and the starter materials. It is then projected, so the
     owner's next message takes the normal path.
- **Other replies:** "cancel" stops the signup. A voice note or photo gets "please type
  it". If the number is already taken, the reply says it's already set up.
- **Before switching it on in production:** guardrails (SS-09). There is no UI for the
  switch yet (SS-10); today it's a `platform_settings` row.

## Web signup and login by WhatsApp code (SS-06 + WEB-12, built 15 Oct)

One code mechanism for both: a 6-digit code sent on WhatsApp proves the number is
yours, for signing up or for logging in to the dashboard without a password.

- **Signup page** `/signup`: WhatsApp number → code → your name, company name, site
  name → straight into the dashboard (`/today`). Same result as the WhatsApp signup:
  a trial, source `web`, the site is also the first project, its automatic DPR on,
  starter materials, projected to WhatsApp (`project_new_company`).
- **Login page:** a "WhatsApp code" tab next to email and password. Works for any
  active user with a WhatsApp number, owner or not, so owners created without a
  password can now reach the dashboard. A number on two accounts is refused (BE-04).
- **Code rules** (`backend/.../application/identity/login_codes.py`): 6 digits, 10
  minutes, one use, 5 wrong tries; one new code a minute and 5 an hour per number;
  only an HMAC of the code is stored (`login_codes`, migration 0475). Asking for a
  login code for a number nobody has answers the same and sends nothing.
- **Routes** (`apps/whatsapp-assistant/src/auth/code_login.py`, under `/auth`):
  `code/request`, `code/login`, `code/verify` (signup code → 30-minute signup ticket),
  `signup`.
- **Signup checks:** `application/organizations/signup_guard.check_signup` runs before
  a signup code is sent and before the company is created. Today it only enforces
  `self_serve.signup_enabled`; **SS-09 adds its guardrails there** (it gets the phone,
  the door and the caller's IP).
- **Sending the code:** server setting `MESIRI_LOGIN_CODE_SENDER`. `whatsapp`
  (default) uses the authentication template `mesiri_login_code`, and only once it
  is in `WHATSAPP_APPROVED_TEMPLATES`; until then both pages say code login isn't
  available yet. `dev` sends nothing and shows the code on the page, for testing
  only. Template to submit: [whatsapp-templates.md](../ops/whatsapp-templates.md).
- **To switch on:** get the template approved, add it to
  `WHATSAPP_APPROVED_TEMPLATES`, and (for signup) turn on `self_serve.signup_enabled`.
  Code login works as soon as the template is approved, even with signup off.
