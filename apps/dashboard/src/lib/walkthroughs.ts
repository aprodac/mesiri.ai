import { MODULE_GROUPS, findPage, type ModuleGroup, type ModulePage } from './module-map'
import { APP_TOUR, PAGE_TOURS, type TourStep } from './tours'

// Learn Mesiri (SS-41/SS-42, docs/plans/learning-centre-plan.md): walkthroughs by page, module, workflow and role,
// started from the Learn page (pages/LearnPage.tsx) and run by components/walkthrough.tsx. One definition for every
// kind. Page and module walkthroughs are made from the hand-written page tours in lib/tours.ts, so a new page tour
// shows up on the Learn page and in its module by itself; workflows and role paths are written here.
//
// Rules that keep a walkthrough true as the product changes (the same as the tours, lib/tours.ts):
// - a step points at a `data-guide` marker, and the build fails when a marker is on no element (vite.config.ts);
// - every `page` must be a built page in lib/module-map.ts (the build checks that too);
// - a WhatsApp practice names the assistant tools that do it, and a test in the WhatsApp assistant checks they are
//   real tools (tests/agent_api/test_module_map_whatsapp.py), so a practice never asks for what WhatsApp can't do;
// - practice is real data (D-L3): every practice is followed by a step that shows how to take it back.

export type WalkKind = 'role' | 'outcome' | 'workflow' | 'module' | 'page'

/** Where a new record shows up, so the engine can say "Got it" when the practice is saved. */
export interface WalkCheck {
  /** An existing route (GET), read before the practice and every few seconds after. `{project}` is the project the
   *  person has picked (the top bar's, or the one the walkthrough's page opened). */
  path: string
  params?: Record<string, string | number>
  /** SS-72: the key that holds the rows, when the answer is not a list or `{ items }` (`work`, `sections`). */
  rows?: string
  /**
   * SS-72: done when the answer says so, instead of when a new row appears: dotted paths into the answer, each with the
   * value it must have, or `{ lte }` / `{ gte }` for a number. In a list, a part names the row by its `key` or `id`
   * (`steps.contract.done`); `length` is how many rows. Already true when the step opens: done at once.
   */
  has?: Record<string, string | number | boolean | { lte?: number; gte?: number }>
}

/** A practice on WhatsApp: the person sends this message to Mesiri. */
export interface TryWhatsApp {
  kind: 'whatsapp'
  say: string
  /** The WhatsApp assistant's tools that do it (agent_api/tools.py ALLOWED), checked by a test. */
  tools: string[]
  check?: WalkCheck
  /** false: look at the card Mesiri sends back, then tap Cancel, so nothing is saved and there is nothing to take
   *  back. For records WhatsApp can't take back (attendance, an advance, a site update). */
  save?: boolean
}

/** A practice here: the step's target is the real button; the person clicks it and the tour waits for its dialog. */
export interface TryHere {
  kind: 'here'
  check?: WalkCheck
  /** SS-72: the thing to do opens no dialog (a button that saves at once, a form on the page): the check is read
   *  every few seconds while the step is open, and the step moves on by itself once it passes. */
  poll?: boolean
  /** false: open the form, look at what it asks, then press Cancel, so nothing is saved (a payment, an advance, a
   *  work order: money or a promise a practice must not leave behind). 21 Nov: practices moved from WhatsApp to the
   *  dashboard's own forms. */
  save?: boolean
}

/** SS-72: a quick check, answered by tapping the page. */
export interface WalkAsk {
  /** The marker of the right answer (a row, a figure); several separated by `|`. */
  answer: string
  /** Said when they tap it. */
  right: string
  /** Said when they tap something else; the light then moves to the answer. */
  wrong: string
}

/** How to take a practice back (D-L3): WhatsApp words, the dashboard way, or both. */
export interface TakeBack {
  /** Who may take it back, when not everyone can. For anyone else the practice before it is card-only (WhatsApp:
   *  look at the card, tap Cancel) or skipped (here), and this step is skipped: a practice must never leave a real
   *  record that the person can't remove. Taking back a delivery, a use or a move is a stock correction:
   *  backend `materials/validation.py` ADJUSTMENT_ROLES (a test keeps the two the same). */
  roles?: readonly string[]
  say?: string
  /** The WhatsApp assistant's tools that take it back, checked by the same test. */
  tools?: string[]
  here?: string
}

export interface WalkStep extends TourStep {
  /** SS-69: the project to open when the page first asks for one ("Open Green Villa from the list"). */
  pick?: string
  /** SS-72: a starter-kit file this step uses (public/learn/kit/<file>): the bubble offers it to download. */
  file?: string
  /** SS-72: a quick check: the person taps the answer on the page. */
  ask?: WalkAsk
  /** Go to this page first; the engine navigates and waits for the step's target. A built page in module-map.ts. */
  page?: string
  try?: TryWhatsApp | TryHere
  takeBack?: TakeBack
  /** From a page tour: skipped when its element is not on screen (a button this role doesn't have). A hand-written
   *  workflow step is shown in the middle instead, so the story still holds on a company with no data yet. */
  optional?: boolean
  /** Light up the record the last practice saved (its row's `data-record-id`), else `target`. */
  showNew?: boolean
  /** Hold here until one of these markers shows (a page that first asks for a project): the page tour's
   *  `startWhen`. Clicks reach the page meanwhile. */
  waitFor?: string[]
  /** The guided project (SS-67): the chapter this step belongs to, for the chapter list in the bubble. Set by
   *  `journey(...)`, never by hand. */
  chapter?: string
  /** The step is about every project: the top bar goes to All projects before its page opens. */
  allProjects?: boolean
  /** The guided project: the story day the sample company must be on for this step (its chapter's `day`, on every
   *  step of the chapter, so a jump into its middle plays the days too). Earlier, the days are played on to it first; later, nothing changes (never back). Set by
   *  `journey(...)`. */
  day?: number
}

export interface Walkthrough {
  id: string
  kind: WalkKind
  title: string
  about: string
  minutes: number
  /** Only these system roles get it; none: everyone. */
  roles?: readonly string[]
  /** Raise when it changes enough to count as not done again. */
  version?: number
  /** A piece of a workflow (W2's first half): used by workflows and outcomes, not listed on its own. */
  part?: boolean
  /** Runs only inside the person's sample company (SS-67, lib/sandbox.ts); the engine refuses it anywhere else. */
  sandbox?: boolean
  steps: WalkStep[]
}

/** Remembered per person in users.guide_seen under this key (lowercase, like every guide key). */
/** Whether this role may take back the practice at `index`: the next take-back step from there says who may. */
export function canTakeBack(walk: Walkthrough, index: number, role: string | null | undefined): boolean {
  const back = walk.steps.slice(index).find((s) => s.takeBack)?.takeBack
  return !back?.roles || back.roles.includes((role ?? '').toUpperCase())
}

/** Whether the practice before a "There it is" step (`showNew`) really saved something for this role: not when it was
 *  card-only (`save: false`, or a practice this role could not take back). Then "There it is" would point at nothing
 *  and say something untrue, so the engine skips it (review 16 Nov). */
export function practiceSaved(walk: Walkthrough, index: number, role: string | null | undefined): boolean {
  for (let i = index - 1; i >= 0; i--) {
    const t = walk.steps[i].try
    if (!t) continue
    if (t.save === false) return false
    return canTakeBack(walk, i, role)
  }
  return true
}

export function learnKey(id: string): string {
  return `/learn/${id}`
}

const minutesFor = (steps: number) => Math.max(1, Math.round(steps * 0.4))

const RECORDERS = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER'] as const
const MONEY_ROLES = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE', 'PROJECT_MANAGER'] as const
const BILLING_ROLES = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] as const
const STARTERS = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER'] as const

// Newest first (by day, then saved time), so a delivery saved now is in the first page.
const INFLOWS: WalkCheck = { path: '/materials/inflows', params: { limit: 100 } }
/** Who may correct (take back) a stock movement: backend ADJUSTMENT_ROLES. */
const ADJUSTERS = ['ADMIN', 'PROJECT_MANAGER'] as const
/** Who may take back an expense: backend authorization/roles.py MONEY_MANAGE_ROLES (not a project manager, who may
 *  record one). */
const MONEY_MANAGERS = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] as const

/** Workflows: one job from start to finish, across pages, with practice (plan section 5.2). */
export const WORKFLOWS: Walkthrough[] = [
  {
    id: 'delivery',
    kind: 'workflow',
    part: true,
    title: 'A delivery, from site to stock',
    about: 'Record a delivery on the dashboard, see it in stock, and take it back.',
    minutes: 4,
    roles: RECORDERS,
    steps: [
      {
        page: '/materials?view=stock',
        title: "Let's record a delivery",
        text: "We'll record a real delivery here on the dashboard, see it land in stock, then take it back. Nothing stays behind.", say: 'Let\'s record a real delivery, right here on the dashboard. We\'ll watch it land in stock, and then take it back, so nothing stays behind.',
        mood: 'hello',
      },
      {
        page: '/materials?view=stock',
        target: 'materials.views',
        title: 'Stock and movements',
        text: 'Stock is what each site holds now. Movements is every delivery, use and move that changed it.', say: 'Stock shows what each site holds right now. Movements is the full story: every delivery, every use, every transfer that changed it.',
      },
      {
        page: '/materials?view=movements',
        target: 'materials.in',
        title: 'Your turn: record it',
        text: 'Click Record delivery: 10 bags of cement, your site, and save. No supplier: a practice must not leave a new one behind. I will wait.', say: 'Your turn. Click Record delivery. Ten bags of cement, your site, and save. Take your time, I\'ll wait.',
        mood: 'send',
        try: { kind: 'here', check: INFLOWS },
      },
      {
        page: '/materials?view=movements',
        target: 'materials.list',
        showNew: true,
        title: 'There it is',
        text: 'The delivery is in Movements, and the stock went up by 10 bags.', say: 'There it is. The delivery is in movements, and the stock went up by ten bags.',
        mood: 'happy',
      },
      {
        page: '/materials?view=movements',
        target: 'materials.list',
        title: 'Take it back',
        text: 'It was practice. Open the row you just saved and press Correct: it is reversed, and both lines stay in the history.', say: 'That was practice, so let\'s take it back. Open the row you just saved, and press Correct. It\'s reversed, and both lines stay in the history, so nothing ever quietly disappears.',
        takeBack: { roles: ADJUSTERS, here: 'Open the row, then Correct (an admin or project manager).' },
      },
      {
        page: '/materials?view=movements',
        target: 'materials.out',
        title: 'Using it works the same',
        text: 'Material used on site: Record use, here. The site can also send it on WhatsApp: "Used 20 bags cement for the slab".', say: 'Using material works the same way. Record use, right here. Or the site sends one message on WhatsApp: used twenty bags of cement for the slab.',
        mood: 'happy',
      },
    ],
  },
  // W1's first half: the site's day in one message (practice: look at the card, then Cancel; a site update can't be
  // taken back on WhatsApp, so nothing is saved).
  {
    id: 'site-update',
    kind: 'workflow',
    part: true,
    title: "The site's day in one message",
    about: 'Who came, what was done and what is stuck, in one line typed into Tell Mesiri (or sent on WhatsApp).',
    minutes: 2,
    roles: RECORDERS,
    steps: [
      {
        page: '/today',
        title: 'Your day, from one message',
        text: 'At the end of the day the site engineer sends one WhatsApp message. Mesiri turns it into attendance, work done and issues, and they show here.', say: 'Here\'s how a day on site reaches you. Every evening, Ravi, your site engineer at Green Villa, sends Mesiri one WhatsApp message, just the way he\'d text you. Mesiri reads it and fills this page: who came, what got done, and anything that went wrong.',
        mood: 'hello',
      },
      {
        page: '/today',
        title: 'Your turn: type the day',
        text: 'Type this into Tell Mesiri, the New box at the top. A card comes back with the people, the work and the issue it found. This is practice: look at the card, then tap Cancel, so nothing is saved.', say: 'Your turn. Type this into Tell Mesiri, the New box at the top of the dashboard. In a moment a card comes back, showing what Mesiri understood: the workers, the work, and the problem. It\'s only practice, so look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: '6 masons, 4 helpers. First-floor slab shuttering done. Cement ran out.', tools: ['record_attendance', 'record_work', 'report_issue'], save: false },
      },
      {
        page: '/today',
        title: 'On a real day, tap Save',
        text: "Then the site's day here shows it at once. From site, the same line works on WhatsApp, and so does a voice note or a photo of the work.", say: 'On a real day, you tap Save, and it shows up here straight away. From site, Ravi can send the same line on WhatsApp. A voice note, or a photo of the work, does the same job.',
        mood: 'happy',
      },
    ],
  },
  // W1's second half: from the sites' days to the daily report.
  {
    id: 'daily-report',
    kind: 'workflow',
    part: true,
    title: 'From the sites to the daily report',
    about: "Each site's day, everything it sent, and the report that goes out.",
    minutes: 2,
    steps: [
      { page: '/today', target: 'today.sites', title: "Each site's day", text: 'Who came, what was done, what came in, and which sites have not reported yet.', say: 'This is each site\'s day at a glance. Who turned up, what was done, what material came in. And if a site hasn\'t reported yet, you see that here, before you have to call anyone.' },
      { page: '/site-log', title: 'Everything the sites sent', text: 'The Site log keeps every update, photo and entry, by day and by site.', mood: 'look', say: 'Nothing gets lost. The site log keeps every message, photo and entry, by day and by site, so you can always go back and check.' },
      { page: '/reports', target: 'reports.list', title: 'The daily report', text: 'Every evening each site gets its daily report (DPR), and it goes to the owner and the client.', say: 'Every evening, each site\'s daily progress report is made for you, and sent to you and to your client. Nobody has to sit and type it up.' },
      { page: '/reports', target: 'reports.pdf', title: 'Exactly as they got it', text: 'Open the PDF the owner and the client received.', mood: 'look', say: 'And this is the report exactly as your client received it. What they saw is what you see.' },
      { page: '/today', target: 'today.send', title: 'Or send it now', text: "When the day looks right, press Send here. From site, \"Send today's report\" on WhatsApp does the same.", mood: 'send', say: 'If the day looks right and you don\'t want to wait for the evening, press send, right here. From site, Ravi can do it on WhatsApp too: send today\'s report.' },
    ],
  },
  // W2's first part: the site asks for material.
  {
    id: 'material-request',
    kind: 'workflow',
    part: true,
    title: 'Asking for material',
    about: 'Ask for material on the dashboard (or from site on WhatsApp), and the request waits for the office.',
    minutes: 2,
    roles: RECORDERS,
    steps: [
      {
        page: '/materials/requests',
        title: 'Asking for material',
        text: 'Material is asked for here, or by the site on WhatsApp. The request waits until the office orders it.', say: 'It starts with a request. You can make it right here, or Ravi asks from site on WhatsApp. Either way, it waits here until the office orders it.',
        mood: 'hello',
      },
      {
        page: '/materials/requests',
        target: 'req.add',
        title: 'Your turn: ask for cement',
        text: "Press New request: 50 bags of cement for your site, needed by Friday, and save. I'll watch for the request here.", say: 'Your turn. Press new request. Fifty bags of cement for your site, needed by Friday, and save. I\'ll watch for it to arrive here.',
        mood: 'send',
        try: { kind: 'here', check: { path: '/procurement/requests', params: { status: 'open' } } },
      },
      {
        page: '/materials/requests',
        showNew: true,
        title: 'There it is',
        text: 'The request is in the list, waiting for the office. The site can ask how it is going on WhatsApp: "my requests".', say: 'There it is, waiting for the office. And Ravi never has to call to chase it. From site, he just asks Mesiri: my requests.',
        mood: 'happy',
      },
      {
        page: '/materials/requests',
        title: 'Take it back',
        text: 'It was practice, so cancel it: open the request and press Cancel.', say: 'That was only practice, so let\'s cancel it. Open the request, and press cancel.',
        takeBack: { here: 'Open the request, then Cancel.' },
      },
    ],
  },
  // W2's middle: the office orders it and watches what is still to come.
  {
    id: 'material-order',
    kind: 'workflow',
    part: true,
    title: 'Ordering it',
    about: 'Purchase orders, what is still to come, and receiving on the order.',
    minutes: 1,
    steps: [
      {
        page: '/procurement/orders',
        title: 'Ordering it',
        text: 'The office turns requests into purchase orders here, and sends them to the supplier as a PDF or on WhatsApp.', say: 'Next, the office turns the request into a purchase order, right here, and sends it to the supplier, as a PDF or on WhatsApp.',
      },
      { page: '/procurement/pending', title: 'What is still to come', text: 'Every order not yet delivered in full, so you know whom to chase.', say: 'This is everything ordered that hasn\'t fully arrived yet. So you always know which supplier to chase, and for what.', mood: 'look' },
      {
        page: '/procurement/grn',
        title: 'When it arrives',
        text: "A delivery on an order is received on it (the GRN), so the order, the stock and the supplier's bill agree.", say: 'When the lorry arrives, the delivery is received against its order. That\'s the goods received note. Now the order, the stock and the supplier\'s bill all agree, so nobody pays for what never came.',
        mood: 'happy',
      },
    ],
  },
  // W4's first half: attendance from site (practice: Cancel; attendance can't be taken back on WhatsApp).
  {
    id: 'attendance',
    kind: 'workflow',
    part: true,
    title: 'Attendance from site',
    about: 'Who came, in one line typed into Tell Mesiri (or sent from site on WhatsApp); the muster roll fills itself.',
    minutes: 1,
    roles: RECORDERS,
    steps: [
      { page: '/labour', title: 'Attendance from site', text: 'Who came is told to Mesiri in one line: typed here, or sent from site on WhatsApp. Attendance, the muster roll and the wages all follow from it.', say: 'Every day, Mesiri is told who came, in one line. Typed here, or sent from site on WhatsApp. That is all it takes: attendance, the muster roll and the wages all follow from it.', mood: 'hello' },
      {
        page: '/labour',
        title: 'Your turn: mark attendance',
        text: 'Type this into Tell Mesiri, the New box at the top. The card shows the team and how many came. This is practice: look at the card, then tap Cancel.', say: 'Your turn. Type this into Tell Mesiri, the New box at the top. The card shows the team and how many turned up. It\'s practice, so just look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: "Rahim's crew: 4 helpers, 2 masons", tools: ['record_attendance'], save: false },
      },
      { page: '/labour', target: 'labour.views', title: 'By day and by month', text: 'Attendance by day, and the muster roll for the month, fill from those lines.', say: 'Attendance by day, and the muster roll for the whole month, fill themselves from those lines. No register to copy out.' },
    ],
  },
  // W4's second half: wages and advances.
  {
    id: 'wages',
    kind: 'workflow',
    part: true,
    title: 'Wages and advances',
    about: 'The wage sheet from attendance, approved and paid, less advances.',
    minutes: 2,
    steps: [
      {
        page: '/labour/wages',
        title: 'The wage sheet',
        text: "The week's attendance at each worker's daily wage, less any advance. Approve it, then pay it, here.", say: 'At the end of the week, here\'s the wage sheet: each worker\'s days at their daily wage, minus any advance. Approve it, then pay it, right here.',
      },
      { page: '/labour/advances', title: 'Advances', text: 'Money given ahead is kept per person and comes off their next wages by itself.', say: 'When someone takes money in advance, it\'s kept against their name, and it comes off their next wages by itself. No more notebooks.' },
      {
        page: '/labour/advances',
        target: 'advances.give',
        title: 'Your turn: an advance',
        text: 'Press Give advance: who, how much, and which cash box it came from. This is practice: look at what it asks, then press Cancel.', say: 'Your turn. Press give advance. It asks who, how much, and which cash box it came out of. Practice again: look, then press cancel.',
        mood: 'send',
        try: { kind: 'here', save: false },
      },
    ],
  },
  // SS-48: W3, W5..W11 (plan section 5.2). A practice WhatsApp can't take back is `save: false` (look at the card,
  // then Cancel); questions are said in the text, not practised, because a practice must save something.
  // W3: supplier bill to payment.
  {
    id: 'supplier-bill',
    kind: 'workflow',
    title: 'Supplier bill to payment',
    about: "Record a bill, match it to what was delivered, see what you owe, and pay it.",
    minutes: 3,
    roles: MONEY_ROLES,
    steps: [
      {
        page: '/finance/expenses',
        title: 'Every bill and payment',
        text: 'A bill from a shop, diesel, a hired machine, tea for the site: each is an expense here, with its photo, its project and its category.',
        mood: 'hello',
      },
      {
        page: '/finance/expenses',
        target: 'exp.add',
        title: 'Your turn: record an expense',
        text: "Press Record expense: 500 for drinking water, your site, no supplier, and save (add the bill's photo on a real day). I'll watch for it here.",
        mood: 'send',
        // No supplier named: a practice must not leave a new supplier behind after it is taken back.
        try: { kind: 'here', check: { path: '/expenses' } },
      },
      { page: '/finance/expenses', showNew: true, title: 'There it is', text: 'The expense is in the list, and in the project\'s cost.', mood: 'happy' },
      {
        page: '/finance/expenses',
        title: 'Take it back',
        text: "It was practice, so take it back: the row's menu, Take back.",
        say: 'That was practice, so take it back. Open the row\'s menu, and press take back.',
        takeBack: { roles: MONEY_MANAGERS, here: "The row's menu (⋯), then Take back." },
      },
      { page: '/finance/vendors', target: 'vendors.tiles', title: 'What you owe each supplier', text: 'Their bills less what you paid, what is overdue, and what you paid ahead.', mood: 'look' },
      {
        page: '/finance/vendors',
        target: 'vendors.view',
        title: 'Delivered, no bill',
        text: 'Material that came with no bill yet. When the bill comes, match it to those deliveries, so nothing is paid twice or for what never came.',
        mood: 'worry',
      },
      {
        page: '/finance/vendors',
        target: 'vendors.list',
        title: 'Pay them',
        text: 'Open a supplier to pay a bill: Pay, the amount and the account it went from.',
        mood: 'happy',
      },
    ],
  },
  // W5: a subcontractor, from work order to bill.
  {
    id: 'subcontract',
    kind: 'workflow',
    title: 'Subcontractor, from work order to bill',
    about: 'A work order at an agreed rate, the work measured, the bill checked against it, then paid.',
    minutes: 3,
    roles: MONEY_ROLES,
    steps: [
      {
        page: '/subcontract/work-orders',
        title: 'The work order',
        text: 'What a subcontractor will do, how much, and at what rate. Everything after is checked against it.',
        mood: 'hello',
      },
      {
        page: '/subcontract/work-orders',
        target: 'wo.add',
        title: 'Your turn: a work order',
        text: 'Press New work order: the subcontractor, the work, the quantity and the rate. This is practice: look at what it asks, then press Cancel.',
        mood: 'send',
        try: { kind: 'here', save: false },
      },
      {
        page: '/subcontract/work-orders',
        title: 'Measure the work',
        text: 'Each week the work done is measured on the work order (or sent from site: "Sree tiles did 600 sq ft this week"). That is what the bill is checked against.',
      },
      {
        page: '/subcontract/bills',
        title: 'Bills & checks',
        text: 'Their bill against the work measured and the rate agreed, less advances and retention. Approve it, or send it back with why.',
        mood: 'think',
      },
      {
        page: '/subcontract/bills',
        title: 'Advances come off by themselves',
        text: 'Money given ahead ("Gave Sree tiles 20,000 advance") comes off their next bill.',
        mood: 'happy',
      },
    ],
  },
  // W6: start a new project.
  {
    id: 'new-project',
    kind: 'workflow',
    title: 'Start a new project',
    about: 'The project, its BOQ from your Excel, the schedule, the site team, and the first report.',
    minutes: 3,
    roles: STARTERS,
    steps: [
      {
        page: '/planning/setup',
        title: 'Start a project',
        text: 'Project start lists every step from "won" to "work starts", and ticks each one as it is done.', say: 'You\'ve won the job. Project start lists every step from won to work starts, and ticks each one off as it\'s done.',
        mood: 'hello',
      },
      {
        page: '/planning/setup',
        target: 'setup.new',
        title: 'A new project',
        text: 'New project: its name, the client and the place. It opens on its start steps.', say: 'A new job starts here. New project asks its name, the client and the place, then opens its steps.',
        mood: 'happy',
      },
      { page: '/planning/setup', target: 'setup.steps', title: 'Steps to "work starts"', text: 'Dates, contract, BOQ, schedule, sites, the site team, suppliers.', say: 'The steps: dates, contract, B O Q, schedule, sites, the site team and suppliers. Do them in any order. Each one ticks itself.', mood: 'think' },
      { page: '/boq', target: 'boq.import', title: 'The BOQ from your Excel', text: 'Upload the estimate you already have: its items, units, quantities and rates become the BOQ.', say: 'Upload the estimate you already have in Excel. Its items, units, quantities and rates become the B O Q. Nothing typed twice.' },
      { page: '/planning/schedule', target: 'schedule.add', title: 'The schedule from the BOQ', text: 'Each BOQ section becomes a bar; Quick plan puts them one after another.', say: 'Each B O Q section becomes a bar on the schedule. Quick plan lines them up one after another in a minute.' },
      {
        page: '/team',
        target: 'team.add',
        title: 'The site team',
        text: 'Press Add person: the engineer, their WhatsApp number and their site. This is practice: look at what it asks, then press Cancel.', say: 'Now the team. Press add person. It asks your site engineer\'s name, their WhatsApp number, and their site. Practice: look, then press cancel.',
        try: { kind: 'here', save: false },
      },
      { page: '/reports', target: 'reports.list', title: 'The first report', text: 'From their first message, the daily report goes out every evening.', say: 'And from Ravi\'s very first message, the daily report goes out every evening. That\'s it. The project is running.', mood: 'happy' },
    ],
  },
  // W7: an issue, start to finish.
  {
    id: 'issue',
    kind: 'workflow',
    title: 'An issue, start to finish',
    about: 'A hold-up reported from site, seen by the office, and closed when it is fixed.',
    minutes: 2,
    steps: [
      { page: '/issues', title: 'Hold-ups from site', text: 'No water, a machine broken, a drawing missing: each stays open here until someone fixes it.', say: 'No water, a broken machine, a missing drawing. Every hold-up the site reports stays here until someone sorts it out.', mood: 'hello' },
      {
        page: '/issues',
        target: 'issues.add',
        title: 'Your turn: report one',
        text: 'Press Report issue: the problem, the site, how urgent. This is practice: look at what it asks, then press Cancel.', say: 'Your turn. Press report issue. It asks the problem, the site, and how urgent it is. Practice: look, then press cancel.',
        mood: 'send',
        try: { kind: 'here', save: false },
      },
      { page: '/issues', target: 'issues.list', title: 'Open until fixed', text: 'The oldest first. Open one to say it is seen, then fixed, or that it will not be fixed and why.', say: 'The oldest are first. Open one to mark it seen, then fixed, or say why it won\'t be fixed. Nothing gets forgotten.', mood: 'think' },
      { page: '/issues', target: 'issues.stats', title: 'At a glance', text: 'How many are open, and how long they have waited.', say: 'At a glance: how many are open, and how long they\'ve been waiting.', mood: 'look' },
      { page: '/issues', title: 'Closing it', text: 'When it is sorted, open it and mark it fixed. From site, "Water is back at the compound wall" on WhatsApp closes it too.', say: 'And when it\'s sorted, open it and mark it fixed. From site, Ravi can just say so on WhatsApp, and it closes.', mood: 'happy' },
    ],
  },
  // W8: billing the client.
  {
    id: 'billing',
    kind: 'workflow',
    title: 'Billing the client',
    about: 'Running bills from the work done, what the client paid, and what they still owe.',
    minutes: 2,
    roles: BILLING_ROLES,
    steps: [
      { page: '/billing/ra-bills', title: 'Running bills', text: 'Each RA bill is the work done since the last one at the BOQ rates, less retention and advance.', say: 'Now getting paid. Each running bill is the work done since the last one, at your B O Q rates, less retention and advance. Worked out for you.', mood: 'hello' },
      { page: '/accounts/receivables', title: 'What the client owes', text: 'Every bill, what was paid against it, and how old the rest is.', say: 'Here is everything your client owes: each bill, what\'s been paid, and how long the rest has been waiting.', mood: 'look' },
      {
        page: '/accounts/receivables',
        target: 'recv.record',
        title: 'Your turn: the client paid',
        text: 'Press Money received: the amount, the bill it goes against, and the bank it came into. This is practice: look at what it asks, then press Cancel.', say: 'Your turn. When the client pays, press money received. It asks the amount, which bill it clears, and the bank it came into. Practice: look, then press cancel.',
        mood: 'send',
        try: { kind: 'here', save: false },
      },
      { page: '/accounts/receivables', title: 'Ask any time', text: 'In Tell Mesiri, or on WhatsApp: "What does the client still owe on Green Villa?"', say: 'And any time, ask Mesiri, here or on WhatsApp: what does the client still owe on Green Villa?', mood: 'happy' },
    ],
  },
  // W9: cost control (questions only, nothing to practise).
  {
    id: 'cost-control',
    kind: 'workflow',
    title: 'Cost control',
    about: 'Which work costs more than it earns, labour and material, before the bill comes.',
    minutes: 2,
    roles: MONEY_ROLES,
    steps: [
      { page: '/boq', target: 'boq.lines', title: 'It starts with the BOQ', text: 'Each line\'s rate is the budget; the work site sends earns against it.', say: 'It all starts with the B O Q. Each line\'s rate is your budget, and every bit of work the site reports earns against it.', mood: 'hello' },
      { page: '/cost', target: 'cost.projects', title: 'Every project, worst first', text: 'Its forecast at completion, done against spent, and the last 7 days.', say: 'Here is every project, the worst one first. Where it\'s heading by the end, what\'s done against what\'s spent, and how the last week went.', mood: 'look' },
      { page: '/cost/green-red', target: 'gr.lines', title: 'Labour, line by line', text: 'Green: the work earned its labour. Red: it cost more. Worst first, with why.', say: 'Now labour, line by line. Green means the work earned what the labour cost. Red means it cost more. The worst are at the top, with the reason.', mood: 'think' },
      { page: '/cost/budget', target: 'budget.kinds', title: 'Budget against spent', text: 'For labour, material and subcontract: the budget, what the work earned, and what was spent.', say: 'For labour, material and subcontractors: the budget, what the work has earned, and what you\'ve actually spent. Side by side.' },
      { page: '/cost/materials', title: 'Material against the BOQ', text: 'What the work needed by the BOQ against what was used, and what is short to finish.', say: 'And material: what the work should have needed, against what was really used. If cement is disappearing, this is where you\'ll see it.', mood: 'worry' },
      { page: '/cost', title: 'Ask Mesiri', text: 'In Tell Mesiri, or on WhatsApp: "How is Green Villa doing on cost?" or "Which work is over on labour this week?"', say: 'And you don\'t have to open all of this. Just ask Mesiri, here or on WhatsApp: how is Green Villa doing on cost?', mood: 'happy' },
    ],
  },
  // W10: machines and hire.
  {
    id: 'machines',
    kind: 'workflow',
    title: 'Machines and hire',
    about: "Each machine's day from site, and the hire bill checked against it.",
    minutes: 2,
    roles: RECORDERS,
    steps: [
      { page: '/equipment/log', title: "Each machine's day", text: 'Hours worked, idle and broken down, and the diesel, from one line: typed into Tell Mesiri, or sent from site.', mood: 'hello' },
      {
        page: '/equipment/log',
        title: 'Your turn: log the machines',
        text: 'Type this into Tell Mesiri, the New box at the top. The card shows each machine and its hours. This is practice: look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: 'Mixer 8 hrs, roller broke down 3 hrs', tools: ['log_machines'], save: false },
      },
      { page: '/equipment/hire', title: 'The hire bill, checked', text: 'The hours the owner billed against the hours site logged, so you pay for what was worked.', mood: 'think' },
      { page: '/equipment/hire', title: 'Ask Mesiri', text: 'In Tell Mesiri, or on WhatsApp: "Does the JCB bill match our hours?"', mood: 'happy' },
    ],
  },
  // W11: month end.
  {
    id: 'month-end',
    kind: 'workflow',
    title: 'Month end',
    about: "The month's report, the books, closing the month, and the export for your accountant.",
    minutes: 2,
    roles: BILLING_ROLES,
    steps: [
      { page: '/reports/period', title: "The month's report", text: 'Work, labour, material and money for the week or the month, per project. Download it here, or ask Mesiri: "Send me October\'s report for Green Villa".', say: 'At month end, here\'s the full picture: work, labour, material and money, for each project. Download it here, or just ask Mesiri: send me October\'s report for Green Villa.', mood: 'hello' },
      { page: '/accounts', title: 'The books keep themselves', text: 'Every bill, payment, delivery and wage recorded here or on WhatsApp is already in the books.', say: 'And your accounts keep themselves. Every bill, payment, delivery and wage already went into the books, the moment it was recorded.', mood: 'look' },
      { page: '/accounts/periods', title: 'Close the month', text: 'Once the month is checked, close it: nothing in it can change without opening it again.', say: 'Once your accountant has checked the month, close it. From then on, nothing in it can change without opening it again.', mood: 'think' },
      { page: '/accounts/tally', title: 'For your accountant', text: 'The month for Tally in one file, so nobody types it in again.', say: 'And for your accountant: the whole month for Tally, in one file. Nobody types it in again.', mood: 'happy' },
    ],
  },
]


/** The app tour, as a walkthrough that starts on Today. */
const APP_WALK: Walkthrough = {
  id: 'app',
  kind: 'page',
  title: 'Around the app',
  about: 'The sidebar, search, picking a project, what to send on WhatsApp, and help.',
  minutes: minutesFor(APP_TOUR.steps.length),
  version: APP_TOUR.version,
  steps: APP_TOUR.steps.map((s) => ({ ...s, page: '/today' })),
}

/** The page's address without ?view=, the key of its tour in PAGE_TOURS. */
const tourPath = (page: ModulePage) => page.url.split('?')[0]

function pageSteps(page: ModulePage): WalkStep[] {
  const tour = PAGE_TOURS[tourPath(page)]
  if (!tour) return []
  const intro: WalkStep[] = tour.introFromPage ? [{ title: page.title, text: page.about, mood: 'hello', say: tour.introSay, for: tour.introFor }] : []
  const steps: WalkStep[] = [...intro, ...tour.steps].map((s) => ({ ...s, page: page.url, optional: true }))
  // A page that shows a picker first (a project to choose): the first step waits for its content.
  if (tour.startWhen?.length && steps[0]) steps[0] = { ...steps[0], waitFor: tour.startWhen }
  return steps
}

/** Built pages that have a hand-written tour, one per tour: the views of a page (Stock, Movements, Items) share its
 *  tour, which starts on the first view. */
function pagesWithTours(group: ModuleGroup): { page: ModulePage; title: string }[] {
  const built = group.pages.filter((p) => p.status === 'built' && !p.shortcut && PAGE_TOURS[tourPath(p)])
  const paths = [...new Set(built.map(tourPath))]
  return paths.map((path) => {
    const views = built.filter((p) => tourPath(p) === path)
    const title = views.length > 1 ? `${group.title}: ${views.map((v) => v.navTitle ?? v.title).join(', ')}` : views[0].title
    return { page: views[0], title }
  })
}

export const PAGE_WALKS: Walkthrough[] = [
  APP_WALK,
  ...MODULE_GROUPS.flatMap((group) =>
    pagesWithTours(group).map(({ page, title }) => {
      const steps = pageSteps(page)
      return {
        id: `page${tourPath(page).replace(/\//g, '-')}`,
        kind: 'page' as const,
        title,
        about: page.about,
        minutes: minutesFor(steps.length),
        roles: page.roles,
        version: PAGE_TOURS[tourPath(page)].version,
        steps,
      }
    }),
  ),
]

/** A module = its pages' tours back to back, in sidebar order (plan section 5.3). */
export const MODULE_WALKS: Walkthrough[] = MODULE_GROUPS.flatMap((group) => {
  const pages = pagesWithTours(group)
  if (pages.length === 0) return []
  const steps = pages.flatMap(({ page }) => pageSteps(page))
  const built = new Set(group.pages.filter((p) => p.status === 'built' && !p.shortcut).map(tourPath)).size
  return [
    {
      id: `module-${group.key}`,
      kind: 'module' as const,
      title: group.title,
      // Until every page of the module has its tour (SS-44..SS-47), say how much it covers.
      about: pages.length < built ? `${group.about} ${pages.length} of ${built} pages so far.` : group.about,
      minutes: minutesFor(steps.length),
      steps,
    },
  ]
})

/** Every walkthrough made so far, for the ones made of others. */
// SS-69 part 1: the sample company's own chapters, up to the BOQ. Every "your turn" is done on the real page and
// checked from what the API says afterwards (SS-72 `has`), never from where the person clicked. The figures are the
// starter kit's (scripts/learn_kit/make_kit.py): the contract summary and the estimate.
const KIT_CONTRACT = 'Green Villa - contract summary.pdf'
const KIT_ESTIMATE = 'Green Villa - estimate.xlsx'
const START_CHECK = (step: string) => ({ path: '/projects/{project}/start', has: { [`steps.${step}.done`]: true } })
const WORK_LEFT = (n: number) => ({ path: '/projects/{project}/boq/work', params: { unlinked: 'true', limit: 500 }, rows: 'work', has: { 'work.length': { lte: n } } })

const GV_SETUP: Walkthrough = {
  id: 'gv-setup',
  kind: 'workflow',
  part: true,
  sandbox: true,
  title: 'Set up Green Villa',
  about: 'The dates, the contract and the BOQ, from the paperwork, on Project start.',
  minutes: 4,
  roles: STARTERS,
  steps: [
    {
      page: '/planning/setup', waitFor: ['setup.steps'], pick: 'Green Villa', mood: 'hello', file: KIT_CONTRACT,
      title: "Green Villa: the office's turn",
      text: 'Green Villa has been building for months: the Main block is up to its parapet, the Annex is on its footings. Two weeks ago Ravi started sending the site\'s day to Mesiri, but nobody set the project up in the office: no dates, no contract, no BOQ. You are the owner. Open Green Villa here; the contract summary has everything.',
      say: 'Green Villa has been building for months. The Main block is up to its parapet, and the Annex is on its footings. Two weeks ago, Ravi started sending the site\'s day to Mesiri. But nobody set the project up in the office. No dates, no contract, no B O Q. You are the owner, so let us do it now. Open Green Villa. Everything you need is on the contract summary.',
      for: {
        basics: { text: 'Green Villa has been building for months, and for two weeks the site has sent its day to Mesiri. The office side was never filled in: when the job starts and ends, what the client agreed to pay, and the list of work (the BOQ). Open Green Villa here; the contract summary has it all.' },
        expert: { text: 'Green Villa is mid-job (Main block at its parapet, Annex at footings), on Mesiri for two weeks, without dates, a contract or a BOQ. Project start lists what is missing; the contract summary has the figures.' },
      },
    },
    {
      page: '/planning/setup', target: 'setup.dates', mood: 'think',
      try: { kind: 'here', poll: true, check: START_CHECK('dates') },
      title: 'Your turn: the dates',
      text: 'From the contract summary: work starts 2 November 2026, handover 31 July 2027. Pick them and press Save dates.',
      say: 'Your turn. From the contract summary: work starts on the second of November, and the handover is the thirty first of July, next year. Pick them, and press Save dates.',
      for: { basics: { text: 'Two dates from the contract summary: work starts 2 November 2026, and the building is handed over 31 July 2027. Pick them and press Save dates. Every "late" Mesiri shows is measured against these.' } },
    },
    {
      page: '/planning/setup', target: 'setup.contract', mood: 'think', file: KIT_CONTRACT,
      try: { kind: 'here', poll: true, check: START_CHECK('contract') },
      title: 'Your turn: the contract',
      text: 'Press "Set the client and contract" (optional on the page for a small job; Green Villa has a signed one). Client: Dr. Anand Krishnan. Contract value ₹82,06,050, agreement GV/2026/007, signed 20 October 2026, retention 5%, advance ₹8,20,605, recovery 10% a bill, GST 18%, defects 12 months.',
      say: 'Now the contract. The page calls it optional, for small jobs, but Green Villa has a signed one. Press, set the client and contract. The client is Doctor Anand Krishnan. Everything else is on the contract summary: the value, the advance, the retention and the defects period.',
      for: {
        basics: { text: 'The contract is what the client agreed to pay and how. Press "Set the client and contract" and copy from the summary: client Dr. Anand Krishnan, value ₹82,06,050, retention 5% (kept back until the defects period ends), advance ₹8,20,605 (paid at the start, taken back 10% from each bill), GST 18%, defects 12 months.' },
        expert: { text: 'Client Dr. Anand Krishnan, ₹82,06,050, GV/2026/007, retention 5%, advance ₹8,20,605 recovered at 10%, GST 18%, DLP 12 months. RA bills read these.' },
      },
    },
    {
      page: '/planning/setup', target: 'setup.boq', mood: 'look', file: KIT_ESTIMATE,
      try: { kind: 'here', poll: true, check: START_CHECK('boq') },
      title: 'Your turn: the BOQ',
      text: 'Download the estimate, then press "Upload the BOQ Excel" and pick it. I show you what I read before anything is saved: check it, then press Import.',
      say: 'Last one: the B O Q. Download the estimate, press upload the B O Q Excel, and pick it. I show you what I read before anything is saved. Have a look, then press import.',
      for: {
        basics: { text: 'The BOQ is the list of every piece of work with its quantity and price, made before the job was won. Download the estimate, press "Upload the BOQ Excel" and pick it. I show you what I read first; then press Import.' },
        data: { text: 'This is the step for your own Excel later. Download the estimate, press "Upload the BOQ Excel", check the columns I found and the lines I read, then press Import.' },
      },
    },
    {
      page: '/planning/setup', target: 'setup.steps', mood: 'happy',
      title: 'Three done',
      text: 'Each step ticked itself the moment it was saved: nobody marks anything done by hand. Now let us see what the BOQ tells you.',
      say: 'Three done. Each step ticked itself the moment it was saved. Nobody marks anything done by hand. Now let us see what the B O Q tells you.',
    },
  ],
}

const GV_BOQ: Walkthrough = {
  id: 'gv-boq',
  kind: 'workflow',
  part: true,
  sandbox: true,
  title: 'The BOQ',
  about: 'What the estimate shows once it is in, and the site work that counts on it.',
  minutes: 4,
  roles: STARTERS,
  steps: [
    {
      page: '/boq', target: 'boq.totals', waitFor: ['boq.lines'], pick: 'Green Villa', mood: 'look',
      title: 'Green Villa at a glance',
      text: 'What the client pays, what it should cost you, the margin, and what the work done has earned. "Lines priced" says 3 lines have no cost yet, so the margin is only for the priced lines, and not final.',
      say: 'Green Villa at a glance. What the client pays, what it should cost you, your margin, and what the work done has earned. Lines priced says three lines have no cost yet. So the margin counts only the priced lines, and it is not final.',
      for: {
        basics: { text: 'The contract value is what the client pays for everything; the budget is what it should cost you; the margin is what you keep. "Lines priced" says 3 lines have no cost yet: the tiling and granite, waiting for the tiler\'s price. So the margin shown is for the other lines only.' },
        expert: { text: 'Contract, budget, margin, earned. 3 lines unpriced (the tiling, for the subcontractor): the margin is on the priced lines and provisional.' },
      },
    },
    {
      page: '/boq', target: 'boq.addall', mood: 'think',
      try: { kind: 'here', poll: true, check: WORK_LEFT(3) },
      title: 'Your turn: count the site\'s work',
      text: 'The site sent 24 pieces of work before this BOQ existed. I matched 21 to their lines by name and unit. Press "Add all suggested".',
      say: 'Your turn. The site sent twenty four pieces of work before this B O Q existed. I matched twenty one of them to their lines. Press, add all suggested.',
      for: { basics: { text: 'Before the BOQ was in, the site already reported work on WhatsApp ("15 sqm partition walls"). I found the line each one belongs to. Press "Add all suggested" and each line shows how far the site has got.' } },
    },
    {
      page: '/boq', target: 'boq.pick', mood: 'think',
      try: { kind: 'here', poll: true, check: WORK_LEFT(0) },
      title: 'Your turn: which plastering?',
      text: 'The site said "plastering" three days running: the Main block\'s ground floor, inside. The BOQ has three plastering lines, so I did not guess. Pick 4.1 Plastering for each and press "Add to line".',
      say: 'Your turn. The site said plastering, three days running. That is the Main block, inside, on the ground floor. But the B O Q has three plastering lines, so I did not guess. For each one, pick the inside plastering, line four point one, and press add to line.',
      for: { expert: { text: 'Three plastering lines, so no suggestion. Pick 4.1 and Add to line, for all three.' } },
    },
    {
      page: '/boq', target: 'boq.lines', mood: 'think',
      ask: {
        answer: 'boq.loss',
        right: 'Yes: the staircase. ₹7,900 from the client for each cubic metre, ₹8,200 to build it. Every cubic metre loses ₹300.',
        wrong: 'Not that one. Look down the Margin column for red: it is the staircase.',
      },
      title: 'Quick check',
      text: 'The site\'s work is on its lines now. One line loses money on every unit it builds. Tap it.',
      say: 'Quick check. One line loses money on every unit it builds. Can you find it? Tap it.',
      for: { basics: { text: 'One line costs more to build than the client pays for it. Its margin is in red. Tap that line.' } },
    },
    {
      page: '/boq', target: 'boq.lines', mood: 'happy',
      title: 'Green Villa is set up',
      text: 'Dates, contract, BOQ, and the site\'s two weeks on Mesiri on their lines. The months before are on paper, so "Earned so far" counts from here. From now on every update from site counts by itself.',
      say: 'Green Villa is set up. The dates, the contract, the B O Q, and the site\'s two weeks on Mesiri, each on its line. The months before that are on paper, so earned so far counts from here. From now on, every update from site counts by itself.',
    },
  ],
}

// The guided project's story chapters (21 Nov 2026: "fill its gaps ... so through simulation itself everyone can
// easily learn"): each plays on its own story day of the 62-day plan (JOURNEY_CHAPTERS `day`), on Green Villa's real
// records, with the owner's own work as "Your turn" (approve the wages, the count, send the running bill). Built from
// the plan (application/learn/sample_plan.py): change a day there, change it here.
const gv = (id: string, title: string, about: string, steps: WalkStep[]): Walkthrough =>
  ({ id, kind: 'workflow', part: true, sandbox: true, title, about, minutes: minutesFor(steps.length), roles: STARTERS, steps })
const GV = 'Green Villa'

const GV_DAY = gv('gv-day', 'A day on site', "Monday at Green Villa, from Ravi's message to the evening report.", [
  { page: '/today', pick: GV, target: 'today.sites', title: 'Monday, day 2', text: "Ravi sent each site's day: who came, the work done, the material used. Nobody typed a register.", say: 'Monday, day two. Ravi has sent each site\'s day: who came, the work done, the material used. Nobody typed a register.', mood: 'hello' },
  { page: '/today', target: 'today.issues', title: 'What is stuck', text: 'Anything Ravi said is stuck stays open here until someone sorts it.', say: 'Anything Ravi said is stuck stays open here, until someone sorts it out.', mood: 'worry' },
  { page: '/site-log', title: 'Everything the site sent', text: 'Every update, entry and photo, by day and by site.', say: 'And every update, entry and photo is kept, by day and by site.', mood: 'look' },
  { page: '/reports', target: 'reports.list', title: 'The evening report', text: "Today's waits for 9 pm, when it is made from what the sites sent and goes to you and to Dr. Anand Krishnan. The days before are here, each as it went.", say: 'Today\'s report waits for nine in the evening. Then it is made from what the sites sent, and goes to you and to Doctor Anand Krishnan. The days before are here, each exactly as it went. Nobody sat and typed them.', mood: 'happy' },
  { page: '/today', title: 'Your turn: tell Mesiri', text: 'Type this into Tell Mesiri, the New box at the top. The card shows what Mesiri understood: look, then tap Cancel. The site sends the same on WhatsApp.', say: 'Your turn. Type this into Tell Mesiri, the New box at the top. Look at the card, then tap cancel. From site, Ravi sends the same on WhatsApp.', mood: 'send', try: { kind: 'whatsapp', say: '6 masons, 4 helpers. First-floor slab shuttering done. Cement ran out.', tools: ['record_attendance', 'record_work', 'report_issue'], save: false } },
])

const GV_MATERIAL = gv('gv-material', 'Cement runs short', "The Main block's cement, from Ravi's request to the lorry at the gate.", [
  { page: '/materials/requests', target: 'req.list', title: 'Friday, day 6', text: "On Monday the Main block ran out of cement. Ravi asked for it here; Anil raised it to the month's 200 bags.", say: 'Friday, day six. On Monday the Main block ran out of cement. Ravi asked for it, and Anil raised it to the month\'s two hundred bags.', mood: 'hello' },
  { page: '/materials?view=movements', title: 'First, the masons', text: 'Before ordering, Anil moved 40 bags from the Annex, so the masons did not stand idle.', say: 'Before anything was ordered, Anil moved forty bags across from the Annex, so the masons did not stand idle.', mood: 'think' },
  { page: '/procurement/quotations?tab=all', target: 'quotes.list', title: 'Three quotes', text: 'Malabar, Kerala Steels and Sri Hardwares quoted for the cement and the steel. Open the request for quotes to see them side by side.', say: 'Three suppliers quoted for the cement and the steel. Open the request for quotes, and see them side by side.', mood: 'look' },
  { page: '/procurement/orders', target: 'po.list', title: 'Cheapest per item', text: 'The split was cheaper than any one supplier: cement from Malabar at ₹400, steel from Kerala Steels at ₹66. Two orders.', say: 'Splitting it was cheaper than any one supplier. Cement from Malabar at four hundred, steel from Kerala Steels at sixty-six. Two orders.', mood: 'happy' },
  { page: '/procurement/pending', target: 'pending.list', title: 'The lorry came short', text: 'Malabar\'s lorry brought 190 bags against the 200 ordered. Ravi took what came: 10 are still to come, and the order says so.', say: 'Malabar\'s lorry brought a hundred and ninety bags, against two hundred ordered. Ravi took what came. Ten are still to come, and the order says so.', mood: 'worry' },
  { page: '/procurement/returns', target: 'returns.list', title: 'Six torn bags', text: 'Six bags were torn. They went back on a return note, and Malabar owes for them until it is settled.', say: 'Six of the bags were torn. They went back on a return note, and Malabar owes for them until it is settled.', mood: 'think' },
  { page: '/materials?view=stock', title: 'Back above the line', text: "The Main block's cement is back: the 40 moved and what the gate kept. Every bag is accounted for.", say: 'And the Main block has cement again: the forty moved, and what the gate kept. Every bag accounted for.', mood: 'happy' },
])

const GV_WAGES = gv('gv-wages', 'Wages week', "Saturday at Green Villa: the week's wage sheet, approved by you, paid by Meera.", [
  { page: '/labour?view=muster', title: 'Saturday, day 7', text: "Pay day. The muster roll filled itself from Ravi's attendance all week: who came, who did not.", say: 'Saturday, day seven. Pay day. The muster roll filled itself from Ravi\'s attendance all week: who came, and who didn\'t.', mood: 'hello' },
  { page: '/labour/advances', target: 'advances.list', title: 'An advance on Wednesday', text: 'Meera gave Suresh ₹2,000 on Wednesday. It comes off his wages today by itself.', say: 'On Wednesday, Meera gave Suresh two thousand rupees. It comes off his wages today, by itself.', mood: 'think' },
  { page: '/labour/wages', target: 'wages.stats', title: 'The wage sheet made itself', text: "Each person's days at their daily wage, the crew as one line, the advance taken back: what is to pay.", say: 'The wage sheet made itself. Each person\'s days at their daily wage, Rahim\'s crew as one line, the advance taken back. And what is left to pay.', mood: 'look' },
  { page: '/labour/wages', target: 'wages.approve', title: 'Your turn: approve it', text: 'Nothing is paid until you approve. Check the sheet, then press Approve.', say: 'Your turn. Nothing is paid until you approve it. Check the sheet, then press approve.', mood: 'send', try: { kind: 'here', poll: true, check: { path: '/labour/wage-sheets/open', params: { project_id: '{project}' }, has: { status: 'approved' } } } },
  { page: '/labour/wages', target: 'wages.pay', title: 'Meera pays it', text: 'Approved, it is Meera\'s: she pays it from the bank or the site\'s cash, and each person gets a slip.', say: 'Once approved, it\'s Meera\'s. She pays it from the bank or the site\'s cash, and each person gets a slip.', mood: 'happy' },
])

const GV_PROBLEMS = gv('gv-problems', 'Problems and machines', "The Annex mixer breaks down: the problem, the task, and the hire bill checked.", [
  { page: '/issues', target: 'issues.list', title: 'The mixer stopped', text: "On Thursday the Annex's hired mixer burnt out its motor mid-morning. Ravi said so, and it stayed open here until it was fixed.", say: 'On Thursday, the Annex\'s hired mixer burnt out its motor, mid-morning. Ravi said so, and it stayed open here until it was fixed.', mood: 'worry' },
  { page: '/tasks?view=all', target: 'tasks.list', title: 'A task, with a time', text: "Anil gave Ravi a task: get the hire company's mechanic there before 8 the next morning. Done, it closed.", say: 'Anil gave Ravi a task: get the mechanic there before eight the next morning. When it was done, it closed.', mood: 'think' },
  { page: '/equipment/log', title: "Each machine's day", text: 'Ravi logs the mixer\'s hours every day: worked, idle, broken down.', say: 'Ravi logs the mixer\'s hours every day: worked, idle, and broken down.', mood: 'look' },
  { page: '/equipment/hire', target: 'hire.list', title: 'The hire bill, checked', text: 'The hire company billed more hours than the site logged. Anil had it corrected to the hours logged before anyone paid.', say: 'The hire company billed more hours than the site logged. Anil had it corrected, to the hours logged, before anyone paid.', mood: 'happy' },
])

const GV_MONEY_OUT = gv('gv-money-out', 'Money out', "Malabar's bill at ₹410, taken back; the corrected bill; the return settled.", [
  { page: '/finance/vendors', target: 'vendors.list', title: 'The bill came at ₹410', text: 'Malabar billed 190 bags at ₹410, against the order at ₹400 and the 184 kept. Mesiri set it beside the order and the gate.', say: 'Malabar\'s bill came at four hundred and ten a bag, for a hundred and ninety bags. Against an order at four hundred, and a hundred and eighty-four kept. Mesiri set it beside the order and the gate.', mood: 'worry' },
  { page: '/finance/vendors', target: 'vendors.list', title: 'Your turn: open Malabar', text: 'Meera took that bill back and asked for a corrected one. Open Malabar Cements Agency in this list to see what is owed now.', say: 'Meera took that bill back, and asked for a corrected one. Open Malabar Cements Agency in this list, and see what is owed now.', mood: 'send' },
  { title: 'Taken back, corrected', text: "Bills to pay shows the corrected bill, MCA/INV/2611-R: 184 bags at ₹400. The one at ₹410 is gone; Returns shows the six bags, settled against it.", say: 'Bills to pay shows the corrected bill: a hundred and eighty-four bags at four hundred. The one at four hundred and ten is gone. And returns shows the six bags, settled against it.', mood: 'happy' },
  { page: '/finance/expenses', title: 'Every rupee out', text: 'Bills, petty cash, the hire: every rupee out is here, against its project and site.', say: 'And every rupee out is here: bills, petty cash, the hire. Each against its project and site.', mood: 'look' },
])

const GV_COUNT = gv('gv-count', 'The store counted', "Ravi counts the Main block's store; three bags short; you approve it.", [
  { page: '/materials/counts', target: 'counts.list', title: 'Monday, day 16', text: "Ravi counted the Main block's store bag by bag. Mesiri put it beside the book: what came, less what was used and sent back.", say: 'Monday, day sixteen. Ravi counted the Main block\'s store, bag by bag. Mesiri put it beside the book: what came, less what was used, and what went back.', mood: 'hello' },
  { page: '/materials/counts', target: 'counts.sheet', title: 'Your turn: approve the count', text: 'Three bags of cement short: wastage, Ravi says. Open the count and press Approve differences, so the book is the store again.', say: 'Three bags of cement short. Wastage, Ravi says. Your turn: open the count, and press approve differences, so the book is the store again.', mood: 'send', try: { kind: 'here', poll: true, check: { path: '/materials/stock-counts', params: { status: 'approved' } } } },
])

const GV_BILLING = gv('gv-billing', 'Billing the client', "Green Villa's running bill: the work done at the BOQ rates, less retention and the advance.", [
  { page: '/billing/ra-bills', pick: GV, target: 'ra.terms', title: 'Day 30: a month of work', text: "The contract's terms are already here: retention 5%, the advance taken back 10% a bill, GST 18%.", say: 'Day thirty: a month of work. The contract\'s terms are already here: five percent retention, the advance taken back at ten percent a bill, and G S T.', mood: 'hello' },
  { page: '/billing/ra-bills', target: 'ra.new', title: 'Your turn: the running bill', text: 'Press New RA bill. Mesiri drafts it from the work measured so far, at the BOQ rates, less retention and the advance.', say: 'Your turn. Press new R A bill. Mesiri drafts it from the work measured so far, at your B O Q rates, less retention and the advance.', mood: 'send', try: { kind: 'here', poll: true, check: { path: '/billing/ra-bills', params: { project_id: '{project}' }, has: { 'first.status': 'draft' } } } },
  { page: '/billing/ra-bills', target: 'ra.submit', title: 'Your turn: send it', text: 'Read the bill: each line\'s work this month at its rate, then what comes off. Right? Press Submit: it goes to Dr. Anand Krishnan.', say: 'Read it: each line\'s work this month at its rate, then what comes off. If it is right, press submit. It goes to Doctor Anand Krishnan.', mood: 'send', try: { kind: 'here', poll: true, check: { path: '/billing/ra-bills', params: { project_id: '{project}' }, has: { 'first.status': 'submitted' } } } },
  { page: '/accounts/receivables', target: 'recv.clients', title: 'What the client owes', text: 'Sent, it is owed: by the bill, how old it is, and what came in against it.', say: 'Once it\'s sent, it\'s owed. By bill, how old it is, and what has come in against it.', mood: 'look' },
])

const GV_COST = gv('gv-cost', 'Is it making money?', 'Green / red on a month of real work: which lines earn their labour, which do not.', [
  { page: '/cost/green-red', pick: GV, target: 'gr.lines', title: 'Line by line', text: 'Each BOQ line: the labour its work earned at the BOQ rate, against the labour that went on it. Green earns it; red costs more.', say: 'Line by line. The labour each line\'s work earned at the B O Q rate, against the labour that went on it. Green earns it. Red costs more.', mood: 'think' },
  { page: '/cost/budget', target: 'budget.kinds', title: 'Budget against spent', text: 'For labour, material and subcontract: the budget, what the work earned, and what was spent.', say: 'For labour, material and subcontract: the budget, what the work has earned, and what was spent.', mood: 'look' },
  { page: '/cost/budget', target: 'budget.labour', title: 'Labour on its lines', text: 'A day of labour no line can be told for waits here, with the line Mesiri suggests. One tap puts the suggestions on.', say: 'A day of labour that no line can be told for waits here, with the line Mesiri suggests. One tap puts them on.', mood: 'happy' },
])

const GV_SUB = gv('gv-sub', 'A subcontractor', "Joy's tiling: measured with him, a bill turned down, the right one approved.", [
  { page: '/subcontract/work-orders', target: 'wo.list', title: "Joy's work order", text: 'Joy Tiling Works lays the tiles at an agreed rate a square metre. Everything after is checked against it.', say: 'Joy Tiling Works lays the tiles, at an agreed rate a square metre. Everything after is checked against it.', mood: 'hello' },
  { page: '/subcontract/bills', target: 'bills.list', title: 'Billed 92, measured 81.88', text: 'Joy billed 92 sqm. Anil measured the finished ground floor with him: 81.88. The bill was turned down with why, and the right one came the next day.', say: 'Joy billed ninety-two square metres. Anil measured the finished ground floor with him: eighty-one point eight eight. That bill was turned down, with why, and the right one came the next day.', mood: 'worry' },
])

const GV_MONTH = gv('gv-month', 'Month end', "The month's report, the books, and the Tally file.", [
  { page: '/reports/period', target: 'period.kpis', title: "The month's report", text: 'Work, labour, material and money for the month, per project, made from what was recorded.', say: 'The month\'s report: work, labour, material and money, per project, made from what was recorded.', mood: 'hello' },
  { page: '/accounts/periods', target: 'periods.months', title: 'The books kept themselves', text: 'Every bill, payment, delivery and wage went into the books when it was recorded. Close the month when it is checked.', say: 'Every bill, payment, delivery and wage went into the books as it was recorded. Close the month once it\'s checked.', mood: 'look' },
  { page: '/accounts/tally', target: 'tally.download', title: 'For your accountant', text: 'The month for Tally in one file, so nobody types it in again.', say: 'And the month for Tally, in one file, so nobody types it in again.', mood: 'happy' },
])

const GV_COMPANY = gv('gv-company', 'All your projects', 'Green Villa and Lake View side by side: which earns, which does not, and the profit and loss.', [
  { page: '/cost', allProjects: true, target: 'cost.projects', title: 'Two projects at once', text: 'Green Villa is finishing; Lake View is going up. Every project here, the worst first: where it will end, done against spent, and the last 7 days.', say: 'You never run one project. Green Villa is finishing, and Lake View is going up. Here is every project, the worst first: where it will end, what is done against what is spent, and the last week.', mood: 'hello' },
  { page: '/accounts/projects', allProjects: true, target: 'proj.list', title: 'Each project\'s profit', text: 'Project P&L: what each project billed, what it cost, and what it made, from the books.', say: 'Project P and L. What each project billed, what it cost, and what it made, straight from the books.', mood: 'look' },
  { page: '/accounts/pl', allProjects: true, target: 'pl.statement', title: 'The company\'s profit and loss', text: 'All projects and the office together: income, costs, and what is left.', say: 'And the whole company: every project and the office together. Income, costs, and what is left.', mood: 'think' },
])

const GV_HANDOVER = gv('gv-handover', 'Handover, to closed', 'The final bill, the handover, the defects period, and the project closed.', [
  { page: '/billing/ra-bills', pick: GV, target: 'ra.list', title: 'Friday, day 62', text: 'The snag list is closed and the last room is painted. Now the final bill: all the work, measured, at the BOQ rates.', say: 'Friday, day sixty-two. The snag list is closed, and the last room is painted. Now the final bill: all the work, measured, at your B O Q rates.', mood: 'hello' },
  { page: '/billing/ra-bills', target: 'ra.new', title: 'Your turn: the final bill', text: 'Press New RA bill: everything not billed yet goes on it.', say: 'Your turn. Press new R A bill. Everything not billed yet goes on it.', mood: 'send', try: { kind: 'here', poll: true, check: { path: '/billing/ra-bills', params: { project_id: '{project}' }, has: { 'first.status': 'draft' } } } },
  { page: '/billing/ra-bills', target: 'ra.submit', title: 'Your turn: send it', text: 'Check it, then press Submit.', say: 'Check it, then press submit.', mood: 'send', try: { kind: 'here', poll: true, check: { path: '/billing/ra-bills', params: { project_id: '{project}' }, has: { 'first.status': 'submitted' } } } },
  { page: '/planning/setup', target: 'setup.stage', title: 'Your turn: hand it over', text: 'The keys go to Dr. Anand Krishnan today. Press Handover on the stage line.', say: 'The keys go to Doctor Anand Krishnan today. Your turn: press handover, on the stage line.', mood: 'send', try: { kind: 'here', poll: true, check: { path: '/projects/{project}/start', has: { 'project.stage': 'handover' } } } },
  { page: '/planning/setup', target: 'setup.stage', title: 'Your turn: the defects period', text: 'For 12 months anything that fails is yours to fix, and 5% of every bill stays with the client until it ends. Press Defect period.', say: 'For twelve months, anything that fails is yours to fix, and five percent of every bill stays with the client until then. Press defect period.', mood: 'think', try: { kind: 'here', poll: true, check: { path: '/projects/{project}/start', has: { 'project.stage': 'defects' } } } },
  { page: '/planning/setup', target: 'setup.stage', title: 'Your turn: close it', text: 'A year on (here, a tap): the defects are fixed and the retention comes back. Press Closed: Green Villa is done.', say: 'A year on, here just a tap: the defects are fixed, and the retention comes back. Press closed. Green Villa is done.', mood: 'happy', try: { kind: 'here', poll: true, check: { path: '/projects/{project}/start', has: { 'project.stage': 'closed' } } } },
])

const made: Walkthrough[] = [...WORKFLOWS, ...MODULE_WALKS, ...PAGE_WALKS, GV_SETUP, GV_BOQ, GV_DAY, GV_MATERIAL, GV_WAGES, GV_PROBLEMS, GV_MONEY_OUT, GV_COUNT, GV_BILLING, GV_COST, GV_SUB, GV_MONTH, GV_COMPANY, GV_HANDOVER]

/** A walkthrough made of others, one after another (W2 = asking + ordering + delivery). An id that is not a
 *  walkthrough fails the build (vite.config.ts), so it is never silently left out here. */
function composed(id: string, title: string, about: string, ids: string[], kind: WalkKind = 'workflow', roles?: readonly string[]): Walkthrough {
  const parts = ids.map((x) => made.find((w) => w.id === x)).filter((w): w is Walkthrough => !!w)
  const walk = { id, kind, title, about, roles, minutes: parts.reduce((n, w) => n + w.minutes, 0), steps: parts.flatMap((w) => w.steps) }
  made.push(walk)
  return walk
}

/** The full workflows (plan section 5.2) made of the parts above. W3, W5..W11 (SS-48) are whole in WORKFLOWS. */
export const FULL_WORKFLOWS: Walkthrough[] = [
  composed('site-to-report', 'Site update to daily report', "The site's day in one WhatsApp message, then everything it fills, up to the report that goes out.", ['site-update', 'daily-report']),
  composed('material', 'Material, from asking to using', 'The site asks, the office orders, it arrives and is used: every step, and how to take each back.', ['material-request', 'material-order', 'delivery']),
  composed('labour-to-wages', 'Labour to wages', 'Attendance from site, the muster roll, the wage sheet, and advances.', ['attendance', 'wages']),
]

/** What a role gets out of Mesiri, in their words (asked 15 Nov in session: "a list of things the owner finds valuable,
 *  that is the title, and how to get it"). Each points at walkthroughs that already exist, so nothing is written
 *  twice; the build fails when one points at a walkthrough that doesn't (vite.config.ts). */
export interface Outcome {
  id: string
  title: string
  why: string
  roles: readonly string[]
  walks: string[]
}

const OWNERS = ['ADMIN', 'OWNER', 'SUPER_ADMIN'] as const
const ENGINEERS = ['SITE_ENGINEER'] as const
const MANAGERS = ['PROJECT_MANAGER'] as const
const FINANCE = ['FINANCE'] as const

export const OUTCOMES: Outcome[] = [
  // The owner (SS-43 draft, 15 Nov; SS-48 points cost, start and problems at W9, W6, W7 and adds W8, W11).
  { id: 'know-every-site', roles: OWNERS, title: "Know every site's day without a phone call", why: 'Your engineers send one WhatsApp message; you get the daily report every evening.', walks: ['site-to-report'] },
  { id: 'see-material', roles: OWNERS, title: 'See where every bag of cement goes', why: 'From the site asking to the material being used: nothing bought twice, nothing gone missing.', walks: ['material'] },
  { id: 'wages-right', roles: OWNERS, title: 'Pay wages right, with no arguments', why: 'Attendance from site becomes the wage sheet, and advances come off by themselves.', walks: ['labour-to-wages'] },
  { id: 'cost-early', roles: OWNERS, title: 'Catch a cost overrun before the bill comes', why: 'Each BOQ line shows what it earned against what it cost, and material is planned before it runs short.', walks: ['cost-control', 'page-planning-materials'] },
  { id: 'start-project', roles: OWNERS, title: 'Start a new project in an afternoon', why: 'Your estimate Excel becomes the BOQ and the schedule; add the site team and they start sending.', walks: ['new-project'] },
  { id: 'hear-problems', roles: OWNERS, title: 'Hear about problems the day they happen', why: 'Hold-ups from site wait in one list until someone acts on them.', walks: ['issue'] },
  { id: 'paid-faster', roles: OWNERS, title: 'Get paid faster by the client', why: 'Running bills from the work site already sent, and what the client still owes, always up to date.', walks: ['billing'] },
  { id: 'month-end', roles: OWNERS, title: 'Month end without chasing the accountant', why: 'The books keep themselves from what is recorded; the month goes to Tally in one file.', walks: ['month-end'] },
  // The site engineer: mostly WhatsApp (plan 5.1).
  { id: 'day-in-one-message', roles: ENGINEERS, title: "Send the day's update in one message", why: 'Who came, what was done, what is stuck: one message, and the daily report writes itself.', walks: ['site-update'] },
  { id: 'material-on-time', roles: ENGINEERS, title: 'Get material on site on time', why: 'Ask on WhatsApp, then record it when it comes and when it is used.', walks: ['material-request', 'delivery'] },
  { id: 'attendance-one-line', roles: ENGINEERS, title: 'Mark attendance in one line', why: '"Rahim\'s crew: 4 helpers, 2 masons", and the muster roll fills itself.', walks: ['attendance'] },
  { id: 'problem-fixed', roles: ENGINEERS, title: 'Report a problem and get it fixed', why: 'Say what is wrong; it stays open until someone acts on it.', walks: ['issue'] },
  // The project manager (SS-48; plan 5.1: W6, W1, W2, W5, W9).
  { id: 'pm-start', roles: MANAGERS, title: 'Get a new project going', why: 'BOQ, schedule and site team set up, and the first report the same week.', walks: ['new-project'] },
  { id: 'pm-daily', roles: MANAGERS, title: "Review every site's day in minutes", why: 'One message from each site becomes its day and the daily report.', walks: ['site-to-report'] },
  { id: 'pm-material', roles: MANAGERS, title: 'Keep material arriving before it is needed', why: 'Requests from site, orders, what is still to come, and what was used.', walks: ['material'] },
  { id: 'pm-subcontract', roles: MANAGERS, title: 'Pay subcontractors for measured work only', why: 'Work orders at agreed rates, and each bill checked against what was measured.', walks: ['subcontract'] },
  { id: 'pm-cost', roles: MANAGERS, title: 'Know which work is losing money', why: 'Each BOQ line, green or red, every day.', walks: ['cost-control'] },
  // Accounts / finance (SS-48; plan 5.1: W3, W4 wages, W8, W11).
  { id: 'fin-bills', roles: FINANCE, title: 'Pay suppliers for what actually came', why: 'Bills matched to deliveries, and what you owe each supplier, by age.', walks: ['supplier-bill'] },
  { id: 'fin-wages', roles: FINANCE, title: 'Pay wages straight from attendance', why: 'The wage sheet comes from attendance, less advances.', walks: ['wages'] },
  { id: 'fin-billing', roles: FINANCE, title: 'Bill the client and see what they owe', why: 'Running bills and client payments in one place.', walks: ['billing'] },
  { id: 'fin-month', roles: FINANCE, title: 'Close the month and hand it to Tally', why: 'The books are already kept; check, close, export.', walks: ['month-end'] },
]

export const OUTCOME_WALKS: Walkthrough[] = OUTCOMES.map((o) => composed(`goal-${o.id}`, o.title, o.why, o.walks, 'outcome', o.roles))

/** Role paths: a role's outcomes in order, as one walkthrough (plan section 5.1). */
export const ROLE_PATHS: Walkthrough[] = [
  composed('path-owner', 'Everything an owner gets, in order', 'All of the above, one after another.', OUTCOMES.filter((o) => o.roles === OWNERS).map((o) => `goal-${o.id}`), 'role', OWNERS),
  composed('path-site-engineer', 'Everything a site engineer does, in order', 'All of the above, one after another.', OUTCOMES.filter((o) => o.roles === ENGINEERS).map((o) => `goal-${o.id}`), 'role', ENGINEERS),
  composed('path-project-manager', 'Everything a project manager does, in order', 'All of the above, one after another.', OUTCOMES.filter((o) => o.roles === MANAGERS).map((o) => `goal-${o.id}`), 'role', MANAGERS),
  composed('path-finance', 'Everything accounts does, in order', 'All of the above, one after another.', OUTCOMES.filter((o) => o.roles === FINANCE).map((o) => `goal-${o.id}`), 'role', FINANCE),
]

/** The guided project, Green Villa from won to closed, in the person's sample company (guided-demo-plan.md section 3).
 *  Each chapter names the walkthroughs it runs; the bubble lists the chapters and jumps between them. Until the
 *  chapters' own walkthroughs are written (SS-69..SS-71) a chapter runs the workflow that already covers it, so the
 *  journey works end to end from day one; a chapter with nothing to run yet (handover and closing) is left out. */
/** `film`: the film episode watched before the chapter (docs/learning/LEARNING_PATH.md), named on its card (21 Nov:
 *  "Chapter 4" and "Episode 3" are the same day on site). */
export const JOURNEY_CHAPTERS: { title: string; walks: string[]; film?: string; day?: number }[] = [
  { title: 'Your sample company', walks: [], film: 'Prologue' },
  // SS-69 part 1 (17 Nov: "our focus is till BOQ, the role play working"): the person does it, Mesiri checks it.
  { title: 'Set up Green Villa', walks: ['gv-setup'], film: 'Episode 1' },
  { title: 'The BOQ', walks: ['gv-boq'], film: 'Episode 1' },
  // 21 Nov: each chapter on its own story day (the 62-day plan), in the order the days come.
  { title: 'A day on site', walks: ['gv-day'], film: 'Episode 3', day: 2 },
  { title: 'Cement runs short', walks: ['gv-material'], film: 'Episode 4', day: 6 },
  { title: 'Wages week', walks: ['gv-wages'], film: 'Episode 5', day: 7 },
  { title: 'Problems and machines', walks: ['gv-problems'], film: 'Episode 6', day: 9 },
  { title: 'Money out', walks: ['gv-money-out'], film: 'Episode 4', day: 10 },
  { title: 'The store counted', walks: ['gv-count'], film: 'Episode 4', day: 16 },
  { title: 'Billing the client', walks: ['gv-billing'], film: 'Episode 8', day: 30 },
  { title: 'Is it making money?', walks: ['gv-cost'], film: 'Episode 9', day: 31 },
  { title: 'A subcontractor', walks: ['gv-sub'], film: 'Episode 7', day: 39 },
  { title: 'Month end', walks: ['gv-month'], film: 'Episode 10', day: 40 },
  { title: 'All your projects', walks: ['gv-company'], film: 'Episode 9', day: 40 },
  { title: 'Handover, to closed', walks: ['gv-handover'], film: 'Episode 11', day: 62 },
]

/** Chapter 0: where the person is, said before anything else (the plan's "Your sample company"). */
const JOURNEY_HELLO: WalkStep[] = [
  {
    page: '/today',
    mood: 'hello',
    title: 'Welcome to Green Villa Builders',
    text: 'This is your own sample company: two projects and two weeks of site work, already recorded. Nothing here is real and nobody gets a message, so try anything.',
    say: 'Welcome to Green Villa Builders. This is your own sample company, with two projects and two weeks of site work already recorded. Nothing here is real, and nobody gets a message. So go ahead and try anything.',
  },
  {
    page: '/today',
    mood: 'look',
    title: 'Green Villa, to the handover',
    text: 'We follow Green Villa through its last two months: set up on Mesiri, a day on site, material, wages, bills and money, to the handover. Jump to any chapter from the list in this box.',
    say: 'We will follow Green Villa through its last two months. Set up on Mesiri, a day on site, material, wages, bills and money, all the way to the handover. You can jump to any chapter from the list in this box.',
  },
]

function journey(id: string, title: string, about: string, chapters: { title: string; walks: string[]; day?: number }[]): Walkthrough {
  const steps = chapters.flatMap((c, i) => {
    const own = i === 0 ? JOURNEY_HELLO : c.walks.flatMap((x) => made.find((w) => w.id === x)?.steps ?? [])
    return own.map((s) => ({ ...s, chapter: c.title, ...(c.day ? { day: c.day } : {}) }))
  })
  return { id, kind: 'workflow', title, about, roles: STARTERS, sandbox: true, minutes: minutesFor(steps.length), steps }
}

export const JOURNEY: Walkthrough = journey(
  'guided-project',
  'A project from start to finish',
  'Green Villa, from won to billed, in your own sample company: watch each thing once, then do it yourself.',
  JOURNEY_CHAPTERS,
)

/** Where each chapter starts in these steps (the steps as the runner has them, after words per kind of person). */
export function chapterStarts(steps: WalkStep[]): { title: string; step: number }[] {
  const starts: { title: string; step: number }[] = []
  steps.forEach((s, i) => {
    if (s.chapter && s.chapter !== steps[i - 1]?.chapter) starts.push({ title: s.chapter, step: i })
  })
  return starts
}

export const ALL_WALKS: Walkthrough[] = [...ROLE_PATHS, ...OUTCOME_WALKS, ...FULL_WORKFLOWS, ...WORKFLOWS, ...MODULE_WALKS, ...PAGE_WALKS, JOURNEY]

/** SS-61: the walkthroughs that speak each step (English first; decided 16 Nov: W1, W2, W4 and the owner's path;
 *  then the BOQ page, asked 16 Nov). A page walkthrough's id (`page-boq`) also gives that page's own tour (first visit,
 *  Help's "Show me around") its voice. Give one its voice by adding its id here; the build fails on an id that
 *  doesn't exist. */
export const VOICED: ReadonlySet<string> = new Set(['site-to-report', 'material', 'labour-to-wages', 'path-owner', 'page-boq', 'guided-project'])

/** Site words written in capitals, spelled out so the voice says the letters ("B O Q", never "bok"). */
const SPELLED = /\b(BOQ|DPR|GRN|RA|PO|GST|TDS|PDF|CSV)s?\b/g

/** What the narrator says for a step: its own spoken words, or its title and text. */
export function spokenWords(step: TourStep): string {
  const words = step.say ?? `${step.title.replace(/[.!?:]$/, '')}. ${step.text}`
  return words
    .replace(/[“”"]/g, '')
    .replace(/\s*&\s*/g, ' and ')
    .replace(SPELLED, (word) => word.split('').join(' '))
    .replace(/\s+/g, ' ')
    .trim()
}

export function findWalkthrough(id: string): Walkthrough | undefined {
  return ALL_WALKS.find((w) => w.id === id)
}

/** May this role take it? Its roles allow it, and at least one step is on a page this role can open: the engine
 *  skips the others, so a walkthrough with none (the Accounts module for a site engineer) would run empty and is
 *  never offered (review 16 Nov). */
export function walkFor(walk: Walkthrough, role: string | null | undefined): boolean {
  if (walk.roles && !walk.roles.includes((role ?? '').toUpperCase())) return false
  return walk.steps.some((s) => !s.page || pageOpenFor(s.page, role))
}

/** Can this role open this page (module-map roles)? */
export function pageOpenFor(url: string, role: string | null | undefined): boolean {
  const [path, query = ''] = url.split('?')
  const roles = findPage(path, query ? `?${query}` : '')?.page.roles
  return !roles || roles.includes((role ?? '').toUpperCase())
}
