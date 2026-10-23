import { useEffect, useState } from 'react';
import { api } from './api';
import { getErrorMessage, useToast } from './Toast';

// SA-11: errors in the app and worker go to the super admins on WhatsApp
// (platform setting `ops_alerts`). Every save is recorded in the audit log.

interface OpsAlerts {
  enabled: boolean;
  numbers: string[];
  team_group_fallback: boolean;
}

export default function OpsAlertsCard() {
  const { showToast } = useToast();
  const [value, setValue] = useState<OpsAlerts | null>(null);
  const [numbersText, setNumbersText] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<{ ops_alerts: { value: OpsAlerts } }>('/admin/platform-settings')
      .then((res) => {
        setValue(res.data.ops_alerts.value);
        setNumbersText(res.data.ops_alerts.value.numbers.join('\n'));
      })
      .catch((err) => setError(getErrorMessage(err, 'Could not load alert settings')));
  }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value) return;
    setSaving(true);
    const numbers = numbersText.split(/[\n,]+/).map((n) => n.trim()).filter(Boolean);
    try {
      const res = await api.put<{ value: OpsAlerts }>('/admin/platform-settings/ops_alerts', { ...value, numbers });
      setValue(res.data.value);
      setNumbersText(res.data.value.numbers.join('\n'));
      showToast('Alert settings saved', 'success');
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not save alert settings'), 'error');
    } finally {
      setSaving(false);
    }
  };

  if (error) return <div className="card" style={{ color: 'var(--error)' }}>{error}</div>;
  if (!value) return <div className="card">Loading alert settings…</div>;

  return (
    <div className="card" data-testid="ops-alerts">
      <h3 style={{ marginTop: 0, fontSize: '16px' }}>Error alerts on WhatsApp</h3>
      <p style={{ fontSize: '13px', color: 'var(--neutral-500)', marginTop: 0 }}>
        When something breaks, Mesiri messages every platform admin who has a WhatsApp number on their account, and the numbers below.
        The same error goes at most once every 30 minutes. Reply <b>alert details</b>, <b>mute alerts 2h</b> or <b>unmute alerts</b>.
      </p>
      <form onSubmit={save}>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: '14px', marginBottom: 'var(--space-4)' }}>
          <input type="checkbox" checked={value.enabled} onChange={(e) => setValue({ ...value, enabled: e.target.checked })} />
          Send error alerts
        </label>
        <div className="form-group">
          <label htmlFor="ops-alert-numbers">Also send to (one WhatsApp number per line, with country code)</label>
          <textarea
            id="ops-alert-numbers"
            className="form-input"
            rows={4}
            placeholder="919876543210"
            value={numbersText}
            onChange={(e) => setNumbersText(e.target.value)}
          />
        </div>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: '14px', marginBottom: 'var(--space-4)' }}>
          <input type="checkbox" checked={value.team_group_fallback} onChange={(e) => setValue({ ...value, team_group_fallback: e.target.checked })} />
          Post to the team WhatsApp group when no super admin could be reached
        </label>
        <button type="submit" className="btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save alert settings'}</button>
      </form>
    </div>
  );
}
