# Requests from many companies: sort first, then build (TM-34)

> Asked 2 Nov 2026: *"One contractor's wish shouldn't change everyone's product. Lets ideate on this and set this up
> properly, cause this itself is its own thing."* Status: **design, for Alan / Ilan's decisions** (the open questions
> at the end). Nothing here is built yet; the phases say what is.

## The problem

Today a request that reaches the team bot (`tell_the_team`, a Cancel reason, "Still wrong", a watch flag) becomes a plan,
and the plan is built **for everyone**. With two test companies that is right. With fifty paying contractors it breaks
three ways:

1. **One company's habit becomes everyone's behaviour.** Contractor A wants the DPR at 6 pm with labour first;
   contractor B relies on 8 pm and materials first. Building A's wish breaks B.
2. **The product grows sideways.** Every one-off ("add my brother-in-law's supplier list to the stock answer") becomes
   code nobody else uses, which slows every later fix.
3. **Many requests need no build at all.** "Can Mesiri send the PDF?" is often already possible: the person needs to
   be shown how, not a new feature.

## The outcomes

Every request is sorted into exactly one of these before anything is built:

| Outcome | When | What happens | Who is told what |
|---|---|---|---|
| **Already possible** | It works today; they didn't know how | No build. The answer, an example message and a `web_link` | The person, at once: "You can already: send *…*" |
| **Product** | Good for every construction company; adds without changing what others rely on, or fixes something wrong for everyone | Built for everyone (as today) | The person: "it works now"; the group: the "what's fixed" card |
| **Company preference** | Their way of working; another company could reasonably want the opposite | Built as a **per-company switch** with the old behaviour as the default; switched on for the company that asked | The person: "switched on for *your company*" |
| **Needs a decision** | Changes what every company relies on, touches a held area (Attendance, Payroll, Workforce, money, data), costs a lot, or conflicts with another company's preference | Held for an owner, with the reason (as autobuild holds today) | The person: "passed to the team; we'll tell you"; the owner: the plan with the reason |
| **Not now** | A one-off, out of scope (not construction site work), or not worth its complexity | No build. Logged as demand; it comes back when more companies ask | The person, politely: what Mesiri does instead, and that it's noted |

"Not now" is never a dead end: the request stays in the log with the company, and **demand is counted across
companies** (below), so a "not now" that three companies ask for becomes a product request by itself.

## How a request is sorted

The production watch's planning turn already reads the request, the conversation and the code. It gains a sorting
step **before** `propose_plan`, and the code checks the result, because the model reads and the code decides
(FIX_APPROACH):

1. **Is it already possible?** Look for an existing tool, route, dashboard page or SOP rule that does it. If yes:
   answer, no plan.
2. **Who else asked?** The request log is searched for the same need across companies (the bot already merges
   duplicates within a running plan; this widens it to the whole log). The count goes on the plan: *asked by 3
   companies (Acme, Paraclette, …)*.
3. **Does it change what others rely on?** An *addition* (a new answer, a new tool, a new field) changes nothing for
   others. A *behaviour change* (a default, a wording others see daily, an order, a time, a rule) does. The plan must
   say which, and list the existing behaviours it changes.
4. **Sort**, by a written rubric in the watch prompt:
   - additions and plain bugs → **Product**;
   - behaviour changes asked by one company → **Company preference**;
   - behaviour changes asked by several companies with none relying on the old way → **Product**, but **Needs a
     decision** when it touches a held area or a company has the opposite preference switched on;
   - out of scope, a one-off, or complexity that outweighs the value → **Not now**.
5. **The code checks the label** (autobuild.js, like `holdReason` today):
   - **Company preference** must add an entry to the preference registry (below) with the old behaviour as its
     default; a plan that edits a default without one is held.
   - **Product** that says "behaviour change" with demand from a single company is held.
   - **Not now** and **Already possible** never build.
   - Every label and its reason is stored on the request (`category`, `reason`, `companies`).

## Per-company switches: "company preferences"

One mechanism for every per-company difference, so preferences don't become scattered `if company == …` branches.

**Registry, one file** (`backend/src/mesiri/domains/organizations/preferences.py`): each preference declared once.

```
DPR_SEND_TIME   = Preference(key="dpr_send_time", type=time, default="19:00",
                    who_may_change="company_admin", label="When the daily report is sent",
                    since="#a83836 (Acme, 2 Nov 2026)")
STOCK_ANSWER_ORDER = Preference(key="stock_answer_order", type=enum("by_material", "by_site"),
                    default="by_material", who_may_change="company_admin", ...)
```

- **Default = today's behaviour**, so adding a preference changes nothing for any company until it is switched on.
- **Stored in `organization_settings`** (the existing table, one row per company per key): no new table, no migration.
  The registry is a thin layer over the settings catalogue that already validates keys and types (`settings.py`).
- **Read in one place.** Backend code reads a preference through one call, `preference(org_id, KEY)`, which returns
  the default when unset (one query per request, cached like the settings query today). The **business rule lives in
  the API** (FIX_APPROACH: backend first), so the dashboard and v3 both get it.
- **v3 sees the ones that matter to its words.** A preference that changes how Mesiri talks (order, detail, language
  style) is listed in v3's facts only when it differs from the default (*"This company prefers: stock answers by
  site"*), with an SOP rule to follow company preferences. Everything else is enforced in code.
- **Who switches it.** `who_may_change` per preference: `company_admin` (dashboard *Company → Preferences*, generated
  from the registry; and on WhatsApp through the same settings API for admins) or `mesiri_team` (control panel only).
- **Tested both ways.** Every preference ships with a test of its default (nothing changed for others) and of its
  switched-on behaviour; a test fails if a registry entry has no such pair.
- **Kept small.** Each preference records which companies use it. The weekly digest lists preferences no company has
  switched on for 60 days; those are removed. A preference switched on by most companies becomes the default (a
  product decision, held for an owner).

## What the person hears

The reply comes from Mesiri on WhatsApp, in their language, by outcome (new wording lines, five languages):

- *Already possible:* "You can already do this: send *'today's labour PDF'*." + an example or a link.
- *Product / preference:* as today: the reference, the preview (UX and features), "it works now".
- *Preference:* "Switched on for your company. Others keep the old way."
- *Needs a decision:* "Passed to the team; this changes things for every company, so the owners decide. I'll tell you."
- *Not now:* "Mesiri doesn't do this; here's what it does instead: … I've noted it; if more companies ask, we'll
  build it."

## What changes where

| Part | Change |
|---|---|
| Watch prompt (`prod_watch.js`) | The sorting step and rubric; "already possible" and "not now" answers |
| `propose_plan` (`tools.js`) | Required `category`, `changes_existing` (list), `companies` (from the log) |
| `autobuild.js` | Code checks per category (above); preference plans must touch the registry |
| Request log (listener store) | `category`, `reason`, `companies`; demand search across companies |
| Requests page | Filter and counts by category; "asked by N companies" |
| `preferences.py` (new) + settings catalogue | The registry, `preference()` reader, validation |
| Dashboard | *Company → Preferences*, generated from the registry |
| v3 (`whatsapp.py` facts, `SOP.md`) | Non-default preferences listed; one SOP rule |
| Mesiri replies | "Already possible" / "not now" / "switched on for your company" lines |
| Digest | Requests by category, top unbuilt demand, unused preferences |

## Phases

1. **Preferences, the mechanism** (no bot changes): registry, reader, settings validation, dashboard page, v3 facts,
   the both-ways test rule. One real preference to prove it (the first that a company asks for).
2. **Sorting in the bot**: the rubric, `category` on plans and requests, demand counting, "already possible" and "not
   now" replies.
3. **Code checks** in autobuild per category; Requests page and digest by category.
4. **Pruning and promotion**: unused preferences, most-used preferences proposed as defaults.

Each phase ships on its own; phase 1 is useful before the bot sorts anything (the team can add a preference by hand).

## Open decisions (Alan / Ilan)

1. **Self-serve switches?** May a company admin change preferences themselves (dashboard and WhatsApp), or only the
   Mesiri team on request? *Suggested: company admins, for preferences marked `company_admin`.*
2. **Behaviour changes for everyone:** always held for an owner, or autobuilt when N companies asked and none has the
   opposite preference? *Suggested: autobuild at 3 companies; held otherwise.*
3. **"Not now" wording:** may Mesiri say "if more companies ask, we'll build it"? It is a soft promise.
4. **Promotion:** a preference switched on by most companies becomes the default after an owner's ok, or by itself?
   *Suggested: owner's ok (it changes things for the rest).*
5. **Pricing:** may some preferences belong to a paid plan later? (Affects whether `who_may_change` needs a plan check.)
