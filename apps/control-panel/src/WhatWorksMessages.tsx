// SA-38: What works, "Every message" view -- every kind of message people sent to Mesiri, section by section,
// split into what works, what doesn't, and what can't be told from the record. A kind opens to the messages
// people sent and the reply each got; picking one shows the WhatsApp conversation on the right.
// Read-only, from GET /admin/message-map (platform admins only). Tab, search and message live in the address.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import { Chat, Dot, HowIcon } from './WhatWorksChat';
import { STATE_COLOR, how, muted, showPanel, when, who, type State } from './whatWorksShared';

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

const TABS: { key: State; label: string; note: string }[] = [
  { key: 'works', label: 'Works', note: 'Mesiri did what the message asked: saved it, put it on the card, answered from the records, sent it, or asked the one thing it needed.' },
  { key: 'broken', label: "Doesn't work", note: 'No reply, a failure, a refusal, a save that did not save, or the person was told "not yet" and it was passed to the team.' },
  { key: 'unsure', label: 'Not sure', note: 'The record cannot tell: a reply with no tool used, a cancel, or a message with no record of what Mesiri did. Read these.' },
];

function matches(e: Example, g: Group, q: string): boolean {
  if (!q) return true;
  return [e.text, e.reply, e.sender, e.company, e.note, g.title, g.tool, g.reason, g.outcome_label]
    .some((v) => (v || '').toLowerCase().includes(q));
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

export default function WhatWorksMessages({ days, company, params, set, reload }: {
  days: number;
  company: string;
  params: URLSearchParams;
  set: (changes: Record<string, string>) => void;
  reload: number;
}) {
  const tab = (TABS.find((t) => t.key === params.get('tab'))?.key || 'works') as State;
  const picked = params.get('message');
  const [search, setSearch] = useState(params.get('q') || '');
  const [data, setData] = useState<MessageMap | null>(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const load = useCallback(() => {
    setError('');
    api
      .get<MessageMap>('/admin/message-map', { params: { days, organization_id: company || undefined } })
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load the messages.')));
  }, [days, company]);

  useEffect(load, [load, reload]);

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
    <>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, maxWidth: 380, height: 36, padding: '0 10px', marginBottom: 'var(--space-4)', border: '1px solid var(--border-default)', borderRadius: 'var(--radius-sm)', background: 'var(--white)', color: 'var(--neutral-400)' }}>
        <Search size={15} />
        <input value={search} onChange={(e) => setSearch(e.target.value)} onBlur={() => set({ q: search.trim() })} placeholder="Search the messages, replies, people" aria-label="Search" style={{ flex: 1, minWidth: 0, border: 'none', outline: 'none', background: 'transparent', font: 'inherit', fontSize: 13.5, color: 'var(--neutral-900)' }} />
      </label>

      {error && <div className="card" style={{ color: 'var(--error)', marginBottom: 'var(--space-4)' }}>{error}</div>}

      {totals && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
          {TABS.map((t) => {
            const on = tab === t.key;
            return (
              <button key={t.key} onClick={() => set({ tab: t.key })} aria-pressed={on} title={t.note} className="card" style={{ textAlign: 'left', font: 'inherit', cursor: 'pointer', borderColor: on ? STATE_COLOR[t.key].ink : undefined, boxShadow: on ? `0 0 0 1px ${STATE_COLOR[t.key].ink}` : undefined }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, ...muted }}><Dot color={STATE_COLOR[t.key].ink} /> {t.label}</div>
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
                  onPick={(id) => {
                    set({ message: id });
                    showPanel();
                  }}
                />
              ))}
            </section>
          ))}
        </div>
        <aside className="ww-side" id="ww-panel">
          <Chat messageId={picked} />
        </aside>
      </div>
    </>
  );
}
