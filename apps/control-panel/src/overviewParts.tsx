// SA-18 / SA-19: the Overview page's pieces -- the "Right now" tiles, the
// "Needs you" list grouped by urgency, the onboarding funnel and the
// companies panel. Shapes mirror GET /admin/overview
// (application/organizations/platform_overview.py).

import { useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { AlertOctagon, AlertTriangle, CheckCircle2, ChevronRight, Flame, Info, Moon } from 'lucide-react';
import { ago, full, SERIES } from './replyFormat';

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
  neutral: { fg: 'var(--neutral-400)', bg: 'var(--neutral-100)', Icon: Info },
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

/** A card with a title, a plain-language hint and a body; a long body
 *  scrolls inside itself (the page never does). */
export function Panel({ title, hint, aside, children, className }: { title: string; hint?: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`ov-panel ${className ?? ''}`}>
      <header className="ov-panel-head">
        <div style={{ minWidth: 0 }}>
          <h2>{title}</h2>
          {hint && <p>{hint}</p>}
        </div>
        {aside}
      </header>
      <div className="ov-panel-body">{children}</div>
    </section>
  );
}

// --- Right now ------------------------------------------------------------------

export function Metric({
  label,
  value,
  sub,
  tone,
  hint,
  to,
  progress,
}: {
  label: string;
  value: string;
  sub: ReactNode;
  tone?: Tone;
  hint: string;
  to: string;
  progress?: number;
}) {
  const t = tone ? TONE[tone] : null;
  return (
    <Link to={to} className="ov-metric" title={hint}>
      <div className="ov-metric-label">
        {t && <t.Icon size={13} strokeWidth={2.4} style={{ color: t.fg }} />}
        {label}
      </div>
      <div className="ov-metric-value">{value}</div>
      {progress !== undefined && (
        <div className="ov-progress">
          <span style={{ width: `${Math.min(100, Math.max(0, progress))}%` }} />
        </div>
      )}
      <div className="ov-metric-sub" style={t && (tone === 'critical' || tone === 'warning') ? { color: t.fg } : undefined}>
        {sub}
      </div>
    </Link>
  );
}

// --- Needs you --------------------------------------------------------------------

const GROUP_LABEL: Record<AttentionItem['severity'], string> = {
  critical: 'Urgent',
  warning: 'Follow up',
  info: 'When you have time',
};

export function AttentionList({ items }: { items: AttentionItem[] }) {
  if (!items.length) {
    return (
      <div className="ov-empty">
        <span className="ov-empty-check">
          <CheckCircle2 size={24} />
        </span>
        <strong>Nothing needs you right now</strong>
        <span>No failures, late reports, waiting buyers or stuck setups.</span>
      </div>
    );
  }
  const groups = (['critical', 'warning', 'info'] as const)
    .map((sev) => ({ sev, rows: items.filter((i) => i.severity === sev) }))
    .filter((g) => g.rows.length);
  return (
    <div>
      {groups.map(({ sev, rows }) => (
        <div key={sev} className="ov-att-group">
          <div className="ov-att-label">
            <span className="ov-dot" style={{ background: TONE[sev].fg }} />
            {GROUP_LABEL[sev]}
          </div>
          {rows.map((item) => {
            const t = TONE[item.severity];
            const names = item.companies.map((c) => `${c.name} (${c.note})`);
            return (
              <Link key={item.key} to={item.link} className="ov-att-row" title={item.detail}>
                <span className="ov-sev" style={{ color: t.fg, background: t.bg }}>
                  <t.Icon size={15} strokeWidth={2.2} />
                </span>
                <span style={{ minWidth: 0, flex: 1 }}>
                  <span className="ov-att-title">
                    <span>{item.title}</span>
                    <span className="ov-count" style={{ color: t.fg, background: t.bg }}>{full(item.count)}</span>
                  </span>
                  <span className="ov-att-sub">
                    {names.length ? names.slice(0, 2).join(', ') + (item.count > 2 ? ` +${item.count - 2} more` : '') : item.detail}
                  </span>
                </span>
                <ChevronRight size={16} className="ov-chevron" />
              </Link>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// --- Onboarding funnel --------------------------------------------------------------

const STEPS: { key: keyof OverviewData['funnel']; label: string }[] = [
  { key: 'started', label: 'Started a trial' },
  { key: 'has_site', label: 'Added a site' },
  { key: 'has_team', label: 'Has a site reporter' },
  { key: 'first_update', label: 'First site update' },
  { key: 'first_dpr', label: 'First DPR sent' },
  { key: 'converted', label: 'Paying' },
];

export function Funnel({ funnel }: { funnel: OverviewData['funnel'] }) {
  if (!funnel.started) {
    return <p className="ov-muted">No trials started in the last 30 days.</p>;
  }
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
  return (
    <div className="ov-funnel">
      {STEPS.map((s, i) => {
        const n = funnel[s.key];
        const pct = Math.round((n / top) * 100);
        return (
          <div key={s.key} className="ov-funnel-row" title={`${n} of ${funnel.started} companies (${pct}%)`}>
            <span className="ov-funnel-label">
              {s.label}
              {i === worst && <span className="ov-tag">biggest drop</span>}
            </span>
            <span className="ov-funnel-bar">
              <span style={{ width: `${pct}%`, minWidth: n ? 4 : 0, background: SERIES.blue }} />
            </span>
            <span className="ov-funnel-num">
              {full(n)} <span>{pct}%</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

// --- Companies ----------------------------------------------------------------------

const STATUS_SEGMENTS = [
  { key: 'active', label: 'Paying', color: SERIES.aqua },
  { key: 'trial', label: 'On trial', color: SERIES.blue },
  { key: 'expired', label: 'Expired', color: 'var(--neutral-300)' },
  { key: 'suspended', label: 'Suspended', color: SERIES.orange },
] as const;

function StatusBadge({ status, daysLeft }: { status: string; daysLeft: number | null }) {
  const cls = status === 'active' ? 'badge-success' : status === 'trial' ? 'badge-info' : status === 'suspended' ? 'badge-error' : 'badge-warning';
  return (
    <span className={`badge ${cls}`} style={{ height: 20, fontSize: 11, flex: 'none' }}>
      {status === 'active' ? 'Paying' : status === 'trial' ? 'Trial' : status[0].toUpperCase() + status.slice(1)}
      {status === 'trial' && daysLeft !== null ? ` · ${daysLeft}d left` : ''}
    </span>
  );
}

export function CompaniesPanel({ data }: { data: OverviewData }) {
  const c = data.companies;
  const [tab, setTab] = useState<'quiet' | 'active'>(data.gone_quiet.length ? 'quiet' : 'active');
  const rows = tab === 'quiet' ? data.gone_quiet : data.most_active;
  const stats = [
    { label: 'New trials', period: '7 days', value: c.new_trials_7d, hint: 'Trials started in the last 7 days', to: '/trials?days=7' },
    { label: 'Converted', period: '30 days', value: c.converted_30d, hint: 'Trials that converted to paying in the last 30 days', to: '/trials?days=30' },
    { label: 'Expired', period: 'now', value: c.expired, hint: 'Trials that ended without paying', to: '/organizations' },
  ];
  return (
    <>
      <Link to="/organizations" className="ov-co-total" title="Open the companies list">
        <span>
          <strong>{full(c.total)}</strong> companies
        </span>
        <ChevronRight size={15} />
      </Link>
      <div className="ov-segbar">
        {STATUS_SEGMENTS.map((s) => (c[s.key] ? <span key={s.key} title={`${s.label}: ${c[s.key]}`} style={{ flex: c[s.key], background: s.color }} /> : null))}
      </div>
      <div className="ov-legend">
        {STATUS_SEGMENTS.filter((s) => c[s.key]).map((s) => (
          <span key={s.key}>
            <span style={{ background: s.color }} />
            {c[s.key]} {s.label.toLowerCase()}
          </span>
        ))}
      </div>
      <div className="ov-co-stats">
        {stats.map((s) => (
          <Link key={s.label} to={s.to} title={s.hint}>
            <strong>{full(s.value)}</strong>
            <span>{s.label}</span>
            <em>{s.period}</em>
          </Link>
        ))}
      </div>

      <div className="ov-seg ov-seg-full" role="tablist">
        <button role="tab" aria-selected={tab === 'quiet'} className={tab === 'quiet' ? 'on' : ''} onClick={() => setTab('quiet')}>
          <Moon size={13} /> Gone quiet{data.gone_quiet.length ? ` · ${data.gone_quiet.length}` : ''}
        </button>
        <button role="tab" aria-selected={tab === 'active'} className={tab === 'active' ? 'on' : ''} onClick={() => setTab('active')}>
          <Flame size={13} /> Most active
        </button>
      </div>
      <p className="ov-muted" style={{ margin: '8px 0 2px' }}>
        {tab === 'quiet' ? 'No message for 3+ days — worth a call.' : 'Most WhatsApp messages in the last 7 days.'}
      </p>
      <div className="ov-scroll">
        {rows.length === 0 && (
          <p className="ov-muted" style={{ padding: '16px 0', textAlign: 'center' }}>
            {tab === 'quiet' ? 'Everyone has been in touch lately.' : 'No messages this week.'}
          </p>
        )}
        {rows.map((r) => (
          <Link key={r.id} to={`/organizations/${r.id}`} className="ov-co-row">
            <span style={{ minWidth: 0, flex: 1 }}>
              <span className="ov-co-name">{r.name}</span>
              <span className="ov-co-meta">
                {tab === 'quiet'
                  ? `Quiet ${r.quiet_days} days · last message ${r.last_message_at ? ago(r.last_message_at) : 'never'}`
                  : `${full(r.messages_7d)} messages · ${full(r.people_7d)} people · ${full(r.dprs_7d)} DPRs`}
              </span>
            </span>
            <StatusBadge status={r.status} daysLeft={r.trial_days_left} />
          </Link>
        ))}
      </div>
    </>
  );
}
