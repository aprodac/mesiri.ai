import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from './api';
import { getErrorMessage } from './Toast';

// SS-11: what trials turn into. Of the trials started in a period: how many
// sent a first update, had a first DPR sent and converted, and what each cost
// while on trial (AI and WhatsApp, BE-25). Reads GET /admin/trials/funnel;
// each trial opens its company page.

interface Step {
  key: string;
  label: string;
  count: number;
  percent: number | null;
}

interface Trial {
  organization_id: string;
  name: string;
  signup_source: string;
  effective_status: string;
  trial_started_at: string;
  first_update_at: string | null;
  first_dpr_sent_at: string | null;
  converted_at: string | null;
  hours_to_first_update: number | null;
  reached: string[];
  ai_calls: number;
  whatsapp_messages: number;
  cost_inr: string;
}

interface Funnel {
  from: string;
  to: string;
  steps: Step[];
  still_on_trial: number;
  cost: { total_inr: string; per_trial_inr: string | null; per_conversion_inr: string | null; unpriced: number };
  trials: Trial[];
}

const RANGES = [
  { days: 7, label: 'Started in the last 7 days' },
  { days: 30, label: 'Started in the last 30 days' },
  { days: 90, label: 'Started in the last 90 days' },
  { days: 365, label: 'Started in the last year' },
];

const STATUS_BADGE: Record<string, [string, string]> = {
  trial: ['On trial', 'badge-info'],
  active: ['Converted', 'badge-success'],
  expired: ['Expired', 'badge-warning'],
  suspended: ['Suspended', 'badge-error'],
};

function indianDay(daysAgo: number): string {
  return new Date(Date.now() - daysAgo * 86_400_000).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
}

function inr(value: string | null): string {
  if (value === null) return '—';
  const n = Number(value);
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' }) : '—';
}

function after(hours: number | null): string {
  if (hours === null) return '';
  return hours < 48 ? ` (${Math.round(hours)} h in)` : ` (day ${Math.floor(hours / 24) + 1})`;
}

const muted = { color: 'var(--neutral-500)', fontSize: '13px' } as const;
const right = { textAlign: 'right' } as const;

export default function Trials() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const days = Number(params.get('days') || 30);
  const [data, setData] = useState<Funnel | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api
      .get<Funnel>('/admin/trials/funnel', { params: { from: indianDay(days - 1), to: indianDay(0) } })
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load the trials funnel')));
  }, [days]);

  const started = data?.steps[0]?.count ?? 0;

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1100px' }}>
      <header style={{ marginBottom: 'var(--space-6)', display: 'flex', justifyContent: 'space-between', gap: 'var(--space-4)', flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div>
          <h1>Trials</h1>
          <p className="subtitle">What trials turn into, and what each costs while on trial (AI and WhatsApp, before GST).</p>
        </div>
        <select
          className="form-input"
          style={{ height: '36px', width: 'auto' }}
          value={days}
          onChange={(e) => setParams({ days: e.target.value })}
        >
          {RANGES.map((r) => (
            <option key={r.days} value={r.days}>
              {r.label}
            </option>
          ))}
        </select>
      </header>

      {error && <p style={{ color: 'var(--error)' }}>{error}</p>}
      {!error && !data && <p style={muted}>Loading…</p>}

      {data && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(190px, 100%), 1fr))', gap: 'var(--space-4)' }}>
            {data.steps.map((step) => (
              <div key={step.key} className="card">
                <div style={muted}>{step.label}</div>
                <div style={{ fontSize: '28px', fontWeight: 600, marginTop: 'var(--space-2)', color: 'var(--neutral-900)' }}>
                  {step.count}
                  {step.key !== 'started' && step.percent !== null && (
                    <span style={{ fontSize: '15px', fontWeight: 500, color: 'var(--neutral-500)', marginLeft: 'var(--space-2)' }}>{step.percent}%</span>
                  )}
                </div>
                <div style={{ height: '6px', borderRadius: '3px', background: 'var(--surface-secondary)', marginTop: 'var(--space-3)' }}>
                  <div style={{ height: '6px', borderRadius: '3px', width: `${step.percent ?? 0}%`, background: 'var(--primary)' }} />
                </div>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 'var(--space-6)', flexWrap: 'wrap', marginTop: 'var(--space-5)', fontSize: '14px', color: 'var(--neutral-700)' }}>
            <span>Still on trial: <b>{data.still_on_trial}</b></span>
            <span>Cost of these trials: <b>{inr(data.cost.total_inr)}</b></span>
            <span>Per trial: <b>{inr(data.cost.per_trial_inr)}</b></span>
            <span>Per conversion: <b>{inr(data.cost.per_conversion_inr)}</b></span>
            {data.cost.unpriced > 0 && <span style={muted}>{data.cost.unpriced} call(s) with no price, not included</span>}
          </div>

          <section style={{ marginTop: 'var(--space-8)' }}>
            <h2 style={{ fontSize: '16px', marginBottom: 'var(--space-3)' }}>
              {started === 0 ? 'No trials started in this period.' : `The ${started} trial${started === 1 ? '' : 's'}, newest first`}
            </h2>
            {started > 0 && (
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Company</th>
                      <th>Started</th>
                      <th>First update</th>
                      <th>First DPR sent</th>
                      <th>Status</th>
                      <th style={right}>AI calls</th>
                      <th style={right}>Messages</th>
                      <th style={right}>Cost on trial</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trials.map((t) => {
                      const [label, badge] = STATUS_BADGE[t.effective_status] ?? [t.effective_status, 'badge-info'];
                      return (
                        <tr key={t.organization_id}>
                          <td>
                            <button
                              onClick={() => navigate(`/organizations/${t.organization_id}`)}
                              style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontWeight: 500, color: 'var(--neutral-900)', fontSize: '14px', textAlign: 'left' }}
                            >
                              {t.name}
                            </button>
                            <div style={muted}>{t.signup_source}</div>
                          </td>
                          <td>{when(t.trial_started_at)}</td>
                          <td>
                            {t.first_update_at ? when(t.first_update_at) + after(t.hours_to_first_update) : <span style={muted}>Not yet</span>}
                          </td>
                          <td>{t.first_dpr_sent_at ? when(t.first_dpr_sent_at) : <span style={muted}>Not yet</span>}</td>
                          <td>
                            <span className={`badge ${badge}`}>{label}</span>
                            {t.converted_at && <div style={muted}>{when(t.converted_at)}</div>}
                          </td>
                          <td style={right}>{t.ai_calls}</td>
                          <td style={right}>{t.whatsapp_messages}</td>
                          <td style={{ ...right, fontWeight: 600 }}>{inr(t.cost_inr)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
