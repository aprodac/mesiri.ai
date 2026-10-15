import { useState } from 'react';
import { Plus, X, CheckCircle2 } from 'lucide-react';
import { api } from './api';

// SA-01: the one screen our team uses to put a company on Mesiri. It sends
// the same request every onboarding path ends in (POST
// /admin/organizations/provision → create_company). Deployment type and
// database route are left to the server's defaults.

interface CreatedSite {
  site_id: string;
  name: string;
}

interface Created {
  id: string;
  name: string;
  status: string;
  trial_ends_at: string | null;
  materials_seeded: number;
  sites: CreatedSite[];
}

interface Props {
  onClose: () => void;
  onCreated: () => void;
  onOpen: (orgId: string) => void;
}

// FastAPI answers a bad body with a list of field errors, and our own
// refusals with a sentence.
function errorText(err: any): string {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d: any) => d?.msg).filter(Boolean).join('; ');
  }
  return 'Could not create the company. Nothing was created.';
}

const sectionTitle: React.CSSProperties = {
  fontSize: '14px',
  fontWeight: 600,
  margin: 'var(--space-6) 0 var(--space-3)',
  color: 'var(--neutral-900)',
};

const hint: React.CSSProperties = { fontSize: '12px', color: 'var(--neutral-500)', marginTop: 4 };

export default function CreateCompany({ onClose, onCreated, onOpen }: Props) {
  const [name, setName] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [ownerPhone, setOwnerPhone] = useState('');
  const [projectName, setProjectName] = useState('');
  const [sites, setSites] = useState<string[]>(['']);
  const [startAs, setStartAs] = useState<'trial' | 'active'>('trial');
  const [showLogin, setShowLogin] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Created | null>(null);

  const setSite = (i: number, value: string) =>
    setSites(sites.map((s, j) => (j === i ? value : s)));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password && !email.trim()) {
      setError('A password needs an email to log in with.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await api.post<Created>('/admin/organizations/provision', {
        name: name.trim(),
        admin_name: ownerName.trim(),
        admin_whatsapp_number: ownerPhone.trim(),
        admin_email: email.trim() || null,
        admin_password: password || null,
        project_name: projectName.trim(),
        // Empty rows are dropped by the server; none left → one site
        // named after the project.
        site_names: sites.map((s) => s.trim()).filter(Boolean),
        start_as: startAs,
      });
      setCreated(res.data);
      onCreated();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  };

  if (created) {
    return (
      <div className="modal-overlay">
        <div className="modal-content" data-testid="create-company-done">
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
            <CheckCircle2 size={22} style={{ color: 'var(--success)' }} />
            <h2 style={{ margin: 0 }}>{created.name} is ready</h2>
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9, fontSize: '14px', color: 'var(--neutral-700)' }}>
            <li>
              {created.status === 'trial' && created.trial_ends_at
                ? `Free trial until ${new Date(created.trial_ends_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}`
                : 'Active'}
            </li>
            <li>
              {created.sites.length === 1 ? 'Site' : `${created.sites.length} sites`}:{' '}
              {created.sites.map((s) => s.name).join(', ')}
            </li>
            <li>{created.materials_seeded} starter materials added</li>
            <li>The owner can now message Mesiri on WhatsApp from {ownerPhone.trim()}</li>
          </ul>
          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>Close</button>
            <button type="button" className="btn-primary" onClick={() => onOpen(created.id)}>Open company</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxHeight: '90vh', overflowY: 'auto' }}>
        <h2 style={{ marginBottom: 'var(--space-2)' }}>Create company</h2>
        <p style={{ fontSize: '13px', color: 'var(--neutral-500)', margin: '0 0 var(--space-4)' }}>
          The owner gets started on WhatsApp. Everything else can be set up later.
        </p>
        <form onSubmit={submit}>
          <div className="form-group">
            <label htmlFor="cc-name">Company name</label>
            <input id="cc-name" required className="form-input" placeholder="e.g. Skyline Builders" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
            <div className="form-group">
              <label htmlFor="cc-owner">Owner name</label>
              <input id="cc-owner" required className="form-input" placeholder="e.g. Ravi Kumar" value={ownerName} onChange={(e) => setOwnerName(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="cc-phone">Owner WhatsApp number</label>
              <input id="cc-phone" required type="tel" className="form-input" placeholder="98765 43210" value={ownerPhone} onChange={(e) => setOwnerPhone(e.target.value)} />
              <div style={hint}>Indian numbers can skip +91.</div>
            </div>
          </div>

          <div style={sectionTitle}>Project and sites</div>
          <div className="form-group">
            <label htmlFor="cc-project">Project name</label>
            <input id="cc-project" required className="form-input" placeholder="e.g. Skyline Apartments" value={projectName} onChange={(e) => setProjectName(e.target.value)} />
          </div>
          <div className="form-group">
            <label>Sites</label>
            {sites.map((site, i) => (
              <div key={i} style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}>
                <input
                  className="form-input"
                  aria-label={`Site ${i + 1}`}
                  placeholder={i === 0 ? (projectName.trim() || 'e.g. Block A') : 'e.g. Block B'}
                  value={site}
                  onChange={(e) => setSite(i, e.target.value)}
                />
                {sites.length > 1 && (
                  <button type="button" className="btn-secondary" aria-label={`Remove site ${i + 1}`} onClick={() => setSites(sites.filter((_, j) => j !== i))}>
                    <X size={14} />
                  </button>
                )}
              </div>
            ))}
            {sites.length < 20 && (
              <button type="button" className="btn-secondary" onClick={() => setSites([...sites, ''])}>
                <Plus size={14} /> Add another site
              </button>
            )}
            <div style={hint}>Each site gets its own daily report; the project report combines them. Leave empty for one site named after the project.</div>
          </div>

          <div style={sectionTitle}>Start as</div>
          <div style={{ display: 'flex', gap: 'var(--space-6)', fontSize: '14px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
              <input type="radio" name="start_as" checked={startAs === 'trial'} onChange={() => setStartAs('trial')} /> Free trial
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
              <input type="radio" name="start_as" checked={startAs === 'active'} onChange={() => setStartAs('active')} /> Active (paying)
            </label>
          </div>

          <div style={{ marginTop: 'var(--space-6)' }}>
            <button
              type="button"
              onClick={() => setShowLogin(!showLogin)}
              style={{ background: 'none', border: 'none', padding: 0, color: 'var(--neutral-600)', fontSize: '13px', cursor: 'pointer', textDecoration: 'underline' }}
            >
              {showLogin ? 'Hide dashboard login' : 'Dashboard login (optional)'}
            </button>
          </div>
          {showLogin && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)', marginTop: 'var(--space-3)' }}>
              <div className="form-group">
                <label htmlFor="cc-email">Owner email</label>
                <input id="cc-email" type="email" className="form-input" placeholder="ravi@skyline.in" value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div className="form-group">
                <label htmlFor="cc-password">Password</label>
                <input id="cc-password" type="password" className="form-input" placeholder="Temporary password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
            </div>
          )}

          {error && (
            <p role="alert" style={{ color: 'var(--error)', fontSize: '13px', margin: 'var(--space-4) 0 0' }}>{error}</p>
          )}

          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={saving}>
              {saving ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
