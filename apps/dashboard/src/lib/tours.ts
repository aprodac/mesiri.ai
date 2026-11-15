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
  /**
   * Start by itself only once one of these markers is on screen: the page's real content, not a project picker or a
   * loading skeleton. Until then the tour waits (and is not marked seen). Replay from Help shows it whatever is there.
   */
  startWhen?: string[]
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
    startWhen: ['boq.empty', 'boq.lines'],
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

  // Planning (SS-44). Each waits until a project is picked and its page has loaded (startWhen); on replay from Help
  // with no project picked, the Spark points at the project list instead.
  '/planning/setup': {
    key: '/tour/planning-setup',
    version: 1,
    introFromPage: true,
    startWhen: ['setup.steps'],
    steps: [
      { target: 'planning.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
      { target: 'setup.stage', title: 'Where the project is', text: 'Tender, won, running, handover. Tap the next stage when the project moves on.' },
      { target: 'setup.steps', title: 'Steps to "work starts"', text: 'Dates, contract, BOQ, schedule, sites, the site team, suppliers. Each step ticks itself when it is done.', mood: 'think' },
      { target: 'setup.next', title: 'Do this next', text: 'The next step is lit up. Its button opens the place to do it.', mood: 'happy' },
      { target: 'setup.schedule', title: 'The schedule today', text: 'Once there is a schedule: how much is done, what is late and the finish date. Tap to open it.', mood: 'look' },
      { target: 'app.whatsapp', title: 'Or start it on WhatsApp', text: 'Send me "New project Lake View for Mr Thomas at Kakkanad, starts 1 Dec" and I set it up.', mood: 'happy' },
    ],
  },
  '/planning/schedule': {
    key: '/tour/planning-schedule',
    version: 1,
    introFromPage: true,
    startWhen: ['schedule.empty', 'schedule.stats'],
    steps: [
      { target: 'planning.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
      { target: 'schedule.empty', title: 'Start from your BOQ', text: 'Upload the estimate Excel: each section becomes a bar. Or add activities by hand.' },
      { target: 'schedule.stats', title: 'At a glance', text: 'How much work is done, what is late, and the finish date the project is heading for at this pace.', mood: 'look' },
      { target: 'schedule.filter', title: 'What to look at', text: 'Everything, only what is late or behind, this week\'s work, or the critical work that moves the handover date.' },
      { target: 'schedule.chart', title: 'Bars that fill themselves', text: 'Each bar fills as site sends its work on WhatsApp. Drag a bar to move it: I show what moves with it before anything is saved.', mood: 'think' },
      { target: 'schedule.add', title: 'Add work', text: 'Add an activity, bring sections from the BOQ Excel, or let Quick plan put them one after another.' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: 'Ask "What\'s late on Green Villa\'s schedule?" or say "Move slab casting to 20 Nov".', mood: 'happy' },
    ],
  },
  '/planning/materials': {
    key: '/tour/planning-materials',
    version: 1,
    introFromPage: true,
    startWhen: ['matplan.empty', 'matplan.stats'],
    steps: [
      { target: 'planning.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
      { target: 'matplan.empty', title: 'Materials for each BOQ line', text: 'The plan needs to know what each BOQ line uses, like cement per m³ of concrete. Fill the common ones in one tap, or set them on the BOQ.', mood: 'think' },
      { target: 'matplan.stats', title: 'At a glance', text: 'How many materials are planned, how many run short in these weeks, and how many BOQ lines have their materials.', mood: 'look' },
      { target: 'matplan.table', title: 'Week by week', text: 'What each material is needed for, week by week from the schedule, against stock and what is on order. Red weeks run short; Order opens a purchase order already filled in.' },
      { target: 'matplan.weeks', title: 'How far ahead', text: 'Look 4, 8 or 12 weeks ahead, or open the BOQ the plan comes from.' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: 'Ask "What do I need to order for next week at Green Villa?"', mood: 'happy' },
    ],
  },
  '/planning/live': {
    key: '/tour/planning-live',
    version: 1,
    introFromPage: true,
    startWhen: ['live.plan'],
    steps: [
      { target: 'planning.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
      { target: 'live.drawings', title: 'Each drawing', text: 'Each floor plan or foundation drawing, with how many rooms or footings are done.' },
      { target: 'live.trades', title: 'One trade at a time', text: 'Show all work, or one trade: brickwork, plastering, tiling.' },
      { target: 'live.stats', title: 'At a glance', text: 'Done, under way, not started, and the photos from site.', mood: 'look' },
      { target: 'live.plan', title: 'The live map', text: 'Each room or footing coloured by what site sent on WhatsApp. Tap one for its work and photos.', mood: 'happy' },
      { target: 'live.photos', title: 'Photos on the plan', text: 'Show the photos from site on the rooms they were taken in.' },
      { target: 'live.feed', title: 'From site', text: 'Updates as they come in. Tap one to find it on the plan.', mood: 'look' },
      { target: 'app.whatsapp', title: 'How site fills it', text: 'Site just says "Brickwork done in Bedroom 2, first floor" and the room changes colour.', mood: 'happy' },
    ],
  },
  '/planning/places': {
    key: '/tour/planning-places',
    version: 1,
    introFromPage: true,
    startWhen: ['places.setup', 'places.stats'],
    steps: [
      { target: 'planning.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
      { target: 'places.setup', title: 'Floors and rooms', text: 'Set them up once: one per line, and every floor gets the same rooms. Rename or remove any of them after.', mood: 'think' },
      { target: 'places.stats', title: 'At a glance', text: 'Floors, rooms, how many are finished and how many are under way.', mood: 'look' },
      { target: 'places.grid', title: 'Room by room', text: 'Each room and each trade: done, under way or not started. Tap a room for its work and photos.' },
      { target: 'places.edit', title: 'Change them', text: 'Add, rename or remove floors and rooms.' },
      { target: 'app.whatsapp', title: 'On WhatsApp', text: 'Site says "FF R2 tiling 40 sqft"; you ask "What\'s left on the first floor?"', mood: 'happy' },
    ],
  },
  '/planning/drawing-check': {
    key: '/tour/planning-drawing-check',
    version: 1,
    introFromPage: true,
    startWhen: ['drawing.drop'],
    steps: [
      { target: 'drawing.drop', title: 'Drop the drawing PDF', text: 'The PDF the architect exported from CAD, not a scan. I read its sheets, levels, room sizes and fixtures.' },
      { target: 'drawing.checks', title: 'What to ask the architect', text: 'Sizes that do not match their labels, levels that disagree: ask before the drawing reaches site.', mood: 'worry' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: 'Ask "What levels does S-101 show?"', mood: 'happy' },
    ],
  },
  '/planning/documents': {
    key: '/tour/planning-documents',
    version: 1,
    introFromPage: true,
    startWhen: ['docs.drop'],
    steps: [
      { target: 'planning.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
      { target: 'docs.drop', title: 'Keep the files here', text: 'Drop the drawings, permits and contract: PDF, photos, Word, Excel or DWG. A new revision of a drawing marks the old one out of date.' },
      { target: 'docs.folders', title: 'Folders', text: 'Drawings, permits, contract, test reports, handover. The locked ones are for the office only.' },
      { target: 'docs.search', title: 'Find one', text: 'By drawing number or title, like S-101.', mood: 'look' },
      { target: 'docs.list', title: 'Open one', text: 'Its revision, its expiry date, and a new revision when one comes. Permits about to expire show at the top.' },
      { target: 'app.whatsapp', title: 'Site asks on WhatsApp', text: '"Send me the latest S-101" and I send the PDF, always the latest revision.', mood: 'happy' },
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
  return [APP_TOUR, ...Object.values(PAGE_TOURS)].flatMap((t) => [
    ...t.steps.map((s) => s.target).filter((x): x is string => !!x),
    ...(t.startWhen ?? []),
  ])
}
