import { Routes, Route, NavLink } from 'react-router-dom';
import {
  Building2,
  LayoutDashboard,
  Users,
  Settings,
  ScrollText,
  Cpu,
  GitBranch,
  Tags,
  ListChecks,
  FlaskConical,
  Timer,
  ListOrdered,
  Stamp,
  IndianRupee,
  Funnel,
  Database as DatabaseIcon,
  MessageSquareReply
} from 'lucide-react';
import { RequireAuth } from './AuthContext';
import Login from './Login';
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

const Sidebar = () => (
  <div className="sidebar">
    <div className="logo-container">
      <div className="logo-icon">
        <Building2 size={18} />
      </div>
      <div className="logo-text">Mesiri Control</div>
    </div>

    <nav>
      <NavLink to="/" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <LayoutDashboard size={16} />
        Overview
      </NavLink>
      <NavLink to="/organizations" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <Building2 size={16} />
        Companies
      </NavLink>
      <NavLink to="/branding-requests" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <Stamp size={16} />
        Branding requests
      </NavLink>
      <NavLink to="/trials" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <Funnel size={16} />
        Trials
      </NavLink>
      <NavLink to="/costs" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <IndianRupee size={16} />
        Costs
      </NavLink>
      <NavLink to="/logs" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <ScrollText size={16} />
        Assistant Logs
      </NavLink>
      <NavLink to="/database" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <DatabaseIcon size={16} />
        Database
      </NavLink>
      <NavLink to="/providers" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <Cpu size={16} />
        AI Providers
      </NavLink>
      <NavLink to="/replies" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <MessageSquareReply size={16} />
        Reply Insights
      </NavLink>
      <NavLink to="/perf" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <Timer size={16} />
        Performance
      </NavLink>
      <NavLink to="/queue-health" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <ListOrdered size={16} />
        Queue Health
      </NavLink>
      <NavLink to="/system-graph" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <GitBranch size={16} />
        System Graph
      </NavLink>
      <NavLink to="/semantic-types" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <Tags size={16} />
        Semantic Types
      </NavLink>
      <NavLink to="/workflows" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <ListChecks size={16} />
        Workflows
      </NavLink>
      <NavLink to="/test-message" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <FlaskConical size={16} />
        Test Message
      </NavLink>
      <NavLink to="/users" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <Users size={16} />
        Superadmins
      </NavLink>
      <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <Settings size={16} />
        Settings
      </NavLink>
    </nav>
  </div>
);

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

