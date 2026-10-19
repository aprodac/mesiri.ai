# WhatsApp message templates (WA-12)

Meta only delivers a message Mesiri starts **outside the 24-hour window** (the
recipient has not messaged the number in the last 24 h) if it is built from a
template that was submitted and **approved** in WhatsApp Manager. Inside the
window Mesiri keeps sending normal messages; templates are only the fallback.

How it works in code:

- Each template is declared in
  [`apps/whatsapp-assistant/src/channel/whatsapp/templates.py`](../../apps/whatsapp-assistant/src/channel/whatsapp/templates.py)
  with exactly the name, language and shape submitted to Meta.
- It is only sent once its name is also listed in the server setting
  `WHATSAPP_APPROVED_TEMPLATES` (comma-separated). Until then a notification
  that needs it is skipped, and the notification row says why:
  `template_not_approved:<name>`.
- Failed deliveries Meta reports later show in the app log as
  `whatsapp.delivery_failed wamid=... code=... title=...`; the matching
  `whatsapp.template_sent name=... wamid=...` line says which template it was.

## Switching a template on

1. Submit it in WhatsApp Manager → Message templates, exactly as below (name,
   category, language, header, body, footer). Use the sample values given.
2. Wait for **Approved**. If Meta changes the category (e.g. Utility →
   Marketing), tell the team before switching it on: the price differs.
3. On the server, add the name to `/opt/mesiri/.env`:
   `WHATSAPP_APPROVED_TEMPLATES=mesiri_dpr_delivery` (comma-separate more), then
   restart `mesiri` and `mesiri-worker`.
4. To switch every template off again: empty the setting and restart. Behaviour
   is then exactly as before WA-12.

## Templates

### `mesiri_dpr_delivery` — the project DPR

Sent by the evening DPR send (BE-16) to an owner/PM who has not messaged in 24 h.

| Field | Value |
| --- | --- |
| Name | `mesiri_dpr_delivery` |
| Category | Utility |
| Language | English (`en`) |
| Header | Document (the DPR PDF) |
| Body | `Daily progress report for {{1}}, {{2}}. {{3}} The PDF is attached; reply here if anything needs fixing.` |
| Footer | `Sent by Mesiri` |
| Buttons | None |

Sample values for the submission: `{{1}}` = `Green Towers`, `{{2}}` = `13 Oct 2026`,
`{{3}}` = `1 of 3 sites not reported.` Sample document: any DPR PDF.

What fills the variables: `{{1}}` the project name, `{{2}}` the report date,
`{{3}}` "All sites reported." / "N of M sites not reported." / "Confirmed by the
site engineer." (single-site projects), plus " Sent on request." after "Send now".

### `mesiri_login_code` — login / signup code (SS-06, WEB-12)

Sent when someone asks for a code on the dashboard's sign-in or signup page.
Authentication templates have fixed wording set by Meta; you only choose the
options below.

| Field | Value |
| --- | --- |
| Name | `mesiri_login_code` |
| Category | **Authentication** |
| Language | English (`en`) |
| Code delivery | **Copy code** (button text: `Copy code`) |
| Body (fixed by Meta) | `{{1}} is your verification code.` |
| Add security recommendation | **On** ("For your security, do not share this code.") |
| Add expiry time | **On**, **10 minutes** |

Sample value: `{{1}}` = `482913`. The code is sent as the body parameter and as
the Copy code button's parameter.

To switch it on: add `mesiri_login_code` to `WHATSAPP_APPROVED_TEMPLATES`.
`MESIRI_LOGIN_CODE_SENDER` must be unset or `whatsapp` (never `dev` on a server
real people use: `dev` shows the code on the page instead of sending it).

### `mesiri_site_day_review` — the evening review of a site's day (WA-04)

Sent between the project's cutoff and its send deadline to a site engineer
who has not messaged in 24 h, when their site's day is missing something
(no work items, or no labour count). Engineers who reported that day are
usually inside the window and get the full message instead, with a
**Site closed today** button. Tapping **Open report** opens the window and
brings that full message.

| Field | Value |
| --- | --- |
| Name | `mesiri_site_day_review` |
| Category | Utility |
| Language | English (`en`) |
| Header | None |
| Body | `Today's report for {{1}}: {{2}} Please reply before {{3}} so it goes out complete.` |
| Footer | `Sent by Mesiri` |
| Buttons | Quick reply: `Open report` |

Sample values for the submission: `{{1}}` = `Block A (Green Towers)`,
`{{2}}` = `Labour count is missing.`, `{{3}}` = `9:00 pm`.

What fills the variables: `{{1}}` the site (with its project when the names
differ), `{{2}}` what is missing ("Labour count is missing." / "Work done and
labour count are missing."), `{{3}}` the project's send deadline. The button
is sent with a payload naming the site and day, so the tap needs no memory.

### `mesiri_site_no_update` — no update from a site today (WA-06)

Declared in code since WA-06 (`SITE_NO_UPDATE`). Sent once per site per day
at the project's cutoff when the site sent nothing at all (if it then sends
something partial, the evening gap-check follows). Inside the 24-hour window
the same reminder goes as a normal message with the same button.

| Field | Value |
| --- | --- |
| Name | `mesiri_site_no_update` |
| Category | Utility |
| Language | English (`en`) |
| Header | None |
| Body | `No update has come in today for {{1}}. Send today's work, labour and photos here before {{2}}, or tap below if the site was closed.` |
| Footer | `Sent by Mesiri` |
| Buttons | Quick reply: `Site closed today` |

Sample values: `{{1}}` = `Block A (Green Towers)`, `{{2}}` = `9:00 pm`.

To switch it on: add `mesiri_site_no_update` to `WHATSAPP_APPROVED_TEMPLATES`.

### `mesiri_dpr_optin` — asking an outside DPR contact to opt in (WA-09)

Sent once when an outside contact (client, architect...) is added to a
project's DPR list without an opt-in on record. A new contact has never
messaged the number, so this always goes as the template.

| Field | Value |
| --- | --- |
| Name | `mesiri_dpr_optin` |
| Category | Utility |
| Language | English (`en`) |
| Header | None |
| Body | `{{1}} would like to send you the daily progress report for {{2}} on WhatsApp. Reply YES to receive it, or STOP to never be messaged.` |
| Footer | `Sent by Mesiri` |
| Buttons | Quick replies: `YES`, `STOP` |

Sample values: `{{1}}` = `Suresh Builders`, `{{2}}` = `Green Towers`.

To switch it on: add `mesiri_dpr_optin` to `WHATSAPP_APPROVED_TEMPLATES`.

### `mesiri_trial_ending` — trial ending soon (SS-08)

Sent to a trial company's owner 2 days before and on the last day of the free
trial, when they haven't messaged Mesiri in the last 24 hours (inside the window
the same reminder goes as plain text).

| Field | Value |
| --- | --- |
| Name | `mesiri_trial_ending` |
| Category | **Utility** |
| Language | English (`en`) |
| Body | `Your Mesiri free trial for {{1}} ends on {{2}}. Reply CONTINUE and our team will call you to keep your daily reports going.` |

Sample values: `{{1}}` = `Suresh Builders`, `{{2}}` = `22 Oct`.

To switch it on: add `mesiri_trial_ending` to `WHATSAPP_APPROVED_TEMPLATES`.

### `mesiri_join_request` — someone asked to join the company (SS-05, SS-12)

Sent to each company admin when a newcomer sends `JOIN <code>`, if that admin
hasn't messaged Mesiri in the last 24 hours (inside the window the same alert
goes as a normal message with the same buttons). Until it is approved, an
admin outside the window is not alerted (logged as
`team_join.admin_not_reached ... reason=outside_window`).

| Field | Value |
| --- | --- |
| Name | `mesiri_join_request` |
| Category | Utility |
| Language | English (`en`) |
| Header | None |
| Body | `{{1}} (+{{2}}) wants to join {{3}} on Mesiri with your join code. Approve them?` |
| Footer | `Sent by Mesiri` |
| Buttons | Quick replies: `Approve`, `Reject` |

Sample values: `{{1}}` = `Ravi Kumar`, `{{2}}` = `919876543210`, `{{3}}` = `Suresh Builders`.

The taps carry the request's id, so Approve / Reject work exactly like the
in-window buttons (only an admin of that company can decide).

To switch it on: add `mesiri_join_request` to `WHATSAPP_APPROVED_TEMPLATES`.

## Who receives the DPR, and opt-in (BE-15)

- Each project can have its own DPR list (`/dpr/projects/{id}/recipients`):
  company users and outside contacts (client, architect...) by name and phone.
  With no list, the project's admins and project managers get it, as before.
- **Opt-in:** Meta requires a person to agree before a business messages them.
  Company users count as agreed by joining the company. An **outside contact
  gets nothing until an opt-in is recorded**: an admin records it when adding
  them ("opted in", with a note on how, e.g. "contract clause 12"), or later
  with `.../recipients/{id}/opt-in`.
- **WhatsApp opt-in (WA-09):** a contact added without one is sent one invite
  (`mesiri_dpr_optin`, never repeated, never sent after an opt-out). Their
  YES or STOP (typed or tapped) is recorded as `whatsapp_reply` for every
  company that invited the number. Only numbers that aren't company users
  are read this way, so a user typing "stop" mid-chat is never opted out.
- **Opt-out** (`.../opt-out`) stops every message to that number from that
  company, users included. Skipped messages are recorded on the notification
  row as `no_opt_in` or `opted_out`.
- Records are kept per company and phone in `whatsapp_opt_ins` (append-only;
  the latest row counts), with who recorded it and how.

## Templates still to add

Each is declared and submitted by its own tracker item: team invite (SS-13,
text in docs/plans/onboarding-plan.md), SS-12.
The evening review (WA-04), the no-update reminder (WA-06), the trial
ending (SS-08) and the login code (SS-06) are above. Getting them all
approved is WA-10.
