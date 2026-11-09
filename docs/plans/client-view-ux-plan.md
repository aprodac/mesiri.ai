# Client view: rich UX plan (CV-05..CV-13)

> Asked by Ilan, 9 Nov 2026 ("in rich UI UX plan it"). Builds on CV-01..CV-03 (shipped `b8d4a1d`, `cb0022f`,
> [client-view-plan](client-view-plan.md)). **Plan only, not started.** The client view is security-sensitive (outside
> people see company data), so the decisions marked **D-CV4..D-CV9** wait for Ilan.
>
> Visual mock (6 phone screens, clickable): [Client view — rich UX](https://claude.ai/artifact/V3wZaQEbkqNNPDtrEWRyF8) (private until shared).

## Objective

Make the client's link something the house owner opens every week because it answers their questions in ten seconds
(how far, on time, what happened, what I owe), and something that saves the builder phone calls ("what is the
status?", "send photos", "how much do I owe?"). Today's page (CV-03) is one long scroll; this makes it an app.

## Business value

- Fewer calls to the PM and the owner: the questions clients ask most are answered on the page and in a Saturday
  WhatsApp message.
- Faster payment: the due amount, the bill, and how to pay are one tap away.
- A selling point: "your client sees the villa grow every week" (Kerala house owners abroad, NRI clients).
- Client questions, changes and complaints arrive written, with a photo, instead of in a phone call nobody records,
  and a change becomes a priced variation before it is built (module 25).

## Principles (from the mock)

1. **Home answers four questions on one screen:** how far (progress ring), on time (status pill and handover
   date), what happened this week (three lines from approved reports, four photos), what I owe (one bar, one
   button).
2. **Bottom tabs, thumb reach:** Home · Progress · Photos · Bills · Ask. Every tab has its own address
   (`/c/:token/photos`), so a WhatsApp message can point straight at it.
3. **The builder's brand, not Mesiri's:** the company's letterhead colour and logo (`brand_color`, already in the
   payload) colour the ring, the tab marker and the main button; Mesiri is one line at the bottom.
4. **Only what the company approved:** photos and "this week" come from approved/sent site reports only (as now).
   Nothing a supervisor sent that the engineer has not looked at.
5. **Explain, never only flag:** a late milestone says why ("steel came 3 days late; 2 days of rain") from the
   hindrance register, and whether the handover moves.
6. **Least work for the builder:** everything is drawn from data the site already sends on WhatsApp. The office
   types nothing new to make the page rich.
7. **Fast on 4G:** thumbnails in grids, full size only when opened; the page paints from cache, then refreshes.

## Screens and items

| ID | Item | What the client sees | Built from (reuse) | Size |
| --- | --- | --- | --- | --- |
| CV-05 | **App shell** | Bottom tabs, per-tab addresses, builder's colour, skeletons, "add to home screen", pull to refresh, last updated line | CV-03 page, `brand_color`, `ClientPage` payload | M |
| CV-06 | **Home** | Cover photo (latest approved), progress ring, On time / Late pill, handover countdown, next-milestone card, "This week on site" (3 lines + 4 photos), money bar with "See RA-01 · ₹4.8 L due", Ask strip | Schedule summary (`expected`, `slip_days`), next undone milestone, project DPR payload of the week's approved days (work lines), receivables | M |
| CV-07 | **Progress** | Done vs should-be %, milestone timeline (done / late with the reason / upcoming), floor-by-floor bars with one line of what is happening | `schedule_store.load` (`expected`, `state`, `days_late`), hindrance reasons (schedule store), `places.progress.roll_up` (LP) as % per floor, never quantities | M |
| CV-08 | **Photos** | Week by week, floor filter chips, full-screen viewer with swipe and caption, before / after of the same place with a slider | `progress_attachments` (approved days only, as now) grouped by week; `activities.location_id` → place for the floor filter; earliest and latest photo per place for before / after; paged `GET /client/{token}/photos?before=` | M |
| CV-09 | **Bills** | Due-now card, contract bar (paid / due / not billed / held back), each bill with status chip, received, left and "what is in this bill", bill PDF on the letterhead, statement PDF, when the next bill is expected | Payload bills (already), RA bill document page (NXT-02) behind the token, receipts, next milestone | M |
| CV-10 | **Pay** (needs **D-CV6**) | "Pay by UPI": the company's UPI ID and QR for the exact amount, "I have paid" with the UTR, finance confirms the receipt (NXT-03) | Company settings (new: UPI ID), `client_receipts` as `draft` until finance confirms | M |
| CV-04 | **Ask** (was "Later"; needs **D-CV7**) | Question / Change / Complaint, text, photo or voice; the thread with the engineer's replies; a priced change with Approve / Not now; a fixed complaint with the after photo | `site_issues` (new type `CLIENT`) so it reaches the PM like every Issue; replies typed on the dashboard; a change becomes a variation once NXT-04 exists | L |
| CV-11 | **Link preview** (needs **D-CV8**) | On WhatsApp the link shows the project name, % done and the cover photo, not "Mesiri" | nginx `location /c/` → a backend route that returns the SPA's `index.html` with this link's `og:` tags; `GET /client/{token}/card.png` (a rendered card, cached a day) | S |
| CV-12 | **Saturday digest and milestone messages** (needs **D-CV9**) | Every Saturday: % (+this week), 2–3 lines, next milestone, due, "6 new photos", buttons Open my project / Ask; "Ground floor slab cast today" when a milestone is marked done | An Automation (`automations` module) per link with the client's number (`clients.phone`); WhatsApp template messages (Meta approval: ops) | M |
| CV-13 | **Office side** | "Preview as client" on each link; send to the client's own number (`wa.me/<phone>`) prefilled; opened count and last opened (already); which tab they read most | `client_links` (add `phone`), open log per tab (additive) | S |

Later, not planned here: Malayalam / English toggle on the client page (the assistant already handles languages; the
page does not), a client login for several projects, architect / consultant access (module 30's directory).

## Decisions for Ilan

| # | Question | Recommendation |
| --- | --- | --- |
| D-CV4 | May the client see the **lines** of their own RA bill (work, quantity, client rate)? D-CV2 said "never rates": that meant our costs and budget rates; the printed RA bill already goes to the client with client rates. | **Yes, their own bill's lines only** (the same as the printed bill). Never budget rates, costs, suppliers. |
| D-CV5 | Should the client see **floor-by-floor %** and the **should-be %** (which shows when work is behind)? | **Yes.** Honest status with the reason builds trust; the reason comes from the hindrance register. |
| D-CV6 | **Pay by UPI**: a static UPI ID / QR with "I have paid" (finance confirms), or a payment gateway (Razorpay: fees, KYC, reconciliation), or neither? | **Static UPI + "I have paid"** for V1. No gateway, no money passes through Mesiri. |
| D-CV7 | **Client messages**: may a client raise a change and **approve a price** on the page, and is that approval the evidence for the variation? | **Yes for questions and complaints now** (they become Issues). Approving a price waits for Variations (NXT-04); until then "Change" is a question the PM answers. |
| D-CV8 | **Link preview with the cover photo**: WhatsApp's servers fetch and keep the preview image. OK to send a site photo there? | **Yes, a rendered card** (name, %, handover) with the photo; a per-company switch to leave the photo out. |
| D-CV9 | **Saturday digest**: send to every client with a link and a phone, or only when the office ticks "send weekly"? Needs a Meta-approved template (ops). | **Opt-in per link**, off by default. |

## Backend work

- `view.py`: add `next_milestone`, `this_week` (approved days' work lines, the DPR payload's own wording), `cover`
  (latest approved photo), `expected` (schedule's should-be %), `floors` (LP roll-up as % and one line), late
  reasons on milestones. Every new field joins the allow-list and its contract test.
- `GET /client/{token}/photos?before=&place=`: paged by week, thumbnails (`?w=` resize on the media route or
  stored thumbnails; whichever the storage provider allows).
- `GET /client/{token}/bills/{ref}`: one bill's document data (D-CV4) for the printable page.
- CV-04: `POST /client/{token}/messages` (text, photo upload, voice), `GET /client/{token}/messages`; stored as a
  `site_issues` row of type `CLIENT` + `client_messages` for the thread; per-link limit (10 a day) against spam.
- CV-10: company `upi_id` (settings), `POST /client/{token}/payments` → `client_receipts` `draft` with the UTR.
- CV-11: `GET /c/{token}` HTML shell with `og:` tags; `GET /client/{token}/card.png`.
- CV-12: an Automation kind `client_weekly`, a template, a send log.

## Frontend work

- Split `ClientViewPage.tsx` into `pages/client/` (shell, Home, Progress, Photos, Bills, Ask) with nested routes
  under `/c/:token`; one query for the summary, paged queries for photos and messages.
- Shared pieces: progress ring, contract bar, milestone timeline, photo grid + viewer (swipe, pinch), before / after
  slider, bottom tab bar. Brand colour from the payload as a CSS variable.
- Office: Preview as client, phone per link, weekly digest switch.
- `screens.mjs` (UX-10): add `/c/<stub>` and its tabs with a stubbed payload so every push checks them.

## Database work (all additive)

`client_links.phone`, `client_links.weekly_digest` (bool); `client_link_opens` (link, tab, at) or counters per tab;
`client_messages` (CV-04); `site_issues` type `CLIENT` (enum value); company setting `upi_id`; `client_receipts`
status `draft` with `utr` if not there. No data rewritten.

## Risks

- **More data on a public page:** every new field goes through the allow-list and the "never shows" test; D-CV4 and
  D-CV5 decide the two that matter.
- **Client messages from a link without a login:** anyone with the link can write. Rate limit per link, photos only
  through our upload (never a URL), the PM sees which link wrote.
- **WhatsApp templates and link previews** depend on Meta (template approval) and WhatsApp's crawler: an ops step,
  not code.
- **Photo weight on 4G:** without thumbnails the photo grid is slow. Thumbnails are part of CV-08, not an extra.
- **Payments:** a client saying "I paid" is not money in the bank. It stays a draft until finance confirms.

## Testing

Contract tests per route (allow-list keys, approved-only photos, cross-company, revoked link, message rate limit),
unit tests for the week grouping and before / after pairing, the UX-10 screenshot check on every client tab at
390 / 1440 px, and a browser run of the whole flow (make link → open → tabs → ask → reply → revoke) as for CV-03.

## Rollback

Each item ships behind its own commit; the shell (CV-05) keeps today's single page as the Home tab, so reverting a
tab never breaks the link. Migrations are additive; turning off a link still stops everything at once.

## Labour isolation

No labour data on the page (no headcount, no wages, no contractors); "this week" lines are work, not people. Labour
and Attendance are not touched.

## Success criteria

- A client sees how far, on time, this week and what they owe without scrolling (390 × 844).
- Every screen paints in under 2 s on a throttled 4G profile with 40 photos.
- Clients open their link at least weekly (open log), and the PM gets fewer "status?" calls (ask the trial companies).
- Not one field outside the allow-list reaches the page (contract test).

## Order

CV-05 → CV-06 → CV-07 → CV-08 → CV-09 → CV-13 (no decisions needed beyond D-CV4/D-CV5), then CV-04, CV-11,
CV-10, CV-12 as D-CV6..D-CV9 are decided.
