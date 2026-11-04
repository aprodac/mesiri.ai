import { useState } from 'react';

// TM-85: one request's story, read from its history in the request log: what the person said, what was found, what
// was changed (commits), how we know it works (review, live check, real use), who worked on it (each session, account,
// handover) and what it used of Claude. The raw history stays one click away.

export interface StoryItem {
  id: number;
  title: string;
  summary: string | null;
  asked_by: string | null;
  created_by: string | null;
  chat_name: string | null;
  source?: string | null;
  done_ref: string | null;
  verified: 'ok' | 'broken' | null;
  verified_at: string | null;
  tried_at: string | null;
  paused?: string | null;
  usage_usd?: number | null;
  usage_5h?: number | null;
  usage_7d?: number | null;
  usage_turns?: number | null;
  usage_accounts?: string | null;
}

export interface LogEntry {
  at: string;
  status: string | null;
  ref: string | null;
  note: string | null;
}

const REPO = 'https://github.com/aprodac/mesiri.ai';
const SESSION = /https:\/\/claude\.ai\/code\/session_[A-Za-z0-9]+/g;
const SHA = /^[0-9a-f]{7,40}$/;

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '—';
}

const muted = { fontSize: '13px', color: 'var(--neutral-600)' };
const label = { fontSize: '12px', fontWeight: 600, color: 'var(--neutral-900)', margin: '10px 0 2px' } as const;
const wrap = { overflowWrap: 'anywhere' as const, whiteSpace: 'pre-wrap' as const };

/** The commits a request names: its done_ref and every ref in its history, once each, oldest first. */
function commitsOf(item: StoryItem, log: LogEntry[]): string[] {
  const refs = [...log.map((e) => e.ref), item.done_ref]
    .flatMap((r) => String(r ?? '').split(/[,\s]+/))
    .map((r) => r.trim())
    .filter((r) => SHA.test(r) || /^[\w.-]+\/[\w.-]+#\d+$/.test(r));
  return [...new Set(refs)];
}

/** Lines of the plan that say what was found: "Root cause:", "Failing test:", "Class:". */
function findingsOf(summary: string | null): string[] {
  return String(summary ?? '')
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => /^(root cause|failing test|class|mechanism)\s*:/i.test(l));
}

const notes = (log: LogEntry[], test: RegExp) => log.filter((e) => e.note && test.test(e.note));

function Commit({ refName }: { refName: string }) {
  const m = refName.match(/^([\w.-]+\/[\w.-]+)#(\d+)$/);
  const href = m ? `https://github.com/${m[1]}/pull/${m[2]}` : `${REPO}/commit/${refName}`;
  return (
    <a href={href} target="_blank" rel="noreferrer" style={{ fontFamily: 'var(--font-mono, monospace)', marginRight: '8px' }}>
      {m ? refName : refName.slice(0, 7)}
    </a>
  );
}

export default function RequestStory({ item, log }: { item: StoryItem; log: LogEntry[] | string | undefined }) {
  const [raw, setRaw] = useState(false);
  const [fullPlan, setFullPlan] = useState(false);
  if (!log) return <span style={muted}>Loading its story…</span>;
  if (typeof log === 'string') return <span style={{ color: 'var(--error)' }}>{log}</span>;

  const found = findingsOf(item.summary);
  const commits = commitsOf(item, log);
  const also = notes(log, /^same problem reported again/i);
  const builds = notes(log, /^🗒 build report/);
  const reviews = notes(log, /^🗒 breaker review/);
  const liveChecks = log.filter((e) => e.note && /verified=(ok|broken)|^live check|^real use/i.test(e.note));
  const handovers = notes(log, /^⏸ handover|^▶️ picked up/);
  const sessions = [...new Set(log.flatMap((e) => (e.note ?? '').match(SESSION) ?? []))];
  // The plan without the lines already shown as findings.
  const plan = String(item.summary ?? '')
    .split('\n')
    .filter((l) => !found.includes(l.trim()))
    .join('\n')
    .trim();

  return (
    <div style={{ ...muted, minWidth: 0 }} aria-label={`How request ${item.id} was handled`}>
      {item.paused && <div className="badge badge-warning" style={{ marginBottom: '6px', whiteSpace: 'normal' }}>⏸ {item.paused}</div>}

      <div style={label}>The problem</div>
      <div style={wrap}>
        {item.title}
        {item.asked_by ? ` · asked by ${item.asked_by}` : item.created_by ? ` · logged by ${item.created_by}` : ''}
        {item.chat_name ? ` · ${item.chat_name}` : ''}
        {item.source ? ` · messages ${item.source}` : ''}
      </div>
      {also.length > 0 && (
        <div style={wrap}>Reported again: {also.map((e) => `${when(e.at)} ${e.note!.replace(/^same problem reported again\s*/i, '')}`).join(' · ')}</div>
      )}

      {(found.length > 0 || plan) && <div style={label}>What was found and the plan</div>}
      {found.map((l) => <div key={l} style={wrap}>{l}</div>)}
      {plan && (
        <div style={wrap}>
          {fullPlan || plan.length <= 500 ? plan : `${plan.slice(0, 500)}…`}
          {plan.length > 500 && (
            <button type="button" className="btn btn-secondary" style={{ marginLeft: '6px', padding: '0 6px', fontSize: '12px' }} onClick={() => setFullPlan(!fullPlan)}>
              {fullPlan ? 'less' : 'whole plan'}
            </button>
          )}
        </div>
      )}

      <div style={label}>What was changed</div>
      {commits.length ? <div>{commits.map((c) => <Commit key={c} refName={c} />)}</div> : <div>No commit yet.</div>}
      {builds.map((e, n) => <div key={n} style={wrap}>{when(e.at)} · {e.note!.replace(/^🗒 build report:\s*/, '').slice(0, 700)}</div>)}

      <div style={label}>How we know it works</div>
      {reviews.map((e, n) => <div key={`r${n}`} style={wrap}>Review {when(e.at)}: {e.note!.replace(/^🗒 breaker review:\s*/, '').slice(0, 400)}</div>)}
      <div>
        Live check: {item.verified === 'ok' ? `✅ passed ${when(item.verified_at)}` : item.verified === 'broken' ? `❌ still broken ${when(item.verified_at)}` : 'not checked yet'}
        {' · '}Used again by who asked: {item.tried_at ? `✓ ${when(item.tried_at)}` : 'not yet'}
      </div>
      {liveChecks.map((e, n) => <div key={`l${n}`} style={wrap}>{when(e.at)} · {e.note!.slice(0, 300)}</div>)}

      <div style={label}>Who worked on it</div>
      {sessions.length ? (
        <div>
          {sessions.map((s, n) => (
            <a key={s} href={s} target="_blank" rel="noreferrer" style={{ marginRight: '8px' }}>session {n + 1}</a>
          ))}
        </div>
      ) : (
        <div>No Claude session linked.</div>
      )}
      {handovers.map((e, n) => <div key={`h${n}`} style={wrap}>{when(e.at)} · {e.note!.slice(0, 400)}</div>)}
      {item.usage_turns ? (
        <div>
          Claude usage: {[item.usage_5h != null ? `~${item.usage_5h}% of a 5-hour window` : null, item.usage_7d != null ? `~${item.usage_7d}% of the week` : null, item.usage_usd != null ? `$${item.usage_usd.toFixed(2)}` : null].filter(Boolean).join(' · ')}
          {` over ${item.usage_turns} turn${item.usage_turns === 1 ? '' : 's'}`}{item.usage_accounts ? ` on ${item.usage_accounts}` : ''} (the % is an estimate)
        </div>
      ) : null}

      <button type="button" className="btn btn-secondary" style={{ marginTop: '8px', padding: '2px 8px', fontSize: '12px' }} onClick={() => setRaw(!raw)}>
        {raw ? 'Hide full history' : `Full history (${log.length})`}
      </button>
      {raw && (
        <ul style={{ margin: '6px 0 0', paddingLeft: '18px' }}>
          {log.map((e, n) => (
            <li key={n} style={{ overflowWrap: 'anywhere' }}>
              {when(e.at)} · {[e.status, e.ref && `commit ${e.ref}`, e.note].filter(Boolean).join(' · ')}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
