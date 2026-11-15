// SA-38: What works -- every kind of message people sent to Mesiri, section by section, split into
// what works, what doesn't, and what can't be told from the record. A kind opens to the messages
// people sent (who, how: typed, voice note, photo, tap) and the reply each got; picking a message
// shows the WhatsApp conversation it was part of on the right, with what Mesiri did in each turn.
// Read-only, from GET /admin/message-map and /admin/message-map/thread/{id} (platform admins only).
// The window, company, tab and search live in the address, so a view can be shared.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronDown, ChevronRight, Hand, Image as ImageIcon, Keyboard, Mic, RefreshCw, Search } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import { WhatsAppText } from './Announcements';

type State = 'works' | 'broken' | 'unsure';

interface Example {
  id: string;
  correlation_id: string;
  text: string;
  reply: string;
  at: string;
  type: string | null;
  sender: string | null;
  role: string | null;
  company: string | null;
  phone_tail: string;
  note: string;
  times: number;
}

interface Group {
  key: string;
  section: string;
  state: State;
  tool: string | null;
  title: string;
  hint: string;
  outcome: string;
  outcome_label: string;
  reason: string;
  count: number;
  people: number;
  companies: string[];
  how: Record<string, number>;
  last_at: string;
  examples: Example[];
}

interface Section {
  key: string;
  label: string;
  works: number;
  broken: number;
  unsure: number;
  groups: Group[];
}

interface MessageMap {
  window: { since: string; until: string; days: number };
  truncated: boolean;
  totals: { messages: number; works: number; broken: number; unsure: number; people: number };
  sections: Section[];
}

interface ThreadMessage {
  id: string;
  correlation_id: string;
  at: string;
  replied_at: string | null;
  type: string | null;
  text: string;
  reply: string;
  state: State | null;
  outcome_label: string;
  reason: string;
  did: string[];
  selected: boolean;
}

interface Thread {
  sender: string | null;
  role: string | null;
  company: string | null;
  messages: ThreadMessage[];
}

interface CompanyOption {
  id: string;
  name: string;
}

const WINDOWS = [
  { days: 1, label: 'Last 24 hours' },
  { days: 7, label: 'Last 7 days' },
  { days: 14, label: 'Last 14 days' },
  { days: 30, label: 'Last 30 days' },
];

const TABS: { key: State; label: string; note: string }[] = [
  { key: 'works', label: 'Works', note: 'Mesiri did what the message asked: saved it, put it on the card, answered from the records, sent it, or asked the one thing it needed.' },
  { key: 'broken', label: "Doesn't work", note: 'No reply, a failure, a refusal, a save that did not save, or the person was told "not yet" and it was passed to the team.' },
  { key: 'unsure', label: 'Not sure', note: 'The record cannot tell: a reply with no tool used, a cancel, or a message with no record of what Mesiri did. Read these.' },
];

const STATE_COLOR: Record<State, { ink: string; soft: string }> = {
  works: { ink: 'var(--success)', soft: 'var(--success-soft)' },
  broken: { ink: 'var(--error)', soft: 'var(--error-soft)' },
  unsure: { ink: 'var(--warning)', soft: 'var(--warning-soft)' },
};

const HOW: Record<string, string> = {
  text: 'typed',
  voice: 'voice note',
  audio: 'voice note',
  image: 'photo',
  document: 'document',
  interactive: 'button tap',
  button: 'button tap',
  unknown: 'other',
};

const muted = { color: 'var(--neutral-500)', fontSize: '12.5px' } as const;

function how(type: string | null): string {
  return HOW[type || 'unknown'] || type || 'other';
}

function HowIcon({ type }: { type: string | null }) {
  const size = 13;
  if (type === 'voice' || type === 'audio') return <Mic size={size} />;
  if (type === 'image' || type === 'document') return <ImageIcon size={size} />;
  if (type === 'interactive' || type === 'button') return <Hand size={size} />;
  return <Keyboard size={size} />;
}

function when(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
}

function role(value: string | null): string {
  return value ? value.replace(/_/g, ' ').toLowerCase() : '';
}

function who(e: { sender: string | null; role: string | null; company: string | null; phone_tail?: string }): string {
  const name = e.sender || (e.phone_tail ? `Number ending ${e.phone_tail}` : 'Unknown sender');
  return [name, role(e.role), e.company].filter(Boolean).join(' · ');
}

function matches(e: Example, g: Group, q: string): boolean {
  if (!q) return true;
  return [e.text, e.reply, e.sender, e.company, e.note, g.title, g.tool, g.reason, g.outcome_label]
    .some((v) => (v || '').toLowerCase().includes(q));
}

function Dot({ state }: { state: State }) {
  return <span style={{ width: 8, height: 8, borderRadius: '50%', background: STATE_COLOR[state].ink, flex: 'none' }} />;
}

/** The conversation one message was part of, drawn as the WhatsApp chat. */
function Chat({ messageId }: { messageId: string | null }) {
  const [thread, setThread] = useState<Thread | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!messageId) return;
    let alive = true;
    setThread(null);
    setError('');
    api
      .get<Thread>(`/admin/message-map/thread/${messageId}`)
      .then((res) => alive && setThread(res.data))
      .catch((err) => alive && setError(getErrorMessage(err, 'Could not load the conversation.')));
    return () => {
      alive = false;
    };
  }, [messageId]);

  useEffect(() => {
    if (thread) document.getElementById('ww-selected')?.scrollIntoView({ block: 'center' });
  }, [thread]);

  if (!messageId) {
    return (
      <div className="card" style={{ ...muted, textAlign: 'center', padding: 'var(--space-10) var(--space-5)' }}>
        Pick a message on the left to see the WhatsApp conversation it was part of.
      </div>
    );
  }
  const selected = thread?.messages.find((m) => m.selected);

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div style={{ background: '#075E54', color: '#fff', padding: '10px 14px' }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{thread ? thread.sender || 'Unknown sender' : 'Loading…'}</div>
        <div style={{ fontSize: 12, opacity: 0.85 }}>{thread ? [role(thread.role), thread.company].filter(Boolean).join(' · ') || 'to Mesiri' : ' '}</div>
      </div>
      <div className="ww-chat" style={{ background: '#E5DDD5', padding: 12, display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto' }}>
        {error && <div style={{ color: 'var(--error)', fontSize: 13 }}>{error}</div>}
        {thread?.messages.map((m) => (
          <div key={m.id} id={m.selected ? 'ww-selected' : undefined} style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: m.selected ? 6 : 0, margin: m.selected ? '0 -6px' : 0, borderRadius: 10, background: m.selected ? 'rgba(245,197,66,0.35)' : 'transparent' }}>
            {/* What the person sent */}
            <div style={{ alignSelf: 'flex-end', maxWidth: '88%', background: '#DCF8C6', borderRadius: '10px 0 10px 10px', padding: '6px 9px', fontSize: 13.5, lineHeight: 1.4, color: '#111', boxShadow: '0 1px 1px rgba(0,0,0,0.1)' }}>
              {m.type !== 'text' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11.5, color: '#4a6b4a', marginBottom: 2 }}>
                  <HowIcon type={m.type} /> {how(m.type)}{(m.type === 'voice' || m.type === 'audio') && m.text ? ', as Mesiri heard it' : ''}
                </div>
              )}
              {m.text ? <WhatsAppText text={m.text} /> : <span style={{ color: '#777' }}>(no text)</span>}
              <div style={{ fontSize: 10.5, color: '#667', textAlign: 'right', marginTop: 2 }}>{clock(m.at)}</div>
            </div>
            {/* What Mesiri replied */}
            {m.reply ? (
              <div style={{ alignSelf: 'flex-start', maxWidth: '92%', background: '#fff', borderRadius: '0 10px 10px 10px', padding: '6px 9px', fontSize: 13.5, lineHeight: 1.4, color: '#111', boxShadow: '0 1px 1px rgba(0,0,0,0.1)', overflowWrap: 'anywhere' }}>
                <WhatsAppText text={m.reply} />
                <div style={{ fontSize: 10.5, color: '#667', textAlign: 'right', marginTop: 2 }}>{m.replied_at ? clock(m.replied_at) : ''}</div>
              </div>
            ) : (
              <div style={{ alignSelf: 'center', fontSize: 11.5, color: '#7a2e2e', background: '#fde8e8', borderRadius: 8, padding: '3px 8px' }}>Mesiri sent no reply</div>
            )}
            {/* What Mesiri did (not part of the chat: only this page shows it) */}
            {m.state && (
              <div style={{ alignSelf: 'flex-start', maxWidth: '92%', fontSize: 11.5, lineHeight: 1.45, color: 'var(--neutral-700)', background: 'rgba(255,255,255,0.72)', border: `1px solid ${STATE_COLOR[m.state].ink}`, borderRadius: 8, padding: '4px 8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, color: STATE_COLOR[m.state].ink }}>
                  <Dot state={m.state} /> {m.outcome_label}
                </div>
                {m.reason && <div>{m.reason}</div>}
                {m.did.map((line, i) => (
                  <div key={i} style={{ overflowWrap: 'anywhere' }}>{line}</div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      {selected && (
        <div style={{ padding: '8px 14px', borderTop: '1px solid var(--border-default)', ...muted }}>
          The highlighted message is the one you picked. Its id, for <Link to="/logs">Assistant logs</Link>:{' '}
          <code style={{ fontSize: 11.5, userSelect: 'all' }}>{selected.correlation_id}</code>
        </div>
      )}
    </div>
  );
}

function GroupRow({ group, open, onToggle, picked, onPick, query }: { group: Group; open: boolean; onToggle: () => void; picked: string | null; onPick: (id: string) => void; query: string }) {
  const examples = group.examples.filter((e) => matches(e, group, query));
  const color = STATE_COLOR[group.state];
  return (
    <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
      <button onClick={onToggle} aria-expanded={open} style={{ display: 'flex', width: '100%', gap: 10, alignItems: 'flex-start', padding: '10px 14px', border: 'none', background: open ? 'var(--neutral-50)' : 'transparent', cursor: 'pointer', textAlign: 'left', font: 'inherit' }}>
        <span style={{ color: 'var(--neutral-400)', marginTop: 2 }}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
            <span style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--neutral-900)' }} title={group.hint || undefined}>{group.title}</span>
            {group.tool && group.title !== group.outcome_label && (
              <span style={{ fontSize: 11.5, fontWeight: 500, color: color.ink, background: color.soft, borderRadius: 999, padding: '1px 8px' }}>{group.outcome_label}</span>
            )}
          </span>
          {group.reason && <span style={{ display: 'block', fontSize: 12.5, color: 'var(--neutral-700)', marginTop: 2, overflowWrap: 'anywhere' }}>{group.reason}</span>}
          <span style={{ display: 'block', ...muted, fontSize: 12, marginTop: 2 }}>
            {Object.entries(group.how).map(([type, n]) => `${n} ${how(type)}`).join(' · ')}
            {' · '}{group.people} {group.people === 1 ? 'person' : 'people'}
            {group.companies.length > 0 && ` · ${group.companies.slice(0, 3).join(', ')}${group.companies.length > 3 ? '…' : ''}`}
            {' · last '}{when(group.last_at)}
          </span>
        </span>
        <span style={{ fontWeight: 600, fontSize: 14, color: color.ink, fontVariantNumeric: 'tabular-nums' }}>{group.count}</span>
      </button>
      {open && (
        <div style={{ padding: '2px 14px 12px 39px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {group.hint && <div style={{ ...muted, fontSize: 12 }}>What this is for: {group.hint}</div>}
          {examples.length === 0 && <div style={muted}>No message here matches the search.</div>}
          {examples.map((e) => {
            const on = picked === e.id;
            return (
              <button key={e.id} onClick={() => onPick(e.id)} style={{ textAlign: 'left', font: 'inherit', cursor: 'pointer', border: `1px solid ${on ? 'var(--neutral-900)' : 'var(--border-default)'}`, background: on ? 'var(--brand-soft)' : 'var(--white)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, ...muted, fontSize: 12 }}>
                  <HowIcon type={e.type} />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{how(e.type)} · {who(e)} · {when(e.at)}</span>
                  {e.times > 1 && <span style={{ marginLeft: 'auto', flex: 'none', fontWeight: 600, color: 'var(--neutral-700)' }}>sent {e.times} times</span>}
                </div>
                <div style={{ fontSize: 13.5, color: 'var(--neutral-900)', marginTop: 3, overflowWrap: 'anywhere' }}>{e.text || <span style={{ color: 'var(--neutral-400)' }}>(no text)</span>}</div>
                <div style={{ fontSize: 12.5, color: 'var(--neutral-600)', marginTop: 3, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', overflowWrap: 'anywhere' }}>
                  <span style={{ color: 'var(--neutral-400)' }}>Mesiri: </span>{e.reply || 'no reply'}
                </div>
                {e.note && <div style={{ fontSize: 12, color: color.ink, marginTop: 3, overflowWrap: 'anywhere' }}>{e.note}</div>}
              </button>
            );
          })}
          {group.examples.length < group.count && !query && (
            <div style={{ ...muted, fontSize: 12 }}>
              Showing {group.examples.length} different messages of {group.count} sent (the same words sent again are shown once).
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function WhatWorks() {
  const [params, setParams] = useSearchParams();
  const days = Number(params.get('days')) || 14;
  const company = params.get('company') || '';
  const tab = (TABS.find((t) => t.key === params.get('tab'))?.key || 'works') as State;
  const picked = params.get('message');
  const [search, setSearch] = useState(params.get('q') || '');
  const [data, setData] = useState<MessageMap | null>(null);
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const set = useCallback(
    (changes: Record<string, string>) => {
      const next = new URLSearchParams(params);
      Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get<MessageMap>('/admin/message-map', { params: { days, organization_id: company || undefined } })
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load the messages.')))
      .finally(() => setLoading(false));
  }, [days, company]);

  useEffect(load, [load]);
  useEffect(() => {
    api
      .get<CompanyOption[]>('/admin/organizations')
      .then((res) => setCompanies(res.data))
      .catch(() => setCompanies([]));
  }, []);

  const query = search.trim().toLowerCase();
  const sections = useMemo(
    () =>
      (data?.sections || [])
        .map((s) => ({
          ...s,
          groups: s.groups.filter((g) => g.state === tab && (!query || g.examples.some((e) => matches(e, g, query)))),
        }))
        .filter((s) => s.groups.length > 0),
    [data, tab, query],
  );

  const totals = data?.totals;
  const judged = totals ? totals.works + totals.broken : 0;

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1400px' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 'var(--space-4)', flexWrap: 'wrap', marginBottom: 'var(--space-5)' }}>
        <div>
          <h1>What works</h1>
          <p className="subtitle">Every kind of message people sent to Mesiri, what it replied, and where it falls short.</p>
        </div>
        <button className="btn-secondary" onClick={load} disabled={loading}>
          <RefreshCw size={16} /> {loading ? 'Loading…' : 'Refresh'}
        </button>
      </header>

      <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', marginBottom: 'var(--space-4)' }}>
        <select className="form-input" style={{ height: 36, width: 'auto' }} value={days} onChange={(e) => set({ days: e.target.value })} aria-label="Time window">
          {WINDOWS.map((w) => (
            <option key={w.days} value={w.days}>{w.label}</option>
          ))}
        </select>
        <select className="form-input" style={{ height: 36, width: 'auto', maxWidth: 260 }} value={company} onChange={(e) => set({ company: e.target.value })} aria-label="Company">
          <option value="">All companies</option>
          {companies.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, flex: '1 1 220px', maxWidth: 380, height: 36, padding: '0 10px', border: '1px solid var(--border-default)', borderRadius: 'var(--radius-sm)', background: 'var(--white)', color: 'var(--neutral-400)' }}>
          <Search size={15} />
          <input value={search} onChange={(e) => setSearch(e.target.value)} onBlur={() => set({ q: search.trim() })} placeholder="Search the messages, replies, people" aria-label="Search" style={{ flex: 1, minWidth: 0, border: 'none', outline: 'none', background: 'transparent', font: 'inherit', fontSize: 13.5, color: 'var(--neutral-900)' }} />
        </label>
      </div>

      {error && <div className="card" style={{ color: 'var(--error)', marginBottom: 'var(--space-4)' }}>{error}</div>}

      {totals && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
          {TABS.map((t) => {
            const on = tab === t.key;
            return (
              <button key={t.key} onClick={() => set({ tab: t.key })} aria-pressed={on} title={t.note} className="card" style={{ textAlign: 'left', font: 'inherit', cursor: 'pointer', borderColor: on ? STATE_COLOR[t.key].ink : undefined, boxShadow: on ? `0 0 0 1px ${STATE_COLOR[t.key].ink}` : undefined }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, ...muted }}><Dot state={t.key} /> {t.label}</div>
                <div style={{ fontSize: 26, fontWeight: 600, marginTop: 4, color: 'var(--neutral-900)', fontVariantNumeric: 'tabular-nums' }}>{totals[t.key]}</div>
              </button>
            );
          })}
          <div className="card">
            <div style={muted}>Messages read</div>
            <div style={{ fontSize: 26, fontWeight: 600, marginTop: 4, color: 'var(--neutral-900)', fontVariantNumeric: 'tabular-nums' }}>{totals.messages}</div>
            <div style={{ ...muted, fontSize: 12 }}>
              from {totals.people} {totals.people === 1 ? 'person' : 'people'}
              {judged > 0 && ` · ${Math.round((totals.works / judged) * 100)}% of the judged ones work`}
            </div>
          </div>
        </div>
      )}

      <p style={{ ...muted, margin: '0 0 var(--space-4)' }}>
        {TABS.find((t) => t.key === tab)?.note}
        {data?.truncated && ' Only the newest 5,000 messages of this window were read.'}
      </p>

      <div className="ww-grid">
        <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          {data && sections.length === 0 && (
            <div className="card" style={muted}>{query ? 'Nothing here matches the search.' : 'No messages of this kind in this window.'}</div>
          )}
          {!data && !error && <div className="card" style={muted}>Loading…</div>}
          {sections.map((s) => (
            <section key={s.key} className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', padding: '12px 14px' }}>
                <h2 style={{ fontSize: 15, margin: 0 }}>{s.label}</h2>
                <span style={{ ...muted, fontSize: 12 }}>
                  <span style={{ color: 'var(--success)' }}>{s.works} work</span> · <span style={{ color: 'var(--error)' }}>{s.broken} don't</span> · {s.unsure} not sure
                </span>
              </div>
              {s.groups.map((g) => (
                <GroupRow
                  key={g.key}
                  group={g}
                  query={query}
                  open={!!open[g.key] || (!!query && open[g.key] !== false)}
                  onToggle={() => setOpen((o) => ({ ...o, [g.key]: !(o[g.key] || (!!query && o[g.key] !== false)) }))}
                  picked={picked}
                  onPick={(id) => set({ message: id })}
                />
              ))}
            </section>
          ))}
        </div>
        <aside className="ww-side">
          <Chat messageId={picked} />
        </aside>
      </div>
    </div>
  );
}
