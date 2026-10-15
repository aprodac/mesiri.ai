import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, ImageOff, Upload, X } from 'lucide-react';
import { api } from './api';
import { getErrorMessage, useToast } from './Toast';

// SA-09: the owner's letterhead / visiting card / logo photos (sent on
// WhatsApp, SS-14) next to the letterhead form, so the Mesiri team can fill
// it in and mark the request done. The assistant then tells the owner; this
// page never messages anyone. API: domains/admin/branding_router.py.

interface Letterhead {
  company_name: string;
  address: string | null;
  phone: string | null;
  email: string | null;
  letterhead_name: string | null;
  brand_color: string | null;
  gstin: string | null;
  signatory_name: string | null;
  signatory_designation: string | null;
  has_logo: boolean;
  logo_url: string | null;
}

interface RequestFile {
  index: number;
  content_type: string | null;
  received_at: string | null;
}

export interface BrandingRequest {
  organization_id: string;
  organization_name: string;
  id: string;
  status: string;
  created_at: string | null;
  done_at: string | null;
  owner_notified: boolean;
  file_count: number;
  files: RequestFile[];
}

interface CompanyBranding {
  letterhead: Letterhead;
  requests: BrandingRequest[];
}

const FIELDS: { key: keyof Letterhead; label: string; placeholder?: string }[] = [
  { key: 'letterhead_name', label: 'Name on letterhead', placeholder: 'If different from the account name' },
  { key: 'gstin', label: 'GSTIN', placeholder: '27AAPFU0939F1ZV' },
  { key: 'signatory_name', label: 'Signatory name' },
  { key: 'signatory_designation', label: 'Signatory designation', placeholder: 'e.g. Managing Director' },
  { key: 'brand_color', label: 'Brand colour', placeholder: '#1F6FEB' },
  { key: 'address', label: 'Address' },
  { key: 'phone', label: 'Phone' },
  { key: 'email', label: 'Email' },
];

type Form = Record<string, string>;

function toForm(l: Letterhead): Form {
  return Object.fromEntries(FIELDS.map((f) => [f.key, (l[f.key] as string | null) ?? '']));
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '—';
}

// A request's photo. Loaded with the admin's token (an <img src> can't send
// it), shown as a thumbnail; a file storage no longer has says so.
function Photo({ orgId, requestId, index, onOpen }: { orgId: string; requestId: string; index: number; onOpen: (url: string) => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    api
      .get(`/admin/organizations/${orgId}/branding-requests/${requestId}/files/${index}`, { responseType: 'blob' })
      .then((res) => {
        objectUrl = URL.createObjectURL(res.data as Blob);
        setUrl(objectUrl);
      })
      .catch(() => setMissing(true));
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [orgId, requestId, index]);

  const box: React.CSSProperties = {
    width: 120,
    height: 120,
    borderRadius: 'var(--radius-sm)',
    border: '1px solid var(--neutral-200)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    background: 'var(--neutral-50)',
  };
  if (missing) {
    return (
      <div style={{ ...box, flexDirection: 'column', gap: 4, fontSize: '11px', color: 'var(--neutral-500)', textAlign: 'center', padding: 8 }}>
        <ImageOff size={18} />
        File no longer available
      </div>
    );
  }
  if (!url) return <div style={box} />;
  return (
    <button type="button" aria-label={`Open photo ${index + 1}`} style={{ ...box, padding: 0, cursor: 'zoom-in' }} onClick={() => onOpen(url)}>
      <img src={url} alt={`Photo ${index + 1} from the owner`} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
    </button>
  );
}

function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export default function BrandingPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [data, setData] = useState<CompanyBranding | null>(null);
  const [form, setForm] = useState<Form>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const [confirmDone, setConfirmDone] = useState<BrandingRequest | null>(null);

  const apply = useCallback((d: CompanyBranding) => {
    setData(d);
    setForm(toForm(d.letterhead));
  }, []);

  const load = useCallback(() => {
    api
      .get<CompanyBranding>(`/admin/organizations/${orgId}/branding`)
      .then((res) => {
        apply(res.data);
        setError(null);
      })
      .catch((err) => setError(getErrorMessage(err, 'Could not load the letterhead')));
  }, [orgId, apply]);

  useEffect(load, [load]);

  if (error) return <div className="card" style={{ color: 'var(--error)' }}>{error}</div>;
  if (!data) return <div className="card">Loading letterhead…</div>;

  const saveFields = async (e: React.FormEvent) => {
    e.preventDefault();
    const changed = Object.fromEntries(
      FIELDS.filter((f) => form[f.key] !== ((data.letterhead[f.key] as string | null) ?? '')).map((f) => [f.key, form[f.key].trim() || null]),
    );
    if (Object.keys(changed).length === 0) return;
    setSaving(true);
    try {
      const res = await api.put<CompanyBranding>(`/admin/organizations/${orgId}/branding`, changed);
      apply(res.data);
      showToast('Letterhead saved', 'success');
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not save the letterhead'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const uploadLogo = async (file: File | undefined) => {
    if (!file) return;
    setSaving(true);
    try {
      const res = await api.put<CompanyBranding>(`/admin/organizations/${orgId}/branding/logo`, {
        content_type: file.type,
        data_base64: await readAsBase64(file),
      });
      apply(res.data);
      showToast('Logo uploaded', 'success');
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not upload the logo'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const removeLogo = async () => {
    setSaving(true);
    try {
      const res = await api.delete<CompanyBranding>(`/admin/organizations/${orgId}/branding/logo`);
      apply(res.data);
      showToast('Logo removed', 'success');
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not remove the logo'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const markDone = async (request: BrandingRequest) => {
    setSaving(true);
    try {
      await api.post(`/admin/organizations/${orgId}/branding-requests/${request.id}/done`);
      showToast('Marked done. The owner hears on their next WhatsApp message.', 'success');
      setConfirmDone(null);
      load();
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not mark the request done'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const openRequest = data.requests.find((r) => r.status === 'open');
  const shown = openRequest ?? data.requests[0];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 1fr) minmax(320px, 1.4fr)', gap: 'var(--space-6)', alignItems: 'start' }} data-testid="branding-panel">
      <div className="card">
        <h3 style={{ marginTop: 0, fontSize: '16px' }}>Photos from the owner</h3>
        {!shown ? (
          <p style={{ fontSize: '13px', color: 'var(--neutral-500)' }}>
            No photos yet. The owner is asked for their letterhead, visiting card or logo on WhatsApp.
          </p>
        ) : (
          <>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-3)', fontSize: '13px', color: 'var(--neutral-600)' }}>
              <span className={`badge ${shown.status === 'open' ? 'badge-warning' : 'badge-success'}`} style={{ whiteSpace: 'nowrap' }}>
                {shown.status === 'open' ? 'Open' : shown.owner_notified ? 'Done · owner told' : 'Done · owner not told yet'}
              </span>
              Received {when(shown.created_at)} · {shown.file_count} {shown.file_count === 1 ? 'file' : 'files'}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
              {shown.files.map((f) => (
                <Photo key={f.index} orgId={orgId} requestId={shown.id} index={f.index} onOpen={setViewing} />
              ))}
            </div>
            {shown.status === 'open' && (
              <button className="btn-primary" style={{ marginTop: 'var(--space-4)' }} disabled={saving} onClick={() => setConfirmDone(shown)}>
                <CheckCircle2 size={16} /> Mark done
              </button>
            )}
            {data.requests.length > 1 && (
              <p style={{ fontSize: '12px', color: 'var(--neutral-500)', marginBottom: 0 }}>
                {data.requests.length - 1} earlier {data.requests.length - 1 === 1 ? 'request' : 'requests'}, already done.
              </p>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0, fontSize: '16px' }}>Letterhead · {data.letterhead.company_name}</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)', marginBottom: 'var(--space-4)' }}>
          <div style={{ width: 72, height: 72, border: '1px solid var(--neutral-200)', borderRadius: 'var(--radius-sm)', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', fontSize: '11px', color: 'var(--neutral-400)' }}>
            {data.letterhead.logo_url ? <img src={data.letterhead.logo_url} alt="Company logo" style={{ maxWidth: '100%', maxHeight: '100%' }} /> : data.letterhead.has_logo ? 'Logo set' : 'No logo'}
          </div>
          <label className="btn-secondary" style={{ cursor: saving ? 'default' : 'pointer' }}>
            <Upload size={14} /> {data.letterhead.has_logo ? 'Replace logo' : 'Upload logo'}
            <input type="file" accept="image/png,image/jpeg,image/webp" style={{ display: 'none' }} disabled={saving} onChange={(e) => uploadLogo(e.target.files?.[0])} />
          </label>
          {data.letterhead.has_logo && (
            <button type="button" className="btn-secondary" disabled={saving} onClick={removeLogo}>Remove</button>
          )}
        </div>
        <div style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: -8, marginBottom: 'var(--space-4)' }}>PNG, JPEG or WebP, up to 700 KB.</div>
        <form onSubmit={saveFields}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 var(--space-4)' }}>
            {FIELDS.map((f) => (
              <div key={f.key} className="form-group" style={f.key === 'address' ? { gridColumn: '1 / -1' } : undefined}>
                <label htmlFor={`lh-${f.key}`}>{f.label}</label>
                <input id={`lh-${f.key}`} className="form-input" placeholder={f.placeholder} value={form[f.key] ?? ''} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
              </div>
            ))}
          </div>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save letterhead'}</button>
        </form>
      </div>

      {viewing && (
        <div className="modal-overlay" onClick={() => setViewing(null)}>
          <div style={{ position: 'relative', maxWidth: '90vw', maxHeight: '90vh' }}>
            <button type="button" aria-label="Close photo" className="btn-secondary" style={{ position: 'absolute', top: 8, right: 8 }} onClick={() => setViewing(null)}>
              <X size={14} />
            </button>
            <img src={viewing} alt="Photo from the owner" style={{ maxWidth: '90vw', maxHeight: '90vh', borderRadius: 'var(--radius-md)' }} />
          </div>
        </div>
      )}

      {confirmDone && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: 440 }}>
            <h2>Letterhead set up?</h2>
            <p style={{ fontSize: '14px', color: 'var(--neutral-600)' }}>
              Mark this request done when the letterhead and logo are in. Mesiri tells the owner "✅ Your letterhead is set up" on their next WhatsApp message.
            </p>
            <div className="modal-actions">
              <button type="button" className="btn-secondary" onClick={() => setConfirmDone(null)} disabled={saving}>Cancel</button>
              <button type="button" className="btn-primary" onClick={() => markDone(confirmDone)} disabled={saving}>
                {saving ? 'Saving…' : 'Mark done'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
