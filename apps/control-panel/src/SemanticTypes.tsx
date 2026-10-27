import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, AlertCircle, Tags, MessageSquare, CheckCircle2, Circle, Play } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api } from './api';
import { type SystemGraphResponse, chipStyle, RoutingFlow } from './systemGraphShared';

const SemanticTypes = () => {
  const [data, setData] = useState<SystemGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const fetchGraph = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .get<SystemGraphResponse>('/admin/system-graph')
      .then((res) => setData({ ...res.data, semantic_types: res.data.semantic_types ?? [] }))
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
          <h1>Semantic Types</h1>
          <p className="subtitle">
            Everything Understanding can decide a message is <em>about</em>, and where each one routes — derived live from the
            canonicalization + routing tables.
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
        <div className="card" style={{ textAlign: 'center', color: 'var(--neutral-500)' }}>Loading semantic types…</div>
      ) : data ? (
        <>
          <p style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: 0, marginBottom: 'var(--space-4)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <Tags size={16} style={{ color: 'var(--primary)' }} /> Read each card as a flow: <strong>semantic type → canonical event → workflow</strong>.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(340px, 100%), 1fr))', gap: 'var(--space-5)' }}>
            {data.semantic_types.map((st) => {
              const isDirectReply = st.workflow_keys.length === 0;
              const badge = isDirectReply
                ? { cls: '', text: 'Direct reply', icon: <MessageSquare size={12} style={{ marginRight: 4 }} /> }
                : st.implemented
                  ? { cls: 'badge-success', text: 'Built', icon: <CheckCircle2 size={12} style={{ marginRight: 4 }} /> }
                  : { cls: 'badge-warning', text: 'Not built yet', icon: <Circle size={12} style={{ marginRight: 4 }} /> };
              // One routing row per canonical event, so MATERIAL_UPDATE shows both branches.
              const rows = st.canonical_events.map((event, i) => {
                const wf = st.workflow_keys[i] ?? (isDirectReply ? null : st.workflow_keys[0] ?? null);
                const steps: { label: string; muted?: boolean }[] = [{ label: st.semantic_type }, { label: event }];
                if (wf) steps.push({ label: wf });
                else if (st.routes_to_reply) steps.push({ label: st.routes_to_reply, muted: true });
                return steps;
              });
              return (
                <div key={st.semantic_type} className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-3)' }}>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '14px', fontFamily: 'monospace', color: 'var(--neutral-900)' }}>{st.semantic_type}</div>
                      <div style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: '2px' }}>{st.description}</div>
                    </div>
                    <span className={`badge ${badge.cls}`} style={{ flexShrink: 0 }}>
                      {badge.icon}{badge.text}
                    </span>
                  </div>

                  {/* Routing flow — the visual centerpiece */}
                  <div style={{ marginTop: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {rows.map((steps, i) => (
                      <RoutingFlow key={i} steps={steps} />
                    ))}
                  </div>

                  <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 12px', margin: 0, marginTop: 'var(--space-4)', paddingTop: 'var(--space-4)', borderTop: '1px solid var(--neutral-100, #eee)', fontSize: '13px' }}>
                    <dt style={{ color: 'var(--neutral-500)' }}>How it's detected</dt>
                    <dd style={{ margin: 0 }}>{st.detection}</dd>
                    {st.required_field_labels.length > 0 && (
                      <>
                        <dt style={{ color: 'var(--neutral-500)' }}>Required fields</dt>
                        <dd style={{ margin: 0 }}>{st.required_field_labels.join(', ')}</dd>
                      </>
                    )}
                  </dl>

                  {st.example_messages.length > 0 && (
                    <div style={{ marginTop: 'var(--space-3)', display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                      {st.example_messages.map((msg) => (
                        <span key={msg} style={chipStyle} onClick={() => tryExample(msg)} title="Test this in Send a test message">
                          <Play size={11} /> {msg}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      ) : null}
    </div>
  );
};

export default SemanticTypes;
