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

export type WalkKind = 'role' | 'workflow' | 'module' | 'page'

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
}

/** A practice here: the step's target is the real button; the person clicks it and the tour waits for its dialog. */
export interface TryHere {
  kind: 'here'
  check?: WalkCheck
}

/** How to take a practice back (D-L3): WhatsApp words, the dashboard way, or both. */
export interface TakeBack {
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
  steps: WalkStep[]
}

/** Remembered per person in users.guide_seen under this key (lowercase, like every guide key). */
export function learnKey(id: string): string {
  return `/learn/${id}`
}

const minutesFor = (steps: number) => Math.max(1, Math.round(steps * 0.4))

const RECORDERS = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER'] as const

const INFLOWS: WalkCheck = { path: '/materials/inflows', params: { limit: 25 } }

/** Workflows: one job from start to finish, across pages, with practice (plan section 5.2). */
export const WORKFLOWS: Walkthrough[] = [
  {
    id: 'delivery',
    kind: 'workflow',
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
        try: { kind: 'whatsapp', say: '10 bags cement came from Malabar', tools: ['record_receipt'], check: INFLOWS },
      },
      {
        page: '/materials?view=movements',
        target: 'materials.list',
        title: 'There it is',
        text: 'The delivery is in Movements, and the stock went up by 10 bags. Your site never opened the dashboard.',
        mood: 'happy',
      },
      {
        page: '/materials?view=movements',
        title: 'Take it back',
        text: 'It was practice, so take it back the same way. Mesiri shows a card: tap Save.',
        takeBack: { say: 'Take back the 10 bags cement delivery', tools: ['undo_receipt'] },
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
        takeBack: { here: 'Open the row, then Correct (an owner, admin or project manager).' },
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
]

/** Role paths: a person's workflows in order (plan section 5.1). SS-43 and SS-48 add them. */
export const ROLE_PATHS: Walkthrough[] = []

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
  const steps: WalkStep[] = [...intro, ...tour.steps].map((s) => ({ ...s, page: page.url }))
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

export const ALL_WALKS: Walkthrough[] = [...ROLE_PATHS, ...WORKFLOWS, ...MODULE_WALKS, ...PAGE_WALKS]

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
