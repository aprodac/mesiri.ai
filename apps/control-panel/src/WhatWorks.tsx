// SA-38 / SA-39: What works -- what people ask Mesiri for, how it ends, and where it falls short.
// One page, views on a segmented control, sharing the filters and the WhatsApp panel:
//   Health (default): by module and by what people ask for, judged by request (WhatWorksHealth.tsx);
//   Playbook: how each module should work, the best real conversation per journey (WhatWorksPlaybook.tsx);
//   Patterns: the connections between failures and the actions that make a fix fast (WhatWorksPatterns.tsx);
//   Every message: version 1's list of every kind of message (WhatWorksMessages.tsx).
// The view, window, company and selection live in the address, so a view can be shared.

import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { api } from './api';
import WhatWorksHealth from './WhatWorksHealth';
import WhatWorksMessages from './WhatWorksMessages';
import WhatWorksPatterns from './WhatWorksPatterns';
import WhatWorksPlaybook from './WhatWorksPlaybook';
import { WINDOWS } from './whatWorksShared';

interface CompanyOption {
  id: string;
  name: string;
}

const VIEWS = [
  { key: 'health', label: 'Health', note: 'How each module is doing, by request: what finished, what was left, what failed, and what to fix first.' },
  { key: 'playbook', label: 'Playbook', note: 'How each module should work: the best real conversation for every way people ask, and how often it goes that way.' },
  { key: 'patterns', label: 'Patterns', note: 'The connections between failures: the same cause in many places, where flows leak, what makes it worse, what people do next.' },
  { key: 'messages', label: 'Every message', note: 'Every kind of message people sent, one message at a time, with a search.' },
] as const;
type View = (typeof VIEWS)[number]['key'];

// The address keys that belong to one view only: cleared when the view changes.
const VIEW_KEYS = ['module', 'cap', 'problem', 'intent', 'journey', 'pattern', 'tab', 'message', 'q'];

export default function WhatWorks() {
  const [params, setParams] = useSearchParams();
  const days = Number(params.get('days')) || 14;
  const company = params.get('company') || '';
  const view: View = VIEWS.find((v) => v.key === params.get('view'))?.key || 'health';
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [reload, setReload] = useState(0);

  const set = useCallback(
    (changes: Record<string, string>) => {
      const next = new URLSearchParams(params);
      Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  useEffect(() => {
    api
      .get<CompanyOption[]>('/admin/organizations')
      .then((res) => setCompanies(res.data))
      .catch(() => setCompanies([]));
  }, []);

  const props = { days, company, params, set, reload };

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1400px' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 'var(--space-4)', flexWrap: 'wrap', marginBottom: 'var(--space-5)' }}>
        <div>
          <h1>What works</h1>
          <p className="subtitle">What people ask Mesiri for, how it ends, and what to fix first.</p>
        </div>
        <button className="btn-secondary" onClick={() => setReload((n) => n + 1)}>
          <RefreshCw size={16} /> Refresh
        </button>
      </header>

      <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
        <div className="seg ww-views" role="tablist" aria-label="View">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              role="tab"
              aria-selected={view === v.key}
              title={v.note}
              className={view === v.key ? 'on' : ''}
              onClick={() => set({ view: v.key === 'health' ? '' : v.key, ...Object.fromEntries(VIEW_KEYS.map((k) => [k, ''])) })}
            >
              {v.label}
            </button>
          ))}
        </div>
        <select className="form-input" style={{ height: 36, width: 'auto' }} value={days} onChange={(e) => set({ days: e.target.value })} aria-label="Time window">
          {WINDOWS.map((w) => (
            <option key={w.days} value={w.days}>{w.label}</option>
          ))}
        </select>
        <select className="form-input" style={{ height: 36, width: 'auto', maxWidth: 260 }} value={company} onChange={(e) => set({ company: e.target.value })} aria-label="Company">
          <option value="">All companies</option>
          {companies.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>

      {view === 'health' && <WhatWorksHealth {...props} />}
      {view === 'playbook' && <WhatWorksPlaybook {...props} />}
      {view === 'patterns' && <WhatWorksPatterns {...props} />}
      {view === 'messages' && <WhatWorksMessages {...props} />}
    </div>
  );
}
