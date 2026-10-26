// SA-17: the Reply Insights message feed -- each WhatsApp message with its
// reply time and AI tokens. A row opens to the message and reply, where the
// reply time went (AI vs everything else) and each AI call it took.

import { Fragment, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, ExternalLink, Zap } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import {
  type CallRow,
  type FeedItem,
  SERIES,
  SPEED_BADGE,
  compact,
  fmtMs,
  full,
  inr,
  muted,
  num,
  speedOf,
  when,
} from './replyFormat';

const COLS = 7;

function SpeedPill({ ms, status }: { ms: number | null; status: string }) {
  if (ms === null) {
    const failed = status === 'failed';
    return <span className={failed ? 'badge badge-error' : 'badge'} style={failed ? undefined : { background: 'var(--neutral-100)', color: 'var(--neutral-600)' }}>{failed ? 'Failed' : 'No reply yet'}</span>;
  }
  return <span className={SPEED_BADGE[speedOf(ms)]} style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtMs(ms)}</span>;
}

/** Input (with its cached part) and output tokens as one thin bar, scaled to the page's largest. */
function TokenBar({ item, max }: { item: FeedItem; max: number }) {
  const total = item.input_tokens + item.output_tokens;
  if (!total) return <span style={muted}>No AI</span>;
  const w = (v: number) => `${(v / Math.max(1, max)) * 100}%`;
  const fresh = item.input_tokens - item.cached_input_tokens;
  return (
    <div title={`${full(item.input_tokens)} in (${full(item.cached_input_tokens)} cached) · ${full(item.output_tokens)} out`}>
      <div style={{ ...num, fontSize: '13px' }}>
        {compact(item.input_tokens)} <span style={muted}>/</span> {compact(item.output_tokens)}
      </div>
      <div style={{ display: 'flex', gap: 2, height: 4, marginTop: 4, justifyContent: 'flex-end' }}>
        {fresh > 0 && <span style={{ width: w(fresh), background: SERIES.blue, borderRadius: 2 }} />}
        {item.cached_input_tokens > 0 && <span style={{ width: w(item.cached_input_tokens), background: SERIES.aqua, borderRadius: 2 }} />}
        {item.output_tokens > 0 && <span style={{ width: w(item.output_tokens), background: SERIES.orange, borderRadius: 2 }} />}
      </div>
    </div>
  );
}

/** Where the reply time went: time in AI calls vs everything else. AI calls
 *  can overlap, so their sum is capped at the reply time. */
function TimeSplit({ item }: { item: FeedItem }) {
  if (item.reply_ms === null) return null;
  const ai = Math.min(item.ai_ms ?? 0, item.reply_ms);
  const other = item.reply_ms - ai;
  const pct = (v: number) => `${(v / Math.max(1, item.reply_ms as number)) * 100}%`;
  return (
    <div style={{ marginBottom: 'var(--space-4)' }}>
      <div style={{ ...muted, fontSize: '12px', marginBottom: 6 }}>Where the {fmtMs(item.reply_ms)} went</div>
      <div style={{ display: 'flex', gap: 2, height: 10 }}>
        {ai > 0 && <span style={{ width: pct(ai), background: SERIES.blue, borderRadius: 3 }} />}
        {other > 0 && <span style={{ width: pct(other), background: 'var(--neutral-300)', borderRadius: 3 }} />}
      </div>
      <div style={{ display: 'flex', gap: 'var(--space-4)', fontSize: '12px', marginTop: 6, color: 'var(--neutral-600)' }}>
        <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: SERIES.blue, marginRight: 6 }} />AI calls {fmtMs(ai)}</span>
        <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: 'var(--neutral-300)', marginRight: 6 }} />Everything else {fmtMs(other)}</span>
      </div>
    </div>
  );
}

function Calls({ correlationId }: { correlationId: string }) {
  const [calls, setCalls] = useState<CallRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<CallRow[]>(`/admin/replies/messages/${encodeURIComponent(correlationId)}/calls`)
      .then((res) => setCalls(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load the AI calls')));
  }, [correlationId]);

  if (error) return <p style={{ color: 'var(--error)', fontSize: '13px' }}>{error}</p>;
  if (!calls) return <p style={muted}>Loading AI calls…</p>;
  if (!calls.length) return <p style={muted}>No AI calls: answered without the AI (a quick reply or a button).</p>;

  return (
    <table style={{ background: 'transparent' }}>
      <thead>
        <tr>
          <th style={{ background: 'transparent' }}>Step</th>
          <th style={{ background: 'transparent' }}>Model</th>
          <th style={{ ...num, background: 'transparent' }}>Time</th>
          <th style={{ ...num, background: 'transparent' }}>In</th>
          <th style={{ ...num, background: 'transparent' }}>Cached</th>
          <th style={{ ...num, background: 'transparent' }}>Out</th>
          <th style={{ ...num, background: 'transparent' }}>Cost</th>
        </tr>
      </thead>
      <tbody>
        {calls.map((c, i) => (
          <tr key={i}>
            <td style={{ fontFamily: 'monospace', fontSize: '12px' }}>{c.purpose ?? c.operation}</td>
            <td style={{ fontSize: '13px' }}>
              {c.model ?? '—'} <span style={muted}>· {c.provider}</span>
            </td>
            <td style={num}>{fmtMs(c.latency_ms)}</td>
            <td style={num}>{full(c.input_tokens)}</td>
            <td style={num}>{full(c.cached_input_tokens)}</td>
            <td style={num}>{full(c.output_tokens)}</td>
            <td style={num}>{c.ai_cost_inr === null ? <span style={muted} title="No price for this model yet">unpriced</span> : inr(c.ai_cost_inr)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Detail({ item }: { item: FeedItem }) {
  const bubble = { padding: '8px 12px', borderRadius: 'var(--radius-md)', fontSize: '13px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' } as const;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) minmax(320px, 2fr)', gap: 'var(--space-6)', padding: 'var(--space-4) 0', alignItems: 'start' }}>
      <div style={{ display: 'grid', gap: 'var(--space-2)' }}>
        <div style={{ ...bubble, background: 'var(--surface-secondary)', justifySelf: 'start', maxWidth: '100%' }}>
          {item.text || <span style={muted}>({item.message_type})</span>}
        </div>
        <div style={{ ...bubble, background: 'var(--primary-soft)', justifySelf: 'end', maxWidth: '100%' }}>
          {item.reply || <span style={muted}>No reply text recorded</span>}
        </div>
        <div style={{ ...muted, fontSize: '12px', marginTop: 'var(--space-2)', display: 'grid', gap: 2 }}>
          <span>Received {when(item.received_at)}{item.processed_at ? ` · done ${when(item.processed_at)}` : ''}</span>
          <span style={{ fontFamily: 'monospace' }}>{item.correlation_id}</span>
          {item.organization_id && (
            <Link to={`/logs?org=${item.organization_id}`} style={{ color: 'var(--info)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              This company's messages in Assistant Logs <ExternalLink size={12} />
            </Link>
          )}
        </div>
      </div>
      <div style={{ minWidth: 0 }}>
        <TimeSplit item={item} />
        <Calls correlationId={item.correlation_id} />
      </div>
    </div>
  );
}

export default function ReplyFeed({ items }: { items: FeedItem[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const maxTokens = Math.max(1, ...items.map((i) => i.input_tokens + i.output_tokens));

  return (
    <table>
      <thead>
        <tr>
          <th style={{ width: 28 }} />
          <th>Received</th>
          <th>From</th>
          <th>Message</th>
          <th style={num}>Reply time</th>
          <th style={{ ...num, width: 140 }}>Tokens in / out</th>
          <th style={num}>AI cost</th>
        </tr>
      </thead>
      <tbody>
        {items.length === 0 && (
          <tr>
            <td colSpan={COLS} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>
              No messages match.
            </td>
          </tr>
        )}
        {items.map((m) => {
          const isOpen = open === m.correlation_id;
          return (
            <Fragment key={m.correlation_id}>
              <tr
                style={{ cursor: 'pointer' }}
                onClick={() => setOpen(isOpen ? null : m.correlation_id)}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setOpen(isOpen ? null : m.correlation_id);
                  }
                }}
                aria-expanded={isOpen}
              >
                <td style={{ color: 'var(--neutral-400)', paddingRight: 0 }}>{isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</td>
                <td style={{ whiteSpace: 'nowrap', fontSize: '13px' }}>{when(m.received_at)}</td>
                <td style={{ fontSize: '13px', whiteSpace: 'nowrap' }}>
                  <div style={{ fontWeight: 500 }}>{m.sender_name ?? `+${m.sender_wa_id}`}</div>
                  <div style={{ ...muted, fontSize: '12px' }}>{m.organization_name ?? 'No company yet'}</div>
                </td>
                <td style={{ maxWidth: 340, fontSize: '13px' }}>
                  <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={m.text ?? ''}>
                    {m.text || <span style={muted}>({m.message_type})</span>}
                  </div>
                  <div style={{ ...muted, fontSize: '12px', textTransform: 'capitalize', display: 'flex', alignItems: 'center', gap: 4 }}>
                    {m.message_type}
                    {m.ai_calls === 0 && m.reply_ms !== null && (
                      <span title="Answered without the AI" style={{ display: 'inline-flex', alignItems: 'center', gap: 2, textTransform: 'none' }}>
                        · <Zap size={11} /> quick reply
                      </span>
                    )}
                    {m.ai_calls > 0 && <span style={{ textTransform: 'none' }}>· {m.ai_calls} AI call{m.ai_calls === 1 ? '' : 's'}</span>}
                  </div>
                </td>
                <td style={num}>
                  <SpeedPill ms={m.reply_ms} status={m.processing_status} />
                </td>
                <td style={num}>
                  <TokenBar item={m} max={maxTokens} />
                </td>
                <td style={{ ...num, fontSize: '13px' }}>
                  {m.ai_calls ? inr(m.ai_cost_inr) : <span style={muted}>—</span>}
                  {m.unpriced > 0 && <span style={muted} title="Calls with no price are not included"> +{m.unpriced}?</span>}
                </td>
              </tr>
              {isOpen && (
                <tr>
                  <td colSpan={COLS} style={{ height: 'auto', background: 'var(--neutral-50)' }}>
                    <Detail item={m} />
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
