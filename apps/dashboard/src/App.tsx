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
import Projects from '@/pages/Projects'
import ProjectDetails from '@/pages/ProjectDetails'
import DailyReportsPage from '@/pages/DailyReportsPage'
import MaterialsPage from '@/pages/MaterialsPage'
import ExpensesPage from '@/pages/ExpensesPage'
import ReceiptsPage from '@/pages/ReceiptsPage'
import AccountsPage from '@/pages/AccountsPage'
import WhatsAppFinancePage from '@/pages/WhatsAppFinancePage'
import WhatsAppLabourPage from '@/pages/WhatsAppLabourPage'
import LabourAnalyticsPage from '@/pages/LabourAnalyticsPage'
import LabourOverviewPage from '@/pages/LabourOverviewPage'
import LabourReportsPage from '@/pages/LabourReportsPage'
import LabourSettingsPage from '@/pages/LabourSettingsPage'
import AttendancePage from '@/pages/AttendancePage'
import WhatsAppInboxPage from '@/pages/WhatsAppInboxPage'
import WorkersPage from '@/pages/WorkersPage'
import PettyCashPage from '@/pages/PettyCashPage'
import FinanceOverviewPage from '@/pages/FinanceOverviewPage'
import FinanceReportsPage from '@/pages/FinanceReportsPage'
import FinanceSettingsPage from '@/pages/FinanceSettingsPage'
import ExpenseDetailPage from '@/pages/ExpenseDetailPage'
import TransactionsPage from '@/pages/TransactionsPage'
import VendorsPage from '@/pages/VendorsPage'
import CategoriesPage from '@/pages/CategoriesPage'
import OperationsIssuesPage from '@/pages/OperationsIssuesPage'
import ActivitiesPage from '@/pages/ActivitiesPage'
import OperationsGalleryPage from '@/pages/OperationsGalleryPage'
import OperationsTimelinePage from '@/pages/OperationsTimelinePage'
import OperationsAnalyticsPage from '@/pages/OperationsAnalyticsPage'
import AutomationsPage from '@/pages/AutomationsPage'
import { ToastProvider } from '@/components/ui/toast-notification'

// V1 routes (WEB-21, docs/DESIGN.md "Pages and routes"): one address per
// thing, named as the sidebar names it. Every older address redirects so
// bookmarks keep working; anything unknown lands on Today.

/** Redirect to `to`, keeping the query string (scope, filters, date). */
function Moved({ to }: { to: string }) {
  const { search } = useLocation()
  return <Navigate to={`${to}${search}`} replace />
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
          <Route path="activities" element={<ActivitiesPage />} />
          <Route path="gallery" element={<OperationsGalleryPage />} />
          <Route path="timeline" element={<OperationsTimelinePage />} />
          <Route path="analytics" element={<OperationsAnalyticsPage />} />

          {/* Labour (module). Its pages are unchanged; folding them into
              Attendance + Workers waits for approval (CLAUDE.md, Labour). */}
          <Route path="labour" element={lab(<Navigate to="/labour/attendance" replace />)} />
          <Route path="labour/overview" element={lab(<LabourOverviewPage />)} />
          <Route path="labour/attendance" element={lab(<AttendancePage />)} />
          <Route path="labour/workers" element={lab(<WorkersPage />)} />
          <Route path="labour/whatsapp" element={lab(<WhatsAppLabourPage />)} />
          <Route path="labour/analytics" element={lab(<LabourAnalyticsPage />)} />
          <Route path="labour/reports" element={lab(<LabourReportsPage />)} />
          <Route path="labour/settings" element={lab(<LabourSettingsPage />)} />

          {/* Materials (module): one page with its own tabs. */}
          <Route path="materials" element={mat(<MaterialsPage />)} />

          {/* Setup */}
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:id" element={<ProjectDetails />} />
          <Route path="team" element={<Users />} />
          <Route path="team/:id" element={<UserDetails />} />
          <Route path="company" element={<CompanyDetails />} />
          <Route path="whatsapp/inbox" element={<WhatsAppInboxPage />} />
          <Route path="automations" element={<RequireModule module="automations"><AutomationsPage /></RequireModule>} />

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
          <Route path="operations/automations" element={<Moved to="/automations" />} />
          <Route path="operations/activities" element={<Moved to="/activities" />} />
          <Route path="operations/gallery" element={<Moved to="/gallery" />} />
          <Route path="operations/timeline" element={<Moved to="/timeline" />} />
          <Route path="operations/analytics" element={<Moved to="/analytics" />} />
          <Route path="users" element={<Moved to="/team" />} />
          <Route path="users/:id" element={<MovedUser />} />
          <Route path="materials/*" element={<Moved to="/materials" />} />
          <Route path="whatsapp/finance" element={<Moved to="/finance/whatsapp" />} />
          <Route path="whatsapp/labour" element={<Moved to="/labour/whatsapp" />} />
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
