import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from './api';
import { getErrorMessage } from './Toast';
import type { BrandingRequest } from './BrandingPanel';

// SA-09: every owner's letterhead / logo photos (SS-14) across companies,
// open ones first and oldest first, so nothing waits unseen. Opening one
// goes to the company's Letterhead tab, where the work is done.

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '—';
}

function statusLabel(r: BrandingRequest): [string, string] {
  if (r.status === 'open') return ['Open', 'badge-warning'];
  return r.owner_notified ? ['Done · owner told', 'badge-success'] : ['Done · owner not told yet', 'badge-info'];
}

export default function BrandingRequests() {
  const navigate = useNavigate();
  const [requests, setRequests] = useState<BrandingRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<BrandingRequest[]>('/admin/branding-requests')
      .then((res) => setRequests(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load branding requests')));
  }, []);

  const open = requests?.filter((r) => r.status === 'open').length ?? 0;

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1000px' }}>
      <header style={{ marginBottom: 'var(--space-6)' }}>
        <h1>Branding requests</h1>
        <p className="subtitle">
          Letterhead, visiting card and logo photos owners sent on WhatsApp. Fill the letterhead in, then mark the request done.
          {requests && ` ${open} open.`}
        </p>
      </header>
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Received</th>
              <th>Files</th>
              <th>Status</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {error && <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--error)' }}>{error}</td></tr>}
            {!error && !requests && <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Loading…</td></tr>}
            {requests?.length === 0 && (
              <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>No branding requests yet.</td></tr>
            )}
            {requests?.map((r) => {
              const [label, badge] = statusLabel(r);
              return (
                <tr key={`${r.organization_id}-${r.id}`}>
                  <td style={{ fontWeight: 500, color: 'var(--neutral-900)' }}>{r.organization_name}</td>
                  <td style={{ fontSize: '13px', color: 'var(--neutral-600)' }}>{when(r.created_at)}</td>
                  <td style={{ fontSize: '13px' }}>{r.file_count}</td>
                  <td><span className={`badge ${badge}`}>{label}</span></td>
                  <td style={{ textAlign: 'right' }}>
                    <button
                      style={{ background: 'none', border: 'none', color: 'var(--neutral-600)', fontWeight: 500, cursor: 'pointer', fontSize: '13px' }}
                      onClick={() => navigate(`/organizations/${r.organization_id}?tab=letterhead`)}
                    >
                      Open
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
