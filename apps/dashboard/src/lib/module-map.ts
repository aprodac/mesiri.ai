import {
  AlertCircle,
  BarChart3,
  BookOpenCheck,
  Boxes,
  Calculator,
  CalendarDays,
  ClipboardCheck,
  ClipboardList,
  FileSearch,
  FileText,
  Gauge,
  HardHat,
  FolderOpen,
  Layers,
  PackageSearch,
  Handshake,
  Landmark,
  ReceiptText,
  ShoppingCart,
  Truck,
  Activity,
  CalendarRange,
  ListTodo,
  ShieldAlert,
  Rocket,
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
      { title: 'Project start', url: '/planning/setup', status: 'built', phase: 'V1', about: 'From "we won it" to "work starts": stage, contract dates, the BOQ from your Excel, the schedule, the site team, suppliers.', example: 'Upload the estimate sheet; 214 BOQ lines and a first schedule in 20 minutes.', tracker: 'ST-01, ST-03, ST-05', roles: MANAGERS, related: [{ title: 'Items', url: '/materials?view=items' }] },
      { title: 'Schedule', url: '/planning/schedule', status: 'built', phase: 'V1', about: 'The project timeline: what should happen when, what site has done, what is late and what it pushes.', example: 'Excavation 3 days late at 60%: footings and slab move; forecast handover 27 Nov.', tracker: 'ST-04' },
      { title: 'BOQ & budget', url: '/boq', status: 'built', phase: 'V1', shortcut: true, about: 'Every work item with its quantity, client rate and budget rate.', example: 'Plastering 18,000 sq ft at ₹42; budget ₹36 per sq ft.', tracker: 'CC-02', roles: MONEY_ROLES },
      { title: 'Material plan', url: '/planning/materials', status: 'built', phase: 'V1', about: 'What each material is needed for, week by week, from the BOQ and the schedule, against stock and orders; red from the week it runs short.', example: 'First floor slab on 20 Nov needs 380 bags cement; 150 in stock: short from the week of 17 Nov.', tracker: 'MP-01, MP-02', roles: MONEY_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }, { title: 'Stock', url: '/materials' }] },
      { title: 'Rate library', url: '/planning/rates', status: 'planned', phase: 'V1', about: "Standard output and material per unit of work, so a BOQ can be priced without a consultant.", example: 'Plastering 12 mm: 1 mason + 1 helper ≈ 80 sq ft a day. 1 m³ M20 ≈ 8 bags cement.', tracker: 'MP-01 (per BOQ line, built)', roles: MANAGERS, related: [{ title: 'BOQ & budget', url: '/boq' }, { title: 'Material plan', url: '/planning/materials' }] },
      { title: 'Places', url: '/planning/places', status: 'built', phase: 'V1', about: 'Every floor and room coloured by the work site reported there, with the photos of each room; "what\'s left on the first floor?" on WhatsApp.', example: 'First floor: plastering done in all 5 rooms; tiling left in Room-2 and the kitchen.', tracker: 'LP-01..LP-05', related: [{ title: 'Schedule', url: '/planning/schedule' }] },
      { title: 'Drawing check', url: '/planning/drawing-check', status: 'built', phase: 'V1', about: 'Drop the architect\'s PDF: its sheets, levels, room sizes and fixtures, and what to ask the architect before it reaches site.', example: 'ROOM-1 is drawn 1740 x 590 cm (1,105 sq ft) but labelled 1,217 sq ft: the label looks copied from ROOM-2.', tracker: 'DR-01..DR-04', roles: MONEY_ROLES },
      { title: 'Drawings', url: '/planning/drawings', status: 'planned', phase: 'V1.5', about: 'Marking up drawings and linking their elements to progress. The register of drawings and their revisions is in Documents.', example: 'Column C4 on S-101 marked poured on 12 Nov.', tracker: 'DRW', related: [{ title: 'Documents', url: '/planning/documents' }] },
      { title: 'Documents', url: '/planning/documents', status: 'built', phase: 'V1', about: 'Drawings with their revision, permits with their expiry, the contract and estimate (office only), per project; "send me the latest S-101" on WhatsApp.', example: 'S-101 rev C uploaded: rev B marked out of date. Building permit expires 3 Dec.', tracker: 'DOC-01, DR-07', related: [{ title: 'Drawing check', url: '/planning/drawing-check' }] },
      { title: 'Tasks', url: '/planning/tasks', status: 'planned', phase: 'V1.5', about: 'Who does what by when.', example: 'Arun: tie steel for grid B by Thursday.' },
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
    pages: [
      { title: 'BOQ & budget', url: '/boq', status: 'built', phase: 'V1', about: 'Every work item with its quantity, client rate and budget rate, the work done on it and the budget it earned.', example: 'Plastering 18,000 sq ft at ₹42; budget ₹36 per sq ft.', tracker: 'CC-02, CC-04', roles: MONEY_ROLES },
      { title: 'Green / red', url: '/cost', status: 'planned', phase: 'V1', about: "Each day's cost against the value of the work done, per work item.", example: 'Plastering green (₹6,400 of labour, 180 sq ft done); brickwork red, ₹2,100 over.', tracker: 'CC-07, CC-11', roles: MONEY_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }, { title: 'Attendance', url: '/labour' }] },
      { title: 'Budget vs actual', url: '/cost/budget', status: 'built', phase: 'V1', about: 'For a project: the budget, the budget earned by the work done, and the money spent, for labour, materials and subcontract; per BOQ line the labour put on it against the labour it earned.', example: 'Plastering: ₹8,680 of labour earned, ₹4,400 spent, ₹4,280 under.', tracker: 'CC-04, CC-05', roles: MONEY_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }] },
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
    pages: [
      { title: 'Stock', url: '/materials?view=stock', status: 'built', phase: 'V1', about: 'What is on site now, how long it lasts, what is coming on orders and what the sites asked for.', example: 'Cement: 217 bags, lasts about 10 days, 200 coming on PO-0042.', tracker: 'WEB-77' },
      { title: 'Movements', url: '/materials?view=movements', status: 'built', phase: 'V1', about: 'The register: every delivery, use and move.', example: '+100 bags cement from Malabar Hardware, ₹41,400.' },
      { title: 'Items', url: '/materials?view=items', status: 'built', phase: 'V1', about: 'Your list of materials, with category and unit.', example: 'Cement OPC 53 · Structural › Concrete · bags.', roles: MANAGERS },
      { title: 'Requests', url: '/materials/requests', status: 'built', phase: 'V1', about: 'What the site asks for, before anyone orders it.', example: 'Engineer: need 200 bags cement by Friday for the first-floor slab.', tracker: 'PRC-22', related: [{ title: 'Stock', url: '/materials' }] },
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
      // PRC-31: requests and orders are one flow; Requests also sits here (the same page as Materials > Requests).
      { title: 'Requests', url: '/materials/requests', status: 'built', phase: 'V1', shortcut: true, about: 'What the sites ask for, before anyone orders it.', example: 'Engineer: need 200 bags cement by Friday for the first-floor slab.', tracker: 'PRC-22' },
      { title: 'Purchase orders', url: '/procurement/orders', status: 'built', phase: 'V1', about: 'Orders to suppliers, with what is still to arrive and duplicate warnings.', example: 'PO-0042 to Malabar: 200 bags at ₹400, 150 delivered, 50 pending.', tracker: 'PRC-06..10', related: [{ title: 'Movements', url: '/materials?view=movements' }] },
      { title: 'Goods received (GRN)', navTitle: 'GRN', url: '/procurement/grn', status: 'built', phase: 'V1', about: 'Each delivery received against its order: GRN number, challan photo, quantity accepted and rejected, who received it.', example: 'GRN-0117: 150 of 200 bags against PO-0042, 3 torn bags rejected, challan photo attached, received by Arun.', tracker: 'PRC-08', related: [{ title: 'Deliveries today (Movements)', url: '/materials?view=movements' }] },
      { title: 'Pending deliveries', url: '/procurement/pending', status: 'planned', phase: 'V1', about: 'What is ordered but has not arrived, and which orders are late.', example: '3 orders past their date: 50 bags cement from Malabar, 2 days late.', tracker: 'PRC-08' },
      { title: 'Bills', url: '/procurement/bills', status: 'planned', phase: 'V1', about: 'Supplier bills matched to deliveries; material delivered but not billed.', example: 'Bill says 200 bags at ₹420, delivery says 150 at ₹400: flagged.', tracker: 'PRC-11', roles: MONEY_ROLES },
      { title: 'Rates', url: '/procurement/rates', status: 'built', phase: 'V1', about: 'What each item cost, from which supplier, over time.', example: 'Cement ₹14 more than last time at Malabar.', tracker: 'PRC-14, PRC-16', roles: MONEY_ROLES },
      { title: 'Quotations', url: '/procurement/quotations', status: 'planned', phase: 'V1.5', about: 'Ask several suppliers, compare side by side, pick one.', example: 'Three shops quote for TMT 12 mm.', roles: MONEY_ROLES },
      { title: 'Suppliers', url: '/finance/vendors', status: 'built', phase: 'V1', shortcut: true, about: 'Suppliers with phone, GSTIN and credit days, and what you owe each one.', example: 'Malabar Hardware · ₹26,000 due, ₹10,000 overdue' },
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
      { title: 'Productivity', url: '/labour/productivity', status: 'planned', phase: 'V1', about: 'Labour cost against measured output and the benchmark. Labour is put on BOQ lines in Cost control > Budget vs actual (CC-05); this page is the colour per line (CC-07).', example: '₹6,400 of labour, 180 sq ft plastered, benchmark 160: green.', tracker: 'CC-05, CC-07', roles: MONEY_ROLES, related: [{ title: 'Attendance', url: '/labour' }] },
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
      { title: 'Subcontractors', url: '/subcontract/teams', status: 'built', phase: 'V1', tracker: 'NXT-05..07', about: 'Every outside team, what they work on, and what you owe each.', example: "Ravi's plastering team: 2 sites, ₹46,000 due, ₹10,000 advance.", roles: MONEY_ROLES },
      { title: 'Work orders', url: '/subcontract/work-orders', status: 'built', phase: 'V1', tracker: 'NXT-05', about: 'Who does which work at what rate.', example: "Plastering to Ravi's team at ₹14 per sq ft, 18,000 sq ft." },
      { title: 'Bills & checks', url: '/subcontract/bills', status: 'built', phase: 'V1', about: 'Each payment checked against the quantity measured.', example: '₹15,000 to the concrete team: 2.4 m³ × ₹6,000 = ₹14,400, slight overpay.', tracker: 'CC-06', roles: MONEY_ROLES },
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
      { title: 'Suppliers', url: '/finance/vendors', status: 'built', phase: 'V1', about: 'Suppliers, subcontractors, hire and services, and what you owe each: bills, deliveries not billed, payments, advances, balance.', example: 'Malabar: ₹40,000 + ₹36,000 delivered − ₹50,000 paid = ₹26,000 due.', tracker: 'CC-09, CC-10' },
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
    pages: [
      { title: 'Project P&L', url: '/accounts/project-pl', status: 'planned', phase: 'V1.5', about: 'Profit or loss of each project: billed to the client minus every cost booked to it.', example: 'Villa Kakkanad: ₹62 L billed, ₹54.8 L cost, ₹7.2 L profit (11.6%).', tracker: 'CC-14', roles: MONEY_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }] },
      { title: 'Party ledgers', url: '/accounts/ledgers', status: 'planned', phase: 'V1.5', about: 'One running account per party (suppliers: built, on each supplier\'s page; clients: with RA bills): every bill, payment and advance, with the balance.', example: "Ravi's team: 3 bills ₹1.26 L, paid ₹1.0 L, advance ₹10,000 → ₹16,000 due.", tracker: 'CC-09', roles: MONEY_ROLES, related: [{ title: 'Suppliers', url: '/finance/vendors' }] },
      { title: 'Receivables', url: '/accounts/receivables', status: 'planned', phase: 'V1.5', about: 'What clients owe you, oldest first, with reminders.', example: 'Mr. Thomas: RA bill 4 ₹12.6 L, 18 days overdue.', roles: MONEY_ROLES },
      { title: 'Cash & bank book', url: '/accounts/cash-bank', status: 'planned', phase: 'V1.5', about: 'Every receipt and payment per cash box and bank account, day by day, with the balance.', example: 'SBI current: opening ₹8.4 L, 12 payments, 2 receipts, closing ₹5.1 L.', roles: MONEY_ROLES, related: [{ title: 'Money', url: '/finance/money' }] },
      { title: 'Day book', url: '/accounts/day-book', status: 'planned', phase: 'V1.5', about: 'Every entry of a day in one list: purchases, expenses, payments, receipts, journals.', example: '6 Nov: 31 entries, ₹4.6 L out, ₹12 L in.', roles: MONEY_ROLES },
      { title: 'Tally sync', url: '/accounts/tally', status: 'planned', phase: 'V1.5', about: "Bills, expenses and payments sent to the accountant's Tally with the right ledgers, no retyping.", example: "October's 340 entries posted to Tally; 2 need a ledger name.", roles: MONEY_ROLES },
      { title: 'Bank reconciliation', url: '/accounts/bank-reco', status: 'planned', phase: 'Later', about: 'Match the bank statement with your entries; show what is missing on either side.', example: '₹45,000 UPI to Malabar in the bank, not entered in Mesiri.', roles: MONEY_ROLES },
      { title: 'Vouchers', url: '/accounts/vouchers', status: 'planned', phase: 'Later', about: 'Payment, receipt, journal and contra entries, numbered and approved.', example: 'PV-0231: ₹50,000 to Malabar Hardware, approved by the GM.', roles: MONEY_ROLES },
      { title: 'GST', url: '/accounts/gst', status: 'planned', phase: 'Later', about: 'Input GST from purchase bills and output GST on client bills, ready for GSTR-1 and 3B.', example: 'October: ₹3.1 L input credit, ₹2.2 L output tax.', roles: MONEY_ROLES },
      { title: 'TDS', url: '/accounts/tds', status: 'planned', phase: 'Later', about: 'TDS deducted from subcontractors and professionals, with what to deposit and certificates.', example: 'October: ₹4,600 under 194C from 3 subcontractors; due 7 Nov.', roles: MONEY_ROLES },
      { title: 'Cash flow', url: '/accounts/cash-flow', status: 'planned', phase: 'Later', about: 'Money needed in the coming weeks against money expected in.', example: 'Next month: ₹38 L to pay, ₹30 L expected from RA bills: ₹8 L short.', roles: MONEY_ROLES },
      { title: 'Profit & loss', url: '/accounts/pl', status: 'planned', phase: 'Later', about: 'The company\'s income and expenses for a period.', example: 'April to October: ₹4.2 cr income, ₹3.8 cr expenses.', roles: MONEY_ROLES },
      { title: 'Balance sheet', url: '/accounts/balance-sheet', status: 'planned', phase: 'Later', about: 'What the company owns and owes on a date.', example: 'As on 31 Oct: stock ₹22 L, receivables ₹48 L, payables ₹31 L.', roles: MONEY_ROLES },
      { title: 'Trial balance', url: '/accounts/trial-balance', status: 'planned', phase: 'Later', about: 'Every ledger balance, debits equal to credits, for the CA.', example: '214 ledgers; debits = credits = ₹6.9 cr.', roles: MONEY_ROLES },
      { title: 'Chart of accounts', url: '/accounts/chart', status: 'planned', phase: 'Later', about: 'The ledgers and groups the books use, matched to the CA\'s Tally.', example: 'Sundry creditors › Malabar Hardware; Direct expenses › Site labour.', roles: MANAGERS },
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
    pages: [
      { title: 'Clients', url: '/billing/clients', status: 'built', phase: 'V1', about: 'Each client, their projects and contract values; the terms each RA bill uses.', example: 'Mr. Thomas: villa, ₹62 L contract, 5% retention.', tracker: 'NXT-01', roles: BILLING_ROLES },
      { title: 'RA bills', url: '/billing/ra-bills', status: 'built', phase: 'V1', about: 'Running bills from the work site measured since the last bill × the client rates, with retention, advance recovery, GST and TDS worked out; printed on your letterhead.', example: 'RA-04: ₹12.6 L of work in October, ₹11.9 L net after retention and TDS.', tracker: 'NXT-02', roles: BILLING_ROLES, related: [{ title: 'BOQ & budget', url: '/boq' }] },
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
    module: 'equipment',
    pages: [
      { title: 'Machines', url: '/equipment', status: 'built', phase: 'V1', about: 'Every machine on every site: hours worked, idle and broken down, diesel, hire cost, service due.', example: 'JCB 6 hours today at ₹1,100 an hour, 30 L diesel.', tracker: 'NXT-11' },
      { title: 'Daily log', url: '/equipment/log', status: 'built', phase: 'V1', about: "One day, every machine: the evening's figures in one screen.", example: 'JCB 6 h, mixer 8 h, roller broke down 3 h.', tracker: 'NXT-11' },
      { title: 'Hire check', url: '/equipment/hire', status: 'built', phase: 'V1', about: 'The hire bill against the hours recorded on site.', example: 'Bill says 220 h; 186 h recorded: ₹37,400 more than the site says.', tracker: 'NXT-13', roles: MONEY_ROLES },
      { title: 'Vehicles', url: '/equipment/vehicles', status: 'built', phase: 'V1', about: 'Company vehicles: trips, fuel and who drove.', example: 'Tipper: 6 trips of sand today, 40 L diesel.', tracker: 'NXT-15' },
      { title: 'Shuttering & tools', url: '/equipment/assets', status: 'built', phase: 'V1', about: 'Which site holds how many plates, props and tools.', example: '400 plates at the villa, 60 sent to Chennai.', tracker: 'NXT-14' },
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
  '/planning/setup': Rocket,
  '/planning/schedule': CalendarRange,
  '/planning/materials': PackageSearch,
  '/planning/places': Layers,
  '/planning/documents': FolderOpen,
  '/planning/drawing-check': FileSearch,
}
