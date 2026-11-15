// SA-39: What works, Health view -- how each module is doing, judged by request (a message that starts something
// plus the taps, answers and changes that continue it), not by single message. "Fix these first" lists the
// largest problems across every module; a module opens to what people can ask for in it; a card or a problem
// opens the requests on the right, the worst first, with the WhatsApp conversation of the one picked.
// Read-only, from GET /admin/message-map/intents (platform admins only). The selection lives in the address.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import { Chat, Dot, HowIcon } from './WhatWorksChat';
import { how, muted, role, showPanel, when } from './whatWorksShared';

type Ending = 'finished' | 'finished_after_question' | 'abandoned' | 'cancelled' | 'failed' | 'complained' | 'unsure' | 'open';
type Bar = Record<Ending, number>;

interface Capability {
  key: string;
  name: string;
  tool: string | null;
  count: number;
  finished: number;
  endings: Bar;
  how: Record<string, number>;
  journeys: Record<string, number>;
  top_reasons: { reason: string; count: number }[];
  phrasings: string[];
  intents: string[];
}

interface Module {
  key: string;
  label: string;
  count: number;
  finished: number;
  endings: Bar;
  capabilities: Capability[];
}

interface Problem {
  key: string;
  ending: Ending;
  reason: string;
  count: number;
  line: string;
  capabilities: { key: string; name: string; count: number }[];
  intents: string[];
}

interface Intent {
  id: string;
  started_at: string;
  how: string;
  company: string | null;
  messages: string[];
  text: string;
  sender_name: string | null;
  sender_role: string | null;
  capability: string;
  section: string;
  ending: Ending;
  reason: string;
  journeys: string[];
}

interface Health {
  window: { since: string; until: string; days: number };
  truncated: boolean;
  totals: { intents: number; still_going: number } & Bar;
  fix_first: Problem[];
  sections: Module[];
  previous: { totals: { intents: number } & Bar; sections: Record<string, { count: number; finished: number }> };
  intents: Intent[];
}

/** The endings, in the order the bars draw them. */
const ENDINGS: { key: Ending; label: string; color: string; note: string }[] = [
  { key: 'finished', label: 'Finished', color: 'var(--success)', note: 'Saved, sent, or answered from the records.' },
  { key: 'finished_after_question', label: 'Finished after a question', color: '#6FBF8A', note: 'Mesiri asked one thing first, then it was saved or answered.' },
  { key: 'abandoned', label: 'Left without Save', color: 'var(--warning)', note: 'A card or a question was still waiting when the person stopped.' },
  { key: 'cancelled', label: 'Cancelled', color: 'var(--neutral-400)', note: 'The person cancelled the card.' },
  { key: 'failed', label: 'Failed', color: 'var(--error)', note: 'No reply, an outage, a refusal, or a save that did not save.' },
  { key: 'complained', label: "Complaint or 'not yet'", color: '#9F1239', note: 'The person said the reply was bad or wrong, or Mesiri cannot do it yet and told the team.' },
  { key: 'unsure', label: 'Not sure', color: 'var(--neutral-200)', note: 'Mesiri replied but the record shows nothing done (no tool, a question back). Each one says why.' },
];
const ENDING = Object.fromEntries(ENDINGS.map((e) => [e.key, e])) as Record<Ending, (typeof ENDINGS)[number]>;
const GOOD: Ending[] = ['finished', 'finished_after_question'];

function pct(part: number, whole: number): number {
  return whole ? Math.round((part / whole) * 100) : 0;
}

function finished(bar: Bar): number {
  return GOOD.reduce((n, k) => n + (bar[k] || 0), 0);
}

function StackedBar({ bar, height = 10 }: { bar: Bar; height?: number }) {
  const total = ENDINGS.reduce((n, e) => n + (bar[e.key] || 0), 0);
  return (
    <div className="ww-bar" style={{ height }} role="img" aria-label={ENDINGS.filter((e) => bar[e.key]).map((e) => `${bar[e.key]} ${e.label}`).join(', ')}>
      {ENDINGS.filter((e) => bar[e.key]).map((e) => (
        <span key={e.key} title={`${bar[e.key]} ${e.label}`} style={{ width: `${(bar[e.key] / total) * 100}%`, background: e.color }} />
      ))}
    </div>
  );
}

function Change({ now, before, days }: { now: { count: number; finished: number }; before?: { count: number; finished: number }; days: number }) {
  if (!before || before.count === 0) return <span style={muted}>none in the {days} days before</span>;
  const delta = pct(now.finished, now.count) - pct(before.finished, before.count);
  const color = delta > 0 ? 'var(--success)' : delta < 0 ? 'var(--error)' : 'var(--neutral-500)';
  return (
    <span style={muted}>
      was {before.count} at {pct(before.finished, before.count)}%{' '}
      {now.count > 0 && <span style={{ color, fontWeight: 600 }}>{delta > 0 ? '+' : ''}{delta} pts</span>}
    </span>
  );
}

function CapabilityCard({ cap, on, onPick }: { cap: Capability; on: boolean; onPick: () => void }) {
  const done = finished(cap.endings);
  return (
    <button className={`ww-cap${on ? ' on' : ''}`} onClick={onPick} aria-pressed={on}>
      <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
        <span style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--neutral-900)', overflowWrap: 'anywhere' }}>{cap.name}</span>
        <span style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums', color: 'var(--neutral-900)' }}>{cap.count}</span>
      </span>
      {cap.tool && <span className="ww-tool">{cap.tool}</span>}
      <StackedBar bar={cap.endings} height={6} />
      <span style={{ ...muted, fontSize: 12 }}>
        {done} of {cap.count} finished ({pct(done, cap.count)}%) · {Object.entries(cap.how).map(([t, n]) => `${n} ${how(t)}`).join(' · ')}
      </span>
      {cap.phrasings.length > 0 && (
        <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {cap.phrasings.map((p) => (
            <span key={p} className="ww-quote">“{p}”</span>
          ))}
        </span>
      )}
      {cap.top_reasons.length > 0 && (
        <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {cap.top_reasons.map((r) => (
            <span key={r.reason} style={{ fontSize: 12, color: 'var(--error)', overflowWrap: 'anywhere' }}>{r.count} × {r.reason}</span>
          ))}
        </span>
      )}
    </button>
  );
}

/** The requests of one capability or problem, worst first, and the conversation of the one picked. */
function Panel({ title, sub, intents, picked, onPick }: { title: string; sub: string; intents: Intent[]; picked: Intent | null; onPick: (id: string) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)' }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--neutral-900)', overflowWrap: 'anywhere' }}>{title}</div>
          <div style={{ ...muted, fontSize: 12 }}>{sub}</div>
        </div>
        <div className="ww-list">
          {intents.map((i) => {
            const on = picked?.id === i.id;
            return (
              <button key={i.id} className={`ww-row${on ? ' on' : ''}`} onClick={() => onPick(i.id)} aria-pressed={on}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: ENDING[i.ending]?.color === 'var(--neutral-200)' ? 'var(--neutral-600)' : ENDING[i.ending]?.color }}>
                  <Dot color={ENDING[i.ending]?.color || 'var(--neutral-300)'} /> {ENDING[i.ending]?.label || i.ending}
                  <span style={{ marginLeft: 'auto', fontWeight: 400, color: 'var(--neutral-500)' }}>{when(i.started_at)}</span>
                </span>
                <span style={{ fontSize: 13, color: 'var(--neutral-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {i.text || <span style={{ color: 'var(--neutral-400)' }}>({how(i.how)}, no text)</span>}
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 5, ...muted, fontSize: 11.5, overflow: 'hidden', whiteSpace: 'nowrap' }}>
                  <HowIcon type={i.how} /> {how(i.how)} · {[i.sender_name || 'Unknown sender', role(i.sender_role), i.company].filter(Boolean).join(' · ')}
                  {i.messages.length > 1 && ` · ${i.messages.length} messages`}
                </span>
                {i.reason && <span style={{ fontSize: 11.5, color: 'var(--neutral-600)', overflowWrap: 'anywhere' }}>{i.reason}</span>}
              </button>
            );
          })}
        </div>
      </div>
      <Chat messageId={picked?.messages[0] || null} highlight={picked?.messages} empty="Pick a request above to see its WhatsApp conversation." />
    </div>
  );
}

export default function WhatWorksHealth({ days, company, params, set, reload }: {
  days: number;
  company: string;
  params: URLSearchParams;
  set: (changes: Record<string, string>) => void;
  reload: number;
}) {
  const [data, setData] = useState<Health | null>(null);
  const [error, setError] = useState('');
  const openModule = params.get('module') || '';
  const cap = params.get('cap') || '';
  const problem = params.get('problem') || '';
  const intentId = params.get('intent') || '';

  const load = useCallback(() => {
    setError('');
    api
      .get<Health>('/admin/message-map/intents', { params: { days, organization_id: company || undefined } })
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load the requests.')));
  }, [days, company]);
  useEffect(load, [load, reload]);

  const byId = useMemo(() => new Map((data?.intents || []).map((i) => [i.id, i])), [data]);

  // What the panel shows: one capability of a module, or one problem of "Fix these first".
  const selection = useMemo(() => {
    if (!data) return null;
    const found = (ids: string[]) => ids.map((id) => byId.get(id)).filter((i): i is Intent => !!i);
    if (problem) {
      const p = data.fix_first.find((x) => x.key === problem);
      if (p) return { title: p.line, sub: `In ${p.capabilities.map((c) => c.name).join(' · ')}. Newest first.`, intents: found(p.intents) };
    }
    if (cap) {
      for (const s of data.sections) {
        const c = s.capabilities.find((x) => x.key === cap);
        if (c && (!openModule || s.key === openModule)) {
          const shown = c.intents.length < c.count ? ` Showing ${c.intents.length} of ${c.count}.` : '';
          return { title: c.name, sub: `${s.label} · ${c.count} requests, the ones that did not finish first.${shown}`, intents: found(c.intents) };
        }
      }
    }
    return null;
  }, [data, byId, problem, cap, openModule]);

  const picked = selection ? selection.intents.find((i) => i.id === intentId) || selection.intents[0] || null : null;

  if (error) return <div className="card" style={{ color: 'var(--error)' }}>{error}</div>;
  if (!data) return <div className="card" style={muted}>Loading…</div>;

  const t = data.totals;
  const done = finished(t);
  const prev = data.previous.totals;

  return (
    <div className="ww-grid">
      <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {/* The whole window in one line */}
        <section className="card">
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 26, fontWeight: 600, color: 'var(--neutral-900)', fontVariantNumeric: 'tabular-nums' }}>{pct(done, t.intents)}%</span>
            <span style={{ fontSize: 13.5, color: 'var(--neutral-700)' }}>
              of {t.intents} requests finished ({done})
            </span>
            <span style={{ marginLeft: 'auto' }}>
              <Change now={{ count: t.intents, finished: done }} before={{ count: prev.intents, finished: finished(prev) }} days={days} />
            </span>
          </div>
          <div style={{ marginTop: 10 }}><StackedBar bar={t} height={12} /></div>
          <div className="ww-legend">
            {ENDINGS.map((e) => (
              <span key={e.key} title={e.note}><Dot color={e.color} /> {e.label} <b>{t[e.key] || 0}</b></span>
            ))}
          </div>
          <p style={{ ...muted, fontSize: 12, margin: '8px 0 0' }}>
            A request is one message that starts something, plus the taps, answers and changes that continue it.
            Finished means the record shows a save, a send or an answer, not that the answer was right.
            {t.still_going > 0 && ` ${t.still_going} still going (the person wrote in the last 30 minutes) are not counted.`}
            {data.truncated && ' Only the newest 10,000 messages of this window and the one before were read.'}
          </p>
        </section>

        {/* Fix these first */}
        {data.fix_first.length > 0 && (
          <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <h2 style={{ fontSize: 15, margin: 0, padding: '12px 14px 4px' }}>Fix these first</h2>
            <p style={{ ...muted, fontSize: 12, margin: 0, padding: '0 14px 8px' }}>The largest problems of the window, the same cause counted once wherever it happened.</p>
            <ol className="ww-fix">
              {data.fix_first.map((p, n) => {
                const on = problem === p.key;
                return (
                  <li key={p.key}>
                    <button className={on ? 'on' : ''} aria-pressed={on} onClick={() => { set({ problem: p.key, cap: '', module: '', intent: '' }); showPanel(); }}>
                      <span className="ww-fix-n">{n + 1}</span>
                      <span style={{ minWidth: 0 }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13.5, fontWeight: 600, color: 'var(--neutral-900)', overflowWrap: 'anywhere' }}>
                          <Dot color={ENDING[p.ending]?.color === 'var(--neutral-200)' ? 'var(--neutral-400)' : ENDING[p.ending]?.color} /> {p.line}
                        </span>
                        <span style={{ display: 'block', ...muted, fontSize: 12 }}>in {p.capabilities.map((c) => `${c.name} (${c.count})`).join(' · ')}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </section>
        )}

        {/* One row per module */}
        <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <h2 style={{ fontSize: 15, margin: 0, padding: '12px 14px' }}>By module</h2>
          {data.sections.length === 0 && <div style={{ ...muted, padding: '0 14px 14px' }}>No requests in this window.</div>}
          {data.sections.map((s) => {
            const open = openModule === s.key;
            return (
              <div key={s.key} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <button className="ww-module" aria-expanded={open} onClick={() => set({ module: open ? '' : s.key })}>
                  <span style={{ color: 'var(--neutral-400)' }}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
                  <span className="ww-module-name">{s.label}</span>
                  <span className="ww-module-bar"><StackedBar bar={s.endings} /></span>
                  <span className="ww-module-num">
                    <b>{pct(s.finished, s.count)}%</b> of {s.count}
                  </span>
                  <span className="ww-module-change"><Change now={s} before={data.previous.sections[s.key]} days={days} /></span>
                </button>
                {open && (
                  <div className="ww-caps">
                    {s.capabilities.map((c) => (
                      <CapabilityCard key={c.key} cap={c} on={cap === c.key && !problem} onPick={() => { set({ cap: c.key, problem: '', intent: '' }); showPanel(); }} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </section>
      </div>

      <aside className="ww-side ww-side-health" id="ww-panel">
        {selection ? (
          <Panel title={selection.title} sub={selection.sub} intents={selection.intents} picked={picked} onPick={(id) => set({ intent: id })} />
        ) : (
          <div className="card" style={{ ...muted, textAlign: 'center', padding: 'var(--space-10) var(--space-5)' }}>
            Pick a problem under “Fix these first”, or open a module and pick what people asked for, to see the requests and their WhatsApp conversations here.
          </div>
        )}
      </aside>
    </div>
  );
}
