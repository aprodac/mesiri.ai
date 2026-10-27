import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from './api';
import { getErrorMessage } from './Toast';

// SA-05: what Mesiri costs to run -- AI calls and WhatsApp messages, in INR,
// from the per-call cost rows BE-25 records. All companies: totals, per day
// and per company. One company: the same, plus what handling each message it
// sent cost and each WhatsApp message sent to its people. Reads GET
// /admin/costs. Days are Indian calendar days.

interface Totals {
  ai_calls: number;
  ai_cost_inr: string;
  whatsapp_messages: number;
  whatsapp_cost_inr: string;
  total_cost_inr: string;
  unpriced: number;
}

interface DayRow extends Totals {
  day: string;
}

interface CompanyRow extends Totals {
  organization_id: string | null;
  organization_name: string | null;
}

interface MessageRow {
  correlation_id: string;
  received_at: string | null;
  sender: string | null;
  message_type: string | null;
  text: string | null;
  ai_calls: number;
  input_tokens: number;
  output_tokens: number;
  ai_cost_inr: string;
  unpriced: number;
}

interface SentRow {
  sent_at: string;
  recipient: string | null;
  operation: string | null;
  category: string | null;
  billable: boolean | null;
  cost_inr: string | null;
}

interface CostsResponse {
  from: string;
  to: string;
  organization_id: string | null;
  totals: Totals;
  by_day: DayRow[];
  by_company?: CompanyRow[];
  messages?: MessageRow[];
  sent?: SentRow[];
}

const RANGES = [
  { days: 1, label: 'Today' },
  { days: 7, label: 'Last 7 days' },
  { days: 30, label: 'Last 30 days' },
  { days: 90, label: 'Last 90 days' },
];

/** An Indian calendar day, `daysAgo` before today, as YYYY-MM-DD. */
function indianDay(daysAgo: number): string {
  const d = new Date(Date.now() - daysAgo * 86_400_000);
  return d.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
}

/** ₹ with paise kept for the small amounts most rows are. */
function inr(value: string | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: n < 1 ? 4 : 2 })}`;
}

function when(iso: string | null): string {
  return iso
    ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' })
    : '—';
}

function dayLabel(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
}

const muted = { color: 'var(--neutral-500)', fontSize: '13px' } as const;
const right = { textAlign: 'right' } as const;

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card">
      <div style={muted}>{label}</div>
      <div style={{ fontSize: '26px', fontWeight: 600, marginTop: 'var(--space-2)', color: 'var(--neutral-900)' }}>{value}</div>
      {note && <div style={{ ...muted, marginTop: 'var(--space-1)' }}>{note}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginTop: 'var(--space-8)' }}>
      <h2 style={{ fontSize: '16px', marginBottom: 'var(--space-3)' }}>{title}</h2>
      <div className="table-container">{children}</div>
    </section>
  );
}

function Empty({ cols, text }: { cols: number; text: string }) {
  return (
    <tr>
      <td colSpan={cols} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>
        {text}
      </td>
    </tr>
  );
}

export default function Costs() {
  const [params, setParams] = useSearchParams();
  const days = Number(params.get('days') || 7);
  const organizationId = params.get('company');
  const [data, setData] = useState<CostsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api
      .get<CostsResponse>('/admin/costs', {
        params: { from: indianDay(days - 1), to: indianDay(0), organization_id: organizationId || undefined },
      })
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load costs')));
  }, [days, organizationId]);

  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next);
  };

  const companyName = organizationId
    ? (data?.by_company?.find((c) => c.organization_id === organizationId)?.organization_name ?? params.get('name') ?? 'This company')
    : null;
  const totals = data?.totals;

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1100px' }}>
      <header style={{ marginBottom: 'var(--space-6)', display: 'flex', justifyContent: 'space-between', gap: 'var(--space-4)', flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div>
          <h1>{companyName ? `Costs · ${companyName}` : 'Costs'}</h1>
          <p className="subtitle">
            AI calls and WhatsApp messages, in rupees, before GST. Days are Indian days.
            {companyName && (
              <>
                {' '}
                <button
                  onClick={() => set({ company: null, name: null })}
                  style={{ background: 'none', border: 'none', padding: 0, color: 'var(--info)', cursor: 'pointer', fontSize: '14px' }}
                >
                  All companies
                </button>
              </>
            )}
          </p>
        </div>
        <select className="form-input" style={{ height: '36px', width: 'auto' }} value={days} onChange={(e) => set({ days: e.target.value })}>
          {RANGES.map((r) => (
            <option key={r.days} value={r.days}>
              {r.label}
            </option>
          ))}
        </select>
      </header>

      {error && <p style={{ color: 'var(--error)' }}>{error}</p>}
      {!error && !data && <p style={muted}>Loading…</p>}

      {totals && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(200px, 100%), 1fr))', gap: 'var(--space-4)' }}>
          <Stat label="Total" value={inr(totals.total_cost_inr)} note={totals.unpriced ? `${totals.unpriced} call(s) with no price, not included` : undefined} />
          <Stat label="AI" value={inr(totals.ai_cost_inr)} note={`${totals.ai_calls.toLocaleString('en-IN')} calls`} />
          <Stat label="WhatsApp" value={inr(totals.whatsapp_cost_inr)} note={`${totals.whatsapp_messages.toLocaleString('en-IN')} messages sent`} />
        </div>
      )}

      {data?.by_company && (
        <Section title="By company">
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th style={right}>AI calls</th>
                <th style={right}>AI</th>
                <th style={right}>Messages</th>
                <th style={right}>WhatsApp</th>
                <th style={right}>Total</th>
              </tr>
            </thead>
            <tbody>
              {data.by_company.length === 0 && <Empty cols={6} text="No costs in this period." />}
              {data.by_company.map((c) => (
                <tr key={c.organization_id ?? 'none'}>
                  <td>
                    {c.organization_id ? (
                      <button
                        onClick={() => set({ company: c.organization_id, name: c.organization_name ?? 'Deleted company' })}
                        style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontWeight: 500, color: 'var(--neutral-900)', fontSize: '14px', textAlign: 'left' }}
                      >
                        {c.organization_name ?? 'Deleted company'}
                      </button>
                    ) : (
                      <span style={muted}>No company yet (signups)</span>
                    )}
                  </td>
                  <td style={right}>{c.ai_calls}</td>
                  <td style={right}>{inr(c.ai_cost_inr)}</td>
                  <td style={right}>{c.whatsapp_messages}</td>
                  <td style={right}>{inr(c.whatsapp_cost_inr)}</td>
                  <td style={{ ...right, fontWeight: 600 }}>{inr(c.total_cost_inr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {data && (
        <Section title="By day">
          <table>
            <thead>
              <tr>
                <th>Day</th>
                <th style={right}>AI calls</th>
                <th style={right}>AI</th>
                <th style={right}>Messages</th>
                <th style={right}>WhatsApp</th>
                <th style={right}>Total</th>
              </tr>
            </thead>
            <tbody>
              {data.by_day.length === 0 && <Empty cols={6} text="No costs in this period." />}
              {data.by_day.map((d) => (
                <tr key={d.day}>
                  <td>{dayLabel(d.day)}</td>
                  <td style={right}>{d.ai_calls}</td>
                  <td style={right}>{inr(d.ai_cost_inr)}</td>
                  <td style={right}>{d.whatsapp_messages}</td>
                  <td style={right}>{inr(d.whatsapp_cost_inr)}</td>
                  <td style={{ ...right, fontWeight: 600 }}>{inr(d.total_cost_inr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {data?.messages && (
        <Section title="Messages from this company (AI cost of handling each, newest 200)">
          <table>
            <thead>
              <tr>
                <th>Received</th>
                <th>Message</th>
                <th style={right}>AI calls</th>
                <th style={right}>Tokens in / out</th>
                <th style={right}>AI cost</th>
              </tr>
            </thead>
            <tbody>
              {data.messages.length === 0 && <Empty cols={5} text="No AI calls in this period." />}
              {data.messages.map((m) => (
                <tr key={m.correlation_id}>
                  <td style={{ whiteSpace: 'nowrap' }}>{when(m.received_at)}</td>
                  <td style={{ maxWidth: '380px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={m.text ?? ''}>
                    {m.text || <span style={muted}>({m.message_type ?? 'message'})</span>}
                    {m.sender && <span style={{ ...muted, marginLeft: 'var(--space-2)' }}>+{m.sender}</span>}
                  </td>
                  <td style={right}>{m.ai_calls}</td>
                  <td style={right}>
                    {m.input_tokens.toLocaleString('en-IN')} / {m.output_tokens.toLocaleString('en-IN')}
                  </td>
                  <td style={right}>
                    {inr(m.ai_cost_inr)}
                    {m.unpriced > 0 && <span style={muted} title="Calls with no price are not included"> +{m.unpriced}?</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {data?.sent && (
        <Section title="WhatsApp messages sent to this company (newest 200)">
          <table>
            <thead>
              <tr>
                <th>Sent</th>
                <th>To</th>
                <th>Category</th>
                <th>Billed</th>
                <th style={right}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.sent.length === 0 && <Empty cols={5} text="No WhatsApp messages in this period." />}
              {data.sent.map((s, i) => (
                <tr key={`${s.sent_at}-${i}`}>
                  <td style={{ whiteSpace: 'nowrap' }}>{when(s.sent_at)}</td>
                  <td>{s.recipient ? `+${s.recipient}` : '—'}</td>
                  <td>{s.category ?? '—'}</td>
                  <td>{s.billable === null ? <span style={muted}>Not known yet</span> : s.billable ? 'Yes' : 'No (free)'}</td>
                  <td style={right}>{inr(s.cost_inr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </div>
  );
}
