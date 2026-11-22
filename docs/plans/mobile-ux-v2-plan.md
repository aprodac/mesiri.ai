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

## 4b. Revised 22 Nov: blue alone is not enough life

Feedback on §4: *"it lacks life, it's the web dashboard one."* Paper, ink and one yellow plus a blue is still the
dashboard's look. Looked at what works now (sources at the end) and drew three directions on the canvas, page **V3**:

| | Direction | Look | From |
|---|---|---|---|
| **A** | **Site board** (recommended) | Warm paper; a dark hero card for the day's report with a yellow ring; a **bento grid** of big rounded tiles, each part of the day in its own colour family (people yellow, work blue, materials peach, problems coral), big figures, the day's photo as a tall tile; a floating dark pill nav with the yellow mic | Bento grids with sizes that mean something; Material 3 Expressive (brighter colour, rounder shapes, springy motion) |
| **B** | **Night shift** | Dark-first: layered charcoal surfaces with hairline borders, yellow for "do now", teal for answers and information, coral for urgent; high-contrast tags ("DUE TODAY", "OPEN 2 DAYS") readable in 3 seconds | Field-app redesigns (dark mode for site use, vivid accents, urgency tags); dark-first apps (Linear, Arc) |
| **C** | **Blueprint** | Editorial: a large serif headline ("Saturday, the 29th"), the report on a blueprint-blue panel with a drawing grid, ledger-style figures, highlighter marks on what matters, hard edges | "Structural UI" (bold serif headlines, ledger numbers, hard edges) |

Recommendation: **A by day, B as its dusk/night mode** (the same tiles and colour families, on dark). A has the most
life and is the easiest to scan (each part is a colour and a place); its colours sit under dark ink so they read in
sun. C is the most distinctive but reads as a report, not a tool.

Sources: [Projektfabrik app redesign](https://contra.com/p/EqoOPelo-projektfabrik-app-redesign),
[Muzli: mobile UI patterns 2026](https://muz.li/blog/whats-changing-in-mobile-app-design-ui-patterns-that-matter-in-2026/),
[Wavespace: UI design trends](https://www.wavespace.agency/blog/ui-design-trends),
[Apple Design Awards 2025](https://developer.apple.com/design/awards/2025/).

## 4c. Chosen 22 Nov: the blueprint colours, a new template (canvas page V4)

Asked: *"go with the blueprint colours with another type of font and bottom bar and another template itself; I like
the colour combination and the blueprint vibe."* Drawn as a template (Today, Speak, Attendance):

- **Colours (kept from C):** paper `#f3efe6`, drawing ink `#15233f`, blueprint `#1e3a6e` with a 16 px drawing grid,
  highlighter yellow `#ffd23f`, pale blueprint `#dfe6f3` / `#b9c8e6`, brick for problems `#c4472f` / `#f6c9bd`.
- **Template:** a blueprint **title block** at the top of each main screen (project, site, date, weather in a ruled
  grid, like a drawing's title block), the day's progress as a **scale bar** (0–9, filled in yellow), "Needs you" as
  **detail bubbles** (circled references: PO 05, RQ 12), the day as a **schedule table** (NO · PART · QTY · mark)
  with highlighter on what matters; 
- **Type (choice in Tweaks):** Archivo Narrow (drawing title blocks, default), Space Grotesk, or Barlow Condensed for
  headings, with JetBrains Mono for references. Instrument Serif dropped.
- **Speak:** the whole screen on the blueprint; the TO SAVE list as a paper sheet with its own title row; Save in
  yellow.
- **Revised 22 Nov** (asked: the Site board's bottom bar; "I don't want sharp everything"; the blueprint grid is good
  "but don't overuse it"): the bottom bar is a **floating drawing-ink pill** (round tab buttons, the active one on
  paper, the yellow mic in the middle); **soft shapes** (cards 16–22 px, pill buttons and chips, 14 px steppers);
  the **drawing grid only on Today's title block**: Speak and the other screens use plain blueprint or paper.

## 4d. The cue system (22 Nov, canvas V4 board "0 · The cue system")

Asked: *"add better visual cues for each component … a stronger design system so that we use visual cues properly and
strongly."* Four kinds of cue, each with one job, the same on every screen:

| Cue | Answers | Rule |
|---|---|---|
| **Category tile** | What kind of thing | An icon in a tinted rounded tile, one per kind: people (blue `#dfe6f3`/`#1e3a6e`), work (green `#d9ede3`/`#1f6b52`), materials (amber `#f8ecc4`/`#7a5a00`), machines (violet `#e6e2f2`/`#4a3f88`), problems (brick `#f6dcd4`/`#b2412b`), photos (graphite `#e8e4dc`/`#3a3d41`), weather and site (sky `#dcecf3`/`#23617a`). Same tile on Today, Needs you, the TO SAVE sheet, Quick add, and the scale bar's colours |
| **State mark** | What state | A round mark that differs in shape as well as colour: done (filled ink ✓), to tell (dashed ring), needs attention (brick !), waiting (ring ◔), not saved yet (dashed yellow), from your voice (yellow ◉). Never colour alone |
| **Time chip** | How urgent | Small mono pills: solid = act now (OVERDUE brick, TODAY yellow, ANSWERED blueprint), outlined = know it (TOMORROW, OPEN 2 DAYS) |
| **Action and voice** | What to do, who is talking | One yellow button per screen (the thing to do now); navy for an action on a card; outline for the other way; "See →" text to look. Mesiri always speaks from a pale-blueprint panel with its M mark; the person's own words sit on paper (or a light panel on Speak) with the voice mark |

Colours keep one job each: paper (ground), drawing ink (words, structure, the bar), blueprint (the one hero per screen;
its grid only on Today), highlighter yellow (do now), brick (something is wrong). Figures and references are mono.

Applied on Today (the scale bar's segments take each part's category colour when told, dashed when not, brick when it
needs attention, with the category icon under each; Needs you cards with tile + time chip + reference + action; the
day's rows with tile, figure, state mark, and "+ Tell" on the parts not told) and Speak (the voice mark and waveform on
what you said; the TO SAVE sheet with a NOT SAVED YET badge, tiles and pending marks per line, the line Mesiri asks
about marked "?" and tinted; Mesiri's question in its panel; Save all as the one yellow button).

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

1. **The direction** (§4b, canvas page V3): A site board (recommended, with B as night mode), B night shift, or C blueprint. Supersedes the third-colour choice of §4.
2. **Build order**: as §5 (look first, then Today and capture), or capture first (camera and attendance before
   the look).
