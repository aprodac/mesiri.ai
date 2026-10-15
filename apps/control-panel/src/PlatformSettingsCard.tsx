import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { api } from './api';
import { getErrorMessage, useToast } from './Toast';

// SS-10: Mesiri-wide trial rules and the self-serve signup switch
// (platform_settings, SS-02). Every save is recorded in the audit log.

interface TrialPolicy {
  trial_days: number;
  retention_days_after_expiry: number;
}

interface SettingsResponse {
  trial_policy: { value: TrialPolicy };
  self_serve: { value: { signup_enabled: boolean } };
}

export default function PlatformSettingsCard() {
  const { showToast } = useToast();
  const [trial, setTrial] = useState<TrialPolicy | null>(null);
  const [saved, setSaved] = useState<TrialPolicy | null>(null);
  const [signupEnabled, setSignupEnabled] = useState<boolean | null>(null);
  const [confirmSignup, setConfirmSignup] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<SettingsResponse>('/admin/platform-settings')
      .then((res) => {
        setTrial(res.data.trial_policy.value);
        setSaved(res.data.trial_policy.value);
        setSignupEnabled(res.data.self_serve.value.signup_enabled);
      })
      .catch((err) => setError(getErrorMessage(err, 'Could not load platform settings')));
  }, []);

  const saveTrial = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!trial) return;
    setSaving(true);
    try {
      const res = await api.put<{ value: TrialPolicy }>('/admin/platform-settings/trial_policy', trial);
      setTrial(res.data.value);
      setSaved(res.data.value);
      showToast('Trial settings saved', 'success');
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not save trial settings'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const saveSignup = async (enabled: boolean) => {
    setSaving(true);
    try {
      const res = await api.put<{ value: { signup_enabled: boolean } }>('/admin/platform-settings/self_serve', { signup_enabled: enabled });
      setSignupEnabled(res.data.value.signup_enabled);
      setConfirmSignup(null);
      showToast(enabled ? 'Self-serve signup switched on' : 'Self-serve signup switched off', 'success');
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not change self-serve signup'), 'error');
    } finally {
      setSaving(false);
    }
  };

  if (error) return <div className="card" style={{ color: 'var(--error)' }}>{error}</div>;
  if (!trial || signupEnabled === null) return <div className="card">Loading platform settings…</div>;

  const dirty = !!saved && (saved.trial_days !== trial.trial_days || saved.retention_days_after_expiry !== trial.retention_days_after_expiry);

  return (
    <div className="card" data-testid="platform-settings">
      <h3 style={{ marginTop: 0, fontSize: '16px' }}>Trials &amp; signup</h3>
      <p style={{ fontSize: '13px', color: 'var(--neutral-500)', marginTop: 0 }}>
        Apply to every company. Changes are recorded in the audit log.
      </p>
      <form onSubmit={saveTrial}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
          <div className="form-group">
            <label htmlFor="trial-days">Free trial length (days)</label>
            <input id="trial-days" type="number" min={1} max={365} required className="form-input" value={trial.trial_days} onChange={(e) => setTrial({ ...trial, trial_days: Number(e.target.value) })} />
            <div style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: 4 }}>New trials only; running trials keep their end date.</div>
          </div>
          <div className="form-group">
            <label htmlFor="retention-days">Keep data after a trial expires (days)</label>
            <input id="retention-days" type="number" min={0} max={3650} required className="form-input" value={trial.retention_days_after_expiry} onChange={(e) => setTrial({ ...trial, retention_days_after_expiry: Number(e.target.value) })} />
          </div>
        </div>
        <button type="submit" className="btn-primary" disabled={saving || !dirty}>{saving ? 'Saving…' : 'Save trial settings'}</button>
      </form>

      <div style={{ borderTop: '1px solid var(--neutral-200)', marginTop: 'var(--space-6)', paddingTop: 'var(--space-4)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-4)' }}>
        <div>
          <div style={{ fontWeight: 500, fontSize: '14px' }}>
            Self-serve signup: <span className={`badge ${signupEnabled ? 'badge-success' : 'badge-warning'}`}>{signupEnabled ? 'On' : 'Off'}</span>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: 4 }}>
            When on, any unknown WhatsApp number can start a free trial on its own.
          </div>
        </div>
        <button className="btn-secondary" disabled={saving} onClick={() => setConfirmSignup(!signupEnabled)}>
          {signupEnabled ? 'Switch off' : 'Switch on'}
        </button>
      </div>

      {confirmSignup !== null && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: 460 }}>
            <h2>{confirmSignup ? 'Switch on self-serve signup?' : 'Switch off self-serve signup?'}</h2>
            {confirmSignup ? (
              <p style={{ fontSize: '14px', color: 'var(--neutral-600)', display: 'flex', gap: 8 }}>
                <AlertTriangle size={18} style={{ color: 'var(--warning)', flexShrink: 0 }} />
                Anyone who messages Mesiri from an unknown number can create a company on a free trial. The abuse limits (SS-09) are not built yet, so keep an eye on new companies.
              </p>
            ) : (
              <p style={{ fontSize: '14px', color: 'var(--neutral-600)' }}>
                Unknown numbers get the old "not registered" reply again. Companies already created are not affected.
              </p>
            )}
            <div className="modal-actions">
              <button type="button" className="btn-secondary" onClick={() => setConfirmSignup(null)} disabled={saving}>Cancel</button>
              <button type="button" className="btn-primary" onClick={() => saveSignup(confirmSignup)} disabled={saving}>
                {saving ? 'Saving…' : confirmSignup ? 'Switch on' : 'Switch off'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
