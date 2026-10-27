// SA-05 / SA-23: what Mesiri costs to run -- AI calls and WhatsApp messages,
// in rupees before GST, from the per-call cost rows BE-25 records. A filter
// bar picks the period (today / 7 / 30 / 90 days / custom dates), one company
// or all, the cost type (all / AI / WhatsApp) and a search; tabs pick the view:
// Companies, People, Days, and for one company its Messages and WhatsApp
// sent. Every filter lives in the URL, so a view can be shared. Reads GET
// /admin/costs. Days are Indian calendar days.

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Bot, CalendarRange, MessageCircle, Search, Wallet, X } from 'lucide-react';
import { api } from './api';
import { getErrorMessage } from './Toast';
import { full, indianDay, inr } from './replyFormat';
import {
  CompaniesView,
  DaysView,
  MessagesView,
  PeopleView,
  SentView,
  type CompanyRow,
  type CostType,
  type DayRow,
  type MessageRow,
  type PersonRow,
  type SentRow,
  type Totals,
} from './costViews';

interface CostsResponse {
  from: string;
  to: string;
  organization_id: string | null;
  totals: Totals;
  by_day: DayRow[];
  by_company?: CompanyRow[];
  by_person?: PersonRow[];
  messages?: MessageRow[];
  sent?: SentRow[];
}

interface CompanyOption {
  id: string;
  name: string;
}

const PERIODS = [
  { key: '1', label: 'Today' },
  { key: '7', label: '7 days' },
  { key: '30', label: '30 days' },
  { key: '90', label: '90 days' },
  { key: 'custom', label: 'Custom' },
];

const TYPES: { key: CostType; label: string }[] = [
  { key: 'all', label: 'All costs' },
  { key: 'ai', label: 'AI' },
  { key: 'whatsapp', label: 'WhatsApp' },
];

type View = 'companies' | 'people' | 'days' | 'messages' | 'sent';

/** The money a row is ranked by for the chosen cost type. */
function amount(row: Totals, type: CostType): number {
  return Number(type === 'ai' ? row.ai_cost_inr : type === 'whatsapp' ? row.whatsapp_cost_inr : row.total_cost_inr);
}

/** Does a row have anything of the chosen cost type? */
function has(row: Totals, type: CostType): boolean {
  return type === 'ai' ? row.ai_calls > 0 : type === 'whatsapp' ? row.whatsapp_messages > 0 : true;
}

function rank<T extends Totals>(rows: T[], type: CostType): T[] {
  return rows.filter((r) => has(r, type)).sort((a, b) => amount(b, type) - amount(a, type));
}

export default function Costs() {
  const [params, setParams] = useSearchParams();
  // `days` is the older link form (Overview, company page): keep honouring it.
  const period = params.get('period') || params.get('days') || '7';
  const company = params.get('company');
  const type = (params.get('type') as CostType) || 'all';
  const q = params.get('q') || '';
  const view = (params.get('view') as View) || (company ? 'people' : 'companies');
  const from = period === 'custom' ? params.get('from') || indianDay(6) : indianDay(Number(period) - 1);
  const to = period === 'custom' ? params.get('to') || indianDay(0) : indianDay(0);

  const [data, setData] = useState<CostsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [search, setSearch] = useState(q);

  useEffect(() => setSearch(q), [q]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .get<CostsResponse>('/admin/costs', { params: { from, to, organization_id: company || undefined } })
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, 'Could not load costs')))
      .finally(() => setLoading(false));
  }, [from, to, company]);

  useEffect(() => {
    api
      .get<CompanyOption[]>('/admin/organizations')
      .then((res) => setCompanies([...res.data].sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => setCompanies([]));
  }, []);

  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key);
      else next.set(key, value);
    }
    next.delete('days');
    setParams(next);
  };

  // Search is applied as you type, kept in the URL a moment later.
  useEffect(() => {
    if (search === q) return;
    const t = setTimeout(() => set({ q: search || null }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const companyName = company
    ? (companies.find((c) => c.id === company)?.name ?? params.get('name') ?? 'This company')
    : null;
  const needle = search.trim().toLowerCase();
  const digits = needle.replace(/\D/g, '');
  const matches = (...texts: (string | null | undefined)[]) =>
    !needle || texts.some((t) => (t ?? '').toLowerCase().includes(needle)) || (digits.length >= 3 && texts.some((t) => (t ?? '').replace(/\D/g, '').includes(digits)));

  const lists = useMemo(() => {
    if (!data) return null;
    return {
      companies: rank(data.by_company ?? [], type).filter((c) => matches(c.organization_name)),
      people: rank(data.by_person ?? [], type).filter((p) => matches(p.full_name, p.phone, p.organization_name, p.phone === null ? 'not tied to a person' : '')),
      days: (data.by_day ?? []).filter((d) => has(d, type)),
      messages: type === 'whatsapp' ? [] : (data.messages ?? []).filter((m) => matches(m.text, m.sender, m.message_type)),
      sent: type === 'ai' ? [] : (data.sent ?? []).filter((s) => matches(s.recipient, s.category)),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, type, needle]);

  const tabs: { key: View; label: string; count?: number }[] = [
    ...(company ? [] : [{ key: 'companies' as View, label: 'Companies', count: lists?.companies.length }]),
    { key: 'people', label: 'People', count: lists?.people.length },
    { key: 'days', label: 'Days', count: lists?.days.length },
    ...(company
      ? [
          { key: 'messages' as View, label: 'Messages', count: lists?.messages.length },
          { key: 'sent' as View, label: 'WhatsApp sent', count: lists?.sent.length },
        ]
      : []),
  ];
  const shownView = tabs.some((t) => t.key === view) ? view : tabs[0].key;
  const filtered = period !== '7' || !!company || type !== 'all' || !!q;
  const t = data?.totals;
  const openCompany = (id: string, name: string) => set({ company: id, name, view: 'people' });

  return (
    <div className="animate-fade-in cost-page">
      <header className="cost-head">
        <div>
          <h1>{companyName ? `Costs · ${companyName}` : 'Costs'}</h1>
          <p className="subtitle">AI calls and WhatsApp messages, in rupees before GST. Days are Indian days.</p>
        </div>
      </header>

      {/* Filters */}
      <section className="cost-filters" aria-label="Filters">
        <div className="cost-filter-row">
          <div className="seg cost-period" role="tablist" aria-label="Period">
            {PERIODS.map((p) => (
              <button
                key={p.key}
                role="tab"
                aria-selected={period === p.key}
                className={period === p.key ? 'on' : ''}
                onClick={() => set(p.key === 'custom' ? { period: 'custom', from, to } : { period: p.key, from: null, to: null })}
              >
                {p.key === 'custom' && <CalendarRange size={13} />}
                {p.label}
              </button>
            ))}
          </div>
          {period === 'custom' && (
            <div className="cost-dates">
              <input type="date" className="form-input" value={from} max={to} onChange={(e) => set({ from: e.target.value })} aria-label="From" />
              <span>to</span>
              <input type="date" className="form-input" value={to} min={from} max={indianDay(0)} onChange={(e) => set({ to: e.target.value })} aria-label="To" />
            </div>
          )}
          {filtered && (
            <button className="cost-clear" onClick={() => setParams(new URLSearchParams())}>
              <X size={13} /> Clear filters
            </button>
          )}
        </div>
        <div className="cost-filter-row">
          <select className="form-input cost-company" value={company ?? ''} onChange={(e) => set({ company: e.target.value || null, name: null, view: null })} aria-label="Company">
            <option value="">All companies</option>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <div className="cost-chips" role="radiogroup" aria-label="Cost type">
            {TYPES.map((ty) => (
              <button key={ty.key} role="radio" aria-checked={type === ty.key} className={`cost-chip${type === ty.key ? ' on' : ''}`} onClick={() => set({ type: ty.key === 'all' ? null : ty.key })}>
                {ty.key === 'ai' && <Bot size={13} />}
                {ty.key === 'whatsapp' && <MessageCircle size={13} />}
                {ty.label}
              </button>
            ))}
          </div>
          <label className="cost-search">
            <Search size={14} />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search a person, number or company" aria-label="Search" />
            {search && (
              <button onClick={() => setSearch('')} aria-label="Clear search">
                <X size={13} />
              </button>
            )}
          </label>
        </div>
      </section>

      {error && <div className="ov-error">{error}</div>}

      {t && (
        <div className="cc-kpis" style={{ opacity: loading ? 0.6 : 1 }}>
          <button className={`cc-kpi cost-kpi${type === 'all' ? ' on' : ''}`} onClick={() => set({ type: null })}>
            <span className="cc-kpi-label">
              <Wallet size={14} /> Total
            </span>
            <span className="cc-kpi-value">{inr(t.total_cost_inr)}</span>
            <span className="cc-kpi-sub">{t.unpriced ? `${t.unpriced} unpriced, not included` : `${from === to ? from : `${from} → ${to}`}`}</span>
          </button>
          <button className={`cc-kpi cost-kpi${type === 'ai' ? ' on' : ''}`} onClick={() => set({ type: 'ai' })}>
            <span className="cc-kpi-label">
              <Bot size={14} /> AI
            </span>
            <span className="cc-kpi-value">{inr(t.ai_cost_inr)}</span>
            <span className="cc-kpi-sub">{full(t.ai_calls)} calls</span>
          </button>
          <button className={`cc-kpi cost-kpi${type === 'whatsapp' ? ' on' : ''}`} onClick={() => set({ type: 'whatsapp' })}>
            <span className="cc-kpi-label">
              <MessageCircle size={14} /> WhatsApp
            </span>
            <span className="cc-kpi-value">{inr(t.whatsapp_cost_inr)}</span>
            <span className="cc-kpi-sub">{full(t.whatsapp_messages)} messages sent</span>
          </button>
        </div>
      )}

      {/* Views */}
      <div className="wl-tabs cost-tabs" role="tablist">
        {tabs.map((tab) => (
          <button key={tab.key} role="tab" aria-selected={shownView === tab.key} className={shownView === tab.key ? 'on' : ''} onClick={() => set({ view: tab.key })}>
            {tab.label}
            {tab.count !== undefined && <span>{full(tab.count)}</span>}
          </button>
        ))}
      </div>

      {!data && !error && <p className="oc-empty">Loading…</p>}
      {lists && (
        <div style={{ opacity: loading ? 0.6 : 1, transition: 'opacity var(--transition-fast)' }}>
          {shownView === 'companies' && <CompaniesView rows={lists.companies} type={type} onOpen={openCompany} />}
          {shownView === 'people' && <PeopleView rows={lists.people} type={type} showCompany={!company} onOpenCompany={openCompany} />}
          {shownView === 'days' && <DaysView rows={lists.days} type={type} />}
          {shownView === 'messages' && <MessagesView rows={lists.messages} />}
          {shownView === 'sent' && <SentView rows={lists.sent} />}
          {shownView === 'people' && !company && (data?.by_person?.length ?? 0) >= 500 && (
            <p className="oc-empty">Showing the 500 most expensive people. Pick a company to see all of its people.</p>
          )}
        </div>
      )}
    </div>
  );
}
