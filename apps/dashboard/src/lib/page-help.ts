// UX-13 (asked 15 Nov 2026: "descriptions are bad for UI/UX: visual cues and simple language on the page, and a help
// button top right that explains each module page and each thing on it"). Pages carry no paragraphs; what each tile,
// tab, colour and button means lives here and shows in the ? help panel (components/help-button.tsx), beside the
// page's `about`, `example` and `whatsapp` from lib/module-map.ts.
//
// Keyed by the page's `url` in the module map (with ?view= for a view). Words stay short: one line per thing.

import type { GuideWords } from './start-mode'

export type HelpTone = 'good' | 'attention' | 'bad' | 'info'

export interface HelpPart {
  /** The name as it shows on the page: a tile, tab, column, colour or button. */
  name: string
  /** What it means, in a few plain words. */
  means: string
  /** The colour it carries on the page, so the help shows the same cue. */
  tone?: HelpTone
  /** UX-22: its `data-guide` marker on the page: the help lights it up when tapped (the build checks it exists). */
  find?: string
  /** UX-22: what it means for a kind of person (lib/start-mode.ts GuideWords); `null` leaves it out for them. */
  for?: Partial<Record<GuideWords, string | null>>
}

export interface PageHelp {
  /** What each thing on the page is. */
  parts?: HelpPart[]
  /** How to use the page, in order. */
  steps?: string[]
  /** Something people often get wrong, in one line. */
  tip?: string
  /** UX-22: the first thing this kind of person should hear about the page, in two lines at most: the page in real
   *  life (basics), where to start (steps), how their data comes in (data), what is different here (expert). */
  forYou?: Partial<Record<GuideWords, string>>
  /** UX-22: "How to use it" for a kind of person. */
  stepsFor?: Partial<Record<GuideWords, string[]>>
}

const SEE_MONEY = 'Rupees show only to owner, admin, finance and project managers.'

export const PAGE_HELP: Record<string, PageHelp> = {
  // ── Every day ────────────────────────────────────────────────────────────────────────────────────────────────
  '/today': {
    parts: [
      { name: 'This week', means: 'What needs you, worst first; tap a line to do it', find: 'today.week' },
      { name: 'Red line', means: 'Urgent: money at risk, short now, late', tone: 'bad' },
      { name: 'Reported', means: 'Sites that sent an update today', tone: 'good' },
      { name: 'Not reported', means: 'Sites that sent nothing yet', tone: 'attention' },
      { name: 'Workers', means: 'People on site today, from attendance' },
      { name: 'Work items', means: 'Pieces of work sites reported' },
      { name: 'Open issues', means: 'Problems still waiting for someone', tone: 'bad' },
    ],
    steps: ['Open a site to see its day.', 'Confirm the day so it goes into the evening report.'],
    tip: 'Pin any page to "Your pages" with the pin beside its name at the top.',
  },
  '/site/approvals': {
    parts: [
      { name: 'Kind tiles', means: 'One colour per kind; tap to show only those', find: 'approvals.kinds' },
      { name: 'Red edge', means: 'Urgent: late, flagged or overdue', tone: 'bad' },
      { name: 'Waited', means: 'Grey today, amber 3 days, red a week', tone: 'attention' },
      { name: 'Approve / Done', means: 'Decided right here, with the module\'s own rule', tone: 'good' },
      { name: 'Decide', means: 'A material request: order it, send from another site, or say no' },
      { name: 'Open / Review', means: 'Checked line by line on its own page' },
    ],
    steps: ['Start with Urgent.', 'Approve what is simple here; open the rest.'],
    tip: 'Nothing is approved in bulk. A rejection always asks why, and the person who asked is told.',
  },
  '/reports': {
    parts: [
      { name: 'Confirmed', means: 'The engineer checked the day', tone: 'good' },
      { name: 'Not confirmed', means: 'Still waiting for a check', tone: 'attention' },
      { name: 'Sent', means: 'The PDF went to the owner on WhatsApp', tone: 'info' },
      { name: 'Not reported', means: 'The site sent nothing that day', tone: 'bad' },
    ],
    steps: ['Pick a day or a status.', 'Open a report to read, fix or send it.'],
  },
  '/reports/period': {
    parts: [
      { name: 'Week / Month / Dates', means: 'The period the report covers' },
      { name: 'Green', means: 'Day confirmed with attendance', tone: 'good' },
      { name: 'Amber', means: 'Part of the day confirmed', tone: 'attention' },
      { name: 'Grey', means: 'Nothing confirmed that day' },
    ],
    steps: ['Pick the period.', 'Download the PDF or Excel, or send it.'],
    tip: 'Every figure comes from its own module. ' + SEE_MONEY,
  },
  '/issues': {
    parts: [
      { name: 'Not seen', means: 'Nobody has said they are on it', tone: 'attention', find: 'issues.states' },
      { name: 'Seen', means: 'Someone is on it, not fixed yet', find: 'issues.states' },
      { name: 'High or critical', means: 'Stops work: act first', tone: 'bad', find: 'issues.stats' },
      { name: 'Waiting 3+ days', means: 'Amber after a day, red after three', tone: 'bad' },
      { name: "Won't fix", means: 'Closed because it no longer matters (not "fixed")' },
    ],
    steps: ['Open an issue.', 'Give it to someone as a task, or mark it fixed.'],
  },
  '/site-log': {
    parts: [
      { name: 'Everything', means: 'All entries from site, newest first' },
      { name: 'Work', means: 'Only work done' },
      { name: 'Photos', means: 'Only entries with photos' },
    ],
    tip: 'A day in an approved report cannot be deleted: add a correction instead. The original is kept.',
  },
  '/analytics': {
    parts: [
      { name: 'Worker-days', means: 'People × days on site' },
      { name: 'Work items', means: 'Pieces of work reported' },
      { name: 'Issues reported', means: 'By how serious they were' },
      { name: 'Hours lost', means: 'Time lost to issues' },
    ],
  },
  '/live': {
    parts: [
      { name: 'Feed', means: 'Each message as it lands' },
      { name: 'What Mesiri understood', means: 'Workers, work, material and photos it took from the message' },
    ],
  },

  // ── Tasks ────────────────────────────────────────────────────────────────────────────────────────────────────
  '/tasks': {
    parts: [
      { name: 'Late', means: 'Past its day, not done', tone: 'bad' },
      { name: 'Due soon', means: 'Due in the next days', tone: 'attention' },
      { name: 'Blocked', means: 'Waiting on something else' },
    ],
    steps: ['Open a task.', 'Mark it started, blocked or done.'],
  },
  '/tasks?view=all': {
    parts: [
      { name: 'Quick add', means: 'What to do, who, by when' },
      { name: 'Late first', means: 'Then by the day it is due' },
    ],
    steps: ['Type the task and pick a person.', 'It stays here until it is done.'],
  },
  '/tasks?view=overdue': { parts: [{ name: 'Days late', means: 'How long past its day', tone: 'bad' }] },
  '/tasks?view=done': { parts: [{ name: 'Done', means: 'Finished tasks, newest first', tone: 'good' }] },

  // ── Plan ─────────────────────────────────────────────────────────────────────────────────────────────────────
  '/planning/setup': {
    steps: ['Set the stage and contract dates.', 'Upload the estimate Excel: it becomes the BOQ.', 'Make the schedule.', 'Add the site team and suppliers.'],
    tip: 'From then on, WhatsApp updates fill the schedule, the daily report and the cost.',
  },
  '/planning/schedule': {
    parts: [
      { name: 'Bar', means: 'One section of work, from start to end' },
      { name: 'Filled part', means: 'Work done, from site updates', tone: 'good' },
      { name: 'Late', means: 'Behind its planned dates', tone: 'bad' },
      { name: 'Critical', means: 'A delay here moves the handover', tone: 'attention' },
      { name: 'Forecast finish', means: 'When it will really end at this pace' },
    ],
    steps: ['Upload the estimate Excel: each section becomes a bar.', 'Use Quick plan to give each bar its days.', 'Site updates fill the bars in.'],
    tip: 'The owner and PM get the schedule on WhatsApp each morning.',
  },
  // UX-22: in the order they sit on the page, each lit up when tapped, and worded per kind of person.
  '/boq': {
    forYou: {
      basics:
        'Think of the building as a long shopping list: 60 cubic metres of concrete, 900 square metres of shuttering, each with a price. This page is that list: what the client pays, what it costs you, and how much the site has done.',
      steps: 'Start by uploading the estimate Excel. After that the page keeps itself up to date from what the site sends on WhatsApp.',
      data: 'Your estimate Excel becomes this page in one upload: Description, Unit, Qty and Rate columns are enough.',
      expert: 'Your BOQ or cost sheet, with one difference: progress is counted from the site\'s WhatsApp updates, not a measurement sheet.',
    },
    parts: [
      { name: 'Top numbers', means: 'Contract value, budget, margin and what the work done has earned', find: 'boq.totals', for: { basics: 'What the client pays, what it should cost you, what you keep, and what is done' } },
      { name: 'Section', means: 'A group of lines: "Concrete work", "Plastering", a floor', find: 'boq.section', for: { basics: 'A chapter of the work: the structure, the walls, a floor. Tap it to fold it', expert: null } },
      { name: 'Work', means: 'The work item and its quantity', find: 'boq.work', for: { basics: 'One job and how much of it: cum is a cubic metre, sqm a square metre', expert: null } },
      { name: 'Progress', means: 'Done so far, from site updates: blue under way, green done, orange over plan', tone: 'info', find: 'boq.progress', for: { basics: 'How much the site has done, filled from its WhatsApp messages' } },
      { name: 'Rate per unit', means: 'The client rate, with your budget cost under it', find: 'boq.rate', for: { basics: 'What the client pays for one unit; under it, what one unit costs you' } },
      { name: 'Value', means: 'Quantity × client rate; the gold bar is its size in the section', find: 'boq.value', for: { basics: 'What the whole line is worth to the client', expert: null } },
      { name: 'Margin', means: 'What the line leaves you: green healthy, orange under 5%, red a loss', tone: 'good', find: 'boq.margin', for: { basics: 'The money this line leaves you. Red means it loses money' } },
      { name: 'Site work to add', means: 'Work no line counts yet. Mesiri suggests the line; Add puts it on', tone: 'attention', find: 'boq.waiting', for: { basics: 'Work the site reported that no line counts yet. Check the line Mesiri guessed, then Add' } },
    ],
    steps: ['Upload the estimate Excel (Description, Unit, Qty, Rate).', 'Add budget rates.', 'Add "Materials per unit" on a line to plan materials.'],
    stepsFor: {
      basics: ['Upload the estimate Excel (ask whoever priced the job for it).', 'Check each line has two prices: the client\'s and your cost.', 'Let the site report work on WhatsApp: the bars fill by themselves.'],
      data: ['Upload the Excel: one row per item with Description, Unit, Qty and Rate.', 'Check what Mesiri read, then save.', 'Fill in the lines with no budget rate ("Lines priced" shows how many).'],
      expert: ['Import the BOQ from Excel.', 'Add budget rates per line, or its labour, material and subcontract parts.', 'Add material norms per line to drive the material plan.'],
    },
    tip: SEE_MONEY,
  },
  '/planning/materials': {
    parts: [
      { name: 'Order now', means: 'Short before a new order can arrive', tone: 'bad' },
      { name: 'This week', means: 'Order-by day within 7 days', tone: 'attention' },
      { name: 'Later', means: 'Runs short later in these weeks', tone: 'info' },
      { name: 'Covered', means: 'Stock + orders last these weeks', tone: 'good' },
      { name: 'Bar', means: 'Green in stock, blue on order, red short' },
      { name: 'Weeks', means: 'Darker needs more; red from the short week' },
      { name: 'Truck', means: 'Days the supplier takes to deliver' },
    ],
    steps: ['Pick a project.', 'Start with Order now.', 'Tap Order: the form is filled in.'],
    tip: 'Empty? On the BOQ, open a line\'s "Materials per unit" (1 cum of M20 = 8 bags cement).',
  },
  '/planning/live': {
    parts: [
      { name: 'Not started', means: 'No work reported there' },
      { name: 'Under way', means: 'Some work reported', tone: 'attention' },
      { name: 'Done', means: 'Work finished', tone: 'good' },
      { name: 'Photos', means: 'Site photos for that room or footing' },
    ],
    steps: ['Upload floor plans in Documents.', 'Track the drawing.', 'Site updates colour each room.'],
  },
  '/planning/places': {
    parts: [
      { name: 'Floors', means: 'Done when every room on it is', tone: 'good' },
      { name: 'Rooms', means: 'Each room with its work and photos' },
      { name: 'Under way', means: 'Work started, not finished', tone: 'attention' },
    ],
    tip: 'Site names the place in an update: "FF R2 tiling 40 sqft".',
  },
  '/planning/drawing-check': {
    parts: [
      { name: 'Ask', means: 'Something to ask the architect', tone: 'bad' },
      { name: 'Check', means: 'Worth a second look', tone: 'attention' },
      { name: 'Info', means: 'Read from the drawing, no problem' },
      { name: 'Cement / Steel', means: 'Net quantities from the drawing' },
    ],
    steps: ['Drop the architect\'s PDF.', 'Read the questions before it reaches site.'],
    tip: 'Quantities are net, not a design check: add your usual wastage.',
  },
  '/planning/documents': {
    parts: [
      { name: 'Revision', means: 'A new upload marks the old one out of date' },
      { name: 'Expiry', means: 'Permits turn red before they expire', tone: 'bad' },
      { name: 'Office only', means: 'Contract and estimate: site staff never see them' },
    ],
  },

  // ── Cost ─────────────────────────────────────────────────────────────────────────────────────────────────────
  '/cost': {
    parts: [
      { name: 'Budget', means: 'What the BOQ says it should cost' },
      { name: 'Earned', means: 'Budget for the work already done' },
      { name: 'Spent', means: 'Money already gone' },
      { name: 'Committed', means: 'Ordered, not paid yet' },
      { name: 'Over budget', means: 'Spending more than the work earned', tone: 'bad' },
      { name: 'Forecast', means: 'Spent + work left at today\'s pace' },
    ],
    tip: SEE_MONEY,
  },
  '/cost/green-red': {
    parts: [
      { name: 'Green', means: 'Labour cost less than the work earned', tone: 'good' },
      { name: 'Amber', means: 'A little over', tone: 'attention' },
      { name: 'Red', means: 'Well over: worth asking why', tone: 'bad' },
      { name: 'Labour earned', means: 'Work measured × labour budget rate' },
      { name: 'Labour spent', means: 'Attendance on the line × wage' },
    ],
    steps: ['Pick a site in the top bar.', 'Pick a day or period.', 'Open a red line to see why.'],
  },
  '/cost/budget': {
    parts: [
      { name: 'Budget', means: 'From the BOQ budget rates' },
      { name: 'Earned', means: 'Budget for the work done' },
      { name: 'Actual', means: 'Money spent' },
      { name: 'Labour vs earned', means: 'Earned minus spent: under is good', tone: 'good' },
      { name: 'Forecast', means: 'Spent, plus the work left at the rate so far' },
      { name: 'Labour not on a line', means: 'Attendance of the last 30 days no BOQ line carries yet', tone: 'attention' },
    ],
    steps: ['Pick a project.', 'Under Labour not on a line, pick the line they worked on and press Put on line.', "Confirm Mesiri's split where it made one, or split a day by man-days."],
    tip: SEE_MONEY,
  },
  '/cost/materials': {
    parts: [
      { name: 'Within the norm', means: 'Used about what the work needed', tone: 'good' },
      { name: 'Used beyond the work', means: 'More used than the BOQ norm', tone: 'bad' },
      { name: 'Short to finish', means: 'Still needed beyond stock and orders', tone: 'attention' },
      { name: 'Not judged', means: 'Not enough work done to tell' },
      { name: 'Needed by the work done', means: "Work measured × the line's materials per unit, with wastage" },
    ],
    tip: 'When to order is on Planning › Material plan.',
  },
  '/cost/centres': {
    parts: [
      { name: 'Cost centre', means: 'The bucket a cost counts in: materials, labour, fuel' },
      { name: 'Not set', means: 'Spending with no bucket yet', tone: 'attention' },
      { name: 'Expense categories', means: 'An expense counts in the centre of its category' },
    ],
    tip: 'Deliveries, attendance and machines find their centre by themselves. A subcontract bill is always Subcontract.',
  },

  // ── Materials ────────────────────────────────────────────────────────────────────────────────────────────────
  '/materials?view=stock': {
    parts: [
      { name: 'Out of stock', means: 'Nothing left on site', tone: 'bad' },
      { name: 'Running low', means: 'Lasts only a few days', tone: 'attention' },
      { name: 'Below minimum', means: 'Under the level you set', tone: 'attention' },
      { name: 'Coming on orders', means: 'Ordered, not arrived yet', tone: 'info' },
      { name: 'Asked for', means: 'Sites requested it' },
      { name: 'Minimum', means: 'Below it, the office gets a note each morning with a draft request' },
      { name: 'Days chip', means: 'How long it lasts: red under 3, amber under 7', tone: 'attention' },
      { name: 'Move from …', means: 'Another site holds spare: one transfer' },
      { name: 'Order …', means: 'A purchase order filled in for a low site' },
      { name: 'Bars / Numbers', means: 'A card per material, or the full table' },
    ],
    steps: ['Record a delivery or opening stock.', 'Or import your list from Excel in Items.'],
  },
  '/materials?view=movements': {
    parts: [
      { name: '+ In', means: 'Delivery, opening stock or transfer in', tone: 'good' },
      { name: '− Out', means: 'Used, wasted or sent to another site', tone: 'bad' },
      { name: 'Correction', means: 'A fix added beside the original: nothing is edited' },
      { name: 'Kind chips', means: 'Deliveries, used, moves, other; tap to filter' },
      { name: 'Day chart', means: 'In above the line, out below, per day' },
      { name: 'Material or site name', means: 'Tap it to see only that' },
    ],
    tip: 'Only the newest entries show: pick a material, a site or shorter dates to see all.',
  },
  '/materials?view=items': {
    parts: [
      { name: 'Main category › sub-category', means: 'Sizes and types are separate items' },
      { name: 'Stop offering it', means: 'Hide an item that has records; its records stay' },
      { name: 'No rate', means: 'Never bought with a price', tone: 'attention' },
      { name: 'No minimum', means: 'Held somewhere, no minimum set' },
      { name: 'Not used 90 d', means: 'Nothing used in 90 days' },
    ],
    steps: ['Start with the standard builder list, or add your own.', 'Or import one Excel: items, vendors, opening stock.'],
  },
  '/materials/requests': {
    parts: [
      { name: 'Waiting for the office', means: 'Not ordered yet', tone: 'attention' },
      { name: 'Late', means: 'Needed by a day already gone', tone: 'bad' },
      { name: 'Due in 2 days', means: 'Needed soon', tone: 'attention' },
      { name: 'Ordered', means: 'A PO is placed', tone: 'info' },
      { name: 'Received', means: 'It came to site', tone: 'good' },
      { name: 'Possible duplicates', means: 'Same item asked twice' },
      { name: 'Waited chip', means: 'Grey under a day, amber a day, red two', tone: 'attention' },
      { name: 'Office orders in', means: 'Average time from asked to ordered, 30 days' },
      { name: 'In plan / Above plan', means: 'Against the project\'s material plan', tone: 'info' },
      { name: 'Order together', means: 'Tick requests at one site, one order' },
    ],
    steps: ['Open a request.', 'Order it, or turn it down.', 'Several at one site: tick them, Order together.'],
  },
  '/materials/counts': {
    parts: [
      { name: 'Difference', means: 'Counted minus the book, in rupees', tone: 'attention' },
      { name: 'Approve', means: 'Puts the book right' },
      { name: 'Site card chip', means: 'Never or 30+ days red, 20+ amber', tone: 'bad' },
      { name: 'Count all / Top 20', means: 'Starts the count in one tap' },
      { name: 'Red / green ₹', means: 'Stock lost / found' },
    ],
    steps: ['Tap Count all on a site.', 'Type what is really there.', 'Approve the differences.'],
  },
  '/materials/value': {
    parts: [
      { name: 'Value', means: 'On hand × last rate' },
      { name: 'Slow moving', means: 'Little used in 30 days', tone: 'attention' },
      { name: 'Split bar', means: 'A material\'s value by site' },
      { name: 'Move to …', means: 'Unused here, used at that site' },
      { name: 'Materials / Sites / Categories', means: 'Where the money in stock sits' },
    ],
    tip: 'Value comes from deliveries with a rate. ' + SEE_MONEY,
  },

  // ── Procurement ──────────────────────────────────────────────────────────────────────────────────────────────
  '/procurement/orders': {
    parts: [
      { name: 'Still to come', means: 'Ordered, not fully arrived', tone: 'info' },
      { name: 'Late', means: 'Past its delivery date', tone: 'bad' },
      { name: 'Due in 2 days', means: 'Arrives soon', tone: 'attention' },
      { name: 'Part received', means: 'Some came, some still to come' },
      { name: 'Material came', means: 'Record a delivery against the order' },
      { name: 'Came, not billed', means: 'Delivered, no supplier bill yet', tone: 'attention' },
      { name: 'Three dots', means: 'Ordered · came · billed', tone: 'good' },
      { name: '% dearer / Best rate', means: 'Against the best rate paid for it', tone: 'bad' },
      { name: 'Score', means: 'The supplier\'s score out of 5' },
    ],
    steps: ['New order, or order from a request.', 'Send it to the supplier on WhatsApp.', 'Tap "Material came" when it arrives.'],
  },
  '/procurement/grn': {
    parts: [
      { name: 'Accepted', means: 'Taken into stock', tone: 'good' },
      { name: 'Rejected', means: 'Sent back, not paid for', tone: 'bad' },
      { name: 'Challan', means: 'The supplier\'s delivery note photo' },
    ],
    steps: ['Open an order.', 'Tap "Material came".'],
  },
  '/procurement/pending': {
    parts: [
      { name: 'Late', means: 'Past its date', tone: 'bad' },
      { name: 'Due today', means: 'Should arrive today', tone: 'attention' },
      { name: 'This week / Later', means: 'Still on time' },
      { name: 'Chase', means: 'One WhatsApp message to the shop' },
      { name: 'Week', means: 'Late, then the next seven days' },
      { name: 'Tell site', means: 'The day\'s deliveries to site on WhatsApp' },
      { name: '% on time', means: 'A supplier that is often late', tone: 'attention' },
    ],
  },
  '/procurement/rates': {
    parts: [
      { name: 'Rates went up', means: 'Paid more than last time', tone: 'bad' },
      { name: 'Rates went down', means: 'Paid less than last time', tone: 'good' },
      { name: 'Cheaper elsewhere', means: 'Another supplier sold it for less', tone: 'good' },
      { name: 'Items bought', means: 'Total spend in the dates picked' },
    ],
    tip: 'A rate shows once a delivery has a price: on WhatsApp, from a bill photo, or on an order.',
  },
  '/procurement/quotations': {
    parts: [
      { name: 'Waiting for quotes', means: 'Sent, no reply yet', tone: 'attention' },
      { name: 'Quotes overdue', means: 'Reply date gone', tone: 'bad' },
      { name: 'Ready to compare', means: 'Enough quotes in', tone: 'good' },
      { name: 'Cost to you', means: 'Before GST from a GST supplier (you claim it back), with GST from one without' },
    ],
    steps: ['Ask for quotes from a few shops.', 'Record their rates, or forward the quote to Mesiri.', 'Order the cheapest.'],
  },
  '/finance/vendors': {
    parts: [
      { name: 'Owed', means: 'What you still have to pay them', tone: 'attention' },
      { name: 'Overdue', means: 'Bills past their due day', tone: 'bad' },
      { name: 'Score', means: 'On time, right quantity, right rate' },
      { name: 'Switched off', means: 'No longer offered; records kept' },
      { name: 'Bill', means: 'An expense with this supplier, or their bill for deliveries' },
      { name: 'Opening balance', means: 'What was owed before Mesiri: set it in Edit details' },
      { name: 'Not billed', means: 'Delivered with a rate, no bill yet: tick them when the bill comes, so nothing counts twice', tone: 'attention' },
    ],
    tip: 'A supplier with records is never deleted: switch it off, or merge a duplicate. Undoing a payment opens its bills again.',
  },
  '/procurement/returns': {
    parts: [
      { name: 'Waiting for pickup', means: 'Ready to go back', tone: 'attention' },
      { name: 'Sent back', means: 'Gone back to the supplier', tone: 'info' },
      { name: 'Settled', means: 'Replaced or credited', tone: 'good' },
      { name: 'Debit note', means: 'Lowers what you owe them at once' },
    ],
    steps: ['Start a return from the GRN, a delivery or the supplier.', 'Or say it on WhatsApp.'],
  },

  // ── Labour ───────────────────────────────────────────────────────────────────────────────────────────────────
  '/labour': {
    parts: [
      { name: 'Man-days', means: 'People × days' },
      { name: 'Days reported', means: 'Days the site sent attendance' },
      { name: 'Average a day', means: 'People on an average day' },
    ],
    tip: 'Sites send it on WhatsApp: "24 workers today: 8 mason, 12 helper, 4 carpenter".',
  },
  '/labour?view=muster': {
    parts: [
      { name: 'P', means: 'Present', tone: 'good' },
      { name: '½', means: 'Half day', tone: 'attention' },
      { name: 'A', means: 'Absent', tone: 'bad' },
      { name: 'A number', means: 'How many came in a headcount group' },
      { name: 'Ringed', means: 'Overtime' },
    ],
    tip: 'Fills itself from attendance. Export it for the contractor or the labour office.',
  },
  '/labour?view=workers': {
    parts: [
      { name: 'Working', means: 'On the active register', tone: 'good' },
      { name: 'Make inactive', means: 'Leaves the register; their days stay' },
    ],
    tip: 'Optional: headcounts work without names. Add names to track days and wages per person.',
  },
  '/labour?view=teams': {
    parts: [
      { name: 'Team', means: 'A labour contractor and his people' },
      { name: 'Man-days', means: 'From attendance' },
    ],
    tip: 'A team is paid through its contractor; advances come back off its wages.',
  },
  '/labour/wages': {
    parts: [
      { name: 'Man-days', means: 'From attendance' },
      { name: 'Wages + overtime', means: 'Days × wage, plus overtime' },
      { name: 'Advance back', means: 'Taken off this week' },
      { name: 'To pay', means: 'What is left to hand over', tone: 'attention' },
      { name: 'Paid', means: 'Handed over', tone: 'good' },
    ],
    steps: ['Pick a site and a week.', 'Approve.', 'Pay from cash or bank, and send the slip.'],
  },
  '/labour/advances': {
    parts: [
      { name: 'Given', means: 'Money handed over before payday' },
      { name: 'Outstanding', means: 'Still to come back', tone: 'attention' },
    ],
    tip: 'It comes back off their next wages on its own.',
  },

  // ── Subcontract ──────────────────────────────────────────────────────────────────────────────────────────────
  '/subcontract/teams': {
    parts: [
      { name: 'Edge colour', means: 'The team\'s worst job: late, over-billed, bill to check, retention due, idle' },
      { name: 'Late', means: 'Past its end date, not done', tone: 'bad' },
      { name: 'Idle', means: 'Nothing measured for 14 days', tone: 'attention' },
      { name: 'Green bar', means: 'Paid', tone: 'good' },
      { name: 'Blue bar', means: 'Billed, not paid yet', tone: 'info' },
      { name: 'Striped bar', means: 'Done, not billed: you will owe it', tone: 'attention' },
      { name: 'Rates by work', means: 'The same work across teams, cheapest first' },
    ],
    steps: ['Start with the coloured teams.', 'Tap the button on a card for its next step.'],
  },
  '/subcontract/work-orders': {
    parts: [
      { name: 'Work order', means: 'Who does which work at what rate' },
      { name: 'Measured', means: 'Work counted on site', tone: 'good' },
      { name: 'Bills to check', means: 'Waiting for you before pay', tone: 'attention' },
      { name: 'Over measured / agreed', means: 'Bill asks for more than done or agreed', tone: 'bad' },
      { name: 'Retention held', means: 'Kept back until the work is accepted' },
      { name: 'Done, not billed', means: 'Measured but not billed yet', tone: 'attention' },
      { name: 'Late', means: 'Past its end date, not done', tone: 'bad' },
    ],
    steps: ['New work order: work, rate, quantity.', 'Site measures the work.', 'Their bill is checked against it before pay.'],
  },
  '/subcontract/bills': {
    tip: 'Each bill here did not pass its check, or came from the subcontractor: a person decides before anything is paid.',
    parts: [
      { name: 'Passed', means: 'Matches measured work and rate', tone: 'good' },
      { name: 'Did not pass', means: 'Asks for more: a person decides', tone: 'bad' },
      { name: 'Green / red bar', means: 'Billed within / beyond what was measured', tone: 'bad' },
      { name: 'Line on the bar', means: 'The quantity agreed' },
      { name: 'Checked', means: 'Bills already decided, with who and why' },
    ],
  },

  // ── Money ────────────────────────────────────────────────────────────────────────────────────────────────────
  '/finance/expenses': {
    parts: [
      { name: 'With bill photo', means: 'Proof attached', tone: 'good' },
      { name: 'No bill photo', means: 'Ask for the bill', tone: 'attention' },
      { name: 'WhatsApp', means: 'Came from a site message' },
    ],
  },
  '/finance/money': {
    parts: [
      { name: 'In the bank', means: 'Company bank accounts' },
      { name: 'Petty cash', means: 'Each site\'s cash box' },
      { name: 'Low cash', means: 'Below the amount set in Settings', tone: 'attention' },
      { name: 'Owed back to staff', means: 'They paid from their own pocket', tone: 'attention' },
      { name: 'Unpaid bills', means: 'Bills not paid yet', tone: 'bad' },
    ],
    steps: ['Add the bank account and each site\'s petty cash.', 'Every expense then says where the money came from.'],
  },
  '/finance/settings': {
    parts: [
      { name: 'Categories', means: 'An expense with no category is "Uncategorized"' },
      { name: 'Low cash', means: 'A site cash box below this shows as low' },
      { name: 'TDS 194C', means: '1% individual / HUF, 2% firm; set per work order' },
    ],
  },
  '/accounts/projects': {
    tip: 'Books profit leaves out deliveries and wages not billed yet: read it beside the real margin.',
    parts: [
      { name: 'Direct cost', means: 'Site cost: materials, labour, subcontract' },
      { name: 'Indirect cost', means: 'Office costs on the project, with any head-office share' },
      { name: 'Real margin', means: 'Work done at client rates less the full cost so far' },
      { name: 'Not billed', means: 'Measured work on no RA bill yet: raise it', tone: 'attention' },
      { name: '7d', means: 'Age of the oldest unpaid bill: amber after 30, red after 60' },
      { name: 'Finish vs budget', means: 'Forecast at completion against the BOQ budget', tone: 'bad' },
      { name: 'At risk', means: 'Losing money or 10% over budget', tone: 'bad' },
      { name: 'Watch', means: 'Heading over, thin margin or cost ahead of work', tone: 'attention' },
    ],
  },
  '/accounts/ledgers': {
    parts: [
      { name: 'Clients owe us', means: 'Money to come in', tone: 'info' },
      { name: 'We owe suppliers', means: 'Money to go out', tone: 'attention' },
    ],
    tip: 'Posted from your records on their own: nothing to type. Every figure opens its entries.',
  },
  '/accounts/cash-flow': {
    parts: [
      { name: 'Coming in', means: 'RA bills sent and not paid, on the day the client usually pays', tone: 'good', find: 'cashflow.stats' },
      { name: 'Going out', means: 'Supplier and subcontractor bills after their credit days, orders, wages', tone: 'bad', find: 'cashflow.stats' },
      { name: 'Lowest point', means: 'The least cash left at a week\'s end; red when it runs out' },
      { name: 'Clients pay in', means: 'Days after a bill the client pays; change it to see a slower client', find: 'cashflow.assume' },
      { name: '≈', means: 'A guessed date: no credit days set, no expected day on the order, or an estimate' },
      { name: 'One project picked', means: 'Its money in and out only: the bank is the company\'s' },
    ],
    steps: ['See the week the cash runs short.', 'Open it: chase a client bill, or move a payment.'],
  },
  '/billing/variations': {
    parts: [
      { name: 'With the client', means: 'Sent, not answered yet; chased after 14 days', tone: 'attention', find: 'variations.states' },
      { name: 'Approved', means: 'On the BOQ: a VO line, or more of a line', tone: 'good', find: 'variations.states' },
      { name: 'Margin', means: 'Amount less our cost, when our cost is priced: green 15% and up' },
      { name: 'Billed', means: 'How much of an approved new item RA bills have taken' },
    ],
    steps: ['Record what the client asked, with its price.', 'Mark it sent, then approved: it goes on the BOQ.', 'The site does it; the next RA bill bills it.'],
  },
  '/accounts/receivables': { parts: [{ name: 'Clients owe', means: 'RA bills sent, not paid', tone: 'attention' }, { name: 'Overdue', means: 'Past the due day', tone: 'bad' }] },
  '/accounts/cash-bank': {
    tip: 'The same balances as Finance › Money. Tap an account for its book, day by day.', parts: [{ name: 'Opening / Closing', means: 'Balance at the start and end' }, { name: 'Money in', means: 'Received', tone: 'good' }, { name: 'Money out', means: 'Paid', tone: 'bad' }] },
  '/accounts/day-book': { parts: [{ name: 'Vouchers', means: 'Every entry of the day' }, { name: 'Total moved', means: 'All money in and out' }] },
  '/accounts/tally': {
    parts: [
      { name: 'Expense', means: 'A Journal: category debit, supplier credit; included GST to "Input GST"' },
      { name: 'Payment', means: 'A Payment: supplier debit, bank or cash credit' },
      { name: 'RA bill', means: 'A Sales voucher; money received is a Receipt' },
      { name: 'Ledgers', means: 'Come first: suppliers under Sundry Creditors' },
    ],
    steps: ['Pick the month.', 'Download the file.', 'Your accountant imports it in Tally.'],
    tip: 'One way only. Import each period once, or it makes duplicates.',
  },
  '/accounts/gst': {
    tip: 'The CA files the return: check purchases against GSTR-2B before claiming.',
    steps: ['Set the company GSTIN: GST then splits into IGST or CGST + SGST.'],
    parts: [
      { name: 'Output GST', means: 'GST on your RA bills' },
      { name: 'Input GST', means: 'GST on purchases you can claim', tone: 'good' },
      { name: 'Credit missed', means: 'Bills with GST not claimed', tone: 'attention' },
    ],
  },
  '/accounts/tds': {
    parts: [
      { name: 'Deducted from subcontractors', means: 'You must deposit it' },
      { name: 'Deducted by clients', means: 'Clients kept it from your bills' },
      { name: 'Late', means: 'Deposit date gone', tone: 'bad' },
    ],
    steps: ['TDS is deducted when a subcontractor bill is checked.', 'Deposit it with a transfer into "TDS payable" in Finance › Money.', 'Match with Form 26AS / 16A before claiming.'],
  },
  '/accounts/pl': {
    parts: [{ name: 'Income', means: 'RA bills sent, before GST' }, { name: 'Costs', means: 'Bills and expenses as booked, net of GST you claim' }, { name: 'Gross profit', means: 'Income minus direct costs', tone: 'good' }],
    steps: ['Simple, Tally or Month by month: same numbers, the page remembers your pick.', 'Tap a line for what is in it, an account for its entries, an entry for its voucher.', 'Tap a part of the ₹100 bar to open that line.'],
    tip: 'Labour reaches the books when wages are paid.',
  },
  '/accounts/balance-sheet': {
    parts: [{ name: 'Owns', means: 'Bank, cash, what clients owe' }, { name: 'Owes', means: 'Suppliers, taxes, loans, other dues' }, { name: 'Worth', means: 'What you own less what you owe: money put in and profit kept' }, { name: 'A minus under owed', means: 'A supplier paid ahead (an advance)' }],
    steps: ['Simple or Tally: same numbers, the page remembers your pick.', 'Tap a line for its accounts, an account for its entries, an entry for its voucher.'],
    tip: 'A project has no balance sheet of its own: see its position under Projects.',
  },
  '/accounts/trial-balance': {
    steps: ['Tap a ledger for every entry in it.'],
    tip: "Groups follow Tally's. Income and expense ledgers start each April at nil.",
    parts: [{ name: 'Debits / Credits', means: 'Must be equal' }, { name: 'Head office and other projects', means: 'What moved between this project and the rest of the company' }, { name: 'Differs from its module', means: 'Often a payment saved with no account, or a record before an opening balance', tone: 'attention' }],
  },
  '/accounts/chart': {
    parts: [{ name: 'Group', means: 'Tally\'s own groups, so your CA reads it as theirs' }],
    tip: 'Each supplier, client, account and category gets its ledger the first time it is needed.',
  },
  '/accounts/periods': {
    parts: [{ name: 'Closed', means: 'No more changes to that month', tone: 'good' }, { name: 'Changed after close', means: 'Someone edited a closed month', tone: 'bad' }],
    steps: ['Close a month once the CA has checked it.'],
    tip: 'A bill changed after its month closed stops nothing on site: the difference is posted on the first open day.',
  },
  '/billing/clients': { parts: [{ name: 'Contract value', means: 'What the client agreed to pay' }, { name: 'Retention', means: 'Share kept back until defects end' }] },
  '/billing/ra-bills': {
    parts: [
      { name: 'Draft', means: 'Prints marked DRAFT', tone: 'attention' },
      { name: 'Sent', means: 'Gone to the client', tone: 'info' },
      { name: 'Passed', means: 'Amount the client\'s engineer passed' },
      { name: 'Quantities', means: "What site measured since the last bill: change one if the client's engineer measured differently" },
    ],
    steps: ['Set the client and contract terms first.', 'New RA bill: it prices the work measured since the last bill.', 'Submit to send.'],
  },
  '/billing/client-view': {
    parts: [
      { name: 'Link', means: 'Opens on the client\'s phone, no login' },
      { name: 'They see', means: 'Progress, photos you approved, bills, payments' },
      { name: 'Never', means: 'Your rates, costs or suppliers', tone: 'bad' },
    ],
  },

  // ── Equipment ────────────────────────────────────────────────────────────────────────────────────────────────
  '/equipment': {
    parts: [
      { name: 'Working today', means: 'Logged hours today', tone: 'good' },
      { name: 'Broken down', means: 'Stopped: on Issues', tone: 'bad' },
      { name: 'Not logged today', means: 'No hours sent yet', tone: 'attention' },
      { name: 'Service due', means: 'Needs its service' },
    ],
    steps: ['Add the machine: owned or hired, with its rate.', 'Site logs its day here or on WhatsApp.'],
  },
  '/equipment/log': { parts: [{ name: 'Worked', means: 'Hours working', tone: 'good' }, { name: 'Idle', means: 'On site, not working', tone: 'attention' }, { name: 'Breakdown', means: 'Hours stopped', tone: 'bad' }] },
  '/equipment/hire': {
    parts: [
      { name: 'Matches', means: 'Bill = hours logged × rate', tone: 'good' },
      { name: 'Bill is more', means: 'Asking more than logged', tone: 'bad' },
      { name: 'Not billed yet', means: 'Hours with no bill', tone: 'attention' },
    ],
    steps: ["Enter the hire company's bill: it is checked against the hours logged.", "Pay it from the hire company's page in Finance › Suppliers."],
    tip: 'Minimum hours a day are charged even when it works less. Breakdown hours are never charged.',
  },
  '/equipment/vehicles': { parts: [{ name: 'Trips', means: 'Loads carried today' }, { name: 'Diesel', means: 'Litres filled' }] },
  '/equipment/assets': {
    parts: [{ name: 'At site', means: 'Plates, props, scaffolding per site' }, { name: 'Categories that come back', means: 'A main category includes its sub-categories' }],
    tip: 'Move them with a material transfer. Lost or damaged: record a usage marked wastage.',
  },

  // ── Settings ─────────────────────────────────────────────────────────────────────────────────────────────────
  '/settings': { parts: [{ name: 'Modules', means: 'Switched on by the Mesiri team: ask us to add one' }] },
  '/projects': {
    parts: [{ name: 'Site', means: 'Where updates land; a project needs one' }, { name: 'Archive', means: 'Leaves the list; its records stay' }],
    steps: ['Add a project.', 'Add its sites.', 'Add who reports from each.'],
  },
  '/team': {
    parts: [
      { name: 'Site staff', means: 'Only a name and WhatsApp number' },
      { name: 'Web login', means: 'Only for people who use this dashboard' },
      { name: 'No number', means: 'Cannot send updates from site', tone: 'attention' },
    ],
  },
  '/company': { parts: [{ name: 'Logo', means: 'Top left of every PDF. PNG, JPEG or WebP, up to 700 KB' }, { name: 'GSTIN', means: 'Printed on bills and letterhead' }] },
  '/whatsapp': {
    tip: 'Set up a scheduled message by telling Mesiri on WhatsApp.',
    parts: [
      { name: 'Not handled', means: 'Mesiri could not file it', tone: 'bad' },
      { name: 'Not on team', means: 'Number unknown: add them in Team', tone: 'attention' },
      { name: 'Automations', means: 'Messages sent on a schedule' },
    ],
  },
  '/bring-data': {
    steps: ['Projects and sites: type them.', 'Team: share contacts on WhatsApp.', 'Materials and vendors: one Excel.', 'Anything else: send the file on WhatsApp.'],
  },
  '/settings/activity': { parts: [{ name: 'Web / WhatsApp', means: 'Where the change was made' }], tip: 'Read only. For the owner and admins.' },
}

export function helpFor(url: string | undefined, pathname: string): PageHelp | undefined {
  return (url && PAGE_HELP[url]) || PAGE_HELP[pathname]
}
