import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import {
  RefreshCw,
  AlertCircle,
  MessageSquare,
  Send,
  FlaskConical,
  Cpu,
  Zap,
  RotateCcw,
  User,
  Building2,
  Layers,
  ChevronRight,
  Sparkles,
} from 'lucide-react';
import { api } from './api';
import {
  type Organization,
  type OrgUser,
  type SimulateResponse,
  type StructuredReply,
  ROUTED_VIA_LABELS,
  RoutingFlow,
} from './systemGraphShared';

interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  timestamp: string;
  text: string;
  structuredReplies?: StructuredReply[];
  resultTrace?: SimulateResponse;
}

interface PresetScenario {
  id: string;
  label: string;
  icon: string;
  prompt: string;
  description: string;
}

const PRESET_SCENARIOS: PresetScenario[] = [
  {
    id: 'material-arrival',
    label: 'Material Arrival',
    icon: '📦',
    prompt: '50 bags of cement arrived at site A',
    description: 'Tests material receipt workflow with stock unit & project verification.',
  },
  {
    id: 'material-usage',
    label: 'Material Usage',
    icon: '🏗️',
    prompt: '20 bags of cement used today',
    description: 'Tests material usage workflow with stock limit validation.',
  },
  {
    id: 'inventory-query',
    label: 'Stock Inventory Query',
    icon: '📊',
    prompt: 'How much cement do we have?',
    description: 'Tests read-only stock level query workflow.',
  },
  {
    id: 'whoami',
    label: 'Who Am I',
    icon: '👤',
    prompt: 'Who am I?',
    description: 'Tests user role & assigned projects/sites identity lookup.',
  },
  {
    id: 'greeting',
    label: 'Category Menu',
    icon: '👋',
    prompt: 'Menu',
    description: 'Tests greeting trigger and interactive category menu list.',
  },
];

const TestMessage = () => {
  const location = useLocation();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [orgId, setOrgId] = useState('');
  const [userId, setUserId] = useState('');
  const [inputText, setInputText] = useState('');
  const [sending, setSending] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeTrace, setActiveTrace] = useState<SimulateResponse | null>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .get<Organization[]>('/admin/organizations')
      .then((res) => setOrgs(res.data))
      .catch(() => setOrgs([]));
  }, []);

  useEffect(() => {
    const prefill = (location.state as { prefill?: string } | null)?.prefill;
    if (prefill) {
      setInputText(prefill);
      setTestError(null);
    }
  }, [location.state]);

  useEffect(() => {
    if (!orgId) {
      setUsers([]);
      setUserId('');
      setMessages([]);
      setActiveTrace(null);
      return;
    }
    api
      .get<OrgUser[]>(`/admin/organizations/${orgId}/users`)
      .then((res) => setUsers(res.data))
      .catch(() => setUsers([]));
  }, [orgId]);

  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [messages, sending]);

  const selectedUser = users.find((u) => u.id === userId);
  const canSend = !!orgId && !!userId && !!selectedUser?.whatsapp_number && !sending;

  const resetSession = async () => {
    if (!orgId || !userId) {
      setMessages([]);
      setActiveTrace(null);
      return;
    }
    setResetting(true);
    setTestError(null);
    try {
      await api.post('/admin/system-graph/simulate/reset', {
        organization_id: orgId,
        user_id: userId,
      });
      setMessages([]);
      setActiveTrace(null);
    } catch (err: any) {
      setTestError(err.response?.data?.detail || 'Failed to reset session');
    } finally {
      setResetting(false);
    }
  };

  const executeSimulation = async (payload: { text?: string; modality?: 'text' | 'interactive'; interactive_reply_id?: string }) => {
    if (!canSend) return;
    const sendText = payload.text || payload.interactive_reply_id || '';
    if (!sendText.trim()) return;

    setSending(true);
    setTestError(null);

    const userMsg: ChatMessage = {
      id: 'msg-' + Date.now() + '-user',
      sender: 'user',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      text: sendText,
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputText('');

    try {
      const res = await api.post<SimulateResponse>('/admin/system-graph/simulate', {
        organization_id: orgId,
        user_id: userId,
        text: payload.text || '',
        modality: payload.modality || 'text',
        interactive_reply_id: payload.interactive_reply_id,
      });

      const data = res.data;
      setActiveTrace(data);

      const replyTextCombined = data.replies.length ? data.replies.join('\n\n') : '(No reply produced)';

      const assistantMsg: ChatMessage = {
        id: 'msg-' + Date.now() + '-assistant',
        sender: 'assistant',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        text: replyTextCombined,
        structuredReplies: data.structured_replies || [],
        resultTrace: data,
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      setTestError(err.response?.data?.detail || 'Simulation failed');
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      executeSimulation({ text: inputText, modality: 'text' });
    }
  };

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <header style={{ marginBottom: 'var(--space-5)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 'var(--space-4)' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <FlaskConical size={24} style={{ color: 'var(--primary)' }} />
            <h1 style={{ margin: 0, fontSize: '22px' }}>WhatsApp Interactive Workflow Workbench</h1>
          </div>
          <p className="subtitle" style={{ marginTop: '4px' }}>
            Simulate complete multi-turn WhatsApp conversations, test button/list interactive gates, and inspect real-time AI routing & pipeline traces.
          </p>
        </div>

        <button className="btn-secondary" onClick={resetSession} disabled={resetting || !userId} title="Resets pending workflow confirmation & held report state for this user">
          <RotateCcw size={15} className={resetting ? 'spin' : ''} /> {resetting ? 'Resetting...' : 'Reset Chat Session'}
        </button>
      </header>

      {/* Target User & Org Selection Bar */}
      <div className="card" style={{ marginBottom: 'var(--space-5)', padding: 'var(--space-4)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(280px, 100%), 1fr))', gap: 'var(--space-4)', alignItems: 'center' }}>
          <div className="form-group" style={{ margin: 0 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Building2 size={15} style={{ color: 'var(--neutral-500)' }} /> Organization
            </label>
            <select className="form-input" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              <option value="">Select organization…</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group" style={{ margin: 0 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <User size={15} style={{ color: 'var(--neutral-500)' }} /> Run as User
            </label>
            <select className="form-input" value={userId} onChange={(e) => setUserId(e.target.value)} disabled={!orgId}>
              <option value="">Select user…</option>
              {users.map((u) => (
                <option key={u.id} value={u.id} disabled={!u.whatsapp_number}>
                  {(u.full_name || u.email || u.id) + (u.whatsapp_number ? '' : ' (no WhatsApp number)')}
                </option>
              ))}
            </select>
          </div>

          {selectedUser && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-3)',
                padding: 'var(--space-2) var(--space-3)',
                background: 'var(--neutral-50)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--neutral-200)',
              }}
            >
              <div
                style={{
                  width: '36px',
                  height: '36px',
                  borderRadius: '50%',
                  background: 'var(--primary-soft)',
                  color: 'var(--primary-active)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 600,
                  fontSize: '14px',
                }}
              >
                {(selectedUser.full_name || 'U')[0].toUpperCase()}
              </div>
              <div style={{ fontSize: '12px', lineHeight: '16px' }}>
                <div style={{ fontWeight: 600, color: 'var(--neutral-900)' }}>{selectedUser.full_name || selectedUser.email}</div>
                <div style={{ color: 'var(--neutral-500)', fontFamily: 'monospace' }}>WA: {selectedUser.whatsapp_number || 'None'}</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Preset Scenarios Quick Bar */}
      <div style={{ marginBottom: 'var(--space-5)' }}>
        <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--neutral-500)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 'var(--space-2)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Sparkles size={13} style={{ color: 'var(--primary)' }} /> Quick Test Scenarios
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(200px, 100%), 1fr))', gap: 'var(--space-2)' }}>
          {PRESET_SCENARIOS.map((scenario) => (
            <button
              key={scenario.id}
              onClick={() => {
                if (!canSend) return;
                executeSimulation({ text: scenario.prompt, modality: 'text' });
              }}
              disabled={!canSend}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                padding: 'var(--space-3)',
                background: 'var(--surface-primary)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-md)',
                cursor: canSend ? 'pointer' : 'not-allowed',
                opacity: canSend ? 1 : 0.6,
                textAlign: 'left',
                transition: 'all 0.15s ease',
              }}
              className="scenario-card"
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600, fontSize: '13px', color: 'var(--neutral-900)', marginBottom: '2px' }}>
                <span>{scenario.icon}</span> {scenario.label}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--neutral-500)', lineClamp: 2, display: '-webkit-box', WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                "{scenario.prompt}"
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Main 2-Column Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, 1fr)', gap: 'var(--space-5)', alignItems: 'start' }}>
        
        {/* Left Column: WhatsApp Chat Sandbox */}
        <div
          className="card"
          style={{
            padding: 0,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            height: '680px',
            border: '1px solid var(--neutral-300)',
            boxShadow: 'var(--shadow-2)',
          }}
        >
          {/* WhatsApp Header */}
          <div
            style={{
              background: '#075e54',
              color: '#ffffff',
              padding: 'var(--space-3) var(--space-4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              <div
                style={{
                  width: '38px',
                  height: '38px',
                  borderRadius: '50%',
                  background: '#25d366',
                  color: '#ffffff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 700,
                  fontSize: '15px',
                }}
              >
                M
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: '14px' }}>Mesiri AI Assistant</div>
                <div style={{ fontSize: '11px', opacity: 0.85, display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#25d366' }}></span>
                  Test Harness Sandbox
                </div>
              </div>
            </div>
            {selectedUser && (
              <span style={{ fontSize: '11px', background: 'rgba(255,255,255,0.15)', padding: '3px 8px', borderRadius: '12px' }}>
                Simulating as {selectedUser.full_name || selectedUser.whatsapp_number}
              </span>
            )}
          </div>

          {/* Messages Stream Body */}
          <div
            ref={chatScrollRef}
            style={{
              flex: 1,
              padding: 'var(--space-4)',
              overflowY: 'auto',
              background: '#efeae2',
              backgroundImage: 'radial-gradient(rgba(0, 0, 0, 0.04) 1px, transparent 0)',
              backgroundSize: '16px 16px',
              display: 'flex',
              flexDirection: 'column',
              gap: 'var(--space-3)',
            }}
          >
            {messages.length === 0 ? (
              <div style={{ margin: 'auto', textAlign: 'center', color: '#667781', maxWidth: '320px', fontSize: '13px' }}>
                <MessageSquare size={32} style={{ opacity: 0.4, marginBottom: '8px' }} />
                <p style={{ margin: 0, fontWeight: 500 }}>No messages in session yet.</p>
                <p style={{ fontSize: '12px', marginTop: '4px', opacity: 0.8 }}>
                  Pick a test user above and type a message or select a scenario preset to start testing.
                </p>
              </div>
            ) : (
              messages.map((msg) => {
                const isUser = msg.sender === 'user';
                return (
                  <div
                    key={msg.id}
                    onClick={() => {
                      if (msg.resultTrace) setActiveTrace(msg.resultTrace);
                    }}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: isUser ? 'flex-end' : 'flex-start',
                      cursor: msg.resultTrace ? 'pointer' : 'default',
                    }}
                  >
                    <div
                      style={{
                        maxWidth: '85%',
                        padding: 'var(--space-3) var(--space-4)',
                        borderRadius: isUser ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                        background: isUser ? '#dcf8c6' : '#ffffff',
                        color: '#111b21',
                        boxShadow: '0 1px 1px rgba(0,0,0,0.13)',
                        position: 'relative',
                        fontSize: '13.5px',
                        lineHeight: '1.45',
                      }}
                    >
                      <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{msg.text}</div>

                      {/* Render Interactive Buttons if reply has any */}
                      {msg.structuredReplies &&
                        msg.structuredReplies.map((sr, sIdx) => (
                          <div key={sIdx} style={{ marginTop: 'var(--space-3)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                            {sr.type === 'buttons' && sr.buttons && (
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '4px' }}>
                                {sr.buttons.map((b) => (
                                  <button
                                    key={b.id}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      executeSimulation({
                                        text: b.title,
                                        modality: 'interactive',
                                        interactive_reply_id: b.id,
                                      });
                                    }}
                                    disabled={!canSend}
                                    style={{
                                      background: '#ffffff',
                                      color: '#075e54',
                                      border: '1px solid #075e54',
                                      borderRadius: '16px',
                                      padding: '6px 14px',
                                      fontSize: '12.5px',
                                      fontWeight: 600,
                                      cursor: canSend ? 'pointer' : 'not-allowed',
                                      boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
                                      transition: 'all 0.1s ease',
                                    }}
                                    className="interactive-btn"
                                  >
                                    {b.title}
                                  </button>
                                ))}
                              </div>
                            )}

                            {sr.type === 'list' && sr.list_rows && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px', background: '#f7f9fa', borderRadius: '8px', padding: '6px', border: '1px solid #e1e8ed' }}>
                                {sr.button_label && (
                                  <div style={{ fontSize: '11px', fontWeight: 600, color: '#667781', marginBottom: '2px', paddingLeft: '4px' }}>
                                    {sr.button_label}
                                  </div>
                                )}
                                {sr.list_rows.map((row) => (
                                  <button
                                    key={row.id}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      executeSimulation({
                                        text: row.title,
                                        modality: 'interactive',
                                        interactive_reply_id: row.id,
                                      });
                                    }}
                                    disabled={!canSend}
                                    style={{
                                      display: 'flex',
                                      justifyContent: 'space-between',
                                      alignItems: 'center',
                                      background: '#ffffff',
                                      border: '1px solid #d1d5db',
                                      borderRadius: '6px',
                                      padding: '8px 10px',
                                      textAlign: 'left',
                                      cursor: canSend ? 'pointer' : 'not-allowed',
                                      fontSize: '12px',
                                    }}
                                    className="list-option-btn"
                                  >
                                    <div>
                                      <div style={{ fontWeight: 600, color: '#111b21' }}>{row.title}</div>
                                      {row.description && <div style={{ fontSize: '11px', color: '#667781' }}>{row.description}</div>}
                                    </div>
                                    <ChevronRight size={14} style={{ color: '#075e54' }} />
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}

                      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '4px', marginTop: '4px', fontSize: '10px', color: '#667781' }}>
                        <span>{msg.timestamp}</span>
                        {msg.resultTrace && (
                          <span className={`badge ${msg.resultTrace.routed_via === 'ai_pipeline' ? 'badge-info' : 'badge-success'}`} style={{ fontSize: '9px', padding: '0 4px', height: '16px' }}>
                            {msg.resultTrace.routed_via === 'ai_pipeline' ? 'AI' : 'Fast'}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
            )}

            {sending && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: '#ffffff', padding: '8px 14px', borderRadius: '12px', width: 'fit-content', fontSize: '12px', color: '#667781', boxShadow: '0 1px 1px rgba(0,0,0,0.1)' }}>
                <RefreshCw size={14} className="spin" style={{ color: '#075e54' }} /> Assistant is thinking…
              </div>
            )}
          </div>

          {/* Chat Input Bar */}
          <div style={{ background: '#f0f2f5', padding: 'var(--space-3) var(--space-4)', borderTop: '1px solid #d1d5db', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <textarea
              className="form-input"
              rows={1}
              style={{ flex: 1, height: '42px', resize: 'none', borderRadius: '21px', padding: '10px 16px', background: '#ffffff', border: '1px solid #cccccc' }}
              placeholder={canSend ? 'Type a test message (e.g. "50 bags cement arrived")...' : 'Select organization and user above first...'}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={!canSend}
            />
            <button
              className="btn-primary"
              style={{ borderRadius: '50%', width: '42px', height: '42px', padding: 0, background: '#075e54', color: '#ffffff', flexShrink: 0 }}
              onClick={() => executeSimulation({ text: inputText, modality: 'text' })}
              disabled={!canSend || !inputText.trim()}
            >
              {sending ? <RefreshCw size={18} className="spin" /> : <Send size={18} />}
            </button>
          </div>

          {testError && (
            <div style={{ padding: '8px 14px', background: 'var(--error-soft)', color: 'var(--error)', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <AlertCircle size={14} /> {testError}
            </div>
          )}
        </div>

        {/* Right Column: Real-Time Pipeline Inspector */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          <div className="card" style={{ padding: 'var(--space-4)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-3)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                <Layers size={18} style={{ color: 'var(--primary)' }} />
                <h2 style={{ fontSize: '15px', margin: 0 }}>Pipeline Inspection Trace</h2>
              </div>
              {activeTrace && (
                <span className={`badge ${activeTrace.routed_via === 'ai_pipeline' ? 'badge-info' : 'badge-success'}`} style={{ fontSize: '11px' }}>
                  {activeTrace.routed_via === 'ai_pipeline' ? <Cpu size={12} style={{ marginRight: 4 }} /> : <Zap size={12} style={{ marginRight: 4 }} />}
                  {ROUTED_VIA_LABELS[activeTrace.routed_via] || activeTrace.routed_via}
                </span>
              )}
            </div>

            {!activeTrace ? (
              <div style={{ fontSize: '13px', color: 'var(--neutral-500)', fontStyle: 'italic', padding: 'var(--space-4) 0', textAlign: 'center' }}>
                Send a message or click an interactive button in the chat preview to view the live execution trace.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                {/* Routing summary pill chain */}
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--neutral-500)', marginBottom: '6px' }}>Execution Path</div>
                  {activeTrace.routed_via !== 'ai_pipeline' ? (
                    <div style={{ fontSize: '12px', color: 'var(--neutral-600)', background: 'var(--neutral-50)', padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--neutral-200)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Zap size={14} style={{ color: 'var(--success)' }} /> Deterministic reply path executed — zero AI cost.
                    </div>
                  ) : (
                    <RoutingFlow
                      steps={[
                        { label: activeTrace.understanding?.semantic_type || 'understanding' },
                        { label: activeTrace.canonical_event?.event_type || 'canonical_event' },
                        { label: activeTrace.planner_decision?.decision_type || 'planner' },
                        { label: activeTrace.workflow_run ? `${activeTrace.workflow_run.workflow_key} (${activeTrace.workflow_run.status})` : 'direct_reply' },
                      ]}
                    />
                  )}
                </div>

                {/* AI Providers Used */}
                {activeTrace.routed_via === 'ai_pipeline' && (
                  <div>
                    <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--neutral-500)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Cpu size={14} /> AI Providers Executed
                    </div>
                    {(() => {
                      const executions = activeTrace.understanding?.provider_executions ?? [];
                      if (executions.length === 0) {
                        return <div style={{ fontSize: '12px', color: 'var(--neutral-500)', fontStyle: 'italic' }}>No AI provider calls executed.</div>;
                      }
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', background: 'var(--neutral-50)', border: '1px solid var(--neutral-200)', borderRadius: 'var(--radius-sm)', padding: 'var(--space-2)' }}>
                          {executions.map((p, i) => (
                            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px' }}>
                              <div>
                                <span style={{ fontWeight: 600 }}>{p.provider}</span> <span style={{ color: 'var(--neutral-500)', fontSize: '11px' }}>({p.operation})</span>
                                {p.model && <div style={{ fontSize: '10px', fontFamily: 'monospace', color: 'var(--neutral-500)' }}>{p.model}</div>}
                              </div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span className={`badge ${p.succeeded ? 'badge-success' : 'badge-error'}`} style={{ fontSize: '9px', padding: '1px 5px' }}>
                                  {p.succeeded ? 'Success' : p.error_code || 'Fail'}
                                </span>
                                {p.latency_ms !== null && <span style={{ fontFamily: 'monospace', fontSize: '11px', color: 'var(--neutral-500)' }}>{p.latency_ms.toFixed(0)}ms</span>}
                              </div>
                            </div>
                          ))}
                        </div>
                      );
                    })()}
                  </div>
                )}

                {/* Detailed Breakdown Accordion */}
                <details style={{ fontSize: '12px', border: '1px solid var(--neutral-200)', borderRadius: 'var(--radius-sm)', padding: '8px 12px', background: 'var(--neutral-50)' }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600, color: 'var(--neutral-700)' }}>Raw Context & Event JSON</summary>
                  <pre style={{ marginTop: '8px', fontSize: '11px', fontFamily: 'monospace', overflowX: 'auto', background: '#ffffff', padding: '8px', borderRadius: '4px', border: '1px solid #e5e5e5' }}>
                    {JSON.stringify(
                      {
                        understanding: activeTrace.understanding,
                        canonical_event: activeTrace.canonical_event,
                        planner_decision: activeTrace.planner_decision,
                        workflow_run: activeTrace.workflow_run,
                      },
                      null,
                      2
                    )}
                  </pre>
                </details>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default TestMessage;
