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
| 6 | Daily setup questions (letterhead/logo photos → team, report time, more sites) | SS-14 (**done**, WhatsApp side), SA-09 (**done**, control panel) |
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

## Branding requests in the control panel (SA-09, built 15 Oct)

The other half of SS-14's letterhead question: the owner's photos are worked here.

- **Branding requests** (sidebar): every company's requests, open first and oldest
  first, with when it came in, file count and status (open / done, owner told or not
  yet). **Open** goes to the company's **Letterhead** tab (`?tab=letterhead`). The
  Companies list shows a "Letterhead photos" badge while a request is open.
- **Letterhead tab** (`BrandingPanel.tsx`): the photos (full size on click; "File no
  longer available" when storage lost one, see INF-09) next to the letterhead form
  (name on letterhead, GSTIN, signatory, brand colour, address, phone, email) and
  logo upload. **Mark done** sets `status: "done"` and `done_at`; the assistant tells
  the owner on their next message and sets `owner_notified`. The control panel sends
  no WhatsApp messages.
- **Code:** one router, `domains/admin/branding_router.py`, mounted by both apps.
  The letterhead logic moved out of the dashboard's `/company/branding*` routes into
  `application/organizations/branding_admin.py`, which both now call (same behaviour
  for the dashboard). Every change is audited (`company.setting_changed`).
- **API:** `GET /admin/branding-requests`; `GET`/`PUT /admin/organizations/{id}/branding`;
  `PUT`/`DELETE .../branding/logo`; `GET .../branding-requests/{rid}/files/{n}` (a photo
  by its position in that company's own request); `POST .../branding-requests/{rid}/done`
  (409 if already done). The companies list adds `open_branding_requests`.
- **Known gap:** the assistant adds photos with a read-and-rewrite of the request list
  without a lock. A photo arriving at the very moment the team clicks Mark done can undo
  one of the two writes. Rare; fixing it means locking on the assistant side (Lane A).

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
  only when the platform setting `self_serve.signup_enabled` is on. It's **on by
  default** since SS-16 (15 Oct; switch it off in the control panel's Settings), and
  while off the old "not registered" reply is unchanged. Reading the setting fails
  closed. Live on 24 Oct: on.
- **The conversation:**
  1. Welcome with buttons: **Start free trial** / **I'm in a company**.
  2. "I'm in a company": ask your admin for the join code and send *JOIN ACME-4821* (SS-05), or ask them to add this number.
  3. "Start free trial": company name, then site name. The owner's name comes from
     their WhatsApp profile and is asked only when the profile has none.
  4. The company is created as a trial, source `whatsapp`, with the first site's
     automatic DPR on and the starter materials. It is then projected, so the
     owner's next message takes the normal path.
- **Other replies:** "cancel" stops the signup. A voice note or photo gets "please type
  it". If the number is already taken, the reply says it's already set up.
- **Before switching it on in production:** guardrails (SS-09). The switch is in the control panel's
  Settings → Trials & signup (SS-10).

## Team joins by code (SS-05, built 19 Oct)

- **Code:** `runtime/join_journey.py` (WhatsApp), `application/organizations/team_join.py`
  (store), `domains/organizations/team_join.py` (rules). Stored in `organization_settings`
  (`join_code`, `join_requests`); the settings API refuses both keys. No migration.
- **Sharing:** an admin or project manager sends *join code*. They get a message to
  forward: the code and a wa.me link that opens a chat with *JOIN ACME-4821* already
  typed. *new join code* replaces it, and the old one stops working at once.
- **Asking:** someone not on Mesiri sends the code. Their name comes from their WhatsApp
  profile, or is asked. Every active admin of the company gets "X wants to join"
  [Approve] [Reject]. This runs before signup, so it works with self-serve signup off.
- **Deciding (admins only):** Approve goes on through the SS-13 contact-share steps
  (project, then CREATE_USER and ADD_PROJECT_MEMBER with their confirmations), so
  nothing new writes users. Once they're on the project, the person is told directly.
  Reject tells them they weren't approved.
- **Guardrails:** a code adds nobody without an admin's Approve. A number gets 5 wrong
  codes a day. Asking again while a request is open sends no second alert. A company
  holds at most 20 open requests. Requests expire after 7 days. An ended trial or a
  suspended company takes no one. A number already on Mesiri never reaches this, and one
  in another company is refused by the SS-13 steps (BE-04).
- **Admins outside the 24 h window (SS-12, 19 Oct):** inside the window the alert is a
  normal message with Approve / Reject buttons; outside it, it goes as the
  `mesiri_join_request` template with the same tap ids (text in
  docs/ops/whatsapp-templates.md), once that is approved and listed in
  `WHATSAPP_APPROVED_TEMPLATES`. Until then such an admin is not alerted and the
  log says `team_join.admin_not_reached ... reason=outside_window`. The window is
  the same last-message lookup the notification sender uses.

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

## Trial reminders and expiry (SS-08, built 15 Oct)

Decided 15 Oct:
- reminders go out 2 days before the end and on the last day;
- after expiry the dashboard is **read-only**, not blocked;
- after the retention period the company is flagged for the team to decide on,
  and **never auto-deleted**.

**Reminders** (`application/organizations/trial.py`):
- **Queued by** the in-app scheduler tick (`runtime/automation_runner.py`), next to the
  project auto-DPR, as `trial_reminder` notification rows for each owner (ADMIN with a
  WhatsApp number). Each owner gets each reminder once.
- **Sent by** the notification sender:
  - plain text inside the 24-hour window ("Reply *CONTINUE*…");
  - outside it, the `mesiri_trial_ending` template, once it's approved (text in
    `docs/ops/whatsapp-templates.md`);
  - held during quiet hours, with a reason recorded whenever a reminder is skipped.

**After the trial ends** (`runtime/trial_journey.py`):
- **Owner:** "your trial ended on 22 Oct, data safe for 30 days" **[Continue with
  Mesiri]**.
- **Anyone else:** "ask <owner> to continue".
- **Suspended companies:** keep the generic reply.

**"Continue"** (a tap, typing CONTINUE, or `POST /company/trial/continue` from the
dashboard):
- records one open request in `organization_settings` `continue_requests` (refused by
  the generic settings API);
- posts in the team WhatsApp group;
- tells the owner the team will call. Converting to paid stays manual (SS-10).

**Read-only dashboard** (`domains/shared/trial_guard.py`, an app middleware):
- For a company whose trial has ended, every change request answers
  `403 {"code": "TRIAL_EXPIRED"}`. Reading still works.
- Login, code login, the webhook, health and `/company/trial/*` are exempt.
- No token, a bad token or a platform admin passes through untouched.
- The status is cached for a minute per company.

### The dashboard once the trial has ended (SS-15, built 15 Oct)

- **Banner on every page** (`apps/dashboard/src/components/trial-banner.tsx`): "Your
  free trial has ended — your data is read-only." The owner gets **Continue with
  Mesiri** (`POST /company/trial/continue`), then "our team will call you"; anyone else
  is told to ask the owner. An open request (from WhatsApp or the dashboard) shows as
  already asked.
- **Where the status comes from:** `/auth/me` now carries `company {status,
  trial_ends_at, trial_days_left, continue_requested}` (the effective status, so a
  trial past its end reads `expired`). It never fails the page: unreadable means no
  banner. Platform admins get `null`.
- **A refused save** (`403 TRIAL_EXPIRED`): the API client (`lib/api.ts`) turns the
  `{code, message}` detail into the message text, so every page's existing error
  display shows it (no generic error, no crash), and switches the app to read-only at
  once (`lib/trial.ts`), covering a page loaded just before the trial ended.
- **Edit actions hidden or disabled while read-only** (`useReadOnly()`): Today's "Send
  now" and "Mark as no work", the getting-started card, "Create Project", "Add User",
  and the letterhead save/upload. Everything else relies on the clear message.
- **During the trial**, the getting-started card's "N days left" links to the same
  Continue action.

## Trial guardrails (SS-09, built 15 Oct)

Protect cost and the shared WhatsApp number's quality rating once self-serve signup
is switched on. All limits are the platform setting `trial_guardrails`, changeable
(and audited) through `PUT /admin/platform-settings/trial_guardrails`. The control
panel's settings card doesn't show these fields yet; that's Lane B's.

**Before a signup** (`check_signup` in `application/organizations/signup_guard.py`):
both doors ask it. The web door (SS-06) asks on code request and before creating; the
WhatsApp door (SS-04) asks on the "Start free trial" tap and before creating. In order:

| Rule | Default | What the person is told |
| --- | --- | --- |
| Signup switch (`self_serve.signup_enabled`) | on (SS-16) | "Sign-up is closed for now…" |
| Number's country code is allowed | `["91"]` | "Mesiri is only available for Indian WhatsApp numbers for now…" |
| One free trial per number per N days | 365 | "This number has already had a free trial. Message us…" |
| Self-serve trials across the platform in 24 h | 25 | "We're getting a lot of sign-ups right now. Please try again tomorrow." |
| Web: different numbers from one IP in 24 h | 3 | same as above |

- **Past trials** come from the audit log (BE-05), which outlives deleted companies. A
  deleted trial doesn't free its number for a new one.
- **The daily count** is self-serve companies only; companies made by staff don't count.

**Flags**, recorded but never blocking:

| Flag | When |
| --- | --- |
| `shared_ip` | the IP was used by another number in 24 h |
| `previous_trial` | the number had a trial before the window |
| `burst` | signups are over 80% of the daily limit |
| `foreign_number` | the number's country isn't allowed |

Every check is logged in `signup_attempts` (migration 0480) with the outcome, reason and
flags. Read a number's flags with `PostgresSignupAttemptRepository.flags_for_phone`.
The web door rolls back on a refusal, so only its allowed attempts are kept (that's all
the per-IP count needs). Refusals are also in the app log (`signup.refused`), flags as
`signup.flagged`.

**During a trial** (`TrialUsageGuard` in `application/organizations/trial_usage.py`):
- **What's checked:** every inbound message from a `trial` company is checked against
  today's usage, from BE-25's cost rows since midnight India time.
- **Defaults:** ₹50 of AI and 200 WhatsApp messages a day. That's about 15 times a
  normal trial day.
- **When over:**
  - the sender gets "You've reached today's free-trial limit… back tomorrow morning";
  - no AI runs;
  - the message is still logged;
  - queued sends, such as the evening report, still go out.
- **Cost of the check:** cached a minute per company.
- **Fails open:** a broken check never blocks a message.
- **Paying companies** are never capped. A cap of 0 means no cap.

---

## Onboarding cards (SS-17, request 87)

Three Swiss-minimal images make the first minutes on WhatsApp look like one product. Target: from "Hi" to the first saved update in under 3 minutes, typing only the company and site names.

Code: `apps/whatsapp-assistant/src/channel/onboarding_cards/` (`data.py` view models, pure; `template.py` HTML/CSS, pure; `render.py` language choice and the PNG through `channel/receipt`'s `ReceiptRenderer`, unchanged), `runtime/signup_journey.py` (cards 1 and 2), `runtime/onboarding_progress.py` (card 3).

**Design system (all three):** 4:5, rendered 1080 x 1350, white, black Inter (Noto Sans Malayalam fallback), a 10 px uppercase tracked header `MESIRI · <TYPE>` over a 2 px rule, big left-aligned headline or number, thin grey row rules, green `#1a7f4b` only for done (filled dot), grey outline circle for pending, one black action box at the bottom. No other colours, no icons. English and Malayalam (the Malayalam header is not letter-spaced: tracking breaks Malayalam conjuncts).

| Card | Where | Content |
|---|---|---|
| 1 Welcome | `_welcome`: header image of the existing [Start free trial] [I'm in a company] message | "Your site, on WhatsApp" / "Tell me what happened. I keep the records." / Tell "6 mason, 10 helper vannu" · Ask "cement stock ethra?" · Get today's report as a PDF |
| 2 Site ready | `_create`: replaces the plain done-text; the caption carries the trial end date | green check, "<Site> is live.", "<Company> · <place>" (place = the part of the site name after the comma), Company ✓ · Site ✓ · Daily report at 9 pm On, action box "TRY IT NOW · Send: 6 mason, 10 helper vannu" |
| 3 Setup progress | `OnboardingProgress` | "N / 6", bar, "<site> · about X min left" (1 min per open step), six steps, action box "NEXT · Send: <first pending step>" |

Signup questions are labelled "Step 1 of 2" (company) and "Step 2 of 2" (site). If a card cannot be rendered or sent, the same message goes out as text (the card is never a reason to stop signup).

**Card 3 steps, all read-only from existing data:** Company & site (always) · First site update (an activity or timeline entry, as SA-02) · Materials list (an active `materials_catalog` row) · Company logo (branding logo uploaded, or the SS-14 branding question answered) · Site engineer (a `project_members` row with role SITE_ENGINEER) · Report time set (changed from default, or the SS-14 question answered: the dashboard checklist's rule). No attendance data is used.

**When card 3 goes out:** (a) right after the company's first saved update; (b) after a later step completes; (c) when the owner types `setup` or `setup status`, any time. (a) and (b) are unprompted: at most one a day, never while a confirmation or setup question is open, only to the ADMIN of a self-serve WhatsApp company in its first 30 days. The day a card goes out SS-14 asks nothing separately (the card's NEXT box is the ask); when the next step is the report time the question's buttons follow the card, because it is answered by a tap. The last card shown is a Redis hint (`user:<id>:onboarding_card`): if lost, the worst case is one extra card. Language: Malayalam card when the owner's remembered language (`reply_language.py`) is Malayalam (script or Manglish); during signup, when the company or site name is in Malayalam script.

Rendered examples (partial progress, EN and ML): [docs/product/onboarding-cards/](../product/onboarding-cards/).

Rollback: `git revert` the commits; signup is the text flow it was. No migration, no new tables.

Not built / known: the first-update, materials, logo and site-engineer NEXT messages are suggestions (`add material: TMT steel 12mm` is not a tested command); Malayalam wording has not been read by a native speaker; the live run below.

## Web intro and first-update screen (SS-18, built 25 Oct)

The web signup's first minutes, in the Swiss style the WhatsApp onboarding cards
(SS-17) use: white ground, a narrow time column, **what the site sent on the left,
what Mesiri made of it on the right**, hairlines between exchanges, black type and
site orange only for the report's rule and the one button.

- **One scene at a time, not one long page.** Both screens play as a slideshow in a
  single frame (`components/onboarding/scenes.tsx`): a numbered step bar on top
  (`01 · Voice note`, …) whose current step fills as the scene runs; each step is a
  button, and choosing one stops the automatic changes. On signup every scene sits in
  the same grid cell, so the frame keeps one height and nothing jumps.
- **`/signup`** plays an example evening beside the form
  (`components/onboarding/intro-conversation.tsx`), four scenes on a loop:
  01 Voice note (waveform inks in, Malayalam words arrive, English below) → 02
  Understood (10 workers counting up, the work, the issue) → 03 Report ("Send today's
  report." and the sheet drawing in) → 04 Your site ("One voice note in. A finished
  daily report out." and the button). The company and site are labelled an example.
  Narrow, the intro comes first and its button jumps to the form.
- **`/welcome`** is where signup now lands (`pages/WelcomePage.tsx`), full screen and
  skippable at every point. It shows Mesiri's WhatsApp number, a QR code and an
  "Open WhatsApp" link with the text pre-filled, then polls the owner's site day every
  3 s. Its steps are 01 Send · 02 Understood · 03 Report; it rests on Send until the
  first update arrives, then plays through with the owner's own data (their words,
  what Mesiri understood, the live report from WEB-27) and stops on the report, with
  "Looks right" (confirms the drafts through the existing confirm API) and "Change
  something" (the site's day page). After 10 minutes of nothing it stops polling and
  points at Today.
- **No demo mode.** Signup links the owner's number and makes the first site, so the
  first message is a real update on the real site (a one-site project files it with
  no "which site?" question). Nothing to clean up, and the checklist ticks for real.
- **Mesiri's number** comes from `MESIRI_WHATSAPP__DISPLAY_NUMBER` and is returned on
  `GET /company/setup-progress` as `whatsapp_number`. Unset, the welcome screen tells
  the owner to use the chat their sign-in code came from, and the checklist's "Copy
  invite" is hidden.
- **Checklist (SS-07) changes:** "Get the first update" links to `/welcome`; "Add your
  site supervisor" gains **Copy invite** (a message to forward with Mesiri's number and
  what to send); the logo link reads "Add logo".
- **Motion:** one clock per scene (`lib/timeline.ts`, `useScenes`) drives every reveal,
  the waveform and the count-ups; CSS transitions only, no animation library. With
  reduced motion nothing changes by itself and every scene shows complete.

Rollback: revert `navigate('/welcome')` in `Signup.tsx` and signup lands on Today as
before; everything else is additive. No migration.

Since then (25 Oct, approved by Alan):

- **Team: add by WhatsApp number (WEB-17).** Name, number, role and project; a dashboard
  login is opt-in. Created through the same `CreateUserHandler` WhatsApp uses
  (`application/identity/add_by_number.py`). Afterwards, a message to forward with
  Mesiri's number and "Send on WhatsApp": Mesiri can't message a new person first until
  an invite template is approved (SS-12). No separate Supervisor role: the checklist
  asks for "the person who reports from site".
- **Checklist (SS-19).** That step ticks only for an active site engineer or project
  manager with a WhatsApp number on a project. "Hide for now" is company-wide for 7 days
  (`POST /company/setup-progress/hide`, `/show`). A "Finish setup N/6" link sits in the
  sidebar's Setup group until everything is done.
- **Report time as a choice.** The step asks "When should the daily report go out?" with
  evening times from 6:30 pm (after the 6 pm close) and "Send it by itself" beside it.
  Save writes the first project's send time and auto-send (`PUT /projects/{id}`, as its
  Reporting tab does) and records the question answered (`report-time-ok`), so keeping
  9 pm counts too.
- **The first report going out** gets a one-time note on Today ("Your first daily report
  is out.", `components/first-report-moment.tsx`) for 3 days after `first_dpr_sent_at`,
  with *See the report* and *Send it to your client too* (the project's recipients).
  Closing it is remembered in that browser.
- **Not built: "Send it to my WhatsApp"** from the welcome screen, logged as WA-74. *Send
  now* publishes to every recipient, "send me today's DPR" needs the evening report
  (`not_generated` on day 0), and a dashboard-side sender would duplicate the WhatsApp
  sending path. The welcome screen's live report has *Print* (save as PDF) meanwhile.
- **Time saved on Today** (`components/time-saved.tsx`): "This week Mesiri sent 5 daily
  reports for you: about 2 h 5 min of writing saved." The count is real (project DPRs
  `PUBLISHED` in the last 7 days, the history API's total); the **25 minutes per report
  is an assumption**, stated in the line's tooltip and kept in one constant
  (`MINUTES_PER_REPORT`). Hidden until a report has gone out.

