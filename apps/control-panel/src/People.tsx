// SA-24: find a person across every company by name, email or WhatsApp number.
// A company's Users tab lists only that company; this answers "where is this
// number?" without opening every company or writing SQL. The number matches on
// its digits, so "79077 93657" and "+91 7907793657" find the same person.

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

const MIN_QUERY = 3;

const statusBadgeClass = (status: string) =>
  (status || '').toLowerCase() === 'active' ? 'badge-success' : 'badge-warning';

export default function People() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PersonMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tooShort = query.trim().length < MIN_QUERY;

  useEffect(() => {
    if (tooShort) {
      setResults([]);
      setError(null);
      return;
    }
    let stale = false;
    const t = setTimeout(() => {
      setLoading(true);
      api
        .get<PersonMatch[]>('/admin/people/search', { params: { q: query.trim() } })
        .then((res) => {
          if (stale) return;
          setResults(res.data);
          setError(null);
        })
        .catch((err) => !stale && setError(err.response?.data?.detail || 'Search failed'))
        .finally(() => !stale && setLoading(false));
    }, 300);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [query, tooShort]);

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
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>No one matches “{query.trim()}”.</td></tr>
            ) : (
              results.map((p) => (
                <tr key={p.id} onClick={() => open(p)} style={{ cursor: 'pointer' }} title="Open">
                  <td style={{ fontWeight: 500, color: 'var(--neutral-900)' }}>{p.full_name || '—'}</td>
                  <td>{p.company ?? <span style={{ color: 'var(--neutral-500)' }}>Platform admin</span>}</td>
                  <td>{p.whatsapp_number || '—'}</td>
                  <td>{p.email || '—'}</td>
                  <td>{p.role || '—'}</td>
                  <td><span className={`badge ${statusBadgeClass(p.status)}`}>{p.status}</span></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {results.length >= 25 && (
        <p style={{ fontSize: '13px', color: 'var(--neutral-500)', marginTop: 'var(--space-3)' }}>
          Showing the first 25. Type more to narrow it down.
        </p>
      )}
    </div>
  );
}
