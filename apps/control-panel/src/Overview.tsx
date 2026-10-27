// SA-18 / SA-20: the Overview -- the super admin's morning screen, on one
// laptop screen with no page scroll.
//   KPI band   -- today in five numbers, each with its 14-day trend
//   Activity   -- the last 14 days, by messages / companies / DPRs / cost
//   Needs you  -- what to act on: Urgent, Follow up, When you have time
//   Companies  -- who's gone quiet, who's most active
//   Onboarding -- how far the last 30 days' trials got, and where they stop
// Every number opens the screen where it's handled. Reads GET /admin/overview
// and /admin/queue/health (worker state lives in Redis; only the assistant
// app can answer).

import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { api } from './api';
import { useAuth } from './AuthContext';
import { getErrorMessage } from './Toast';
import { AreaChart } from './overviewCharts';
import { compact, fmtMs, full, inr } from './replyFormat';
import { Card, Inbox, Kpi, Onboarding, WatchList, type OverviewData, type QueueHealth, type Tone } from './overviewParts';

const LIVE_MS = 60_000;

const METRICS = [
  { key: 'messages', label: 'Messages', unit: 'messages', format: (v: number) => compact(v) },
  { key: 'active_companies', label: 'Companies', unit: 'company-days', format: (v: number) => full(Math.round(v)) },
  { key: 'dprs_sent', label: 'DPRs', unit: 'DPRs sent', format: (v: number) => full(Math.round(v)) },
  { key: 'cost_inr', label: 'Cost', unit: 'spent', format: (v: number) => inr(String(Math.round(v * 100) / 100)) },
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

  const workerDown = queue !== null && queue !== 'unknown' && queue.queue_enabled && !queue.worker_alive;
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

  const s = data?.status;
  const series = (key: MetricKey) => (data ? data.activity.map((d) => Number(d[key])) : []);
  const yesterday = (key: MetricKey) => (data && data.activity.length > 1 ? Number(data.activity[data.activity.length - 2][key]) : 0);
  const speed = s ? (s.reply_p50_1h_ms ?? s.reply_p50_24h_ms) : null;
  const speedTone: Tone = speed === null ? 'neutral' : speed < 10_000 ? 'good' : speed < 30_000 ? 'warning' : 'critical';
  const operational = data ? data.companies.active + data.companies.trial : 0;
  const active = METRICS.find((m) => m.key === metric) ?? METRICS[0];
  const activeTotal = series(metric).reduce((a, b) => a + b, 0);
  const health = workerDown
    ? { tone: 'critical', text: 'Message worker down' }
    : urgent
      ? { tone: 'critical', text: `${urgent} urgent ${urgent === 1 ? 'issue' : 'issues'}` }
      : { tone: 'good', text: 'All systems normal' };

  return (
    <div className="animate-fade-in ov">
      <header className="ov-head">
        <div className="ov-title">
          <h1>
            {greeting()}
            {firstName ? `, ${firstName}` : ''}
          </h1>
          <p>
            {new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' })}
            {data && attention.length > 0 && (
              <>
                {' · '}
                {attention.length} {attention.length === 1 ? 'thing needs' : 'things need'} you
              </>
            )}
          </p>
        </div>
        <div className="ov-actions">
          {data && (
            <Link to={workerDown ? '/queue-health' : '/logs?status=failed'} className={`ov-health ${health.tone}`}>
              <span className="ov-health-dot" />
              {health.text}
            </Link>
          )}
          <button className={`ov-live${live ? ' on' : ''}`} onClick={() => setLive(!live)} aria-pressed={live} title="Refresh every minute">
            <span className="ov-switch" />
            Live
          </button>
          <button className="ov-icon-btn" onClick={() => load()} disabled={loading} title="Refresh now" aria-label="Refresh now">
            <RefreshCw size={15} className={loading ? 'ov-spin' : undefined} />
          </button>
        </div>
      </header>

      {error && <div className="ov-error">{error}</div>}
      {!data && !error && <div className="ov-skeleton" aria-label="Loading" />}

      {data && s && (
        <>
          <section className="kpis" aria-label="Today">
            <Kpi
              label="Messages today"
              value={full(data.today.messages)}
              trend={series('messages')}
              compare={`Yesterday ${full(yesterday('messages'))}`}
              to="/logs"
              hint="WhatsApp messages from site today (Indian time). The line is the last 14 days."
            />
            <Kpi
              label="Companies reporting"
              value={full(data.today.active_companies)}
              unit={` / ${full(operational)}`}
              trend={series('active_companies')}
              compare={`${full(data.companies.active_7d)} active this week`}
              to="/organizations"
              hint="Companies that sent a message today, out of those that can use Mesiri now."
            />
            <Kpi
              label="DPRs sent"
              value={full(data.today.dprs_sent)}
              unit={` / ${full(data.today.dprs_due)}`}
              tone={data.today.dprs_late ? 'critical' : data.today.dprs_due ? 'good' : 'neutral'}
              trend={series('dprs_sent')}
              compare={data.today.dprs_late ? `${data.today.dprs_late} late — past send time` : data.today.dprs_due ? 'All on time' : 'None due yet today'}
              to="/organizations"
              hint="Daily progress reports sent today, out of those whose send time has passed. Late means 30+ minutes past the project's send time."
            />
            <Kpi
              label="Reply speed"
              value={fmtMs(speed)}
              tone={speedTone}
              compare={s.reply_p95_24h_ms !== null ? `Slowest 5% ${fmtMs(s.reply_p95_24h_ms)}` : 'No replies yet'}
              to="/replies?window=1440"
              hint="How long a typical WhatsApp message waits for Mesiri's answer, last hour (or last 24 hours if quiet)."
            />
            <Kpi
              label="Cost today"
              value={inr(data.cost.today_inr)}
              trend={series('cost_inr')}
              compare={`${inr(data.cost.week_inr)} this week`}
              to="/costs?days=7"
              hint={`AI and WhatsApp, before GST. This week: AI ${inr(data.cost.week_ai_inr)}, WhatsApp ${inr(data.cost.week_whatsapp_inr)}.`}
            />
          </section>

          <div className="board" style={{ opacity: loading ? 0.85 : 1 }}>
            <div className="board-main">
              <Card
                title="Activity"
                meta={`${active.format(activeTotal)} ${active.unit} in 14 days`}
                className="grow"
                action={
                  <div className="seg" role="tablist">
                    {METRICS.map((m) => (
                      <button key={m.key} role="tab" aria-selected={metric === m.key} className={metric === m.key ? 'on' : ''} onClick={() => setMetric(m.key)}>
                        {m.label}
                      </button>
                    ))}
                  </div>
                }
              >
                <AreaChart
                  labels={data.activity.map((d) => new Date(`${d.day}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }))}
                  values={series(metric)}
                  format={active.format}
                />
              </Card>
              <Card
                title="Companies"
                meta={`${full(data.companies.total)} total · ${full(data.companies.active)} paying · ${full(data.companies.trial)} on trial`}
                action={
                  <Link to="/organizations" className="oc-link">
                    View all
                  </Link>
                }
                className="companies"
              >
                <WatchList data={data} />
              </Card>
            </div>

            <div className="board-side">
              <Card title="Needs you" meta={attention.length ? `${attention.length} open` : undefined} className="grow">
                <div className="oc-scroll">
                  <Inbox items={attention} />
                </div>
              </Card>
              <Card
                title="Onboarding"
                meta="Trials started in 30 days"
                action={
                  <Link to="/trials" className="oc-link">
                    Trials
                  </Link>
                }
              >
                <Onboarding funnel={data.funnel} />
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
