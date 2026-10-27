import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, XCircle } from 'lucide-react';
import { api } from './api';

interface QueueHealth {
  queue_enabled: boolean;
  health_check_interval_seconds: number;
  worker_alive: boolean;
  jobs_complete: number | null;
  jobs_failed: number | null;
  jobs_retried: number | null;
  jobs_ongoing: number | null;
  queue_depth: number | null;
  raw_status: string | null;
}

// The worker updates its health-check key every health_check_interval
// seconds; polling faster than that would just show the same value.
const POLL_MS = 15_000;

export default function QueueHealth() {
  const [health, setHealth] = useState<QueueHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(() => {
    return api
      .get<QueueHealth>('/admin/queue/health')
      .then((res) => {
        setHealth(res.data);
        setError(null);
        setLastChecked(new Date());
      })
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load queue health'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    pollRef.current = setInterval(load, POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [load]);

  if (loading) {
    return (
      <div className="animate-fade-in" style={{ maxWidth: '900px', color: 'var(--neutral-500)' }}>
        Loading…
      </div>
    );
  }

  const notWired = health !== null && !health.queue_enabled;
  const down = health !== null && health.queue_enabled && !health.worker_alive;
  const up = health !== null && health.queue_enabled && health.worker_alive;

  const statusColor = notWired ? 'var(--neutral-400)' : down ? 'var(--error)' : 'var(--success)';

  return (
    <div className="animate-fade-in" style={{ maxWidth: '900px' }}>
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          marginBottom: 'var(--space-6)',
        }}
      >
        <div>
          <h1>Queue Health</h1>
          <p className="subtitle">
            Whether the ARQ worker is actually consuming WhatsApp messages from Redis — no SSH
            required.
          </p>
        </div>
        <button className="btn-secondary" onClick={load}>
          <RefreshCw size={16} /> Refresh
        </button>
      </header>

      {error && <p style={{ color: 'var(--error)', marginBottom: 'var(--space-4)' }}>{error}</p>}

      {health && (
        <div className="card" style={{ marginBottom: 'var(--space-6)', borderLeft: `3px solid ${statusColor}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            {notWired ? (
              <AlertTriangle size={20} style={{ color: 'var(--neutral-500)' }} />
            ) : down ? (
              <XCircle size={20} style={{ color: 'var(--error)' }} />
            ) : (
              <CheckCircle2 size={20} style={{ color: 'var(--success)' }} />
            )}
            <div>
              <div style={{ fontSize: '15px', fontWeight: 500 }}>
                {notWired
                  ? 'Durable queue not enabled on this environment'
                  : down
                    ? 'Worker not responding'
                    : 'Worker is alive and consuming the queue'}
              </div>
              <div style={{ fontSize: '13px', color: 'var(--neutral-500)' }}>
                {notWired
                  ? 'This environment runs without a real Redis (dev/test) — messages are handled in-process, not queued.'
                  : down
                    ? `No health-check update from mesiri-worker in the last ${health.health_check_interval_seconds}s. Messages are queuing in Redis but nobody is processing them — same failure mode as the original incident.`
                    : `Last confirmed alive ${lastChecked ? lastChecked.toLocaleTimeString() : '—'}. Refreshes every ${POLL_MS / 1000}s.`}
              </div>
            </div>
          </div>

          {up && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(min(140px, 100%), 1fr))',
                gap: 'var(--space-4)',
                marginTop: 'var(--space-4)',
                paddingTop: 'var(--space-4)',
                borderTop: '1px solid var(--border-strong)',
              }}
            >
              <div>
                <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Queue depth</div>
                <div style={{ fontSize: '18px', fontWeight: 600 }}>{health.queue_depth ?? '—'}</div>
              </div>
              <div>
                <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>In progress</div>
                <div style={{ fontSize: '18px', fontWeight: 600 }}>{health.jobs_ongoing ?? '—'}</div>
              </div>
              <div>
                <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Completed</div>
                <div style={{ fontSize: '18px', fontWeight: 600 }}>{health.jobs_complete ?? '—'}</div>
              </div>
              <div>
                <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Retried</div>
                <div style={{ fontSize: '18px', fontWeight: 600 }}>{health.jobs_retried ?? '—'}</div>
              </div>
              <div>
                <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Failed</div>
                <div
                  style={{
                    fontSize: '18px',
                    fontWeight: 600,
                    color: (health.jobs_failed ?? 0) > 0 ? 'var(--error)' : undefined,
                  }}
                >
                  {health.jobs_failed ?? '—'}
                </div>
              </div>
            </div>
          )}

          {health.raw_status && (
            <div
              style={{
                marginTop: 'var(--space-4)',
                paddingTop: 'var(--space-3)',
                borderTop: '1px solid var(--border-strong)',
                fontFamily: 'monospace',
                fontSize: '11px',
                color: 'var(--neutral-500)',
              }}
            >
              {health.raw_status}
            </div>
          )}
        </div>
      )}

      <p style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>
        A "queue depth" that keeps climbing with jobs never completing usually means the worker
        crashed mid-batch — check <code>journalctl -u mesiri-worker</code> on the VPS for the
        underlying error; this page can tell you something is wrong, not why.
      </p>
    </div>
  );
}
