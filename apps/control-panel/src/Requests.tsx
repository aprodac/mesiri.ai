import { Fragment, useEffect, useMemo, useState } from 'react';
import { api } from './api';
import { getErrorMessage } from './Toast';

// TM-19: everything people asked Mesiri for (and the team asked the bot for), and what happened
// to each: asked, waiting for an ok, building, live, verified, broken, dropped. Who asked, the
// commit, the live check and whether the person used Mesiri again after it went live.
// Read from the team bot's request log through /admin/requests (platform admins only).

type Stage = 'asked' | 'waiting' | 'building' | 'live' | 'verified' | 'broken' | 'dropped';

interface RequestItem {
  id: number;
  title: string;
  type: string;
  summary: string | null;
  stage: Stage;
  status: string;
  chat_name: string | null;
  created_by: string | null;
  asked_by: string | null;
  held: string | null;
  done_ref: string | null;
  live_at: string | null;
  verified: 'ok' | 'broken' | null;
  verified_at: string | null;
  tried_at: string | null;
  created_at: string;
  updated_at: string;
}

interface Counts extends Record<Stage, number> {
  total: number;
  from_users: number;
  shipped: number;
  open: number;
  tried: number;
}

/** TM-23: how fast and how well the loop works (from the request log and the testers' own taps). */
interface Loop {
  shipped_from_users: number;
  hours_to_live_median: number | null;
  hours_to_live_p90: number | null;
  live_checked: number;
  live_check_ok: number;
  verdicts: { works: number; still_wrong: number; days: number } | null;
}

const hours = (h: number | null) => (h == null ? '—' : h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${h.toFixed(1)} h` : `${(h / 24).toFixed(1)} days`);

interface LogEntry {
  at: string;
  status: string | null;
  ref: string | null;
  note: string | null;
}

const STAGES: Record<Stage, [string, string]> = {
  asked: ['Asked', 'badge-info'],
  waiting: ['Waiting for ok', 'badge-warning'],
  building: ['Building', 'badge-warning'],
  live: ['Live', 'badge-success'],
  verified: ['Verified live', 'badge-success'],
  broken: ['Broken', 'badge-error'],
  dropped: ['Dropped', 'badge-info'],
};

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '—';
}

const muted = { fontSize: '13px', color: 'var(--neutral-600)' };

export default function Requests() {
  const [items, setItems] = useState<RequestItem[] | null>(null);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [loop, setLoop] = useState<Loop | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage | 'all' | 'open' | 'shipped'>('all');
  const [usersOnly, setUsersOnly] = useState(false);
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<number | null>(null);
  const [log, setLog] = useState<Record<number, LogEntry[] | string>>({});

  useEffect(() => {
    api
      .get<{ counts: Counts; loop?: Loop; items: RequestItem[] }>('/admin/requests')
      .then((res) => {
        setItems(res.data.items);
        setCounts(res.data.counts);
        setLoop(res.data.loop ?? null);
      })
      .catch((err) => setError(getErrorMessage(err, 'Could not load the requests')));
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (items ?? []).filter((i) => {
      if (usersOnly && !i.asked_by) return false;
      if (stage === 'open' && !['asked', 'waiting', 'building'].includes(i.stage)) return false;
      if (stage === 'shipped' && !['live', 'verified', 'broken'].includes(i.stage)) return false;
      if (stage !== 'all' && stage !== 'open' && stage !== 'shipped' && i.stage !== stage) return false;
      return !q || `${i.id} ${i.title} ${i.asked_by ?? ''} ${i.created_by ?? ''}`.toLowerCase().includes(q);
    });
  }, [items, stage, usersOnly, query]);

  const toggle = (id: number) => {
    setOpen(open === id ? null : id);
    if (log[id]) return;
    api
      .get<{ log: LogEntry[] }>(`/admin/requests/${id}`)
      .then((res) => setLog((l) => ({ ...l, [id]: res.data.log })))
      .catch((err) => setLog((l) => ({ ...l, [id]: getErrorMessage(err, 'Could not load the history') })));
  };

  const kpis: [string, number | undefined, string, typeof stage][] = [
    ['All requests', counts?.total, counts ? `${counts.from_users} from users` : '', 'all'],
    ['Open', counts?.open, counts ? `${counts.building} building · ${counts.waiting} waiting for ok` : '', 'open'],
    ['Shipped', counts?.shipped, counts ? `${counts.tried} used again by who asked` : '', 'shipped'],
    ['Verified live', counts?.verified, 'the bot re-tested it after deploy', 'verified'],
    ['Broken', counts?.broken, 'failed the live check', 'broken'],
  ];

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1200px' }}>
      <header style={{ marginBottom: 'var(--space-6)' }}>
        <h1>Requests</h1>
        <p className="subtitle">
          What people asked Mesiri for and what the team asked the bot for, from asking to verified live. In WhatsApp: <code>@bot requests</code>.
        </p>
      </header>

      <div className="kpis" style={{ marginBottom: 'var(--space-5)' }}>
        {kpis.map(([label, value, sub, key]) => (
          <button
            key={label}
            type="button"
            className="kpi"
            onClick={() => setStage(stage === key ? 'all' : key)}
            style={{ border: 'none', textAlign: 'left', cursor: 'pointer', background: stage === key && key !== 'all' ? 'var(--neutral-50)' : undefined }}
          >
            <span className="kpi-label">
              {key === 'broken' && <span className={`kpi-dot ${value ? 'critical' : 'good'}`} />}
              {label}
            </span>
            <span className="kpi-row"><span className="kpi-value">{value ?? '—'}</span></span>
            <span className="kpi-compare">{sub}</span>
          </button>
        ))}
      </div>

      {loop && (
        <div className="kpis" style={{ marginBottom: 'var(--space-5)' }} aria-label="How the loop is doing">
          <div className="kpi">
            <span className="kpi-label">Asked → live (median)</span>
            <span className="kpi-row"><span className="kpi-value">{hours(loop.hours_to_live_median)}</span></span>
            <span className="kpi-compare">slowest tenth {hours(loop.hours_to_live_p90)} · {loop.shipped_from_users} shipped for users</span>
          </div>
          <div className="kpi">
            <span className="kpi-label">Live check passed</span>
            <span className="kpi-row"><span className="kpi-value">{loop.live_checked ? `${loop.live_check_ok} / ${loop.live_checked}` : '—'}</span></span>
            <span className="kpi-compare">the bot re-sent what was asked after deploy</span>
          </div>
          <div className="kpi">
            <span className="kpi-label">
              {loop.verdicts && <span className={`kpi-dot ${loop.verdicts.still_wrong ? 'critical' : 'good'}`} />}
              Testers said
            </span>
            <span className="kpi-row">
              <span className="kpi-value">{loop.verdicts ? `${loop.verdicts.works} ✅ · ${loop.verdicts.still_wrong} ❌` : '—'}</span>
            </span>
            <span className="kpi-compare">
              {loop.verdicts ? `Works / Still wrong taps, last ${loop.verdicts.days} days` : 'taps could not be read'}
            </span>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
        <input
          className="form-input"
          placeholder="Search number, title or person"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ maxWidth: '280px' }}
        />
        <select className="form-input" value={stage} onChange={(e) => setStage(e.target.value as typeof stage)} style={{ maxWidth: '200px' }}>
          <option value="all">Every stage</option>
          <option value="open">Open (not live yet)</option>
          <option value="shipped">Shipped</option>
          {(Object.keys(STAGES) as Stage[]).map((s) => (
            <option key={s} value={s}>{STAGES[s][0]}{counts ? ` (${counts[s]})` : ''}</option>
          ))}
        </select>
        <label style={{ ...muted, display: 'flex', gap: '6px', alignItems: 'center' }}>
          <input type="checkbox" checked={usersOnly} onChange={(e) => setUsersOnly(e.target.checked)} />
          Asked by users only
        </label>
        {items && <span style={muted}>{shown.length} shown</span>}
      </div>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th style={{ width: '48px' }}>#</th>
              <th>Request</th>
              <th>Asked by</th>
              <th>Stage</th>
              <th>Live check</th>
              <th>Used again</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {error && <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--error)' }}>{error}</td></tr>}
            {!error && !items && <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Loading…</td></tr>}
            {items && shown.length === 0 && (
              <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Nothing here.</td></tr>
            )}
            {shown.map((i) => {
              const [label, badge] = STAGES[i.stage] ?? STAGES.asked;
              const entries = log[i.id];
              return (
                <Fragment key={i.id}>
                  <tr onClick={() => toggle(i.id)} style={{ cursor: 'pointer' }}>
                    <td style={muted}>{i.id}</td>
                    <td>
                      <div style={{ fontWeight: 500, color: 'var(--neutral-900)' }}>{i.title}</div>
                      <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>
                        {i.type}{i.done_ref ? ` · commit ${i.done_ref}` : ''}{i.held && i.stage === 'waiting' ? ` · held: ${i.held}` : ''}
                      </div>
                    </td>
                    <td style={muted}>{i.asked_by ?? <span style={{ color: 'var(--neutral-400)' }}>{i.created_by ?? i.chat_name ?? '—'}</span>}</td>
                    <td><span className={`badge ${badge}`}>{label}</span></td>
                    <td style={muted}>{i.verified === 'ok' ? `✅ ${when(i.verified_at)}` : i.verified === 'broken' ? `❌ ${when(i.verified_at)}` : i.live_at ? 'pending' : '—'}</td>
                    <td style={muted}>{i.tried_at ? `✓ ${when(i.tried_at)}` : i.live_at && i.asked_by ? 'not yet' : '—'}</td>
                    <td style={muted}>{when(i.updated_at)}</td>
                  </tr>
                  {open === i.id && (
                    <tr>
                      <td />
                      <td colSpan={6} style={{ background: 'var(--neutral-50)' }}>
                        {i.summary && <p style={{ ...muted, whiteSpace: 'pre-wrap', marginBottom: '8px' }}>{i.summary.slice(0, 1200)}</p>}
                        {!entries && <span style={muted}>Loading history…</span>}
                        {typeof entries === 'string' && <span style={{ color: 'var(--error)' }}>{entries}</span>}
                        {Array.isArray(entries) && (
                          <ul style={{ ...muted, margin: 0, paddingLeft: '18px' }}>
                            {entries.map((e, n) => (
                              <li key={n}>
                                {when(e.at)} · {[e.status, e.ref && `commit ${e.ref}`, e.note].filter(Boolean).join(' · ')}
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
