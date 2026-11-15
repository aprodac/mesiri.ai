// SA-39 phase 4: What works, Patterns view -- the connections between failures, so the next fix is obvious.
// Same cause in many places (with its trend and the fix actions), where each flow loses requests, what makes it
// worse (how it was sent, script, role, company; only splits with enough requests), what people do after a
// failure. Short on purpose: labels and numbers; anything longer is a tooltip.
// Read-only, from GET /admin/message-map/intents (platform admins only). The selection lives in the address.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Copy, Info } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import { Dot } from './WhatWorksChat';
import { Panel } from './WhatWorksRequests';
import { ENDING, muted, pct, showPanel, type Ending, type Intent } from './whatWorksShared';

interface Cause {
  key: string;
  ending: Ending;
  line: string;
  count: number;
  before: number;
  trend: 'new' | 'growing' | 'shrinking' | 'steady';
  capabilities: { key: string; name: string; count: number }[];
  intents: string[];
  correlation_ids: string[];
  replay: string;
  team_refs: string[];
}

interface Leak {
  key: string;
  name: string;
  section: string;
  steps: { key: string; label: string; count: number }[];
  widest_drop: { at: string; lost: number } | null;
  lost: number;
  intents: string[];
}

interface Split {
  key: string;
  label: string;
  groups: { key: string; name: string; count: number; finished: number }[];
  hidden: number;
}

interface Patterns {
  causes: Cause[];
  gone: { key: string; line: string; before: number }[];
  leaks: Leak[];
  splits: Split[];
  after_failure: { total: number; kinds: { key: string; label: string; count: number; intents: string[] }[] };
  split_floor: number;
}

interface Answer {
  patterns: Patterns;
  intents: Intent[];
}

const TREND: Record<Cause['trend'], { label: string; color: string }> = {
  new: { label: 'new', color: 'var(--error)' },
  growing: { label: 'growing', color: 'var(--error)' },
  shrinking: { label: 'shrinking', color: 'var(--success)' },
  steady: { label: '', color: 'var(--neutral-500)' },
};

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="ww-copy"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          window.setTimeout(() => setDone(false), 1500);
        }).catch(() => undefined);
      }}
    >
      {done ? <Check size={12} /> : <Copy size={12} />} {label}
    </button>
  );
}

function Heading({ title, tip }: { title: string; tip: string }) {
  return (
    <h2 style={{ fontSize: 15, margin: 0, padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
      {title}
      <span style={{ color: 'var(--neutral-400)', display: 'inline-flex', cursor: 'help', fontWeight: 400 }} title={tip}><Info size={14} /></span>
    </h2>
  );
}

export default function WhatWorksPatterns({ days, company, params, set, reload }: {
  days: number;
  company: string;
  params: URLSearchParams;
  set: (changes: Record<string, string>) => void;
  reload: number;
}) {
  const [data, setData] = useState<Answer | null>(null);
  const [error, setError] = useState('');
  const pattern = params.get('pattern') || '';
  const intentId = params.get('intent') || '';

  const load = useCallback(() => {
    setError('');
    api
      .get<Answer>('/admin/message-map/intents', { params: { days, organization_id: company || undefined } })
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load the patterns.')));
  }, [days, company]);
  useEffect(load, [load, reload]);

  const byId = useMemo(() => new Map((data?.intents || []).map((i) => [i.id, i])), [data]);

  // What the panel shows: a cause, a leaking flow, or what people did after a failure.
  const selection = useMemo(() => {
    if (!data || !pattern) return null;
    const p = data.patterns;
    const found = (ids: string[]) => ids.map((id) => byId.get(id)).filter((i): i is Intent => !!i);
    const [kind, ...rest] = pattern.split(':');
    const key = rest.join(':');
    if (kind === 'cause') {
      const c = p.causes.find((x) => x.key === key);
      if (c) return { title: c.line, sub: c.capabilities.map((x) => `${x.name} (${x.count})`).join(' · '), intents: found(c.intents), cause: c };
    }
    if (kind === 'leak') {
      const l = p.leaks.find((x) => x.key === key);
      if (l) return { title: l.name, sub: `${l.lost} not finished · newest first`, intents: found(l.intents) };
    }
    if (kind === 'after') {
      const a = p.after_failure.kinds.find((x) => x.key === key);
      if (a) return { title: `After a failure: ${a.label.toLowerCase()}`, sub: `${a.count} requests · newest first`, intents: found(a.intents) };
    }
    return null;
  }, [data, byId, pattern]);
  const picked = selection ? selection.intents.find((i) => i.id === intentId) || selection.intents[0] || null : null;

  if (error) return <div className="card" style={{ color: 'var(--error)' }}>{error}</div>;
  if (!data) return <div className="card" style={muted}>Loading…</div>;
  const p = data.patterns;
  const pick = (value: string) => {
    set({ pattern: value, intent: '' });
    showPanel();
  };

  const cause = selection && 'cause' in selection ? selection.cause : undefined;
  const actions = cause && (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8, alignItems: 'center' }}>
      {cause.replay && <CopyButton text={cause.replay} label="Replay command" />}
      {cause.correlation_ids.length > 0 && <CopyButton text={cause.correlation_ids.join('\n')} label={`${cause.correlation_ids.length} ids`} />}
      {cause.team_refs.length > 0 && (
        <span style={{ ...muted, fontSize: 12 }} title="The team request log uses the same reference">Team requests: {cause.team_refs.join(' ')}</span>
      )}
    </div>
  );

  return (
    <div className="ww-grid">
      <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {/* 1 + 5: same cause, many places; trend against the window before */}
        <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <Heading title="Same cause" tip={`Each problem counted once wherever it happened, against the ${days} days before. Pick one for its requests, the replay command and the ids.`} />
          {p.causes.length === 0 && <div style={{ ...muted, padding: '0 14px 14px' }}>No problems in this window.</div>}
          <div className="ww-pat-list">
            {p.causes.map((c) => {
              const on = pattern === `cause:${c.key}`;
              const trend = TREND[c.trend];
              return (
                <button key={c.key} className={`ww-pat-row${on ? ' on' : ''}`} aria-pressed={on} onClick={() => pick(`cause:${c.key}`)}
                  title={`In ${c.capabilities.map((x) => `${x.name} (${x.count})`).join(' · ')}`}>
                  <Dot color={ENDING[c.ending]?.color === 'var(--neutral-200)' ? 'var(--neutral-400)' : ENDING[c.ending]?.color} />
                  <span className="ww-pat-line">{c.line}</span>
                  {c.capabilities.length > 1 && <span className="ww-chip">{c.capabilities.length} places</span>}
                  {trend.label && <span className="ww-chip" style={{ color: trend.color }} title={`${c.before} in the ${days} days before`}>{trend.label}</span>}
                </button>
              );
            })}
          </div>
          {p.gone.length > 0 && (
            <div style={{ ...muted, fontSize: 12, padding: '8px 14px 12px', borderTop: '1px solid var(--border-subtle)' }}
              title={p.gone.map((g) => g.line).join('\n')}>
              Gone since the {days} days before: <span style={{ color: 'var(--success)' }}>{p.gone.length}</span>
            </div>
          )}
        </section>

        {/* 2: where each flow leaks */}
        {p.leaks.length > 0 && (
          <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <Heading title="Where it leaks" tip="Per thing people ask for: asked → a tool was called → on the card or answered → finished. The step that loses most is named." />
            <div className="ww-pat-list">
              {p.leaks.slice(0, 8).map((l) => {
                const on = pattern === `leak:${l.key}`;
                return (
                  <button key={l.key} className={`ww-pat-row${on ? ' on' : ''}`} aria-pressed={on} onClick={() => pick(`leak:${l.key}`)} title={l.section}>
                    <span className="ww-pat-line">{l.name}</span>
                    <span className="ww-funnel" title={l.steps.map((s) => `${s.label}: ${s.count}`).join('\n')}>
                      {l.steps.map((s) => s.count).join(' → ')}
                    </span>
                    {l.widest_drop && <span className="ww-chip" style={{ color: 'var(--error)' }}>−{l.widest_drop.lost} at “{l.widest_drop.at.split(',')[0].toLowerCase()}”</span>}
                  </button>
                );
              })}
            </div>
          </section>
        )}

        {/* 3: what makes it worse */}
        <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <Heading title="What makes it worse" tip={`The share that finished, split by how it was sent, the script, who sent it and the company. A group shows only with ${p.split_floor} requests or more.`} />
          {p.splits.length === 0 && <div style={{ ...muted, padding: '0 14px 14px' }}>Not enough requests to compare yet.</div>}
          <div className="ww-splits">
            {p.splits.map((s) => (
              <div key={s.key} className="ww-split">
                <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--neutral-700)' }}>{s.label}</div>
                {s.groups.map((g) => (
                  <div key={g.key} className="ww-split-row" title={`${g.finished} of ${g.count} finished`}>
                    <span className="ww-quote" style={{ fontSize: 12.5 }}>{g.name}</span>
                    <span className="ww-split-bar"><span style={{ width: `${pct(g.finished, g.count)}%` }} /></span>
                    <span style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums', color: 'var(--neutral-900)' }}>{pct(g.finished, g.count)}%</span>
                    <span style={{ ...muted, fontSize: 11.5, fontVariantNumeric: 'tabular-nums' }}>{g.count}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </section>

        {/* 4: what people do after a failure */}
        {p.after_failure.total > 0 && (
          <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <Heading title="After a failure" tip="What the person did next in the same conversation. 'Sent it again' and 'said it was wrong' are the nightly reviewer's signals (admin/friction.py)." />
            <div className="ww-after">
              {p.after_failure.kinds.map((k) => {
                const on = pattern === `after:${k.key}`;
                return (
                  <button key={k.key} className={`ww-after-cell${on ? ' on' : ''}`} aria-pressed={on} disabled={k.count === 0} onClick={() => pick(`after:${k.key}`)}>
                    <span style={{ fontSize: 22, fontWeight: 600, color: 'var(--neutral-900)', fontVariantNumeric: 'tabular-nums' }}>{k.count}</span>
                    <span style={{ ...muted, fontSize: 12 }}>{k.label}</span>
                  </button>
                );
              })}
            </div>
          </section>
        )}
      </div>

      <aside className="ww-side ww-side-health" id="ww-panel">
        {selection ? (
          <Panel title={selection.title} sub={selection.sub} intents={selection.intents} picked={picked} onPick={(id) => set({ intent: id })} actions={actions || undefined} />
        ) : (
          <div className="card" style={{ ...muted, textAlign: 'center', padding: 'var(--space-10) var(--space-5)' }}>Pick a row to see its conversations.</div>
        )}
      </aside>
    </div>
  );
}
