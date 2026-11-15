# Guided onboarding — a start that fits the person

> **Status: proposed, 15 Nov 2026. Waiting for Ilan's approval. No code written.**
> Tracker items: **SS-26 to SS-37** in [V1_TRACKER.md](V1_TRACKER.md).
> Builds on [onboarding-plan.md](onboarding-plan.md) (agreed 15 Oct) and does not replace it.

## 1. The question that started this

Can someone who knows nothing about software, and nothing about construction, set up Mesiri
and move their data in without help? And does Mesiri treat a beginner, an expert and someone
coming from other software differently, the way a game asks "have you played before?" first?

**Today: no.** Mesiri has one onboarding path and everyone gets it.

## 2. What exists today (investigation)

| Piece | Where | What it does |
| --- | --- | --- |
| WhatsApp signup (SS-04, SS-22) | `apps/whatsapp-assistant/src/runtime/signup_journey.py`, `interactions/signup_state.py` | Set up my company / Join my team / What is Mesiri? Then company name, site, owner name, confirm |
| Web signup + intro (SS-06, SS-18) | `apps/dashboard/src/pages/Signup.tsx`, `components/onboarding/` | Example evening in six scenes, then phone, code, names |
| Welcome screen (SS-18) | `pages/WelcomePage.tsx` | Mesiri's number and QR, waits for the first real update, shows what was understood and the report |
| Getting-started checklist (SS-07, SS-19) | `components/getting-started-card.tsx`, `lib/setup.ts`, `backend/.../organizations/setup_router.py` | Six steps for the company admin, each worked out from the data. "Hide for now" for 7 days |
| Daily setup questions (SS-14) | `backend/.../organizations/setup_questions.py`, `apps/whatsapp-assistant/src/runtime/setup_questions.py` | One question a day on WhatsApp: logo, report time, more sites |
| A person's own preferences (WA-169) | `backend/.../identity/preferences_router.py` (`/me/preferences`) | Reply language and voice transcript, stored on the person's `users` row |
| What every page is for | `apps/dashboard/src/lib/module-map.ts` | 79 built pages, each with `about`, `example`, and for many the WhatsApp message that feeds it |
| Sidebar by role | `components/app-sidebar.tsx`, `components/home/role-home.tsx` | Sections ordered by role; pages hidden by role and by module |
| Excel imports | `components/materials/import-dialog.tsx` (items, vendors, opening stock, minimum stock), `components/schedule/boq-import-dialog.tsx` (BOQ, reads the customer's own file) | Template download, upload, preview |
| Sample data | `apps/whatsapp-assistant/src/admin/demo.py` (SA-30, SA-36) | Two weeks of believable records, only for the Mesiri team's demo company |
| Field guides (LRN) | tracker section LRN | Ten guides on how construction works, a glossary planned as guide 09 |
| Trials funnel (SS-11) | control panel → Trials | Started → first update → first report → converted |

**What is missing**

1. Nobody is asked who they are. The only thing Mesiri knows about a person is their role.
2. The checklist, the sidebar and the WhatsApp messages are the same for a first-time user
   and for someone who has run three other tools.
3. No page explains itself when you open it for the first time. The text exists in
   `module-map.ts` but is only shown on planned pages.
4. Construction words (DPR, BOQ, RA bill, GRN, shuttering) are never explained.
5. The imports exist but are scattered, one inside Materials and one inside Schedule. A person
   arriving with spreadsheets has no single place that says "bring these, in this order".
6. No import for workers, clients, open purchase orders or opening balances, and none from
   another product's export.
7. A team member who joins later gets a welcome message on WhatsApp and nothing on the
   dashboard. The checklist is for the company admin only.

## 3. Objective

Every person gets a start that fits them, chosen with **one tap**, changeable at any time:
a beginner is led by the hand, someone with spreadsheets is taken to the imports, and an
experienced user is left alone.

## 4. Scope

**In**

- One question, asked once per person, with four answers (section 6).
- The answer changes four things on the dashboard: the checklist, how much of the sidebar
  shows, whether pages explain themselves, and whether "Bring your data" comes first.
- A "What is this page?" button on every page, for everyone.
- Plain-word explanations of construction terms.
- One "Bring your data" page that gathers the imports that already exist.
- The same question on WhatsApp, and tips that match the answer.
- The answer shown in the control panel's trials funnel.

**Out (listed in section 14 as later work)**

- Importers for other products' exports (Tally masters, other construction software).
- A workers import: it changes Workforce, which needs its own approval.
- A sample site inside a real company.
- Video.
- Malayalam and Hindi wording for the dashboard tips (the dashboard is English today).

## 5. Business value

- **Fewer trials that stall.** The funnel's biggest drop is before the first update. A
  beginner who is told exactly what to do next is more likely to send it.
- **Faster switch from spreadsheets.** A builder with a materials list and a BOQ in Excel can
  be loaded in an hour instead of typing for days. The imports are built; people do not find them.
- **Experienced users are not slowed down.** No cards, no tips, everything open.
- **Less hand-holding by the Mesiri team.** Fewer "where do I…" messages in the group.
- **We learn who signs up.** The funnel split by answer tells us which kind of customer converts.

## 6. The design

### 6.1 The question

> **How would you like to start?**
>
> 1. **Show me step by step** — I'm new to tools like this.
> 2. **I have my data in Excel or on paper** — help me bring it in.
> 3. **I've used other construction software** — show me where things are.
> 4. **I'll find my way** — no tips.

Stored as the person's **start mode**: `guided` · `bring_data` · `switching` · `free`.

Rules:

1. **One tap, never a form.** The existing rule "WhatsApp, not forms; default everything"
   stands.
2. **Never before the first value.** It is not a signup step. Nothing about creating the
   company changes.
3. **Skippable.** No answer means `guided`, which is the safe side: tips can be closed, a
   missing tip cannot be found.
4. **Per person, not per company.** The owner may be an expert and the accountant new.
5. **Changeable.** Settings → "How Mesiri guides me", and "Show me around again".
6. **It only changes help, never access.** Roles and modules still decide what a person may
   see and do. A mode never hides data from someone allowed to see it; "Show everything" is
   always one tap away.

"I don't know construction" is deliberately **not** a fifth answer. Asking a builder whether
they know construction is insulting, and the people who don't (an accountant, an office
assistant, the owner's family) are mostly known by role. Instead the term explanations
(6.5) are there for everyone, and are shown opened-up in `guided` mode.

### 6.2 What each mode gets

| | `guided` | `bring_data` | `switching` | `free` |
| --- | --- | --- | --- | --- |
| Checklist on Today | The six steps, each with a "why" line and one button | Six steps + "Bring your materials list", "Bring your BOQ" | Same as `bring_data`, + "Where things are" | Hidden (still under Finish setup) |
| Sidebar | Short: the daily pages for the role, + "Show everything" | Full | Full | Full |
| Page explains itself on first visit | Yes | Only on the import pages | No | No |
| "What is this page?" button | Yes | Yes | Yes | Yes |
| Term explanations | Underlined, open on tap | On tap | On tap | On tap |
| "Bring your data" page | In the sidebar | **Landing step after the first update** | In the checklist | In Settings |
| WhatsApp tips, first week | One a day | One, about sending the Excel/BOQ | None | None |

### 6.3 Where the question is asked

- **Web:** on `/welcome`, while the owner waits for their first update to arrive (dead time
  today). For a team member, a small dialog on their first dashboard login.
- **WhatsApp:** as the first of the daily setup questions (SS-14's mechanism), sent the
  morning after signup, with the four answers as list rows. Not during signup.
- Answered in one place, it is not asked in the other (the same record, as report time
  already works).

### 6.4 Pages that explain themselves

`module-map.ts` already says, for each page, what it is for, an example, and the WhatsApp
message that fills it. That text becomes:

- a **"?" button** in every page header (all modes) that opens the three lines, and
- a **strip at the top on the first visit** in `guided` mode, closed with one tap and
  remembered for that person.

No tour library, no arrows pointing at buttons: those break every time a page changes, and
the team changes pages daily. Text that lives next to the page definition stays true.

### 6.5 Construction words in plain language

One glossary file (term, one plain sentence, an example) and one small `<Term>` component
that underlines the word and shows the sentence on tap. Starts with about 40 terms taken
from the field guides (LRN, guide 09). Used first on the checklist, Today, Daily reports,
BOQ, Materials and the money pages.

### 6.6 Bring your data

One page, `/bring-data`, listing what can be brought in, in the order that makes sense, each
row showing whether it is already in:

1. Sites and projects (form; a handful at most)
2. Team (share a contact on WhatsApp, or the Team page)
3. Materials, vendors, opening stock (existing Excel import)
4. BOQ / estimate (existing Excel import, reads the customer's own file)
5. Drawings and documents (existing upload)
6. "Something else? Send the file to Mesiri on WhatsApp and our team will load it" — a
   request to the Mesiri team, the same way the letterhead photo already goes (SS-14).

It opens the dialogs that exist. No new importer in this plan.

### 6.7 Built for a product that keeps changing

Mesiri is still in development: pages are added, renamed and reshaped every week. Guidance
that is written once and left alone would be wrong within a month, and wrong guidance is
worse than none. So the guidance is built to change with the product, by these rules:

1. **One source for each fact.** What a page is for lives only in `module-map.ts`, beside
   the page's route. Checklist steps are ticked from the data, never by hand. The import
   templates are made by the backend that reads them. Nothing is described in two places.
2. **No guidance tied to the screen's layout.** No arrows pointing at buttons, no
   "click the third tab", no screenshots inside the product. Text says what the page is for
   and what to send on WhatsApp, which stays true when the layout changes.
3. **A new page cannot ship without its explanation.** A test fails when a page marked
   `built` has no `about` and `example`, or when a checklist step or a "Bring your data"
   row links to a route that no longer exists. Whoever changes a page fixes its guidance in
   the same commit, because the push is refused otherwise.
4. **Modes are data, not code paths.** One table says what each mode shows (the one in 6.2).
   Adding a fifth mode, or changing what `guided` shows, is an edit to that table, not to
   every page.
5. **Changes are told to the people they affect.** Each page's guide carries a version. When
   a page changes in a way a user would notice, its version goes up and the strip comes back
   once as "Updated: …" with one line on what is new, for `guided` users on the page and for
   everyone under a "What's new" entry. `free` users are not interrupted.
6. **New features join the path by themselves.** A new import added to the imports list
   appears on "Bring your data"; a new module switched on for a company appears in the
   sidebar and gets its strip, with no onboarding work.
7. **Small pieces, each useful alone.** Every tracker item can ship, be changed or be removed
   without the others. If the answers in 6.1 turn out wrong after the first trials, the
   wording and the table change; stored answers that no longer exist fall back to `guided`.
8. **Looked at again on a schedule.** SS-36 (watching real people) is repeated after any
   large change to signup, Today or the sidebar, and the funnel by mode is read monthly.

## 7. Files expected to change

**Backend**

- `backend/migrations/versions/0553_users_start_mode.py` (new; the number is checked again
  right before writing)
- `backend/src/mesiri/domains/identity/preferences_router.py` (start mode, pages seen)
- `backend/src/mesiri/domains/organizations/setup_questions.py` (one more question)
- `backend/src/mesiri/domains/organizations/setup_router.py` (data-in flags for the checklist)
- `backend/src/mesiri/application/organizations/companies_overview.py`,
  `platform_overview.py` (funnel split)
- tests beside each

**Dashboard**

- `apps/dashboard/src/lib/start-mode.ts` (new), `lib/glossary.ts` (new), `lib/api.ts`,
  `lib/setup.ts`, `lib/module-map.ts` (an `essential` flag on the daily pages)
- `components/onboarding/start-question.tsx` (new), `components/page-guide.tsx` (new),
  `components/term.tsx` (new), `lib/guide-check.test.ts` (new: the test in 6.7 rule 3)
- `components/getting-started-card.tsx`, `components/app-sidebar.tsx`
- `pages/WelcomePage.tsx`, `pages/SettingsPage.tsx`, `pages/BringDataPage.tsx` (new), `App.tsx`

**WhatsApp assistant**

- `apps/whatsapp-assistant/src/runtime/setup_questions.py` (ask and record the answer)
- `apps/whatsapp-assistant/src/channel/onboarding_cards/` (the question card)
- `agent_api/tools.py` `ALLOWED` + one line in `agent_api/SOP.md`, so "stop the tips" or
  "guide me again" said in chat works through the same `/me/preferences` route (v3 rule)

**Docs:** this file, `onboarding-plan.md`, `V1_TRACKER.md`.

## 8. Work by layer

**Database.** One additive migration: `users.start_mode` (text, nullable, checked against
the four values) and `users.guide_seen` (jsonb, default `{}`: pages whose strip was closed, with the guide version seen).
Nullable means "not asked yet"; nothing existing is rewritten. Same pattern as
`reply_language` (migration 0501).

**API.** Extend `GET /me/preferences` with `start_mode` and `guide_seen`; add
`PUT /me/preferences/start-mode` and `POST /me/preferences/guide-seen`. Self only, the id
from the token, exactly as the reply-language route works. `GET /company/setup-progress`
gains `has_materials` and `has_boq`. No new router.

**Backend.** One more entry in the setup questions (`start_mode`), ordered first. Funnel
query groups trials by the owner's start mode.

**Frontend.** A `useStartMode()` hook read once and shared (like `useSetupProgress`). The
checklist builds its steps from the mode. The sidebar's existing `pageVisible` filter gains
one condition, with the "Show everything" switch next to the existing planned-modules switch.

**WhatsApp.** The question goes out through the existing daily-question sender. Tips are
fixed lines chosen by mode, sent only inside the 24-hour window (no new template needed).

## 9. Risks

| Risk | How it is handled |
| --- | --- |
| The question itself is friction and people leave | Asked after signup, in dead time, one tap, skippable, default applies |
| People pick the wrong answer | Changeable in Settings; `guided` tips close with one tap; "Show everything" always visible |
| The short sidebar makes someone think a feature does not exist | Only in `guided`; the switch sits at the bottom of the list with a count ("Show all 79 pages"); search (⌘K) always finds every page |
| The product is still changing, so tips go stale | Section 6.7: one source per fact, no layout-tied guidance, a test that refuses a page without its explanation or a dead link, versioned guides that announce changes |
| The modes or wording turn out wrong | Modes are one table; an unknown stored answer falls back to `guided`; no data depends on the mode |
| Existing customers suddenly see tips | Existing users have no answer; for accounts older than 14 days no answer is read as `free` and the question is not asked |
| `users` table and `/me` route are identity code | Self-only route copied from an existing one; reviewed as security-adjacent before push (see section 13) |
| Admin-only checklist stays admin-only | Unchanged; team members get the page guide and the question, not the company checklist |
| More WhatsApp messages in the first week | At most one tip a day, never on a day a setup question was asked, stopped by "stop tips" |

## 10. Testing strategy

- **Backend unit:** the preferences routes (own row only, bad value refused, another
  company's user untouched); setup-question ordering; old-account default; funnel split.
- **Migration:** upgrade and downgrade on a copy; chain has one head.
- **Dashboard:** `tsc`, `oxlint`, `vite build`; unit tests for the checklist per mode and
  the sidebar filter; a Playwright pass through the four modes with screenshots.
- **WhatsApp:** tests for the question being sent once, answered from either side, and the
  tip rules (one a day, not with a setup question, stops on request).
- **Regression:** full backend suite, WhatsApp assistant suite, existing checklist and
  welcome tests unchanged for a user with no answer and an old account.
- **Live:** after deploy, sign up a test number in each mode and check the control panel.
- **With real people:** two or three contractors who have never seen Mesiri, watched without
  help. This cannot be automated and is the test that matters most.

## 11. Rollback strategy

- Each tracker item is its own commit; `git revert` of any one leaves the rest working.
- The migration only adds two nullable columns. Reverting the code leaves them unused and
  harmless; the downgrade drops them. No data is rewritten at any point.
- No answer stored behaves exactly as today for old accounts, so a rollback needs no cleanup.

## 12. Labour isolation

No change to Labour, Attendance, Payroll or Workforce. The workers import is left out for
this reason and listed as later work needing its own approval.

## 13. Decisions needed from Ilan (recommended in bold)

| # | Decision | Options |
| --- | --- | --- |
| D-GO1 | Build this at all, and when | **After the open WhatsApp bugs, as `Must` for self-serve** · Later · No |
| D-GO2 | The four answers and their wording | **As in 6.1** · Three (merge 2 and 3) · Other wording |
| D-GO3 | When it is asked on WhatsApp | **Morning after signup, as the first daily question** · Right after "Looks good" · Web only |
| D-GO4 | Short sidebar in `guided` mode | **Yes, with "Show everything"** · No, always the full sidebar |
| D-GO5 | Existing users | **Treated as `free`, never asked; can switch tips on in Settings** · Ask everyone once |
| D-GO6 | Where the answer is stored | **Two columns on `users`, beside `reply_language`** · An organization setting keyed by user (no migration, but not where a person's preferences live) |
| D-GO7 | Change to `users` and `/me/preferences` (identity code) | **Approve as additive and self-only** · Review first |
| D-GO8 | Later work (section 14) | **Add as `Later` rows now** · Decide after the first trials use this |

## 14. Later work (not in this plan)

1. Workers and gangs import from Excel (Workforce: needs approval).
2. Clients, open purchase orders and opening balances import.
3. Import from other products' exports (Tally masters first; Mesiri already exports to Tally).
4. A sample site to explore: the demo generator (SA-36) exists, but putting sample records in
   a real company needs a safe way to remove them.
5. Send the Excel on WhatsApp and Mesiri imports it (v3 can already read Excel files, WA-313).
6. Tips and glossary in Malayalam and Hindi.
7. Short screen recordings per page.

## 15. Build order

| # | Item | Size | Depends on |
| --- | --- | --- | --- |
| SS-26 | This plan and the decisions | S | — |
| SS-27 | Store the start mode: migration, `/me/preferences` | S | SS-26 |
| SS-28 | Ask the question on `/welcome` and on a team member's first login; Settings entry | S | SS-27 |
| SS-29 | "What is this page?" on every page; first-visit strip in `guided` | M | SS-27 |
| SS-30 | Checklist per mode | S | SS-28 |
| SS-31 | Short sidebar in `guided`, "Show everything" | S | SS-28, D-GO4 |
| SS-32 | Bring your data page | M | SS-28 |
| SS-33 | Construction words in plain language | M | SS-29 |
| SS-34 | WhatsApp: the question and tips by mode | M | SS-27, D-GO3 |
| SS-35 | Control panel: start mode in the trials funnel and on the company page | S | SS-27 |
| SS-36 | Test with contractors who have never seen Mesiri; fix what they trip on | M | SS-28 to SS-34 |
| SS-37 | Keep guidance true as Mesiri changes: the guard test, guide versions, "Updated" strip, "What's new" | S | SS-29 |

About 3 weeks of focused work. SS-37's guard test is written together with SS-29, so no
page guide exists unguarded. SS-27 to SS-30 (about one week) already give the game-style
start; the rest can follow in any order.

## 16. Success criteria

1. A new owner answers the question in one tap, or skips it, and reaches the first report no
   slower than today.
2. A person who has never used Mesiri completes the six checklist steps without asking the
   Mesiri team anything (checked in SS-36).
3. A builder with a materials Excel and a BOQ Excel has both loaded within an hour of signing up.
4. A `free` user sees no card, no strip and no tip, on the dashboard or WhatsApp.
5. The share of trials that send a first update within 24 hours goes up; the funnel shows it
   by start mode.
6. No change for an existing user who never opens Settings.
7. A page that is added or reshaped later cannot be pushed without its explanation, and its
   users are told once what changed.
