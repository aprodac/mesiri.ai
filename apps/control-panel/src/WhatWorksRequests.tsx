// SA-39: What works -- what the views show of requests: the endings bar, and the panel that lists requests and
// shows the WhatsApp conversation of the one picked.

import type { ReactNode } from 'react';
import { Chat, Dot, HowIcon } from './WhatWorksChat';
import { ENDING, ENDINGS, how, muted, role, when, type Bar, type Intent } from './whatWorksShared';

export function StackedBar({ bar, height = 10 }: { bar: Bar; height?: number }) {
  const total = ENDINGS.reduce((n, e) => n + (bar[e.key] || 0), 0);
  return (
    <div className="ww-bar" style={{ height }} role="img" aria-label={ENDINGS.filter((e) => bar[e.key]).map((e) => `${bar[e.key]} ${e.label}`).join(', ')}>
      {ENDINGS.filter((e) => bar[e.key]).map((e) => (
        <span key={e.key} title={`${bar[e.key]} ${e.label}`} style={{ width: `${(bar[e.key] / total) * 100}%`, background: e.color }} />
      ))}
    </div>
  );
}

export /** The requests of one capability or problem, worst first, and the conversation of the one picked. */
function Panel({ title, sub, intents, picked, onPick, actions }: { title: string; sub: string; intents: Intent[]; picked: Intent | null; onPick: (id: string) => void; actions?: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)' }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--neutral-900)', overflowWrap: 'anywhere' }}>{title}</div>
          <div style={{ ...muted, fontSize: 12 }}>{sub}</div>
          {actions}
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
                <span title={[how(i.how), i.sender_name, role(i.sender_role), i.company].filter(Boolean).join(' · ')} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--neutral-900)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  <span style={{ color: 'var(--neutral-400)', flex: 'none', display: 'inline-flex' }}><HowIcon type={i.how} /></span>
                  {i.text || <span style={{ color: 'var(--neutral-400)' }}>({how(i.how)}, no text)</span>}
                </span>
                {i.reason && <span className="ww-quote" style={{ fontSize: 11.5, color: 'var(--neutral-600)' }}>{i.reason}</span>}
              </button>
            );
          })}
        </div>
      </div>
      <Chat messageId={picked?.messages[0] || null} highlight={picked?.messages} empty="Pick a request above to see its WhatsApp conversation." />
    </div>
  );
}

