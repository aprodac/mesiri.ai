// SA-05 / SA-23: the Costs page's five views -- Companies, People, Days, and
// for one company its Messages (AI cost of handling each) and WhatsApp sent.
// Rows arrive already filtered and sorted by Costs.tsx; `type` only says
// which money column is the one being looked at.

import { ArrowUpRight } from 'lucide-react';
import { compact, full, inr } from './replyFormat';

export interface Totals {
  ai_calls: number;
  ai_cost_inr: string;
  whatsapp_messages: number;
  whatsapp_cost_inr: string;
  total_cost_inr: string;
  unpriced: number;
}

export interface DayRow extends Totals {
  day: string;
}

export interface CompanyRow extends Totals {
  organization_id: string | null;
  organization_name: string | null;
}

export interface PersonRow extends Totals {
  phone: string | null;
  user_id: string | null;
  full_name: string | null;
  role: string | null;
  organization_id: string | null;
  organization_name: string | null;
  messages_handled: number;
  input_tokens: number;
  output_tokens: number;
}

export interface MessageRow {
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

export interface SentRow {
  sent_at: string;
  recipient: string | null;
  operation: string | null;
  category: string | null;
  billable: boolean | null;
  cost_inr: string | null;
}

export type CostType = 'all' | 'ai' | 'whatsapp';

const num = { textAlign: 'right', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' } as const;

function when(iso: string | null): string {
  return iso
    ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' })
    : '—';
}

function dayLabel(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
}

function phoneLabel(digits: string | null): string {
  if (!digits) return '—';
  const d = digits.slice(-10);
  return `+91 ${d.slice(0, 5)} ${d.slice(5)}`;
}

function Empty({ cols, text }: { cols: number; text: string }) {
  return (
    <tr>
      <td colSpan={cols} style={{ textAlign: 'center', color: 'var(--neutral-500)', height: 72 }}>
        {text}
      </td>
    </tr>
  );
}

/** The money columns, with the one being filtered on marked. */
function money(type: CostType, key: CostType) {
  return { ...num, ...(type === key ? { color: 'var(--neutral-900)', fontWeight: 600 } : {}) };
}

function Unpriced({ n }: { n: number }) {
  return n > 0 ? (
    <span className="cv-unpriced" title="Calls with no price are not included">
      {' '}
      +{n}?
    </span>
  ) : null;
}

export function CompaniesView({ rows, type, onOpen }: { rows: CompanyRow[]; type: CostType; onOpen: (id: string, name: string) => void }) {
  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>Company</th>
            <th style={num}>AI calls</th>
            <th style={money(type, 'ai')}>AI</th>
            <th style={num}>Messages</th>
            <th style={money(type, 'whatsapp')}>WhatsApp</th>
            <th style={money(type, 'all')}>Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <Empty cols={6} text="No companies match these filters." />}
          {rows.map((c) => (
            <tr key={c.organization_id ?? 'none'}>
              <td>
                {c.organization_id ? (
                  <button className="cv-link" onClick={() => onOpen(c.organization_id as string, c.organization_name ?? 'Deleted company')}>
                    {c.organization_name ?? 'Deleted company'}
                    <ArrowUpRight size={13} />
                  </button>
                ) : (
                  <span className="cv-muted">No company yet (signups)</span>
                )}
              </td>
              <td style={num}>{full(c.ai_calls)}</td>
              <td style={money(type, 'ai')}>{inr(c.ai_cost_inr)}</td>
              <td style={num}>{full(c.whatsapp_messages)}</td>
              <td style={money(type, 'whatsapp')}>{inr(c.whatsapp_cost_inr)}</td>
              <td style={{ ...money(type, 'all'), fontWeight: 600 }}>
                {inr(c.total_cost_inr)}
                <Unpriced n={c.unpriced} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PeopleView({
  rows,
  type,
  showCompany,
  onOpenCompany,
}: {
  rows: PersonRow[];
  type: CostType;
  showCompany: boolean;
  onOpenCompany: (id: string, name: string) => void;
}) {
  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>Person</th>
            {showCompany && <th>Company</th>}
            <th style={money(type, 'ai')}>AI</th>
            <th style={money(type, 'whatsapp')}>WhatsApp</th>
            <th style={money(type, 'all')}>Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <Empty cols={showCompany ? 5 : 4} text="No people match these filters." />}
          {rows.map((p, i) => {
            const role = (p.role || '').toLowerCase().replace(/_/g, ' ');
            return (
              <tr key={`${p.organization_id}-${p.phone}-${p.user_id}-${i}`}>
                <td>
                  <div className="cv-person">
                    {p.phone === null ? 'Not tied to a person' : p.full_name || phoneLabel(p.phone)}
                  </div>
                  <div className="cv-sub">
                    {p.phone === null
                      ? 'Scheduled reports, reminders, setup'
                      : p.user_id
                        ? `${role ? role[0].toUpperCase() + role.slice(1) : 'User'} · ${phoneLabel(p.phone)}`
                        : 'Not a user of this company'}
                  </div>
                </td>
                {showCompany && (
                  <td>
                    {p.organization_id ? (
                      <button className="cv-link" onClick={() => onOpenCompany(p.organization_id as string, p.organization_name ?? 'Deleted company')}>
                        {p.organization_name ?? 'Deleted company'}
                      </button>
                    ) : (
                      <span className="cv-muted">No company yet</span>
                    )}
                  </td>
                )}
                <td style={money(type, 'ai')}>
                  {inr(p.ai_cost_inr)}
                  <div className="cv-sub">{p.ai_calls ? `${full(p.messages_handled)} msgs · ${compact(p.input_tokens + p.output_tokens)} tokens` : '—'}</div>
                </td>
                <td style={money(type, 'whatsapp')}>
                  {inr(p.whatsapp_cost_inr)}
                  <div className="cv-sub">{p.whatsapp_messages ? `${full(p.whatsapp_messages)} sent` : '—'}</div>
                </td>
                <td style={{ ...money(type, 'all'), fontWeight: 600 }}>
                  {inr(p.total_cost_inr)}
                  <Unpriced n={p.unpriced} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function DaysView({ rows, type }: { rows: DayRow[]; type: CostType }) {
  const top = Math.max(0.0001, ...rows.map((d) => Number(type === 'ai' ? d.ai_cost_inr : type === 'whatsapp' ? d.whatsapp_cost_inr : d.total_cost_inr)));
  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>Day</th>
            <th style={num}>AI calls</th>
            <th style={money(type, 'ai')}>AI</th>
            <th style={num}>Messages</th>
            <th style={money(type, 'whatsapp')}>WhatsApp</th>
            <th style={money(type, 'all')}>Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <Empty cols={6} text="No costs in this period." />}
          {rows.map((d) => {
            const v = Number(type === 'ai' ? d.ai_cost_inr : type === 'whatsapp' ? d.whatsapp_cost_inr : d.total_cost_inr);
            return (
              <tr key={d.day}>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {dayLabel(d.day)}
                  <span className="cv-bar">
                    <span style={{ width: `${(v / top) * 100}%` }} />
                  </span>
                </td>
                <td style={num}>{full(d.ai_calls)}</td>
                <td style={money(type, 'ai')}>{inr(d.ai_cost_inr)}</td>
                <td style={num}>{full(d.whatsapp_messages)}</td>
                <td style={money(type, 'whatsapp')}>{inr(d.whatsapp_cost_inr)}</td>
                <td style={{ ...money(type, 'all'), fontWeight: 600 }}>{inr(d.total_cost_inr)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function MessagesView({ rows }: { rows: MessageRow[] }) {
  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>Received</th>
            <th>Message</th>
            <th style={num}>AI calls</th>
            <th style={num}>Tokens in / out</th>
            <th style={num}>AI cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <Empty cols={5} text="No messages match these filters." />}
          {rows.map((m) => (
            <tr key={m.correlation_id}>
              <td style={{ whiteSpace: 'nowrap' }}>{when(m.received_at)}</td>
              <td style={{ maxWidth: 380 }}>
                <div className="cv-ellipsis" title={m.text ?? ''}>
                  {m.text || <span className="cv-muted">({m.message_type ?? 'message'})</span>}
                </div>
                {m.sender && <div className="cv-sub">{phoneLabel(m.sender)}</div>}
              </td>
              <td style={num}>{full(m.ai_calls)}</td>
              <td style={num}>
                {full(m.input_tokens)} / {full(m.output_tokens)}
              </td>
              <td style={{ ...num, fontWeight: 600 }}>
                {inr(m.ai_cost_inr)}
                <Unpriced n={m.unpriced} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SentView({ rows }: { rows: SentRow[] }) {
  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>Sent</th>
            <th>To</th>
            <th>Category</th>
            <th>Billed</th>
            <th style={num}>Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <Empty cols={5} text="No WhatsApp messages match these filters." />}
          {rows.map((s, i) => (
            <tr key={`${s.sent_at}-${i}`}>
              <td style={{ whiteSpace: 'nowrap' }}>{when(s.sent_at)}</td>
              <td style={{ whiteSpace: 'nowrap' }}>{phoneLabel(s.recipient)}</td>
              <td style={{ textTransform: 'capitalize' }}>{s.category ?? '—'}</td>
              <td>{s.billable === null ? <span className="cv-muted">Not known yet</span> : s.billable ? 'Yes' : 'No (free)'}</td>
              <td style={{ ...num, fontWeight: 600 }}>{inr(s.cost_inr)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
