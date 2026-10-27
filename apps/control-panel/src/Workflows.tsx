import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, AlertCircle, ChevronDown, ChevronRight, CheckCircle2, Circle, Play } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api } from './api';
import { type SystemGraphResponse, MermaidDiagram, chipStyle } from './systemGraphShared';

const Workflows = () => {
  const [data, setData] = useState<SystemGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const navigate = useNavigate();

  const fetchGraph = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .get<SystemGraphResponse>('/admin/system-graph')
      .then((res) => setData({ ...res.data, workflows: res.data.workflows ?? [] }))
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load system graph'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  const toggle = (key: string) => setExpanded((e) => ({ ...e, [key]: !e[key] }));

  const tryExample = (msg: string) => {
    navigate('/test-message', { state: { prefill: msg } });
  };

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1100px' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 'var(--space-6)' }}>
        <div>
          <h1>Workflows</h1>
          <p className="subtitle">Multi-step flows the assistant can carry out, generated live from the workflow graph.</p>
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
        <div className="card" style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Loading workflows…</div>
      ) : data ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(340px, 100%), 1fr))', gap: 'var(--space-5)' }}>
          {data.workflows.map((wf) => {
            const open = !!expanded[wf.workflow_key];
            return (
              <div key={wf.workflow_key} className="card">
                <div
                  onClick={() => toggle(wf.workflow_key)}
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                    {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '14px', color: 'var(--neutral-900)' }}>{wf.title}</div>
                      <div style={{ fontFamily: 'monospace', fontSize: '11px', color: 'var(--neutral-500)' }}>{wf.workflow_key}</div>
                    </div>
                  </div>
                  <span className={`badge ${wf.implemented ? 'badge-success' : 'badge-warning'}`}>
                    {wf.implemented ? <CheckCircle2 size={12} style={{ marginRight: 4 }} /> : <Circle size={12} style={{ marginRight: 4 }} />}
                    {wf.implemented ? 'Built' : 'Not built yet'}
                  </span>
                </div>

                {/* Example chips are always visible — the most useful bit */}
                {wf.example_messages.length > 0 && (
                  <div style={{ marginTop: 'var(--space-3)', display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {wf.example_messages.map((msg) => (
                      <span
                        key={msg}
                        style={chipStyle}
                        onClick={(e) => {
                          e.stopPropagation();
                          tryExample(msg);
                        }}
                        title="Test this in Send a test message"
                      >
                        <Play size={11} /> {msg}
                      </span>
                    ))}
                  </div>
                )}

                {open && (
                  <div style={{ marginTop: 'var(--space-4)', borderTop: '1px solid var(--neutral-100, #eee)', paddingTop: 'var(--space-4)', fontSize: '13px' }}>
                    <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 12px', margin: 0 }}>
                      <dt style={{ color: 'var(--neutral-500)' }}>Canonical event</dt>
                      <dd style={{ margin: 0, fontFamily: 'monospace' }}>{wf.canonical_event || '—'}</dd>
                      <dt style={{ color: 'var(--neutral-500)' }}>Semantic type</dt>
                      <dd style={{ margin: 0, fontFamily: 'monospace' }}>{wf.semantic_type || '—'}</dd>
                      <dt style={{ color: 'var(--neutral-500)' }}>Required fields</dt>
                      <dd style={{ margin: 0 }}>{wf.required_field_labels.length ? wf.required_field_labels.join(', ') : 'none'}</dd>
                      {wf.node_names.length > 0 && (
                        <>
                          <dt style={{ color: 'var(--neutral-500)' }}>Graph nodes</dt>
                          <dd style={{ margin: 0, fontFamily: 'monospace' }}>{wf.node_names.join(' → ')}</dd>
                        </>
                      )}
                    </dl>
                    {wf.mermaid && (
                      <div style={{ marginTop: 'var(--space-3)' }}>
                        <div style={{ fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--neutral-500)', marginBottom: 'var(--space-2)' }}>
                          Draft graph
                        </div>
                        <MermaidDiagram source={wf.mermaid} />
                      </div>
                    )}
                    {wf.lifecycle_mermaid && (
                      <div style={{ marginTop: 'var(--space-4)' }}>
                        <div style={{ fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--neutral-500)', marginBottom: 'var(--space-2)' }}>
                          After confirmation — branches to outcome
                        </div>
                        <MermaidDiagram source={wf.lifecycle_mermaid} />
                      </div>
                    )}
                    {!wf.implemented && (
                      <p style={{ color: 'var(--neutral-500)', marginTop: 'var(--space-3)', marginBottom: 0 }}>
                        This intent is understood but routes to a "not supported yet" reply until the workflow is added.
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
};

export default Workflows;
