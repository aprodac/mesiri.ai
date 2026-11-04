import { Fragment, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from './api';
import { getErrorMessage } from './Toast';

// TM-19: everything people asked Mesiri for (and the team asked the bot for), and what happened
// to each: asked, waiting for an ok, building, live, verified, broken, dropped. Who asked, the
// commit, the live check and whether the person used Mesiri again after it went live.
// Read from the team bot's request log through /admin/requests (platform admins only).
// TM-80: one board of what is being worked on right now (New → Needs a decision → Being built →
// Live, being checked → Done this week), with the list kept as the second view. TM-78: each
// Claude account's 5-hour and weekly use on top; TM-79: what each request used of Claude.
// The view and filters live in the address (?view=list&type=bug), so a filtered view can be shared.

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
  source?: string | null;
  claimed_by?: string | null;
  claimed_at?: string | null;
  usage_usd?: number | null;
  usage_5h?: number | null;
  usage_7d?: number | null;
  usage_turns?: number | null;
  usage_accounts?: string | null;
}

interface Window {
  pct: number | null;
  resets_at: string | null;
}

/** TM-78: one Claude account as the bot last read it. */
interface Account {
  id: string;
  label: string | null;
  logged_in: boolean | null;
  default: boolean | null;
  five_hour: Window | null;
  seven_day: Window | null;
  read_at: string | null;
  limited_until: string | null;
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
  minutes_by_stage?: { plan: number | null; build: number | null; deploy: number | null };
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

type Column = 'new' | 'decision' | 'building' | 'checking' | 'done';
const COLUMNS: [Column, string, string][] = [
  ['new', 'New', 'logged, nobody has started'],
  ['decision', 'Needs a decision', 'waiting for an owner'],
  ['building', 'Being built', 'someone is on it'],
  ['checking', 'Live, being checked', 'shipped; the live check is pending or failed'],
  ['done', 'Done this week', 'verified live in the last 7 days'],
];

const DAY = 86_400_000;
/** TM-77: a request "in progress" with no change for this long is shown as stale: nobody may really be on it. */
const STALE_MS = 2 * DAY;

/** Which board column a request is in; null when it is off the board (dropped, or done before this week). */
function columnOf(i: RequestItem, now: number): Column | null {
  if (i.stage === 'asked') return 'new';
  if (i.stage === 'waiting') return 'decision';
  if (i.stage === 'building') return 'building';
  if (i.stage === 'live' || i.stage === 'broken') return now - Date.parse(i.updated_at) < 14 * DAY || i.stage === 'broken' ? 'checking' : null;
  if (i.stage === 'verified') return now - Date.parse(i.verified_at ?? i.updated_at) < 7 * DAY ? 'done' : null;
  return null;
}

const isStale = (i: RequestItem, now: number) => i.stage === 'building' && now - Date.parse(i.updated_at) > STALE_MS;

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '—';
}

/** "~14% 5h · $2.10", or null when the request has no usage recorded. */
function usageShort(i: RequestItem): string | null {
  if (!i.usage_turns) return null;
  return [i.usage_5h != null ? `~${i.usage_5h}% 5h` : null, i.usage_7d != null ? `~${i.usage_7d}% wk` : null, i.usage_usd != null ? `$${i.usage_usd.toFixed(2)}` : null]
    .filter(Boolean)
    .join(' · ');
}

/** Where a request came from: the group (customer or team) and, for Claude sessions, that it was one. */
const sourceOf = (i: RequestItem) => i.chat_name ?? '—';
const whoOf = (i: RequestItem) => (i.status === 'open' || i.status === 'in_progress' ? i.claimed_by ?? null : null);

const muted = { fontSize: '13px', color: 'var(--neutral-600)' };
const small = { fontSize: '12px', color: 'var(--neutral-500)' };

function Meter({ label, w }: { label: string; w: Window | null }) {
  const pct = w?.pct ?? null;
  const tone = pct == null ? 'var(--neutral-300)' : pct >= 80 ? 'var(--error)' : pct >= 60 ? 'var(--warning)' : 'var(--success)';
  return (
    <div style={{ minWidth: '120px' }}>
      <div style={{ ...small, display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
        <span>{label}</span>
        <span style={{ color: 'var(--neutral-900)', fontWeight: 500 }}>{pct == null ? '—' : `${Math.round(pct)}%`}</span>
      </div>
      <div style={{ height: '6px', borderRadius: '3px', background: 'var(--neutral-100)', overflow: 'hidden', marginTop: '4px' }} role="meter" aria-valuenow={pct ?? undefined} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div style={{ width: `${Math.min(100, pct ?? 0)}%`, height: '100%', background: tone }} />
      </div>
      {w?.resets_at && <div style={{ ...small, marginTop: '2px' }}>resets {when(w.resets_at)}</div>}
    </div>
  );
}

function Accounts({ accounts, open }: { accounts: Account[] | null | undefined; open: { usd: number; n: number } | null }) {
  if (accounts === undefined) return null;
  return (
    <div className="card" style={{ marginBottom: 'var(--space-5)' }} aria-label="Claude accounts">
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', marginBottom: 'var(--space-3)' }}>
        <strong style={{ color: 'var(--neutral-900)' }}>Claude accounts</strong>
        <span style={small}>
          {open && open.n > 0 ? `open work has used $${open.usd.toFixed(2)} of Claude (${open.n} request${open.n === 1 ? '' : 's'}) · ` : ''}
          as the bot last read them · in WhatsApp: <code>@bot account</code>
        </span>
      </div>
      {accounts === null && <span style={muted}>The bot did not send account readings (it may need a restart after its update).</span>}
      {accounts && accounts.length === 0 && <span style={muted}>No Claude accounts on the bot.</span>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 'var(--space-4)' }}>
        {(accounts ?? []).map((a) => (
          <div key={a.id}>
            <div style={{ fontWeight: 500, color: 'var(--neutral-900)', marginBottom: '6px' }}>
              {a.label ?? a.id.toUpperCase()}
              {a.default && <span style={{ ...small, marginLeft: '6px' }}>default</span>}
              {a.logged_in === false && <span style={{ ...small, marginLeft: '6px' }}>no login</span>}
            </div>
            {a.limited_until ? (
              <span className="badge badge-error">at its limit until {when(a.limited_until)}</span>
            ) : (
              <div style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
                <Meter label="5-hour" w={a.five_hour} />
                <Meter label="Weekly" w={a.seven_day} />
              </div>
            )}
            <div style={{ ...small, marginTop: '4px' }}>{a.read_at ? `read ${when(a.read_at)}` : 'not read yet (it is read on the next bot turn)'}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Requests() {
  const [items, setItems] = useState<RequestItem[] | null>(null);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [loop, setLoop] = useState<Loop | null>(null);
  const [accounts, setAccounts] = useState<Account[] | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [log, setLog] = useState<Record<number, LogEntry[] | string>>({});
  const [params, setParams] = useSearchParams();
  const [now, setNow] = useState(0); // set when the list arrives, so stale / this-week are measured from then

  const view = params.get('view') === 'list' ? 'list' : 'board';
  const stage = (params.get('stage') ?? 'all') as Stage | 'all' | 'open' | 'shipped';
  const usersOnly = params.get('users') === '1';
  const query = params.get('q') ?? '';
  const type = params.get('type') ?? '';
  const source = params.get('source') ?? '';
  const who = params.get('who') ?? '';
  const sort = params.get('sort') === 'usage' ? 'usage' : 'updated';
  const set = (key: string, value: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );

  useEffect(() => {
    api
      .get<{ counts: Counts; loop?: Loop; items: RequestItem[]; accounts?: Account[] | null }>('/admin/requests')
      .then((res) => {
        setNow(Date.now());
        setItems(res.data.items);
        setCounts(res.data.counts);
        setLoop(res.data.loop ?? null);
        setAccounts(res.data.accounts ?? null);
      })
      .catch((err) => setError(getErrorMessage(err, 'Could not load the requests')));
  }, []);

  const options = useMemo(() => {
    const uniq = (xs: (string | null)[]) => [...new Set(xs.filter((x): x is string => Boolean(x)))].sort();
    const all = items ?? [];
    return { types: uniq(all.map((i) => i.type)), sources: uniq(all.map(sourceOf)), who: uniq(all.map(whoOf)) };
  }, [items]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = (items ?? []).filter((i) => {
      if (usersOnly && !i.asked_by) return false;
      if (view === 'list') {
        if (stage === 'open' && !['asked', 'waiting', 'building'].includes(i.stage)) return false;
        if (stage === 'shipped' && !['live', 'verified', 'broken'].includes(i.stage)) return false;
        if (stage !== 'all' && stage !== 'open' && stage !== 'shipped' && i.stage !== stage) return false;
      }
      if (type && i.type !== type) return false;
      if (source && sourceOf(i) !== source) return false;
      if (who && whoOf(i) !== who) return false;
      return !q || `${i.id} ${i.title} ${i.asked_by ?? ''} ${i.created_by ?? ''} ${i.claimed_by ?? ''}`.toLowerCase().includes(q);
    });
    return sort === 'usage' ? [...list].sort((a, b) => (b.usage_usd ?? -1) - (a.usage_usd ?? -1)) : list;
  }, [items, stage, usersOnly, query, type, source, who, view, sort]);

  const board = useMemo(() => {
    const cols = Object.fromEntries(COLUMNS.map(([c]) => [c, [] as RequestItem[]])) as Record<Column, RequestItem[]>;
    for (const i of shown) {
      const c = columnOf(i, now);
      if (c) cols[c].push(i);
    }
    return cols;
  }, [shown, now]);

  const usageTotal = useMemo(() => {
    const open = (items ?? []).filter((i) => ['asked', 'waiting', 'building'].includes(i.stage) && i.usage_usd != null);
    return { usd: open.reduce((s, i) => s + (i.usage_usd ?? 0), 0), n: open.length };
  }, [items]);

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

  const history = (id: number) => {
    const entries = log[id];
    return (
      <>
        {!entries && <span style={muted}>Loading history…</span>}
        {typeof entries === 'string' && <span style={{ color: 'var(--error)' }}>{entries}</span>}
        {Array.isArray(entries) && (
          <ul style={{ ...muted, margin: 0, paddingLeft: '18px' }}>
            {entries.map((e, n) => (
              <li key={n} style={{ overflowWrap: 'anywhere' }}>
                {when(e.at)} · {[e.status, e.ref && `commit ${e.ref}`, e.note].filter(Boolean).join(' · ')}
              </li>
            ))}
          </ul>
        )}
      </>
    );
  };

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1400px' }}>
      <header style={{ marginBottom: 'var(--space-6)' }}>
        <h1>Requests</h1>
        <p className="subtitle">
          Everything being fixed or built for Mesiri, wherever it came from (WhatsApp groups, feedback in Mesiri chat, Claude sessions), who is on it and
          what it used of Claude. In WhatsApp: <code>@bot status</code>, <code>@bot status &lt;n&gt;</code>, <code>@bot account</code>.
        </p>
      </header>

      <Accounts accounts={accounts} open={items ? usageTotal : null} />

      <div className="kpis" style={{ marginBottom: 'var(--space-5)' }}>
        {kpis.map(([label, value, sub, key]) => (
          <button
            key={label}
            type="button"
            className="kpi"
            onClick={() => {
              set('view', 'list');
              set('stage', stage === key ? '' : key === 'all' ? '' : key);
            }}
            style={{ border: 'none', textAlign: 'left', cursor: 'pointer', background: view === 'list' && stage === key && key !== 'all' ? 'var(--neutral-50)' : undefined }}
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
          {loop.minutes_by_stage && (
            <div className="kpi">
              <span className="kpi-label">Where the time goes (median)</span>
              <span className="kpi-row">
                <span className="kpi-value" style={{ fontSize: '18px' }}>
                  {(['plan', 'build', 'deploy'] as const).map((s) => `${s} ${hours(loop.minutes_by_stage![s] == null ? null : loop.minutes_by_stage![s]! / 60)}`).join(' · ')}
                </span>
              </span>
              <span className="kpi-compare">asked → build started → pushed → live</span>
            </div>
          )}
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
        <div role="tablist" aria-label="View" style={{ display: 'flex', gap: '4px' }}>
          {(['board', 'list'] as const).map((v) => (
            <button key={v} type="button" role="tab" aria-selected={view === v} className={`btn ${view === v ? 'btn-primary' : 'btn-secondary'}`} onClick={() => set('view', v === 'board' ? '' : v)}>
              {v === 'board' ? 'Board' : 'List'}
            </button>
          ))}
        </div>
        <input className="form-input" placeholder="Search number, title or person" value={query} onChange={(e) => set('q', e.target.value)} style={{ maxWidth: '240px' }} />
        {view === 'list' && (
          <select className="form-input" value={stage} onChange={(e) => set('stage', e.target.value === 'all' ? '' : e.target.value)} style={{ maxWidth: '190px' }} aria-label="Stage">
            <option value="all">Every stage</option>
            <option value="open">Open (not live yet)</option>
            <option value="shipped">Shipped</option>
            {(Object.keys(STAGES) as Stage[]).map((s) => (
              <option key={s} value={s}>{STAGES[s][0]}{counts ? ` (${counts[s]})` : ''}</option>
            ))}
          </select>
        )}
        <select className="form-input" value={type} onChange={(e) => set('type', e.target.value)} style={{ maxWidth: '150px' }} aria-label="Type">
          <option value="">Every type</option>
          {options.types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select className="form-input" value={source} onChange={(e) => set('source', e.target.value)} style={{ maxWidth: '200px' }} aria-label="Group">
          <option value="">Every group</option>
          {options.sources.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select className="form-input" value={who} onChange={(e) => set('who', e.target.value)} style={{ maxWidth: '200px' }} aria-label="Who is on it">
          <option value="">Anyone on it</option>
          {options.who.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        {view === 'list' && (
          <select className="form-input" value={sort} onChange={(e) => set('sort', e.target.value === 'usage' ? 'usage' : '')} style={{ maxWidth: '170px' }} aria-label="Sort">
            <option value="updated">Newest change first</option>
            <option value="usage">Most Claude usage first</option>
          </select>
        )}
        <label style={{ ...muted, display: 'flex', gap: '6px', alignItems: 'center' }}>
          <input type="checkbox" checked={usersOnly} onChange={(e) => set('users', e.target.checked ? '1' : '')} />
          Asked by users only
        </label>
        {items && <span style={muted}>{view === 'board' ? `${Object.values(board).reduce((s, c) => s + c.length, 0)} on the board` : `${shown.length} shown`}</span>}
      </div>

      {error && <div className="card" style={{ color: 'var(--error)' }}>{error}</div>}
      {!error && !items && <div className="card" style={muted}>Loading…</div>}

      {items && view === 'board' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 'var(--space-3)', alignItems: 'start' }}>
          {COLUMNS.map(([key, label, hint]) => (
            <section key={key} aria-label={label} style={{ background: 'var(--neutral-50)', borderRadius: 'var(--radius-lg)', padding: 'var(--space-3)', minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '2px' }}>
                <strong style={{ color: 'var(--neutral-900)' }}>{label}</strong>
                <span style={muted}>{board[key].length}</span>
              </div>
              <div style={{ ...small, marginBottom: 'var(--space-3)' }}>{hint}</div>
              {board[key].length === 0 && <div style={small}>Nothing here.</div>}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {board[key].map((i) => {
                  const used = usageShort(i);
                  const on = whoOf(i);
                  const stale = isStale(i, now);
                  return (
                    <article key={i.id} className="card" style={{ padding: 'var(--space-3)', cursor: 'pointer', minWidth: 0 }} onClick={() => toggle(i.id)}>
                      <div style={{ ...small, display: 'flex', justifyContent: 'space-between', gap: '6px' }}>
                        <span>[{i.id}] · {i.type}</span>
                        {i.stage === 'broken' && <span className="badge badge-error">broken</span>}
                        {stale && <span className="badge badge-warning" title="No change for over 2 days">stale</span>}
                      </div>
                      <div style={{ fontWeight: 500, color: 'var(--neutral-900)', margin: '4px 0', overflowWrap: 'anywhere' }}>{i.title}</div>
                      <div style={{ ...small, overflowWrap: 'anywhere' }}>
                        from {sourceOf(i)}{i.asked_by ? ` · asked by ${i.asked_by.split(/[,(]/)[0].trim()}` : ''}
                      </div>
                      {on && <div style={{ ...small, overflowWrap: 'anywhere' }}>on it: {on}</div>}
                      {i.held && i.stage === 'waiting' && <div style={{ ...small, color: 'var(--warning)', overflowWrap: 'anywhere' }}>{i.held.slice(0, 160)}</div>}
                      {used && <div style={{ ...small, color: 'var(--neutral-700)' }}>Claude: {used}{i.usage_accounts ? ` · ${i.usage_accounts}` : ''}</div>}
                      {i.done_ref && <div style={{ ...small, overflowWrap: 'anywhere' }}>commit {i.done_ref}</div>}
                      {open === i.id && <div style={{ marginTop: '8px' }} onClick={(e) => e.stopPropagation()}>{history(i.id)}</div>}
                    </article>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}

      {items && view === 'list' && (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th style={{ width: '48px' }}>#</th>
                <th>Request</th>
                <th>Asked by</th>
                <th>Stage</th>
                <th>Claude usage</th>
                <th>Live check</th>
                <th>Used again</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {shown.length === 0 && <tr><td colSpan={8} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Nothing here.</td></tr>}
              {shown.map((i) => {
                const [label, badge] = STAGES[i.stage] ?? STAGES.asked;
                const on = whoOf(i);
                return (
                  <Fragment key={i.id}>
                    <tr onClick={() => toggle(i.id)} style={{ cursor: 'pointer' }}>
                      <td style={muted}>{i.id}</td>
                      <td>
                        <div style={{ fontWeight: 500, color: 'var(--neutral-900)' }}>{i.title}</div>
                        <div style={small}>
                          {i.type} · {sourceOf(i)}{on ? ` · on it: ${on}` : ''}{i.done_ref ? ` · commit ${i.done_ref}` : ''}{i.held && i.stage === 'waiting' ? ` · held: ${i.held}` : ''}
                        </div>
                      </td>
                      <td style={muted}>{i.asked_by ?? <span style={{ color: 'var(--neutral-400)' }}>{i.created_by ?? i.chat_name ?? '—'}</span>}</td>
                      <td>
                        <span className={`badge ${badge}`}>{label}</span>
                        {isStale(i, now) && <span className="badge badge-warning" style={{ marginLeft: '4px' }}>stale</span>}
                      </td>
                      <td style={muted}>{usageShort(i) ?? '—'}</td>
                      <td style={muted}>{i.verified === 'ok' ? `✅ ${when(i.verified_at)}` : i.verified === 'broken' ? `❌ ${when(i.verified_at)}` : i.live_at ? 'pending' : '—'}</td>
                      <td style={muted}>{i.tried_at ? `✓ ${when(i.tried_at)}` : i.live_at && i.asked_by ? 'not yet' : '—'}</td>
                      <td style={muted}>{when(i.updated_at)}</td>
                    </tr>
                    {open === i.id && (
                      <tr>
                        <td />
                        <td colSpan={7} style={{ background: 'var(--neutral-50)' }}>
                          {i.summary && <p style={{ ...muted, whiteSpace: 'pre-wrap', marginBottom: '8px' }}>{i.summary.slice(0, 1200)}</p>}
                          {i.usage_turns ? (
                            <p style={{ ...muted, marginBottom: '8px' }}>
                              Claude: {usageShort(i)} over {i.usage_turns} turn{i.usage_turns === 1 ? '' : 's'}{i.usage_accounts ? ` on ${i.usage_accounts}` : ''}. The % is an estimate from the account's readings.
                            </p>
                          ) : null}
                          {history(i.id)}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
