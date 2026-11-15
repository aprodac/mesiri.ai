import type { SparkMood } from '@/components/live/spark'
import { findPage } from './module-map'

// The guided tours (asked 15 Nov: "like in games, everything highlighted and told, one by one", with "that Mesiri
// character in Live to help"): the Spark from Live walks a new person through the app and each main page, one thing
// at a time. components/tour.tsx draws them.
//
// Built to survive a product that keeps changing (guided-onboarding-plan.md 6.7):
// - a step points at a marker on the element itself (`data-guide="today.send"`), never at a screen position, so a
//   moved button keeps its step;
// - a step whose element is not on the screen (a role that can't see the button, a page with no data yet) is skipped,
//   never shown pointing at nothing;
// - the build fails when a step's marker is on no element any more (vite.config.ts, checkTourMarkers), so a removed
//   button can't leave its step behind;
// - raise a tour's `version` when it changes enough to show again to people who finished it.

export interface TourStep {
  /** The `data-guide` marker of what to point at; none: the Spark speaks in the middle of the screen. */
  target?: string
  title: string
  text: string
  mood?: SparkMood
}

export interface Tour {
  /** Remembered per person under this key, at this version (users.guide_seen, SS-27). */
  key: string
  version: number
  steps: TourStep[]
  /** The page's own `about` from module-map.ts goes first, as the Spark's hello. */
  introFromPage?: boolean
}

/** The first tour: the app around the page, once per person. */
export const APP_TOUR: Tour = {
  key: '/tour/app',
  version: 1,
  steps: [
    {
      title: "Hi, I'm Mesiri",
      text: "Your site team sends me updates on WhatsApp: text, voice notes, photos. I turn them into records and your daily report. Let me show you around. It takes a minute.",
      mood: 'hello',
    },
    {
      target: 'app.nav',
      title: 'Everything is here',
      text: 'Every part of Mesiri, in the order a project runs: Plan, Site, Buy, Money. You start with the everyday pages; "Show all" opens the rest.',
    },
    { target: 'app.search', title: 'Find anything', text: 'Search finds any page, project or record. Ctrl K opens it from anywhere.', mood: 'look' },
    { target: 'app.scope', title: 'One project or all', text: 'Pick a project or a site here, and every page shows just that one.' },
    {
      target: 'app.whatsapp',
      title: 'What to send me',
      text: 'This shows what to send me on WhatsApp for the page you are on. Your site team never needs to open the dashboard.',
    },
    { target: 'app.help', title: 'Stuck?', text: 'Help explains the page and its words, and plays this tour again.', mood: 'happy' },
  ],
}

/** Each main page's tour, by its address in lib/module-map.ts. */
export const PAGE_TOURS: Record<string, Tour> = {
  '/today': {
    key: '/tour/today',
    version: 1,
    introFromPage: true,
    steps: [
      { target: 'today.day', title: 'Any day', text: 'Move between days here. Each day keeps what the sites sent.' },
      { target: 'today.checklist', title: 'Getting started', text: 'Your first steps. Each one ticks itself when it is done.' },
      { target: 'today.sites', title: "Each site's day", text: "Who came, what work was done, what came in and what is missing. Open a site to see its whole day." },
      { target: 'today.send', title: 'The daily report', text: 'When the day looks right, send the daily report (DPR) to the owner and the client. It can also go by itself every evening.', mood: 'send' },
      { target: 'today.issues', title: 'What is stuck', text: 'Problems from site wait here until someone acts on them.', mood: 'worry' },
      { target: 'today.tell', title: 'Tell me here too', text: 'You can tell me things right here, the way you would on WhatsApp.', mood: 'happy' },
    ],
  },
  '/reports': {
    key: '/tour/reports',
    version: 1,
    introFromPage: true,
    steps: [
      { target: 'reports.filters', title: 'Which reports', text: 'Choose the dates, and site or project reports.' },
      { target: 'reports.list', title: 'Every report', text: 'Each site and project report, newest first, grouped by project.' },
      { target: 'reports.pdf', title: 'The PDF', text: 'Open the PDF exactly as the owner and client got it.', mood: 'look' },
      { target: 'reports.export', title: 'Take it to Excel', text: 'Download the list as a CSV file.', mood: 'happy' },
    ],
  },
  '/issues': {
    key: '/tour/issues',
    version: 1,
    introFromPage: true,
    steps: [
      { target: 'issues.stats', title: 'At a glance', text: 'How many are open, how many are urgent, and how much time they have cost.', mood: 'look' },
      { target: 'issues.search', title: 'Find one', text: 'Search by what was said, the site or who reported it.', mood: 'look' },
      { target: 'issues.list', title: 'Act on it', text: 'Each issue stays open until someone marks it seen, fixed, or won\'t fix.' },
      { target: 'issues.add', title: 'Report one here', text: 'Or report it from the office. On WhatsApp, the site just says what is wrong.', mood: 'happy' },
    ],
  },
  '/materials': {
    key: '/tour/materials',
    version: 1,
    introFromPage: true,
    steps: [
      { target: 'materials.views', title: 'Three views', text: 'Stock: what each site holds. Movements: what came in, was used or moved. Items: your list of materials.' },
      { target: 'materials.in', title: 'A delivery', text: 'Record what came in. On WhatsApp: "200 bags cement came from Malabar".' },
      { target: 'materials.out', title: 'Used on site', text: 'Record what was used. On WhatsApp: "Used 20 bags cement for the slab".' },
      { target: 'materials.move', title: 'Between sites', text: 'Move stock from one site to another, so both sites stay right.', mood: 'happy' },
    ],
  },
  '/labour': {
    key: '/tour/labour',
    version: 1,
    introFromPage: true,
    steps: [
      { target: 'labour.views', title: 'Four views', text: 'Attendance by day, the muster roll for the month, your workers and their wages, and the labour teams.' },
      { target: 'labour.add', title: 'Add a worker', text: 'Add a person with their trade and daily wage. On WhatsApp the site just says who came: "Suresh team: 4 masons, 2 helpers".', mood: 'happy' },
    ],
  },
  '/boq': {
    key: '/tour/boq',
    version: 1,
    introFromPage: true,
    steps: [
      { target: 'boq.empty', title: 'Start here', text: 'Upload the estimate Excel you already have; I read its items, units and quantities. Or start one section by hand.' },
      { target: 'boq.import', title: 'From your Excel', text: 'Bring the BOQ in from the Excel you already have.' },
      { target: 'boq.lines', title: 'Every line', text: 'Each work item with its quantity and rates. Work the site sends on WhatsApp counts on its line by itself, with the budget it earned.', mood: 'think' },
      { target: 'boq.schedule', title: 'Its schedule', text: 'The same sections become the project schedule.', mood: 'happy' },
    ],
  },
  '/projects': {
    key: '/tour/projects',
    version: 1,
    introFromPage: true,
    steps: [
      { target: 'projects.add', title: 'A new project', text: 'Add a project and its sites. Each site gets its own daily report.' },
      { target: 'projects.list', title: 'Your projects', text: 'Open one to set who reports from each site and who gets its report.', mood: 'happy' },
    ],
  },
  '/team': {
    key: '/tour/team',
    version: 1,
    introFromPage: true,
    steps: [
      { target: 'team.add', title: 'Add a person', text: 'Their name, WhatsApp number and role. Or, on WhatsApp, just share their contact with me.' },
      { target: 'team.search', title: 'Find someone', text: 'By name, email or number.', mood: 'look' },
      { target: 'team.list', title: 'Everyone', text: 'Who reports and who reads, with their role and sites.', mood: 'happy' },
    ],
  },
}

/** The tour of the page at this address, if it has one. */
export function tourForPage(pathname: string, search = ''): { tour: Tour; about: string; title: string } | null {
  const hit = findPage(pathname, search)
  if (!hit || hit.page.status !== 'built') return null
  const tour = PAGE_TOURS[hit.page.url.split('?')[0]]
  return tour ? { tour, about: hit.page.about, title: hit.page.title } : null
}

/** Every marker the tours point at (the build checks each is on some element: vite.config.ts). */
export function tourMarkers(): string[] {
  return [APP_TOUR, ...Object.values(PAGE_TOURS)].flatMap((t) => t.steps.map((s) => s.target).filter((x): x is string => !!x))
}
