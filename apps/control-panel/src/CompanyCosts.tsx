// SA-22: the Costs tab on a company's page -- what the company cost over a
// period (AI and WhatsApp, in rupees before GST) and what each person in it
// cost: the AI calls made handling the messages they sent, and the WhatsApp
// messages sent to them. Costs tied to no one (a scheduled report, a
// reminder template) are their own row, so the rows add up to the total.
// Reads GET /admin/costs?organization_id=…; the Costs page has the same
// company's message-by-message detail.

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Bot, MessageCircle, Wallet } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import { compact, full, indianDay, inr } from './replyFormat';

interface Totals {
  ai_calls: number;
  ai_cost_inr: string;
  whatsapp_messages: number;
  whatsapp_cost_inr: string;
  total_cost_inr: string;
  unpriced: number;
}

interface PersonRow {
  phone: string | null;
  user_id: string | null;
  full_name: string | null;
  role: string | null;
  messages_handled: number;
  ai_calls: number;
  input_tokens: number;
  output_tokens: number;
  ai_cost_inr: string;
  whatsapp_messages: number;
  whatsapp_cost_inr: string;
  total_cost_inr: string;
  unpriced: number;
}

interface CompanyCostsResponse {
  totals: Totals;
  by_person: PersonRow[];
}

const RANGES = [
  { days: 1, label: 'Today' },
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
];

function who(p: PersonRow): { name: string; sub: string } {
  if (p.phone === null) return { name: 'Not tied to a person', sub: 'Scheduled reports, reminders and setup' };
  const phone = `+91 ${p.phone.slice(0, 5)} ${p.phone.slice(5)}`;
  if (!p.user_id) return { name: phone, sub: 'Not a user of this company' };
  const role = (p.role || '').toLowerCase().replace(/_/g, ' ');
  return { name: p.full_name || phone, sub: `${role ? role[0].toUpperCase() + role.slice(1) : 'User'} · ${phone}` };
}

export default function CompanyCosts({ orgId, orgName }: { orgId: string; orgName: string }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<CompanyCostsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .get<CompanyCostsResponse>('/admin/costs', {
        params: { from: indianDay(days - 1), to: indianDay(0), organization_id: orgId },
      })
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load costs')))
      .finally(() => setLoading(false));
  }, [orgId, days]);

  const t = data?.totals;
  const people = data?.by_person ?? [];
  const top = Math.max(0.0001, ...people.map((p) => Number(p.total_cost_inr)));
  const detail = `/costs?company=${orgId}&name=${encodeURIComponent(orgName)}&days=${days}`;

  return (
    <div className="cc" style={{ opacity: loading && data ? 0.7 : 1 }}>
      <div className="cc-bar">
        <div className="seg" role="tablist" aria-label="Period">
          {RANGES.map((r) => (
            <button key={r.days} role="tab" aria-selected={days === r.days} className={days === r.days ? 'on' : ''} onClick={() => setDays(r.days)}>
              {r.label}
            </button>
          ))}
        </div>
        <Link to={detail} className="oc-link cc-detail">
          Every message and send <ArrowUpRight size={13} />
        </Link>
      </div>

      {error && <div className="ov-error">{error}</div>}
      {!data && !error && <p className="oc-empty">Loading costs…</p>}

      {t && (
        <>
          <div className="cc-kpis">
            <div className="cc-kpi">
              <span className="cc-kpi-label">
                <Wallet size={14} /> Total
              </span>
              <span className="cc-kpi-value">{inr(t.total_cost_inr)}</span>
              <span className="cc-kpi-sub">Before GST{t.unpriced ? ` · ${t.unpriced} unpriced, not included` : ''}</span>
            </div>
            <div className="cc-kpi">
              <span className="cc-kpi-label">
                <Bot size={14} /> AI
              </span>
              <span className="cc-kpi-value">{inr(t.ai_cost_inr)}</span>
              <span className="cc-kpi-sub">{full(t.ai_calls)} calls</span>
            </div>
            <div className="cc-kpi">
              <span className="cc-kpi-label">
                <MessageCircle size={14} /> WhatsApp
              </span>
              <span className="cc-kpi-value">{inr(t.whatsapp_cost_inr)}</span>
              <span className="cc-kpi-sub">{full(t.whatsapp_messages)} messages sent</span>
            </div>
          </div>

          <section className="cc-people">
            <header className="cc-people-head">
              <h3>By person</h3>
              <span>AI for handling what they sent · WhatsApp for what was sent to them</span>
            </header>
            {people.length === 0 ? (
              <p className="oc-empty">No costs in this period.</p>
            ) : (
              <div className="cc-list">
                <div className="cc-row cc-cols" aria-hidden="true">
                  <span>Person</span>
                  <span>AI</span>
                  <span>WhatsApp</span>
                  <span>Total</span>
                </div>
                {people.map((p) => {
                  const w = who(p);
                  const share = (Number(p.total_cost_inr) / top) * 100;
                  return (
                    <div key={`${p.phone}-${p.user_id}`} className={`cc-row${p.phone === null ? ' system' : ''}`}>
                      <div className="cc-who">
                        <span className="cc-name">{w.name}</span>
                        <span className="cc-sub">{w.sub}</span>
                      </div>
                      <div className="cc-cell">
                        <span className="cc-cell-label">AI</span>
                        <span className="cc-cell-value">{inr(p.ai_cost_inr)}</span>
                        <span className="cc-cell-sub">
                          {p.ai_calls ? `${full(p.messages_handled)} msgs · ${compact(p.input_tokens + p.output_tokens)} tokens` : '—'}
                        </span>
                      </div>
                      <div className="cc-cell">
                        <span className="cc-cell-label">WhatsApp</span>
                        <span className="cc-cell-value">{inr(p.whatsapp_cost_inr)}</span>
                        <span className="cc-cell-sub">{p.whatsapp_messages ? `${full(p.whatsapp_messages)} sent` : '—'}</span>
                      </div>
                      <div className="cc-cell cc-total">
                        <span className="cc-cell-label">Total</span>
                        <span className="cc-cell-value">
                          {inr(p.total_cost_inr)}
                          {p.unpriced > 0 && (
                            <span className="cc-unpriced" title="Calls with no price are not included">
                              {' '}
                              +{p.unpriced}?
                            </span>
                          )}
                        </span>
                        <span className="cc-share">
                          <span style={{ width: `${share}%` }} />
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
