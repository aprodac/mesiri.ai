import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams, Link } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, CheckCircle, Cloud, Pencil, Plus, Server, Sparkles, Trash2, X } from 'lucide-react';
import { api } from './api';
import UserAccessEditor, { type OrgProject } from './UserAccessEditor';
import AddUserDialog from './AddUserDialog';
import PlanCard from './PlanCard';
import BrandingPanel from './BrandingPanel';
import { useToast, getErrorMessage } from './Toast';
import CompanyDetailsDialog from './CompanyDetailsDialog';

interface Organization {
  id: string;
  name: string;
  deployment_type: string;
  db_route: string;
  status: string;
  created_at: string;
}

interface ProjectAccessGrant {
  project_id: string;
  project_name: string;
  site_access: string;
}

interface OrgUser {
  id: string;
  email: string | null;
  full_name: string | null;
  role: string | null;
  status?: string;
  whatsapp_number: string | null;
  access_mode: string;
  project_access: ProjectAccessGrant[];
}

interface TimelineEntry {
  id: string;
  project_id: string | null;
  site_id: string | null;
  event_type: string;
  summary: string;
  occurred_at: string;
}

interface SettingSpec {
  key: string;
  description: string;
  default: unknown;
}

interface ModuleSpec {
  key: string;
  label: string;
  description: string;
  always_on: boolean;
  in_v1: boolean;
}

interface OrgSettingsPayload {
  settings: Record<string, unknown>;
  specs: SettingSpec[];
  valid_roles: string[];
  // Absent from a backend older than SA-07; the Modules card is then hidden.
  modules?: ModuleSpec[];
}

const ENABLED_MODULES_KEY = 'enabled_modules';

// Keys the settings tab renders as a role checkbox group. Anything else the
// backend reports in `specs` is shown read-only rather than guessed at, so a
// new setting shipped server-side can't silently render as the wrong control.
const ROLE_LIST_SETTINGS = new Set(['whatsapp_material_create_roles']);

const ROLE_LABELS: Record<string, string> = {
  ADMIN: 'Admin',
  PROJECT_MANAGER: 'Project manager',
  SITE_ENGINEER: 'Site engineer',
  FINANCE: 'Finance',
};

type Tab = 'users' | 'activity' | 'settings' | 'letterhead';

const statusBadgeClass = (status: string) =>
  (status || '').toLowerCase() === 'active' ? 'badge-success' : 'badge-warning';

export default function OrganizationDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();

  const [org, setOrg] = useState<Organization | null>(null);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  // ?tab=letterhead opens the Letterhead tab (from Branding requests, SA-09).
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>(searchParams.get('tab') === 'letterhead' ? 'letterhead' : 'users');
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projects, setProjects] = useState<OrgProject[]>([]);
  const [editingUser, setEditingUser] = useState<OrgUser | null>(null);
  const [editingDetails, setEditingDetails] = useState(false);
  const [addingUser, setAddingUser] = useState(false);
  const [orgSettings, setOrgSettings] = useState<OrgSettingsPayload | null>(null);
  // The plan card's effective status (SS-10); stable, so it doesn't reload the card.
  const showStatus = useCallback((status: string) => {
    setOrg((prev) => (prev ? { ...prev, status } : prev));
  }, []);
  const [savingSetting, setSavingSetting] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const [showSeedModal, setShowSeedModal] = useState(false);
  const [includeDemoTx, setIncludeDemoTx] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [seedResult, setSeedResult] = useState<string | null>(null);

  const handleSeedFinance = async () => {
    if (!id) return;
    setSeeding(true);
    setError(null);
    setSeedResult(null);

    try {
      const res = await api.post<{
        categories_created: number;
        accounts_created: number;
        vendors_created: number;
        settings_created: number;
        expenses_created: number;
        transactions_created: number;
      }>(`/admin/organizations/${id}/seed-finance`, {
        include_demo_transactions: includeDemoTx,
      });

      const successMsg = `Finance data seeded successfully! Created ${res.data.accounts_created} accounts, ${res.data.categories_created} categories, ${res.data.vendors_created} vendors, ${res.data.settings_created} settings, ${res.data.expenses_created} expenses, and ${res.data.transactions_created} transactions.`;
      setSeedResult(successMsg);
      showToast(successMsg, 'success');
      setShowSeedModal(false);
    } catch (err: unknown) {
      const msg = getErrorMessage(err, 'Failed to seed finance data');
      setError(msg);
      showToast(msg, 'error');
    } finally {
      setSeeding(false);
    }
  };

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    // Only the organization itself is load-bearing: without it there is no
    // page. Everything else is a tab's worth of content, so each is fetched
    // independently and degrades to empty on failure.
    //
    // This used to be one Promise.all over all five calls, which meant a
    // single 404 (a settings endpoint that had been added to a router the
    // app never registers) rejected the whole chain and rendered
    // "Not Found" in place of the entire organization.
    const optional = <T,>(p: Promise<{ data: T }>, fallback: T): Promise<T> =>
      p.then((r) => r.data).catch(() => fallback);

    Promise.all([
      api.get<Organization>(`/admin/organizations/${id}`),
      optional(api.get<OrgUser[]>(`/admin/organizations/${id}/users`), []),
      optional(
        api.get<{ items: TimelineEntry[]; total: number }>(
          `/admin/organizations/${id}/timeline`
        ),
        { items: [], total: 0 }
      ),
      optional<OrgSettingsPayload | null>(
        api.get<OrgSettingsPayload>(`/admin/organizations/${id}/settings`),
        null
      ),
      optional(api.get<OrgProject[]>(`/admin/organizations/${id}/projects`), []),
    ])
      .then(([orgRes, usersData, timelineData, settingsData, projectsData]) => {
        setOrg(orgRes.data);
        setUsers(usersData);
        setTimeline(timelineData.items);
        setOrgSettings(settingsData);
        setProjects(projectsData);
      })
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load organization'))
      .finally(() => setLoading(false));
  }, [id]);

  const executeDelete = () => {
    if (!org) return;
    setDeleting(true);
    setError(null);
    api
      .delete(`/admin/organizations/${org.id}`)
      .then(() => navigate('/organizations'))
      .catch((err) => {
        setError(err.response?.data?.detail || 'Failed to delete organization');
        setDeleting(false);
        setShowDeleteModal(false);
      });
  };

  const handleToggleSettingRole = (key: string, role: string, checked: boolean) => {
    if (!id || !orgSettings) return;
    const current = Array.isArray(orgSettings.settings[key])
      ? (orgSettings.settings[key] as string[])
      : [];
    const next = checked ? [...current, role] : current.filter((r) => r !== role);

    // Optimistic: the checkbox reflects the click immediately, and the catch
    // below puts the old value back if the save is rejected -- a permission
    // toggle that appears to have saved but hasn't is worse than a slow one.
    setOrgSettings({ ...orgSettings, settings: { ...orgSettings.settings, [key]: next } });
    setSavingSetting(key);
    setSettingsError(null);
    api
      .put(`/admin/organizations/${id}/settings`, { key, value: next })
      .catch((err) => {
        setSettingsError(err.response?.data?.detail || 'Failed to save setting');
        setOrgSettings((prev) =>
          prev ? { ...prev, settings: { ...prev.settings, [key]: current } } : prev
        );
      })
      .finally(() => setSavingSetting(null));
  };

  const handleToggleModule = (moduleKey: string, enabled: boolean) => {
    if (!id || !orgSettings) return;
    const stored = orgSettings.settings[ENABLED_MODULES_KEY];
    const current = Array.isArray(stored) ? (stored as string[]) : [];
    const next = enabled
      ? [...current, moduleKey]
      : current.filter((m) => m !== moduleKey);

    // Same optimistic save-and-revert as the role checkboxes above. The
    // backend returns the canonical list (catalogue order, always-on modules
    // included), so the switch state is replaced with what was actually saved.
    setOrgSettings({
      ...orgSettings,
      settings: { ...orgSettings.settings, [ENABLED_MODULES_KEY]: next },
    });
    setSavingSetting(ENABLED_MODULES_KEY);
    setSettingsError(null);
    api
      .put<{ key: string; value: string[] }>(`/admin/organizations/${id}/settings`, {
        key: ENABLED_MODULES_KEY,
        value: next,
      })
      .then((res) =>
        setOrgSettings((prev) =>
          prev
            ? { ...prev, settings: { ...prev.settings, [ENABLED_MODULES_KEY]: res.data.value } }
            : prev
        )
      )
      .catch((err) => {
        setSettingsError(err.response?.data?.detail || 'Failed to save modules');
        setOrgSettings((prev) =>
          prev
            ? { ...prev, settings: { ...prev.settings, [ENABLED_MODULES_KEY]: current } }
            : prev
        );
      })
      .finally(() => setSavingSetting(null));
  };

  const handleUpdateUserStatus = (user: OrgUser, newStatus: string) => {
    if (!id) return;
    setUpdatingUserId(user.id);
    setError(null);
    api
      .patch<OrgUser>(`/admin/organizations/${id}/users/${user.id}/status`, { status: newStatus })
      .then((res) => {
        setUsers((prev) =>
          prev.map((u) => (u.id === user.id ? { ...u, status: res.data.status || newStatus } : u))
        );
      })
      .catch((err) => setError(err.response?.data?.detail || 'Failed to update user status'))
      .finally(() => setUpdatingUserId(null));
  };

  const handleForceDeleteUser = (user: OrgUser) => {
    if (!id) return;
    const confirmed = window.confirm(
      `FORCE DELETE "${user.full_name || user.email || user.id}"?\n\nThis will unbind user ownership on historical records and PERMANENTLY delete the account. This cannot be undone.`
    );
    if (!confirmed) return;

    setDeletingUserId(user.id);
    setError(null);
    api
      .delete(`/admin/organizations/${id}/users/${user.id}?force=true`)
      .then(() => setUsers((prev) => prev.filter((u) => u.id !== user.id)))
      .catch((err) => setError(err.response?.data?.detail || 'Failed to force delete user'))
      .finally(() => setDeletingUserId(null));
  };

  const handleDeleteUser = (user: OrgUser) => {
    if (!id) return;
    const confirmed = window.confirm(
      `Remove ${user.full_name || user.email || user.id} from this organization?`
    );
    if (!confirmed) return;

    setDeletingUserId(user.id);
    setError(null);
    api
      .delete(`/admin/organizations/${id}/users/${user.id}`)
      .then(() => setUsers((prev) => prev.filter((u) => u.id !== user.id)))
      .catch((err) => {
        if (err.response?.status === 409) {
          const detail = err.response?.data?.detail || 'User owns historical records.';
          const choice = window.confirm(
            `${detail}\n\nClick OK to DEACTIVATE account (recommended).\nClick CANCEL to choice Force Delete.`
          );
          if (choice) {
            handleUpdateUserStatus(user, 'Inactive');
          } else {
            handleForceDeleteUser(user);
          }
          return;
        }
        setError(err.response?.data?.detail || 'Failed to remove user');
      })
      .finally(() => setDeletingUserId(null));
  };

  if (loading) {
    return <div className="animate-fade-in" style={{ maxWidth: '1200px', color: 'var(--neutral-500)' }}>Loading…</div>;
  }

  if (error && !org) {
    return (
      <div className="animate-fade-in" style={{ maxWidth: '1200px' }}>
        <Link to="/organizations" className="btn-secondary" style={{ display: 'inline-flex', marginBottom: 'var(--space-6)' }}>
          <ArrowLeft size={16} /> Back to Companies
        </Link>
        <p style={{ color: 'var(--error)' }}>{error}</p>
      </div>
    );
  }

  if (!org) return null;

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1200px' }}>
      <Link to="/organizations" className="btn-secondary" style={{ display: 'inline-flex', marginBottom: 'var(--space-6)' }}>
        <ArrowLeft size={16} /> Back to Companies
      </Link>

      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 'var(--space-6)' }}>
        <div>
          <h1>{org.name}</h1>
          <p className="subtitle">
            <span className={`badge ${org.deployment_type === 'SaaS' ? 'badge-info' : 'badge-warning'}`} style={{ marginRight: 8 }}>
              {org.deployment_type === 'SaaS' ? <Cloud size={12} style={{ marginRight: 4 }} /> : <Server size={12} style={{ marginRight: 4 }} />}
              {org.deployment_type}
            </span>
            <span className={`badge ${statusBadgeClass(org.status)}`} style={{ textTransform: 'capitalize' }}>
              {org.status}
            </span>
          </p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
          <button className="btn-secondary" onClick={() => setEditingDetails(true)}>
            <Pencil size={16} /> Edit details
          </button>
          <button
            className="btn-secondary"
            style={{ color: '#2563EB', borderColor: '#93C5FD' }}
            onClick={() => setShowSeedModal(true)}
            disabled={seeding}
          >
            <Sparkles size={16} /> {seeding ? 'Seeding…' : 'Seed Finance Data'}
          </button>
          <button
            className="btn-secondary"
            style={{ color: 'var(--error)', borderColor: 'var(--error)' }}
            onClick={() => setShowDeleteModal(true)}
            disabled={deleting}
          >
            <Trash2 size={16} /> Delete Tenant
          </button>
        </div>
      </header>

      {seedResult && (
        <div style={{ padding: 'var(--space-3)', background: '#F0FDF4', border: '1px solid #86EFAC', borderRadius: 'var(--radius-md)', color: '#166534', marginBottom: 'var(--space-4)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <CheckCircle size={18} />
          <span>{seedResult}</span>
        </div>
      )}

      {error && <p style={{ color: 'var(--error)', marginBottom: 'var(--space-4)' }}>{error}</p>}

      <PlanCard orgId={org.id} onStatus={showStatus} />

      <div className="card" style={{ marginBottom: 'var(--space-6)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(200px, 100%), 1fr))', gap: 'var(--space-4)' }}>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Database Route</div>
            <div style={{ fontFamily: 'monospace', fontSize: '13px' }}>{org.db_route}</div>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Created</div>
            <div style={{ fontSize: '13px' }}>{new Date(org.created_at).toLocaleString()}</div>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Users</div>
            <div style={{ fontSize: '13px' }}>{users.length}</div>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>WhatsApp messages</div>
            <Link to={`/logs?org=${org.id}`} style={{ fontSize: '13px' }}>View messages →</Link>
          </div>
        </div>
      </div>

      <nav style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-4)', borderBottom: '1px solid var(--border-strong)' }}>
        {(['users', 'activity', 'settings', 'letterhead'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: 'none',
              border: 'none',
              borderBottom: tab === t ? '2px solid var(--primary)' : '2px solid transparent',
              padding: 'var(--space-3) var(--space-2)',
              fontWeight: 500,
              fontSize: '14px',
              color: tab === t ? 'var(--neutral-900)' : 'var(--neutral-500)',
              cursor: 'pointer',
            }}
          >
            {t === 'users' ? 'Users & Roles' : t === 'activity' ? 'Activity' : t === 'settings' ? 'Settings' : 'Letterhead'}
          </button>
        ))}
      </nav>

      {tab === 'users' && (
        <>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 'var(--space-3)' }}>
          <button className="btn-secondary" onClick={() => setAddingUser(true)}>
            <Plus size={16} /> Add user
          </button>
        </div>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th>WhatsApp</th>
                <th>Project &amp; Site Access</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 ? (
                <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>No users in this organization.</td></tr>
              ) : (
                users.map((u) => {
                  const isInactive = (u.status || 'active').toLowerCase() === 'inactive';
                  return (
                    <tr key={u.id}>
                      <td style={{ fontWeight: 500, color: 'var(--neutral-900)' }}>{u.full_name || '—'}</td>
                      <td>{u.email || '—'}</td>
                      <td style={{ textTransform: 'capitalize' }}>{(u.role || '').toLowerCase()}</td>
                      <td>
                        <span
                          className={`badge ${statusBadgeClass(u.status || 'active')}`}
                          style={{ textTransform: 'capitalize' }}
                        >
                          {u.status || 'active'}
                        </span>
                      </td>
                      <td style={{ fontSize: '13px', color: 'var(--neutral-500)' }}>{u.whatsapp_number || 'Not mapped'}</td>
                      <td style={{ fontSize: '13px' }}>
                        {u.access_mode === 'all_projects' ? (
                          <span className="badge badge-info">All Projects</span>
                        ) : u.project_access.length === 0 ? (
                          <span style={{ color: 'var(--neutral-500)' }}>No projects assigned</span>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                            {u.project_access.map((grant) => (
                              <div key={grant.project_id}>
                                <span style={{ fontWeight: 500 }}>{grant.project_name}</span>
                                <span style={{ color: 'var(--neutral-500)' }}> — {grant.site_access}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--primary)',
                            fontWeight: 500,
                            cursor: 'pointer',
                            fontSize: '13px',
                            marginRight: '12px',
                          }}
                          onClick={() => setEditingUser(u)}
                        >
                          Edit access
                        </button>
                        <button
                          style={{
                            background: 'none',
                            border: 'none',
                            color: isInactive ? 'var(--primary)' : 'var(--neutral-600)',
                            fontWeight: 500,
                            cursor: 'pointer',
                            fontSize: '13px',
                            marginRight: '12px',
                          }}
                          onClick={() => handleUpdateUserStatus(u, isInactive ? 'active' : 'inactive')}
                          disabled={updatingUserId === u.id}
                        >
                          {updatingUserId === u.id ? 'Updating…' : isInactive ? 'Reactivate' : 'Deactivate'}
                        </button>
                        <button
                          style={{ background: 'none', border: 'none', color: 'var(--error)', fontWeight: 500, cursor: 'pointer', fontSize: '13px', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                          onClick={() => handleDeleteUser(u)}
                          disabled={deletingUserId === u.id}
                        >
                          <X size={13} /> {deletingUserId === u.id ? 'Removing…' : 'Remove'}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        </>
      )}

      {tab === 'activity' && (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Event</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {timeline.length === 0 ? (
                <tr><td colSpan={3} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>No activity recorded yet.</td></tr>
              ) : (
                timeline.map((entry) => (
                  <tr key={entry.id}>
                    <td style={{ fontSize: '13px', color: 'var(--neutral-500)', whiteSpace: 'nowrap' }}>
                      {new Date(entry.occurred_at).toLocaleString()}
                    </td>
                    <td><span className="badge badge-info">{entry.event_type}</span></td>
                    <td>{entry.summary}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'letterhead' && <BrandingPanel orgId={org.id} />}

      {tab === 'settings' && (
        <div>
          {settingsError && (
            <div className="badge badge-warning" style={{ display: 'block', marginBottom: 'var(--space-3)' }}>
              {settingsError}
            </div>
          )}
          {orgSettings?.modules && orgSettings.modules.length > 0 && (
            <section
              aria-labelledby="modules-heading"
              style={{
                border: '1px solid var(--border-strong)',
                borderRadius: 'var(--radius)',
                padding: 'var(--space-4)',
                marginBottom: 'var(--space-4)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'baseline',
                  gap: 'var(--space-3)',
                  flexWrap: 'wrap',
                  marginBottom: '4px',
                }}
              >
                <h3 id="modules-heading" style={{ margin: 0, fontSize: '15px', fontWeight: 600 }}>
                  Modules
                </h3>
                <span style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>
                  Changes apply immediately
                </span>
              </div>
              <p
                style={{
                  margin: '0 0 var(--space-3)',
                  fontSize: '13px',
                  color: 'var(--neutral-500)',
                }}
              >
                What this company can use. A switched-off module's dashboard pages and WhatsApp
                flows stop working for this company.
              </p>
              {orgSettings.modules.map((mod) => {
                const stored = orgSettings.settings[ENABLED_MODULES_KEY];
                const enabledList = Array.isArray(stored) ? (stored as string[]) : [];
                const isOn = mod.always_on || enabledList.includes(mod.key);
                const busy = savingSetting === ENABLED_MODULES_KEY;
                const inputId = `module-${mod.key}`;
                return (
                  <div
                    key={mod.key}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 'var(--space-3)',
                      padding: '10px 0',
                      borderTop: '1px solid var(--neutral-200)',
                    }}
                  >
                    <input
                      id={inputId}
                      type="checkbox"
                      role="switch"
                      aria-checked={isOn}
                      checked={isOn}
                      disabled={mod.always_on || busy}
                      onChange={(e) => handleToggleModule(mod.key, e.target.checked)}
                      style={{
                        width: '18px',
                        height: '18px',
                        cursor: mod.always_on ? 'not-allowed' : busy ? 'wait' : 'pointer',
                        accentColor: 'var(--primary)',
                      }}
                    />
                    <label htmlFor={inputId} style={{ flex: 1, minWidth: 0, cursor: 'inherit' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '14px', fontWeight: 500 }}>{mod.label}</span>
                        {mod.always_on && <span className="badge badge-info">Always on</span>}
                        {mod.in_v1 && !mod.always_on && (
                          <span className="badge badge-success">V1</span>
                        )}
                      </span>
                      <span
                        style={{ display: 'block', fontSize: '13px', color: 'var(--neutral-500)' }}
                      >
                        {mod.description}
                      </span>
                    </label>
                    <span
                      style={{
                        fontSize: '12px',
                        fontWeight: 600,
                        color: isOn ? 'var(--success)' : 'var(--neutral-500)',
                        minWidth: '28px',
                        textAlign: 'right',
                      }}
                    >
                      {isOn ? 'On' : 'Off'}
                    </span>
                  </div>
                );
              })}
            </section>
          )}

          {!orgSettings || orgSettings.specs.length === 0 ? (
            <p style={{ color: 'var(--neutral-500)', fontSize: '14px' }}>
              No configurable settings for this organization.
            </p>
          ) : (
            orgSettings.specs
              .filter((spec) => !(orgSettings.modules && spec.key === ENABLED_MODULES_KEY))
              .map((spec) => {
              const value = orgSettings.settings[spec.key];
              const selected = Array.isArray(value) ? (value as string[]) : [];
              return (
                <div
                  key={spec.key}
                  style={{
                    border: '1px solid var(--border-strong)',
                    borderRadius: 'var(--radius)',
                    padding: 'var(--space-4)',
                    marginBottom: 'var(--space-3)',
                  }}
                >
                  <div style={{ fontSize: '14px', fontWeight: 500, marginBottom: '4px' }}>
                    {spec.key === 'whatsapp_material_create_roles'
                      ? 'Add materials from WhatsApp'
                      : spec.key}
                  </div>
                  <div
                    style={{
                      fontSize: '13px',
                      color: 'var(--neutral-500)',
                      marginBottom: 'var(--space-3)',
                    }}
                  >
                    {spec.description}
                  </div>

                  {ROLE_LIST_SETTINGS.has(spec.key) ? (
                    <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
                      {orgSettings.valid_roles.map((role) => (
                        <label
                          key={role}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            fontSize: '13px',
                            cursor: savingSetting === spec.key ? 'wait' : 'pointer',
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={selected.includes(role)}
                            disabled={savingSetting === spec.key}
                            onChange={(e) =>
                              handleToggleSettingRole(spec.key, role, e.target.checked)
                            }
                          />
                          {ROLE_LABELS[role] || role}
                        </label>
                      ))}
                    </div>
                  ) : (
                    <code style={{ fontSize: '12px' }}>{JSON.stringify(value)}</code>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}

      {addingUser && id && org && (
        <AddUserDialog
          orgId={id}
          orgName={org.name}
          onClose={() => setAddingUser(false)}
          onCreated={() => {
            api
              .get<OrgUser[]>(`/admin/organizations/${id}/users`)
              .then((res) => setUsers(res.data))
              .catch(() => setError('User added, but the list could not be refreshed.'));
          }}
        />
      )}

      {editingDetails && (
        <CompanyDetailsDialog
          orgId={org.id}
          onClose={() => setEditingDetails(false)}
          onSaved={(details) => {
            setOrg((prev) => (prev ? { ...prev, name: details.name } : prev));
            setEditingDetails(false);
          }}
        />
      )}
      {editingUser && id && (
        <UserAccessEditor
          orgId={id}
          user={editingUser}
          projects={projects}
          onClose={() => setEditingUser(null)}
          onSaved={() => {
            // Re-read rather than patching local state: the server applies
            // the org-wide role bypass, so what it returns can differ from
            // what was submitted (an admin always comes back "All Projects").
            api
              .get<OrgUser[]>(`/admin/organizations/${id}/users`)
              .then((res) => setUsers(res.data))
              .catch(() => setError('Saved, but the list could not be refreshed.'));
          }}
        />
      )}

      {showDeleteModal && (
        <DeleteOrgModal
          orgName={org.name}
          isOpen={showDeleteModal}
          deleting={deleting}
          onClose={() => setShowDeleteModal(false)}
          onConfirm={executeDelete}
        />
      )}

      {showSeedModal && (
        <SeedFinanceModal
          orgName={org.name}
          isOpen={showSeedModal}
          seeding={seeding}
          includeDemoTx={includeDemoTx}
          setIncludeDemoTx={setIncludeDemoTx}
          onClose={() => setShowSeedModal(false)}
          onConfirm={handleSeedFinance}
        />
      )}
    </div>
  );
}

interface DeleteOrgModalProps {
  orgName: string;
  isOpen: boolean;
  deleting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

function DeleteOrgModal({ orgName, isOpen, deleting, onClose, onConfirm }: DeleteOrgModalProps) {
  const [typedName, setTypedName] = useState('');

  if (!isOpen) return null;

  const isConfirmed = typedName.trim() === orgName.trim();

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(14, 17, 22, 0.65)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '16px',
      }}
      onClick={onClose}
    >
      <div
        className="animate-fade-in"
        style={{
          background: 'var(--surface-primary, #FFFFFF)',
          border: '1px solid var(--border-default, #E5E7EB)',
          borderRadius: 'var(--radius-md, 12px)',
          padding: '24px',
          maxWidth: '480px',
          width: '100%',
          boxShadow: 'var(--shadow-overlay, 0 20px 48px rgba(16,24,40,0.18))',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', marginBottom: '16px' }}>
          <div
            style={{
              padding: '10px',
              borderRadius: '50%',
              background: 'var(--error-soft, #FEE2E2)',
              color: 'var(--error, #EF4444)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <AlertTriangle size={22} />
          </div>
          <div>
            <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 600, color: 'var(--neutral-900)' }}>
              Delete Tenant Organization?
            </h3>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--neutral-500)' }}>
              This action <strong style={{ color: 'var(--error)' }}>cannot be undone</strong>.
            </p>
          </div>
        </div>

        <div
          style={{
            background: 'var(--surface-secondary, #F3F4F6)',
            borderRadius: '8px',
            padding: '12px 14px',
            marginBottom: '16px',
            fontSize: '13px',
            color: 'var(--neutral-700)',
            lineHeight: 1.5,
          }}
        >
          Deleting <strong>"{orgName}"</strong> will permanently purge:
          <ul style={{ margin: '6px 0 0 18px', padding: 0 }}>
            <li>All user accounts, roles & access policies</li>
            <li>All projects, job sites & assigned memberships</li>
            <li>All money accounts, expenses & transaction ledgers</li>
            <li>All material catalogues, receipts & movement logs</li>
            <li>All timeline activity & message logs</li>
          </ul>
        </div>

        <div style={{ marginBottom: '20px' }}>
          <label
            htmlFor="confirm-org-name"
            style={{ display: 'block', fontSize: '13px', fontWeight: 500, marginBottom: '6px', color: 'var(--neutral-700)' }}
          >
            Type <code style={{ background: '#E5E7EB', padding: '2px 6px', borderRadius: '4px' }}>{orgName}</code> to confirm:
          </label>
          <input
            id="confirm-org-name"
            type="text"
            className="form-input"
            style={{ width: '100%', boxSizing: 'border-box' }}
            placeholder={orgName}
            value={typedName}
            onChange={(e) => setTypedName(e.target.value)}
            disabled={deleting}
            autoFocus
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={onClose}
            disabled={deleting}
          >
            Cancel
          </button>
          <button
            type="button"
            style={{
              background: isConfirmed ? 'var(--error)' : 'var(--neutral-300)',
              color: 'var(--white)',
              border: 'none',
              borderRadius: 'var(--radius-sm, 8px)',
              padding: '8px 16px',
              fontWeight: 500,
              fontSize: '14px',
              cursor: isConfirmed && !deleting ? 'pointer' : 'not-allowed',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
            }}
            onClick={onConfirm}
            disabled={!isConfirmed || deleting}
          >
            <Trash2 size={15} /> {deleting ? 'Deleting…' : 'Permanently Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}

function SeedFinanceModal({
  orgName,
  isOpen,
  seeding,
  includeDemoTx,
  setIncludeDemoTx,
  onClose,
  onConfirm,
}: {
  orgName: string;
  isOpen: boolean;
  seeding: boolean;
  includeDemoTx: boolean;
  setIncludeDemoTx: (val: boolean) => void;
  onClose: () => void;
  onConfirm: () => void;
}) {
  if (!isOpen) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        style={{
          background: 'var(--white, #fff)',
          borderRadius: 'var(--radius-lg, 12px)',
          padding: '24px',
          maxWidth: '500px',
          width: '90%',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Sparkles size={20} style={{ color: '#2563EB' }} /> Seed Finance Data
          </h2>
          <button
            type="button"
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--neutral-400)' }}
            disabled={seeding}
          >
            <X size={20} />
          </button>
        </div>

        <p style={{ fontSize: '14px', color: 'var(--neutral-600)', marginBottom: '16px', lineHeight: 1.5 }}>
          This will populate starter money accounts, expense categories, vendors, and finance settings for <strong>{orgName}</strong>.
        </p>

        <div style={{ background: '#F3F4F6', padding: '12px 16px', borderRadius: '8px', marginBottom: '20px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '14px', cursor: 'pointer', fontWeight: 500 }}>
            <input
              type="checkbox"
              checked={includeDemoTx}
              onChange={(e) => setIncludeDemoTx(e.target.checked)}
              disabled={seeding}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
            <span>Include Sample Past Expenses & Ledger Transactions</span>
          </label>
          <p style={{ margin: '4px 0 0 26px', fontSize: '12px', color: 'var(--neutral-500)' }}>
            Adds realistic historical payments, petty cash disbursements, and vendor bills for instant visual testing in the Web Dashboard.
          </p>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button type="button" className="btn-secondary" onClick={onClose} disabled={seeding}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
            onClick={onConfirm}
            disabled={seeding}
          >
            <Sparkles size={15} /> {seeding ? 'Seeding Data…' : 'Seed Finance Data'}
          </button>
        </div>
      </div>
    </div>
  );
}
