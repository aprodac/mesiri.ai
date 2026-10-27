import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  RefreshCw,
  GitBranch,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Play,
  AlertTriangle,
  FileText,
  Tags,
  ListChecks,
  FlaskConical,
  Zap,
} from 'lucide-react';
import { api } from './api';
import { type SystemGraphResponse, MermaidDiagram, chipStyle } from './systemGraphShared';

const SystemGraph = () => {
  const [data, setData] = useState<SystemGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showMap, setShowMap] = useState(false);
  const navigate = useNavigate();

  const fetchGraph = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .get<SystemGraphResponse>('/admin/system-graph')
      .then((res) =>
        setData({
          ...res.data,
          fast_paths: res.data.fast_paths ?? [],
          hardcoded_replies: res.data.hardcoded_replies ?? [],
          stages: res.data.stages ?? [],
          semantic_types: res.data.semantic_types ?? [],
          workflows: res.data.workflows ?? [],
        }),
      )
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load system graph'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  const tryExample = (msg: string) => {
    navigate('/test-message', { state: { prefill: msg } });
  };

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1100px' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 'var(--space-6)' }}>
        <div>
          <h1>System Graph</h1>
          <p className="subtitle">
            How the WhatsApp assistant reacts to every message — generated live from the routing tables, and testable end-to-end.
          </p>
        </div>
        <button className="btn-secondary" onClick={fetchGraph} disabled={loading}>
          <RefreshCw size={16} className={loading ? 'spin' : undefined} /> Refresh
        </button>
      </header>

      {error && (
        <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--danger, #d33)', marginBottom: 'var(--space-6)' }}>
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {loading && !data ? (
        <div className="card" style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Loading live system map…</div>
      ) : data ? (
        <>
          {/* --- Pipeline stages --- */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))', gap: 'var(--space-4)', marginBottom: 'var(--space-8)' }}>
            {data.stages.map((stage) => (
              <div key={stage.key} className="card">
                <h2 style={{ fontSize: '15px', fontWeight: 600, margin: 0, marginBottom: 'var(--space-2)' }}>{stage.title}</h2>
                <p style={{ fontSize: '12px', color: 'var(--neutral-500)', margin: 0, marginBottom: 'var(--space-3)' }}>{stage.summary}</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {stage.nodes.map((n) => (
                    <div key={n.id} style={{ fontSize: '12px' }}>
                      <span style={{ fontWeight: 500, color: 'var(--neutral-800, #333)' }}>{n.label}</span>
                      {n.description && <span style={{ color: 'var(--neutral-500)' }}> — {n.description}</span>}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* --- Fast paths (deterministic, pre-AI) --- */}
          <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: 'var(--space-2)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <Zap size={16} style={{ color: 'var(--warning, #c98a1e)' }} /> Fast paths (deterministic, no AI)
          </h2>
          <p style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: 0, marginBottom: 'var(--space-4)' }}>
            These run before the AI pipeline is ever touched — matched against static phrase lists, not model output. Click an example to test it.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(260px, 100%), 1fr))', gap: 'var(--space-4)', marginBottom: 'var(--space-8)' }}>
            {data.fast_paths.map((fp) => (
              <div key={fp.key} className="card">
                <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '4px' }}>{fp.title}</div>
                <p style={{ fontSize: '12px', color: 'var(--neutral-500)', margin: 0, marginBottom: 'var(--space-3)' }}>{fp.description}</p>
                {fp.example_messages.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {fp.example_messages.map((msg) => (
                      <span key={msg} style={chipStyle} onClick={() => tryExample(msg)} title="Load into the test panel">
                        <Play size={11} /> {msg}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* --- Hardcoded / canned replies --- */}
          <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: 'var(--space-2)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <FileText size={16} style={{ color: 'var(--neutral-600)' }} /> Hardcoded / canned replies
          </h2>
          <p style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: 0, marginBottom: 'var(--space-4)' }}>
            Every reply in the system that's a fixed template, not generated for the specific message — including ones the AI pipeline itself falls back to. Rendered live from the actual source functions, so this is always what's really shipping.
            {data.hardcoded_replies.some((r) => r.flag) && (
              <span style={{ color: 'var(--warning, #c98a1e)', fontWeight: 500 }}>
                {' '}{data.hardcoded_replies.filter((r) => r.flag).length} flagged as misleading or leftover dev text below.
              </span>
            )}
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', marginBottom: 'var(--space-8)' }}>
            {data.hardcoded_replies.map((r) => (
              <div
                key={r.key}
                className="card"
                style={r.flag ? { borderColor: 'var(--warning, #c98a1e)', borderWidth: '1px', borderStyle: 'solid' } : undefined}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-3)', marginBottom: 'var(--space-2)' }}>
                  <div style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                    <div style={{ fontWeight: 600, fontSize: '13px' }}>{r.title}</div>
                    <div style={{ fontFamily: 'monospace', fontSize: '11px', color: 'var(--neutral-500)' }}>{r.source}</div>
                  </div>
                  {r.flag && (
                    <span className="badge badge-warning" style={{ fontSize: '10px', flexShrink: 0 }}>
                      <AlertTriangle size={11} style={{ marginRight: 4 }} /> Flagged
                    </span>
                  )}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--neutral-500)', marginBottom: 'var(--space-2)' }}>
                  <strong>Trigger:</strong> {r.trigger}
                </div>
                <div style={{ whiteSpace: 'pre-wrap', background: 'var(--neutral-50, #fafafa)', border: '1px solid var(--neutral-200, #e5e5e5)', borderRadius: 'var(--radius-sm)', padding: 'var(--space-3)', fontSize: '13px' }}>
                  {r.template}
                </div>
                {r.flag && (
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', marginTop: 'var(--space-2)', fontSize: '12px', color: 'var(--warning, #c98a1e)' }}>
                    <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: '2px' }} /> {r.flag}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* --- Overview diagram (collapsible) --- */}
          <div className="card" style={{ marginBottom: 'var(--space-8)' }}>
            <button
              onClick={() => setShowMap((s) => !s)}
              style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', background: 'none', border: 'none', cursor: 'pointer', fontSize: '15px', fontWeight: 600, padding: 0, minHeight: 36, width: '100%', color: 'var(--neutral-900)' }}
            >
              {showMap ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
              <GitBranch size={16} style={{ color: 'var(--primary)' }} /> Full pipeline diagram
            </button>
            {showMap && (
              <div style={{ marginTop: 'var(--space-4)' }}>
                <MermaidDiagram source={data.mermaid} />
              </div>
            )}
          </div>

          {/* --- Links to the pages that used to live here --- */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))', gap: 'var(--space-4)' }}>
            <Link to="/semantic-types" className="card" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', textDecoration: 'none', color: 'inherit' }}>
              <Tags size={20} style={{ color: 'var(--primary)' }} />
              <div>
                <div style={{ fontWeight: 600, fontSize: '14px' }}>Semantic Types</div>
                <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>What the assistant can understand, and how it routes</div>
              </div>
            </Link>
            <Link to="/workflows" className="card" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', textDecoration: 'none', color: 'inherit' }}>
              <ListChecks size={20} style={{ color: 'var(--primary)' }} />
              <div>
                <div style={{ fontWeight: 600, fontSize: '14px' }}>Workflows</div>
                <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Multi-step flows the assistant can carry out</div>
              </div>
            </Link>
            <Link to="/test-message" className="card" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', textDecoration: 'none', color: 'inherit' }}>
              <FlaskConical size={20} style={{ color: 'var(--primary)' }} />
              <div>
                <div style={{ fontWeight: 600, fontSize: '14px' }}>Send a test message</div>
                <div style={{ fontSize: '12px', color: 'var(--neutral-500)' }}>Run the real AI pipeline as any user and see the reply</div>
              </div>
            </Link>
          </div>
        </>
      ) : null}
    </div>
  );
};

export default SystemGraph;
