import { useEffect, useState } from 'react';
import { api } from './api';
import { getErrorMessage, useToast } from './Toast';

// SA-03: rename a company or change its primary contact. Address, phone and
// email are on the Letterhead tab (SA-09); suspend is on the Plan card
// (SS-10). Every change is recorded in the audit log by the API.

interface CompanyDetails {
  id: string;
  name: string;
  primary_contact: string | null;
}

export default function CompanyDetailsDialog({
  orgId,
  onClose,
  onSaved,
}: {
  orgId: string;
  onClose: () => void;
  onSaved: (details: CompanyDetails) => void;
}) {
  const { showToast } = useToast();
  const [name, setName] = useState<string | null>(null);
  const [contact, setContact] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<CompanyDetails>(`/admin/organizations/${orgId}/details`)
      .then((res) => {
        setName(res.data.name);
        setContact(res.data.primary_contact ?? '');
      })
      .catch((err) => setError(getErrorMessage(err, 'Could not load the company details')));
  }, [orgId]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await api.patch<CompanyDetails>(`/admin/organizations/${orgId}/details`, {
        name,
        primary_contact: contact,
      });
      showToast('Company details saved', 'success');
      onSaved(res.data);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not save the company details'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 460 }}>
        <h2>Edit company details</h2>
        <p style={{ fontSize: '14px', color: 'var(--neutral-600)', marginBottom: 'var(--space-4)' }}>
          The name shows in the dashboard and on WhatsApp. Address, phone and email are on the Letterhead tab.
        </p>
        {name === null && !error && <p style={{ fontSize: '14px', color: 'var(--neutral-500)' }}>Loading…</p>}
        {name !== null && (
          <>
            <div className="form-group">
              <label htmlFor="company-name">Company name</label>
              <input id="company-name" className="form-input" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="form-group">
              <label htmlFor="company-contact">Primary contact (optional)</label>
              <input
                id="company-contact"
                className="form-input"
                placeholder="e.g. Suresh, 98765 43210"
                value={contact}
                maxLength={300}
                onChange={(e) => setContact(e.target.value)}
              />
            </div>
          </>
        )}
        {error && <p style={{ fontSize: '14px', color: 'var(--error)' }}>{error}</p>}
        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={save} disabled={saving || name === null || !name.trim()}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
