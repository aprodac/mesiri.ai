import { Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom'
import { AppLayout } from '@/components/app-layout'
import { RequireModule } from '@/components/require-module'
import Login from '@/pages/Login'
import Signup from '@/pages/Signup'
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
import DailyReportsPage from '@/pages/DailyReportsPage'
import MaterialsPage from '@/pages/MaterialsPage'
import ExpensesPage from '@/pages/ExpensesPage'
import ReceiptsPage from '@/pages/ReceiptsPage'
import AccountsPage from '@/pages/AccountsPage'
import WhatsAppFinancePage from '@/pages/WhatsAppFinancePage'
import PettyCashPage from '@/pages/PettyCashPage'
import FinanceOverviewPage from '@/pages/FinanceOverviewPage'
import FinanceReportsPage from '@/pages/FinanceReportsPage'
import FinanceSettingsPage from '@/pages/FinanceSettingsPage'
import ExpenseDetailPage from '@/pages/ExpenseDetailPage'
import TransactionsPage from '@/pages/TransactionsPage'
import VendorsPage from '@/pages/VendorsPage'
import CategoriesPage from '@/pages/CategoriesPage'
import OperationsIssuesPage from '@/pages/OperationsIssuesPage'
import OperationsAnalyticsPage from '@/pages/OperationsAnalyticsPage'
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

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/" element={<AppLayout />}>
          <Route index element={<Moved to="/today" />} />

          {/* Daily */}
          <Route path="today" element={<TodayPage />} />
          <Route path="reports" element={<DailyReportsPage />} />
          <Route path="reports/:date/sites/:siteId" element={<SiteDayPage />} />
          <Route path="reports/:date/projects/:projectId" element={<ProjectDayPage />} />
          <Route path="issues" element={<OperationsIssuesPage />} />

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

          {/* Setup */}
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:id" element={<ProjectDetails />} />
          <Route path="team" element={<Users />} />
          <Route path="team/:id" element={<UserDetails />} />
          <Route path="company" element={<CompanyDetails />} />
          <Route path="company/messages" element={<Moved to="/whatsapp?view=messages" />} />
          <Route path="whatsapp" element={<WhatsAppPage />} />
          <Route path="whatsapp/inbox" element={<Moved to="/whatsapp" />} />
          <Route path="automations" element={<Moved to="/whatsapp?view=automations" />} />

          {/* Finance (module; not in V1 by default) */}
          <Route path="finance" element={fin(<Navigate to="/finance/expenses" replace />)} />
          <Route path="finance/overview" element={fin(<FinanceOverviewPage />)} />
          <Route path="finance/expenses" element={fin(<ExpensesPage />)} />
          <Route path="finance/expenses/:id" element={fin(<ExpenseDetailPage />)} />
          <Route path="finance/receipts" element={fin(<ReceiptsPage />)} />
          <Route path="finance/accounts" element={fin(<AccountsPage />)} />
          <Route path="finance/whatsapp" element={fin(<WhatsAppFinancePage />)} />
          <Route path="finance/transactions" element={fin(<TransactionsPage />)} />
          <Route path="finance/petty-cash" element={fin(<PettyCashPage />)} />
          <Route path="finance/vendors" element={fin(<VendorsPage />)} />
          <Route path="finance/categories" element={fin(<CategoriesPage />)} />
          <Route path="finance/reports" element={fin(<FinanceReportsPage />)} />
          <Route path="finance/settings" element={fin(<FinanceSettingsPage />)} />

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
