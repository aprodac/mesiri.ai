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

export function learnKey(id: string): string {
  return `/learn/${id}`
}

const minutesFor = (steps: number) => Math.max(1, Math.round(steps * 0.4))

const RECORDERS = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER'] as const

// Newest first (by day, then saved time), so a delivery saved now is in the first page.
const INFLOWS: WalkCheck = { path: '/materials/inflows', params: { limit: 100 } }
/** Who may correct (take back) a stock movement: backend ADJUSTMENT_ROLES. */
const ADJUSTERS = ['ADMIN', 'PROJECT_MANAGER'] as const

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
        text: 'At the end of the day the site engineer sends one WhatsApp message. Mesiri turns it into attendance, work done and issues, and they show here.',
        mood: 'hello',
      },
      {
        page: '/today',
        title: 'Try it: send the day',
        text: 'Send this to Mesiri. A card comes back with the people, the work and the issue it found. This is practice: look at the card, then tap Cancel, so nothing is saved.',
        mood: 'send',
        try: { kind: 'whatsapp', say: '6 masons, 4 helpers. First-floor slab shuttering done. Cement ran out.', tools: ['record_attendance', 'record_work', 'report_issue'], save: false },
      },
      {
        page: '/today',
        title: 'On a real day, tap Save',
        text: "Then the site's day here shows it at once. A voice note or a photo of the work works the same way.",
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
      { page: '/today', target: 'today.sites', title: "Each site's day", text: 'Who came, what was done, what came in, and which sites have not reported yet.' },
      { page: '/site-log', title: 'Everything the sites sent', text: 'The Site log keeps every update, photo and entry, by day and by site.', mood: 'look' },
      { page: '/reports', target: 'reports.list', title: 'The daily report', text: 'Every evening each site gets its daily report (DPR), and it goes to the owner and the client.' },
      { page: '/reports', target: 'reports.pdf', title: 'Exactly as they got it', text: 'Open the PDF the owner and the client received.', mood: 'look' },
      { page: '/today', target: 'today.send', title: 'Or send it now', text: "When the day looks right, send it yourself. On WhatsApp: \"Send today's report\".", mood: 'send' },
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
  const intro: WalkStep[] = tour.introFromPage ? [{ title: page.title, text: page.about, mood: 'hello' }] : []
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

/** The full workflows (plan section 5.2), made of the parts above. SS-48 adds W3, W5..W11. */
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

export const OUTCOMES: Outcome[] = [
  // The owner (SS-43 draft, 15 Nov). SS-48 adds billing the client and month end once W8 and W11 are written.
  { id: 'know-every-site', roles: OWNERS, title: "Know every site's day without a phone call", why: 'Your engineers send one WhatsApp message; you get the daily report every evening.', walks: ['site-to-report'] },
  { id: 'see-material', roles: OWNERS, title: 'See where every bag of cement goes', why: 'From the site asking to the material being used: nothing bought twice, nothing gone missing.', walks: ['material'] },
  { id: 'wages-right', roles: OWNERS, title: 'Pay wages right, with no arguments', why: 'Attendance from site becomes the wage sheet, and advances come off by themselves.', walks: ['labour-to-wages'] },
  { id: 'cost-early', roles: OWNERS, title: 'Catch a cost overrun before the bill comes', why: 'Each BOQ line shows what it earned against what it cost, and material is planned before it runs short.', walks: ['page-boq', 'page-planning-materials'] },
  { id: 'start-project', roles: OWNERS, title: 'Start a new project in an afternoon', why: 'Your estimate Excel becomes the BOQ and the schedule; add the site team and they start sending.', walks: ['page-planning-setup', 'page-planning-schedule', 'page-team'] },
  { id: 'hear-problems', roles: OWNERS, title: 'Hear about problems the day they happen', why: 'Hold-ups from site wait in one list until someone acts on them.', walks: ['page-issues'] },
  // The site engineer: mostly WhatsApp (plan 5.1).
  { id: 'day-in-one-message', roles: ENGINEERS, title: "Send the day's update in one message", why: 'Who came, what was done, what is stuck: one message, and the daily report writes itself.', walks: ['site-update'] },
  { id: 'material-on-time', roles: ENGINEERS, title: 'Get material on site on time', why: 'Ask on WhatsApp, then record it when it comes and when it is used.', walks: ['material-request', 'delivery'] },
  { id: 'attendance-one-line', roles: ENGINEERS, title: 'Mark attendance in one line', why: '"Suresh team: 4 masons, 2 helpers", and the muster roll fills itself.', walks: ['attendance'] },
  { id: 'problem-fixed', roles: ENGINEERS, title: 'Report a problem and get it fixed', why: 'Say what is wrong; it stays open until someone acts on it.', walks: ['page-issues'] },
]

export const OUTCOME_WALKS: Walkthrough[] = OUTCOMES.map((o) => composed(`goal-${o.id}`, o.title, o.why, o.walks, 'outcome', o.roles))

/** Role paths: a role's outcomes in order, as one walkthrough (plan section 5.1). SS-48 adds Project manager, Finance. */
export const ROLE_PATHS: Walkthrough[] = [
  composed('path-owner', 'Everything an owner gets, in order', 'All of the above, one after another.', OUTCOMES.filter((o) => o.roles === OWNERS).map((o) => `goal-${o.id}`), 'role', OWNERS),
  composed('path-site-engineer', 'Everything a site engineer does, in order', 'All of the above, one after another.', OUTCOMES.filter((o) => o.roles === ENGINEERS).map((o) => `goal-${o.id}`), 'role', ENGINEERS),
]

export const ALL_WALKS: Walkthrough[] = [...ROLE_PATHS, ...OUTCOME_WALKS, ...FULL_WORKFLOWS, ...WORKFLOWS, ...MODULE_WALKS, ...PAGE_WALKS]

export function findWalkthrough(id: string): Walkthrough | undefined {
  return ALL_WALKS.find((w) => w.id === id)
}

/** May this role take it? A step on a page the role can't open is skipped by the engine, not here. */
export function walkFor(walk: Walkthrough, role: string | null | undefined): boolean {
  return !walk.roles || walk.roles.includes((role ?? '').toUpperCase())
}

/** Can this role open this page (module-map roles)? */
export function pageOpenFor(url: string, role: string | null | undefined): boolean {
  const [path, query = ''] = url.split('?')
  const roles = findPage(path, query ? `?${query}` : '')?.page.roles
  return !roles || roles.includes((role ?? '').toUpperCase())
}
