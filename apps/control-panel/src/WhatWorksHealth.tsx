// SA-39: What works, Health view -- how each module is doing, judged by request (a message that starts something
// plus the taps, answers and changes that continue it), not by single message. "Fix these first" lists the
// largest problems across every module; a module opens to what people can ask for in it; a card or a problem
// opens the requests on the right, the worst first, with the WhatsApp conversation of the one picked.
// Read-only, from GET /admin/message-map/intents (platform admins only). The selection lives in the address.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Info } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import { Dot } from './WhatWorksChat';
import { Panel, StackedBar } from './WhatWorksRequests';
import { ENDING, ENDINGS, finished, muted, pct, showPanel, type Bar, type Ending, type Intent } from './whatWorksShared';

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

interface Health {
  window: { since: string; until: string; days: number };
  truncated: boolean;
  totals: { intents: number; still_going: number } & Bar;
  fix_first: Problem[];
  sections: Module[];
  previous: { totals: { intents: number } & Bar; sections: Record<string, { count: number; finished: number }> };
  intents: Intent[];
}

/** The change in finished share against the window before; nothing when that window had no requests. */
function Change({ now, before, days }: { now: { count: number; finished: number }; before?: { count: number; finished: number }; days: number }) {
  if (!before || before.count === 0 || now.count === 0) return null;
  const delta = pct(now.finished, now.count) - pct(before.finished, before.count);
  const color = delta > 0 ? 'var(--success)' : delta < 0 ? 'var(--error)' : 'var(--neutral-500)';
  return (
    <span style={{ color, fontWeight: 600, fontSize: 12.5 }} title={`${pct(before.finished, before.count)}% of ${before.count} in the ${days} days before`}>
      {delta > 0 ? '+' : ''}{delta} pts
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
      <span style={{ ...muted, fontSize: 12 }}>{pct(done, cap.count)}% finished</span>
      {cap.top_reasons[0] && (
        <span className="ww-quote" style={{ color: 'var(--error)', fontSize: 12 }} title={cap.top_reasons.map((r) => `${r.count} × ${r.reason}`).join('\n')}>
          {cap.top_reasons[0].count} × {cap.top_reasons[0].reason}
        </span>
      )}
    </button>
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
      if (p) return { title: p.line, sub: 'Newest first', intents: found(p.intents) };
    }
    if (cap) {
      for (const s of data.sections) {
        const c = s.capabilities.find((x) => x.key === cap);
        if (c && (!openModule || s.key === openModule)) {
          return { title: c.name, sub: `${c.count} requests · not finished first`, intents: found(c.intents) };
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
            <span style={{ fontSize: 13.5, color: 'var(--neutral-700)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              of {t.intents} requests finished
              <span style={{ color: 'var(--neutral-400)', display: 'inline-flex', cursor: 'help' }} title={'A request is one message that starts something, plus the taps, answers and changes that continue it. Finished means the record shows a save, a send or an answer, not that the answer was right.' + (t.still_going ? ` ${t.still_going} still going are not counted.` : '')}>
                <Info size={14} />
              </span>
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
          {data.truncated && <p style={{ ...muted, fontSize: 12, margin: '8px 0 0' }}>Only the newest 10,000 messages were read.</p>}
        </section>

        {/* Fix these first */}
        {data.fix_first.length > 0 && (
          <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <h2 style={{ fontSize: 15, margin: 0, padding: '12px 14px' }}>Fix these first</h2>
            <ol className="ww-fix">
              {data.fix_first.map((p, n) => {
                const on = problem === p.key;
                return (
                  <li key={p.key}>
                    <button className={on ? 'on' : ''} aria-pressed={on} onClick={() => { set({ problem: p.key, cap: '', module: '', intent: '' }); showPanel(); }}>
                      <span className="ww-fix-n">{n + 1}</span>
                      <span style={{ minWidth: 0 }}>
                        <span title={`In ${p.capabilities.map((c) => `${c.name} (${c.count})`).join(' · ')}`} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13.5, fontWeight: 600, color: 'var(--neutral-900)', overflowWrap: 'anywhere' }}>
                          <Dot color={ENDING[p.ending]?.color === 'var(--neutral-200)' ? 'var(--neutral-400)' : ENDING[p.ending]?.color} /> {p.line}
                        </span>
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
            Pick a problem or a module to see its conversations.
          </div>
        )}
      </aside>
    </div>
  );
}
