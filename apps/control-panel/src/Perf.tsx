import { Fragment, useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from './api';

interface StageSummaryEntry {
  stage: string;
  n: number;
  failures: number;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
}

interface ProviderSummaryEntry {
  stage: string;
  provider: string;
  operation: string;
  model: string | null;
  n: number;
  failures: number;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
}

interface WallTimeSummaryEntry {
  message_type: string;
  n: number;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
}

interface PerfSummary {
  since: string;
  stages: StageSummaryEntry[];
  providers: ProviderSummaryEntry[];
  wall_times: WallTimeSummaryEntry[];
}

interface WorstOffenderEntry {
  correlation_id: string;
  message_type: string;
  received_at: string;
  processed_at: string | null;
  wall_ms: number | null;
}

interface PrepipelineEntry {
  correlation_id: string;
  stage_payload: Record<string, number> | null;
  duration_ms: number | null;
  succeeded: boolean;
  created_at: string;
}

const WINDOW_OPTIONS = [
  { label: 'Last hour', minutes: 60 },
  { label: 'Last 2 hours', minutes: 120 },
  { label: 'Last 6 hours', minutes: 360 },
  { label: 'Last 24 hours', minutes: 1440 },
  { label: 'Last 7 days', minutes: 10080 },
];

const fmtMs = (ms: number | null | undefined): string => {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
};

// Below this, a stage/operation isn't worth visually flagging -- keeps the
// coloring meaningful (a real outlier, not every row past a few hundred ms).
const SLOW_MS = 3000;
const WARN_MS = 1000;

const severityColor = (ms: number | null | undefined): string => {
  if (ms === null || ms === undefined) return 'var(--neutral-500)';
  if (ms >= SLOW_MS) return 'var(--error)';
  if (ms >= WARN_MS) return 'var(--warning, #b45309)';
  return 'var(--neutral-700, var(--neutral-800))';
};

function Th({ children, align }: { children: React.ReactNode; align?: 'right' }) {
  return (
    <th style={align === 'right' ? { textAlign: 'right' } : undefined}>{children}</th>
  );
}

function MsCell({ ms }: { ms: number | null | undefined }) {
  return (
    <td style={{ textAlign: 'right', fontSize: '13px', color: severityColor(ms) }}>{fmtMs(ms)}</td>
  );
}

export default function Perf() {
  const [windowMinutes, setWindowMinutes] = useState(120);
  const [summary, setSummary] = useState<PerfSummary | null>(null);
  const [worst, setWorst] = useState<WorstOffenderEntry[]>([]);
  const [prepipeline, setPrepipeline] = useState<PrepipelineEntry[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((minutes: number, isRefresh: boolean) => {
    if (isRefresh) setRefreshing(true);
    setError(null);
    return Promise.all([
      api.get<PerfSummary>('/admin/perf/summary', { params: { since_minutes: minutes } }),
      api.get<WorstOffenderEntry[]>('/admin/perf/worst', {
        params: { since_minutes: minutes, limit: 15 },
      }),
      api.get<PrepipelineEntry[]>('/admin/perf/prepipeline', {
        params: { since_minutes: minutes, limit: 15 },
      }),
    ])
      .then(([summaryRes, worstRes, prepipelineRes]) => {
        setSummary(summaryRes.data);
        setWorst(worstRes.data);
        setPrepipeline(prepipelineRes.data);
      })
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load performance data'))
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  }, []);

  useEffect(() => {
    setLoading(true);
    load(windowMinutes, false);
  }, [windowMinutes, load]);

  if (loading) {
    return (
      <div className="animate-fade-in" style={{ maxWidth: '1200px', color: 'var(--neutral-500)' }}>
        Loading…
      </div>
    );
  }

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1200px' }}>
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          marginBottom: 'var(--space-6)',
          gap: 'var(--space-4)',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1>Performance</h1>
          <p className="subtitle">
            Where WhatsApp replies actually spend their time -- pipeline stages, AI provider
            calls, and wall-clock, by modality.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
          <select
            className="form-input"
            value={windowMinutes}
            onChange={(e) => setWindowMinutes(Number(e.target.value))}
            style={{ height: '36px' }}
          >
            {WINDOW_OPTIONS.map((opt) => (
              <option key={opt.minutes} value={opt.minutes}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            className="btn-secondary"
            onClick={() => load(windowMinutes, true)}
            disabled={refreshing}
          >
            <RefreshCw size={16} /> {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </header>

      {error && <p style={{ color: 'var(--error)', marginBottom: 'var(--space-4)' }}>{error}</p>}

      {/* Wall-clock by modality */}
      <section style={{ marginBottom: 'var(--space-6)' }}>
        <h2 style={{ fontSize: '15px', marginBottom: 'var(--space-3)' }}>Total reply time, by message type</h2>
        <p style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: '-8px', marginBottom: 'var(--space-3)' }}>
          received_at → processed_at. An image's number can include however long the sender took
          to answer "what is this photo for?", not just processing -- read alongside the stage
          breakdown below, not instead of it.
        </p>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <Th align="right">Count</Th>
                <Th align="right">Avg</Th>
                <Th align="right">p50</Th>
                <Th align="right">p95</Th>
                <Th align="right">Max</Th>
              </tr>
            </thead>
            <tbody>
              {summary?.wall_times.length ? (
                summary.wall_times.map((row) => (
                  <tr key={row.message_type}>
                    <td style={{ fontSize: '13px', textTransform: 'capitalize' }}>{row.message_type}</td>
                    <td style={{ textAlign: 'right', fontSize: '13px' }}>{row.n}</td>
                    <MsCell ms={row.avg_ms} />
                    <MsCell ms={row.p50_ms} />
                    <MsCell ms={row.p95_ms} />
                    <MsCell ms={row.max_ms} />
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>
                    No completed messages in this window.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Pipeline stage breakdown */}
      <section style={{ marginBottom: 'var(--space-6)' }}>
        <h2 style={{ fontSize: '15px', marginBottom: 'var(--space-3)' }}>Pipeline stages</h2>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Stage</th>
                <Th align="right">Count</Th>
                <Th align="right">Failures</Th>
                <Th align="right">Avg</Th>
                <Th align="right">p50</Th>
                <Th align="right">p95</Th>
                <Th align="right">Max</Th>
              </tr>
            </thead>
            <tbody>
              {summary?.stages.length ? (
                summary.stages.map((row) => (
                  <tr key={row.stage}>
                    <td style={{ fontSize: '13px', fontFamily: 'monospace' }}>{row.stage}</td>
                    <td style={{ textAlign: 'right', fontSize: '13px' }}>{row.n}</td>
                    <td
                      style={{
                        textAlign: 'right',
                        fontSize: '13px',
                        color: row.failures > 0 ? 'var(--error)' : 'var(--neutral-500)',
                      }}
                    >
                      {row.failures}
                    </td>
                    <MsCell ms={row.avg_ms} />
                    <MsCell ms={row.p50_ms} />
                    <MsCell ms={row.p95_ms} />
                    <MsCell ms={row.max_ms} />
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>
                    No stage traces in this window.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Provider call breakdown */}
      <section style={{ marginBottom: 'var(--space-6)' }}>
        <h2 style={{ fontSize: '15px', marginBottom: 'var(--space-3)' }}>AI provider calls</h2>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Stage</th>
                <th>Provider</th>
                <th>Operation</th>
                <th>Model</th>
                <Th align="right">Count</Th>
                <Th align="right">Failures</Th>
                <Th align="right">Avg</Th>
                <Th align="right">p50</Th>
                <Th align="right">p95</Th>
                <Th align="right">Max</Th>
              </tr>
            </thead>
            <tbody>
              {summary?.providers.length ? (
                summary.providers.map((row) => (
                  <tr key={`${row.stage}-${row.provider}-${row.operation}-${row.model ?? ''}`}>
                    <td style={{ fontSize: '13px', fontFamily: 'monospace' }}>{row.stage}</td>
                    <td style={{ fontSize: '13px' }}>{row.provider}</td>
                    <td style={{ fontSize: '13px', fontFamily: 'monospace' }}>{row.operation}</td>
                    <td style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>{row.model ?? '—'}</td>
                    <td style={{ textAlign: 'right', fontSize: '13px' }}>{row.n}</td>
                    <td
                      style={{
                        textAlign: 'right',
                        fontSize: '13px',
                        color: row.failures > 0 ? 'var(--error)' : 'var(--neutral-500)',
                      }}
                    >
                      {row.failures}
                    </td>
                    <MsCell ms={row.avg_ms} />
                    <MsCell ms={row.p50_ms} />
                    <MsCell ms={row.p95_ms} />
                    <MsCell ms={row.max_ms} />
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={10} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>
                    No provider calls in this window.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Worst offenders */}
      <section style={{ marginBottom: 'var(--space-6)' }}>
        <h2 style={{ fontSize: '15px', marginBottom: 'var(--space-3)' }}>Slowest messages</h2>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Received</th>
                <th>Type</th>
                <th>Correlation ID</th>
                <Th align="right">Wall time</Th>
              </tr>
            </thead>
            <tbody>
              {worst.length ? (
                worst.map((row) => (
                  <tr key={row.correlation_id}>
                    <td style={{ fontSize: '13px', whiteSpace: 'nowrap' }}>
                      {new Date(row.received_at).toLocaleString()}
                    </td>
                    <td style={{ fontSize: '13px', textTransform: 'capitalize' }}>{row.message_type}</td>
                    <td style={{ fontSize: '12px', fontFamily: 'monospace', color: 'var(--neutral-500)' }}>
                      {row.correlation_id}
                    </td>
                    <MsCell ms={row.wall_ms} />
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>
                    No completed messages in this window.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Prepipeline step ranking */}
      <section style={{ marginBottom: 'var(--space-6)' }}>
        <h2 style={{ fontSize: '15px', marginBottom: 'var(--space-3)' }}>
          Pre-understanding steps, per message
        </h2>
        <p style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: '-8px', marginBottom: 'var(--space-3)' }}>
          Everything that runs before the AI call -- fast-path checks, DB lookups, resumes.
          <code>_unaccounted_ms</code> is wall time no named step claimed; a large value there
          means the cost is somewhere not yet instrumented. Click a row to see every step.
        </p>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Correlation ID</th>
                <Th align="right">Total</Th>
                <Th align="right">Worst step</Th>
              </tr>
            </thead>
            <tbody>
              {prepipeline.length ? (
                prepipeline.map((row) => {
                  const steps = row.stage_payload ?? {};
                  const [worstStepName, worstStepMs] =
                    Object.entries(steps).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))[0] ?? [null, null];
                  const isOpen = expanded === row.correlation_id;
                  return (
                    <Fragment key={row.correlation_id}>
                      <tr
                        style={{ cursor: 'pointer' }}
                        onClick={() => setExpanded(isOpen ? null : row.correlation_id)}
                      >
                        <td style={{ fontSize: '13px', whiteSpace: 'nowrap' }}>
                          {new Date(row.created_at).toLocaleString()}
                        </td>
                        <td style={{ fontSize: '12px', fontFamily: 'monospace', color: 'var(--neutral-500)' }}>
                          {row.correlation_id}
                        </td>
                        <MsCell ms={row.duration_ms} />
                        <td style={{ textAlign: 'right', fontSize: '12px', fontFamily: 'monospace' }}>
                          {worstStepName ? `${worstStepName} (${fmtMs(worstStepMs)})` : '—'}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td colSpan={4} style={{ background: 'var(--neutral-50, #fafafa)' }}>
                            <div
                              style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fill, minmax(min(180px, 100%), 1fr))',
                                gap: 'var(--space-2)',
                                padding: 'var(--space-3) 0',
                              }}
                            >
                              {Object.entries(steps)
                                .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
                                .map(([name, ms]) => (
                                  <div key={name} style={{ fontSize: '12px' }}>
                                    <span style={{ fontFamily: 'monospace', color: 'var(--neutral-500)' }}>
                                      {name}
                                    </span>
                                    <span style={{ float: 'right', color: severityColor(ms) }}>
                                      {fmtMs(ms)}
                                    </span>
                                  </div>
                                ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={4} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>
                    No prepipeline traces in this window.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
