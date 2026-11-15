// SA-39 phase 3: What works, Playbook view -- how each module should work, shown by real conversations.
// Per module, per thing people ask for, one row per journey it was really used in (one thing then Save, several
// things in one message, Mesiri asks and the person answers, changed before saving, ...). Each row's best case
// is the cleanest real request of the window, picked by a score (decision D2: never written by hand); beside it,
// how many real requests of that journey end the same way. A journey with no clean run says so.
// Read-only, from GET /admin/message-map/intents (platform admins only). The selection lives in the address.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, Info, Pin, PinOff } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import { Chat } from './WhatWorksChat';
import { muted, showPanel, when } from './whatWorksShared';

interface Journey {
  key: string;
  label: string;
  count: number;
  same_end: number;
  best: string | null;
  best_messages: number;
  best_reply_s: number | null;
  pinned: { message_id: string; note: string | null; by: string | null; at: string | null; in_window: boolean } | null;
  candidates: string[];
}

interface PlaybookCapability {
  key: string;
  name: string;
  tool: string;
  count: number;
  journeys: Journey[];
  missing: number;
}

interface PlaybookModule {
  key: string;
  label: string;
  count: number;
  capabilities: PlaybookCapability[];
  missing: number;
}

interface Intent {
  id: string;
  started_at: string;
  messages: string[];
  sender_name: string | null;
  company: string | null;
}

interface Answer {
  playbook: PlaybookModule[];
  intents: Intent[];
  pins_ok: boolean;
}

const JOURNEY_NOTE: Record<string, string> = {
  one_thing: 'The person sends one thing, Mesiri puts it on the card, one Save keeps it.',
  several_things: 'One message carries several things; they all go on one card and one Save keeps them.',
  asked_answered: 'Mesiri needs one thing it cannot work out (which site, how big a bag) and asks; the answer finishes it.',
  changed_before_save: 'The person changes a line on the card before saving it.',
  corrected_after_save: 'The person corrects something already saved.',
  memory: 'A follow-up that only makes sense with what came before ("make it 25", "Site B").',
  read_answer: 'A question answered from what is recorded.',
  voice: 'Sent as a voice note.',
  photo: 'Sent as a photo.',
  cancelled: 'The person cancels the card, and nothing is saved.',
};

function share(part: number, whole: number): string {
  return whole ? `${Math.round((part / whole) * 100)}%` : '–';
}

export default function WhatWorksPlaybook({ days, company, params, set, reload }: {
  days: number;
  company: string;
  params: URLSearchParams;
  set: (changes: Record<string, string>) => void;
  reload: number;
}) {
  const [data, setData] = useState<Answer | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [pinError, setPinError] = useState('');

  const load = useCallback(() => {
    setError('');
    api
      .get<Answer>('/admin/message-map/intents', { params: { days, organization_id: company || undefined } })
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load the playbook.')));
  }, [days, company]);
  useEffect(load, [load, reload]);

  const byId = useMemo(() => new Map((data?.intents || []).map((i) => [i.id, i])), [data]);
  const modules = useMemo(() => data?.playbook || [], [data]);

  // What is open and picked: from the address, else the first module and its first journey with a best case.
  const openModule = params.get('module') || modules[0]?.key || '';
  const picked = useMemo(() => {
    const capKey = params.get('cap');
    const journeyKey = params.get('journey');
    for (const m of modules) {
      for (const c of m.capabilities) {
        for (const j of c.journeys) {
          if (capKey ? c.key === capKey && j.key === journeyKey : m.key === openModule && j.best) return { module: m, cap: c, journey: j };
        }
      }
    }
    return null;
  }, [modules, params, openModule]);

  if (error) return <div className="card" style={{ color: 'var(--error)' }}>{error}</div>;
  if (!data) return <div className="card" style={muted}>Loading…</div>;

  const journeys = modules.reduce((n, m) => n + m.capabilities.reduce((k, c) => k + c.journeys.length, 0), 0);
  const missing = modules.reduce((n, m) => n + m.missing, 0);
  // The runs to step through: the shown example first (pinned or scored), then the other clean runs.
  const runs = picked ? [...new Set([picked.journey.best, ...picked.journey.candidates].filter((x): x is string => !!x))] : [];
  const runId = runs.includes(params.get('run') || '') ? params.get('run')! : runs[0];
  const best = runId ? byId.get(runId) : undefined;
  const at = runs.indexOf(runId || '');
  const pinnedHere = !!picked?.journey.pinned?.in_window && !!best && best.messages[0] === picked.journey.pinned.message_id;

  const pinWrite = (pin: boolean) => {
    if (!picked || !best) return;
    const url = `/admin/message-map/pins/${encodeURIComponent(picked.cap.key)}/${encodeURIComponent(picked.journey.key)}`;
    setBusy(true);
    setPinError('');
    (pin ? api.put(url, { message_id: best.messages[0] }) : api.delete(url))
      .then(() => {
        set({ run: '' });
        load();
      })
      .catch((err) => setPinError(getErrorMessage(err, pin ? 'Could not pin it.' : 'Could not unpin it.')))
      .finally(() => setBusy(false));
  };

  return (
    <div className="ww-grid">
      <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        <section className="card" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '12px 14px' }}>
          <h2 style={{ fontSize: 15, margin: 0 }}>How each module should work</h2>
          <span style={{ color: 'var(--neutral-400)', display: 'inline-flex', cursor: 'help' }} title={`The best real conversation of the last ${days} ${days === 1 ? 'day' : 'days'} for each way people ask: it finished, nobody corrected it, Mesiri asked nothing it did not need, then the fewest messages and the fastest reply. Beside it, how many real requests of that kind end the same way.`}>
            <Info size={14} />
          </span>
          <span style={{ ...muted, marginLeft: 'auto' }}>
            {journeys} ways of asking{missing > 0 && <span style={{ color: 'var(--warning)' }}> · {missing} with no example</span>}
          </span>
        </section>

        {modules.length === 0 && <div className="card" style={muted}>No requests in this window.</div>}
        {modules.map((m) => {
          const open = openModule === m.key;
          return (
            <section key={m.key} className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <button className="ww-pb-head" aria-expanded={open} onClick={() => set({ module: open ? '_none' : m.key, cap: '', journey: '' })}>
                <span style={{ color: 'var(--neutral-400)' }}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
                <span style={{ fontWeight: 600, fontSize: 14.5, color: 'var(--neutral-900)' }}>{m.label}</span>
                {m.missing > 0 && <span style={{ ...muted, color: 'var(--warning)', marginLeft: 'auto' }}>{m.missing} with no example</span>}
              </button>
              {open && m.capabilities.map((c) => (
                <div key={c.key} className="ww-pb-cap">
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--neutral-900)' }}>{c.name}</span>
                    <span className="ww-tool" style={{ marginTop: 0 }}>{c.tool}</span>
                  </div>
                  <div className="ww-pb-journeys">
                    {c.journeys.map((j) => {
                      const on = picked?.cap.key === c.key && picked.journey.key === j.key;
                      return (
                        <button
                          key={j.key}
                          className={`ww-pb-row${on ? ' on' : ''}${j.best ? '' : ' none'}`}
                          aria-pressed={on}
                          title={JOURNEY_NOTE[j.key]}
                          onClick={() => { set({ module: m.key, cap: c.key, journey: j.key, run: '' }); showPanel(); }}
                        >
                          <span style={{ fontSize: 13, fontWeight: 550, color: 'var(--neutral-900)' }}>{j.label}</span>
                          <span style={{ fontSize: 12, color: j.best ? 'var(--neutral-600)' : 'var(--warning)', fontVariantNumeric: 'tabular-nums' }}>
                            {j.best ? `${share(j.same_end, j.count)} of ${j.count}` : 'No example yet'}
                            {j.pinned?.in_window && <Pin size={11} style={{ marginLeft: 6, verticalAlign: -1 }} aria-label="pinned" />}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </section>
          );
        })}
      </div>

      <aside className="ww-side ww-side-health" id="ww-panel">
        {picked ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <div className="card" style={{ padding: '10px 14px' }} title={JOURNEY_NOTE[picked.journey.key]}>
              <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--neutral-900)' }}>{picked.journey.label}</div>
              <div style={{ ...muted, fontSize: 12, marginTop: 2 }}>
                {picked.cap.name} · {picked.journey.same_end} of {picked.journey.count} end this way{best && ` · ${when(best.started_at)}`}
              </div>
              {best && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                  {runs.length > 1 && (
                    <>
                      <button className="ww-copy" aria-label="Previous run" disabled={at <= 0} onClick={() => set({ run: runs[at - 1] })}><ChevronLeft size={13} /></button>
                      <span style={{ ...muted, fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>{at + 1} / {runs.length}</span>
                      <button className="ww-copy" aria-label="Next run" disabled={at >= runs.length - 1} onClick={() => set({ run: runs[at + 1] })}><ChevronRight size={13} /></button>
                    </>
                  )}
                  {data.pins_ok && (pinnedHere ? (
                    <button className="ww-copy" disabled={busy} onClick={() => pinWrite(false)} title={`Pinned by ${picked.journey.pinned?.by || 'an admin'}. Unpin to show the scored pick.`}>
                      <PinOff size={12} /> Pinned · unpin
                    </button>
                  ) : (
                    <button className="ww-copy" disabled={busy} onClick={() => pinWrite(true)} title="Show this one as the example of this row">
                      <Pin size={12} /> Pin as example
                    </button>
                  ))}
                  {picked.journey.pinned && !picked.journey.pinned.in_window && (
                    <span style={{ ...muted, fontSize: 11.5 }} title="The pinned conversation is older than this window">pinned one not in window</span>
                  )}
                </div>
              )}
              {pinError && <div style={{ color: 'var(--error)', fontSize: 12, marginTop: 6 }}>{pinError}</div>}
            </div>
            {best ? (
              <Chat messageId={best.messages[0]} highlight={best.messages} />
            ) : (
              <div className="card" style={{ ...muted, color: 'var(--warning)' }}>No clean example in this window.</div>
            )}
          </div>
        ) : (
          <div className="card" style={{ ...muted, textAlign: 'center', padding: 'var(--space-10) var(--space-5)' }}>
            Pick a row to see its best conversation.
          </div>
        )}
      </aside>
    </div>
  );
}
