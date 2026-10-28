# Mesiri inside WhatsApp groups — plan (WA-87)

> Status: **approved 28 Oct 2026 (Ilan); code built 28 Oct, switched OFF.** Mesiri's number
> is an Official Business Account. What is left is on Meta's side and a live test: see
> *Switching it on*. Nothing reaches a customer until `WHATSAPP_GROUPS_ENABLED=true`.

## Built (28 Oct 2026)

| Piece | Where |
| --- | --- |
| Tables `whatsapp_groups`, `whatsapp_group_join_requests` (additive, row-level security) | `backend/migrations/versions/0492_whatsapp_groups.py` |
| Reads/writes of those tables | `apps/whatsapp-assistant/src/runtime/whatsapp_group_query.py` |
| Meta Groups API calls (create, invite link, approve / reject join requests) | `channel/whatsapp/groups.py` |
| Posting into a group: any send target `group:<id>` | `channel/whatsapp/outbound.py` |
| Everything else: creating, Meta's group webhooks, joining, the 1-on-1 command and Allow taps, reading group messages, the reply wrapper | `runtime/group_chat.py` |
| Group messages and `group_*` webhooks through ingress | `ingress/receiver.py`, `ingress/normalization.py` |
| Wiring + switch `WHATSAPP_GROUPS_ENABLED` | `runtime/dependencies.py`, `runtime/message_journey.py` (one hook, next to the super-admin alert replies) |
| Evening DPR into the project's site groups | `runtime/project_auto_dpr.py`, `runtime/send_pending_notifications.py` |
| Invite template `mesiri_group_invite` (4 body values, link in the body) | `channel/whatsapp/templates.py`, `docs/ops/whatsapp-templates.md` |
| Dashboard: `GET`/`POST /projects/{p}/sites/{s}/whatsapp-group`, admins only | `whatsapp_groups/router.py`; button in each site row: `apps/dashboard/src/components/site-whatsapp-group.tsx` |

How it behaves, as built:

- **Making a group:** dashboard button (company admin), or on WhatsApp 1-on-1: a company
  admin sends "make a group for Block A"; a super admin sends "make a group for Acme, Block A"
  (or "Acme Block A"). Anyone else in a company is told only the owner or an admin can; a
  stranger gets the usual unknown-sender reply. One group per site at a time.
- **When Meta says the group exists:** a welcome line in the group; each person on the site
  team (site members, project members with every site, company admins) gets the invite 1-on-1
  (the template outside 24 h); the creator gets the link to forward to the client. All through
  the notification queue, so opt-outs, the 24 h window and templates are handled as for the DPR.
- **Joining:** approval required. Site team: approved at once. Anyone else: the creator (else
  the company's admins) gets "+91… wants to join" with Allow / Don't allow, 1-on-1.
- **In the group:** a message from someone on the site team gets 👍 at once, is handled exactly
  like their 1-on-1 message with the group's site preselected, and the 👍 turns ✅ when it is
  saved. Everyone else is ignored (nothing saved, no reply, no 👍).
- **Private by default (stricter than point 3 below):** every reply, card and question,
  answers to questions included, goes to the sender 1-on-1. Only 👍/✅, the welcome line and
  the evening DPR go into the group. Reason: an answer can carry money or wages, and the client
  is in the group. If Meta refuses a private reply (no open chat with that person), one line in
  the group asks them to say hi to Mesiri.
- **Evening DPR:** the project DPR (PDF, card, text) also goes into each of the project's
  active site groups, at the same time as to the owner.

Not verified (no Meta access from the build session): the real webhook payloads, the
create-call answer, whether reactions and documents work in groups, whether a group message
opens the sender's 24 h window, the size limit. The parsing is deliberately tolerant and logs
every event it does not recognise (`group.event_ignored`), so the live test shows the truth.

## Switching it on

1. Meta (WhatsApp Manager / App dashboard): subscribe the app to `group_lifecycle_update`,
   `group_participants_update`, `group_settings_update`, `group_status_update`. Submit the
   `mesiri_group_invite` template (text in `docs/ops/whatsapp-templates.md`).
2. Server: `WHATSAPP_GROUPS_ENABLED=true` in the app's environment (web + worker), restart.
   When the template is approved, add `mesiri_group_invite` to `WHATSAPP_APPROVED_TEMPLATES`.
3. Live test with our own numbers only: make a group for a test site, join, send "8 masons
   today" and a photo, check the ✅, the site DPR, and that an outsider's message is ignored.
   Read `group.*` lines in the app log; fix any payload field the logs show differently.

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

## Creating a group and inviting people (approved 28 Oct)

What Meta allows: Mesiri calls `POST /<phone-number-id>/groups` with a name (`subject`, max
128 characters), an optional description and `join_approval_mode` (`auto_approve` or
`approval_required`). Meta answers with a `group_lifecycle_update` webhook carrying the group
id and an **invite link**. **There is no way to add a person directly**: everyone joins by
tapping the link. With `approval_required`, each tap becomes a join request that Mesiri
approves or rejects (`/<group-id>/join_requests`). Mesiri created the group, so it is its admin.

Proposed flow, so the owner has as little to do as possible:

1. **Start.** Any of:
   - the owner taps *Create WhatsApp group* on the site page in the dashboard;
   - a company owner or admin writes to Mesiri 1-on-1: "make a group for Kakkanad site";
   - a Mesiri super admin writes to Mesiri 1-on-1, naming the company:
     "make a group for Acme, Kakkanad site" (for trials our team sets up).
   Only these roles can create a group; anyone else is told to ask their owner.
2. **Mesiri creates it** as "Kakkanad site · Mesiri", with `approval_required`.
3. **Mesiri invites the team itself.** It already has the numbers of the people on that
   site, so it sends each of them the link 1-on-1 ("Join the Kakkanad site group: <link>").
   Outside the 24-hour window this needs a new template, `mesiri_group_invite`, approved by Meta.
4. **The owner gets the link too**, as a ready-to-forward message, to send to the client and
   our team.
5. **Joining.** A team member's tap is approved at once. Anyone else (the client, our team)
   is approved when the owner taps *Allow* on a card Mesiri sends them 1-on-1, so a forwarded
   link can't bring a stranger in. The 8-person limit is checked first; when full, the owner
   is told.
6. **Welcome.** When the group is ready, Mesiri posts one line in it: "Send today's work,
   photos and workers here. I'll save them to Kakkanad site."

## Scope

In: the gate, group ↔ site mapping, group reply routing, quiet mode, group creation + invite
link, DPR posted to the group, flag.
Out (later): several sites per group, clients asking questions in the group, moving an
existing group, groups larger than Meta's limit.

## Files expected to change

Planned layout before the build; see *Built* above for where things ended up (the site is
preselected through `WorkSite.preselect` instead of a resolver change; one module,
`runtime/group_chat.py`, instead of three).

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

- Everything behind `WHATSAPP_GROUPS_ENABLED` (default off). Off = group messages dropped at
  ingress (they never reach the 1-on-1 path), no group can be made, no DPR goes to a group.
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
1. Gate: group messages never go down the 1-on-1 path. **Done** (`ingress/receiver.py`: a message with `group_id` is dropped before it is claimed, so no read receipt, no save, no reply). The normalizer + flag move to step 3, where they are first needed.
2. Table, group creation, invite link, lifecycle webhook. **Done 28 Oct.**
3. Group reply routing + private-by-default + quiet mode + group pins site. **Done 28 Oct.**
4. Dashboard button; DPR posted to the group. **Done 28 Oct.**
5. Live test in our own test group, then the first customer trial. **Waiting on step 0.**

## Success criteria

- In a test group, an engineer sends a photo and "8 masons, plastering 2nd floor": it is saved
  to the group's site, the group sees ✅, and the site DPR shows it.
- An expense sent in the group: the confirmation reaches the sender 1-on-1, the group sees nothing.
- A message from a person who is not on the team: nothing saved, no reply.
- With the flag off, the 1-on-1 suite is unchanged and group messages are ignored.

## Decisions

Approved 28 Oct (Ilan): ~8-person limit, quiet mode, one group = one site, evening DPR posted
to the group, identity / tenant isolation as planned, labour messages arriving from groups
(replies stay 1-on-1).

Approved 28 Oct (Ilan): the creation / invite flow above, plus creation by a company admin or
a super admin messaging Mesiri directly.

## Sources

- Meta, Groups API: https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/
- Meta, Groups API get started: https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/get-started/
- Meta, group messaging: https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/groups-messaging/
- Woztell guide (8-person limit, OBA): https://support.woztell.com/portal/en/kb/articles/whatsapp-cloud-api-grupos-user-guide-woztell
- 360dialog, group management: https://docs.360dialog.com/docs/messaging/groups/group-management
