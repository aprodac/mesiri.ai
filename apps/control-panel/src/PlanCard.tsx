import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import { getErrorMessage, useToast } from './Toast';
import { STATUS_BADGE, SOURCE_LABELS, shortDate, statusText, type Company } from './companyStatus';
import SetupSteps from './SetupSteps';

// SS-10: a company's plan on its page: the effective status, trial dates,
// days used, setup progress, and the superadmin's trial controls. Every
// action is recorded in the audit log by the API (trial_controls.py).

type Action = 'extend' | 'convert' | 'suspend' | 'reactivate';

interface Props {
  orgId: string;
  // The effective status whenever it is loaded or changed, so the page
  // header shows the same (an ended trial reads expired, not trial).
  onStatus?: (status: string) => void;
}

const label: React.CSSProperties = { fontSize: '12px', color: 'var(--neutral-500)' };
const value: React.CSSProperties = { fontSize: '13px', marginTop: 2 };

function daysUsed(c: Company): number | null {
  if (!c.trial_started_at) return null;
  const end = c.converted_at ? new Date(c.converted_at) : new Date();
  return Math.max(0, Math.floor((end.getTime() - new Date(c.trial_started_at).getTime()) / 86400000));
}

export default function PlanCard({ orgId, onStatus }: Props) {
  const { showToast } = useToast();
  const [company, setCompany] = useState<Company | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Action | null>(null);
  const [confirming, setConfirming] = useState<Action | null>(null);
  const [extendDays, setExtendDays] = useState(7);
  const [reason, setReason] = useState('');

  const load = useCallback(() => {
    api
      .get<Company>(`/admin/organizations/${orgId}/overview`)
      .then((res) => {
        setCompany(res.data);
        setError(null);
        onStatus?.(res.data.effective_status);
      })
      .catch((err) => setError(getErrorMessage(err, 'Could not load the plan')));
  }, [orgId, onStatus]);

  useEffect(load, [load]);

  const run = async (action: Action) => {
    setPending(action);
    try {
      const path = action === 'extend' ? 'trial/extend' : action;
      const body = action === 'extend' ? { days: extendDays } : action === 'suspend' ? { reason: reason.trim() || null } : undefined;
      await api.post(`/admin/organizations/${orgId}/${path}`, body);
      const done: Record<Action, string> = {
        extend: `Trial extended by ${extendDays} day${extendDays === 1 ? '' : 's'}`,
        convert: 'Converted to paid',
        suspend: 'Company suspended',
        reactivate: 'Company reactivated',
      };
      showToast(done[action], 'success');
      setConfirming(null);
      setReason('');
      load();
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not change the plan'), 'error');
    } finally {
      setPending(null);
    }
  };

  if (error) return <div className="card" style={{ marginBottom: 'var(--space-6)', color: 'var(--error)' }}>{error}</div>;
  if (!company) return null;

  const status = company.effective_status;
  const onTrial = status === 'trial' || status === 'expired';
  const used = daysUsed(company);

  return (
    <div className="card" style={{ marginBottom: 'var(--space-6)' }} data-testid="plan-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          <h3 style={{ margin: 0, fontSize: '16px' }}>Plan</h3>
          <span className={`badge ${STATUS_BADGE[status] ?? 'badge-warning'}`}>{statusText(company)}</span>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          {onTrial && (
            <>
              <button className="btn-secondary" disabled={!!pending} onClick={() => setConfirming('extend')}>Extend trial</button>
              <button className="btn-primary" disabled={!!pending} onClick={() => setConfirming('convert')}>Convert to paid</button>
            </>
          )}
          {status !== 'suspended' ? (
            <button className="btn-secondary" style={{ color: 'var(--error)', borderColor: 'var(--error)' }} disabled={!!pending} onClick={() => setConfirming('suspend')}>
              Suspend
            </button>
          ) : (
            <button className="btn-primary" disabled={!!pending} onClick={() => setConfirming('reactivate')}>Reactivate</button>
          )}
        </div>
      </div>

      {!!company.open_continue_requests && (
        <div className="badge badge-success" style={{ display: 'block', marginBottom: 'var(--space-4)', padding: '8px 12px', fontSize: '13px' }}>
          The owner asked to continue with Mesiri
          {company.continue_requested_at ? ` on ${shortDate(company.continue_requested_at)}` : ''}. Convert to paid or extend the trial to answer it.
        </div>
      )}
      {company.eligible_for_deletion && (
        <div className="badge badge-error" style={{ display: 'block', marginBottom: 'var(--space-4)', padding: '8px 12px', fontSize: '13px' }}>
          Eligible for deletion: the trial ended longer ago than its data is kept. Nothing is deleted automatically.
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(150px, 100%), 1fr))', gap: 'var(--space-4)' }}>
        <div><div style={label}>Source</div><div style={value}>{SOURCE_LABELS[company.signup_source] ?? company.signup_source}</div></div>
        <div><div style={label}>Trial started</div><div style={value}>{shortDate(company.trial_started_at ?? null)}</div></div>
        <div><div style={label}>Trial ends</div><div style={value}>{shortDate(company.trial_ends_at)}</div></div>
        <div><div style={label}>Days used</div><div style={value}>{used ?? '—'}</div></div>
        <div><div style={label}>Converted</div><div style={value}>{shortDate(company.converted_at ?? null)}</div></div>
        <div><div style={label}>Setup</div><div style={value}><SetupSteps setup={company.setup} /></div></div>
      </div>

      {confirming && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: 440 }}>
            {confirming === 'extend' && (
              <>
                <h2>Extend trial</h2>
                <p style={{ fontSize: '14px', color: 'var(--neutral-600)' }}>
                  Adds days to the trial{status === 'expired' ? ', counted from today, and switches the company back on' : ''}.
                </p>
                <div className="form-group">
                  <label htmlFor="extend-days">Days to add</label>
                  <input
                    id="extend-days"
                    type="number"
                    min={1}
                    max={90}
                    className="form-input"
                    value={extendDays}
                    onChange={(e) => setExtendDays(Math.max(1, Math.min(90, Number(e.target.value) || 1)))}
                  />
                </div>
              </>
            )}
            {confirming === 'convert' && (
              <>
                <h2>Convert to paid?</h2>
                <p style={{ fontSize: '14px', color: 'var(--neutral-600)' }}>
                  {company.name} becomes an active, paying customer. The trial no longer limits it.
                </p>
              </>
            )}
            {confirming === 'suspend' && (
              <>
                <h2>Suspend {company.name}?</h2>
                <p style={{ fontSize: '14px', color: 'var(--neutral-600)' }}>
                  Mesiri stops answering everyone in this company on WhatsApp from their next message, and no reports are sent. Their data is kept, and you can reactivate them at any time.
                </p>
                <div className="form-group">
                  <label htmlFor="suspend-reason">Reason (optional, kept in the audit log)</label>
                  <input id="suspend-reason" className="form-input" placeholder="e.g. invoice unpaid" value={reason} onChange={(e) => setReason(e.target.value)} />
                </div>
              </>
            )}
            {confirming === 'reactivate' && (
              <>
                <h2>Reactivate {company.name}?</h2>
                <p style={{ fontSize: '14px', color: 'var(--neutral-600)' }}>
                  {company.converted_at || !company.trial_ends_at
                    ? 'It goes back to active.'
                    : 'It goes back to its trial; if the trial has already ended it stays expired until you extend it.'}
                </p>
              </>
            )}
            <div className="modal-actions">
              <button type="button" className="btn-secondary" onClick={() => setConfirming(null)} disabled={!!pending}>Cancel</button>
              <button
                type="button"
                className="btn-primary"
                style={confirming === 'suspend' ? { background: 'var(--error)', borderColor: 'var(--error)', color: 'var(--white)' } : undefined}
                onClick={() => run(confirming)}
                disabled={!!pending}
              >
                {pending
                  ? 'Saving…'
                  : { extend: `Add ${extendDays} day${extendDays === 1 ? '' : 's'}`, convert: 'Convert to paid', suspend: 'Suspend', reactivate: 'Reactivate' }[confirming]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
