import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AppLayout } from '@/components/app-layout'
import Login from '@/pages/Login'
import Overview from '@/pages/Overview'
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
  return <Navigate to={`/overview${location.search}`} replace />
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
      <Route path="/" element={<AppLayout />}>
        <Route index element={<IndexRedirect />} />
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

        <Route path="operations/automations" element={<AutomationsPage />} />

        <Route path="operations/settings" element={<OperationsSettingsPage />} />



        {/* Finance Section */}
        <Route path="finance" element={<Navigate to="/finance/expenses" replace />} />
        <Route path="finance/overview" element={<FinanceOverviewPage />} />
        <Route path="finance/expenses" element={<ExpensesPage />} />
        <Route path="finance/expenses/:id" element={<ExpenseDetailPage />} />
        <Route path="finance/receipts" element={<ReceiptsPage />} />
        <Route path="finance/accounts" element={<AccountsPage />} />
        <Route path="finance/whatsapp" element={<WhatsAppFinancePage />} />
        <Route path="whatsapp/finance" element={<WhatsAppFinancePage />} />
        <Route path="finance/transactions" element={<TransactionsPage />} />
        <Route path="finance/petty-cash" element={<PettyCashPage />} />
        <Route path="finance/vendors" element={<VendorsPage />} />
        <Route path="finance/categories" element={<CategoriesPage />} />
        <Route path="finance/reports" element={<FinanceReportsPage />} />
        <Route path="finance/settings" element={<FinanceSettingsPage />} />

        {/* Materials Section */}
        <Route path="materials" element={<MaterialsPage />} />
        <Route path="materials/overview" element={<MaterialsPage />} />
        <Route path="materials/inventory" element={<OperationalPlaceholder title="Material Inventory" />} />
        <Route path="materials/purchases" element={<OperationalPlaceholder title="Material Purchases" />} />
        <Route path="materials/suppliers" element={<OperationalPlaceholder title="Suppliers" />} />
        <Route path="materials/categories" element={<OperationalPlaceholder title="Material Categories" />} />

        {/* Labour & Workforce Section */}
        <Route path="labour" element={<Navigate to="/labour/attendance" replace />} />
        <Route path="labour/overview" element={<LabourOverviewPage />} />
        <Route path="labour/attendance" element={<AttendancePage />} />
        <Route path="labour/workers" element={<WorkersPage />} />
        <Route path="labour/whatsapp" element={<WhatsAppLabourPage />} />
        <Route path="whatsapp/labour" element={<WhatsAppLabourPage />} />
        <Route path="labour/analytics" element={<LabourAnalyticsPage />} />
        <Route path="labour/reports" element={<LabourReportsPage />} />
        <Route path="labour/settings" element={<LabourSettingsPage />} />

        {/* Legacy operational routes fallbacks */}
        <Route path="timeline" element={<OperationsTimelinePage />} />
        <Route path="analytics" element={<OperationsAnalyticsPage />} />

        <Route path="gallery" element={<OperationsGalleryPage />} />

        <Route path="reports" element={<OperationalPlaceholder title="Reports" />} />
        <Route path="expenses" element={<ExpensesPage />} />
        <Route path="petty-cash" element={<PettyCashPage />} />
      </Route>
    </Routes>
    </ToastProvider>
  )
}
