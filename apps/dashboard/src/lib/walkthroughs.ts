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
  /** An existing list route (GET), read before the practice and every few seconds after. */
  path: string
  params?: Record<string, string | number>
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
    if (t.kind === 'whatsapp' && t.save === false) return false
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
    about: 'Record a delivery on WhatsApp and here, see it in stock, and take it back.',
    minutes: 4,
    roles: RECORDERS,
    steps: [
      {
        page: '/materials?view=stock',
        title: "Let's record a delivery",
        text: "We'll record a real delivery the way your site would, see it land in stock, then take it back. Nothing stays behind.",
        mood: 'hello',
      },
      {
        page: '/materials?view=stock',
        target: 'materials.views',
        title: 'Stock and movements',
        text: 'Stock is what each site holds now. Movements is every delivery, use and move that changed it.',
      },
      {
        page: '/materials?view=movements',
        title: 'Send it on WhatsApp',
        text: "Send this to Mesiri, like a site engineer would. A card comes back: tap Save. I'll watch for it here.",
        mood: 'send',
        // No supplier named: a practice must not leave a new supplier behind after it is taken back.
        try: { kind: 'whatsapp', say: '10 bags cement came', tools: ['record_receipt'], check: INFLOWS },
      },
      {
        page: '/materials?view=movements',
        target: 'materials.list',
        showNew: true,
        title: 'There it is',
        text: 'The delivery is in Movements, and the stock went up by 10 bags. Your site never opened the dashboard.',
        mood: 'happy',
      },
      {
        page: '/materials?view=movements',
        title: 'Take it back',
        text: 'It was practice, so take it back the same way. Mesiri shows a card: tap Save.',
        takeBack: { roles: ADJUSTERS, say: 'Take back the 10 bags cement delivery', tools: ['undo_receipt'] },
      },
      {
        page: '/materials?view=movements',
        target: 'materials.in',
        title: 'Now from the office',
        text: 'Click Record delivery, fill in the material, the quantity and the site, and save. I will wait.',
        try: { kind: 'here', check: INFLOWS },
      },
      {
        page: '/materials?view=movements',
        target: 'materials.list',
        title: 'Take that one back too',
        text: 'Open the row you just saved and press Correct: it is reversed, and both lines stay in the history.',
        takeBack: { roles: ADJUSTERS, here: 'Open the row, then Correct (an admin or project manager).' },
      },
      {
        page: '/materials?view=movements',
        target: 'materials.out',
        title: 'Using it works the same',
        text: 'Material used on site is one message too: "Used 20 bags cement for the slab". Or Record use here.',
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
    about: 'Who came, what was done and what is stuck, sent on WhatsApp.',
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
        title: 'Try it: send the day',
        text: 'Send this to Mesiri. A card comes back with the people, the work and the issue it found. This is practice: look at the card, then tap Cancel, so nothing is saved.', say: 'Let\'s try it. Send this message to Mesiri. In a moment a card comes back, showing what Mesiri understood: the workers, the work, and the problem. It\'s only practice, so look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: '6 masons, 4 helpers. First-floor slab shuttering done. Cement ran out.', tools: ['record_attendance', 'record_work', 'report_issue'], save: false },
      },
      {
        page: '/today',
        title: 'On a real day, tap Save',
        text: "Then the site's day here shows it at once. A voice note or a photo of the work works the same way.", say: 'On a real day, Ravi taps Save, and it shows up here straight away. He doesn\'t even need to type. A voice note, or a photo of the work, does the same job.',
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
      { page: '/today', target: 'today.send', title: 'Or send it now', text: "When the day looks right, send it yourself. On WhatsApp: \"Send today's report\".", mood: 'send', say: 'If the day looks right and you don\'t want to wait for the evening, send it now. Ravi can do it from WhatsApp too. He just says: send today\'s report.' },
    ],
  },
  // W2's first part: the site asks for material.
  {
    id: 'material-request',
    kind: 'workflow',
    part: true,
    title: 'Asking for material',
    about: 'The site asks on WhatsApp, and the request waits for the office.',
    minutes: 2,
    roles: RECORDERS,
    steps: [
      {
        page: '/materials/requests',
        title: 'Asking for material',
        text: 'The site asks on WhatsApp. The request waits here until the office orders it, and the site can ask how it is going.',
        mood: 'hello',
      },
      {
        page: '/materials/requests',
        title: 'Try it: ask for cement',
        text: "Send this. If you have more than one site, Mesiri asks which. A card comes back: tap Save. I'll watch for the request here.",
        mood: 'send',
        try: { kind: 'whatsapp', say: 'Need 50 bags cement by Friday', tools: ['ask_for_material'], check: { path: '/procurement/requests', params: { status: 'open' } } },
      },
      {
        page: '/materials/requests',
        showNew: true,
        title: 'There it is',
        text: 'The request is in the list, waiting for the office. The site can ask on WhatsApp how it is going: "my requests".',
        mood: 'happy',
      },
      {
        page: '/materials/requests',
        title: 'Take it back',
        text: 'It was practice, so cancel it the same way. Mesiri shows a card: tap Save.',
        takeBack: { say: 'Cancel my cement request', tools: ['cancel_material_request'] },
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
        text: 'The office turns requests into purchase orders and sends them to the supplier, on WhatsApp or as a PDF. On WhatsApp: "Order 50 bags cement from Malabar at 380".',
      },
      { page: '/procurement/pending', title: 'What is still to come', text: 'Every order not yet delivered in full, so you know whom to chase.', mood: 'look' },
      {
        page: '/procurement/grn',
        title: 'When it arrives',
        text: "A delivery on an order is received on it (the GRN), so the order, the stock and the supplier's bill agree.",
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
    about: 'Who came, in one line on WhatsApp; the muster roll fills itself.',
    minutes: 1,
    roles: RECORDERS,
    steps: [
      { page: '/labour', title: 'Attendance from site', text: 'The site says who came. Attendance, the muster roll and the wages all follow from it.', mood: 'hello' },
      {
        page: '/labour',
        title: 'Try it: mark attendance',
        text: 'Send this. The card shows the team and how many came. This is practice: look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: 'Suresh team: 4 masons, 2 helpers', tools: ['record_attendance'], save: false },
      },
      { page: '/labour', target: 'labour.views', title: 'By day and by month', text: 'Attendance by day, and the muster roll for the month, fill from those messages.' },
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
        text: "The week's attendance at each worker's daily wage, less any advance. Approve it, then pay it. On WhatsApp: \"What do I pay Suresh's team this week?\".",
      },
      { page: '/labour/advances', title: 'Advances', text: 'Money given ahead is kept per person and comes off their next wages by itself.' },
      {
        page: '/labour/advances',
        title: 'Try it: an advance',
        text: 'Send this. The card shows who, how much and what they owe after it. This is practice: look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: 'Gave Ravi 500 advance', tools: ['give_labour_advance'], save: false },
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
        title: 'Try it: record an expense',
        text: "Send this to Mesiri (add a photo of the bill on a real day). If you have more than one site, Mesiri asks which. A card comes back: tap Save. I'll watch for it here.",
        mood: 'send',
        // No supplier named: a practice must not leave a new supplier behind after it is taken back.
        try: { kind: 'whatsapp', say: 'Paid 500 for drinking water', tools: ['record_expense'], check: { path: '/expenses' } },
      },
      { page: '/finance/expenses', showNew: true, title: 'There it is', text: 'The expense is in the list, and in the project\'s cost.', mood: 'happy' },
      {
        page: '/finance/expenses',
        title: 'Take it back',
        text: 'It was practice, so take it back the same way. Mesiri shows a card: tap Save.',
        takeBack: { roles: MONEY_MANAGERS, say: 'Take back the drinking water expense', tools: ['undo_expense'] },
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
        text: 'Open a supplier to pay a bill. On WhatsApp: "Paid Malabar 50,000 by UPI", and "How much do we owe Malabar?".',
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
        title: 'Try it: a work order',
        text: 'Send this. The card shows the work, the quantity and the rate. This is practice: look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: 'Work order to Sree tiles: floor tiling 2,400 sq ft at 38', tools: ['create_work_order'], save: false },
      },
      {
        page: '/subcontract/work-orders',
        title: 'Measure the work',
        text: 'Each week site says how much was done: "Sree tiles did 600 sq ft this week". That is what the bill is checked against.',
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
        text: 'Project start lists every step from "won" to "work starts", and ticks each one as it is done.',
        mood: 'hello',
      },
      {
        page: '/planning/setup',
        title: 'Try it: a new project',
        text: 'Send this. The card shows the project, the client, the place and the start date. This is practice: look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: 'New project Lake View for Mr Thomas at Kakkanad, starts 1 Dec', tools: ['create_project'], save: false },
      },
      { page: '/planning/setup', target: 'setup.steps', title: 'Steps to "work starts"', text: 'Dates, contract, BOQ, schedule, sites, the site team, suppliers.', mood: 'think' },
      { page: '/boq', target: 'boq.import', title: 'The BOQ from your Excel', text: 'Upload the estimate you already have: its items, units, quantities and rates become the BOQ.' },
      { page: '/planning/schedule', target: 'schedule.add', title: 'The schedule from the BOQ', text: 'Each BOQ section becomes a bar; Quick plan puts them one after another.' },
      {
        page: '/team',
        target: 'team.add',
        title: 'The site team',
        text: 'Add the engineer by their WhatsApp number. On WhatsApp: "Add Ravi 98470 12345 as site engineer on Lake View". This is practice: look at the card, then tap Cancel.',
        try: { kind: 'whatsapp', say: 'Add Ravi 98470 12345 as site engineer on Lake View', tools: ['add_person'], save: false },
      },
      { page: '/reports', target: 'reports.list', title: 'The first report', text: 'From their first message, the daily report goes out every evening.', mood: 'happy' },
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
      { page: '/issues', title: 'Hold-ups from site', text: 'No water, a machine broken, a drawing missing: each stays open here until someone fixes it.', mood: 'hello' },
      {
        page: '/issues',
        title: 'Try it: report one',
        text: 'Send this. The card shows the problem and the site. This is practice: look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: 'No water since morning at the compound wall', tools: ['report_issue'], save: false },
      },
      { page: '/issues', target: 'issues.list', title: 'Open until fixed', text: 'The oldest first. Open one to say it is seen, then fixed, or that it will not be fixed and why.', mood: 'think' },
      { page: '/issues', target: 'issues.stats', title: 'At a glance', text: 'How many are open, and how long they have waited.', mood: 'look' },
      { page: '/issues', title: 'Closing it from site', text: 'When it is sorted, site says "Water is back at the compound wall" and it closes.', mood: 'happy' },
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
      { page: '/billing/ra-bills', title: 'Running bills', text: 'Each RA bill is the work done since the last one at the BOQ rates, less retention and advance.', mood: 'hello' },
      { page: '/accounts/receivables', title: 'What the client owes', text: 'Every bill, what was paid against it, and how old the rest is.', mood: 'look' },
      {
        page: '/accounts/receivables',
        title: 'Try it: the client paid',
        text: 'Send this. The card shows the payment and the bill it goes against. This is practice: look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: 'Client paid 5 lakh for RA-03', tools: ['record_client_receipt'], save: false },
      },
      { page: '/accounts/receivables', title: 'Ask any time', text: 'On WhatsApp: "What does the client still owe on Green Villa?"', mood: 'happy' },
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
      { page: '/boq', target: 'boq.lines', title: 'It starts with the BOQ', text: 'Each line\'s rate is the budget; the work site sends earns against it.', mood: 'hello' },
      { page: '/cost', target: 'cost.projects', title: 'Every project, worst first', text: 'Its forecast at completion, done against spent, and the last 7 days.', mood: 'look' },
      { page: '/cost/green-red', target: 'gr.lines', title: 'Labour, line by line', text: 'Green: the work earned its labour. Red: it cost more. Worst first, with why.', mood: 'think' },
      { page: '/cost/budget', target: 'budget.kinds', title: 'Budget against spent', text: 'For labour, material and subcontract: the budget, what the work earned, and what was spent.' },
      { page: '/cost/materials', title: 'Material against the BOQ', text: 'What the work needed by the BOQ against what was used, and what is short to finish.', mood: 'worry' },
      { page: '/cost', title: 'Ask on WhatsApp', text: '"How is Green Villa doing on cost?" or "Which work is over on labour this week?"', mood: 'happy' },
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
      { page: '/equipment/log', title: "Each machine's day", text: 'Hours worked, idle and broken down, and the diesel, from one message from site.', mood: 'hello' },
      {
        page: '/equipment/log',
        title: 'Try it: log the machines',
        text: 'Send this. The card shows each machine and its hours. This is practice: look at the card, then tap Cancel.',
        mood: 'send',
        try: { kind: 'whatsapp', say: 'Mixer 8 hrs, roller broke down 3 hrs', tools: ['log_machines'], save: false },
      },
      { page: '/equipment/hire', title: 'The hire bill, checked', text: 'The hours the owner billed against the hours site logged, so you pay for what was worked.', mood: 'think' },
      { page: '/equipment/hire', title: 'Ask on WhatsApp', text: '"Does the JCB bill match our hours?"', mood: 'happy' },
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
      { page: '/reports/period', title: "The month's report", text: 'Work, labour, material and money for the week or the month, per project. On WhatsApp: "Send me October\'s report for Green Villa".', mood: 'hello' },
      { page: '/accounts', title: 'The books keep themselves', text: 'Every bill, payment, delivery and wage recorded on WhatsApp or here is already in the books.', mood: 'look' },
      { page: '/accounts/periods', title: 'Close the month', text: 'Once the month is checked, close it: nothing in it can change without opening it again.', mood: 'think' },
      { page: '/accounts/tally', title: 'For your accountant', text: 'The month for Tally in one file, so nobody types it in again.', mood: 'happy' },
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
  const intro: WalkStep[] = tour.introFromPage ? [{ title: page.title, text: page.about, mood: 'hello', say: tour.introSay }] : []
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
const made: Walkthrough[] = [...WORKFLOWS, ...MODULE_WALKS, ...PAGE_WALKS]

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
  { id: 'attendance-one-line', roles: ENGINEERS, title: 'Mark attendance in one line', why: '"Suresh team: 4 masons, 2 helpers", and the muster roll fills itself.', walks: ['attendance'] },
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

export const ALL_WALKS: Walkthrough[] = [...ROLE_PATHS, ...OUTCOME_WALKS, ...FULL_WORKFLOWS, ...WORKFLOWS, ...MODULE_WALKS, ...PAGE_WALKS]

/** SS-61: the walkthroughs that speak each step (English first; decided 16 Nov: W1, W2, W4 and the owner's path;
 *  then the BOQ page, asked 16 Nov). A page walkthrough's id (`page-boq`) also gives that page's own tour (first visit,
 *  Help's "Show me around") its voice. Give one its voice by adding its id here; the build fails on an id that
 *  doesn't exist. */
export const VOICED: ReadonlySet<string> = new Set(['site-to-report', 'material', 'labour-to-wages', 'path-owner', 'page-boq'])

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
