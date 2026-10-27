// SA-18: the Overview -- the super admin's morning screen. Top to bottom it
// answers: is anything broken (status strip), what needs me today (ranked
// list, each row opens the screen where it's fixed), what happened today,
// how the business is doing (companies, trials, conversions, cost, 14 days
// of activity, the onboarding funnel) and which companies need a nudge
// (most active, gone quiet). Reads GET /admin/overview and
// /admin/queue/health (worker state lives in Redis, only the assistant app
// can answer it).

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Flame, Moon, RefreshCw } from 'lucide-react';
import { api } from './api';
import { useAuth } from './AuthContext';
import { getErrorMessage } from './Toast';
import { StackedColumns } from './replyCharts';
import { SERIES, compact, full, inr } from './replyFormat';
import {
  AttentionList,
  CompanyTable,
  Funnel,
  StatusStrip,
  TodayCard,
  TonePill,
  type OverviewData,
  type QueueHealth,
} from './overviewParts';

const LIVE_MS = 60_000;

const METRICS = [
  { key: 'messages', label: 'Messages', format: (v: number) => compact(v) },
  { key: 'active_companies', label: 'Companies reporting', format: (v: number) => full(v) },
  { key: 'dprs_sent', label: 'DPRs sent', format: (v: number) => full(v) },
  { key: 'cost_inr', label: 'Cost', format: (v: number) => inr(String(v)) },
] as const;
type MetricKey = (typeof METRICS)[number]['key'];

const STATUS_SEGMENTS = [
  { key: 'active', label: 'Active', color: SERIES.aqua },
  { key: 'trial', label: 'Trial', color: SERIES.blue },
  { key: 'expired', label: 'Expired', color: 'var(--neutral-300)' },
  { key: 'suspended', label: 'Suspended', color: SERIES.orange },
] as const;

function greeting(): string {
  const h = Number(new Date().toLocaleString('en-IN', { hour: 'numeric', hour12: false, timeZone: 'Asia/Kolkata' }));
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

function Card({ title, aside, children, pad = true }: { title?: string; aside?: ReactNode; children: ReactNode; pad?: boolean }) {
  return (
    <section className="card ov-card" style={pad ? undefined : { padding: 0, overflow: 'hidden' }}>
      {title && (
        <div className="ov-card-head" style={pad ? undefined : { padding: 'var(--space-5) var(--space-5) var(--space-3)' }}>
          <h2>{title}</h2>
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

function Kpi({ label, value, note, to, children }: { label: string; value: string; note?: ReactNode; to: string; children?: ReactNode }) {
  return (
    <Link to={to} className="card ov-kpi">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ color: 'var(--neutral-500)', fontSize: '13px' }}>{label}</span>
        <ArrowUpRight size={14} className="ov-kpi-arrow" />
      </div>
      <div style={{ fontSize: '28px', fontWeight: 600, color: 'var(--neutral-900)', marginTop: 'var(--space-2)', lineHeight: 1.15 }}>{value}</div>
      {children}
      {note && <div style={{ color: 'var(--neutral-500)', fontSize: '12px', marginTop: 6 }}>{note}</div>}
    </Link>
  );
}

export default function Overview() {
  const { me } = useAuth();
  const [data, setData] = useState<OverviewData | null>(null);
  const [queue, setQueue] = useState<QueueHealth | null | 'unknown'>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(true);
  const [metric, setMetric] = useState<MetricKey>('messages');
  const [companyTab, setCompanyTab] = useState<'active' | 'quiet'>('active');
  const request = useRef(0);

  const load = useCallback(() => {
    const id = ++request.current;
    setLoading(true);
    api
      .get<QueueHealth>('/admin/queue/health')
      .then((res) => id === request.current && setQueue(res.data))
      .catch(() => id === request.current && setQueue('unknown'));
    return api
      .get<OverviewData>('/admin/overview')
      .then((res) => {
        if (id !== request.current) return;
        setData(res.data);
        setError(null);
      })
      .catch((err) => id === request.current && setError(getErrorMessage(err, 'Could not load the overview')))
      .finally(() => id === request.current && setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(load, LIVE_MS);
    return () => clearInterval(timer);
  }, [live, load]);

  const workerDown = queue !== null && queue !== 'unknown' && queue.queue_enabled && !queue.worker_alive;
  const critical = (data?.attention.filter((i) => i.severity === 'critical').length ?? 0) + (workerDown ? 1 : 0);
  const open = (data?.attention.length ?? 0) + (workerDown ? 1 : 0);
  const firstName = me?.name?.split(' ')[0];

  const c = data?.companies;
  const operational = c ? c.active + c.trial : 0;
  const convRate = c && c.trials_started_30d ? Math.round((c.converted_30d / c.trials_started_30d) * 100) : null;
  const activeMetric = METRICS.find((m) => m.key === metric) ?? METRICS[0];

  return (
    <div className="animate-fade-in ov-page">
      <header className="ov-header">
        <div>
          <h1 style={{ marginBottom: 4 }}>
            {greeting()}
            {firstName ? `, ${firstName}` : ''}
          </h1>
          <p className="subtitle" style={{ margin: 0 }}>
            {new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' })}
            {' · '}Here's how Mesiri is doing across every company.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          {data &&
            (critical ? (
              <TonePill tone="critical">{critical} urgent</TonePill>
            ) : open ? (
              <TonePill tone="warning">{open} to look at</TonePill>
            ) : (
              <TonePill tone="good">All clear</TonePill>
            ))}
          <label className="ov-live" title="Refresh every minute">
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
            Live
            {live && <span className="ov-live-dot" />}
          </label>
          <button className="btn-secondary" onClick={() => load()} disabled={loading} aria-label="Refresh">
            <RefreshCw size={16} className={loading ? 'ov-spin' : undefined} />
            {data ? `Updated ${new Date(data.generated_at).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })}` : 'Refresh'}
          </button>
        </div>
      </header>

      {error && <p style={{ color: 'var(--error)' }}>{error}</p>}
      {!data && !error && <div className="ov-skeleton" aria-label="Loading" />}

      {data && c && (
        <div style={{ opacity: loading ? 0.75 : 1, transition: 'opacity var(--transition-fast)' }}>
          <StatusStrip data={data} queue={queue} />

          {/* What needs me + today */}
          <div className="ov-grid-main">
            <Card
              title="Needs attention"
              aside={<span style={{ color: 'var(--neutral-500)', fontSize: '12px' }}>Most urgent first · click to act</span>}
            >
              {workerDown && (
                <Link to="/queue-health" className="ov-attention-row ov-attention-critical">
                  <span style={{ fontWeight: 600 }}>The message worker is down</span>
                  <span style={{ fontSize: '12.5px' }}>WhatsApp messages are queuing up and not being answered — open Queue Health</span>
                </Link>
              )}
              <AttentionList items={data.attention} />
            </Card>
            <div className="ov-stack">
              <TodayCard data={data} />
              <Card title="Onboarding, last 30 days" aside={<Link to="/trials" className="ov-link">Trials <ArrowUpRight size={13} /></Link>}>
                <Funnel funnel={data.funnel} />
              </Card>
            </div>
          </div>

          {/* Business pulse */}
          <div className="ov-kpis">
            <Kpi label="Companies" value={full(c.total)} to="/organizations" note={`${full(operational)} can use Mesiri now`}>
              <div className="ov-segbar" role="img" aria-label={STATUS_SEGMENTS.map((s) => `${c[s.key]} ${s.label}`).join(', ')}>
                {STATUS_SEGMENTS.map((s) =>
                  c[s.key] ? <span key={s.key} title={`${s.label}: ${c[s.key]}`} style={{ flex: c[s.key], background: s.color }} /> : null,
                )}
              </div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 8, fontSize: '11.5px', color: 'var(--neutral-600)' }}>
                {STATUS_SEGMENTS.filter((s) => c[s.key]).map((s) => (
                  <span key={s.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 2, background: s.color }} />
                    {c[s.key]} {s.label.toLowerCase()}
                  </span>
                ))}
              </div>
            </Kpi>
            <Kpi label="New trials" value={full(c.new_trials_7d)} to="/trials?days=7" note={`this week · ${full(c.trials_started_30d)} in 30 days`} />
            <Kpi
              label="Converted to paying"
              value={full(c.converted_30d)}
              to="/trials?days=30"
              note={convRate === null ? 'in the last 30 days' : `in 30 days · ${convRate}% of new trials`}
            />
            <Kpi
              label="Active this week"
              value={full(c.active_7d)}
              to="/logs"
              note={operational ? `of ${full(operational)} companies sent a message` : 'companies that sent a message'}
            />
            <Kpi
              label="Running cost, 7 days"
              value={inr(data.cost.week_inr)}
              to="/costs?days=7"
              note={`AI ${inr(data.cost.week_ai_inr)} · WhatsApp ${inr(data.cost.week_whatsapp_inr)}`}
            />
          </div>

          {/* Activity */}
          <div style={{ marginTop: 'var(--space-4)' }}>
            <Card
              title="Last 14 days"
              aside={
                <div role="tablist" className="ov-seg">
                  {METRICS.map((m) => (
                    <button key={m.key} role="tab" aria-selected={metric === m.key} className={metric === m.key ? 'on' : ''} onClick={() => setMetric(m.key)}>
                      {m.label}
                    </button>
                  ))}
                </div>
              }
            >
              <StackedColumns
                labels={data.activity.map((d) => new Date(`${d.day}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }))}
                format={activeMetric.format}
                empty="Nothing in the last 14 days."
                series={[
                  {
                    key: metric,
                    label: activeMetric.label,
                    color: metric === 'cost_inr' ? SERIES.orange : SERIES.blue,
                    values: data.activity.map((d) => Number(d[metric])),
                  },
                ]}
              />
            </Card>
          </div>

          {/* Companies that need a nudge */}
          <div style={{ marginTop: 'var(--space-4)' }}>
            <Card
              pad={false}
              title={companyTab === 'active' ? 'Most active this week' : 'Gone quiet'}
              aside={
                <div role="tablist" className="ov-seg">
                  <button role="tab" aria-selected={companyTab === 'active'} className={companyTab === 'active' ? 'on' : ''} onClick={() => setCompanyTab('active')}>
                    <Flame size={13} /> Most active
                  </button>
                  <button role="tab" aria-selected={companyTab === 'quiet'} className={companyTab === 'quiet' ? 'on' : ''} onClick={() => setCompanyTab('quiet')}>
                    <Moon size={13} /> Gone quiet{data.gone_quiet.length ? ` · ${data.gone_quiet.length}` : ''}
                  </button>
                </div>
              }
            >
              {companyTab === 'quiet' && (
                <p style={{ margin: '0 var(--space-5) var(--space-3)', color: 'var(--neutral-500)', fontSize: '12.5px' }}>
                  Companies that can use Mesiri but haven't sent a message for 3+ days — worth a call before they drift away.
                </p>
              )}
              <CompanyTable rows={companyTab === 'active' ? data.most_active : data.gone_quiet} quiet={companyTab === 'quiet'} />
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
