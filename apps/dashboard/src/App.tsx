import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AppLayout } from '@/components/app-layout'
import { RequireModule } from '@/components/require-module'
import Login from '@/pages/Login'
import Signup from '@/pages/Signup'
import Overview from '@/pages/Overview'
import TodayPage from '@/pages/TodayPage'
import SiteDayPage from '@/pages/SiteDayPage'
import Users from '@/pages/Users'
import UserDetails from '@/pages/UserDetails'
import CompanyDetails from '@/pages/CompanyDetails'
import Projects from '@/pages/Projects'
import ProjectDetails from '@/pages/ProjectDetails'
import DailyReportsPage from '@/pages/DailyReportsPage'
import ActivitiesPage from '@/pages/ActivitiesPage'
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
import OperationsTimelinePage from '@/pages/OperationsTimelinePage'
import OperationsIssuesPage from '@/pages/OperationsIssuesPage'
import OperationsGalleryPage from '@/pages/OperationsGalleryPage'
import OperationsAnalyticsPage from '@/pages/OperationsAnalyticsPage'
import OperationsSettingsPage from '@/pages/OperationsSettingsPage'
import AutomationsPage from '@/pages/AutomationsPage'





import { OperationalPlaceholder } from '@/components/operational-placeholder'

import { ToastProvider } from '@/components/ui/toast-notification'

function IndexRedirect() {
  const location = useLocation()
  return <Navigate to={`/today${location.search}`} replace />
}

function OperationsIndexRedirect() {
  const location = useLocation()
  return <Navigate to={`/operations/dashboard${location.search}`} replace />
}

export default function App() {
  return (
    <ToastProvider>
      <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/" element={<AppLayout />}>
        <Route index element={<IndexRedirect />} />
        <Route path="today" element={<TodayPage />} />
        <Route path="today/sites/:siteId/:date" element={<SiteDayPage />} />
        <Route path="overview" element={<Overview />} />
        <Route path="whatsapp/inbox" element={<WhatsAppInboxPage />} />
        <Route path="users" element={<Users />} />
        <Route path="users/:id" element={<UserDetails />} />
        <Route path="company" element={<CompanyDetails />} />
        <Route path="projects" element={<Projects />} />
        <Route path="projects/:id" element={<ProjectDetails />} />

        {/* Operations Section */}
        <Route path="operations" element={<OperationsIndexRedirect />} />
        <Route path="operations/dashboard" element={<Overview />} />
        <Route path="operations/activities" element={<ActivitiesPage />} />
        <Route path="operations/timeline" element={<OperationsTimelinePage />} />
        <Route path="operations/daily-reports" element={<DailyReportsPage />} />
        <Route path="operations/issues" element={<OperationsIssuesPage />} />

        <Route path="operations/gallery" element={<OperationsGalleryPage />} />

        <Route path="operations/analytics" element={<OperationsAnalyticsPage />} />

        <Route path="operations/automations" element={<RequireModule module="automations"><AutomationsPage /></RequireModule>} />

        <Route path="operations/settings" element={<OperationsSettingsPage />} />



        {/* Finance Section */}
        <Route path="finance" element={<RequireModule module="finance"><Navigate to="/finance/expenses" replace /></RequireModule>} />
        <Route path="finance/overview" element={<RequireModule module="finance"><FinanceOverviewPage /></RequireModule>} />
        <Route path="finance/expenses" element={<RequireModule module="finance"><ExpensesPage /></RequireModule>} />
        <Route path="finance/expenses/:id" element={<RequireModule module="finance"><ExpenseDetailPage /></RequireModule>} />
        <Route path="finance/receipts" element={<RequireModule module="finance"><ReceiptsPage /></RequireModule>} />
        <Route path="finance/accounts" element={<RequireModule module="finance"><AccountsPage /></RequireModule>} />
        <Route path="finance/whatsapp" element={<RequireModule module="finance"><WhatsAppFinancePage /></RequireModule>} />
        <Route path="whatsapp/finance" element={<RequireModule module="finance"><WhatsAppFinancePage /></RequireModule>} />
        <Route path="finance/transactions" element={<RequireModule module="finance"><TransactionsPage /></RequireModule>} />
        <Route path="finance/petty-cash" element={<RequireModule module="finance"><PettyCashPage /></RequireModule>} />
        <Route path="finance/vendors" element={<RequireModule module="finance"><VendorsPage /></RequireModule>} />
        <Route path="finance/categories" element={<RequireModule module="finance"><CategoriesPage /></RequireModule>} />
        <Route path="finance/reports" element={<RequireModule module="finance"><FinanceReportsPage /></RequireModule>} />
        <Route path="finance/settings" element={<RequireModule module="finance"><FinanceSettingsPage /></RequireModule>} />

        {/* Materials Section */}
        <Route path="materials" element={<RequireModule module="materials"><MaterialsPage /></RequireModule>} />
        <Route path="materials/overview" element={<RequireModule module="materials"><MaterialsPage /></RequireModule>} />
        <Route path="materials/inventory" element={<RequireModule module="materials"><OperationalPlaceholder title="Material Inventory" /></RequireModule>} />
        <Route path="materials/purchases" element={<RequireModule module="materials"><OperationalPlaceholder title="Material Purchases" /></RequireModule>} />
        <Route path="materials/suppliers" element={<RequireModule module="materials"><OperationalPlaceholder title="Suppliers" /></RequireModule>} />
        <Route path="materials/categories" element={<RequireModule module="materials"><OperationalPlaceholder title="Material Categories" /></RequireModule>} />

        {/* Labour & Workforce Section */}
        <Route path="labour" element={<RequireModule module="labour"><Navigate to="/labour/attendance" replace /></RequireModule>} />
        <Route path="labour/overview" element={<RequireModule module="labour"><LabourOverviewPage /></RequireModule>} />
        <Route path="labour/attendance" element={<RequireModule module="labour"><AttendancePage /></RequireModule>} />
        <Route path="labour/workers" element={<RequireModule module="labour"><WorkersPage /></RequireModule>} />
        <Route path="labour/whatsapp" element={<RequireModule module="labour"><WhatsAppLabourPage /></RequireModule>} />
        <Route path="whatsapp/labour" element={<RequireModule module="labour"><WhatsAppLabourPage /></RequireModule>} />
        <Route path="labour/analytics" element={<RequireModule module="labour"><LabourAnalyticsPage /></RequireModule>} />
        <Route path="labour/reports" element={<RequireModule module="labour"><LabourReportsPage /></RequireModule>} />
        <Route path="labour/settings" element={<RequireModule module="labour"><LabourSettingsPage /></RequireModule>} />

        {/* Legacy operational routes fallbacks */}
        <Route path="timeline" element={<OperationsTimelinePage />} />
        <Route path="analytics" element={<OperationsAnalyticsPage />} />

        <Route path="gallery" element={<OperationsGalleryPage />} />

        <Route path="reports" element={<OperationalPlaceholder title="Reports" />} />
        <Route path="expenses" element={<RequireModule module="finance"><ExpensesPage /></RequireModule>} />
        <Route path="petty-cash" element={<RequireModule module="finance"><PettyCashPage /></RequireModule>} />
      </Route>
    </Routes>
    </ToastProvider>
  )
}
