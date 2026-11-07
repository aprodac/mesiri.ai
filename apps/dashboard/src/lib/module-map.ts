import {
  AlertCircle,
  BarChart3,
  Boxes,
  Calculator,
  CalendarDays,
  ClipboardCheck,
  ClipboardList,
  FileText,
  Gauge,
  HardHat,
  Handshake,
  Landmark,
  ReceiptText,
  ShoppingCart,
  Truck,
  Activity,
  CalendarRange,
  ListTodo,
  ShieldAlert,
  Stamp,
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
  pages: ModulePage[]
}

export const MODULE_GROUPS: ModuleGroup[] = [
  {
    key: 'site',
    title: 'Site',
    icon: CalendarDays,
    tone: 'orange',
    about: 'What happened on site today, and what is stuck.',
    pages: [
      { title: 'Today', url: '/today', status: 'built', phase: 'V1', about: "Each site's day: what came in, what is missing, what needs you.", example: 'Main building sent 4 updates; Compound wall has not reported.' },
      { title: 'Daily reports', url: '/reports', status: 'built', phase: 'V1', about: 'Every DPR, newest first.', example: 'Last evening\'s PDF that went to the owner.' },
      { title: 'Weekly & monthly', url: '/reports/period', status: 'planned', phase: 'V1', about: 'A week or a month in one report: work, labour, materials and money, as PDF and Excel.', example: 'October report to the MD on the 1st: 3 sites, ₹42 L spent, 2 delays.', tracker: 'PRC-19, PRC-20', related: [{ title: 'Daily reports', url: '/reports' }] },
      { title: 'Issues', url: '/issues', status: 'built', phase: 'V1', about: 'Hindrances reported from site, open until someone acts.', example: 'No water since morning; shuttering team didn\'t come.' },
      { title: 'Approvals', url: '/site/approvals', status: 'planned', phase: 'V1.5', about: 'Everything waiting for your OK in one place: expenses, orders, bills, requests.', example: 'PM to approve: ₹18,000 JCB hire, 200 bags cement, Ravi\'s bill 3.', related: [{ title: 'Expenses', url: '/finance/expenses' }] },
      { title: 'Site log', url: '/site-log', status: 'built', phase: 'V1', about: 'Everything the sites sent: work, photos, all entries.', example: '5 m³ poured on grid B, with photos.' },
      { title: 'Quality checks', url: '/site/quality', status: 'planned', phase: 'V1.5', about: 'Checklists before key work and test results after it.', example: 'Before the slab pour: cover blocks, shuttering level. Cube test at 7 and 28 days.', related: [{ title: 'Site log', url: '/site-log' }] },
      { title: 'Safety', url: '/site/safety', status: 'planned', phase: 'Later', about: 'Incidents, near misses and toolbox talks, with photos.', example: 'Worker on the scaffold without a helmet: photo, who acted, by when.', related: [{ title: 'Issues', url: '/issues' }] },
      { title: 'Snag list', url: '/site/snags', status: 'planned', phase: 'Later', about: 'Defects to fix before handover, room by room, until closed.', example: 'Bedroom 2: tile chipped near the door; closed after replacement.' },
      { title: 'Analytics', url: '/analytics', status: 'built', phase: 'V1', about: 'Trends across days and sites.', example: 'Which site reports late most often.' },
    ],
  },
  {
    key: 'planning',
    title: 'Planning',
    icon: ClipboardList,
    tone: 'teal',
    about: 'What the project should contain and cost, before work starts.',
    pages: [
      { title: 'BOQ & budget', url: '/boq', status: 'built', phase: 'V1', about: 'Every work item with its quantity, client rate and budget rate.', example: 'Plastering 18,000 sq ft at ₹42; budget ₹36 per sq ft.', tracker: 'CC-02', roles: MONEY_ROLES },
      { title: 'Project setup', url: '/planning/setup', status: 'planned', phase: 'V1', about: 'Start a project from the customer\'s own Excel: BOQ, suppliers with balances, opening stock.', example: 'Upload the estimate sheet; 214 BOQ lines and 12 suppliers loaded in 2 minutes.', tracker: 'CC-13, PRC-05', roles: MANAGERS, related: [{ title: 'Items', url: '/materials?view=items' }] },
      { title: 'Rate library', url: '/planning/rates', status: 'planned', phase: 'V1', about: "Standard output and material per unit of work, so a BOQ can be priced without a consultant.", example: 'Plastering 12 mm: 1 mason + 1 helper ≈ 80 sq ft a day. 1 m³ M20 ≈ 8 bags cement.', tracker: 'CC-03', roles: MANAGERS, related: [{ title: 'BOQ & budget', url: '/boq' }] },
      { title: 'Drawings', url: '/planning/drawings', status: 'planned', phase: 'V1.5', about: 'The latest drawings, so site always builds from the right revision.', example: 'Structural drawing rev C replaces rev B.', tracker: 'DRW' },
      { title: 'Documents', url: '/planning/documents', status: 'planned', phase: 'V1.5', about: 'Contracts, permits, approvals and agreements, per project, findable from WhatsApp.', example: 'Building permit, structural approval, Ravi\'s work order PDF.' },
      { title: 'Tasks', url: '/planning/tasks', status: 'planned', phase: 'V1.5', about: 'Who does what by when.', example: 'Arun: tie steel for grid B by Thursday.' },
      { title: 'Schedule', url: '/planning/schedule', status: 'planned', phase: 'Later', about: 'The project timeline: stages, dependencies, what is late.', example: 'Slab on 14 Nov, then 21 days curing before the next floor; plastering 4 days behind.' },
      { title: 'Tendering', url: '/planning/tendering', status: 'planned', phase: 'Later', about: 'Price a new job from its BOQ and your rate library, to bid.', example: 'School building tender: 380 lines priced, 12% margin, bid ₹3.8 cr.', roles: MONEY_ROLES },
    ],
  },
  {
    key: 'cost',
    title: 'Cost control',
    icon: Gauge,
    tone: 'rose',
    about: 'Was the money spent matched by the work done? Green or red, every day.',
    pages: [
      { title: 'Green / red', url: '/cost', status: 'planned', phase: 'V1', about: "Each day's cost against the value of the work done, per work item.", example: 'Plastering green (₹6,400 of labour, 180 sq ft done); brickwork red, ₹2,100 over.', tracker: 'CC-07, CC-11', roles: MONEY_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }, { title: 'Attendance', url: '/labour' }] },
      { title: 'Budget vs actual', url: '/cost/budget', status: 'planned', phase: 'V1', about: 'Each BOQ line: quantity done and money spent against plan.', example: 'Concrete: 40% of quantity done, 46% of budget spent.', tracker: 'CC-04', roles: MONEY_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }] },
      { title: 'Cost centres', url: '/cost/centres', status: 'planned', phase: 'V1', about: 'Where the money went: materials, labour, subcontract, fuel, equipment.', example: 'This month: materials ₹8.2 L, labour ₹3.1 L, fuel ₹18,000.', tracker: 'CC-01', roles: MONEY_ROLES, related: [{ title: 'Expenses', url: '/finance/expenses' }] },
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
    pages: [
      { title: 'Stock', url: '/materials?view=stock', status: 'built', phase: 'V1', about: 'What is on site now, and how long it lasts.', example: 'Cement: 217 bags, lasts about 10 days.' },
      { title: 'Movements', url: '/materials?view=movements', status: 'built', phase: 'V1', about: 'The register: every delivery, use and move.', example: '+100 bags cement from Malabar Hardware, ₹41,400.' },
      { title: 'Items', url: '/materials?view=items', status: 'built', phase: 'V1', about: 'Your list of materials, with category and unit.', example: 'Cement OPC 53 · Structural › Concrete · bags.', roles: MANAGERS },
      { title: 'Requests', url: '/materials/requests', status: 'planned', phase: 'V1', about: 'What the site asks for, before anyone orders it.', example: 'Engineer: need 200 bags cement by Friday for the first-floor slab.', tracker: 'PRC', related: [{ title: 'Stock', url: '/materials' }] },
      { title: 'Reconciliation', url: '/materials/reconciliation', status: 'planned', phase: 'V1', about: 'Required by the BOQ vs received vs used vs left, so a shortage shows early.', example: 'BOQ needs 960 bags; 700 received, 610 used, 90 left: short in 6 days.', tracker: 'CC-08', related: [{ title: 'Stock', url: '/materials' }, { title: 'BOQ & budget', url: '/boq' }] },
      { title: 'Central store', url: '/materials/store', status: 'planned', phase: 'Later', about: 'A yard or godown that buys in bulk and sends to sites.', example: '20 tonnes of steel at the yard; 3 tonnes sent to the villa today.', related: [{ title: 'Movements', url: '/materials?view=movements' }] },
    ],
  },
  {
    key: 'procurement',
    title: 'Procurement',
    icon: ShoppingCart,
    tone: 'sky',
    about: 'From "the site needs it" to "the supplier is paid", each step checked against the last.',
    pages: [
      { title: 'Purchase orders', url: '/procurement/orders', status: 'planned', phase: 'V1', about: 'Orders to suppliers, with what is still to arrive and duplicate warnings.', example: 'PO-0042 to Malabar: 200 bags at ₹400, 150 delivered, 50 pending.', tracker: 'PRC-06..10', related: [{ title: 'Movements', url: '/materials?view=movements' }] },
      { title: 'Goods received (GRN)', navTitle: 'GRN', url: '/procurement/grn', status: 'planned', phase: 'V1', about: 'Each delivery received against its order: GRN number, challan photo, quantity accepted and rejected, who received it.', example: 'GRN-0117: 150 of 200 bags against PO-0042, 3 torn bags rejected, challan photo attached, received by Arun.', tracker: 'PRC-08', related: [{ title: 'Deliveries today (Movements)', url: '/materials?view=movements' }] },
      { title: 'Pending deliveries', url: '/procurement/pending', status: 'planned', phase: 'V1', about: 'What is ordered but has not arrived, and which orders are late.', example: '3 orders past their date: 50 bags cement from Malabar, 2 days late.', tracker: 'PRC-08' },
      { title: 'Bills', url: '/procurement/bills', status: 'planned', phase: 'V1', about: 'Supplier bills matched to deliveries; material delivered but not billed.', example: 'Bill says 200 bags at ₹420, delivery says 150 at ₹400: flagged.', tracker: 'PRC-11', roles: MONEY_ROLES },
      { title: 'Rates', url: '/procurement/rates', status: 'planned', phase: 'V1', about: 'What each item cost, from which supplier, over time.', example: 'Cement ₹14 more than last time at Malabar.', tracker: 'PRC-14, PRC-16', roles: MONEY_ROLES },
      { title: 'Quotations', url: '/procurement/quotations', status: 'planned', phase: 'V1.5', about: 'Ask several suppliers, compare side by side, pick one.', example: 'Three shops quote for TMT 12 mm.', roles: MONEY_ROLES },
      { title: 'Suppliers', url: '/finance/vendors', status: 'built', phase: 'V1', shortcut: true, about: 'Suppliers with phone and GSTIN.', example: 'Malabar Hardware · GSTIN 32AAAPM…' },
      { title: 'Payables', url: '/finance/payables', status: 'planned', phase: 'V1', shortcut: true, about: 'What you owe each supplier: deliveries, payments, advances, balance.', example: 'Malabar: ₹40,000 + ₹36,000 delivered − ₹50,000 paid = ₹26,000 due.', tracker: 'CC-09, CC-10', roles: MONEY_ROLES },
      { title: 'Reports', url: '/procurement/reports', status: 'planned', phase: 'V1', about: 'Spend by supplier, category and project; late deliveries; rate changes.', example: 'October: ₹28 L bought, 41% from Malabar; 6 late deliveries; cement up 3.5%.', tracker: 'PRC-19', roles: MONEY_ROLES, related: [{ title: 'Movements', url: '/materials?view=movements' }] },
      { title: 'Returns', url: '/procurement/returns', status: 'planned', phase: 'Later', about: 'Material sent back, and what the supplier now owes you (debit note).', example: 'Bent steel returned: Kerala Steels owes ₹8,400.', roles: MONEY_ROLES },
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
    pages: [
      { title: 'Attendance', url: '/labour', status: 'built', phase: 'V1', about: 'Who worked today, by contractor and trade.', example: '4 masons and 2 helpers under Suresh.' },
      { title: 'Workers', url: '/labour?view=workers', status: 'built', phase: 'V1', about: 'Your workers and their daily wage.', example: 'Mason ₹1,200 a day, helper ₹800.' },
      { title: 'Productivity', url: '/labour/productivity', status: 'planned', phase: 'V1', about: 'Labour cost against measured output and the benchmark.', example: '₹6,400 of labour, 180 sq ft plastered, benchmark 160: green.', tracker: 'CC-05', roles: MONEY_ROLES, related: [{ title: 'Attendance', url: '/labour' }] },
      { title: 'Wages & advances', url: '/labour/wages', status: 'planned', phase: 'V1.5', about: 'What each team is owed, advances given, weekly settlement.', example: "Suresh's team: ₹38,400 this week minus ₹5,000 advance.", roles: MONEY_ROLES },
    ],
  },
  {
    key: 'subcontract',
    title: 'Subcontract',
    icon: Handshake,
    tone: 'violet',
    about: 'Work given out at an agreed rate, paid against measured quantity.',
    pages: [
      { title: 'Subcontractors', url: '/subcontract/teams', status: 'planned', phase: 'V1.5', about: 'Every outside team, what they work on, and what you owe each.', example: "Ravi's plastering team: 2 sites, ₹46,000 due, ₹10,000 advance.", roles: MONEY_ROLES },
      { title: 'Work orders', url: '/subcontract/work-orders', status: 'planned', phase: 'V1.5', about: 'Who does which work at what rate.', example: "Plastering to Ravi's team at ₹14 per sq ft, 18,000 sq ft.", roles: MONEY_ROLES },
      { title: 'Bills & checks', url: '/subcontract/bills', status: 'planned', phase: 'V1', about: 'Each payment checked against the quantity measured.', example: '₹15,000 to the concrete team: 2.4 m³ × ₹6,000 = ₹14,400, slight overpay.', tracker: 'CC-06', roles: MONEY_ROLES },
    ],
  },
  {
    key: 'finance',
    title: 'Finance',
    icon: Landmark,
    tone: 'violet',
    module: 'finance',
    about: "Money in and out of the company's accounts.",
    pages: [
      { title: 'Expenses', url: '/finance/expenses', status: 'built', phase: 'V1', about: 'Every expense with its photo and who paid.', example: '₹100 petrol from the engineer\'s petty cash.', roles: MONEY_ROLES },
      { title: 'Money', url: '/finance/money', status: 'built', phase: 'V1', about: 'Accounts and petty cash balances.', example: 'Site petty cash ₹4,200; office bank.' },
      { title: 'Payables', url: '/finance/payables', status: 'planned', phase: 'V1', about: 'What you owe each supplier: deliveries, payments, advances, balance.', example: 'Malabar: ₹40,000 + ₹36,000 delivered − ₹50,000 paid = ₹26,000 due.', tracker: 'CC-09, CC-10', roles: MONEY_ROLES, related: [{ title: 'Vendors', url: '/finance/vendors' }] },
      { title: 'Vendors', url: '/finance/vendors', status: 'built', phase: 'V1', about: 'Suppliers with phone and GSTIN.', example: 'Malabar Hardware · GSTIN 32AAAPM…' },
      { title: 'Tally export', url: '/finance/tally', status: 'planned', phase: 'V1.5', about: "Expenses and bills sent to the accountant's Tally, no retyping.", example: "October's 340 entries exported to Tally in one file.", roles: MONEY_ROLES },
      { title: 'Cash flow', url: '/finance/cash-flow', status: 'planned', phase: 'Later', about: 'Money needed in the coming weeks against money expected in.', example: 'Next month: ₹38 L to pay, ₹30 L expected from RA bills: ₹8 L short.', roles: MONEY_ROLES },
      { title: 'GST & TDS', url: '/finance/tax', status: 'planned', phase: 'Later', about: 'Input GST from bills and TDS deducted from subcontractors, ready for the accountant.', example: 'October: ₹3.1 L input GST; ₹4,600 TDS under 194C.', roles: MONEY_ROLES },
      { title: 'Settings', url: '/finance/settings', status: 'built', phase: 'V1', about: 'Categories and finance options.', example: 'Expense categories.' },
    ],
  },
  {
    key: 'billing',
    title: 'Client billing',
    icon: ReceiptText,
    tone: 'green',
    about: 'Money you collect from the client, in stages against measured work.',
    pages: [
      { title: 'Clients', url: '/billing/clients', status: 'planned', phase: 'V1.5', about: 'Each client, their projects, what they were billed and what they paid.', example: 'Mr. Thomas: villa, ₹62 L billed, ₹50 L received.', roles: MONEY_ROLES },
      { title: 'RA bills', url: '/billing/ra-bills', status: 'planned', phase: 'V1.5', about: 'Stage bills: work measured this period × BOQ rates.', example: 'RA bill 4: ₹12.6 L for work done in October.', roles: MONEY_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }] },
      { title: 'Variations', url: '/billing/variations', status: 'planned', phase: 'Later', about: 'Extra or changed work the client asked for, priced and approved before it is built.', example: 'Client adds a balcony: ₹1.8 L approved on 3 Nov.', roles: MONEY_ROLES },
      { title: 'Payments received', url: '/billing/receipts', status: 'planned', phase: 'Later', about: 'Money in from clients, and the share held back until handover (retention).', example: 'Received ₹12 L of RA bill 4; 5% (₹63,000) held.', roles: MONEY_ROLES },
      { title: 'Client view', url: '/billing/client-view', status: 'planned', phase: 'V1.5', about: 'A link the house owner opens to see progress and photos.', example: 'Mr. Thomas sees his villa\'s week in photos.' },
    ],
  },
  {
    key: 'equipment',
    title: 'Equipment',
    icon: Truck,
    tone: 'teal',
    about: 'Machines, vehicles, and reusable items like shuttering that go missing quietly.',
    pages: [
      { title: 'Machines & hire', url: '/equipment', status: 'planned', phase: 'V1.5', about: 'Hours, fuel and hire charges per machine.', example: 'JCB 6 hours today at ₹1,100 an hour, 30 L diesel.' },
      { title: 'Vehicles', url: '/equipment/vehicles', status: 'planned', phase: 'Later', about: 'Company vehicles: trips, fuel and who used them.', example: 'Tipper: 6 trips of sand today, 40 L diesel.' },
      { title: 'Shuttering & tools', url: '/equipment/assets', status: 'planned', phase: 'V1.5', about: 'Which site holds how many plates, props and tools.', example: '400 plates at the villa, 60 sent to Chennai.' },
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
}
