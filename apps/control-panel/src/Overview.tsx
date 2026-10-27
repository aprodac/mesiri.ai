// SA-18 / SA-19: the Overview -- the super admin's morning screen, on one
// laptop screen with no page scroll. Three zones, read left to right:
//   Right now  -- six numbers: is the system fine, what happened today
//   Needs you  -- what to act on, grouped Urgent / Follow up / When you have time
//   The rest   -- activity over 14 days and onboarding (middle), companies
//                 with a watch list of who's gone quiet (right)
// Each number opens the screen where it's handled. A long list scrolls inside
// its own panel. Reads GET /admin/overview and /admin/queue/health (worker
// state lives in Redis; only the assistant app can answer).

import { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from './api';
import { useAuth } from './AuthContext';
import { getErrorMessage } from './Toast';
import { StackedColumns } from './replyCharts';
import { SERIES, compact, fmtMs, full, inr } from './replyFormat';
import {
  AttentionList,
  CompaniesPanel,
  Funnel,
  Metric,
  Panel,
  TonePill,
  type OverviewData,
  type QueueHealth,
  type Tone,
} from './overviewParts';

const LIVE_MS = 60_000;

const METRICS = [
  { key: 'messages', label: 'Messages', format: (v: number) => compact(v) },
  { key: 'active_companies', label: 'Companies', format: (v: number) => full(v) },
  { key: 'dprs_sent', label: 'DPRs', format: (v: number) => full(v) },
  { key: 'cost_inr', label: 'Cost', format: (v: number) => inr(String(v)) },
] as const;
type MetricKey = (typeof METRICS)[number]['key'];

function greeting(): string {
  const h = Number(new Date().toLocaleString('en-IN', { hour: 'numeric', hour12: false, timeZone: 'Asia/Kolkata' }));
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

export default function Overview() {
  const { me } = useAuth();
  const [data, setData] = useState<OverviewData | null>(null);
  const [queue, setQueue] = useState<QueueHealth | null | 'unknown'>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(true);
  const [metric, setMetric] = useState<MetricKey>('messages');
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

  const workerKnown = queue !== null && queue !== 'unknown' && queue.queue_enabled;
  const workerDown = workerKnown && !(queue as QueueHealth).worker_alive;
  const attention = data
    ? [
        ...(workerDown
          ? [{ key: 'worker', severity: 'critical' as const, title: 'Message worker is down', detail: 'WhatsApp messages are queuing up and not being answered', link: '/queue-health', count: 1, companies: [] }]
          : []),
        ...data.attention,
      ]
    : [];
  const urgent = attention.filter((i) => i.severity === 'critical').length;
  const firstName = me?.name?.split(' ')[0];
  const activeMetric = METRICS.find((m) => m.key === metric) ?? METRICS[0];

  // Right now: the system's health in one tile.
  const s = data?.status;
  const speed = s ? (s.reply_p50_1h_ms ?? s.reply_p50_24h_ms) : null;
  const problems = s ? s.failed_24h + s.unanswered : 0;
  const system: { value: string; tone: Tone; sub: string } = workerDown
    ? { value: 'Down', tone: 'critical', sub: 'messages are not handled' }
    : problems
      ? { value: 'Issues', tone: 'warning', sub: `${s?.failed_24h} failed · ${s?.unanswered} waiting` }
      : { value: 'Healthy', tone: 'good', sub: workerKnown ? 'worker running, nothing failed' : 'nothing failed in 24 h' };

  return (
    <div className="animate-fade-in ov-fit">
      <header className="ov-header">
        <div style={{ minWidth: 0 }}>
          <h1>
            {greeting()}
            {firstName ? `, ${firstName}` : ''}
          </h1>
          <p>
            {new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' })}
            {' · '}everything across every company, on one screen
          </p>
        </div>
        <div className="ov-header-actions">
          {data &&
            (urgent ? (
              <TonePill tone="critical">{urgent} urgent</TonePill>
            ) : attention.length ? (
              <TonePill tone="warning">{attention.length} to look at</TonePill>
            ) : (
              <TonePill tone="good">All clear</TonePill>
            ))}
          <label className="ov-live" title="Refresh every minute">
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
            Live
            {live && <span className="ov-live-dot" />}
          </label>
          <button className="ov-refresh" onClick={() => load()} disabled={loading} title="Refresh now">
            <RefreshCw size={14} className={loading ? 'ov-spin' : undefined} />
            {data ? new Date(data.generated_at).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' }) : 'Refresh'}
          </button>
        </div>
      </header>

      {error && <p style={{ color: 'var(--error)' }}>{error}</p>}
      {!data && !error && <div className="ov-skeleton" aria-label="Loading" />}

      {data && s && (
        <>
          {/* Right now */}
          <section className="ov-metrics" aria-label="Right now" style={{ opacity: loading ? 0.8 : 1 }}>
            <Metric
              label="System"
              value={system.value}
              tone={system.tone}
              sub={system.sub}
              to={workerDown ? '/queue-health' : problems ? `/logs?status=${s.failed_24h ? 'failed' : 'pending'}` : '/queue-health'}
              hint="Is Mesiri handling WhatsApp messages? Checks the message worker, failed messages (24 h) and messages waiting 10+ minutes for a reply."
            />
            <Metric
              label="Reply speed"
              value={fmtMs(speed)}
              tone={speed === null ? 'neutral' : speed < 10_000 ? 'good' : 'warning'}
              sub={s.reply_p50_1h_ms !== null ? 'typical, last hour' : 'typical, last 24 h'}
              to="/replies?window=1440"
              hint="How long a typical WhatsApp message waits for Mesiri's answer (the median)."
            />
            <Metric
              label="Messages today"
              value={full(data.today.messages)}
              sub={`${full(data.today.active_companies)} ${data.today.active_companies === 1 ? 'company' : 'companies'} · ${full(data.today.active_people)} ${data.today.active_people === 1 ? 'person' : 'people'}`}
              to="/logs"
              hint="WhatsApp messages from site today (Indian time), and how many companies and people sent them."
            />
            <Metric
              label="DPRs today"
              value={`${full(data.today.dprs_sent)} / ${full(data.today.dprs_due)}`}
              tone={data.today.dprs_late ? 'critical' : data.today.dprs_due ? 'good' : undefined}
              progress={data.today.dprs_due ? (data.today.dprs_sent / data.today.dprs_due) * 100 : 0}
              sub={data.today.dprs_late ? `${data.today.dprs_late} late` : `${full(data.today.dpr_projects)} projects send daily`}
              to="/organizations"
              hint="Daily progress reports sent today, out of those whose send time has passed. Late = 30+ minutes past the project's send time."
            />
            <Metric
              label="Active this week"
              value={full(data.companies.active_7d)}
              sub={`of ${full(data.companies.active + data.companies.trial)} companies`}
              to="/organizations"
              hint="Companies that sent at least one WhatsApp message in the last 7 days, out of those that can use Mesiri now."
            />
            <Metric
              label="Cost · 7 days"
              value={inr(data.cost.week_inr)}
              sub={`today ${inr(data.cost.today_inr)}`}
              to="/costs?days=7"
              hint={`AI ${inr(data.cost.week_ai_inr)} + WhatsApp ${inr(data.cost.week_whatsapp_inr)} over the last 7 days, before GST.`}
            />
          </section>

          {/* Needs you · activity + onboarding · companies */}
          <div className="ov-board" style={{ opacity: loading ? 0.8 : 1 }}>
            <Panel title="Needs you" hint="Most urgent first. Click a row to act on it." className="ov-col">
              <div className="ov-scroll">
                <AttentionList items={attention} />
              </div>
            </Panel>

            <div className="ov-col ov-stack">
              <Panel
                title="Last 14 days"
                hint="Per day, Indian time. Pick what to show."
                className="ov-grow"
              >
                <div role="tablist" className="ov-seg ov-chart-seg">
                  {METRICS.map((m) => (
                    <button key={m.key} role="tab" aria-selected={metric === m.key} className={metric === m.key ? 'on' : ''} onClick={() => setMetric(m.key)}>
                      {m.label}
                    </button>
                  ))}
                </div>
                <div className="ov-chart">
                  <StackedColumns
                    fill
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
                </div>
              </Panel>
              <Panel title="Onboarding" hint="Trials started in the last 30 days, and how far they got.">
                <Funnel funnel={data.funnel} />
              </Panel>
            </div>

            <Panel title="Companies" hint="Who's paying, who's on trial, and who to call." className="ov-col">
              <CompaniesPanel data={data} />
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
