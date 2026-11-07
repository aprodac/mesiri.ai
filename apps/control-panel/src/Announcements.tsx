import { useCallback, useEffect, useMemo, useState } from 'react';
import { ImagePlus, Megaphone, Plus, Send, Trash2, Users } from 'lucide-react';
import { api } from './api';
import { getErrorMessage, useToast } from './Toast';

// SA-37: a message from the Mesiri team to the people of every company, on WhatsApp. Write it once (words and
// up to four pictures), choose who gets it, see how many it reaches, send. Delivery follows the sender's rules:
// people who messaged Mesiri in the last 24 hours get it within a minute; the others when they next message
// (up to the hold), or by the template once Meta approves it. Every send is in the admin audit log.

interface Announcement {
  id: string;
  title: string;
  message: string;
  images: number;
  hold_days: number;
  created_at: string;
  updated_at: string;
  sends: { at: string; by: string; people: number; queued: number; roles: string[]; organization_ids: string[] }[];
  deliveries: Record<string, number>;
}

interface Reach {
  people: number;
  in_window: number;
  companies: { organization_id: string; name: string; status: string; people: number; in_window: number }[];
}

type RoleGroup = 'all' | 'office' | 'site';

const ROLE_WORDS: Record<RoleGroup, string> = { all: 'Everyone', office: 'Office (admin, owner, PM, finance)', site: 'Site people' };

const STATE_WORDS: Record<string, [string, string]> = {
  sent: ['Delivered', 'badge-success'],
  pending: ['Going out', 'badge-info'],
  waiting_window: ['Waits for their next message', 'badge-warning'],
};

function stateLabel(state: string): [string, string] {
  if (STATE_WORDS[state]) return STATE_WORDS[state];
  const reason = state.replace(/^skipped:/, '');
  const words: Record<string, string> = {
    expired_waiting_for_window: 'Did not message in time',
    expired_after_template: 'Got the template, never replied',
    no_resolvable_recipient: 'No WhatsApp number',
    opted_out: 'Opted out',
    send_failed: 'WhatsApp refused it',
  };
  return [`Not sent: ${words[reason] ?? reason}`, 'badge-error'];
}

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

/** WhatsApp's own formatting, as the person will see it: *bold*, _italic_, line breaks. */
function WhatsAppText({ text }: { text: string }) {
  return (
    <>
      {text.split('\n').map((line, i) => (
        <div key={i} style={{ minHeight: '1.2em' }}>
          {line.split(/(\*[^*\n]+\*|_[^_\n]+_)/g).map((part, j) =>
            /^\*[^*]+\*$/.test(part) ? <strong key={j}>{part.slice(1, -1)}</strong>
              : /^_[^_]+_$/.test(part) ? <em key={j}>{part.slice(1, -1)}</em>
              : <span key={j}>{part}</span>,
          )}
        </div>
      ))}
    </>
  );
}

function usePictures(announcement: Announcement | null) {
  const [urls, setUrls] = useState<string[]>([]);
  useEffect(() => {
    let alive = true;
    const made: string[] = [];
    if (!announcement || !announcement.images) {
      setUrls([]);
      return;
    }
    Promise.all(
      Array.from({ length: announcement.images }, (_, i) =>
        api.get(`/admin/announcements/${announcement.id}/images/${i}`, { responseType: 'blob' }).then((r) => {
          const url = URL.createObjectURL(r.data as Blob);
          made.push(url);
          return url;
        }),
      ),
    ).then((list) => alive && setUrls(list)).catch(() => alive && setUrls([]));
    return () => {
      alive = false;
      made.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [announcement?.id, announcement?.images, announcement?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps
  return urls;
}

export default function Announcements() {
  const { showToast } = useToast();
  const [items, setItems] = useState<Announcement[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState({ title: '', message: '', hold_days: 7 });
  const [roles, setRoles] = useState<RoleGroup>('all');
  const [picked, setPicked] = useState<string[]>([]); // empty = every company
  const [reach, setReach] = useState<Reach | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (select?: string) => {
    try {
      const res = await api.get<{ items: Announcement[] }>('/admin/announcements');
      setItems(res.data.items);
      const id = select ?? selectedId ?? res.data.items[0]?.id ?? null;
      setSelectedId(id);
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not load announcements'), 'error');
    }
  }, [selectedId, showToast]);

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const current = useMemo(() => items?.find((a) => a.id === selectedId) ?? null, [items, selectedId]);
  const pictures = usePictures(current);
  useEffect(() => {
    if (current) setDraft({ title: current.title, message: current.message, hold_days: current.hold_days });
    setConfirming(false);
  }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const audience = useMemo(
    () => ({ organization_ids: picked, roles: roles === 'all' ? [] : [roles] }),
    [picked, roles],
  );
  useEffect(() => {
    api.post<Reach>('/admin/announcements/audience', audience).then((r) => setReach(r.data)).catch(() => setReach(null));
    setConfirming(false);
  }, [audience]);
  const [allCompanies, setAllCompanies] = useState<Reach['companies']>([]);
  useEffect(() => {
    api.post<Reach>('/admin/announcements/audience', { organization_ids: [], roles: [] }).then((r) => setAllCompanies(r.data.companies)).catch(() => {});
  }, []);

  const dirty = !!current && (draft.title !== current.title || draft.message !== current.message || draft.hold_days !== current.hold_days);

  async function save(): Promise<string | null> {
    setBusy(true);
    try {
      if (!current) {
        const res = await api.post<Announcement>('/admin/announcements', draft);
        await load(res.data.id);
        return res.data.id;
      }
      if (dirty) await api.patch(`/admin/announcements/${current.id}`, draft);
      await load(current.id);
      return current.id;
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not save'), 'error');
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function addPictures(files: FileList | null) {
    if (!files?.length) return;
    const id = current?.id ?? (await save());
    if (!id) return;
    setBusy(true);
    try {
      for (const file of Array.from(files)) {
        const data = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
          reader.onerror = () => reject(reader.error);
          reader.readAsDataURL(file);
        });
        await api.post(`/admin/announcements/${id}/images`, { content_type: file.type, data_base64: data });
      }
      await load(id);
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not add the picture'), 'error');
      await load(id);
    } finally {
      setBusy(false);
    }
  }

  async function removePicture(index: number) {
    if (!current) return;
    await api.delete(`/admin/announcements/${current.id}/images/${index}`);
    await load(current.id);
  }

  async function send() {
    if (!current) return;
    if (dirty && !(await save())) return;
    setBusy(true);
    try {
      const res = await api.post<{ queued: number; already: number; in_window: number }>(`/admin/announcements/${current.id}/send`, audience);
      const { queued, already } = res.data;
      showToast(`Queued for ${queued} ${queued === 1 ? 'person' : 'people'}${already ? ` (${already} already had it today)` : ''}. Going out now.`, 'success');
      setConfirming(false);
      await load(current.id);
    } catch (err) {
      showToast(getErrorMessage(err, 'Could not send'), 'error');
    } finally {
      setBusy(false);
    }
  }

  function startNew() {
    setSelectedId(null);
    setDraft({ title: '', message: '', hold_days: 7 });
  }

  const later = reach ? reach.people - reach.in_window : 0;
  const canSend = !!current && !!reach?.people && draft.title.trim() && draft.message.trim();

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1200px' }}>
      <header style={{ marginBottom: 'var(--space-6)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 10 }}><Megaphone size={22} /> Announcements</h1>
          <p className="subtitle">A message from the Mesiri team to the people of every company, on WhatsApp.</p>
        </div>
        <button className="btn-secondary" onClick={startNew} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Plus size={16} /> New announcement</button>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 280px) minmax(0, 1fr)', gap: 'var(--space-6)', alignItems: 'start' }} className="announcements-grid">
        {/* History */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          {items === null && <div className="card" style={{ color: 'var(--neutral-500)' }}>Loading…</div>}
          {items?.length === 0 && <div className="card" style={{ color: 'var(--neutral-500)' }}>None yet.</div>}
          {items?.map((a) => {
            const delivered = a.deliveries.sent ?? 0;
            const total = Object.values(a.deliveries).reduce((n, v) => n + v, 0);
            return (
              <button
                key={a.id}
                onClick={() => setSelectedId(a.id)}
                className="card"
                style={{ textAlign: 'left', cursor: 'pointer', padding: 'var(--space-4)', border: a.id === selectedId ? '2px solid var(--brand)' : undefined, background: a.id === selectedId ? 'var(--brand-soft)' : undefined }}
              >
                <div style={{ fontWeight: 600, color: 'var(--neutral-900)' }}>{a.title}</div>
                <div style={{ fontSize: 12, color: 'var(--neutral-500)', marginTop: 2 }}>
                  {a.sends.length ? `Sent ${when(a.sends[a.sends.length - 1].at)}` : 'Draft, not sent'}
                </div>
                {total > 0 && (
                  <div style={{ marginTop: 8, height: 6, borderRadius: 999, background: 'var(--neutral-200)', overflow: 'hidden', display: 'flex' }}>
                    <span style={{ width: `${(delivered / total) * 100}%`, background: 'var(--success)' }} />
                    <span style={{ width: `${((a.deliveries.waiting_window ?? 0) / total) * 100}%`, background: 'var(--brand)' }} />
                  </div>
                )}
                {total > 0 && <div style={{ fontSize: 12, color: 'var(--neutral-600)', marginTop: 4 }}>{delivered} of {total} delivered</div>}
              </button>
            );
          })}
        </div>

        {/* Editor */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
          <div className="card" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(260px, 340px)', gap: 'var(--space-6)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontWeight: 500, fontSize: 13 }}>
                Title <span style={{ fontWeight: 400, color: 'var(--neutral-500)' }}>(also the line in the template: "There is something new in Mesiri: …")</span>
                <input className="form-input" maxLength={60} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="Material Requests" />
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontWeight: 500, fontSize: 13 }}>
                Message <span style={{ fontWeight: 400, color: 'var(--neutral-500)' }}>*bold*, _italic_; {draft.message.length}/3500</span>
                <textarea className="form-input" rows={12} maxLength={3500} value={draft.message} onChange={(e) => setDraft({ ...draft, message: e.target.value })} style={{ fontFamily: 'inherit', resize: 'vertical', height: 'auto', minHeight: 260, lineHeight: 1.45, padding: '10px 12px' }} />
              </label>
              <div>
                <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 6 }}>Pictures <span style={{ fontWeight: 400, color: 'var(--neutral-500)' }}>(sent before the message; up to 4)</span></div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {pictures.map((url, i) => (
                    <div key={url} style={{ position: 'relative' }}>
                      <img src={url} alt={`Picture ${i + 1}`} style={{ width: 84, height: 84, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--border-default)' }} />
                      <button aria-label={`Remove picture ${i + 1}`} onClick={() => removePicture(i)} style={{ position: 'absolute', top: 4, right: 4, background: 'rgba(0,0,0,0.6)', color: '#fff', border: 0, borderRadius: 6, padding: 3, cursor: 'pointer' }}><Trash2 size={13} /></button>
                    </div>
                  ))}
                  {(current?.images ?? 0) < 4 && (
                    <label style={{ width: 84, height: 84, border: '1.5px dashed var(--border-strong)', borderRadius: 8, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4, fontSize: 12, color: 'var(--neutral-600)', cursor: 'pointer' }}>
                      <ImagePlus size={18} /> Add
                      <input type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={(e) => { addPictures(e.target.files); e.target.value = ''; }} />
                    </label>
                  )}
                </div>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                Someone who hasn't messaged Mesiri today gets it when they next do, for up to
                <select className="form-input" value={draft.hold_days} onChange={(e) => setDraft({ ...draft, hold_days: Number(e.target.value) })} style={{ width: 'auto' }}>
                  {[1, 3, 7, 14].map((d) => <option key={d} value={d}>{d} day{d > 1 ? 's' : ''}</option>)}
                </select>
              </label>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn-secondary" disabled={busy || (!!current && !dirty) || !draft.title.trim() || !draft.message.trim()} onClick={save}>{current ? 'Save changes' : 'Save draft'}</button>
              </div>
            </div>
            {/* Preview */}
            <div>
              <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 6 }}>As they'll see it</div>
              <div style={{ background: '#E5DDD5', borderRadius: 12, padding: 12, display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 520, overflowY: 'auto' }}>
                {pictures.map((url) => <img key={url} src={url} alt="" style={{ width: '75%', borderRadius: 8, alignSelf: 'flex-start', border: '3px solid #fff' }} />)}
                <div style={{ background: '#fff', borderRadius: '0 10px 10px 10px', padding: '8px 10px', fontSize: 13.5, lineHeight: 1.4, color: '#111', alignSelf: 'flex-start', maxWidth: '92%', boxShadow: '0 1px 1px rgba(0,0,0,0.1)' }}>
                  {draft.message ? <WhatsAppText text={draft.message} /> : <span style={{ color: '#999' }}>The message…</span>}
                </div>
              </div>
            </div>
          </div>

          {/* Audience and send */}
          {current && (
            <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 16 }}><Users size={18} /> Who gets it</h2>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {(Object.keys(ROLE_WORDS) as RoleGroup[]).map((r) => (
                  <button key={r} onClick={() => setRoles(r)} className={roles === r ? 'btn-primary' : 'btn-secondary'} style={{ padding: '6px 12px', fontSize: 13 }}>{ROLE_WORDS[r]}</button>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button onClick={() => setPicked([])} className={picked.length === 0 ? 'btn-primary' : 'btn-secondary'} style={{ padding: '6px 12px', fontSize: 13 }}>Every company</button>
                {allCompanies.map((c) => {
                  const on = picked.includes(c.organization_id);
                  return (
                    <button key={c.organization_id} onClick={() => setPicked(on ? picked.filter((x) => x !== c.organization_id) : [...picked, c.organization_id])} className={on ? 'btn-primary' : 'btn-secondary'} style={{ padding: '6px 12px', fontSize: 13 }}>
                      {c.name} <span style={{ opacity: 0.7 }}>· {c.people}</span>{c.status === 'trial' && <span className="badge badge-info" style={{ marginLeft: 6 }}>trial</span>}
                    </button>
                  );
                })}
              </div>
              {reach && (
                <div style={{ display: 'flex', gap: 'var(--space-6)', flexWrap: 'wrap', padding: 'var(--space-4)', background: 'var(--surface-secondary)', borderRadius: 10 }}>
                  <div><div style={{ fontSize: 28, fontWeight: 600 }}>{reach.people}</div><div style={{ fontSize: 12, color: 'var(--neutral-600)' }}>people in {reach.companies.length} {reach.companies.length === 1 ? 'company' : 'companies'}</div></div>
                  <div><div style={{ fontSize: 28, fontWeight: 600, color: 'var(--success)' }}>{reach.in_window}</div><div style={{ fontSize: 12, color: 'var(--neutral-600)' }}>get it within a minute<br />(messaged in the last 24 h)</div></div>
                  <div><div style={{ fontSize: 28, fontWeight: 600, color: 'var(--brand-ink)' }}>{later}</div><div style={{ fontSize: 12, color: 'var(--neutral-600)' }}>when they next message<br />(up to {draft.hold_days} day{draft.hold_days > 1 ? 's' : ''})</div></div>
                </div>
              )}
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                {!confirming ? (
                  <button className="btn-primary" disabled={!canSend || busy} onClick={() => setConfirming(true)} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <Send size={16} /> Send to {reach?.people ?? 0} {reach?.people === 1 ? 'person' : 'people'}
                  </button>
                ) : (
                  <>
                    <span style={{ fontWeight: 500 }}>Send "{draft.title}" to {reach?.people} people in {reach?.companies.length} companies? This can't be taken back.</span>
                    <button className="btn-primary" disabled={busy} onClick={send} style={{ background: 'var(--brand)', color: 'var(--neutral-900)' }}>Yes, send it</button>
                    <button className="btn-secondary" onClick={() => setConfirming(false)}>Back</button>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Delivery */}
          {current && Object.keys(current.deliveries).length > 0 && (
            <div className="card">
              <h2 style={{ fontSize: 16, marginBottom: 'var(--space-3)' }}>Delivery</h2>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {Object.entries(current.deliveries).sort((a, b) => b[1] - a[1]).map(([state, n]) => {
                  const [label, badge] = stateLabel(state);
                  return <span key={state} className={`badge ${badge}`}>{label}: {n}</span>;
                })}
              </div>
              <div style={{ fontSize: 12, color: 'var(--neutral-500)', marginTop: 'var(--space-3)' }}>
                {current.sends.map((s) => `${when(s.at)} by ${s.by}: ${s.queued} queued`).join(' · ')}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
