// SA-18 / SA-20: the Overview page's pieces -- the KPI band, the "Needs
// you" inbox, the onboarding steps and the companies watch list. Shapes
// mirror GET /admin/overview (application/organizations/platform_overview.py).

import { useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Check, ChevronRight } from 'lucide-react';
import { Sparkline } from './overviewCharts';
import { ago, full } from './replyFormat';

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

export type Tone = 'good' | 'warning' | 'critical' | 'neutral';

/** A white card with a title row and a body. */
export function Card({ title, meta, action, children, className }: { title: string; meta?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`oc ${className ?? ''}`}>
      <header className="oc-head">
        <h2>{title}</h2>
        {meta && <span className="oc-meta">{meta}</span>}
        {action && <span className="oc-action">{action}</span>}
      </header>
      <div className="oc-body">{children}</div>
    </section>
  );
}

// --- KPI band --------------------------------------------------------------------

export function Kpi({
  label,
  value,
  unit,
  compare,
  tone,
  trend,
  to,
  hint,
}: {
  label: string;
  value: string;
  unit?: string;
  compare: ReactNode;
  tone?: Tone;
  trend?: number[];
  to: string;
  hint: string;
}) {
  return (
    <Link to={to} className="kpi" title={hint}>
      <span className="kpi-label">
        {tone && tone !== 'neutral' && <span className={`kpi-dot ${tone}`} />}
        {label}
        <ArrowUpRight size={13} className="kpi-go" />
      </span>
      <span className="kpi-row">
        <span className="kpi-value">
          {value}
          {unit && <span className="kpi-unit">{unit}</span>}
        </span>
        {trend && <Sparkline values={trend} />}
      </span>
      <span className={`kpi-compare ${tone === 'critical' || tone === 'warning' ? tone : ''}`}>{compare}</span>
    </Link>
  );
}

// --- Needs you ------------------------------------------------------------------------

const GROUPS: { sev: AttentionItem['severity']; label: string }[] = [
  { sev: 'critical', label: 'Urgent' },
  { sev: 'warning', label: 'Follow up' },
  { sev: 'info', label: 'When you have time' },
];

export function Inbox({ items }: { items: AttentionItem[] }) {
  if (!items.length) {
    return (
      <div className="ib-empty">
        <span>
          <Check size={20} strokeWidth={2.5} />
        </span>
        <strong>You're all caught up</strong>
        <p>No failures, late reports, waiting buyers or stuck setups.</p>
      </div>
    );
  }
  return (
    <div className="ib">
      {GROUPS.map(({ sev, label }) => {
        const rows = items.filter((i) => i.severity === sev);
        if (!rows.length) return null;
        return (
          <div key={sev} className="ib-group">
            <div className="ib-label">
              <span className={`ib-dot ${sev}`} />
              {label}
              <span className="ib-n">{rows.length}</span>
            </div>
            {rows.map((item) => {
              const names = item.companies.map((c) => c.name);
              return (
                <Link key={item.key} to={item.link} className="ib-row" title={item.detail}>
                  <span className="ib-text">
                    <span className="ib-title">{item.title}</span>
                    <span className="ib-sub">
                      {names.length ? names.slice(0, 2).join(', ') + (item.count > 2 ? ` and ${item.count - 2} more` : '') : item.detail}
                    </span>
                  </span>
                  <span className={`ib-count ${sev}`}>{full(item.count)}</span>
                  <ChevronRight size={15} className="ib-chev" />
                </Link>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

// --- Onboarding -------------------------------------------------------------------------

const STEPS: { key: keyof OverviewData['funnel']; label: string }[] = [
  { key: 'started', label: 'Started trial' },
  { key: 'has_site', label: 'Added a site' },
  { key: 'has_team', label: 'Site reporter' },
  { key: 'first_update', label: 'First update' },
  { key: 'first_dpr', label: 'First DPR' },
  { key: 'converted', label: 'Paying' },
];

export function Onboarding({ funnel }: { funnel: OverviewData['funnel'] }) {
  if (!funnel.started) return <p className="oc-empty">No trials started in the last 30 days.</p>;
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
    <div className="ob">
      {STEPS.map((s, i) => {
        const n = funnel[s.key];
        const pct = Math.round((n / funnel.started) * 100);
        return (
          <div key={s.key} className={`ob-row${i === worst ? ' worst' : ''}`} title={`${n} of ${funnel.started} (${pct}%)`}>
            <span className="ob-label">{s.label}</span>
            <span className="ob-track">
              <span style={{ width: `${pct}%` }} />
            </span>
            <span className="ob-num">{full(n)}</span>
            <span className="ob-pct">{pct}%</span>
          </div>
        );
      })}
      {worst > 0 && (
        <p className="ob-note">
          Most drop off before <strong>{STEPS[worst].label.toLowerCase()}</strong> — {worstDrop} of {funnel[STEPS[worst - 1].key]} stop there.
        </p>
      )}
    </div>
  );
}

// --- Companies watch list ------------------------------------------------------------------

const AVATAR_TONES = ['#F5C542', '#A7C7E7', '#B9D8B0', '#E8B4A0', '#C9B7E3', '#E7D6A5'];

function Avatar({ name }: { name: string }) {
  const clean = name.replace(/^seed\s+/i, '');
  const tone = AVATAR_TONES[[...clean].reduce((a, ch) => a + ch.charCodeAt(0), 0) % AVATAR_TONES.length];
  return (
    <span className="wl-avatar" style={{ background: tone }}>
      {clean[0]?.toUpperCase()}
    </span>
  );
}

function Status({ status, daysLeft }: { status: string; daysLeft: number | null }) {
  const label = status === 'active' ? 'Paying' : status === 'trial' ? (daysLeft !== null ? `Trial · ${daysLeft}d left` : 'Trial') : status[0].toUpperCase() + status.slice(1);
  return <span className={`wl-status ${status}`}>{label}</span>;
}

export function WatchList({ data }: { data: OverviewData }) {
  const [tab, setTab] = useState<'quiet' | 'active'>(data.gone_quiet.length ? 'quiet' : 'active');
  const rows = tab === 'quiet' ? data.gone_quiet : data.most_active;
  return (
    <>
      <div className="wl-tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'quiet'} className={tab === 'quiet' ? 'on' : ''} onClick={() => setTab('quiet')}>
          Gone quiet <span>{data.gone_quiet.length}</span>
        </button>
        <button role="tab" aria-selected={tab === 'active'} className={tab === 'active' ? 'on' : ''} onClick={() => setTab('active')}>
          Most active <span>{data.most_active.length}</span>
        </button>
        <span className="wl-hint">{tab === 'quiet' ? 'No message in 3+ days — worth a call' : 'Most messages in the last 7 days'}</span>
      </div>
      <div className="wl-scroll">
        {rows.length === 0 ? (
          <p className="oc-empty">{tab === 'quiet' ? 'Every company has been in touch lately.' : 'No messages this week yet.'}</p>
        ) : (
          <table className="wl">
            <thead>
              <tr>
                <th>Company</th>
                <th>Status</th>
                {tab === 'quiet' ? <th className="r">Quiet for</th> : <th className="r">Messages</th>}
                {tab === 'active' && <th className="r">DPRs</th>}
                <th className="r">Last message</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/organizations/${r.id}`} className="wl-name">
                      <Avatar name={r.name} />
                      {r.name}
                    </Link>
                  </td>
                  <td>
                    <Status status={r.status} daysLeft={r.trial_days_left} />
                  </td>
                  {tab === 'quiet' ? (
                    <td className="r">{r.quiet_days} days</td>
                  ) : (
                    <td className="r">{full(r.messages_7d)}</td>
                  )}
                  {tab === 'active' && <td className="r">{full(r.dprs_7d)}</td>}
                  <td className="r muted">{r.last_message_at ? ago(r.last_message_at) : 'Never'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
