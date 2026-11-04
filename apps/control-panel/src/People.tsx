// SA-24: find a person across every company by name, email or WhatsApp number.
// A company's Users tab lists only that company; this answers "where is this
// number?" without opening every company or writing SQL. The number matches on
// its digits, so "79077 93657" and "+91 7907793657" find the same person.
// SA-25: a number also shows the free trials it started, deleted companies
// included, since that record (not a user) is what refuses a second trial.

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';
import { api } from './api';

interface PersonMatch {
  id: string;
  full_name: string;
  email: string | null;
  whatsapp_number: string | null;
  role: string;
  status: string;
  organization_id: string | null;
  company: string | null;
}

interface SignupTry {
  at: string;
  phone: string;
  signup_source: string;
  outcome: string;
  reason: string | null;
  flags: string[];
}

/** SS-25: why a signup was refused, in plain words. */
const REASONS: Record<string, string> = {
  previous_trial: 'Trial already used',
  daily_limit: 'Daily signup limit',
  ip_limit: 'Too many numbers from one place',
  country_not_allowed: 'Not an Indian number',
  signup_closed: 'Signup switched off',
};

interface TrialUse {
  number: string | null;
  company: string;
  started_at: string;
  signup_source: string | null;
  organization_id: string | null;
  company_exists: boolean;
  new_trial_from: string | null;
  allowed_at: string | null;
  deleted_at: string | null;
  trial_left_seconds: number | null;
}

/** SS-24: "5 days 3 hours", "7 hours": what is left of a deleted company's trial. */
const leftLabel = (seconds: number) => {
  const hours = Math.floor(seconds / 3600);
  const days = Math.floor(hours / 24);
  const rest = hours % 24;
  const parts = days ? [`${days} day${days === 1 ? '' : 's'}`] : [];
  if (rest || !days) parts.push(`${rest} hour${rest === 1 ? '' : 's'}`);
  return parts.join(' ');
};

const MIN_QUERY = 3;
const MIN_DIGITS = 4;

const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });

const statusBadgeClass = (status: string) =>
  (status || '').toLowerCase() === 'active' ? 'badge-success' : 'badge-warning';

export default function People() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PersonMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trials, setTrials] = useState<TrialUse[]>([]);
  const [attempts, setAttempts] = useState<SignupTry[]>([]);
  // SA-26: "Allow a new trial" asks once more before it acts; `reload` refreshes the rows after.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [allowing, setAllowing] = useState(false);
  const [allowError, setAllowError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  // SS-25: nothing typed lists everyone recent (people, every trial, every signup attempt),
  // so a number can be found without knowing it; 1-2 characters wait for more.
  const browsing = query.trim().length === 0;
  const tooShort = !browsing && query.trim().length < MIN_QUERY;
  const isNumber = query.replace(/\D/g, '').length >= MIN_DIGITS;
  const showTrials = browsing || isNumber;

  useEffect(() => {
    if (tooShort) {
      setResults([]);
      setTrials([]);
      setAttempts([]);
      setError(null);
      return;
    }
    let stale = false;
    const t = setTimeout(() => {
      setLoading(true);
      const q = query.trim();
      const people = api.get<PersonMatch[]>('/admin/people/search', { params: { q } });
      const used = showTrials
        ? api.get<TrialUse[]>('/admin/people/trials', { params: { q } }).then((res) => res.data)
        : Promise.resolve([] as TrialUse[]);
      const tried = showTrials
        ? api.get<SignupTry[]>('/admin/people/attempts', { params: { q } }).then((res) => res.data)
        : Promise.resolve([] as SignupTry[]);
      Promise.all([people, used, tried])
        .then(([res, trialRows, attemptRows]) => {
          if (stale) return;
          setResults(res.data);
          setTrials(trialRows);
          setAttempts(attemptRows);
          setError(null);
        })
        .catch((err) => !stale && setError(err.response?.data?.detail || 'Search failed'))
        .finally(() => !stale && setLoading(false));
    }, 300);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [query, tooShort, showTrials, reload]);

  const allowTrial = (number: string) => {
    setAllowing(true);
    setAllowError(null);
    api
      .post('/admin/people/trials/allow', { number })
      .then(() => {
        setConfirming(null);
        setReload((n) => n + 1);
      })
      .catch((err) => setAllowError(err.response?.data?.detail || 'Could not allow a new trial'))
      .finally(() => setAllowing(false));
  };

  // The newest trial of each number is the one that limits it, so only that row gets the button.
  const newestFor = new Map<string, string>();
  for (const t of trials) {
    const key = (t.number || '').replace(/\D/g, '');
    if (key && !newestFor.has(key)) newestFor.set(key, t.started_at);
  }

  /** Clicking a number searches it: its people, trials and attempts together. */
  const searchNumber = (number: string) => setQuery(number.replace(/\D/g, ''));

  const open = (p: PersonMatch) => {
    if (p.organization_id) navigate(`/organizations/${p.organization_id}`);
    else navigate('/users');
  };

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1000px' }}>
      <header style={{ marginBottom: 'var(--space-6)' }}>
        <h1>Find a person</h1>
        <p className="subtitle">
          Search every company by name, email or WhatsApp number. Deactivated and suspended people are included.
        </p>
      </header>

      <div style={{ position: 'relative', marginBottom: 'var(--space-4)', maxWidth: '480px' }}>
        <Search
          size={16}
          style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--neutral-400)' }}
        />
        <input
          autoFocus
          type="search"
          className="form-input"
          style={{ paddingLeft: '36px' }}
          placeholder="Name, email or number (e.g. 79077 93657)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search people"
        />
      </div>

      {browsing && <h2 style={{ fontSize: '16px', marginBottom: 'var(--space-3)' }}>People added most recently</h2>}
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Company</th>
              <th>WhatsApp</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {tooShort ? (
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Type at least {MIN_QUERY} characters.</td></tr>
            ) : error ? (
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--error)' }}>{error}</td></tr>
            ) : loading && results.length === 0 ? (
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Searching…</td></tr>
            ) : results.length === 0 ? (
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>
                {browsing ? 'No people yet.' : isNumber ? 'No user has this number now.' : `No one matches “${query.trim()}”.`}
              </td></tr>
            ) : (
              results.map((p) => (
                <tr key={p.id} onClick={() => open(p)} style={{ cursor: 'pointer' }} title="Open">
                  <td style={{ fontWeight: 500, color: 'var(--neutral-900)' }}>{p.full_name || '—'}</td>
                  <td>{p.company ?? <span style={{ color: 'var(--neutral-500)' }}>Platform admin</span>}</td>
                  <td>
                    {p.whatsapp_number ? (
                      <button className="link-button" style={_numberLink} onClick={(e) => { e.stopPropagation(); searchNumber(p.whatsapp_number || ''); }}>
                        {p.whatsapp_number}
                      </button>
                    ) : '—'}
                  </td>
                  <td>{p.email || '—'}</td>
                  <td>{p.role || '—'}</td>
                  <td><span className={`badge ${statusBadgeClass(p.status)}`}>{p.status}</span></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {!browsing && results.length >= 25 && (
        <p style={{ fontSize: '13px', color: 'var(--neutral-500)', marginTop: 'var(--space-3)' }}>
          Showing the first 25. Type more to narrow it down.
        </p>
      )}

      {showTrials && !tooShort && !error && (
        <section style={{ marginTop: 'var(--space-6)' }}>
          <h2 style={{ fontSize: '16px', marginBottom: 'var(--space-2)' }}>
            {browsing ? 'Every free trial started' : 'Free trials started by this number'}
          </h2>
          <p className="subtitle" style={{ marginBottom: 'var(--space-3)' }}>
            One free trial per number. This record stays when the company is deleted: if the number signs up again, it gets the normal setup with only the rest of that trial (7 days, deleted after 2: 5 days left); a trial used up is refused.
            <strong> Allow a new trial</strong> lets that number start one more (recorded in the audit log); the new trial limits it again.
          </p>
          {allowError && <p style={{ color: 'var(--error)', fontSize: '13px', marginBottom: 'var(--space-3)' }}>{allowError}</p>}
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Number</th>
                  <th>Started</th>
                  <th>Source</th>
                  <th>Company now</th>
                  <th>New trial possible from</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && trials.length === 0 ? (
                  <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Searching…</td></tr>
                ) : trials.length === 0 ? (
                  <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>{browsing ? 'No free trials yet.' : 'This number never started a free trial.'}</td></tr>
                ) : (
                  trials.map((t) => {
                    const open = t.new_trial_from === null || new Date(t.new_trial_from) <= new Date();
                    const number = t.number || '';
                    const limits = !open && newestFor.get(number.replace(/\D/g, '')) === t.started_at;
                    const key = `${t.started_at}-${t.company}`;
                    return (
                      <tr
                        key={key}
                        onClick={t.organization_id ? () => navigate(`/organizations/${t.organization_id}`) : undefined}
                        style={{ cursor: t.organization_id ? 'pointer' : 'default' }}
                      >
                        <td style={{ fontWeight: 500, color: 'var(--neutral-900)' }}>{t.company || '—'}</td>
                        <td>
                          {t.number ? (
                            <button className="link-button" style={_numberLink} onClick={(e) => { e.stopPropagation(); searchNumber(t.number || ''); }}>
                              {t.number}
                            </button>
                          ) : '—'}
                        </td>
                        <td>{day(t.started_at)}</td>
                        <td>{t.signup_source || '—'}</td>
                        <td>
                          <span className={`badge ${t.company_exists ? 'badge-success' : 'badge-warning'}`}>
                            {t.company_exists ? 'exists' : 'deleted'}
                          </span>
                          {t.deleted_at && (
                            <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>on {day(t.deleted_at)}</div>
                          )}
                        </td>
                        <td>
                          {t.new_trial_from === null ? 'Any time (rule off)' : open ? 'Now' : day(t.new_trial_from)}
                          {t.allowed_at ? (
                            <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Allowed {day(t.allowed_at)}: a full trial</div>
                          ) : t.trial_left_seconds !== null && t.trial_left_seconds > 0 ? (
                            <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>with {leftLabel(t.trial_left_seconds)} of its trial left</div>
                          ) : t.trial_left_seconds === 0 ? (
                            <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>its trial was used up</div>
                          ) : null}
                        </td>
                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }} onClick={(e) => e.stopPropagation()}>
                          {limits && confirming !== key && (
                            <button className="btn-secondary" style={{ padding: '4px 10px', fontSize: '13px' }} onClick={() => setConfirming(key)}>
                              Allow a new trial
                            </button>
                          )}
                          {limits && confirming === key && (
                            <span style={{ display: 'inline-flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                              <button className="btn-secondary" style={{ padding: '4px 10px', fontSize: '13px' }} disabled={allowing} onClick={() => setConfirming(null)}>
                                Cancel
                              </button>
                              <button className="btn-primary" style={{ padding: '4px 10px', fontSize: '13px' }} disabled={allowing} onClick={() => allowTrial(number)}>
                                {allowing ? 'Allowing…' : `Yes, allow +${number.replace(/\D/g, '')}`}
                              </button>
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {showTrials && !tooShort && !error && (
        <section style={{ marginTop: 'var(--space-6)' }}>
          <h2 style={{ fontSize: '16px', marginBottom: 'var(--space-2)' }}>
            {browsing ? 'Recent signup attempts' : 'Signup attempts from this number'}
          </h2>
          <p className="subtitle" style={{ marginBottom: 'var(--space-3)' }}>
            Every time someone tried to start a free trial on WhatsApp or the web, and what happened: refused ones show why.
          </p>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Number</th>
                  <th>Source</th>
                  <th>Outcome</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {loading && attempts.length === 0 ? (
                  <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Searching…</td></tr>
                ) : attempts.length === 0 ? (
                  <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>No signup attempts.</td></tr>
                ) : (
                  attempts.map((a, i) => (
                    <tr key={`${a.at}-${a.phone}-${i}`}>
                      <td style={{ whiteSpace: 'nowrap' }}>{new Date(a.at).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}</td>
                      <td>
                        <button className="link-button" style={_numberLink} onClick={() => searchNumber(a.phone)}>
                          {a.phone}
                        </button>
                      </td>
                      <td>{a.signup_source}</td>
                      <td>
                        <span className={`badge ${a.outcome === 'refused' ? 'badge-warning' : 'badge-success'}`}>{a.outcome}</span>
                      </td>
                      <td>{a.reason ? REASONS[a.reason] || a.reason : '—'}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

/** A number that searches itself when clicked; looks like plain text with an underline. */
const _numberLink: React.CSSProperties = {
  background: 'none',
  border: 'none',
  padding: 0,
  color: 'inherit',
  textDecoration: 'underline dotted',
  cursor: 'pointer',
  font: 'inherit',
};
