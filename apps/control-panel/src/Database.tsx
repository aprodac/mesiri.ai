import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowDown, ArrowUp, Play, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { api } from './api';

// SA-15: browse every table and run SQL. Reads are free; a write is a dry
// run (nothing changes, shows the row count) and then "Run write", which the
// server keeps only if it changes that same number of rows. Every SQL read
// and write is in the audit log. Rules: backend database_console.py.

interface TableInfo {
  name: string;
  estimated_rows: number | null;
  size_bytes: number;
}

interface ColumnInfo {
  name: string;
  type: string;
  nullable: boolean;
  default: string | null;
  primary_key: boolean;
}

interface ResultSet {
  columns: string[];
  rows: unknown[][];
  row_count: number | null;
  truncated: boolean;
  duration_ms: number;
  max_rows: number;
}

interface TablePage extends ResultSet {
  table: string;
  column_info: ColumnInfo[];
  offset: number;
}

const PAGE_SIZE = 50;

const fmtBytes = (n: number): string => {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} kB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
};

const fmtCell = (v: unknown): string => {
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
};

const errText = (err: unknown, fallback: string): string => {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail) return JSON.stringify(detail);
  return fallback;
};

function ResultGrid({
  result,
  sortBy,
  sortDesc,
  onSort,
}: {
  result: ResultSet;
  sortBy?: string | null;
  sortDesc?: boolean;
  onSort?: (column: string) => void;
}) {
  if (result.columns.length === 0) {
    return (
      <p style={{ fontSize: '13px', color: 'var(--neutral-500)' }}>
        Done{result.row_count !== null ? `: ${result.row_count} row(s)` : ''} in {result.duration_ms} ms.
      </p>
    );
  }
  return (
    <div className="table-container" style={{ maxHeight: '60vh', overflow: 'auto' }}>
      <table style={{ fontFamily: 'var(--font-mono, monospace)' }}>
        <thead>
          <tr>
            {result.columns.map((c) => (
              <th
                key={c}
                onClick={onSort ? () => onSort(c) : undefined}
                style={{
                  position: 'sticky',
                  top: 0,
                  whiteSpace: 'nowrap',
                  cursor: onSort ? 'pointer' : undefined,
                  zIndex: 1,
                }}
              >
                {c}
                {sortBy === c && (sortDesc ? <ArrowDown size={12} /> : <ArrowUp size={12} />)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i}>
              {row.map((v, j) => {
                const text = fmtCell(v);
                return (
                  <td
                    key={j}
                    title={text.length > 60 ? text : undefined}
                    style={{
                      fontSize: '12px',
                      height: '36px',
                      whiteSpace: 'nowrap',
                      maxWidth: '360px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      color: v === null ? 'var(--neutral-400)' : undefined,
                    }}
                  >
                    {v === null ? 'NULL' : text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BrowseTable({ table }: { table: string }) {
  const [page, setPage] = useState<TablePage | null>(null);
  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [offset, setOffset] = useState(0);
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortDesc, setSortDesc] = useState(true);
  const [filterColumn, setFilterColumn] = useState('');
  const [filterValue, setFilterValue] = useState('');
  const [applied, setApplied] = useState<{ column: string; value: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setOffset(0);
    setSortBy(null);
    setSortDesc(true);
    setFilterColumn('');
    setFilterValue('');
    setApplied(null);
  }, [table]);

  const load = useCallback(() => {
    setLoading(true);
    const params: Record<string, string | number | boolean> = { limit: PAGE_SIZE, offset, desc: sortDesc };
    if (sortBy) params.order_by = sortBy;
    if (applied) {
      params.filter_column = applied.column;
      params.filter_value = applied.value;
    }
    api
      .get<TablePage>(`/admin/database/tables/${encodeURIComponent(table)}`, { params })
      .then((res) => {
        setColumns(res.data.column_info);
        setPage(res.data);
        setError(null);
      })
      .catch((err) => setError(errText(err, 'Failed to load the table')))
      .finally(() => setLoading(false));
  }, [table, offset, sortBy, sortDesc, applied]);

  useEffect(() => {
    load();
  }, [load]);

  const onSort = (column: string) => {
    if (sortBy === column) setSortDesc(!sortDesc);
    else {
      setSortBy(column);
      setSortDesc(true);
    }
    setOffset(0);
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap', marginBottom: 'var(--space-3)' }}>
        <select
          className="form-input"
          style={{ width: 'auto', height: '36px' }}
          value={filterColumn}
          onChange={(e) => setFilterColumn(e.target.value)}
        >
          <option value="">Filter column…</option>
          {columns.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
        <input
          className="form-input"
          style={{ width: '280px', height: '36px' }}
          placeholder="equals (as text)"
          value={filterValue}
          onChange={(e) => setFilterValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && filterColumn) {
              setApplied({ column: filterColumn, value: filterValue });
              setOffset(0);
            }
          }}
        />
        <button
          className="btn-secondary"
          style={{ height: '36px' }}
          disabled={!filterColumn}
          onClick={() => {
            setApplied({ column: filterColumn, value: filterValue });
            setOffset(0);
          }}
        >
          <Search size={14} /> Filter
        </button>
        {applied && (
          <button
            className="btn-secondary"
            style={{ height: '36px' }}
            onClick={() => {
              setApplied(null);
              setFilterValue('');
              setOffset(0);
            }}
          >
            Clear
          </button>
        )}
        <div style={{ flex: 1 }} />
        <button className="btn-secondary" style={{ height: '36px' }} onClick={load}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {columns.length > 0 && (
        <p style={{ fontSize: '12px', color: 'var(--neutral-500)', marginBottom: 'var(--space-3)' }}>
          {columns.map((c, i) => (
            <span key={c.name}>
              {i > 0 && ' · '}
              <strong style={{ color: 'var(--neutral-700)' }}>{c.name}</strong> {c.type}
              {c.primary_key ? ' (PK)' : ''}
            </span>
          ))}
        </p>
      )}

      {error && <p style={{ color: 'var(--error)', marginBottom: 'var(--space-3)' }}>{error}</p>}
      {loading && !page && <p style={{ color: 'var(--neutral-500)' }}>Loading…</p>}
      {page && <ResultGrid result={page} sortBy={sortBy} sortDesc={sortDesc} onSort={onSort} />}

      {page && (
        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', marginTop: 'var(--space-3)' }}>
          <button
            className="btn-secondary"
            style={{ height: '32px' }}
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </button>
          <button
            className="btn-secondary"
            style={{ height: '32px' }}
            disabled={!page.truncated}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
          <span style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>
            Rows {page.rows.length ? offset + 1 : 0}–{offset + page.rows.length} · {page.duration_ms} ms
          </span>
        </div>
      )}
    </div>
  );
}

function SqlConsole({ initialSql }: { initialSql: string }) {
  const [sql, setSql] = useState(initialSql);
  const [result, setResult] = useState<ResultSet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  // The dry run this write would use: only valid for the exact SQL it ran.
  const [dryRun, setDryRun] = useState<{ sql: string; rows: number } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => setSql(initialSql), [initialSql]);

  const run = (mode: 'read' | 'dry_run' | 'write') => {
    if (!sql.trim()) return;
    if (mode === 'write') {
      if (!dryRun || dryRun.sql !== sql) return;
      const ok = window.confirm(
        `Run this write on the LIVE database?\n\nIt will change ${dryRun.rows} row(s). This cannot be undone from here.\n\n${sql.slice(0, 500)}`,
      );
      if (!ok) return;
    }
    setRunning(true);
    setError(null);
    setNotice(null);
    api
      .post<ResultSet>('/admin/database/query', {
        sql,
        mode,
        expected_rows: mode === 'write' ? dryRun?.rows : undefined,
      })
      .then((res) => {
        setResult(res.data);
        if (mode === 'dry_run') {
          setDryRun({ sql, rows: res.data.row_count ?? 0 });
          setNotice(`Dry run: this would change ${res.data.row_count ?? 0} row(s). Nothing was changed.`);
        } else if (mode === 'write') {
          setDryRun(null);
          setNotice(`Done: ${res.data.row_count ?? 0} row(s) changed. Recorded in the audit log.`);
        }
      })
      .catch((err) => {
        setError(errText(err, 'The statement failed'));
        if (mode === 'write') setDryRun(null);
      })
      .finally(() => setRunning(false));
  };

  const canWrite = dryRun !== null && dryRun.sql === sql && !running;

  return (
    <div>
      <textarea
        className="form-input"
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            run('read');
          }
        }}
        spellCheck={false}
        rows={8}
        style={{ width: '100%', height: 'auto', fontFamily: 'var(--font-mono, monospace)', fontSize: '13px', padding: 'var(--space-3)' }}
        placeholder="SELECT * FROM organizations ORDER BY created_at DESC LIMIT 20"
      />
      <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap', margin: 'var(--space-3) 0' }}>
        <button className="btn-primary" disabled={running} onClick={() => run('read')}>
          <Play size={14} /> Run read
        </button>
        <span style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Ctrl+Enter · read-only, cannot change data</span>
        <div style={{ flex: 1 }} />
        <button className="btn-secondary" disabled={running} onClick={() => run('dry_run')}>
          <ShieldCheck size={14} /> Dry run
        </button>
        <button
          className="btn-secondary"
          disabled={!canWrite}
          onClick={() => run('write')}
          style={canWrite ? { borderColor: 'var(--error)', color: 'var(--error)' } : undefined}
          title={canWrite ? undefined : 'Dry-run this exact statement first'}
        >
          <AlertTriangle size={14} /> Run write{canWrite ? ` (${dryRun?.rows} rows)` : ''}
        </button>
      </div>
      <p style={{ fontSize: '12px', color: 'var(--neutral-500)', marginBottom: 'var(--space-3)' }}>
        INSERT / UPDATE / DELETE: Dry run first (changes nothing, shows the row count), then Run write. The write is
        kept only if it changes the same number of rows. Schema changes go through migrations, not here. One statement at
        a time; reads time out after 15 s, writes after 30 s; up to 500 rows are shown.
      </p>
      {notice && <p style={{ color: 'var(--success)', marginBottom: 'var(--space-3)', fontSize: '14px' }}>{notice}</p>}
      {error && (
        <pre
          style={{
            color: 'var(--error)',
            whiteSpace: 'pre-wrap',
            fontSize: '13px',
            marginBottom: 'var(--space-3)',
          }}
        >
          {error}
        </pre>
      )}
      {result && (
        <>
          <ResultGrid result={result} />
          {result.columns.length > 0 && (
            <p style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: 'var(--space-2)' }}>
              {result.rows.length} row(s){result.truncated ? ` (first ${result.max_rows} shown)` : ''} · {result.duration_ms} ms
            </p>
          )}
        </>
      )}
    </div>
  );
}

export default function Database() {
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<'browse' | 'sql'>('browse');
  const [error, setError] = useState<string | null>(null);

  const loadTables = useCallback(() => {
    api
      .get<{ tables: TableInfo[] }>('/admin/database/tables')
      .then((res) => {
        setTables(res.data.tables);
        setError(null);
      })
      .catch((err) => setError(errText(err, 'Failed to load tables')));
  }, []);

  useEffect(() => {
    loadTables();
  }, [loadTables]);

  const shown = useMemo(
    () => tables.filter((t) => t.name.toLowerCase().includes(search.trim().toLowerCase())),
    [tables, search],
  );

  const initialSql = selected ? `SELECT * FROM ${selected} LIMIT 50` : '';

  return (
    <div className="animate-fade-in">
      <header style={{ marginBottom: 'var(--space-6)' }}>
        <h1>Database</h1>
        <p className="subtitle">
          Every table in the live database. Browse rows, run read-only SQL, or change rows with a dry run first. Every
          SQL read and write is recorded in the audit log.
        </p>
      </header>

      {error && <p style={{ color: 'var(--error)', marginBottom: 'var(--space-4)' }}>{error}</p>}

      <div className="stack-sm" style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 280px) minmax(0, 1fr)', gap: 'var(--space-5)' }}>
        <div className="card" style={{ padding: 'var(--space-3)', alignSelf: 'start' }}>
          <input
            className="form-input"
            style={{ height: '36px', marginBottom: 'var(--space-2)' }}
            placeholder={`Search ${tables.length} tables`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div style={{ maxHeight: '70vh', overflowY: 'auto' }}>
            {shown.map((t) => (
              <button
                key={t.name}
                onClick={() => {
                  setSelected(t.name);
                  setTab('browse');
                }}
                className={`nav-item ${selected === t.name ? 'active' : ''}`}
                style={{
                  width: '100%',
                  border: 'none',
                  background: selected === t.name ? undefined : 'transparent',
                  cursor: 'pointer',
                  justifyContent: 'space-between',
                  fontSize: '13px',
                  textAlign: 'left',
                }}
              >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{t.name}</span>
                <span style={{ fontSize: '11px', color: 'var(--neutral-500)', whiteSpace: 'nowrap' }}>
                  {t.estimated_rows !== null ? `~${t.estimated_rows.toLocaleString()}` : '?'} · {fmtBytes(t.size_bytes)}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="card" style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', marginBottom: 'var(--space-4)', alignItems: 'center' }}>
            <button
              className={tab === 'browse' ? 'btn-primary' : 'btn-secondary'}
              style={{ height: '32px' }}
              onClick={() => setTab('browse')}
            >
              Browse{selected ? `: ${selected}` : ''}
            </button>
            <button
              className={tab === 'sql' ? 'btn-primary' : 'btn-secondary'}
              style={{ height: '32px' }}
              onClick={() => setTab('sql')}
            >
              SQL
            </button>
          </div>
          {tab === 'browse' &&
            (selected ? (
              <BrowseTable table={selected} />
            ) : (
              <p style={{ color: 'var(--neutral-500)' }}>Pick a table on the left, or open the SQL tab.</p>
            ))}
          {tab === 'sql' && <SqlConsole initialSql={initialSql} />}
        </div>
      </div>
    </div>
  );
}
