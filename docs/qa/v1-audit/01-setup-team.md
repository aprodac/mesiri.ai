# 01 · Setup & Team — V1 audit

12 problems found in Setup & Team; the biggest is that a Project Manager can create an
Admin over WhatsApp (security).

- **Audited:** 23 Oct 2026 · **Original sheet:** [Setup & Team — WhatsApp test sheet](https://claude.ai/artifact/TTnyiMyXvEvGz6M4G1L4Dc)
- **Not verified:** the live AI's wording. Exact code locations were not recorded in the
  original sheet; the Code lines below name the area to start from.

## Summary

| ID | Problem | Severity | Approval | Phone |
| --- | --- | --- | --- | --- |
| SET-01 | A PM can create an Admin over WhatsApp | Serious | Alan: security | B (PM) |
| SET-02 | A joiner is told "I've asked…" but no admin is reached | Serious | Ops (WA-10) | C (new) |
| SET-03 | Signup takes any text as the company or site name | Serious | None | C (new) |
| SET-04 | A typed "add person" sends no invite | Serious | None | A (Admin) |
| SET-05 | Role words saved wrong (accountant, PM, owner → Site Engineer) | Other | Alan: security (roles) | A |
| SET-06 | A shared contact card always becomes Site Engineer | Other | Alan: security (roles) | A |
| SET-07 | The join code needs exact words | Other | None | A |
| SET-08 | "Add a site" from the setup question goes to the first project | Other | None | A |
| SET-09 | Broken sentence in the join-code message | Other | None | A |
| SET-10 | "Not registered" points to a Mesiri app that doesn't exist | Other | None | C |
| SET-11 | Changing the report time in setup changes every project | Other | None | A |
| SET-12 | A PM can't approve joiners and isn't told why | Other | Decision | B |

## Before you test

Use three WhatsApp numbers, all in the test company **Mesiri Test Builders** only
(these tests create real people and sites).

| Phone | Set up as | Tests |
| --- | --- | --- |
| A | Admin (owner) of the test company | 4, 5, 6, 7, 8, 9, 11 |
| B | Project Manager in the same company | 1, 12 |
| C | A number not registered anywhere on Mesiri | 2, 3, 10 |

- Control panel → **self-serve signup**: on for SET-03, off for SET-10.
- Keep the dashboard **Team** page open to see each new person's role.
- Delete test people and test companies afterwards.

## Problems

### SET-01 · A PM can create an Admin over WhatsApp

- **Severity:** Serious · **Approval:** Alan: security
- **Repro (Phone B, PM):** `add Test Person 919XXXXXXXXX as admin` (a spare number), tap Yes on each step.
- **Expected:** refused; only an Admin may create an Admin.
- **Actual (problem exists if):** Team page shows Test Person as **Admin**. Change or delete them afterwards.
- **Code:** the add-member / create-user plan on WhatsApp: `apps/whatsapp-assistant/src/runtime/agent/change_entry.py` (`_add_member`), `apps/whatsapp-assistant/src/runtime/member_create_plan.py`; role check `_PROJECT_CREATE_ROLES` in `runtime/inbound_journey/_shared.py`.
- **Fix direction:** cap the role a creator may grant at their own level (PM → PM, Site Engineer).

### SET-02 · A joiner is told "I've asked…" but no admin is reached

- **Severity:** Serious · **Approval:** Ops (needs approved Meta templates, WA-10)
- **Repro:** make sure Phone A hasn't messaged Mesiri for 24+ hours. From Phone C: `JOIN <code>`, then your name.
- **Actual:** Phone C is told "I've asked… to approve you", but Phone A never gets Approve / Reject (outside the 24 h window the message needs a template).
- **Fix direction:** until templates are approved, tell the joiner plainly and show the request on the dashboard Team page.

### SET-03 · Signup takes any text as the company or site name

- **Severity:** Serious · **Approval:** None
- **Repro (Phone C, signup on):**
    1. `Hi`, then type `yes` → the same welcome repeats (typing instead of tapping).
    2. Type `start free trial` → the welcome repeats again.
    3. Tap **Start free trial**, then type `what is this?` → it moves on to "Step 2 of 2".
    4. Type `venda` → it says the company is set up (or "something went wrong").
- **Actual:** a company called "what is this?" appears in the control panel. Delete it after.
- **Code:** `apps/whatsapp-assistant/src/runtime/signup_journey.py`.
- **Fix direction:** accept typed equivalents of the buttons; reject questions and very short or no-word answers as names.

### SET-04 · A typed "add person" sends no invite

- **Severity:** Serious · **Approval:** None
- **Repro (Phone A):** `add Ravi Test to Green Villa as supervisor`, give his number, tap Yes.
- **Actual:** no "Forward the next message to them" text with a link arrives.
- **Fix direction:** the typed path should end the same way as the contact-card path, with the invite to forward.

### SET-05 · Role words saved wrong

- **Severity:** Other · **Approval:** Alan: security (roles)
- **Repro (Phone A):** repeat SET-04 with `as accountant`, then `as PM`, then `as owner`.
- **Actual:** Team page shows **Site Engineer**, not Finance / Project Manager / Admin.
- **Fix direction:** map common role words (PM, project manager, accountant, owner, director, supervisor); ask when unsure.

### SET-06 · A shared contact card always becomes Site Engineer

- **Severity:** Other · **Approval:** Alan: security (roles)
- **Repro (Phone A):** share a WhatsApp contact (📎 → Contact), follow the taps.
- **Actual:** no way to pick a role; Team page shows Site Engineer; it takes 3 taps.
- **Code:** `apps/whatsapp-assistant/src/runtime/contact_share_journey.py`.

### SET-07 · The join code needs exact words

- **Severity:** Other · **Approval:** None
- **Repro (Phone A):** send each alone: `join code`, `send join code`, `give me the join code`, `how do I add my team?`
- **Actual:** only the first gets a code; the last never mentions join codes or contact cards.

### SET-08 · "Add a site" goes to the first project

- **Severity:** Other · **Approval:** None
- **Repro (Phone A, 2+ projects):** when asked "Working on another site too?", tap **Add a site** and give a name.
- **Actual:** the site is created under the first project without asking which.
- **Code:** `apps/whatsapp-assistant/src/runtime/setup_questions.py`.

### SET-09 · Broken sentence in the join-code message

- **Severity:** Other · **Approval:** None
- **Repro (Phone A):** `join code`
- **Actual:** the first message says "Whoever sends it is asked **to you to approve**…".

### SET-10 · "Not registered" points to an app that doesn't exist

- **Severity:** Other · **Approval:** None
- **Repro (Phone C, signup off):** `Hi`
- **Actual:** the reply says "in the Mesiri app" and doesn't show your number.

### SET-11 · Changing the report time in setup changes every project

- **Severity:** Other · **Approval:** None
- **Repro (Phone A):** when asked "Your daily report goes out by 9 pm…", pick another time.
- **Actual:** Projects & Sites shows the new time on **every** project.
- **Code:** `apps/whatsapp-assistant/src/runtime/setup_questions.py`.

### SET-12 · A PM can't approve joiners and isn't told why

- **Severity:** Other · **Approval:** Decision (should PMs approve joiners?)
- **Repro (Phone B):** `join code`, forward it to Phone C; from Phone C send `JOIN <code>`.
- **Actual:** only Phone A gets Approve / Reject; Phone B gets nothing and is not told why.

## Test results

| ID | Problem | Phone | Result | What Mesiri replied |
| --- | --- | --- | --- | --- |
| SET-01 | PM can create an Admin | B | Not tested | |
| SET-02 | Joiner never hears back | C | Not tested | |
| SET-03 | Signup takes any text | C | Fixed (unit test) | Names checked; typed yes/start work; Company · Site card with Looks good / Edit before creating. Live check pending after deploy |
| SET-04 | Typed add sends no invite | A | Fixed (unit test) | Typed add ends with the ADDED + invite link, as a shared contact does. Live check pending after deploy |
| SET-05 | Role words saved wrong | A | Not tested | |
| SET-06 | Contact card always Site Engineer | A | Not tested | |
| SET-07 | Join code needs exact words | A | Fixed (unit test) | `get_join_code` agent tool answers any phrasing (admin / PM only). Live check pending after deploy |
| SET-08 | Add a site goes to first project | A | Fixed (unit test) | Asks which project (buttons) when there is more than one. Live check pending after deploy |
| SET-09 | Broken join-code sentence | A | Fixed (unit test) | Now "asked for your approval". Live check pending after deploy |
| SET-10 | "Not registered" points to an app | C | Fixed (unit test) | Shows the number, the join code and the web signup link. Live check pending after deploy |
| SET-11 | Report time changes every project | A | Fixed (unit test) | Asks "all projects or one?" when there is more than one. Live check pending after deploy |
| SET-12 | PM can't approve joiners | B | Not tested | |
