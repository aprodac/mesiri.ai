// SA-38 / SA-39: What works -- the WhatsApp conversation one message was part of (GET /admin/message-map/thread/{id},
// platform admins only), drawn as the chat, with what Mesiri did under each reply; and the small icons the views share.

import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Hand, Image as ImageIcon, Keyboard, Mic } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import { WhatsAppText } from './Announcements';
import { STATE_COLOR, how, muted, role, type State } from './whatWorksShared';

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

export function HowIcon({ type }: { type: string | null }) {
  const size = 13;
  if (type === 'voice' || type === 'audio') return <Mic size={size} />;
  if (type === 'image' || type === 'document') return <ImageIcon size={size} />;
  if (type === 'interactive' || type === 'button') return <Hand size={size} />;
  return <Keyboard size={size} />;
}

export function Dot({ color }: { color: string }) {
  return <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flex: 'none' }} />;
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
}

/** The conversation one message was part of, drawn as the WhatsApp chat. ``highlight``: the messages to mark
 *  (one request of several messages); without it, the picked message is marked. */
export function Chat({ messageId, highlight, empty }: { messageId: string | null; highlight?: string[]; empty?: string }) {
  const [thread, setThread] = useState<Thread | null>(null);
  const [error, setError] = useState('');
  const box = useRef<HTMLDivElement>(null);

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
    // Scroll the chat box only, never the page (on a phone the list of requests sits above it).
    const el = box.current?.querySelector<HTMLElement>('#ww-selected');
    if (box.current && el) box.current.scrollTop = el.offsetTop - box.current.clientHeight / 3;
  }, [thread]);

  if (!messageId) {
    return (
      <div className="card" style={{ ...muted, textAlign: 'center', padding: 'var(--space-10) var(--space-5)' }}>
        {empty || 'Pick a message on the left to see the WhatsApp conversation it was part of.'}
      </div>
    );
  }
  const marked = new Set(highlight || []);
  const isMarked = (m: ThreadMessage) => (highlight ? marked.has(m.id) : m.selected);
  const selected = thread?.messages.find((m) => m.selected);

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div style={{ background: '#075E54', color: '#fff', padding: '10px 14px' }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{thread ? thread.sender || 'Unknown sender' : 'Loading…'}</div>
        <div style={{ fontSize: 12, opacity: 0.85 }}>{thread ? [role(thread.role), thread.company].filter(Boolean).join(' · ') || 'to Mesiri' : ' '}</div>
      </div>
      <div ref={box} className="ww-chat" style={{ position: 'relative', background: '#E5DDD5', padding: 12, display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto' }}>
        {error && <div style={{ color: 'var(--error)', fontSize: 13 }}>{error}</div>}
        {thread?.messages.map((m) => (
          <div key={m.id} id={m.selected ? 'ww-selected' : undefined} style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: isMarked(m) ? 6 : 0, margin: isMarked(m) ? '0 -6px' : 0, borderRadius: 10, background: isMarked(m) ? 'rgba(245,197,66,0.35)' : 'transparent' }}>
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
                  <Dot color={STATE_COLOR[m.state].ink} /> {m.outcome_label}
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
          {highlight ? 'The highlighted messages are this request. ' : 'The highlighted message is the one you picked. '}
          Its id, for <Link to="/logs">Assistant logs</Link>:{' '}
          <code style={{ fontSize: 11.5, userSelect: 'all' }}>{selected.correlation_id}</code>
        </div>
      )}
    </div>
  );
}
