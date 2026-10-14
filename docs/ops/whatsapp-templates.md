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

## Who receives the DPR, and opt-in (BE-15)

- Each project can have its own DPR list (`/dpr/projects/{id}/recipients`):
  company users and outside contacts (client, architect...) by name and phone.
  With no list, the project's admins and project managers get it, as before.
- **Opt-in:** Meta requires a person to agree before a business messages them.
  Company users count as agreed by joining the company. An **outside contact
  gets nothing until an opt-in is recorded**: an admin records it when adding
  them ("opted in", with a note on how, e.g. "contract clause 12"), or later
  with `.../recipients/{id}/opt-in`. The WhatsApp "reply YES" opt-in is WA-09.
- **Opt-out** (`.../opt-out`) stops every message to that number from that
  company, users included. Skipped messages are recorded on the notification
  row as `no_opt_in` or `opted_out`.
- Records are kept per company and phone in `whatsapp_opt_ins` (append-only;
  the latest row counts), with who recorded it and how.

## Templates still to add

Each is declared and submitted by its own tracker item: evening gap-check
(WA-04), no-update reminder (WA-06), welcome / opt-in (WA-09), signup login code
and trial messages (SS-06, SS-08, SS-12). Getting them all approved is WA-10.
