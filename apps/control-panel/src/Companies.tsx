import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Check, Circle } from 'lucide-react';
import { api } from './api';
import CreateCompany from './CreateCompany';

// SA-02: every company with its real status (a trial past its end reads
// expired) and how far it got with setup, so stuck trials stand out. The
// numbers come from GET /admin/organizations (companies_overview.py).

interface Setup {
  has_team: boolean;
  has_site: boolean;
  first_update_at: string | null;
  first_dpr_sent_at: string | null;
}

interface Company {
  id: string;
  name: string;
  effective_status: string;
  trial_days_left: number | null;
  trial_ends_at: string | null;
  signup_source: string;
  created_at: string | null;
  setup: Setup;
}

const FILTERS = ['all', 'trial', 'active', 'expired', 'suspended'] as const;
type Filter = (typeof FILTERS)[number];

const FILTER_LABELS: Record<Filter, string> = {
  all: 'All',
  trial: 'Trial',
  active: 'Active',
  expired: 'Expired',
  suspended: 'Suspended',
};

const SOURCE_LABELS: Record<string, string> = {
  superadmin: 'Superadmin',
  whatsapp: 'WhatsApp',
  web: 'Web',
  api: 'API',
};

const STATUS_BADGE: Record<string, string> = {
  trial: 'badge-info',
  active: 'badge-success',
  expired: 'badge-warning',
  suspended: 'badge-error',
};

function shortDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

function statusText(c: Company): string {
  if (c.effective_status === 'trial') {
    if (c.trial_days_left === null) return 'Trial';
    if (c.trial_days_left <= 1) return 'Trial · last day';
    return `Trial · ${c.trial_days_left} days left`;
  }
  return FILTER_LABELS[c.effective_status as Filter] ?? c.effective_status;
}

function Step({ label, done, title }: { label: string; done: boolean; title: string }) {
  return (
    <span
      title={title}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 3,
        fontSize: '12px',
        marginRight: 'var(--space-3)',
        color: done ? 'var(--success)' : 'var(--neutral-400)',
      }}
    >
      {done ? <Check size={13} /> : <Circle size={11} />}
      {label}
    </span>
  );
}

function SetupSteps({ setup }: { setup: Setup }) {
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <Step label="Team" done={setup.has_team} title={setup.has_team ? 'Has people besides the owner' : 'Only the owner so far'} />
      <Step label="Site" done={setup.has_site} title={setup.has_site ? 'Has a site' : 'No site yet'} />
      <Step
        label="Update"
        done={!!setup.first_update_at}
        title={setup.first_update_at ? `First update ${shortDate(setup.first_update_at)}` : 'No site update yet'}
      />
      <Step
        label="DPR"
        done={!!setup.first_dpr_sent_at}
        title={setup.first_dpr_sent_at ? `First DPR sent ${shortDate(setup.first_dpr_sent_at)}` : 'No DPR sent yet'}
      />
    </span>
  );
}

export default function Companies() {
  const navigate = useNavigate();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    api
      .get<Company[]>('/admin/organizations')
      .then((res) => {
        setCompanies(res.data);
        setError(null);
      })
      .catch(() => setError('Could not load companies.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const count = (f: Filter) =>
    f === 'all' ? companies.length : companies.filter((c) => c.effective_status === f).length;
  const shown = filter === 'all' ? companies : companies.filter((c) => c.effective_status === filter);

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1200px' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 'var(--space-6)' }}>
        <div>
          <h1>Companies</h1>
          <p className="subtitle">Every company on Mesiri, its status and how far it got with setup.</p>
        </div>
        <button className="btn-primary" onClick={() => setCreating(true)}>
          <Plus size={16} /> Create company
        </button>
      </header>

      <div role="tablist" style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-4)', flexWrap: 'wrap' }}>
        {FILTERS.map((f) => (
          <button
            key={f}
            role="tab"
            aria-selected={filter === f}
            className={filter === f ? 'btn-primary' : 'btn-secondary'}
            style={{ padding: '4px 12px', fontSize: '13px' }}
            onClick={() => setFilter(f)}
          >
            {FILTER_LABELS[f]} ({count(f)})
          </button>
        ))}
      </div>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Status</th>
              <th>Source</th>
              <th>Setup</th>
              <th>Created</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Loading live data...</td></tr>
            )}
            {!loading && error && (
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--error)' }}>{error}</td></tr>
            )}
            {!loading && !error && shown.map((c) => (
              <tr key={c.id}>
                <td style={{ fontWeight: 500, color: 'var(--neutral-900)' }}>{c.name}</td>
                <td>
                  <span
                    className={`badge ${STATUS_BADGE[c.effective_status] ?? 'badge-warning'}`}
                    title={c.effective_status === 'trial' && c.trial_ends_at ? `Trial ends ${shortDate(c.trial_ends_at)}` : undefined}
                  >
                    {statusText(c)}
                  </span>
                </td>
                <td style={{ fontSize: '13px', color: 'var(--neutral-600)' }}>{SOURCE_LABELS[c.signup_source] ?? c.signup_source}</td>
                <td><SetupSteps setup={c.setup} /></td>
                <td style={{ fontSize: '13px', color: 'var(--neutral-500)', whiteSpace: 'nowrap' }}>{shortDate(c.created_at)}</td>
                <td style={{ textAlign: 'right' }}>
                  <button
                    style={{ background: 'none', border: 'none', color: 'var(--neutral-600)', fontWeight: 500, cursor: 'pointer', fontSize: '13px' }}
                    onClick={() => navigate(`/organizations/${c.id}`)}
                  >
                    Manage
                  </button>
                </td>
              </tr>
            ))}
            {!loading && !error && shown.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>
                  {companies.length === 0 ? 'No companies yet. Click "Create company" to add one.' : `No ${FILTER_LABELS[filter].toLowerCase()} companies.`}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {creating && (
        <CreateCompany
          onClose={() => setCreating(false)}
          onCreated={load}
          onOpen={(orgId) => navigate(`/organizations/${orgId}`)}
        />
      )}
    </div>
  );
}
