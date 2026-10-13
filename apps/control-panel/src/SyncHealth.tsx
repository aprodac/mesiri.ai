import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock, RefreshCw } from 'lucide-react';
import { api } from './api';

interface ReconcileRun {
  id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  counts: Record<string, number> | null;
  error_count: number;
  errors: string[] | null;
  trigger: string;
}

interface ReconcileStatus {
  enabled: boolean;
  interval_seconds: number;
  last_run: ReconcileRun | null;
  needs_attention: boolean;
  recent_runs: ReconcileRun[];
}

interface ShadowMismatch {
  port: string;
  method: string;
  args: Record<string, unknown>;
  context_result: unknown;
  main_result: unknown;
  hits: number;
  first_seen_at: string;
  last_seen_at: string;
}

interface ShadowStatus {
  identity_source: string;
  mismatches: ShadowMismatch[];
}

const SOURCE_LABEL: Record<string, string> = {
  context: 'WhatsApp copy only',
  shadow: 'WhatsApp copy, checked against the main tables',
  main: 'Main tables',
};

// BE-01: before WhatsApp stops reading its own copy of people, projects and
// sites, both are asked the same questions side by side. An empty list after
// a few days of real messages means the switch is safe.
function IdentityShadow() {
  const [shadow, setShadow] = useState<ShadowStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ShadowStatus>('/admin/reconcile/shadow')
      .then((res) => setShadow(res.data))
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load the comparison'));
  }, []);

  if (error) return <p style={{ color: 'var(--error)' }}>{error}</p>;
  if (!shadow) return null;

  const clean = shadow.mismatches.length === 0;
  return (
    <div style={{ marginTop: 'var(--space-8)' }}>
      <h2 style={{ fontSize: '18px', marginBottom: 'var(--space-2)' }}>
        WhatsApp copy vs main tables
      </h2>
      <p className="subtitle" style={{ marginBottom: 'var(--space-4)' }}>
        Reading from: {SOURCE_LABEL[shadow.identity_source] || shadow.identity_source}.{' '}
        {shadow.identity_source === 'shadow' &&
          (clean
            ? 'No differences so far.'
            : `${shadow.mismatches.length} question${shadow.mismatches.length === 1 ? '' : 's'} answered differently.`)}
      </p>
      {!clean && (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Last seen</th>
                <th>Lookup</th>
                <th>Times</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {shadow.mismatches.map((m, i) => (
                <tr key={i}>
                  <td style={{ fontSize: '13px', whiteSpace: 'nowrap' }}>
                    {new Date(m.last_seen_at).toLocaleString()}
                  </td>
                  <td style={{ fontSize: '13px' }}>
                    {m.port}.{m.method}
                  </td>
                  <td style={{ fontSize: '13px' }}>{m.hits}</td>
                  <td style={{ fontSize: '12px' }}>
                    <details>
                      <summary style={{ cursor: 'pointer' }}>Show</summary>
                      <pre style={{ fontSize: '11px', whiteSpace: 'pre-wrap', margin: '8px 0 0' }}>
                        {JSON.stringify(
                          { asked: m.args, copy: m.context_result, main: m.main_result },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  succeeded: 'Healthy',
  completed_with_errors: 'Completed with errors',
  failed: 'Failed',
};

const statusBadge = (status: string) => {
  if (status === 'succeeded') return 'badge-success';
  if (status === 'completed_with_errors') return 'badge-warning';
  return 'badge-error';
};

const formatDuration = (ms: number | null) => {
  if (ms === null) return '—';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
};

const formatInterval = (seconds: number) => {
  if (seconds % 3600 === 0) return `${seconds / 3600} hour${seconds === 3600 ? '' : 's'}`;
  if (seconds % 60 === 0) return `${seconds / 60} minutes`;
  return `${seconds} seconds`;
};

const countsSummary = (counts: Record<string, number> | null) => {
  if (!counts) return '—';
  const parts = Object.entries(counts)
    .filter(([, v]) => typeof v === 'number')
    .map(([k, v]) => `${k} ${v}`);
  return parts.length ? parts.join(' · ') : '—';
};

export default function SyncHealth() {
  const [status, setStatus] = useState<ReconcileStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    return api
      .get<ReconcileStatus>('/admin/reconcile')
      .then((res) => {
        setStatus(res.data);
        setError(null);
      })
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load sync health'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runNow = () => {
    setRunning(true);
    setError(null);
    api
      .post('/admin/reconcile/run')
      .then(() => load())
      .catch((err) => setError(err.response?.data?.detail || 'Failed to run sync check'))
      .finally(() => setRunning(false));
  };

  if (loading) {
    return (
      <div className="animate-fade-in" style={{ maxWidth: '1200px', color: 'var(--neutral-500)' }}>
        Loading…
      </div>
    );
  }

  const neverRun = status !== null && status.last_run === null;

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1200px' }}>
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          marginBottom: 'var(--space-6)',
        }}
      >
        <div>
          <h1>Sync Health</h1>
          <p className="subtitle">
            Keeps WhatsApp in step with project and site assignments made on the dashboard.
          </p>
        </div>
        <button className="btn-secondary" onClick={runNow} disabled={running}>
          <RefreshCw size={16} /> {running ? 'Running…' : 'Run check now'}
        </button>
      </header>

      {error && <p style={{ color: 'var(--error)', marginBottom: 'var(--space-4)' }}>{error}</p>}

      {status && (
        <div
          className="card"
          style={{
            marginBottom: 'var(--space-6)',
            borderLeft: `3px solid ${
              neverRun
                ? 'var(--neutral-400)'
                : status.needs_attention
                  ? 'var(--error)'
                  : 'var(--success)'
            }`,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            {neverRun ? (
              <Clock size={20} style={{ color: 'var(--neutral-500)' }} />
            ) : status.needs_attention ? (
              <AlertTriangle size={20} style={{ color: 'var(--error)' }} />
            ) : (
              <CheckCircle2 size={20} style={{ color: 'var(--success)' }} />
            )}
            <div>
              <div style={{ fontSize: '15px', fontWeight: 500 }}>
                {neverRun
                  ? 'Waiting for the first check'
                  : status.needs_attention
                    ? 'Needs attention'
                    : 'Everything in sync'}
              </div>
              <div style={{ fontSize: '13px', color: 'var(--neutral-500)' }}>
                {!status.enabled
                  ? 'Automatic checking is switched off.'
                  : neverRun
                    ? `No check has completed yet. Runs every ${formatInterval(status.interval_seconds)}.`
                    : status.needs_attention
                      ? 'The most recent check did not finish cleanly — see the runs below.'
                      : `Last checked ${new Date(status.last_run!.started_at).toLocaleString()}.`}
              </div>
            </div>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              gap: 'var(--space-4)',
              marginTop: 'var(--space-4)',
              paddingTop: 'var(--space-4)',
              borderTop: '1px solid var(--border-strong)',
            }}
          >
            <div>
              <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Automatic checking</div>
              <div style={{ fontSize: '13px' }}>{status.enabled ? 'On' : 'Off'}</div>
            </div>
            <div>
              <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Runs every</div>
              <div style={{ fontSize: '13px' }}>{formatInterval(status.interval_seconds)}</div>
            </div>
            <div>
              <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Last run took</div>
              <div style={{ fontSize: '13px' }}>
                {status.last_run ? formatDuration(status.last_run.duration_ms) : '—'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Problems found</div>
              <div style={{ fontSize: '13px' }}>
                {status.last_run ? status.last_run.error_count : '—'}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Result</th>
              <th>Took</th>
              <th>Trigger</th>
              <th>Synced</th>
              <th>Problems</th>
            </tr>
          </thead>
          <tbody>
            {!status || status.recent_runs.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>
                  No checks recorded yet.
                </td>
              </tr>
            ) : (
              status.recent_runs.map((run) => (
                <tr key={run.id}>
                  <td style={{ fontSize: '13px', whiteSpace: 'nowrap' }}>
                    {new Date(run.started_at).toLocaleString()}
                  </td>
                  <td>
                    <span className={`badge ${statusBadge(run.status)}`}>
                      {STATUS_LABEL[run.status] || run.status}
                    </span>
                  </td>
                  <td style={{ fontSize: '13px' }}>{formatDuration(run.duration_ms)}</td>
                  <td style={{ fontSize: '13px', color: 'var(--neutral-500)' }}>
                    {run.trigger === 'manual' ? 'Manual' : 'Automatic'}
                  </td>
                  <td style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>
                    {countsSummary(run.counts)}
                  </td>
                  <td style={{ fontSize: '12px' }}>
                    {run.error_count === 0 ? (
                      <span style={{ color: 'var(--neutral-500)' }}>None</span>
                    ) : (
                      <details>
                        <summary style={{ cursor: 'pointer', color: 'var(--error)' }}>
                          {run.error_count} problem{run.error_count === 1 ? '' : 's'}
                        </summary>
                        <ul style={{ margin: '8px 0 0 16px', padding: 0 }}>
                          {(run.errors || []).map((e, i) => (
                            <li key={i} style={{ fontFamily: 'monospace', fontSize: '11px' }}>
                              {e}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <IdentityShadow />
    </div>
  );
}
