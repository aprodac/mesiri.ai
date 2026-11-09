import { Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom'
import { AppLayout } from '@/components/app-layout'
import { RequireModule } from '@/components/require-module'
import Login from '@/pages/Login'
import Signup from '@/pages/Signup'
import WelcomePage from '@/pages/WelcomePage'
import LivePage from '@/pages/LivePage'
import { RequireAuth } from '@/lib/AuthContext'
import TodayPage from '@/pages/TodayPage'
import SiteDayPage from '@/pages/SiteDayPage'
import ProjectDayPage from '@/pages/ProjectDayPage'
import Users from '@/pages/Users'
import UserDetails from '@/pages/UserDetails'
import CompanyDetails from '@/pages/CompanyDetails'
import WhatsAppPage from '@/pages/WhatsAppPage'
import LabourPage from '@/pages/LabourPage'
import SiteLogPage from '@/pages/SiteLogPage'
import Projects from '@/pages/Projects'
import ProjectDetails from '@/pages/ProjectDetails'
import ProjectBoqPage from '@/pages/ProjectBoqPage'
import BoqIndexPage from '@/pages/BoqIndexPage'
import SchedulePage from '@/pages/SchedulePage'
import MaterialPlanPage from '@/pages/MaterialPlanPage'
import PlacesPage from '@/pages/PlacesPage'
import DocumentsPage from '@/pages/DocumentsPage'
import LivePlansPage from '@/pages/LivePlansPage'
import ClientsPage from '@/pages/ClientsPage'
import DrawingCheckPage from '@/pages/DrawingCheckPage'
import RaBillsPage from '@/pages/RaBillsPage'
import RaBillDocumentPage from '@/pages/RaBillDocumentPage'
import ProjectStartPage from '@/pages/ProjectStartPage'
import CostBudgetPage from '@/pages/CostBudgetPage'
import CostVariancePage from '@/pages/CostVariancePage'
import CostHomePage from '@/pages/CostHomePage'
import CostMaterialsPage from '@/pages/CostMaterialsPage'
import TallyExportPage from '@/pages/TallyExportPage'
import TrialBalancePage from '@/pages/accounts/TrialBalancePage'
import DayBookPage from '@/pages/accounts/DayBookPage'
import LedgersPage from '@/pages/accounts/LedgersPage'
import LedgerStatementPage from '@/pages/accounts/LedgerStatementPage'
import ChartOfAccountsPage from '@/pages/accounts/ChartOfAccountsPage'
import PeriodsPage from '@/pages/accounts/PeriodsPage'
import AccountsHomePage from '@/pages/accounts/AccountsHomePage'
import ProfitLossPage from '@/pages/accounts/ProfitLossPage'
import BalanceSheetPage from '@/pages/accounts/BalanceSheetPage'
import CashBankPage from '@/pages/accounts/CashBankPage'
import ProjectsBooksPage from '@/pages/accounts/ProjectsBooksPage'
import ProjectBooksPage from '@/pages/accounts/ProjectBooksPage'
import ReceivablesPage from '@/pages/ReceivablesPage'
import CostCentresPage from '@/pages/CostCentresPage'
import PlannedPage from '@/pages/PlannedPage'
import ApprovalsPage from '@/pages/ApprovalsPage'
import AttentionPage from '@/pages/AttentionPage'
import { PLANNED_PAGES } from '@/lib/module-map'
import DailyReportsPage from '@/pages/DailyReportsPage'
import MaterialsPage from '@/pages/MaterialsPage'
import RequestsPage from '@/pages/RequestsPage'
import PurchaseOrdersPage from '@/pages/PurchaseOrdersPage'
import PurchaseOrderDocumentPage from './pages/PurchaseOrderDocumentPage'
import GoodsReceiptsPage from './pages/GoodsReceiptsPage'
import RatesPage from './pages/RatesPage'
import ExpensesPage from '@/pages/ExpensesPage'
import FinanceReportsPage from '@/pages/FinanceReportsPage'
import FinanceSettingsPage from '@/pages/FinanceSettingsPage'
import VendorsPage from '@/pages/VendorsPage'
import VendorPage from '@/pages/VendorPage'
import MoneyPage from '@/pages/MoneyPage'
import OperationsIssuesPage from '@/pages/OperationsIssuesPage'
import OperationsAnalyticsPage from '@/pages/OperationsAnalyticsPage'
import EquipmentPage from '@/pages/EquipmentPage'
import MachinePage from '@/pages/MachinePage'
import EquipmentLogPage from '@/pages/EquipmentLogPage'
import HireCheckPage from '@/pages/HireCheckPage'
import ReturnablesPage from '@/pages/ReturnablesPage'
import WorkOrdersPage from '@/pages/WorkOrdersPage'
import WorkOrderPage from '@/pages/WorkOrderPage'
import { BillsChecksPage, StatementPage, SubcontractorsPage, WorkOrderDocumentPage } from '@/pages/SubcontractPages'
import { ToastProvider } from '@/components/ui/toast-notification'

// V1 routes (WEB-21, docs/DESIGN.md "Pages and routes"): one address per
// thing, named as the sidebar names it. Every older address redirects so
// bookmarks keep working; anything unknown lands on Today.

/** Redirect to `to`, keeping the query string (scope, filters, date). */
function Moved({ to }: { to: string }) {
  const { search } = useLocation()
  // Keep the old address's query (the scope's project/site), merged with
  // any the new address carries (/labour?view=workers).
  const joined = search && to.includes('?') ? `${to}&${search.slice(1)}` : `${to}${search}`
  return <Navigate to={joined} replace />
}

/** The DPR pages moved from /today/... (date last) to /reports/:date/... */
function MovedDayPage({ level }: { level: 'sites' | 'projects' }) {
  const { id = '', date = '' } = useParams()
  const { search } = useLocation()
  return <Navigate to={`/reports/${date}/${level}/${id}${search}`} replace />
}

function MovedUser() {
  const { id = '' } = useParams()
  return <Navigate to={`/team/${id}`} replace />
}

const fin = (page: React.ReactNode) => <RequireModule module="finance">{page}</RequireModule>
const lab = (page: React.ReactNode) => <RequireModule module="labour">{page}</RequireModule>
const mat = (page: React.ReactNode) => <RequireModule module="materials">{page}</RequireModule>
const eqp = (page: React.ReactNode) => <RequireModule module="equipment">{page}</RequireModule>
const cst = (page: React.ReactNode) => <RequireModule module="cost">{page}</RequireModule>
const acc = (page: React.ReactNode) => <RequireModule module="accounts">{page}</RequireModule>

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        {/* After signup (SS-18): full screen, outside the sidebar layout. */}
        <Route path="/welcome" element={<RequireAuth><WelcomePage /></RequireAuth>} />
        {/* The report writing itself as messages arrive (WEB-37): full screen, for demos too. */}
        <Route path="/live" element={<RequireAuth><LivePage /></RequireAuth>} />
        {/* PRC-26: the purchase order for the supplier, full screen so it prints clean. */}
        <Route path="/procurement/orders/:id/document" element={<RequireAuth><PurchaseOrderDocumentPage /></RequireAuth>} />
        {/* NXT-02: the RA bill for the client, full screen so it prints clean. */}
        <Route path="/billing/ra-bills/:id/document" element={<RequireAuth><RaBillDocumentPage /></RequireAuth>} />
        {/* NXT-05 / NXT-17: the work order and a subcontractor's statement, full screen so they print clean. */}
        <Route path="/subcontract/work-orders/:id/document" element={<RequireAuth><WorkOrderDocumentPage /></RequireAuth>} />
        <Route path="/subcontract/statement/:vendorId" element={<RequireAuth><StatementPage /></RequireAuth>} />
        <Route path="/" element={<AppLayout />}>
          <Route index element={<Moved to="/today" />} />

          {/* Daily */}
          <Route path="today" element={<TodayPage />} />
          <Route path="reports" element={<DailyReportsPage />} />
          <Route path="reports/:date/sites/:siteId" element={<SiteDayPage />} />
          <Route path="reports/:date/projects/:projectId" element={<ProjectDayPage />} />
          <Route path="issues" element={<OperationsIssuesPage />} />
          <Route path="site/approvals" element={<ApprovalsPage />} />
          <Route path="site/attention" element={<AttentionPage />} />

          {/* Site records: everything the sites sent, across days. */}
          <Route path="site-log" element={<SiteLogPage />} />
          <Route path="activities" element={<Moved to="/site-log" />} />
          <Route path="gallery" element={<Moved to="/site-log?view=photos" />} />
          <Route path="timeline" element={<Moved to="/site-log?view=all" />} />
          <Route path="analytics" element={<OperationsAnalyticsPage />} />

          {/* Labour (module): one page, Attendance | Workers (WEB-22). The
              old seven addresses land on the matching view. */}
          <Route path="labour" element={lab(<LabourPage />)} />
          <Route path="labour/workers" element={<Moved to="/labour?view=workers" />} />
          <Route path="labour/*" element={<Moved to="/labour" />} />

          {/* Materials (module): one page with its own tabs. */}
          <Route path="materials" element={mat(<MaterialsPage />)} />
          {/* PRC-22: what the sites ask for, before anyone orders it. */}
          <Route path="materials/requests" element={mat(<RequestsPage />)} />
          {/* PRC-10: orders to suppliers, and what came against them. */}
          <Route path="procurement/orders" element={mat(<PurchaseOrdersPage />)} />
          {/* NXT-05..07: subcontract */}
          <Route path="subcontract/work-orders" element={<WorkOrdersPage />} />
          <Route path="subcontract/work-orders/:id" element={<WorkOrderPage />} />
          <Route path="subcontract/bills" element={<BillsChecksPage />} />
          <Route path="subcontract/teams" element={<SubcontractorsPage />} />
          {/* PRC-29: goods received notes. */}
          <Route path="procurement/grn" element={mat(<GoodsReceiptsPage />)} />
          <Route path="procurement/rates" element={mat(<RatesPage />)} />

          {/* NXT-11 / NXT-13 / NXT-14 / NXT-15: Equipment (module). */}
          <Route path="equipment" element={eqp(<EquipmentPage />)} />
          <Route path="equipment/vehicles" element={eqp(<EquipmentPage kind="vehicle" />)} />
          <Route path="equipment/log" element={eqp(<EquipmentLogPage />)} />
          <Route path="equipment/hire" element={eqp(<HireCheckPage />)} />
          <Route path="equipment/assets" element={eqp(<ReturnablesPage />)} />
          <Route path="equipment/:id" element={eqp(<MachinePage />)} />

          {/* Setup */}
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:id" element={<ProjectDetails />} />
          <Route path="projects/:id/boq" element={<ProjectBoqPage />} />
          <Route path="boq" element={<BoqIndexPage />} />
          {/* ST-04 / ST-05: the start of a project and its schedule. */}
          <Route path="planning/setup" element={<ProjectStartPage />} />
          <Route path="planning/schedule" element={<SchedulePage />} />
          <Route path="planning/materials" element={<MaterialPlanPage />} />
          <Route path="planning/places" element={<PlacesPage />} />
          <Route path="planning/documents" element={<DocumentsPage />} />
          <Route path="planning/live" element={<LivePlansPage />} />
          <Route path="planning/drawing-check" element={<DrawingCheckPage />} />
          <Route path="billing/clients" element={<ClientsPage />} />
          <Route path="billing/ra-bills" element={<RaBillsPage />} />
          {/* CC-01 / CC-04 / CC-07: the Cost control module. */}
          <Route path="cost" element={cst(<CostHomePage />)} />
          <Route path="cost/green-red" element={cst(<CostVariancePage />)} />
          <Route path="cost/materials" element={cst(<CostMaterialsPage />)} />
          <Route path="cost/budget" element={cst(<CostBudgetPage />)} />
          <Route path="cost/centres" element={cst(<CostCentresPage />)} />
          {/* WEB-72: planned module pages (lib/module-map.ts). Only shown while "Show planned
              modules" is on; otherwise PlannedPage sends the address to Today. */}
          {PLANNED_PAGES.map(({ page }) => (
            <Route key={page.url} path={page.url.slice(1)} element={<PlannedPage />} />
          ))}
          <Route path="team" element={<Users />} />
          <Route path="team/:id" element={<UserDetails />} />
          <Route path="company" element={<CompanyDetails />} />
          <Route path="company/messages" element={<Moved to="/whatsapp?view=messages" />} />
          <Route path="whatsapp" element={<WhatsAppPage />} />
          <Route path="whatsapp/inbox" element={<Moved to="/whatsapp" />} />
          <Route path="automations" element={<Moved to="/whatsapp?view=automations" />} />

          {/* Finance (module; not in V1 by default) */}
          <Route path="finance" element={fin(<Navigate to="/finance/expenses" replace />)} />
          {/* WEB-51: Finance is four pages (Expenses, Money, Vendors, Settings); the old addresses land on the right one. */}
          <Route path="finance/expenses" element={fin(<ExpensesPage />)} />
          <Route path="finance/expenses/:id" element={fin(<ExpensesPage />)} />
          <Route path="finance/money" element={fin(<MoneyPage />)} />
          <Route path="finance/vendors" element={fin(<VendorsPage />)} />
          <Route path="accounts/tally" element={fin(<TallyExportPage />)} />
          <Route path="accounts" element={acc(<AccountsHomePage />)} />
          <Route path="accounts/pl" element={acc(<ProfitLossPage />)} />
          <Route path="accounts/balance-sheet" element={acc(<BalanceSheetPage />)} />
          <Route path="accounts/cash-bank" element={acc(<CashBankPage />)} />
          <Route path="accounts/projects" element={acc(<ProjectsBooksPage />)} />
          <Route path="accounts/projects/:id" element={acc(<ProjectBooksPage />)} />
          <Route path="accounts/project-pl" element={<Navigate to="/accounts/projects" replace />} />
          <Route path="accounts/trial-balance" element={acc(<TrialBalancePage />)} />
          <Route path="accounts/day-book" element={acc(<DayBookPage />)} />
          <Route path="accounts/ledgers" element={acc(<LedgersPage />)} />
          <Route path="accounts/ledgers/:id" element={acc(<LedgerStatementPage />)} />
          <Route path="accounts/chart" element={acc(<ChartOfAccountsPage />)} />
          <Route path="accounts/periods" element={acc(<PeriodsPage />)} />
          <Route path="accounts/receivables" element={fin(<ReceivablesPage />)} />
          <Route path="finance/vendors/:id" element={fin(<VendorPage />)} />
          <Route path="finance/settings" element={fin(<FinanceSettingsPage />)} />
          <Route path="finance/reports" element={fin(<FinanceReportsPage />)} />
          <Route path="finance/overview" element={<Navigate to="/finance/expenses" replace />} />
          <Route path="finance/receipts" element={<Navigate to="/finance/expenses?photo=yes" replace />} />
          <Route path="finance/accounts" element={<Navigate to="/finance/money" replace />} />
          <Route path="finance/petty-cash" element={<Navigate to="/finance/money" replace />} />
          <Route path="finance/transactions" element={<Navigate to="/finance/money?view=transactions" replace />} />
          <Route path="finance/categories" element={<Navigate to="/finance/settings" replace />} />
          <Route path="finance/whatsapp" element={<Navigate to="/finance/settings" replace />} />

          {/* Old addresses */}
          <Route path="today/sites/:id/:date" element={<MovedDayPage level="sites" />} />
          <Route path="today/projects/:id/:date" element={<MovedDayPage level="projects" />} />
          <Route path="operations/daily-reports" element={<Moved to="/reports" />} />
          <Route path="operations/issues" element={<Moved to="/issues" />} />
          <Route path="operations/automations" element={<Moved to="/whatsapp?view=automations" />} />
          <Route path="operations/activities" element={<Moved to="/site-log" />} />
          <Route path="operations/gallery" element={<Moved to="/site-log?view=photos" />} />
          <Route path="operations/timeline" element={<Moved to="/site-log?view=all" />} />
          <Route path="operations/analytics" element={<Moved to="/analytics" />} />
          <Route path="users" element={<Moved to="/team" />} />
          <Route path="users/:id" element={<MovedUser />} />
          <Route path="materials/*" element={<Moved to="/materials" />} />
          <Route path="whatsapp/finance" element={<Moved to="/finance/whatsapp" />} />
          <Route path="whatsapp/labour" element={<Moved to="/labour" />} />
          <Route path="expenses" element={<Moved to="/finance/expenses" />} />
          <Route path="petty-cash" element={<Moved to="/finance/petty-cash" />} />
          {/* Removed pages (the operations dashboard -- Today does its job --
              and operations settings, which nothing read) and anything unknown. */}
          <Route path="*" element={<Moved to="/today" />} />
        </Route>
      </Routes>
    </ToastProvider>
  )
}
