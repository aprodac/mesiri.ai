import { useEffect, useState } from 'react';
import { Routes, Route, NavLink, useNavigate } from 'react-router-dom';
import {
  Building2,
  LayoutDashboard,
  Users,
  Settings,
  Plus,
  Server,
  Cloud,
  TrendingUp,
  Activity,
  ScrollText,
  Cpu,
  GitBranch,
  Tags,
  ListChecks,
  FlaskConical,
  HeartPulse,
  Timer,
  ListOrdered
} from 'lucide-react';
import { api } from './api';
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
import SyncHealth from './SyncHealth';
import Perf from './Perf';
import QueueHealth from './QueueHealth';

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
        Organizations
      </NavLink>
      <NavLink to="/logs" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <ScrollText size={16} />
        Assistant Logs
      </NavLink>
      <NavLink to="/providers" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <Cpu size={16} />
        AI Providers
      </NavLink>
      <NavLink to="/sync-health" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <HeartPulse size={16} />
        Sync Health
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

const Dashboard = () => (
  <div className="animate-fade-in" style={{ maxWidth: '1200px' }}>
    <header style={{ marginBottom: 'var(--space-8)' }}>
      <h1>Fleet Overview</h1>
      <p className="subtitle">Manage SaaS and On-Premise tenant deployments.</p>
    </header>
    
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 'var(--space-6)', marginBottom: 'var(--space-10)' }}>
      {/* High-Emphasis Intelligence Dark Component */}
      <div className="card-dark">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--space-4)' }}>
          <div>
            <h2 style={{ fontSize: '14px', fontWeight: 500, margin: 0, color: 'var(--neutral-400)' }}>Total Organizations</h2>
            <div style={{ fontSize: '32px', fontWeight: 600, marginTop: 'var(--space-2)', color: 'var(--white)' }}>24</div>
          </div>
          <div style={{ padding: 'var(--space-2)', backgroundColor: 'rgba(126, 217, 87, 0.1)', borderRadius: 'var(--radius-sm)', color: 'var(--primary)' }}>
            <Activity size={20} />
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '12px', color: 'var(--primary)' }}>
          <TrendingUp size={14} />
          <span>+3 this month</span>
        </div>
      </div>
      
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--space-4)' }}>
          <div>
            <h2 style={{ fontSize: '14px', fontWeight: 500, margin: 0, color: 'var(--neutral-500)' }}>SaaS Tenants</h2>
            <div style={{ fontSize: '32px', fontWeight: 600, marginTop: 'var(--space-2)', color: 'var(--neutral-900)' }}>18</div>
          </div>
          <div style={{ padding: 'var(--space-2)', backgroundColor: 'var(--info-soft)', borderRadius: 'var(--radius-sm)', color: 'var(--info)' }}>
            <Cloud size={20} />
          </div>
        </div>
        <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>
          Shared Cluster 01 & 02
        </div>
      </div>

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--space-4)' }}>
          <div>
            <h2 style={{ fontSize: '14px', fontWeight: 500, margin: 0, color: 'var(--neutral-500)' }}>On-Prem Instances</h2>
            <div style={{ fontSize: '32px', fontWeight: 600, marginTop: 'var(--space-2)', color: 'var(--neutral-900)' }}>6</div>
          </div>
          <div style={{ padding: 'var(--space-2)', backgroundColor: 'var(--warning-soft)', borderRadius: 'var(--radius-sm)', color: 'var(--warning)' }}>
            <Server size={20} />
          </div>
        </div>
        <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>
          Dedicated Infrastructure
        </div>
      </div>
    </div>
  </div>
);

interface Organization {
  id: string;
  name: string;
  deployment_type: string;
  db_route: string;
  status: string;
}

const Organizations = () => {
  const navigate = useNavigate();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [provisioning, setProvisioning] = useState(false);
  
  // Form State
  const [formData, setFormData] = useState({
    name: '',
    deployment_type: 'SaaS',
    db_route: 'shared-cluster-01',
    admin_name: '',
    admin_email: '',
    admin_password: ''
  });

  const fetchOrgs = () => {
    setLoading(true);
    api.get('/admin/organizations')
      .then(res => setOrgs(res.data))
      .catch(err => console.error("Failed to fetch organizations", err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchOrgs();
  }, []);

  const handleProvision = (e: React.FormEvent) => {
    e.preventDefault();
    setProvisioning(true);
    api.post('/admin/organizations/provision', formData)
      .then(() => {
        setIsModalOpen(false);
        setFormData({
          name: '', deployment_type: 'SaaS', db_route: 'shared-cluster-01',
          admin_name: '', admin_email: '', admin_password: ''
        });
        fetchOrgs();
      })
      .catch(err => {
        console.error("Provisioning failed", err);
        alert(err.response?.data?.detail || "Provisioning failed");
      })
      .finally(() => setProvisioning(false));
  };

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1200px' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 'var(--space-6)' }}>
        <div>
          <h1>Organizations</h1>
          <p className="subtitle">Manage all construction ERP tenants.</p>
        </div>
        <button className="btn-primary" onClick={() => setIsModalOpen(true)}>
          <Plus size={16} /> Add Tenant
        </button>
      </header>
      
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Deployment</th>
              <th>Database Route</th>
              <th>Status</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} style={{textAlign: 'center', color: 'var(--neutral-500)'}}>Loading live data...</td></tr>
            ) : orgs.map(org => (
              <tr key={org.id}>
                <td style={{ fontWeight: 500, color: 'var(--neutral-900)' }}>{org.name}</td>
                <td>
                  <span className={`badge ${org.deployment_type === 'SaaS' ? 'badge-info' : 'badge-warning'}`}>
                    {org.deployment_type === 'SaaS' ? <Cloud size={12} style={{ marginRight: 4 }} /> : <Server size={12} style={{ marginRight: 4 }} />}
                    {org.deployment_type}
                  </span>
                </td>
                <td style={{ fontFamily: 'monospace', fontSize: '13px', color: 'var(--neutral-500)' }}>{org.db_route}</td>
                <td>
                  <span
                    className={`badge ${(org.status || '').toLowerCase() === 'active' ? 'badge-success' : 'badge-warning'}`}
                    style={{ textTransform: 'capitalize' }}
                  >
                    {org.status}
                  </span>
                </td>
                <td style={{ textAlign: 'right' }}>
                  <button
                    style={{ background: 'none', border: 'none', color: 'var(--neutral-600)', fontWeight: 500, cursor: 'pointer', fontSize: '13px' }}
                    onClick={() => navigate(`/organizations/${org.id}`)}
                  >
                    Manage
                  </button>
                </td>
              </tr>
            ))}
            {!loading && orgs.length === 0 && (
              <tr><td colSpan={5} style={{textAlign: 'center', color: 'var(--neutral-500)'}}>No organizations found. Click "Add Tenant" to create one.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {isModalOpen && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h2 style={{ marginBottom: 'var(--space-6)' }}>Provision New Tenant</h2>
            <form onSubmit={handleProvision}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
                <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                  <label>Company Name</label>
                  <input required type="text" className="form-input" placeholder="e.g. Acme Construction" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} />
                </div>
                <div className="form-group">
                  <label>Deployment Type</label>
                  <select className="form-input" value={formData.deployment_type} onChange={e => setFormData({...formData, deployment_type: e.target.value})}>
                    <option value="SaaS">SaaS (Shared)</option>
                    <option value="On-Prem">On-Premise (Dedicated)</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>Database Route</label>
                  <input required type="text" className="form-input" value={formData.db_route} onChange={e => setFormData({...formData, db_route: e.target.value})} />
                </div>
              </div>
              
              <h3 style={{ fontSize: '16px', fontWeight: 600, marginTop: 'var(--space-6)', marginBottom: 'var(--space-4)', color: 'var(--neutral-900)' }}>Initial Admin User</h3>
              <div className="form-group">
                <label>Admin Full Name</label>
                <input required type="text" className="form-input" placeholder="John Doe" value={formData.admin_name} onChange={e => setFormData({...formData, admin_name: e.target.value})} />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
                <div className="form-group">
                  <label>Admin Email</label>
                  <input required type="email" className="form-input" placeholder="john@acme.com" value={formData.admin_email} onChange={e => setFormData({...formData, admin_email: e.target.value})} />
                </div>
                <div className="form-group">
                  <label>Admin Password</label>
                  <input required type="password" className="form-input" placeholder="Temporary password" value={formData.admin_password} onChange={e => setFormData({...formData, admin_password: e.target.value})} />
                </div>
              </div>

              <div className="modal-actions">
                <button type="button" className="btn-secondary" onClick={() => setIsModalOpen(false)}>Cancel</button>
                <button type="submit" className="btn-primary" disabled={provisioning}>
                  {provisioning ? 'Provisioning...' : 'Provision Tenant'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

function AppLayout() {
  return (
    <RequireAuth>
      <div className="app-container">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/organizations" element={<Organizations />} />
            <Route path="/organizations/:id" element={<OrganizationDetail />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/providers" element={<Providers />} />
            <Route path="/sync-health" element={<SyncHealth />} />
            <Route path="/perf" element={<Perf />} />
            <Route path="/queue-health" element={<QueueHealth />} />
            <Route path="/system-graph" element={<SystemGraph />} />
            <Route path="/semantic-types" element={<SemanticTypes />} />
            <Route path="/workflows" element={<Workflows />} />
            <Route path="/test-message" element={<TestMessage />} />
            <Route path="/users" element={<PlatformUsers />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Dashboard />} />
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

