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
| 4 | Add a team member by sharing a contact; invite to forward | SS-13 (**done**) |
| 5 | One-screen create form + companies list in the control panel | SA-01, SA-02 (**done**) |
| 6 | Daily setup questions (letterhead/logo photos → team, report time, more sites) | SS-14 (**done**, WhatsApp side); control-panel requests list: Lane B |
| 6b | Getting-started checklist on the dashboard's Today page | SS-07 (**done**) |
| 7 | Trial reminders, expiry, limits, superadmin trial controls | SS-08, SS-09, SS-10 (**done**) |

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
- **Audit log (BE-05):** writes one `company.created` entry in the same transaction:
  the platform admin on `/provision` (callers pass `actor=`), the owner themselves
  (`self_signup`) for a WhatsApp/web signup, otherwise `system`. See
  [admin-audit-log.md](../backend/admin-audit-log.md).
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
- **Several sites (SA-01):** optional `site_names: [...]` creates every name as a
  site under the one project (each site gets its own report; the project's report
  combines them). Empty entries are dropped; duplicates (any case), more than 20, or
  a `site_name` that disagrees are refused (400). The response's `sites` lists
  `{site_id, name}` for each; `project_id`/`site_id` still name the first. Every
  site is projected to WhatsApp.

`auto_dpr=True` switches the first project's automatic DPR on (cutoff 18:00 and
send by 21:00 keep their defaults); the WhatsApp signup uses it, the superadmin's
`/provision` doesn't.

## Control panel "Create company" (SA-01, built 15 Oct)

`apps/control-panel/src/CreateCompany.tsx`, opened by **Create company** on the
Organizations page. Replaces the old "Provision New Tenant" form.

- **Asks:** company name, owner name, owner WhatsApp number, project name, one or
  more site names (empty → one site named after the project), free trial (default)
  or active. Owner email + password sit under "Dashboard login (optional)".
- **Doesn't ask:** deployment type and database route (server defaults).
- **After Create:** trial end date, the sites made, starter materials count, and
  **Open company**. Errors (taken number/email, bad input) show in the form.
- **One project per company here;** more projects are added later from the dashboard.
- **Not yet:** the project's automatic DPR stays off for superadmin-created companies
  (`/provision` doesn't pass `auto_dpr`), unlike WhatsApp signup; and the owner gets no
  WhatsApp welcome message (the welcome is part of the team-member work with SS-05).

## Control panel companies list (SA-02, built 15 Oct)

`apps/control-panel/src/Companies.tsx` (sidebar **Companies**), fed by
`GET /admin/organizations`, which both admin routers answer from one read:
`application/organizations/companies_overview.py`.

- **Status:** the effective status (`lifecycle.effective_status`), so a trial past its
  end shows **Expired** while its stored status still says `trial`; trials show days
  left. Filters: All / Trial / Active / Expired / Suspended.
- **Source:** `signup_source` (Superadmin, WhatsApp, Web, API).
- **Setup ticks:**
  - **Team**: an active user besides the owner.
  - **Site**: at least one site.
  - **Update**: the first confirmed site record, the earliest of `activities` (work
    reported) and `timeline_entries` (materials, issues). The timeline is filled by a
    job every few minutes, so a material-only first update can show a little late.
  - **DPR**: the first `PUBLISHED` daily report (automatic or "Send now").
- **API (additive):** each item adds `effective_status`, `trial_days_left`,
  `trial_started_at`, `trial_ends_at`, `converted_at`, `signup_source` and
  `setup {has_team, has_site, first_update_at, first_dpr_sent_at}`.
- Deployment type and database route moved off the list (still on the company page).

## Superadmin trial controls (SS-10, built 15 Oct)

**Company page → Plan card** (`apps/control-panel/src/PlanCard.tsx`): effective status,
trial start/end, days used, converted date, setup ticks, and four actions, each behind a
confirmation and recorded in the audit log (BE-05) in the same transaction:

| Action | Allowed when | Result |
| --- | --- | --- |
| Extend trial (1-90 days) | trial or expired | end = later of old end and now, + N days; back to `trial` |
| Convert to paid | trial or expired | `active`, `converted_at` = now; trial dates kept as history |
| Suspend (optional reason) | anything but suspended | `suspended`; WhatsApp refuses the company from its next message |
| Reactivate | suspended | `active` if it was converted or never on a trial, else back to its trial (expired at once if the end has passed) |

Anything else is refused with 409; nothing is changed or recorded.

**Settings → Trials & signup** (`PlatformSettingsCard.tsx`): free trial length (new
trials only), days data is kept after a trial expires, and the self-serve signup switch
(warns that the SS-09 guardrails aren't built yet).

- **Code:** rules and the transaction in `application/organizations/trial_controls.py`;
  settings save + audit in `platform_settings_admin.py`; one company's overview via
  `companies_overview.company_setup` (shared with SS-07).
- **API:** `GET /admin/organizations/{id}/overview`, `POST /admin/organizations/{id}/trial/extend`
  `{days}`, `/convert`, `/suspend` `{reason?}`, `/reactivate` (both admin routers; the
  assistant re-projects the company after a change). `GET /admin/platform-settings`,
  `PUT /admin/platform-settings/{key}` (assistant only, like platform users).
- **Not in it:** trial reminders and expiry messages (SS-08), deleting data after the
  retention period, the trials funnel (SS-11).

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
- **Before switching it on in production:** guardrails (SS-09). The switch is in the control panel's
  Settings → Trials & signup (SS-10).

## Team by shared contact (SS-13, built 15 Oct)

- **Code:** `apps/whatsapp-assistant/src/runtime/contact_share_journey.py`. Shared
  contact cards are read in `ingress/normalization.py` into
  `metadata["shared_contacts"]`.
- **What happens when an Admin or PM shares a contact.** Nothing new writes users or
  memberships; it uses the same workflows as a typed "add Rajesh, 98765..., as site
  engineer":
  - **New number:** the CREATE_USER → ADD_PROJECT_MEMBER plan
    (`start_member_create_plan`, now accepting an explicit `whatsapp_number`). That's
    **two confirmation taps**: create the user, then add them to the project.
  - **Already in this company:** ADD_PROJECT_MEMBER only (one tap).
  - **In another company:** refused (BE-04).
  - **Several projects:** a project picker first.
  - **Several cards in one share:** the first is added, and the owner is asked to
    share the others one at a time (one plan per user).
- **The invite.** Mesiri can't message the new person first, because WhatsApp only
  allows that within 24 h of their own message unless a template is used. So after
  the add succeeds, the owner gets a ready-to-forward invite with a
  `wa.me/<Mesiri number>?text=Hi` link. When the person says Hi they're already a
  user, and the existing first-message intro welcomes them.
- **Proposed template for SS-12** (utility, for direct invites later):
  *"Hi {{1}}, {{2}} has added you to Mesiri to send daily site updates on WhatsApp.
  Reply Hi to start."*

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
  only an HMAC of the code is stored (`login_codes`, migration 0476). Asking for a
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

## Daily setup questions (SS-14, built 15 Oct)

Decided 15 Oct: the **logo and letterhead are set up by the Mesiri team, not read by AI**.
The owner sends photos on WhatsApp, and we fill in the letterhead from the control panel.

- **Code:** `apps/whatsapp-assistant/src/runtime/setup_questions.py`. The rules are in
  `backend/src/mesiri/domains/organizations/setup_questions.py`.
- **When questions go out:** to the owner (ADMIN) only, at most one a day, right
  after Mesiri replies to one of their own messages. That keeps them inside
  WhatsApp's 24-hour window, so no template is needed. Nothing is asked while a
  confirmation or question is open, or more than 30 days after the company was
  created. Each question is asked once; answered or skipped, it isn't repeated.
- **The questions, in order:**
  1. **Letterhead / visiting card / logo photos.** Photos sent in the next 30
     minutes are saved as one **branding request** (`organization_settings`
     key `branding_requests`). Each photo is posted to the Mesiri team WhatsApp
     group through the teammate listener (`runtime/team_notify.py`).
  2. **Report time:** 7 pm / 8 pm / keep 9 pm. This sets `dpr_send_deadline` on
     every project of the company.
  3. **Another site?** Starts the existing "add a site" workflow.
- **Contract with the control panel:**
  - Each branding request is `{id, status: open|done, created_at,
    sent_by_user_id, files: [{object_key, content_type, received_at}], done_at,
    owner_notified}`.
  - The team fills the letterhead in (the existing branding setting and logo
    upload), then sets `status: "done"` and `done_at`.
  - The owner hears "✅ Your letterhead is set up" on their next message, within
    3 hours.
  - The progress per question is in `setup_progress`.
  - The generic settings API refuses both keys.
- **To switch the team-group posts on**, the app needs `TEAMMATE_TOKEN` (the
  listener's token) in its environment. Without it nothing is posted, but the
  requests are still saved for the control panel.
- **Not included yet:** "who else gets the report?". It waits for WA-09 (opt-in),
  because outside contacts receive nothing until they opt in.

## Getting-started checklist (SS-07, built 15 Oct)

A card at the top of **Today** for company admins
(`apps/dashboard/src/components/getting-started-card.tsx`), fed by
`GET /company/setup-progress` (`backend/.../domains/organizations/setup_router.py`).
Nothing is ticked by hand: every item comes from what happened.

- **One definition of "done":** the card uses the same setup read as the control
  panel's companies list (`companies_overview.py`, SA-02), extended with two items.
  The owner and the Mesiri team always see the same progress.
- **Items:** first site · site supervisor (an active user besides the owner) · first
  update from site · report time · logo on the report · first DPR sent. Each open
  item links to where it's done (Team, Project → Reporting, Company → Letterhead),
  plus the trial days left.
- **Report time** is the one item the data can't show (keeping 9 pm looks like never
  looking). It counts as done when a project's time was changed from 18:00 / 21:00,
  or the report-time setup question was **answered**, on WhatsApp (SS-14) or with the
  card's "9:00 pm is fine" (`POST /company/setup-progress/report-time-ok`). Both write
  SS-14's own `setup_progress` record, so neither side asks again. A skipped question
  doesn't count.
- **Logo:** done when the letterhead has a logo (`branding.logo_object_key`). A
  branding request sent on WhatsApp (SS-14) ticks it once the team has uploaded the
  logo.
- **Hiding:** gone for good once everything is done; "Hide for now" is remembered in
  that browser only.
