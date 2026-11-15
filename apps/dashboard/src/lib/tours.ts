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

  // SS-47: the other modules' pages, as their own block (Site, Tasks, Materials, Labour, Subcontract, Finance, Client
  // billing, Equipment, Settings). Each waits for its page's content, never a skeleton or a picker (startWhen).
  '/reports/period': {
    key: '/tour/reports-period',
    version: 1,
    introFromPage: true,
    startWhen: ['period.kpis'],
    steps: [
      { target: 'period.kinds', title: 'A week or a month', text: 'Pick the week, the month, or your own dates. The arrows go back and forward one at a time.' },
      { target: 'period.kpis', title: 'At a glance', text: 'Work against plan, labour, materials and money for the period. Tap a number to open its part of the report.', mood: 'look' },
      { target: 'period.projects', title: 'Every project', text: 'With no project picked, every running project in one table, the one that needs you most first. Tap one for its own report.' },
      { target: 'period.open', title: 'One project', text: 'Or open one project\'s report from here.' },
      { target: 'period.needs', title: 'What needs you', text: 'What went wrong this period and what to do about it, next to how each part did.', mood: 'worry' },
      { target: 'period.sections', title: 'Each part in full', text: 'Work, schedule, labour, materials, money, issues and photos, one at a time.' },
      { target: 'period.download', title: 'PDF and Excel', text: 'The same report as a PDF for the owner, or an Excel file.' },
      { target: 'period.send', title: 'Send it', text: 'Send it now, or every Monday or every 1st by itself.', mood: 'send' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"Send me October\'s report for Green Villa", or "Send the monthly report to Ravi on the 1st".', mood: 'happy' },
    ],
  },
  '/site-log': {
    key: '/tour/site-log',
    version: 1,
    introFromPage: true,
    startWhen: ['sitelog.list', 'sitelog.empty'],
    steps: [
      { target: 'sitelog.views', title: 'Three views', text: 'Work: each piece of work the sites reported. Photos: every photo. Everything: every entry, in the order it came.' },
      { target: 'sitelog.stats', title: 'At a glance', text: 'Work reported, under way, finished, and stopped. Stopped work needs a look.', mood: 'look' },
      { target: 'sitelog.filters', title: 'Narrow it down', text: 'Search the work or the contractor, or pick a status and the dates.' },
      { target: 'sitelog.list', title: 'Day by day', text: 'Newest first, by day and site. Tap a line for its details and photos; tap the site for that day\'s report.' },
      { target: 'sitelog.empty', title: 'Nothing yet', text: 'The work comes in from WhatsApp. Site just says what was done.', mood: 'think' },
      { target: 'sitelog.export', title: 'Take it to Excel', text: 'Download what is shown as a CSV file.' },
      { target: 'app.whatsapp', title: 'How site fills it', text: '"Plastering 120 sq ft on the second floor", with a photo. Ask "What was done yesterday at Main building?"', mood: 'happy' },
    ],
  },
  '/analytics': {
    key: '/tour/analytics',
    version: 1,
    introFromPage: true,
    startWhen: ['analytics.stats'],
    steps: [
      { target: 'analytics.range', title: 'How far back', text: 'The last 7, 30 or 90 days.' },
      { target: 'analytics.stats', title: 'At a glance', text: 'Worker-days, work items, photos, issues, and the hours lost to them.', mood: 'look' },
      { target: 'analytics.charts', title: 'Day by day', text: 'People on site and work reported each day. Table shows the same numbers as a list.' },
      { target: 'analytics.reporting', title: 'Which sites report', text: 'How many days each site sent updates, and how many of its reports were confirmed. A site that goes quiet shows here first.', mood: 'think' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"How many people worked this week at Green Villa?"', mood: 'happy' },
    ],
  },
  '/tasks': {
    key: '/tour/tasks',
    version: 1,
    introFromPage: true,
    startWhen: ['tasks.list', 'tasks.empty'],
    steps: [
      { target: 'tasks.views', title: 'Four views', text: 'My tasks: given to you. All open: every open task. Overdue: past their day. Done: finished, and who closed them.' },
      { target: 'tasks.filters', title: 'Narrow it down', text: 'By site, by who has it, or search.' },
      { target: 'tasks.list', title: 'Late first', text: 'Each task with who has it, the site and the day it is due. Late days show in red.', mood: 'worry' },
      { target: 'tasks.empty', title: 'Nothing here', text: 'Tasks given to people show here, late first. Give the first one.', mood: 'think' },
      { target: 'tasks.detail', title: 'Open one', text: 'The person it is for moves it on: Start, Blocked with the reason, Done, or Done with a photo.', mood: 'think' },
      { target: 'tasks.add', title: 'Give a task', text: 'What to do, for whom, at which site, by when.', mood: 'happy' },
    ],
  },
  '/materials/counts': {
    key: '/tour/stock-count',
    version: 1,
    introFromPage: true,
    startWhen: ['counts.list', 'counts.empty'],
    steps: [
      { target: 'counts.due', title: 'Due for a count', text: 'Sites not counted in 30 days. Tap one to start its count.', mood: 'worry' },
      { target: 'counts.start', title: 'Start a count', text: 'Pick the site, and every item or just the 20 most valuable. The book is frozen at that moment.' },
      { target: 'counts.list', title: 'Every count', text: 'Each count with how much is counted and how many items differ from the book.' },
      { target: 'counts.empty', title: 'No counts yet', text: 'Count a site once a month: what the book says is there against what really is.', mood: 'think' },
      { target: 'counts.sheet', title: 'Count on a phone', text: 'Type what is really there. Each difference asks why: wastage, theft, a wrong entry. The owner approves them into the book.', mood: 'think' },
      { target: 'app.whatsapp', title: 'Count on WhatsApp', text: '"Count: cement 92 bags, sand 3 loads".', mood: 'happy' },
    ],
  },
  '/materials/value': {
    key: '/tour/stock-value',
    version: 1,
    introFromPage: true,
    startWhen: ['value.list', 'value.empty'],
    steps: [
      { target: 'value.tiles', title: 'What the stock is worth', text: 'What is on hand times the average rate it was bought at.', mood: 'look' },
      { target: 'value.slow', title: 'Not moving', text: 'Stock not used in 30 days: money sitting on site. Tap it to see only those.', mood: 'worry' },
      { target: 'value.categories', title: 'By category', text: 'Steel, cement, tiles: where the money in stock is.' },
      { target: 'value.list', title: 'Every item', text: 'Most valuable first, with its site, quantity and rate.' },
      { target: 'value.empty', title: 'Nothing on hand', text: 'Stock value comes from deliveries with a rate. Record the rate when material comes in.', mood: 'think' },
      { target: 'value.export', title: 'Take it to Excel', text: 'Download the list.' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"What is the stock at Green Villa worth?"', mood: 'happy' },
    ],
  },
  '/labour/wages': {
    key: '/tour/wages',
    version: 1,
    introFromPage: true,
    startWhen: ['wages.stats'],
    steps: [
      { target: 'wages.week', title: 'One pay week', text: 'One site\'s week. The arrows go back and forward a week.' },
      { target: 'wages.stats', title: 'The week in figures', text: 'Man-days from attendance, wages and overtime, the advance taken back, deductions, to pay and paid.', mood: 'look' },
      { target: 'wages.list', title: 'Each worker and team', text: 'Days times the daily wage, less what they took ahead. Tap one to set the advance back, add a deduction or send the slip.' },
      { target: 'wages.empty', title: 'No attendance', text: 'Wages come from attendance. Site says who came, every day.', mood: 'think' },
      { target: 'wages.approve', title: 'Approve the week', text: 'When it looks right, approve it. Then pay from site cash or the bank.' },
      { target: 'wages.pay', title: 'Pay', text: 'Pay everyone, or one person from their row. The money leaves the account you pick.', mood: 'send' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"What do I pay Suresh\'s team this week?", then "Approve this week\'s wages".', mood: 'happy' },
    ],
  },
  '/labour/advances': {
    key: '/tour/advances',
    version: 1,
    introFromPage: true,
    startWhen: ['advances.list', 'advances.empty'],
    steps: [
      { target: 'advances.stats', title: 'Still out', text: 'Money given ahead that is not back yet, and to how many people and teams.', mood: 'look' },
      { target: 'advances.owed', title: 'Who has it', text: 'Each person and team, most first. It comes off their next wages by itself.' },
      { target: 'advances.list', title: 'Every advance', text: 'Who got it, from which account, and who gave it. A wrong one can be taken back: the money returns to its account.' },
      { target: 'advances.empty', title: 'None yet', text: 'An advance given on site is told on WhatsApp.', mood: 'think' },
      { target: 'advances.give', title: 'Give one here', text: 'To a worker or a team, from a cash box or the bank.' },
      { target: 'app.whatsapp', title: 'On WhatsApp', text: '"Gave Ravi 500 advance".', mood: 'happy' },
    ],
  },
  '/subcontract/teams': {
    key: '/tour/subcontractors',
    version: 1,
    introFromPage: true,
    startWhen: ['subs.list', 'subs.empty'],
    steps: [
      { target: 'subs.list', title: 'Every outside team', text: 'Their open work orders and sites. The bar shows how much work is done and how much is billed.' },
      { target: 'subs.empty', title: 'None yet', text: 'A subcontractor is added with their first work order.', mood: 'think' },
      { target: 'subs.money', title: 'What you owe', text: 'The work given, what is payable now, the retention held and the advance still to recover.', mood: 'look' },
      { target: 'subs.actions', title: 'Their papers', text: 'Their work orders, a statement to send them, and their account.' },
      { target: 'subs.orders', title: 'Work orders', text: 'Who does which work at what rate.' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"What do we owe the tiling team?"', mood: 'happy' },
    ],
  },
  '/subcontract/work-orders': {
    key: '/tour/work-orders',
    version: 1,
    introFromPage: true,
    startWhen: ['wo.list', 'wo.empty'],
    steps: [
      { target: 'sub.value', title: 'Money kept', text: 'Over-billing caught before it was paid: work billed that was not measured, or above the agreed rate.', mood: 'happy' },
      { target: 'wo.tiles', title: 'At a glance', text: 'Open work orders, bills to check, lines billed above what was measured or agreed, and what is payable now. Tap one to see only those.', mood: 'look' },
      { target: 'wo.tabs', title: 'Where each one is', text: 'Open, drafts, work done, or all.' },
      { target: 'wo.filters', title: 'Find one', text: 'By WO number, the work or the site, or by subcontractor.' },
      { target: 'wo.list', title: 'Each work order', text: 'The team, the work, how much is done and billed. Open one to measure the work and check its bills.' },
      { target: 'wo.empty', title: 'None yet', text: 'Concreting, plastering, wiring: who does it, at what rate.', mood: 'think' },
      { target: 'wo.add', title: 'A new work order', text: 'The team, the work, the quantity and the rate. Send it to them on WhatsApp as a PDF.' },
      { target: 'app.whatsapp', title: 'On WhatsApp', text: '"Work order to Sree tiles: floor tiling 2,400 sq ft at ₹38", then "Sree tiles did 600 sq ft this week".', mood: 'happy' },
    ],
  },
  '/subcontract/bills': {
    key: '/tour/subcontract-bills',
    version: 1,
    introFromPage: true,
    startWhen: ['bills.list', 'bills.empty'],
    steps: [
      { target: 'sub.value', title: 'Money kept', text: 'Over-billing caught before it was paid, this month or since the start.', mood: 'happy' },
      { target: 'bills.list', title: 'Bills to check', text: 'Each bill set against the work measured on site and the agreed rate. What does not match is shown in red.', mood: 'worry' },
      { target: 'bills.decide', title: 'Approve or reject', text: 'Approve it, reject it with the reason, or open its work order.' },
      { target: 'bills.empty', title: 'Nothing waiting', text: 'Every bill is checked.', mood: 'happy' },
      { target: 'app.whatsapp', title: 'On WhatsApp', text: '"Concrete team bill ₹15,000 for 2.4 m³": I check it against what was measured.', mood: 'happy' },
    ],
  },

  // Planning (SS-44). Each waits until a project is picked and its page has loaded (startWhen); on replay from Help
  // with no project picked, the Spark points at the project list instead (project.pick).
  '/planning/setup': {
    key: '/tour/planning-setup',
    version: 1,
    introFromPage: true,
    startWhen: ['setup.steps'],
    steps: [
      { target: 'project.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
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
      { target: 'project.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
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
      { target: 'project.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
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
      { target: 'project.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
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
      { target: 'project.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
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
      { target: 'project.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
      { target: 'docs.drop', title: 'Keep the files here', text: 'Drop the drawings, permits and contract: PDF, photos, Word, Excel or DWG. A new revision of a drawing marks the old one out of date.' },
      { target: 'docs.folders', title: 'Folders', text: 'Drawings, permits, contract, test reports, handover. The locked ones are for the office only.' },
      { target: 'docs.search', title: 'Find one', text: 'By drawing number or title, like S-101.', mood: 'look' },
      { target: 'docs.list', title: 'Open one', text: 'Its revision, its expiry date, and a new revision when one comes. Permits about to expire show at the top.' },
      { target: 'app.whatsapp', title: 'Site asks on WhatsApp', text: '"Send me the latest S-101" and I send the PDF, always the latest revision.', mood: 'happy' },
    ],
  },
  // Procurement (SS-45): from the site's request to the supplier's account.
  '/materials/requests': {
    key: '/tour/requests',
    version: 1,
    introFromPage: true,
    startWhen: ['req.list'],
    steps: [
      { target: 'req.tiles', title: 'What needs you', text: 'Waiting for the office, late, due in 2 days, and possible duplicates. Tap one to see only those.', mood: 'look' },
      { target: 'req.tabs', title: 'Where each request is', text: 'Waiting, ordered, received, or not ordered.' },
      { target: 'req.filters', title: 'Narrow it down', text: 'By site, who asked, category, the day it is needed, or search.' },
      { target: 'req.list', title: 'Open one', text: 'See what was asked, then order it, get quotes for it, or mark it received.', mood: 'think' },
      { target: 'req.act', title: 'Decide here', text: 'Create the order already filled in, get quotes from several shops, send it from another site, or say it is not being ordered.' },
      { target: 'req.add', title: 'A request from the office', text: 'Make one here when the site asks by phone.' },
      { target: 'app.whatsapp', title: 'How site asks', text: 'Site says "Need 200 bags cement by Friday for the first-floor slab". "Show my requests" lists theirs.', mood: 'happy' },
    ],
  },
  '/procurement/orders': {
    key: '/tour/orders',
    version: 1,
    introFromPage: true,
    startWhen: ['po.list'],
    steps: [
      { target: 'po.tiles', title: 'At a glance', text: 'Still to come, late, due in 2 days, and part received. Tap one to see only those.', mood: 'look' },
      { target: 'po.tabs', title: 'Where each order is', text: 'To come, part received, received, closed.' },
      { target: 'po.filters', title: 'Find an order', text: 'By site, supplier, category or due date, or search by PO number, the supplier\'s number or an item.' },
      { target: 'po.list', title: 'Open an order', text: 'Record what came, change it, close it short or cancel it.', mood: 'think' },
      { target: 'po.send', title: 'Send it to the shop', text: 'Open the PO document, or send the order on WhatsApp already written. You press send.', mood: 'send' },
      { target: 'po.receive', title: 'When it comes', text: 'Material came: count what arrived, what was rejected and why, with the challan photo. That makes the GRN.' },
      { target: 'po.add', title: 'A new order', text: 'Order from the office. An order that repeats another is flagged before it goes.' },
      { target: 'app.whatsapp', title: 'Order on WhatsApp', text: '"Order 200 bags cement from Malabar at ₹400".', mood: 'happy' },
    ],
  },
  '/procurement/grn': {
    key: '/tour/grn',
    version: 1,
    introFromPage: true,
    startWhen: ['grn.list'],
    steps: [
      { target: 'grn.search', title: 'Find a delivery', text: 'By GRN, PO, supplier, challan number or item.', mood: 'look' },
      { target: 'grn.list', title: 'Each delivery', text: 'Against its order: what was accepted, what was rejected and why, who received it, and the challan photo.' },
      { target: 'grn.challan', title: 'The challan photo', text: 'The supplier\'s challan as site photographed it, kept with the delivery.' },
      { target: 'grn.return', title: 'Send it back', text: 'What was rejected at the gate goes back to the supplier with a debit note.', mood: 'worry' },
      { target: 'app.whatsapp', title: 'How site records it', text: '"150 bags cement came against PO-0042, 3 torn": I record the delivery and the 3 not accepted.', mood: 'happy' },
    ],
  },
  '/procurement/pending': {
    key: '/tour/pending',
    version: 1,
    introFromPage: true,
    startWhen: ['pending.list', 'pending.empty'],
    steps: [
      { target: 'pending.tiles', title: 'What is still to come', text: 'Late, due today, this week, and orders with no date. Tap one to see only those.', mood: 'look' },
      { target: 'pending.group', title: 'By date or by supplier', text: 'By supplier puts each shop\'s lines together, so you chase each one once.' },
      { target: 'pending.list', title: 'Each line still to come', text: 'How much has come so far. Material came records the delivery.' },
      { target: 'pending.chase', title: 'Chase the supplier', text: 'Call them, or open WhatsApp with the message already written; you send it.', mood: 'send' },
      { target: 'pending.came', title: 'It arrived', text: 'Material came records the delivery against its order.' },
      { target: 'pending.empty', title: 'Nothing waiting', text: 'Every order came in full.', mood: 'happy' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"What hasn\'t arrived yet?"', mood: 'happy' },
    ],
  },
  '/procurement/rates': {
    key: '/tour/rates',
    version: 1,
    introFromPage: true,
    startWhen: ['rates.list'],
    steps: [
      { target: 'rates.tiles', title: 'At a glance', text: 'What was bought, the items whose rate went up or down, and what buying from the cheapest supplier would have saved.', mood: 'look' },
      { target: 'rates.sort', title: 'Sort', text: 'By what was spent most, the biggest change, or the most to save.' },
      { target: 'rates.filters', title: 'Narrow it down', text: 'By site, supplier, category and period, or search.' },
      { target: 'rates.list', title: 'Each item', text: 'Its rate and how it moved. Open one for every purchase by supplier, and order again from here.', mood: 'think' },
      { target: 'rates.cheaper', title: 'Cheaper elsewhere', text: 'Another supplier gave it cheaper: what it would have saved, and an order to them in one tap.', mood: 'happy' },
      { target: 'rates.order', title: 'Order again', text: 'The same item from the same shop at the last rate, already filled in.' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"What did we pay for cement last time?"', mood: 'happy' },
    ],
  },
  '/procurement/quotations': {
    key: '/tour/quotations',
    version: 1,
    introFromPage: true,
    startWhen: ['quotes.list'],
    steps: [
      { target: 'quotes.tiles', title: 'At a glance', text: 'Waiting for quotes, ready to compare, overdue, and what comparing has saved.', mood: 'look' },
      { target: 'quotes.tabs', title: 'Where each one is', text: 'Each request for quotes, from asked to ordered.' },
      { target: 'quotes.list', title: 'Each request for quotes', text: 'The items and the suppliers asked. Open one to add their quotes.' },
      { target: 'quotes.detail', title: 'One request for quotes', text: 'Its items, the suppliers asked, their quotes side by side, and the order you place from them.', mood: 'think' },
      { target: 'quotes.suppliers', title: 'Each supplier', text: 'Send them the request on WhatsApp, then record their reply. Ask one more shop at the bottom.' },
      { target: 'quotes.compare', title: 'Side by side', text: 'Each quote as it really costs you: GST you can claim back is left out. Pick per item, or order all from the cheapest.', mood: 'happy' },
      { target: 'quotes.add', title: 'Ask for quotes', text: 'Pick the items and the suppliers to ask.' },
      { target: 'app.whatsapp', title: 'On WhatsApp', text: '"Get quotes from Malabar, KK and Sree for 500 bags cement", then "KK quoted 398 for cement".', mood: 'happy' },
    ],
  },
  '/finance/vendors': {
    key: '/tour/suppliers',
    version: 1,
    introFromPage: true,
    startWhen: ['vendors.list'],
    steps: [
      { target: 'vendors.tiles', title: 'What you owe', text: 'What you owe, what is overdue, what was delivered with no bill yet, and what you paid ahead.', mood: 'look' },
      { target: 'vendors.age', title: 'How long it waited', text: 'Unpaid bills and unbilled deliveries by how old they are. The red end is what to pay first.', mood: 'worry' },
      { target: 'vendors.view', title: 'Delivered, no bill', text: 'Material that came with no bill yet: chase the bill before you pay.', mood: 'worry' },
      { target: 'vendors.search', title: 'Find a supplier', text: 'By name, phone or GSTIN, or by kind.' },
      { target: 'vendors.sort', title: 'Sort', text: 'Most owed, most overdue, waiting longest, or the best score.' },
      { target: 'vendors.list', title: 'Each supplier', text: 'Open one for what you owe them, with their bills and payments.', mood: 'think' },
      { target: 'vendors.add', title: 'Add a supplier', text: 'Phone, GSTIN and credit days. A shop named on a delivery, an order or an expense is added by itself.' },
      { target: 'app.whatsapp', title: 'On WhatsApp', text: '"How much do we owe Malabar?" or "Paid Malabar 50,000 by UPI".', mood: 'happy' },
    ],
  },
  '/procurement/returns': {
    key: '/tour/returns',
    version: 1,
    introFromPage: true,
    startWhen: ['returns.list'],
    steps: [
      { target: 'returns.tiles', title: 'At a glance', text: 'Returns waiting for pickup, what suppliers owe you, and returns this month.', mood: 'look' },
      { target: 'returns.tabs', title: 'Where each return is', text: 'Open, waiting for pickup, sent back, settled.' },
      { target: 'returns.list', title: 'Each return', text: 'Its debit note lowers what you owe the supplier at once, until a replacement or a credit settles it.', mood: 'think' },
      { target: 'returns.act', title: 'Move it along', text: 'Print the debit note, mark it sent back, then settled when the replacement or credit comes.' },
      { target: 'app.whatsapp', title: 'Start one', text: 'Site says "12 steel bars bent, returning to KSL". From the office, start one from a GRN or the supplier\'s page.', mood: 'happy' },
    ],
  },

  // Cost control (SS-45): was the money spent matched by the work done?
  '/cost': {
    key: '/tour/cost',
    version: 1,
    introFromPage: true,
    startWhen: ['cost.stats', 'cost.empty'],
    steps: [
      { target: 'cost.empty', title: 'Start with a BOQ', text: 'Cost control sets the money spent against the BOQ. Add one first.', mood: 'think' },
      { target: 'cost.stats', title: 'At a glance', text: 'The budget, what the work done earned at BOQ rates, what was spent, what is ordered but not yet in, and how many projects are heading over.', mood: 'look' },
      { target: 'cost.projects', title: 'Worst first', text: 'Each project green or red by where it will finish. Tap one for its BOQ lines.' },
      { target: 'cost.pages', title: 'Look closer', text: 'Green / red by day, budget against actual, materials against the BOQ, and where the money went.' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"How is Green Villa doing on cost?"', mood: 'happy' },
    ],
  },
  '/cost/green-red': {
    key: '/tour/cost-green-red',
    version: 1,
    introFromPage: true,
    startWhen: ['gr.stats'],
    steps: [
      { target: 'project.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
      { target: 'gr.period', title: 'Which days', text: 'Yesterday, today, the last 7 or 30 days.' },
      { target: 'gr.stats', title: 'At a glance', text: 'The overall colour, the labour the work earned against the labour it cost, and how many lines are red or amber.', mood: 'look' },
      { target: 'gr.days', title: 'Each day', text: 'Tap a day to see only that day.' },
      { target: 'gr.lines', title: 'Lines, worst first', text: 'Green: the work earned at least the labour it cost. Amber: within 10%. Red: less, or labour with no work measured.', mood: 'think' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"Which work is over on labour this week?"', mood: 'happy' },
    ],
  },
  '/cost/budget': {
    key: '/tour/cost-budget',
    version: 1,
    introFromPage: true,
    startWhen: ['budget.kinds', 'budget.empty'],
    steps: [
      { target: 'project.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
      { target: 'budget.empty', title: 'Start with a BOQ', text: 'This project has no BOQ yet. Open it and bring the estimate Excel.', mood: 'think' },
      { target: 'budget.kinds', title: 'Labour, materials, subcontract', text: 'For each: the budget, what the work done earned, what was spent, and how far over or under.', mood: 'look' },
      { target: 'budget.lines', title: 'Every BOQ line', text: 'Planned, done and left; the budget, what it earned, and the labour spent on it.' },
      { target: 'budget.labour', title: 'Labour to check', text: 'Attendance on no BOQ line, or split by me from the day\'s work. Confirm it, or pick the line they worked on.', mood: 'think' },
      { target: 'app.whatsapp', title: 'On WhatsApp', text: '"Budget against spent for Green Villa?" or "Put today\'s 6 masons on ground-floor brickwork".', mood: 'happy' },
    ],
  },
  '/cost/materials': {
    key: '/tour/cost-materials',
    version: 1,
    introFromPage: true,
    startWhen: ['costmat.stats', 'costmat.empty'],
    steps: [
      { target: 'project.pick', title: 'Pick a project', text: 'This page works on one project at a time. Pick it here, or in the bar at the top.' },
      { target: 'costmat.empty', title: 'Materials for each BOQ line', text: 'Set what each line uses per unit on the BOQ, like cement bags per m³, and this page sets what was used against what the work needed.', mood: 'think' },
      { target: 'costmat.stats', title: 'At a glance', text: 'Materials used beyond what the work needed, within it, short to finish, and not judged.', mood: 'look' },
      { target: 'costmat.list', title: 'Worst first', text: 'Each material: used against what the work done needed. Red is more than 10% over.', mood: 'worry' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"Is cement use above the BOQ?"', mood: 'happy' },
    ],
  },
  '/cost/centres': {
    key: '/tour/cost-centres',
    version: 1,
    introFromPage: true,
    steps: [
      { target: 'centres.period', title: 'Which period', text: '7 or 30 days, this month, everything, or your own dates.' },
      { target: 'centres.total', title: 'Everything spent', text: 'The whole period in one bar, split by cost centre.', mood: 'look' },
      { target: 'centres.list', title: 'Where the money went', text: 'Materials, labour, subcontract, fuel, equipment, and what each is made of.' },
      { target: 'centres.categories', title: 'Expense categories', text: 'Each expense counts in its category\'s centre. Pick one for any category not set.', mood: 'think' },
      { target: 'app.whatsapp', title: 'Ask on WhatsApp', text: '"What did we spend on diesel this month?"', mood: 'happy' },
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
