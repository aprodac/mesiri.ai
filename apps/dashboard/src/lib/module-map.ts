import {
  AlertCircle,
  BarChart3,
  BookOpenCheck,
  Boxes,
  Calculator,
  CalendarDays,
  AlarmClock,
  CircleCheck,
  ClipboardCheck,
  ClipboardList,
  FileSearch,
  FileText,
  Gauge,
  HardHat,
  FolderOpen,
  Layers,
  MapPinned,
  PackageSearch,
  Handshake,
  Landmark,
  ReceiptText,
  ShoppingCart,
  Truck,
  Activity,
  CalendarRange,
  ListTodo,
  ListChecks,
  ShieldAlert,
  Rocket,
  Stamp,
  Settings as SettingsIcon,
  type LucideIcon,
} from 'lucide-react'
import type { ModuleKey } from './modules'

// The construction-ERP module map (WEB-72): every module and page a contractor's ERP has, that
// Mesiri builds now (V1) or next (V1.5). Studied 6 Nov 2026 from Powerplay, Onsite, Indian
// construction ERPs and Procore/Buildertrend; the full map, with Later and Not-planned pages,
// is the "Construction ERP Map" reference page. One list drives the preview sidebar, the
// placeholder routes, the top-bar breadcrumb and the placeholder pages, so a page is named
// once. When a planned page is built, change its `status` to 'built' and point `url` at it.

/** Mirrors backend EXPENSE_VIEW_ROLES: pages that show rates, margins or money owed. */
export const MONEY_ROLES = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE', 'PROJECT_MANAGER'] as const
// NXT-01/02: client contracts and bills (D-N3 default; backend may_manage_money).
const BILLING_ROLES = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] as const
const MANAGERS = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER'] as const

export type PageStatus = 'built' | 'planned'
export type Phase = 'V1' | 'V1.5' | 'Later'

export interface ModulePage {
  title: string
  /** Address, with ?view= for a view of a built page. Planned pages own their path. */
  url: string
  status: PageStatus
  phase: Phase
  /** What question the page answers, in one sentence (shown on the placeholder). */
  about: string
  /** The same, on a real site. */
  example: string
  /** A WhatsApp message that fills this page, shown in the page's help (UX-08). */
  whatsapp?: string
  /** Tracker IDs (docs/plans/V1_TRACKER.md). */
  tracker?: string
  /** Only these roles see it (the API refuses the rest). */
  roles?: readonly string[]
  /** A shorter name for the sidebar, when the title is long. */
  navTitle?: string
  /** Also listed in this module's menu, but its home is another module (breadcrumb, counts). */
  shortcut?: boolean
  /** Built pages that already hold part of this, linked from the placeholder. */
  related?: { title: string; url: string }[]
  /** Hidden when the company has this module switched off, when it differs from its group's (Accounts, ACC). */
  module?: ModuleKey
}

export interface ModuleGroup {
  key: string
  title: string
  icon: LucideIcon
  /** Icon colour in the sidebar (see NAV_TONES there). */
  tone: 'orange' | 'sky' | 'rose' | 'emerald' | 'violet' | 'amber' | 'green' | 'teal' | 'indigo'
  /** What the module is for, in one line. */
  about: string
  /** Hidden when the company has this module switched off (WEB-02). */
  module?: ModuleKey
  /** Where the module sits in the project's story (UX-04, docs/plans/ui-story-plan.md section 4): the sidebar
   *  shows the daily pages, then PLAN, SITE, BUY, MONEY, then Settings. */
  section: NavSection
  /** Its pages are its section's rows, with no drawer (Tasks: a section of its own, Adarsh 9 Nov 2026). */
  flat?: boolean
  pages: ModulePage[]
}

/** The sidebar's sections, in the order of a project's life (UX-04). */
export type NavSection = 'daily' | 'tasks' | 'plan' | 'site' | 'buy' | 'money' | 'settings'

export const SECTION_TITLES: Record<NavSection, string> = {
  daily: 'Every day',
  tasks: 'Tasks',
  plan: 'Plan',
  site: 'Site',
  buy: 'Buy',
  money: 'Money',
  settings: 'Settings',
}

/** Each role's day comes first (UX-04/UX-11): the same sections, in the order the role reaches for them. */
export const SECTION_ORDER: Record<string, NavSection[]> = {
  // Tasks (who does what by when) comes first for everyone who gives or does them; finance neither gives nor does
  // one, so it comes last for them.
  ADMIN: ['tasks', 'plan', 'site', 'buy', 'money'],
  OWNER: ['tasks', 'plan', 'site', 'buy', 'money'],
  SUPER_ADMIN: ['tasks', 'plan', 'site', 'buy', 'money'],
  PROJECT_MANAGER: ['tasks', 'site', 'plan', 'buy', 'money'],
  SITE_ENGINEER: ['tasks', 'site', 'buy', 'plan', 'money'],
  FINANCE: ['money', 'buy', 'site', 'plan', 'tasks'],
}

export function sectionOrder(role: string | null | undefined): NavSection[] {
  return SECTION_ORDER[(role || '').toUpperCase()] ?? SECTION_ORDER.ADMIN
}

export const MODULE_GROUPS: ModuleGroup[] = [
  {
    key: 'site',
    title: 'Site',
    icon: CalendarDays,
    tone: 'orange',
    about: 'What happened on site today, and what is stuck.',
    section: 'daily',
    pages: [
      { title: 'Today', url: '/today', status: 'built', whatsapp: "6 masons, 4 helpers. First-floor slab shuttering done. Cement ran out.", phase: 'V1', about: "Each site's day: what came in, what is missing, what needs you.", example: 'Main building sent 4 updates; Compound wall has not reported.' },
      { title: 'Daily reports', url: '/reports', status: 'built', phase: 'V1', about: 'Every DPR, newest first.', example: 'Last evening\'s PDF that went to the owner.' },
      { title: 'Weekly & monthly', url: '/reports/period', status: 'built', phase: 'V1', about: 'A week or a month in one report: work against plan, labour, materials, money and what needs you, as PDF and Excel.', example: 'October report to the MD on the 1st: 3 sites, ₹42 L spent, 2 delays.', tracker: 'PRC-19, PRC-20', related: [{ title: 'Daily reports', url: '/reports' }] },
      { title: 'Issues', url: '/issues', status: 'built', whatsapp: "No water since morning at Compound wall", phase: 'V1', about: 'Hindrances reported from site, open until someone acts.', example: 'No water since morning; shuttering team didn\'t come.' },
      { title: 'Approvals', url: '/site/approvals', status: 'planned', phase: 'V1.5', about: 'Everything waiting for your OK in one place: expenses, orders, bills, requests.', example: 'PM to approve: ₹18,000 JCB hire, 200 bags cement, Ravi\'s bill 3.', related: [{ title: 'Expenses', url: '/finance/expenses' }] },
      { title: 'Site log', url: '/site-log', status: 'built', whatsapp: "Plastering 120 sq ft on the second floor, with a photo", phase: 'V1', about: 'Everything the sites sent: work, photos, all entries.', example: '5 m³ poured on grid B, with photos.' },
      { title: 'Quality checks', url: '/site/quality', status: 'planned', phase: 'V1.5', about: 'Checklists before key work and test results after it.', example: 'Before the slab pour: cover blocks, shuttering level. Cube test at 7 and 28 days.', related: [{ title: 'Site log', url: '/site-log' }] },
      { title: 'Safety', url: '/site/safety', status: 'planned', phase: 'Later', about: 'Incidents, near misses and toolbox talks, with photos.', example: 'Worker on the scaffold without a helmet: photo, who acted, by when.', related: [{ title: 'Issues', url: '/issues' }] },
      { title: 'Snag list', url: '/site/snags', status: 'planned', phase: 'Later', about: 'Defects to fix before handover, room by room, until closed.', example: 'Bedroom 2: tile chipped near the door; closed after replacement.' },
      { title: 'Analytics', url: '/analytics', status: 'built', phase: 'V1', about: 'Trends across days and sites.', example: 'Which site reports late most often.' },
    ],
  },
  {
    key: 'tasks',
    title: 'Tasks',
    icon: ListChecks,
    tone: 'amber',
    about: 'Who does what by when: given here, moved to done by the person it is for, late ones flagged.',
    // TSK-01/02 (9 Nov 2026): a module of its own, switched on per company like Cost control. Web only for now
    // (Adarsh, 9 Nov): no WhatsApp tools or reminders, so no `whatsapp` sentence on its pages. Its own sidebar
    // section, TASKS, with the pages as rows (Adarsh, 9 Nov: "own sidebar section").
    module: 'tasks',
    section: 'tasks',
    flat: true,
    pages: [
      { title: 'My tasks', url: '/tasks', status: 'built', phase: 'V1', about: 'What is given to you, late first, then by the day it is due.', example: 'T-14 Tie steel for grid B, due Thursday; T-9 blocked: no shuttering.', tracker: 'TSK-02' },
      { title: 'All tasks', url: '/tasks?view=all', status: 'built', phase: 'V1', about: 'Every open task on the projects you see, by person, site and due day.', example: '23 open at Villa Kakkanad: 4 late, 6 due this week.', tracker: 'TSK-02' },
      { title: 'Overdue', url: '/tasks?view=overdue', status: 'built', phase: 'V1', about: 'Tasks past their day and still not done, with who has them.', example: 'T-6 Arun, 3 days late: waterproofing the terrace.', tracker: 'TSK-02' },
      { title: 'Done', url: '/tasks?view=done', status: 'built', phase: 'V1', about: 'What was finished and who closed it.', example: 'T-11 done by Biju yesterday.', tracker: 'TSK-02' },
      { title: 'Checklists', url: '/tasks/checklists', status: 'planned', phase: 'Later', about: 'Ready-made checklists to attach to a task before key work.', example: 'Before the slab pour: cover blocks, shuttering level, curing plan.', tracker: 'TSK-09', related: [{ title: 'Quality checks', url: '/site/quality' }] },
    ],
  },
  {
    key: 'planning',
    title: 'Planning',
    icon: ClipboardList,
    tone: 'teal',
    about: 'What the project should contain and cost, before work starts.',
    section: 'plan',
    pages: [
      { title: 'Project start', url: '/planning/setup', status: 'built', phase: 'V1', about: 'From "we won it" to "work starts": stage, contract dates, the BOQ from your Excel, the schedule, the site team, suppliers.', example: 'Upload the estimate sheet; 214 BOQ lines and a first schedule in 20 minutes.', tracker: 'ST-01, ST-03, ST-05', roles: MANAGERS, related: [{ title: 'Items', url: '/materials?view=items' }] },
      { title: 'Schedule', url: '/planning/schedule', status: 'built', phase: 'V1', about: 'The project timeline: what should happen when, what site has done, what is late and what it pushes.', example: 'Excavation 3 days late at 60%: footings and slab move; forecast handover 27 Nov.', tracker: 'ST-04' },
      { title: 'BOQ & budget', url: '/boq', status: 'built', phase: 'V1', about: 'Every work item with its quantity, client rate and budget rate.', example: 'Plastering 18,000 sq ft at ₹42; budget ₹36 per sq ft.', tracker: 'CC-02', roles: MONEY_ROLES },
      { title: 'Material plan', url: '/planning/materials', status: 'built', phase: 'V1', about: 'What each material is needed for, week by week, from the BOQ and the schedule, against stock and orders; red from the week it runs short.', example: 'First floor slab on 20 Nov needs 380 bags cement; 150 in stock: short from the week of 17 Nov.', tracker: 'MP-01, MP-02', roles: MONEY_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }, { title: 'Stock', url: '/materials' }] },
      { title: 'Rate library', url: '/planning/rates', status: 'planned', phase: 'V1', about: "Standard output and material per unit of work, so a BOQ can be priced without a consultant.", example: 'Plastering 12 mm: 1 mason + 1 helper ≈ 80 sq ft a day. 1 m³ M20 ≈ 8 bags cement.', tracker: 'MP-01 (per BOQ line, built)', roles: MANAGERS, related: [{ title: 'BOQ & budget', url: '/boq' }, { title: 'Material plan', url: '/planning/materials' }] },
      { title: 'Live plans', url: '/planning/live', status: 'built', phase: 'V1', about: 'The drawings as live maps: every room and footing coloured by the work site sent on WhatsApp, per trade, with photos and a live feed.', example: 'First floor: Pantry plastering done (green), Office-1 under way; B3 footing concreted this morning.', tracker: 'DR-10, DR-11', related: [{ title: 'Documents', url: '/planning/documents' }, { title: 'Places', url: '/planning/places' }] },
      { title: 'Places', url: '/planning/places', status: 'built', phase: 'V1', about: 'Every floor and room coloured by the work site reported there, with the photos of each room; "what\'s left on the first floor?" on WhatsApp.', example: 'First floor: plastering done in all 5 rooms; tiling left in Room-2 and the kitchen.', whatsapp: "What's left on the first floor?", tracker: 'LP-01..LP-05', related: [{ title: 'Schedule', url: '/planning/schedule' }] },
      { title: 'Drawing check', url: '/planning/drawing-check', status: 'built', phase: 'V1', about: 'Drop the architect\'s PDF: its sheets, levels, room sizes and fixtures, and what to ask the architect before it reaches site.', example: 'ROOM-1 is drawn 1740 x 590 cm (1,105 sq ft) but labelled 1,217 sq ft: the label looks copied from ROOM-2.', tracker: 'DR-01..DR-04', roles: MONEY_ROLES },
      { title: 'Drawings', url: '/planning/drawings', status: 'planned', phase: 'V1.5', about: 'Marking up drawings and linking their elements to progress. The register of drawings and their revisions is in Documents.', example: 'Column C4 on S-101 marked poured on 12 Nov.', tracker: 'DRW', related: [{ title: 'Documents', url: '/planning/documents' }] },
      { title: 'Documents', url: '/planning/documents', status: 'built', phase: 'V1', about: 'Drawings with their revision, permits with their expiry, the contract and estimate (office only), per project; "send me the latest S-101" on WhatsApp.', example: 'S-101 rev C uploaded: rev B marked out of date. Building permit expires 3 Dec.', whatsapp: "Send me the latest S-101", tracker: 'DOC-01, DR-07', related: [{ title: 'Drawing check', url: '/planning/drawing-check' }] },
      { title: 'Tendering', url: '/planning/tendering', status: 'planned', phase: 'Later', about: 'Price a new job from its BOQ and your rate library, to bid.', example: 'School building tender: 380 lines priced, 12% margin, bid ₹3.8 cr.', roles: MONEY_ROLES },
    ],
  },
  {
    key: 'cost',
    title: 'Cost control',
    icon: Gauge,
    tone: 'rose',
    about: 'Was the money spent matched by the work done? Green or red, every day.',
    // CC-01 (8 Nov 2026): a module of its own, switched on per company like Equipment.
    module: 'cost',
    section: 'money',
    pages: [
      { title: 'Overview', url: '/cost', status: 'built', phase: 'V1', about: 'Every project with a BOQ, worst first: budget, done against spent, committed, the forecast at completion, the last 7 days.', example: 'Villa Kakkanad: ₹4,500 under at completion; Block C: 2 red lines this week.', tracker: 'CC-19, CC-22', roles: MONEY_ROLES },
      { title: 'BOQ & budget', url: '/boq', status: 'built', phase: 'V1', shortcut: true, about: 'Every work item with its quantity, client rate and budget rate, the work done on it and the budget it earned.', example: 'Plastering 18,000 sq ft at ₹42; budget ₹36 per sq ft.', tracker: 'CC-02, CC-04', roles: MONEY_ROLES },
      { title: 'Green / red', url: '/cost/green-red', status: 'built', phase: 'V1', about: "Each BOQ line's labour against the labour budget its work earned, per day or period: green, amber or red, worst first, with why.", example: 'Plastering amber: ₹4,400 of labour for 300 sq ft, ₹14.67 per sq ft against ₹14.', tracker: 'CC-07', roles: [...MONEY_ROLES, 'SITE_ENGINEER'], related: [{ title: 'BOQ & budget', url: '/boq' }, { title: 'Attendance', url: '/labour' }] },
      { title: 'Budget vs actual', url: '/cost/budget', status: 'built', phase: 'V1', about: 'For a project: the budget, the budget earned by the work done, and the money spent, for labour, materials and subcontract; per BOQ line the labour put on it against the labour it earned.', example: 'Plastering: ₹8,680 of labour earned, ₹4,400 spent, ₹4,280 under.', tracker: 'CC-04, CC-05', roles: MONEY_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }] },
      { title: 'Materials vs BOQ', url: '/cost/materials', status: 'built', phase: 'V1', about: 'Per material: what the work done needed by the BOQ norms against what was used, and what is short to finish beyond stock and open orders.', example: 'Cement: 4 bags used, the work needed 3; 26 bags short to finish.', tracker: 'CC-08', roles: MONEY_ROLES, related: [{ title: 'Material plan', url: '/planning/materials' }] },
      { title: 'Cost centres', url: '/cost/centres', status: 'built', phase: 'V1', about: 'Where the money went: materials, labour, subcontract, fuel, equipment.', example: 'This month: materials ₹8.2 L, labour ₹3.1 L, fuel ₹18,000.', tracker: 'CC-01', roles: MONEY_ROLES, related: [{ title: 'Expenses', url: '/finance/expenses' }] },
      { title: 'Closeout report', url: '/cost/closeout', status: 'planned', phase: 'V1.5', about: 'At handover: budget vs actual, leftover stock, what is still owed.', example: 'Villa Kakkanad: ₹2.4 cr budget, ₹2.31 cr spent, 3 suppliers unpaid.', tracker: 'CC-14', roles: MONEY_ROLES },
    ],
  },
  {
    key: 'materials',
    title: 'Materials',
    icon: Boxes,
    tone: 'emerald',
    module: 'materials',
    about: 'What is on site, what came, what went into the work.',
    section: 'site',
    pages: [
      { title: 'Stock', url: '/materials?view=stock', status: 'built', phase: 'V1', about: 'What is on site now, how long it lasts, what is coming on orders and what the sites asked for; a minimum per item, and a morning note with a draft request when a site goes below it.', example: 'Cement: 40 bags at Villa, below the minimum of 100; order 200.', whatsapp: 'Set minimum cement at Villa 100 bags', tracker: 'WEB-77, PRC-47' },
      { title: 'Movements', url: '/materials?view=movements', status: 'built', whatsapp: "Used 20 bags cement for the slab today", phase: 'V1', about: 'The register: every delivery, use and move.', example: '+100 bags cement from Malabar Hardware, ₹41,400.' },
      { title: 'Items', url: '/materials?view=items', status: 'built', phase: 'V1', about: 'Your list of materials, with category and unit.', example: 'Cement OPC 53 · Structural › Concrete · bags.', roles: MANAGERS },
      { title: 'Requests', url: '/materials/requests', status: 'built', phase: 'V1', shortcut: true, about: 'What the site asks for, before anyone orders it.', example: 'Engineer: need 200 bags cement by Friday for the first-floor slab.', whatsapp: "Need 200 bags cement by Friday for the first-floor slab", tracker: 'PRC-22', related: [{ title: 'Stock', url: '/materials' }] },
      { title: 'Stock count', url: '/materials/counts', status: 'built', phase: 'V1', about: 'Count a site on a phone; book against counted, the differences in units and rupees; the owner approves them into the book. Sites not counted in 30 days are flagged.', example: 'SC-0004 Villa: cement 8 bags short (₹3,200, wastage), steel 100 kg more.', whatsapp: 'Count: cement 92 bags, sand 3 loads', tracker: 'PRC-48', related: [{ title: 'Stock', url: '/materials' }] },
      { title: 'Stock value', url: '/materials/value', status: 'built', phase: 'V1', about: 'What the stock on site is worth (quantity x average rate), by category, the top items, and what has not moved in 30 days.', example: 'Villa: ₹4.2 L in stock; ₹38,000 of tiles not used in 30 days.', tracker: 'PRC-49', roles: MONEY_ROLES, related: [{ title: 'Stock', url: '/materials' }] },
      { title: 'Central store', url: '/materials/store', status: 'planned', phase: 'Later', about: 'A yard or godown that buys in bulk and sends to sites.', example: '20 tonnes of steel at the yard; 3 tonnes sent to the villa today.', related: [{ title: 'Movements', url: '/materials?view=movements' }] },
    ],
  },
  {
    key: 'procurement',
    title: 'Procurement',
    icon: ShoppingCart,
    tone: 'sky',
    about: 'From "the site needs it" to "the supplier is paid", each step checked against the last.',
    section: 'buy',
    pages: [
      // PRC-31: requests and orders are one flow; Requests also sits here (the same page as Materials > Requests).
      { title: 'Requests', url: '/materials/requests', status: 'built', phase: 'V1', about: 'What the sites ask for, before anyone orders it.', example: 'Engineer: need 200 bags cement by Friday for the first-floor slab.', tracker: 'PRC-22' },
      { title: 'Purchase orders', url: '/procurement/orders', status: 'built', phase: 'V1', about: 'Orders to suppliers, with what is still to arrive and duplicate warnings.', example: 'PO-0042 to Malabar: 200 bags at ₹400, 150 delivered, 50 pending.', whatsapp: "Order 200 bags cement from Malabar at ₹400", tracker: 'PRC-06..10', related: [{ title: 'Movements', url: '/materials?view=movements' }] },
      { title: 'Goods received (GRN)', navTitle: 'GRN', url: '/procurement/grn', status: 'built', phase: 'V1', about: 'Each delivery received against its order: GRN number, challan photo, quantity accepted and rejected, who received it.', example: 'GRN-0117: 150 of 200 bags against PO-0042, 3 torn bags rejected, challan photo attached, received by Arun.', whatsapp: "150 bags came against PO-0042, 3 torn", tracker: 'PRC-08', related: [{ title: 'Deliveries today (Movements)', url: '/materials?view=movements' }] },
      { title: 'Pending deliveries', url: '/procurement/pending', status: 'built', phase: 'V1', about: 'What is ordered but has not arrived, by date or by supplier, with one message to chase each shop.', example: '3 orders past their date: 50 bags cement from Malabar, 2 days late.', tracker: 'PRC-45', related: [{ title: 'Purchase orders', url: '/procurement/orders' }] },
      { title: 'Bills', url: '/procurement/bills', status: 'planned', phase: 'V1', about: 'Supplier bills matched to deliveries; material delivered but not billed.', example: 'Bill says 200 bags at ₹420, delivery says 150 at ₹400: flagged.', tracker: 'PRC-11', roles: MONEY_ROLES },
      { title: 'Rates', url: '/procurement/rates', status: 'built', phase: 'V1', about: 'What each item cost, from which supplier, over time.', example: 'Cement ₹14 more than last time at Malabar.', tracker: 'PRC-14, PRC-16', roles: MONEY_ROLES },
      { title: 'Quotations', url: '/procurement/quotations', status: 'built', phase: 'V1', about: 'Ask several suppliers, compare side by side as each really costs you (GST and all), and order the chosen ones.', example: 'Three shops quote for TMT 12 mm: KK cheapest at ₹60/kg, saves ₹8,000.', whatsapp: 'Get quotes from Malabar, KK and Sree for 500 bags cement', tracker: 'PRC-40..44', roles: MONEY_ROLES, related: [{ title: 'Rates', url: '/procurement/rates' }, { title: 'Purchase orders', url: '/procurement/orders' }] },
      { title: 'Suppliers', url: '/finance/vendors', status: 'built', phase: 'V1', about: 'Suppliers with phone, GSTIN and credit days, and what you owe each one.', example: 'Malabar Hardware · ₹26,000 due, ₹10,000 overdue' },
      { title: 'Reports', url: '/procurement/reports', status: 'planned', phase: 'V1', about: 'Spend by supplier, category and project; late deliveries; rate changes.', example: 'October: ₹28 L bought, 41% from Malabar; 6 late deliveries; cement up 3.5%.', tracker: 'PRC-19', roles: MONEY_ROLES, related: [{ title: 'Movements', url: '/materials?view=movements' }] },
      { title: 'Returns', url: '/procurement/returns', status: 'built', phase: 'V1', about: 'Material sent back to the supplier from a GRN, a delivery or their page; the debit note lowers what you owe them at once, until a replacement or credit settles it.', example: 'Bent steel returned: DN-0003, Kerala Steels owes ₹8,400 back.', whatsapp: '12 steel bars bent, returning to KSL', tracker: 'PRC-46', roles: MONEY_ROLES, related: [{ title: 'Goods received (GRN)', url: '/procurement/grn' }, { title: 'Suppliers', url: '/finance/vendors' }] },
      { title: 'Rate contracts', url: '/procurement/contracts', status: 'planned', phase: 'Later', about: 'Yearly agreed rates with a supplier, used on every order automatically.', example: 'Malabar: cement at ₹395 a bag until March.', roles: MONEY_ROLES },
    ],
  },
  {
    key: 'labour',
    title: 'Labour',
    icon: HardHat,
    tone: 'amber',
    module: 'labour',
    about: 'Who worked, what it cost, and whether the work matched the cost.',
    section: 'site',
    pages: [
      { title: 'Attendance', url: '/labour', status: 'built', whatsapp: "Suresh team: 4 masons, 2 helpers today", phase: 'V1', about: 'Who worked today, by contractor and trade.', example: '4 masons and 2 helpers under Suresh.' },
      { title: 'Muster roll', url: '/labour?view=muster', status: 'built', phase: 'V1', about: "A site's month as the grid sites keep: each person down, each day across, P / ½ / A, overtime, totals; from attendance, never typed again. Export for the contractor or the labour office.", example: 'November at Compound wall: 14 people, 312 man-days, 18 h overtime.', tracker: 'LW-02' },
      { title: 'Workers', url: '/labour?view=workers', status: 'built', phase: 'V1', about: 'Your workers and their daily wage.', example: 'Mason ₹1,200 a day, helper ₹800.' },
      { title: 'Teams', url: '/labour?view=teams', status: 'built', phase: 'V1', about: "Labour contractors and their teams: who is in each, how many days they did; a team is paid through its contractor and has its own account.", example: "Suresh team: 12 on the register, 260 man-days in 30 days.", tracker: 'LW-01', related: [{ title: 'Suppliers', url: '/finance/vendors' }] },
      { title: 'Productivity', url: '/labour/productivity', status: 'planned', phase: 'V1', about: 'Labour cost against measured output and the benchmark. Labour is put on BOQ lines in Cost control > Budget vs actual (CC-05); this page is the colour per line (CC-07).', example: '₹6,400 of labour, 180 sq ft plastered, benchmark 160: green.', tracker: 'CC-05, CC-07', roles: MONEY_ROLES, related: [{ title: 'Attendance', url: '/labour' }] },
      { title: 'Wages', url: '/labour/wages', status: 'built', phase: 'V1', about: "A site's pay week: each worker and team, days from attendance × wage, overtime, the advance taken back and deductions, to pay; approve, pay from cash or bank, send the slip.", example: "Suresh team, 2–8 Nov: 48 man-days, ₹38,400, advance ₹5,000 back, ₹33,400 paid from site cash.", whatsapp: "What do I pay Suresh's team this week?", tracker: 'LW-04, LW-05', roles: MONEY_ROLES, related: [{ title: 'Advances', url: '/labour/advances' }, { title: 'Cash & bank book', url: '/accounts/cash-bank' }] },
      { title: 'Advances', url: '/labour/advances', status: 'built', phase: 'V1', about: 'Money given to a worker or a labour team before payday, from a money account; taken back off their next wages on its own.', example: 'Ravi ₹500 on Tuesday from site petty cash; ₹500 back on Saturday.', whatsapp: 'Gave Ravi 500 advance', tracker: 'LW-03', related: [{ title: 'Wages', url: '/labour/wages' }] },
    ],
  },
  {
    key: 'subcontract',
    title: 'Subcontract',
    icon: Handshake,
    tone: 'violet',
    about: 'Work given out at an agreed rate, paid against measured quantity.',
    section: 'buy',
    pages: [
      { title: 'Subcontractors', url: '/subcontract/teams', status: 'built', phase: 'V1', tracker: 'NXT-05..07', about: 'Every outside team, what they work on, and what you owe each.', example: "Ravi's plastering team: 2 sites, ₹46,000 due, ₹10,000 advance.", roles: MONEY_ROLES },
      { title: 'Work orders', url: '/subcontract/work-orders', status: 'built', phase: 'V1', tracker: 'NXT-05', about: 'Who does which work at what rate.', example: "Plastering to Ravi's team at ₹14 per sq ft, 18,000 sq ft." },
      { title: 'Bills & checks', url: '/subcontract/bills', status: 'built', phase: 'V1', about: 'Each payment checked against the quantity measured.', example: '₹15,000 to the concrete team: 2.4 m³ × ₹6,000 = ₹14,400, slight overpay.', whatsapp: "Concrete team bill ₹15,000 for 2.4 m³", tracker: 'CC-06', roles: MONEY_ROLES },
    ],
  },
  {
    key: 'finance',
    title: 'Finance',
    icon: Landmark,
    tone: 'violet',
    module: 'finance',
    about: "Money in and out of the company's accounts.",
    section: 'money',
    pages: [
      { title: 'Expenses', url: '/finance/expenses', status: 'built', whatsapp: "Paid ₹3,800 diesel for the generator, photo of the bill", phase: 'V1', about: 'Every expense with its photo and who paid.', example: '₹100 petrol from the engineer\'s petty cash.', roles: MONEY_ROLES },
      { title: 'Money', url: '/finance/money', status: 'built', phase: 'V1', about: 'Accounts and petty cash balances.', example: 'Site petty cash ₹4,200; office bank.' },
      { title: 'Suppliers', url: '/finance/vendors', status: 'built', phase: 'V1', shortcut: true, about: 'Suppliers, subcontractors, hire and services, and what you owe each: bills, deliveries not billed, payments, advances, balance.', example: 'Malabar: ₹40,000 + ₹36,000 delivered − ₹50,000 paid = ₹26,000 due.', tracker: 'CC-09, CC-10' },
      { title: 'Settings', url: '/finance/settings', status: 'built', phase: 'V1', about: 'Categories and finance options.', example: 'Expense categories.' },
    ],
  },
  {
    key: 'accounts',
    title: 'Accounts',
    icon: BookOpenCheck,
    tone: 'indigo',
    module: 'finance',
    about: "The company's books: every rupee in and out, by party and by project, ready for the CA and Tally.",
    section: 'money',
    pages: [
      { title: 'Accounts home', navTitle: 'Home', url: '/accounts', status: 'built', phase: 'V1', module: 'accounts', about: "The owner's one screen: cash and bank today, owed to us and by us, this month's profit against last, the year by month, GST this month, TDS to deposit, the projects best first.", example: 'Cash ₹15.9 L; clients owe ₹6.4 L; profit this month ₹2.1 L, up 18%.', tracker: 'ACC-09', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'Project P&L', url: '/accounts/projects', status: 'built', phase: 'V1', module: 'accounts', about: 'Profit or loss of each project: billed to the client minus every cost booked to it, its position (received, owed, retention held), against the BOQ budget.', example: 'Villa Kakkanad: ₹62 L billed, ₹54.8 L cost, ₹7.2 L profit (11.6%).', tracker: 'ACC-08, CC-20', roles: MONEY_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }] },
      { title: 'Ledgers', url: '/accounts/ledgers', status: 'built', phase: 'V1', module: 'accounts', about: 'Every ledger in the books with its balance: suppliers, clients, bank and cash, expense heads; each with every entry and a running balance.', example: "Malabar: bill ₹11,800, paid ₹5,000 and ₹2,000 on account → ₹4,800 Cr.", tracker: 'ACC-05', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'], related: [{ title: 'Suppliers', url: '/finance/vendors' }] },
      { title: 'Receivables', url: '/accounts/receivables', status: 'built', phase: 'V1', about: 'What each client owes, most first, by age; money received against a bill, on account or as an advance.', example: 'Mr. Thomas: RA-02 ₹2.67 L left, 38 days; ₹8.5 L advance recovered through the bills.', whatsapp: "Client paid 5 lakh for RA-03", tracker: 'NXT-03', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'Cash & bank book', url: '/accounts/cash-bank', status: 'built', phase: 'V1', module: 'accounts', about: 'Every cash box and bank account: opening, money in, money out, closing, day by day.', example: 'HDFC current: opening ₹8.5 L, in ₹10 L, out ₹2.6 L, closing ₹15.9 L.', tracker: 'ACC-07', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'], related: [{ title: 'Money', url: '/finance/money' }] },
      { title: 'Day book', url: '/accounts/day-book', status: 'built', phase: 'V1', module: 'accounts', about: 'Every voucher of a period, day by day: purchases, payments, receipts, sales, contra and journals, posted from the records on their own.', example: '6 Nov: 31 vouchers, ₹4.6 L moved.', tracker: 'ACC-05', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'Tally export', url: '/accounts/tally', status: 'built', phase: 'V1', about: "A period's expenses and payments as Tally vouchers, with their ledgers, for the accountant to import. One way.", example: "October: 312 expenses and 41 payments in one file; GST split to Input GST.", tracker: 'NXT-12', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'Bank reconciliation', url: '/accounts/bank-reco', status: 'planned', phase: 'Later', about: 'Match the bank statement with your entries; show what is missing on either side.', example: '₹45,000 UPI to Malabar in the bank, not entered in Mesiri.', roles: MONEY_ROLES },
      { title: 'Vouchers', url: '/accounts/vouchers', status: 'planned', phase: 'Later', about: 'Payment, receipt, journal and contra entries, numbered and approved.', example: 'PV-0231: ₹50,000 to Malabar Hardware, approved by the GM.', roles: MONEY_ROLES },
      { title: 'GST', url: '/accounts/gst', status: 'built', phase: 'V1', module: 'accounts', about: 'Output GST on RA bills and input GST you can claim, net payable in GSTR-3B terms, IGST or CGST + SGST by state; every bill with its GSTIN; credit missed and why.', example: 'October: ₹1.86 L output, ₹30,600 input, ₹1.55 L payable; ₹90 missed (supplier with no GSTIN).', tracker: 'ACC-10', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'TDS', url: '/accounts/tds', status: 'built', phase: 'V1', module: 'accounts', about: 'TDS deducted from subcontractors (194C), deposited or due by the 7th; TDS clients deducted from your RA bills, to claim.', example: 'October: ₹840 deducted from Ajay Tiling, due 7 Nov; clients deducted ₹20,600.', tracker: 'ACC-11', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'Cash flow', url: '/accounts/cash-flow', status: 'planned', phase: 'Later', about: 'Money needed in the coming weeks against money expected in.', example: 'Next month: ₹38 L to pay, ₹30 L expected from RA bills: ₹8 L short.', roles: MONEY_ROLES },
      { title: 'Profit & loss', url: '/accounts/pl', status: 'built', phase: 'V1', module: 'accounts', about: "The company's (or a project's, or a site's) income and costs for a period: gross and net profit, against the period before or last year.", example: 'October: ₹10.3 L billed, ₹2.9 L cost, ₹7.4 L profit (72%).', tracker: 'ACC-06', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'Balance sheet', url: '/accounts/balance-sheet', status: 'built', phase: 'V1', module: 'accounts', about: 'What the company owns and owes on a date, with the year\'s profit in capital.', example: 'As on 31 Oct: bank ₹15.9 L, receivables ₹6.4 L, payables ₹2.1 L.', tracker: 'ACC-06', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'Trial balance', url: '/accounts/trial-balance', status: 'built', phase: 'V1', module: 'accounts', about: 'Every ledger balance in its group, debits equal to credits, for the company, a project or a site; checked against Money, suppliers and Receivables.', example: '214 ledgers; debits = credits = ₹6.9 cr.', tracker: 'ACC-05, ACC-22', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'Chart of accounts', url: '/accounts/chart', status: 'built', phase: 'V1', module: 'accounts', about: "The ledgers and groups the books use, in Tally's groups; a ledger per supplier, client, account and category made on its own.", example: 'Sundry creditors › Malabar Hardware; Direct expenses › Materials.', tracker: 'ACC-01', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'Months', url: '/accounts/periods', status: 'built', phase: 'V1', module: 'accounts', about: 'Each month open or closed; a change after close is posted on the first open day and marked.', example: 'October closed by finance on 5 Nov; 1 bill changed after close.', tracker: 'ACC-02', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE'] },
      { title: 'Fixed assets', url: '/accounts/assets', status: 'planned', phase: 'Later', about: 'Machines, vehicles and shuttering owned, with depreciation.', example: 'JCB bought ₹28 L in 2024, written down to ₹21 L.', roles: MONEY_ROLES },
      { title: 'Year end', url: '/accounts/year-end', status: 'planned', phase: 'Later', about: 'Lock a closed period so nobody changes it, and carry balances forward.', example: 'March 2026 locked by the CA on 15 May.', roles: MANAGERS },
    ],
  },
  {
    key: 'billing',
    title: 'Client billing',
    icon: ReceiptText,
    tone: 'green',
    about: 'Money you collect from the client, in stages against measured work.',
    section: 'money',
    pages: [
      { title: 'Clients', url: '/billing/clients', status: 'built', phase: 'V1', about: 'Each client, their projects and contract values; the terms each RA bill uses.', example: 'Mr. Thomas: villa, ₹62 L contract, 5% retention.', tracker: 'NXT-01', roles: BILLING_ROLES },
      { title: 'RA bills', url: '/billing/ra-bills', status: 'built', phase: 'V1', about: 'Running bills from the work site measured since the last bill × the client rates, with retention, advance recovery, GST and TDS worked out; printed on your letterhead.', example: 'RA-04: ₹12.6 L of work in October, ₹11.9 L net after retention and TDS.', tracker: 'NXT-02', roles: BILLING_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }] },
      { title: 'Variations', url: '/billing/variations', status: 'planned', phase: 'Later', about: 'Extra or changed work the client asked for, priced and approved before it is built.', example: 'Client adds a balcony: ₹1.8 L approved on 3 Nov.', roles: MONEY_ROLES },
      { title: 'Payments received', url: '/billing/receipts', status: 'planned', phase: 'Later', about: 'Money in from clients, and the share held back until handover (retention).', example: 'Received ₹12 L of RA bill 4; 5% (₹63,000) held.', roles: MONEY_ROLES },
      { title: 'Client view', url: '/billing/client-view', status: 'built', phase: 'V1', about: 'A link the house owner opens on the phone, no login: progress, milestones, photos from approved site reports, bills and payments. Never rates or costs.', example: 'Mr. Thomas sees his villa at 42%, the slab done on 3 Nov, RA-02 ₹2.6 L due.', tracker: 'CV-01..CV-03', roles: BILLING_ROLES, related: [{ title: 'RA bills', url: '/billing/ra-bills' }, { title: 'Clients', url: '/billing/clients' }] },
    ],
  },
  {
    key: 'equipment',
    title: 'Equipment',
    icon: Truck,
    tone: 'teal',
    about: 'Machines, vehicles, and reusable items like shuttering that go missing quietly.',
    module: 'equipment',
    section: 'site',
    pages: [
      { title: 'Machines', url: '/equipment', status: 'built', phase: 'V1', about: 'Every machine on every site: hours worked, idle and broken down, diesel, hire cost, service due.', example: 'JCB 6 hours today at ₹1,100 an hour, 30 L diesel.', whatsapp: "JCB 6 hrs, 2 hrs breakdown, 30 L diesel", tracker: 'NXT-11' },
      { title: 'Daily log', url: '/equipment/log', status: 'built', phase: 'V1', about: "One day, every machine: the evening's figures in one screen.", example: 'JCB 6 h, mixer 8 h, roller broke down 3 h.', whatsapp: "Mixer 8 hrs, roller broke down 3 hrs", tracker: 'NXT-11' },
      { title: 'Hire check', url: '/equipment/hire', status: 'built', phase: 'V1', about: 'The hire bill against the hours recorded on site.', example: 'Bill says 220 h; 186 h recorded: ₹37,400 more than the site says.', tracker: 'NXT-13', roles: MONEY_ROLES },
      { title: 'Vehicles', url: '/equipment/vehicles', status: 'built', phase: 'V1', about: 'Company vehicles: trips, fuel and who drove.', example: 'Tipper: 6 trips of sand today, 40 L diesel.', whatsapp: "Tipper 6 trips of sand, 40 L diesel", tracker: 'NXT-15' },
      { title: 'Shuttering & tools', url: '/equipment/assets', status: 'built', phase: 'V1', about: 'Which site holds how many plates, props and tools.', example: '400 plates at the villa, 60 sent to Chennai.', whatsapp: "Sent 60 plates from the villa to Chennai", tracker: 'NXT-14' },
    ],
  },
  {
    // UX-04: setup in one place, at the bottom of the sidebar (admins). Its pages keep their addresses.
    key: 'settings',
    title: 'Settings',
    icon: SettingsIcon,
    tone: 'indigo',
    about: 'Your company, projects and sites, team and WhatsApp.',
    section: 'settings',
    pages: [
      { title: 'Settings', url: '/settings', status: 'built', phase: 'V1', about: 'Everything you set up once: company, projects and sites, team, WhatsApp, modules.', example: 'Add a site; invite the engineer; set the report time.', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN'] },
      { title: 'Projects & sites', url: '/projects', status: 'built', phase: 'V1', about: 'Each project, its sites and who gets its reports.', example: 'Villa Kakkanad: Main building, Compound wall.', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN'] },
      { title: 'Team', url: '/team', status: 'built', phase: 'V1', about: 'Everyone who reports to or reads from Mesiri, with their role and sites.', example: 'Arun, site engineer, Main building.', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN'] },
      { title: 'Company', url: '/company', status: 'built', phase: 'V1', about: 'Company details, letterhead, logo and report settings.', example: 'GSTIN, address and logo on every PDF.', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN'] },
      { title: 'WhatsApp', url: '/whatsapp', status: 'built', phase: 'V1', about: 'Conversations with Mesiri, every message, and scheduled messages.', example: "Arun's 6 pm update and Mesiri's reply.", roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN'] },
      { title: 'Activity log', url: '/settings/activity', status: 'built', phase: 'V1', about: 'Who changed what, when: every save, edit, delete and approval, on the web and on WhatsApp, newest first. Read only.', example: 'Meera · Submit RA bill RA-02 · 4:10 pm · Web.', tracker: 'ADM-01, ADM-02', roles: ['ADMIN', 'OWNER', 'SUPER_ADMIN'] },
    ],
  },
]

/** Pages with their module, flat. */
export const ALL_PAGES = MODULE_GROUPS.flatMap((group) => group.pages.filter((page) => !page.shortcut).map((page) => ({ group, page })))

/** Planned pages own a route each; the placeholder page reads them from here. */
export const PLANNED_PAGES = ALL_PAGES.filter((p) => p.page.status === 'planned')

/** The module and page an address belongs to (for the breadcrumb and the placeholder). */
export function findPage(pathname: string, search = ''): { group: ModuleGroup; page: ModulePage } | null {
  const view = new URLSearchParams(search).get('view')
  let best: { group: ModuleGroup; page: ModulePage; score: number } | null = null
  for (const entry of ALL_PAGES) {
    const [path, query] = entry.page.url.split('?')
    if (pathname !== path && !pathname.startsWith(`${path}/`)) continue
    const pageView = new URLSearchParams(query ?? '').get('view')
    // A view of a page matches only its own ?view=; the first view of a page is its default.
    if (pageView && view && pageView !== view) continue
    const score = path.length * 10 + (pageView && pageView === view ? 5 : 0) + (pathname === path ? 1 : 0)
    if (!best || score > best.score) best = { ...entry, score }
  }
  return best ? { group: best.group, page: best.page } : null
}

/** Icons for the few built pages the sidebar shows as plain links. */
export const PAGE_ICONS: Record<string, LucideIcon> = {
  '/today': CalendarDays,
  '/tasks': ListChecks,
  '/tasks?view=all': ListTodo,
  '/tasks?view=overdue': AlarmClock,
  '/tasks?view=done': CircleCheck,
  '/tasks/checklists': ClipboardCheck,
  '/reports': FileText,
  '/issues': AlertCircle,
  '/site-log': Activity,
  '/analytics': BarChart3,
  '/site/quality': ClipboardCheck,
  '/reports/period': CalendarRange,
  '/site/approvals': Stamp,
  '/site/safety': ShieldAlert,
  '/site/snags': ListTodo,
  '/boq': Calculator,
  '/planning/setup': Rocket,
  '/planning/schedule': CalendarRange,
  '/planning/materials': PackageSearch,
  '/planning/places': Layers,
  '/planning/live': MapPinned,
  '/planning/documents': FolderOpen,
  '/planning/drawing-check': FileSearch,
}
