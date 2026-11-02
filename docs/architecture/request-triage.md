# Requests from many companies: build it, switch it on for the company that asked (TM-34)

> Asked 2 Nov 2026: *"One contractor's wish shouldn't change everyone's product ... set this up properly, cause this
> itself is its own thing."* Revised the same day around the team's idea: *"everything gets built, but when a company
> asks, it's built for that company; from the control panel we can see it and turn it on for others if they need it
> too."* Status: **design**. Phase 1 changes a shared component (the module gate), so it waits for an owner's ok.

## The principle

**Say yes, build it, switch it on only for the company that asked.**

- The contractor who asked gets it, fast. Nobody hears "no" because of other companies.
- Every other company keeps exactly what it had, because a new feature is **off** for them.
- The team sees every feature in the control panel: who asked, who has it on, whether it is used. Turning it on for
  another company (or for all) is one tap and no build.
- Features that prove themselves **graduate**: on for everyone, switch removed from the code. Features nobody uses
  are **retired**. This is what stops "everything gets built" turning into a pile of switches.

It reuses what exists. Mesiri already switches **modules** per company (`enabled_modules`, `require_module` on every
router, switches in the control panel, a polite refusal on WhatsApp). A feature is the same thing one size smaller.

## What gets a switch, what doesn't

The bot sorts each request into one of four kinds. None of them waits for an owner.

| Kind | Example | What happens | Switch? |
|---|---|---|---|
| **Fix** | the DPR total is wrong; Mesiri misread "50 bags" | Fixed for everyone (wrong is wrong everywhere) | No |
| **Already possible** | "can Mesiri send the labour PDF?" (it can) | No build. Mesiri shows how, with an example and a link | No |
| **New feature** | DPR at 6 pm; stock answers by site; a weekly cement summary | Built behind a feature switch; **on for the company that asked**, off for the rest | **Yes** |
| **Not Mesiri** | not construction site work ("book my train ticket") | Declined politely, with what Mesiri does do; logged | No |

The test between *fix* and *new feature* is one question: **could another company reasonably want it the old way?**
If yes, it's a feature with a switch. When unsure, it's a feature: a switch costs a little code; breaking another
company costs a customer.

"Not Mesiri" is the only no, and it is rare. One-offs that *are* construction work are built as features: they cost
little because they are off for everyone else, and retirement removes them if they go unused.

## A feature switch

**Registry, one file**: `backend/src/mesiri/domains/organizations/features.py`. Each feature is declared once:

```python
DPR_EVENING_TIME = Feature(
    key="dpr_send_time",
    label="Daily report at a chosen time",
    module="dpr",                       # it lives inside a module; off when the module is off
    kind="choice", options=("19:00", "18:00", "20:00"), default="19:00",   # or kind="on_off"
    asked_by="#a83836 Acme Builders, 2 Nov 2026",
)
```

- **Off / old way by default.** Adding a feature changes nothing for any company until it is switched on.
- **On / off, or a choice.** When two companies want opposite things (6 pm vs 8 pm) it is one feature with options,
  not two features.
- **Stored in `organization_settings`** next to `enabled_modules`: one `features` row per company
  (`{"dpr_send_time": "18:00", "stock_by_site": true}`). No new table, no migration.
- **Read in one place.** `feature(org_id, KEY)` returns the company's value or the default; the read is cached per
  request like the module read. **The rule lives in the API** (FIX_APPROACH: backend first), so the dashboard and
  WhatsApp both get it.
- **A whole new route** (a new report, a new answer) is gated like a module: `require_feature("weekly_cement")`
  next to `require_module(...)`. A company without it gets the same polite "not switched on" as a module that's off.

### How v3 sees features

v3 is "an API route plus an SOP rule", so a feature needs both parts to switch:

- **Tools.** A route gated by `require_feature` is left out of the company's tool list when the feature is off, so
  the model never offers it (today a switched-off module's routes stay in the list and answer 403; this fixes that
  for modules too).
- **SOP rules.** A rule that belongs to a feature is marked in `SOP.md` with `<!-- feature: key -->` and is included
  only for companies that have it on.
- **Facts.** Features that change how Mesiri *talks* (order, detail) are listed in the facts only when not default:
  *"This company has on: stock answers by site."*

### Tested both ways

Every feature ships with two tests: switched off, behaviour is exactly as before (others unharmed); switched on, it
does what was asked. A registry test fails if a feature has no such pair, and autobuild refuses a feature plan without
it.

## The control panel: Features

One new page, plus a tab on each company.

**Features page** (every feature, one row each):

| Feature | Asked by | On for | Used (30 days) | Age | Actions |
|---|---|---|---|---|---|
| Daily report at a chosen time | Acme, 2 Nov | Acme, Paraclette | 41 | 3 w | *Turn on for… · On for all · Graduate · Retire* |

- **Turn on for…**: pick companies. One tap, no build, written to the audit log.
- **On for all**: every company, including new signups (the default flips). Still a switch, still reversible.
- **Graduate**: it has been on for all for a while with no complaints; the bot removes the switch from the code (the
  old way and its test go), leaving one path. This is the step that keeps the code clean.
- **Retire**: unused; the bot removes the feature and its code.

**Company tab**: that company's switches, with who turned each on and when.

The page is also a **sales tool**: walking into a new contractor, the list of features other contractors asked for
is the demo. A feature can be switched on for the demo company in one tap.

## Offering it to others

When a feature has been on for its first company for a week, the weekly digest lists it: *"Daily report at a chosen
time: Acme uses it daily. Offer to others?"* The team can then:

- switch it on for chosen companies, or
- let Mesiri **offer it**: each company admin gets a WhatsApp message, *"New in Mesiri: send the daily report at a time
  you choose. Want it? [Yes] [No thanks]"*. Yes switches it on (an ordinary feature switch, by the admin). The message
  never names the company that asked.

## From request to switch (the bot)

The production watch already plans from the request, the conversation and the code. It changes in small ways:

1. **Sort** into the four kinds above, with the reason. "Already possible" and "Not Mesiri" are answered at once, no
   plan.
2. **Same feature already exists?** Search the registry and the request log across companies. If another company asked
   for the same thing and it was built, **no build: switch it on** for this company (an ordinary switch, logged) and
   tell the person. This is the fastest reply there is, and it gets faster as the product grows.
3. **New feature plan** names the feature key, its default, the company to switch on, and its two tests.
4. **Code checks** (autobuild.js, like `holdReason` today):
   - a *new feature* plan must add a registry entry and both tests; a plan that changes existing behaviour without a
     switch is held;
   - a *fix* that changes something another company relies on is held (it should have been a feature);
   - every kind and reason is stored on the request (`kind`, `feature`, `company`).
5. **After deploy** the bot switches the feature on for the company that asked (through the same settings API, logged
   as "the bot, for request #ref") and sends the usual "is this how you want it?" preview and "it works now".

## What the person hears

New wording lines, five languages:

- *New feature:* "Done: switched on for *your company*." (+ preview, "it works now")
- *Already existed for others:* "Switched on for you; it's ready now."
- *Already possible:* "You can already do this: send *'today's labour PDF'*."
- *Not Mesiri:* "Mesiri is for site work, so it can't do this. It can: …"

## What changes where

| Part | Change |
|---|---|
| `features.py` (new) | The registry, `feature()` reader, validation of stored values |
| `settings.py` | A `features` setting (validated against the registry), platform-admin only to start |
| `domains/shared/modules.py` | `require_feature` beside `require_module` (**shared component: owner's ok**) |
| `agent_api/tools.py`, `whatsapp.py`, `SOP.md` | Per-company tool list (modules and features); feature-tagged SOP rules; non-default features in facts |
| Control panel | Features page; company tab; turn on / on for all / graduate / retire |
| `prod_watch.js`, `tools.js`, `autobuild.js` | The four kinds; reuse-before-build; plan fields; code checks; switch on after deploy |
| Request log, Requests page | `kind`, `feature`; counts by kind |
| Digest | New features to offer; unused features to retire; on-for-all features to graduate |
| Wording | The lines above |

## Phases

1. **The switch** (no bot change): registry, `feature()`, `require_feature`, the `features` setting, per-company v3
   tool list, feature-tagged SOP rules, the both-ways test rule, the control panel page. Proven with the first real
   feature a company asks for. Useful at once: the team can build a feature for one company by hand.
2. **The bot builds features**: the four kinds, reuse-before-build, plan fields, code checks, switch on after deploy,
   the replies.
3. **Offering**: digest section and the WhatsApp "want it?" offer to company admins.
4. **Keeping it clean**: graduate and retire, driven from the control panel and the digest.

## Decisions taken

- Everything that is construction work gets built; a company's request is built **for that company** and switched
  on for others from the control panel (the team, 2 Nov 2026).
- **No owner's ok to switch a feature on**, attendance, payroll, workforce and money included: the switch only
  affects the company that asked, its off path is tested, and it is one tap to turn off (the team, 2 Nov 2026).
- Requests that are not construction work are declined politely (the team, 2 Nov 2026).

## Still open (Alan / Ilan), none blocks phase 1

1. **May company admins switch features themselves** (from an offer, or a dashboard page), or only the Mesiri team?
   *Suggested: only the team at first; the WhatsApp offer (phase 3) lets admins say yes to what the team offers.*
2. **Graduate when?** *Suggested: on for all for 4 weeks with no "Still wrong" or Cancel on it; the team taps
   Graduate, the bot does the cleanup.*
3. **Paid features later?** A feature can name a plan; the switch then also checks the plan. Not needed now.
