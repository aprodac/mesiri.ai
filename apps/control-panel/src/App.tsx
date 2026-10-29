import { Routes, Route } from 'react-router-dom';
import { RequireAuth } from './AuthContext';
import Login from './Login';
import Sidebar from './Sidebar';
import Logs from './Logs';
import SettingsPage from './Settings';
import PlatformUsers from './PlatformUsers';
import Providers from './Providers';
import SystemGraph from './SystemGraph';
import SemanticTypes from './SemanticTypes';
import Workflows from './Workflows';
import TestMessage from './TestMessage';
import OrganizationDetail from './OrganizationDetail';
import Companies from './Companies';
import BrandingRequests from './BrandingRequests';
import Costs from './Costs';
import Trials from './Trials';
import Perf from './Perf';
import Replies from './Replies';
import QueueHealth from './QueueHealth';
import Database from './Database';
import Overview from './Overview';

function AppLayout() {
  return (
    <RequireAuth>
      <div className="app-container">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/organizations" element={<Companies />} />
            <Route path="/organizations/:id" element={<OrganizationDetail />} />
            <Route path="/branding-requests" element={<BrandingRequests />} />
            <Route path="/costs" element={<Costs />} />
            <Route path="/trials" element={<Trials />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/database" element={<Database />} />
            <Route path="/providers" element={<Providers />} />
            <Route path="/replies" element={<Replies />} />
            <Route path="/perf" element={<Perf />} />
            <Route path="/queue-health" element={<QueueHealth />} />
            <Route path="/system-graph" element={<SystemGraph />} />
            <Route path="/semantic-types" element={<SemanticTypes />} />
            <Route path="/workflows" element={<Workflows />} />
            <Route path="/test-message" element={<TestMessage />} />
            <Route path="/users" element={<PlatformUsers />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Overview />} />
          </Routes>
        </main>
      </div>
    </RequireAuth>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={<AppLayout />} />
    </Routes>
  );
}

export default App;

