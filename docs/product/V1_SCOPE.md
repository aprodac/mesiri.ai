# Mesiri V1 scope

> **Status:** proposal for approval by Alan and Ilan · Prepared for Adarsh VP · 21 October 2026
> · Confidential, internal.
> Source: `Mesiri_V1_Scope.pdf` (repo root), converted to Markdown 24 Oct 2026. Content unchanged.
> Once signed off, this list is recorded in [V1_TRACKER.md](../plans/V1_TRACKER.md) and the
> conflicting scope in `docs/architecture/Core-architecture.md` is fixed.

The proposed feature list for the V1 launch: construction, Daily Progress Report (DPR).

**The V1 promise.** Your site team sends updates on WhatsApp during the day. In the evening
Mesiri asks for anything missing, the engineer confirms, and by 9 PM a branded PDF Daily
Progress Report reaches the owner, the PM and the client, without anyone typing a report.

## How the scope was decided

1. **Does a standard Indian construction DPR need it?** A DPR has manpower, work done,
   materials, equipment, issues, photos and tomorrow's plan. Anything that is part of that is in.
2. **Does it add work for the site team?** (the project's main product rule). If it does, it is out.
3. **Does it bring support load or risk V1 does not need?** If yes, it waits for a later version.

## Modules

| Module | In V1? | Why |
| --- | --- | --- |
| DPR core | Yes | It is the product. |
| Labour: headcount | Yes | Manpower is the first section of every DPR; without it owners will not trust the report. |
| Materials | Yes | Materials received and used are a standard DPR section; stock is what owners ask about most. |
| Equipment | Yes, inside the DPR only | Captured on WhatsApp and shown in the PDF; no separate dashboard page. |
| Finance | No (V1.1 paid add-on) | Accounting, not reporting: money mistakes destroy trust, customers compare it with Tally, and it doubles support. Already built, so it can be switched on per company later. |
| Automations | No | The DPR already sends itself on time; a second scheduling feature confuses the story. |

## Depth of each module

### Labour: headcount by contractor and trade only

| Keep in V1 | Hide for V1 |
| --- | --- |
| WhatsApp: "Ravi contractor 12 mason, 5 helper" | Workers roster (individual names) |
| Attendance page (counts per site per day) | Asking for each worker's name after attendance (worker promotion) |
| Labour section in the DPR | Labour Overview, Analytics, Reports, Settings, "WhatsApp Automations" pages |
| "How many workers yesterday?" on WhatsApp | |

**Why counts and not names:** DPRs report manpower as counts by agency and trade. Tracking
each named worker is wages and payroll territory, with more typing for supervisors and salary
expectations V1 does not meet. That belongs in V2.

### Materials: in, used, transferred, stock

| Keep in V1 | Hide for V1 |
| --- | --- |
| WhatsApp: received, used, transfer between sites, stock questions | The 4 empty placeholder pages (Inventory, Purchases, Suppliers, Categories) |
| Bill photo attached to a material receipt | Purchase or invoice accounting |
| Materials page: stock, opening stock, adjustments | |
| Materials section in the DPR | |

## The final V1 product

### WhatsApp (site team and owners)

- Report work done, manpower, materials (in / used / transfer), equipment, issues, photos,
  tomorrow's plan, weather and hours lost, by text, voice or forwarded messages, in
  Malayalam, Manglish or English.
- Undo and corrections; questions such as "today's DPR?", "workers yesterday?", "cement stock?".
- Evening gap check, then the engineer confirms, then the branded PDF DPR is sent automatically.
- Setup on WhatsApp: signup, add a site, add people by sharing a contact, join codes.

### Dashboard: the whole menu (8 items, down from about 40)

| Menu item | Who sees it | What it is for |
| --- | --- | --- |
| Today | Everyone | Each site's day and what is missing |
| Daily Reports | Everyone | Site and project DPRs, history, versions |
| Issues | Everyone | Open and closed site issues |
| Attendance | Everyone | Labour headcount by contractor and trade |
| Materials | Everyone | Stock, received / used, opening stock |
| Projects & Sites | Admin | Sites, DPR time, recipients, site label |
| Team | Admin | People, roles, sites |
| Company & Branding | Admin | Letterhead, logo, GSTIN, signatory |

Control panel (Mesiri team): unchanged.

## Not in V1

| Item | When |
| --- | --- |
| Finance (expenses, petty cash, accounts, vendors) | V1.1, paid add-on, per company |
| Automations (user-set scheduled messages) | Later |
| Named workers, wages, payroll | V2 |
| Mobile app | Parked |
| Online payments for subscriptions | After launch (V1 uses invoice + UPI / bank transfer) |
| Signature or stamp image on DPRs | Decided 13 Oct: not in V1 |
| Anomaly alerts (e.g. sudden manpower jump) | Later |
| People who belong to several companies | Dropped |
| Other industries (bakery, clinic, …) | V2 (tools + templates) |

## Changes needed in the code

Small changes; nothing is deleted. Every hidden feature stays in the code and can be switched
back on per company.

| Change | Type | Approval |
| --- | --- | --- |
| Hide the "More" section: old Operations pages, Gallery, Timeline, Analytics, WhatsApp Inbox | Dashboard menu | None |
| Hide the 4 empty Materials pages and the extra Labour pages | Dashboard menu | None |
| Turn off worker promotion (asking for names) and hide Workers roster | WhatsApp, Labour module | Alan (protected module) |
| Finance and Automations stay off by default | Already the case | None |
| Confirm equipment appears in the DPR PDF | Check, fix if missing | None |
| Polite reply to expense messages: "Expense tracking is coming soon" | WhatsApp text | None |
| Record this list as the official V1 scope in V1_TRACKER.md; fix the conflicting scope in Core-architecture.md | Documentation | After sign-off |

> **Audit note (24 Oct 2026):** "Confirm equipment appears in the DPR PDF": it does not;
> there is no equipment capture or table at all. See
> [ISS-01](../qa/v1-audit/06-issues-conditions.md#iss-01--equipment-cannot-be-recorded).
> The menu changes are done (WEB-20) except hiding Workers Roster, which waits for Alan: see [DSH-01](../qa/v1-audit/09-dashboard.md#dsh-01--the-menu-isnt-the-v1-menu).

## Decision

Once approved, this list is the V1 scope: anything not on it waits for V1.1 or V2.

## Sign-off

| Name | Role | Decision | Date |
| --- | --- | --- | --- |
| Alan | Product / approvals | [ ] Approved [ ] Changes | |
| Ilan | Operations | [ ] Approved [ ] Changes | |
