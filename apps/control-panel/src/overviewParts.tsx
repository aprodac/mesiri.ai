// SA-18: the Overview page's pieces -- the system status strip, the "needs
// attention" list, today's dark card, the onboarding funnel and the
// company tables. Shapes mirror GET /admin/overview
// (application/organizations/platform_overview.py).

import { Link } from 'react-router-dom';
import type { ReactNode } from 'react';
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock,
  Info,
  MessageSquare,
  Server,
  Timer,
} from 'lucide-react';
import { ago, fmtMs, full, inr, SERIES } from './replyFormat';

export interface AttentionItem {
  key: string;
  severity: 'critical' | 'warning' | 'info';
  title: string;
  detail: string;
  link: string;
  count: number;
  companies: { id: string; name: string; note: string }[];
}

export interface CompanyRow {
  id: string;
  name: string;
  status: string;
  trial_days_left: number | null;
  messages_7d: number;
  people_7d: number;
  dprs_7d: number;
  last_message_at: string | null;
  created_at: string | null;
  quiet_days?: number;
}

export interface OverviewData {
  generated_at: string;
  status: {
    messages_24h: number;
    failed_24h: number;
    unanswered: number;
    unanswered_oldest: string | null;
    reply_p50_1h_ms: number | null;
    reply_p50_24h_ms: number | null;
    reply_p95_24h_ms: number | null;
    replied_1h: number;
  };
  attention: AttentionItem[];
  today: {
    day: string;
    messages: number;
    active_companies: number;
    active_people: number;
    dprs_sent: number;
    dprs_due: number;
    dprs_late: number;
    dpr_projects: number;
    cost_inr: string;
  };
  companies: {
    total: number;
    active: number;
    trial: number;
    expired: number;
    suspended: number;
    new_trials_7d: number;
    trials_started_30d: number;
    converted_30d: number;
    active_7d: number;
  };
  funnel: Record<'started' | 'has_site' | 'has_team' | 'first_update' | 'first_dpr' | 'converted', number>;
  activity: { day: string; messages: number; active_companies: number; active_people: number; dprs_sent: number; cost_inr: string }[];
  cost: { today_inr: string; week_inr: string; week_ai_inr: string; week_whatsapp_inr: string; week_unpriced: number };
  most_active: CompanyRow[];
  gone_quiet: CompanyRow[];
}

export interface QueueHealth {
  queue_enabled: boolean;
  worker_alive: boolean;
  queue_depth: number | null;
}

/** Status colours: always shown with an icon and a word, never colour alone. */
const TONE = {
  good: { fg: 'var(--success)', bg: 'var(--success-soft)', Icon: CheckCircle2 },
  warning: { fg: '#b45309', bg: 'var(--warning-soft)', Icon: AlertTriangle },
  critical: { fg: 'var(--error)', bg: 'var(--error-soft)', Icon: AlertOctagon },
  info: { fg: 'var(--info)', bg: 'var(--info-soft)', Icon: Info },
  neutral: { fg: 'var(--neutral-500)', bg: 'var(--neutral-100)', Icon: Info },
} as const;
export type Tone = keyof typeof TONE;

export function TonePill({ tone, children }: { tone: Tone; children: ReactNode }) {
  const t = TONE[tone];
  return (
    <span className="ov-pill" style={{ color: t.fg, background: t.bg }}>
      <t.Icon size={13} strokeWidth={2.4} />
      {children}
    </span>
  );
}

// --- System status strip ----------------------------------------------------

function StatusCell({ icon, label, value, note, tone }: { icon: ReactNode; label: string; value: string; note: string; tone: Tone }) {
  const t = TONE[tone];
  return (
    <div className="ov-status-cell">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--neutral-500)', fontSize: '12px' }}>
        <span className="ov-icon-chip">{icon}</span>
        {label}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '2px 8px', flexWrap: 'wrap', marginTop: 10 }}>
        <span style={{ fontSize: '20px', fontWeight: 600, color: 'var(--neutral-900)' }}>{value}</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '12px', color: t.fg, fontWeight: 500 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: t.fg }} />
          {note}
        </span>
      </div>
    </div>
  );
}

export function StatusStrip({ data, queue }: { data: OverviewData; queue: QueueHealth | null | 'unknown' }) {
  const s = data.status;
  const worker =
    queue === null
      ? { value: '…', note: 'checking', tone: 'neutral' as Tone }
      : queue === 'unknown' || !queue.queue_enabled
        ? { value: 'Unknown', note: 'not reported here', tone: 'neutral' as Tone }
        : queue.worker_alive
          ? { value: 'Running', note: `${full(queue.queue_depth ?? 0)} queued`, tone: (queue.queue_depth ?? 0) > 20 ? ('warning' as Tone) : ('good' as Tone) }
          : { value: 'Down', note: 'messages are not handled', tone: 'critical' as Tone };
  const speed = s.reply_p50_1h_ms ?? s.reply_p50_24h_ms;
  const speedTone: Tone = speed === null ? 'neutral' : speed < 10_000 ? 'good' : speed < 30_000 ? 'warning' : 'critical';
  return (
    <div className="ov-status-strip">
      <StatusCell icon={<Server size={14} />} label="Message worker" value={worker.value} note={worker.note} tone={worker.tone} />
      <StatusCell
        icon={<Timer size={14} />}
        label={s.reply_p50_1h_ms !== null ? 'Typical reply, last hour' : 'Typical reply, last 24 h'}
        value={fmtMs(speed)}
        note={speed === null ? 'no replies yet' : speedTone === 'good' ? 'healthy' : 'slow'}
        tone={speedTone}
      />
      <StatusCell
        icon={<AlertOctagon size={14} />}
        label="Failed, last 24 h"
        value={full(s.failed_24h)}
        note={s.failed_24h ? `of ${full(s.messages_24h)} messages` : 'none'}
        tone={s.failed_24h ? 'critical' : 'good'}
      />
      <StatusCell
        icon={<Clock size={14} />}
        label="Waiting 10+ min for a reply"
        value={full(s.unanswered)}
        note={s.unanswered ? `oldest ${ago(s.unanswered_oldest)}` : 'none'}
        tone={s.unanswered ? 'warning' : 'good'}
      />
    </div>
  );
}

// --- Needs attention ----------------------------------------------------------

export function AttentionList({ items }: { items: AttentionItem[] }) {
  if (!items.length) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', textAlign: 'center', padding: 'var(--space-10) var(--space-4)', gap: 'var(--space-2)' }}>
        <span className="ov-empty-check">
          <CheckCircle2 size={26} />
        </span>
        <div style={{ fontWeight: 600, color: 'var(--neutral-900)', marginTop: 'var(--space-2)' }}>Nothing needs you right now</div>
        <div style={{ color: 'var(--neutral-500)', fontSize: '13px' }}>No failures, late reports, waiting leads or stuck setups.</div>
      </div>
    );
  }
  return (
    <div style={{ display: 'grid' }}>
      {items.map((item) => {
        const t = TONE[item.severity];
        return (
          <Link key={item.key} to={item.link} className="ov-attention-row">
            <span className="ov-sev" style={{ color: t.fg, background: t.bg }}>
              <t.Icon size={16} strokeWidth={2.2} />
            </span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontWeight: 600, color: 'var(--neutral-900)', fontSize: '14px' }}>{item.title}</span>
                <span className="ov-count" style={{ color: t.fg, background: t.bg }}>
                  {full(item.count)}
                </span>
                <span className="sr-only">{item.severity}</span>
              </div>
              <div style={{ color: 'var(--neutral-500)', fontSize: '12.5px', marginTop: 2 }}>{item.detail}</div>
              {item.companies.length > 0 && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                  {item.companies.slice(0, 3).map((c, i) => (
                    <span key={`${c.id}-${i}`} className="ov-chip">
                      <strong style={{ fontWeight: 500, color: 'var(--neutral-800)' }}>{c.name}</strong>
                      <span style={{ color: 'var(--neutral-500)' }}>{c.note}</span>
                    </span>
                  ))}
                  {item.count > 3 && <span className="ov-chip" style={{ color: 'var(--neutral-500)' }}>+{item.count - 3} more</span>}
                </div>
              )}
            </div>
            <ChevronRight size={18} className="ov-chevron" />
          </Link>
        );
      })}
    </div>
  );
}

// --- Today --------------------------------------------------------------------

export function TodayCard({ data }: { data: OverviewData }) {
  const t = data.today;
  const pct = t.dprs_due ? Math.min(100, Math.round((t.dprs_sent / t.dprs_due) * 100)) : 0;
  const row = (label: string, value: ReactNode) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '10px 0', borderTop: '1px solid var(--border-dark)', fontSize: '13px' }}>
      <span style={{ color: 'var(--neutral-400)' }}>{label}</span>
      <span style={{ color: 'var(--white)', fontWeight: 500, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  );
  return (
    <div className="card-dark ov-today">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: '13px', color: 'var(--neutral-400)' }}>Today</span>
        <span style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>
          {new Date(`${t.day}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 'var(--space-3)' }}>
        <span style={{ fontSize: '48px', fontWeight: 600, lineHeight: 1, color: 'var(--white)' }}>{full(t.messages)}</span>
        <span style={{ color: 'var(--neutral-400)', fontSize: '13px', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <MessageSquare size={14} /> messages from site
        </span>
      </div>

      <div style={{ marginTop: 'var(--space-6)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: 8 }}>
          <span style={{ color: 'var(--neutral-400)' }}>DPRs sent</span>
          <span style={{ color: 'var(--white)', fontWeight: 500 }}>
            {full(t.dprs_sent)} <span style={{ color: 'var(--neutral-500)' }}>of {full(t.dprs_due)} due so far</span>
          </span>
        </div>
        <div style={{ height: 8, borderRadius: 4, background: 'rgba(126,217,87,0.15)' }}>
          <div style={{ width: `${pct}%`, height: '100%', borderRadius: 4, background: 'var(--primary)', transition: 'width var(--transition-default)' }} />
        </div>
        <div style={{ fontSize: '12px', marginTop: 8, color: t.dprs_late ? '#fca5a5' : 'var(--neutral-500)' }}>
          {t.dprs_late
            ? `${t.dprs_late} late — past the send time`
            : `${full(t.dpr_projects)} project${t.dpr_projects === 1 ? '' : 's'} send a DPR every day`}
        </div>
      </div>

      <div style={{ marginTop: 'var(--space-5)' }}>
        {row('Companies reporting', full(t.active_companies))}
        {row('People reporting', full(t.active_people))}
        {row('Running cost', inr(t.cost_inr))}
      </div>
    </div>
  );
}

// --- Onboarding funnel ----------------------------------------------------------

const STEPS: { key: keyof OverviewData['funnel']; label: string }[] = [
  { key: 'started', label: 'Started a trial' },
  { key: 'has_site', label: 'Added a site' },
  { key: 'has_team', label: 'Has a site reporter' },
  { key: 'first_update', label: 'First site update' },
  { key: 'first_dpr', label: 'First DPR sent' },
  { key: 'converted', label: 'Paying' },
];

export function Funnel({ funnel }: { funnel: OverviewData['funnel'] }) {
  const top = Math.max(1, funnel.started);
  // The step that loses the most companies is where to help.
  let worst = -1;
  let worstDrop = 0;
  STEPS.slice(1).forEach((s, i) => {
    const drop = funnel[STEPS[i].key] - funnel[s.key];
    if (drop > worstDrop) {
      worstDrop = drop;
      worst = i + 1;
    }
  });
  if (!funnel.started) {
    return <p style={{ color: 'var(--neutral-500)', fontSize: '13px' }}>No trials started in the last 30 days.</p>;
  }
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {STEPS.map((s, i) => {
        const n = funnel[s.key];
        const pct = Math.round((n / top) * 100);
        return (
          <div key={s.key}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: 5 }}>
              <span style={{ color: 'var(--neutral-700)' }}>
                {s.label}
                {i === worst && <span className="ov-chip" style={{ marginLeft: 8, color: '#b45309', background: 'var(--warning-soft)', border: 'none' }}>biggest drop</span>}
              </span>
              <span style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--neutral-900)', fontWeight: 500 }}>
                {full(n)} <span style={{ color: 'var(--neutral-500)', fontWeight: 400 }}>· {pct}%</span>
              </span>
            </div>
            <div style={{ height: 8, background: 'var(--neutral-100)', borderRadius: 4 }}>
              <div style={{ width: `${pct}%`, minWidth: n ? 4 : 0, height: '100%', borderRadius: 4, background: SERIES.blue, opacity: 1 - i * 0.1 }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// --- Companies ------------------------------------------------------------------

function StatusBadge({ status, daysLeft }: { status: string; daysLeft: number | null }) {
  const cls = status === 'active' ? 'badge-success' : status === 'trial' ? 'badge-info' : status === 'suspended' ? 'badge-error' : 'badge-warning';
  return (
    <span className={`badge ${cls}`} style={{ textTransform: 'capitalize' }}>
      {status}
      {status === 'trial' && daysLeft !== null ? ` · ${daysLeft}d` : ''}
    </span>
  );
}

export function CompanyTable({ rows, quiet }: { rows: CompanyRow[]; quiet?: boolean }) {
  const num = { textAlign: 'right', fontVariantNumeric: 'tabular-nums' } as const;
  if (!rows.length) {
    return (
      <p style={{ color: 'var(--neutral-500)', fontSize: '13px', padding: 'var(--space-6)', textAlign: 'center', margin: 0 }}>
        {quiet ? 'Every company has been in touch in the last 3 days.' : 'No messages from any company this week.'}
      </p>
    );
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Company</th>
          <th>Status</th>
          {quiet ? <th style={num}>Quiet for</th> : <th style={num}>Messages</th>}
          {!quiet && <th style={num}>People</th>}
          {!quiet && <th style={num}>DPRs</th>}
          <th style={num}>Last message</th>
          <th style={{ width: 28 }} />
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className="ov-link-row">
            <td>
              <Link to={`/organizations/${r.id}`} style={{ color: 'var(--neutral-900)', fontWeight: 500, textDecoration: 'none' }}>
                {r.name}
              </Link>
            </td>
            <td>
              <StatusBadge status={r.status} daysLeft={r.trial_days_left} />
            </td>
            {quiet ? (
              <td style={{ ...num, color: (r.quiet_days ?? 0) >= 7 ? 'var(--error)' : 'var(--neutral-800)' }}>{r.quiet_days} days</td>
            ) : (
              <>
                <td style={num}>{full(r.messages_7d)}</td>
                <td style={num}>{full(r.people_7d)}</td>
                <td style={num}>{full(r.dprs_7d)}</td>
              </>
            )}
            <td style={{ ...num, color: 'var(--neutral-500)', fontSize: '13px' }}>{r.last_message_at ? ago(r.last_message_at) : 'never'}</td>
            <td>
              <Link to={`/organizations/${r.id}`} aria-label={`Open ${r.name}`} style={{ color: 'var(--neutral-400)', display: 'inline-flex' }}>
                <ChevronRight size={16} />
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
