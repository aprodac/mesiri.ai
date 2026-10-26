// SA-17: Reply Insights -- how fast every WhatsApp message was answered and
// the AI tokens it took, across companies. Headline numbers, reply time and
// tokens over time, the speed bands, where the tokens go (by step and by
// model) and the message feed. Filters live in the URL so a view can be
// shared. Reads GET /admin/replies and /admin/replies/messages.

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import ReplyFeed from './ReplyFeed';
import { BandBars, Legend, LineChart, StackedColumns } from './replyCharts';
import {
  type Feed,
  type Overview,
  SERIES,
  bucketLabel,
  compact,
  fmtMs,
  full,
  inr,
  muted,
  num,
} from './replyFormat';

const WINDOWS = [
  { minutes: 60, label: 'Last hour' },
  { minutes: 360, label: 'Last 6 hours' },
  { minutes: 1440, label: 'Last 24 hours' },
  { minutes: 10080, label: 'Last 7 days' },
  { minutes: 43200, label: 'Last 30 days' },
];

const TYPES = ['text', 'audio', 'image', 'interactive', 'button', 'document', 'video', 'location'];

const SORTS = [
  { key: 'newest', label: 'Newest' },
  { key: 'slowest', label: 'Slowest' },
  { key: 'tokens', label: 'Most tokens' },
  { key: 'cost', label: 'Most expensive' },
];

const PAGE = 50;
const LIVE_MS = 30_000;
/** "Slow only" in the feed: the band where a reply starts to feel slow. */
const SLOW_MS = 15_000;

interface CompanyOption {
  id: string;
  name: string;
}

function bandLabels(bounds: number[]): string[] {
  const s = (ms: number) => (ms >= 60_000 ? `${ms / 60_000} min` : `${ms / 1000} s`);
  return [
    `Under ${s(bounds[0])}`,
    ...bounds.slice(1).map((hi, i) => {
      const lo = s(bounds[i]);
      // "5–15 s", but "30 s–1 min" when the units differ.
      return lo.split(' ')[1] === s(hi).split(' ')[1] ? `${lo.split(' ')[0]}–${s(hi)}` : `${lo}–${s(hi)}`;
    }),
    `Over ${s(bounds[bounds.length - 1])}`,
  ];
}

function Tile({ label, value, note }: { label: string; value: string; note?: ReactNode }) {
  return (
    <div className="card">
      <div style={muted}>{label}</div>
      <div style={{ fontSize: '26px', fontWeight: 600, marginTop: 'var(--space-2)', color: 'var(--neutral-900)' }}>{value}</div>
      {note && <div style={{ ...muted, fontSize: '12px', marginTop: 'var(--space-1)' }}>{note}</div>}
    </div>
  );
}

function Panel({ title, note, aside, children }: { title: string; note?: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="card" style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-3)', flexWrap: 'wrap', marginBottom: 'var(--space-4)' }}>
        <div>
          <h2 style={{ fontSize: '15px', margin: 0 }}>{title}</h2>
          {note && <p style={{ ...muted, fontSize: '12px', margin: '4px 0 0' }}>{note}</p>}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

export default function Replies() {
  const [params, setParams] = useSearchParams();
  const minutes = Number(params.get('window') || 1440);
  const company = params.get('company') || '';
  const type = params.get('type') || '';
  const sort = params.get('sort') || 'newest';
  const slowOnly = params.get('slow') === '1';
  const page = Number(params.get('page') || 0);

  const [overview, setOverview] = useState<Overview | null>(null);
  const [feed, setFeed] = useState<Feed | null>(null);
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [updated, setUpdated] = useState<Date | null>(null);
  const request = useRef(0);

  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key);
      else next.set(key, value);
    }
    if (!('page' in changes)) next.delete('page');
    setParams(next);
  };

  const load = useCallback(() => {
    const id = ++request.current;
    setLoading(true);
    const scope = { since_minutes: minutes, organization_id: company || undefined, message_type: type || undefined };
    return Promise.all([
      api.get<Overview>('/admin/replies', { params: scope }),
      api.get<Feed>('/admin/replies/messages', {
        params: { ...scope, sort, slower_than_ms: slowOnly ? SLOW_MS : undefined, limit: PAGE, offset: page * PAGE },
      }),
    ])
      .then(([o, f]) => {
        if (id !== request.current) return;
        setOverview(o.data);
        setFeed(f.data);
        setError(null);
        setUpdated(new Date());
      })
      .catch((err) => id === request.current && setError(getErrorMessage(err, 'Could not load reply insights')))
      .finally(() => id === request.current && setLoading(false));
  }, [minutes, company, type, sort, slowOnly, page]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(load, LIVE_MS);
    return () => clearInterval(timer);
  }, [live, load]);

  useEffect(() => {
    api
      .get<CompanyOption[]>('/admin/organizations')
      .then((res) => setCompanies([...res.data].sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => setCompanies([]));
  }, []);

  const s = overview?.summary;
  const labels = overview ? overview.timeline.map((p) => bucketLabel(p.bucket, overview.step_minutes)) : [];
  const tokensPerAiMessage = s && s.with_ai ? (s.input_tokens + s.output_tokens) / s.with_ai : null;
  const cachedShare = s && s.input_tokens ? Math.round((s.cached_input_tokens / s.input_tokens) * 100) : 0;
  const stepTotal = overview ? Math.max(1, ...overview.by_step.map((r) => r.input_tokens + r.output_tokens)) : 1;
  const modelTotal = overview ? overview.by_model.reduce((t, r) => t + r.input_tokens + r.output_tokens, 0) : 0;
  const pages = feed ? Math.max(1, Math.ceil(feed.total / PAGE)) : 1;

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1240px' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 'var(--space-4)', flexWrap: 'wrap', marginBottom: 'var(--space-5)' }}>
        <div>
          <h1>Reply Insights</h1>
          <p className="subtitle">How fast every WhatsApp message gets an answer, and the AI tokens it takes.</p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
          {updated && (
            <span style={{ ...muted, fontSize: '12px' }}>
              Updated {updated.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '13px', color: 'var(--neutral-700)', cursor: 'pointer' }}>
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
            Live
            {live && <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--success)', boxShadow: '0 0 0 3px var(--success-soft)' }} />}
          </label>
          <button className="btn-secondary" onClick={() => load()} disabled={loading}>
            <RefreshCw size={16} /> {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </header>

      {/* Filters: one row, scoping everything below. */}
      <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', marginBottom: 'var(--space-6)' }}>
        <select className="form-input" style={{ height: 36, width: 'auto' }} value={minutes} onChange={(e) => set({ window: e.target.value })} aria-label="Time window">
          {WINDOWS.map((w) => (
            <option key={w.minutes} value={w.minutes}>{w.label}</option>
          ))}
        </select>
        <select className="form-input" style={{ height: 36, width: 'auto', maxWidth: 260 }} value={company} onChange={(e) => set({ company: e.target.value })} aria-label="Company">
          <option value="">All companies</option>
          {companies.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <select className="form-input" style={{ height: 36, width: 'auto' }} value={type} onChange={(e) => set({ type: e.target.value })} aria-label="Message type">
          <option value="">All message types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</option>
          ))}
        </select>
      </div>

      {error && <p style={{ color: 'var(--error)', marginBottom: 'var(--space-4)' }}>{error}</p>}
      {!overview && !error && <p style={muted}>Loading…</p>}

      {overview && s && (
        <div style={{ opacity: loading ? 0.6 : 1, transition: 'opacity var(--transition-fast)' }}>
          {/* Headline numbers */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 'var(--space-4)' }}>
            <div className="card-dark">
              <div style={{ fontSize: '13px', color: 'var(--neutral-400)' }}>Typical reply time</div>
              <div style={{ fontSize: '48px', fontWeight: 600, lineHeight: 1.1, marginTop: 'var(--space-2)', color: 'var(--white)' }}>{fmtMs(s.p50_ms)}</div>
              <div style={{ fontSize: '12px', color: 'var(--neutral-400)', marginTop: 'var(--space-2)' }}>
                median · 9 in 10 within {fmtMs(s.p90_ms)}
              </div>
            </div>
            <Tile label="Slowest 5%" value={fmtMs(s.p95_ms)} note={`slowest of all ${fmtMs(s.max_ms)}`} />
            <Tile
              label="Messages"
              value={full(s.messages)}
              note={
                <>
                  {full(s.replied)} answered
                  {s.messages - s.replied > 0 && ` · ${full(s.messages - s.replied - s.failed)} waiting`}
                  {s.failed > 0 && <span style={{ color: 'var(--error)' }}> · {full(s.failed)} failed</span>}
                </>
              }
            />
            <Tile
              label="Tokens per AI message"
              value={compact(tokensPerAiMessage)}
              note={`${full(s.with_ai)} used the AI · ${full(s.no_ai)} quick replies`}
            />
            <Tile
              label="Tokens used"
              value={compact(s.input_tokens + s.output_tokens)}
              note={`${compact(s.input_tokens)} in (${cachedShare}% cached) · ${compact(s.output_tokens)} out`}
            />
            <Tile
              label="AI cost"
              value={inr(s.ai_cost_inr)}
              note={
                <>
                  {s.with_ai ? `${inr(String(Number(s.ai_cost_inr) / s.with_ai))} per AI message` : 'no AI calls'}
                  {s.unpriced > 0 && ` · ${s.unpriced} unpriced`}
                </>
              }
            />
          </div>

          {/* Reply time + speed bands */}
          <div className="replies-split">
            <div style={{ minWidth: 0 }}>
              <Panel
                title="Reply time"
                note={`Received → answered, per ${overview.step_minutes >= 1440 ? 'day' : overview.step_minutes >= 60 ? `${overview.step_minutes / 60} h` : `${overview.step_minutes} min`} (Indian time). A held photo includes the sender's wait.`}
                aside={<Legend line series={[{ key: 'p50', label: 'Typical (median)', color: SERIES.blue }, { key: 'p95', label: 'Slowest 5%', color: SERIES.orange }]} />}
              >
                <LineChart
                  labels={labels}
                  format={(v) => fmtMs(v)}
                  empty="No answered messages in this window."
                  series={[
                    { key: 'p50', label: 'Typical', color: SERIES.blue, values: overview.timeline.map((p) => p.p50_ms) },
                    { key: 'p95', label: 'Slowest 5%', color: SERIES.orange, values: overview.timeline.map((p) => p.p95_ms) },
                  ]}
                />
              </Panel>
            </div>
            <Panel title="Reply speed" note={`${full(s.replied)} answered messages`}>
              <BandBars
                color={SERIES.blue}
                bands={bandLabels(overview.bands_ms).map((label, i) => ({ label, count: s[`band_${i}`] ?? 0 }))}
              />
              <p style={{ ...muted, fontSize: '12px', marginTop: 'var(--space-4)', marginBottom: 0 }}>
                Average {fmtMs(s.avg_ms)}. Click <strong>Slowest</strong> in the feed below to see what took longest.
              </p>
            </Panel>
          </div>

          {/* Tokens over time + where they go */}
          <div className="replies-split">
            <div style={{ minWidth: 0 }}>
              <Panel
                title="Token usage"
                note="AI tokens for the messages received in each period."
                aside={
                  <Legend
                    series={[
                      { key: 'fresh', label: 'Input', color: SERIES.blue },
                      { key: 'cached', label: 'Cached input', color: SERIES.aqua },
                      { key: 'out', label: 'Output', color: SERIES.orange },
                    ]}
                  />
                }
              >
                <StackedColumns
                  labels={labels}
                  format={(v) => compact(v)}
                  empty="No AI tokens in this window."
                  series={[
                    { key: 'fresh', label: 'Input', color: SERIES.blue, values: overview.timeline.map((p) => p.input_tokens - p.cached_input_tokens) },
                    { key: 'cached', label: 'Cached input', color: SERIES.aqua, values: overview.timeline.map((p) => p.cached_input_tokens) },
                    { key: 'out', label: 'Output', color: SERIES.orange, values: overview.timeline.map((p) => p.output_tokens) },
                  ]}
                />
              </Panel>
            </div>
            <Panel title="Where the tokens go" note="By step of handling a message">
              {overview.by_step.length === 0 && <p style={muted}>No AI calls in this window.</p>}
              <div style={{ display: 'grid', gap: 12 }}>
                {overview.by_step.slice(0, 8).map((r) => {
                  const tokens = r.input_tokens + r.output_tokens;
                  return (
                    <div key={r.step} title={`${full(r.calls)} calls · avg ${fmtMs(r.avg_ms)} · ${inr(r.ai_cost_inr)}`}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', gap: 8 }}>
                        <span style={{ fontFamily: 'monospace', fontSize: '12px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.step}</span>
                        <span style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                          {compact(tokens)} <span style={muted}>· {full(r.calls)} calls</span>
                        </span>
                      </div>
                      <div style={{ height: 6, background: 'var(--neutral-100)', borderRadius: 3, marginTop: 4 }}>
                        <div style={{ width: `${(tokens / stepTotal) * 100}%`, minWidth: tokens ? 3 : 0, height: '100%', background: SERIES.blue, borderRadius: 3 }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </Panel>
          </div>

          {/* By model */}
          <section style={{ marginTop: 'var(--space-6)' }}>
            <h2 style={{ fontSize: '15px', marginBottom: 'var(--space-3)' }}>By model</h2>
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th style={num}>Calls</th>
                    <th style={num}>Avg time</th>
                    <th style={num}>Slowest 5%</th>
                    <th style={num}>Input</th>
                    <th style={num}>Cached</th>
                    <th style={num}>Output</th>
                    <th style={num}>Share</th>
                    <th style={num}>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.by_model.length === 0 && (
                    <tr>
                      <td colSpan={9} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>No AI calls in this window.</td>
                    </tr>
                  )}
                  {overview.by_model.map((r) => {
                    const share = modelTotal ? ((r.input_tokens + r.output_tokens) / modelTotal) * 100 : 0;
                    return (
                      <tr key={`${r.provider}-${r.model}`}>
                        <td style={{ fontSize: '13px' }}>
                          <span style={{ fontWeight: 500 }}>{r.model ?? '—'}</span> <span style={muted}>· {r.provider}</span>
                        </td>
                        <td style={num}>{full(r.calls)}</td>
                        <td style={num}>{fmtMs(r.avg_ms)}</td>
                        <td style={num}>{fmtMs(r.p95_ms)}</td>
                        <td style={num}>{full(r.input_tokens)}</td>
                        <td style={num}>{full(r.cached_input_tokens)}</td>
                        <td style={num}>{full(r.output_tokens)}</td>
                        <td style={{ ...num, width: 120 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}>
                            <div style={{ width: 56, height: 6, background: 'var(--neutral-100)', borderRadius: 3 }}>
                              <div style={{ width: `${share}%`, height: '100%', background: SERIES.blue, borderRadius: 3 }} />
                            </div>
                            {Math.round(share)}%
                          </div>
                        </td>
                        <td style={num}>
                          {inr(r.ai_cost_inr)}
                          {r.unpriced > 0 && <span style={muted} title="Calls with no price are not included"> +{r.unpriced}?</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* The feed */}
          <section style={{ marginTop: 'var(--space-8)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap', marginBottom: 'var(--space-3)' }}>
              <h2 style={{ fontSize: '15px', margin: 0 }}>
                Messages <span style={{ ...muted, fontWeight: 400 }}>· {full(feed?.total ?? 0)}</span>
              </h2>
              <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap' }}>
                <div role="tablist" style={{ display: 'inline-flex', border: '1px solid var(--border-default)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
                  {SORTS.map((o) => (
                    <button
                      key={o.key}
                      role="tab"
                      aria-selected={sort === o.key}
                      onClick={() => set({ sort: o.key === 'newest' ? null : o.key })}
                      style={{
                        border: 'none',
                        padding: '6px 12px',
                        fontSize: '13px',
                        cursor: 'pointer',
                        background: sort === o.key ? 'var(--dark)' : 'var(--surface-primary)',
                        color: sort === o.key ? 'var(--white)' : 'var(--neutral-700)',
                      }}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '13px', color: 'var(--neutral-700)', cursor: 'pointer' }}>
                  <input type="checkbox" checked={slowOnly} onChange={(e) => set({ slow: e.target.checked ? '1' : null })} />
                  Only {SLOW_MS / 1000} s or slower
                </label>
              </div>
            </div>
            <div className="table-container">
              <ReplyFeed items={feed?.items ?? []} />
            </div>
            {feed && feed.total > PAGE && (
              <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 'var(--space-3)', marginTop: 'var(--space-3)', fontSize: '13px' }}>
                <span style={muted}>
                  {page * PAGE + 1}–{Math.min(feed.total, (page + 1) * PAGE)} of {full(feed.total)}
                </span>
                <button className="btn-secondary" disabled={page === 0} onClick={() => set({ page: String(page - 1) })} aria-label="Previous page">
                  <ChevronLeft size={16} />
                </button>
                <button className="btn-secondary" disabled={page + 1 >= pages} onClick={() => set({ page: String(page + 1) })} aria-label="Next page">
                  <ChevronRight size={16} />
                </button>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
