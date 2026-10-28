# Mesiri inside WhatsApp groups — plan (WA-87)

> Status: **plan, waiting for approval** (asked 28 Oct 2026; Mesiri's number is an
> Official Business Account, confirmed the same day). No product code written yet.

## Objective

The Mesiri business number is a member of a customer's WhatsApp group. People in the group
send site updates, photos and questions there, and get the same results they get in a 1-on-1
chat with Mesiri. That lets the team run trials and demos with the client in one group.

## Business value

- Trials happen where the customer already talks: one group with the owner, engineer and our
  team, instead of each person chatting with the bot alone.
- The client sees Mesiri working (saved updates, the evening DPR) without installing anything.
- Our team watches the trial live in the same group and can step in.

## What WhatsApp allows (Meta Cloud API "Groups API")

From Meta's docs and BSP guides (developers.facebook.com is blocked in the cloud session,
so the numbers below come from search results and **must be confirmed in the spike, step 0**):

| Point | What we know |
| --- | --- |
| Eligibility | Official Business Account. **We have it.** |
| Group size | **About 8 people, counting Mesiri's own number** (third-party guides; not yet seen on Meta's own page) |
| Who creates it | Mesiri creates the group through the API. It **cannot be added to a group a customer already made** |
| How people join | Through an invite link that Mesiri gets back after creating the group (`group_lifecycle_update` webhook) |
| Sending | The same `/messages` call with `"recipient_type": "group"` and `"to": <group id>` |
| Inbound | Group messages come in on our existing webhook, carrying the group id and the sender |
| Webhook fields to subscribe | `group_lifecycle_update`, `group_participants_update`, `group_settings_update`, `group_status_update` |
| Buttons / lists / Save cards in groups | **Unknown.** Examples only show text and templates. This decides how much of the 1-on-1 experience carries over |

The other route, the spare-SIM linked device (`teammate/`), was ruled out: it breaks
WhatsApp's terms, a number that sends to customers gets banned, and it cannot send buttons.
Teammate stays read-only, as it is today.

## How the assistant works today (investigation)

- Inbound: `ingress/webhook.py` → `ingress/receiver.py` (`_iter_message_contexts` reads
  `value.messages`) → `ingress/normalization.py` (sender = `message["from"]`) → pipeline.
- Identity is the sender's phone number (`sender.wa_id`), resolved to a company user.
- Replies go to the sender: `sender.wa_id` appears 55 times in 14 files; every send goes
  through `channel/whatsapp/outbound.py` `WhatsAppSender._send`, which hard-codes
  `"recipient_type": "individual"`.
- A sender wrapper pattern already exists: `runtime/forward_batch.py` `BatchingSender`
  wraps `WhatsAppSender` and changes behaviour through a context variable. Group replies
  reuse that pattern instead of touching the 55 call sites.
- **Regression risk found:** nothing checks for a group today. Once Mesiri is in a group,
  a group message would be handled as a 1-on-1 message and the reply would go **privately to
  the sender**. The first code change is the gate that stops that.

## Proposed behaviour (defaults, see Decisions)

1. **One group = one site.** The group is created for a site; every update in it belongs to
   that site, so nobody is asked "which site?".
2. **Who Mesiri listens to.** Messages from people on that company's team are processed as
   usual. Messages from anyone else (the client, our team) are ignored: nothing saved, no reply.
3. **Quiet by default.** A site update (photo, "10 masons today", material arrived) is saved
   and acknowledged with a ✅ reaction, or a single short line if reactions don't work in
   groups. Mesiri writes a full reply only when someone @mentions it, replies to its message,
   or asks a question.
4. **Private things stay private.** Money (expenses, petty cash), labour pay and wages, login
   codes, setup questions and ops alerts are sent to the person 1-on-1, never into the group.
   This is an allowlist: only listed reply kinds may go to a group; everything else goes 1-on-1.
5. **Evening DPR.** After the engineer confirms it, the site DPR PDF is also posted into the
   group, so the client sees the result.
6. **Creating a group.** A "Create WhatsApp group" button on the site page in the dashboard,
   plus a WhatsApp command for the owner ("make a group for Kakkanad site"). Both return the
   invite link to share.

## Scope

In: the gate, group ↔ site mapping, group reply routing, quiet mode, group creation + invite
link, DPR posted to the group, flag.
Out (later): several sites per group, clients asking questions in the group, moving an
existing group, groups larger than Meta's limit.

## Files expected to change

| Area | Files |
| --- | --- |
| Ingress | `ingress/receiver.py` (read group id; lane key = group + sender), `ingress/normalization.py` (`metadata.chat_kind`, `metadata.group_id`), new `ingress/group_gate.py` |
| Replies | new `runtime/group_reply.py` (sender wrapper + context variable + allowlist), `channel/whatsapp/outbound.py` (`recipient_type` from the target), `runtime/dependencies.py` (wrap the sender) |
| Context | `context/resolver.py` (a group pins the site) |
| Groups | new `groups/` (Meta Groups API client, lifecycle webhook handler, create command) |
| DPR | the existing DPR send path: also post to the site's group |
| Backend | additive migration `0492_whatsapp_groups` (group id, company, site, invite link, status, created by/at); model + repository |
| Dashboard | site page: "Create WhatsApp group" button, invite link, status |
| Tests | unit tests per new module, replay cases for group payloads, migration test |

## Backend / database / API work

- Table `whatsapp_groups`: `id`, `company_id`, `site_id`, `wa_group_id` (unique),
  `invite_link`, `status` (creating / active / closed), `created_by_user_id`, timestamps.
  Additive only. The head is `0491` today; re-check right before writing it.
- `POST /sites/{id}/whatsapp-group` (create), `GET /sites/{id}/whatsapp-group` (status + link).
  Scoped like every other site endpoint (company + site permission).

## Risks

| Risk | Mitigation |
| --- | --- |
| A group message leaks a private reply into the group | Allowlist, default 1-on-1; tests for every private flow |
| Wrong company or site: tenant isolation | A group belongs to one company; the sender must be a member of that company **and** the site; otherwise ignored |
| 8-person limit is too small for a real site team | Confirmed in step 0 before building; product decision |
| Buttons / Save cards don't work in groups | Step 0 checks it; fallback: the Save card goes 1-on-1 to the sender, the group gets the ✅ |
| Labour attendance photos sent in the group | Labour behaviour unchanged; its replies stay 1-on-1. Needs Alan's ok (Module Isolation) |
| Group messages billed differently | Step 0 reads pricing; BE-25 already logs Meta's pricing per message |
| Spam: Mesiri talking too much in a busy group | Quiet mode (point 3) |

## Testing strategy

- Unit: normalizer (group payload), gate (unknown group, outsider, member), reply wrapper
  (group vs private kinds), resolver (group pins site), lane key.
- Replay suite: group versions of existing cases (photo, workers count, correction, question).
- Integration: migration + repository on Postgres; endpoints scoped by company.
- Regression: the full WhatsApp suite (1-on-1 behaviour must not change with the flag off
  **or** on).
- Live: one real test group (our numbers only) before any customer group.

## Rollback

- Everything behind `MESIRI_WHATSAPP_GROUPS` (default `off`). Off = group messages ignored
  (still the gate, so they never reach the 1-on-1 path).
- Revert the commits; the migration is additive, so the table can stay.
- On Meta's side, unsubscribe the group webhook fields; Mesiri can leave the groups it made.

## Labour isolation

No Labour, Attendance, Payroll or Workforce code changes. Their replies are on the private
side of the allowlist. Attendance photos sent in a group follow the normal labour flow with
replies 1-on-1. This still changes where labour messages *come from*, so it needs Alan's ok.

## Steps

0. **Spike (no product code; needs someone with Meta Business Manager access):** subscribe the
   group webhook fields, create one test group through the API, and record: the size limit,
   the inbound payload shape, whether buttons, lists, reactions and documents work, and pricing.
   Result goes into this doc.
1. Gate + normalizer + flag (group messages never go down the 1-on-1 path).
2. Table, group creation, invite link, lifecycle webhook.
3. Group reply routing + allowlist + quiet mode + group pins site.
4. Dashboard button; DPR posted to the group.
5. Live test in our own test group, then the first customer trial.

## Success criteria

- In a test group, an engineer sends a photo and "8 masons, plastering 2nd floor": it is saved
  to the group's site, the group sees ✅, and the site DPR shows it.
- An expense sent in the group: the confirmation reaches the sender 1-on-1, the group sees nothing.
- A message from a person who is not on the team: nothing saved, no reply.
- With the flag off, the 1-on-1 suite is unchanged and group messages are ignored.

## Decisions needed

1. Is a group size of about 8 enough for trials? (Confirmed in step 0.)
2. Quiet mode (✅ + reply only when asked) or a confirmation for every update?
3. One group = one site, or one group per project?
4. Should the evening DPR be posted into the group for the client?
5. Approval: identity / tenant isolation (security-sensitive) and labour messages arriving
   from groups (Module Isolation).

## Sources

- Meta, Groups API: https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/
- Meta, Groups API get started: https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/get-started/
- Meta, group messaging: https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/groups-messaging/
- Woztell guide (8-person limit, OBA): https://support.woztell.com/portal/en/kb/articles/whatsapp-cloud-api-grupos-user-guide-woztell
- 360dialog, group management: https://docs.360dialog.com/docs/messaging/groups/group-management
