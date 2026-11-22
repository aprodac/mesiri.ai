# Mobile app, part 2: a site engineer's whole day, well arranged

> Asked 22 Nov 2026 (in session): *"so now every important pages and all for site engineer is there in this? but i
> think ui still needs a more improvement overall. our main thing should be ui and the ux, feature rich ux, layouting
> and arrangement all well thought and very easy to use … it lacks a third colour or life to feel balanced."*
> Follows [mobile-site-engineer-plan.md](mobile-site-engineer-plan.md) (part 1, MOB-01 … MOB-13).
> Screens: the "Mesiri Site Engineer App" design canvas, page **V2**.
>
> Status: **plan, waiting for two choices** (§6): the third colour, and the build order.

## 1. Is everything a site engineer needs there? Not yet

What the app does today (part 1): the day as 7 rows, voice and typing to Mesiri, three forms (delivery, use,
problem), one-field voice, stock, requests, offline outbox, sign-in, English and Malayalam.

What a site engineer does in a day, against the app. The dashboard already has every one of these (its API is the
app's API), so most gaps are screens, not backend.

| The day's job | Dashboard has | App today | Gap |
|---|---|---|---|
| Who came (by trade, named workers) | Attendance, Muster roll, Workers, Teams | Voice only | **Attendance screen**: counts per trade, "same as yesterday" in one tap, named workers |
| Work done, on the BOQ line / schedule | Today, BOQ, Schedule | Voice only | **Work screen**: pick the activity due this week, quantity, % done |
| **Photos of the work** | Site log, gallery (from WhatsApp) | **Nothing** | **Camera**: progress photos and bills; needs an image door on the assistant (as WhatsApp photos) |
| Deliveries due today, receive against the order | Pending deliveries, POs | Form only, no order | **Coming**: today's deliveries, receive in one tap (order line filled) |
| Problems: open ones, acknowledge, resolve | Issues | Create only | **Problems list** with resolve / still open |
| Machines: hours, diesel, idle | Equipment daily log | Nothing | **Machines** row and form |
| What is planned this week, tomorrow's plan | Schedule, Live plans | Nothing | **Plan**: this week's activities for the site; tomorrow's plan in the evening |
| My tasks | Tasks | Nothing | **Tasks** (given to me, due, done) |
| Drawings and documents | Documents, Drawing check | Nothing | **Drawings**: open a sheet on site, offline once opened |
| Site expenses, petty cash, bill photo | Expenses, Money | Nothing | **Expense** with photo (their cash box) |
| The evening report: see it, send it | Daily reports | "Send now" only | **Close the day**: what is missing, preview, send |
| Past days | Site log, reports | Nothing | **History**: any day, read only |
| What needs me | Home "waiting" | Nothing | **Needs you**: answers, deliveries due, tasks due, open problems |

## 2. The arrangement (information architecture)

Five places, each answering one question. The mic stays in the middle.

```
  Today          Work          [ MIC ]          Stock          More
  "what now"     "what to do"   "tell Mesiri"    "what we have"  "everything else"
```

| Tab | Holds | Top of the screen |
|---|---|---|
| **Today** | Needs you · the day's parts (7 rows + photos + machines) · Close the day | A greeting with the weather and the day's tape |
| **Work** | This week's plan (schedule activities for the site) · my tasks · problems · drawings | What is due today |
| **Mic** | Speak (as now) | |
| **Stock** | Stock · coming today · requests · count | Running low, coming today |
| **More** | People (attendance, workers) · machines · expenses · history · site · language · sign out | |

Rules for the arrangement:

1. **One question per screen, the answer at the top.** No screen opens on a menu.
2. **Thumb zone.** Actions sit in the bottom half (the "Add" sheet, Save bars); reading sits in the top half.
3. **Two taps to anything daily**, from Today.
4. **Every list has its add** at the bottom-right of its section, the same way everywhere.
5. **A state for everything**: loading (skeleton), empty (says what to do, with the button), error (says why, with
   retry), offline (kept copy, marked), saved (a toast with Undo for 5 s).

## 3. The UX ideas (least work for the person on site)

| # | Idea | What it saves |
|---|---|---|
| U1 | **Quick add sheet**: tap and hold the mic, or the "+" on Today: Photo · Attendance · Delivery · Used · Problem · Work · Expense · Machine. Each opens its form with the site and date already right | Hunting through tabs |
| U2 | **Same as yesterday**: attendance, machines and the plan open on yesterday's figures; one tap to keep, tap a number to change | Typing the same crew every day |
| U3 | **Camera first**: a photo is taken, then Mesiri reads it (a bill becomes an expense or a delivery; a site photo goes on the day, on the activity it shows) and shows its card to Save | Filling a bill by hand |
| U4 | **Close the day** (from 5 pm, or "Send now"): walks through what is missing, one screen each, then the report preview and Send | A report that goes out half empty |
| U5 | **Needs you** strip on Today: an answered request, a delivery due today, a task due, a problem left open; each one tap to act | Missing the office's answer |
| U6 | **Undo after save** (5 s toast), and every saved line on its row can be changed or taken back | Fear of tapping Save |
| U7 | **Steppers for counts** (− 6 +) with big targets for attendance and quantities; number keypad only when asked | Fiddly keyboards with gloves |
| U8 | **Smart order**: the rows not told yet float up after 3 pm; told ones fold | Scrolling past what is done |
| U9 | **Sunlight mode** (higher contrast, bigger type) and **dusk mode** (dark), auto by time or set | Glare at noon, glare at night |
| U10 | **Haptic tick** on save, on recording start/stop | Looking at the screen to know it worked |
| U11 | **Suggested use** in Close the day: from today's work and its BOQ line, "plastering 42 sqm uses about 9 bags cement"; the person keeps or changes it. Only where the BOQ line carries material quantities (the material plan / materials-vs-BOQ data); otherwise the step is plain | Working out consumption by hand |

## 4. Giving it life: the third colour and more

Today the app is paper, ink and one yellow, with green and brick only for status. It reads calm but flat: nothing
says "this is the plan", "this is Mesiri", "this is information", so everything looks equally important.

**Proposal: Blueprint blue** (`#2f5aa8` ink, `#e6edf8` wash) as the third colour, with one rule each:

| Colour | Means | Used for |
|---|---|---|
| Ink | Structure, actions | text, main buttons |
| **Safety yellow** | Do this now / voice | the mic, progress, "from your voice", today's one main action |
| **Blueprint blue** | Plan and information, and Mesiri itself | Mesiri's replies, the plan and schedule, drawings, links, selected filters, info notes |
| Green / brick | Status only | done / attention |

Why blue: yellow and blue are the colours of site signage (mandatory signs are blue, warnings yellow), drawings are
blue, it sits opposite yellow so the two balance, and it is far from both status colours, so nothing is confused.
Other options drawn on the canvas for comparison: **sage** (calm, but too close to "done" green) and **terracotta**
(warm, brick-like, but too close to "attention").

More life, without noise:

- **Real photos** on Today (the day's photos as a strip) and on each activity: the site's own pictures are the
  best colour the app can have.
- **Weather and time of day** in the greeting ("Good evening · 29 °C, light rain").
- **Small charts where a number moves**: crew size over 7 days (a sparkline under Attendance), stock as gauges (have).
- **Line icons per part of the day** (people, a trowel, a truck, a drum, a camera), one weight, in ink.
- **Tinted panels** for grouping: Needs you on a blue wash, Close the day on a yellow wash, so sections read at a glance.

## 5. Build order (proposed, each a tracker item)

| ID | What | Backend? |
|---|---|---|
| MOB-14 | **The third colour and the parts**: blue tokens and rules, tinted panels, line icons per part, toast with Undo, skeletons, empty and error states everywhere | No |
| MOB-15 | **Today, rearranged**: greeting with weather, Needs you, the day's parts with photos and machines, Close the day entry | Reads only |
| MOB-16 | **Quick add sheet** (U1) and the **Attendance screen** with steppers and Same as yesterday (U2, U7) | No (existing routes) |
| MOB-17 | **Camera**: photos and bills through the assistant (an image door like the voice one), photo strip on Today | **Yes**: `POST /assistant/messages/photo` (additive) |
| MOB-18 | **Work tab**: this week's plan, Work done form on the activity, my tasks, problems list with resolve | Reads + existing writes |
| MOB-19 | **Close the day** (U4): what is missing, preview of the report, send | Reads (report preview) |
| MOB-20 | **Stock tab, complete**: coming today, receive against the order, stock count | Existing routes |
| MOB-21 | **More**: machines log, expenses with photo, history (any day), drawings viewer | Existing routes |
| MOB-22 | **Sunlight and dusk modes**, haptics | No |

MOB-12 (Idempotency-Key on the other routes) runs alongside: MOB-20 and MOB-21 need it for payments and logs.

## 6. Choices needed

1. **The third colour**: blueprint blue (recommended), sage or terracotta. All three are on the canvas.
2. **Build order**: as §5 (look first, then Today and capture), or capture first (camera and attendance before
   the look).
