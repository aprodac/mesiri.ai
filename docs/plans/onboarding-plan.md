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
| 4 | Add a team member by sharing a contact; invite to forward | SS-13 (**done**) |
| 5 | One-screen create form + companies list in the control panel | SA-01 (**done**), SA-02 |
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
