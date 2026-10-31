import { useEffect, useState } from 'react';
import { CheckCircle2, XCircle, RefreshCw, Cpu, ShieldAlert, Key, GitMerge } from 'lucide-react';
import { api } from './api';

interface Provider {
  id: string;
  name: string;
  model: string | null;
  configured: boolean;
  key_preview: string | null;
  source: string;
  base_url?: string | null;
}

interface CheckResult {
  ok: boolean;
  error: string | null;
  latency_ms: number | null;
}

interface CapabilityRouting {
  provider_id: string;
  model: string;
  fallback_provider_id: string | null;
  fallback_model: string | null;
}

interface AIConfig {
  routing: Record<string, CapabilityRouting>;
  secrets: Record<string, { api_key: string | null; base_url: string | null }>;
}

// ──────────────────────────────────────────────────
// Static capability definitions
// ──────────────────────────────────────────────────
const CAPABILITY_DEFS: {
  key: string;
  label: string;
  providers: { value: string; label: string }[];
  models: Record<string, string[]>;
}[] = [
  {
    key: 'voice',
    label: 'Voice / STT',
    providers: [
      { value: 'sarvam', label: 'Sarvam' },
      { value: 'gemini', label: 'Gemini' },
      { value: 'fake', label: 'Fake (Mock data)' },
    ],
    models: {
      sarvam: ['saaras:v2.5'],
      gemini: ['gemini-2.5-flash'],
    },
  },
  {
    key: 'extraction',
    label: 'Structured Extraction',
    providers: [
      { value: 'gemini', label: 'Gemini' },
      { value: 'deepseek', label: 'DeepSeek' },
      { value: 'fake', label: 'Fake (Mock data)' },
    ],
    models: {
      gemini: ['gemini-2.5-flash'],
      deepseek: ['deepseek-chat'],
    },
  },
  {
    key: 'vision',
    label: 'Vision / Image Analysis',
    providers: [
      { value: 'gemini', label: 'Gemini' },
      { value: 'fake', label: 'Fake (Mock data)' },
    ],
    models: {
      gemini: ['gemini-2.5-flash'],
    },
  },
  {
    key: 'translation',
    label: 'Translation',
    providers: [
      { value: 'gemini', label: 'Gemini' },
      { value: 'deepseek', label: 'DeepSeek' },
      { value: 'fake', label: 'Fake (Mock data)' },
    ],
    models: {
      gemini: ['gemini-2.5-flash'],
      deepseek: ['deepseek-chat'],
    },
  },
  {
    key: 'agent',
    label: 'WhatsApp assistant (classic agent)',
    providers: [{ value: 'gemini', label: 'Gemini' }],
    models: {
      gemini: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.5-flash-lite', 'gemini-3-pro-preview', 'gemini-3-flash-preview'],
    },
  },
  {
    key: 'agent_v2',
    label: 'WhatsApp assistant v2 (materials; empty = same as above)',
    providers: [{ value: 'gemini', label: 'Gemini' }],
    models: {
      gemini: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.5-flash-lite', 'gemini-3-pro-preview', 'gemini-3-flash-preview'],
    },
  },
];

function defaultModelForProvider(cap: string, pid: string): string {
  const def = CAPABILITY_DEFS.find((c) => c.key === cap);
  if (!def) return '';
  const list = def.models[pid];
  return list?.[0] ?? '';
}

// ──────────────────────────────────────────────────
// CapabilityCard
// ──────────────────────────────────────────────────
interface CapabilityCardProps {
  capKey: string;
  label: string;
  providers: { value: string; label: string }[];
  models: Record<string, string[]>;
  routing: CapabilityRouting;
  onRoutingChange: (key: string, routing: CapabilityRouting) => void;
}

function CapabilityCard({ capKey, label, providers, models, routing, onRoutingChange }: CapabilityCardProps) {
  const [isCustomPrimary, setIsCustomPrimary] = useState(false);
  const [isCustomFallback, setIsCustomFallback] = useState(false);
  const [customPrimaryModel, setCustomPrimaryModel] = useState('');
  const [customFallbackModel, setCustomFallbackModel] = useState('');

  // Initialise custom-model state from loaded config
  useEffect(() => {
    const knownModels = Object.values(models).flat();
    if (routing.model && routing.model !== 'fake' && !knownModels.includes(routing.model)) {
      setIsCustomPrimary(true);
      setCustomPrimaryModel(routing.model);
    }
    if (
      routing.fallback_model &&
      routing.fallback_model !== 'fake' &&
      !knownModels.includes(routing.fallback_model)
    ) {
      setIsCustomFallback(true);
      setCustomFallbackModel(routing.fallback_model);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleProviderChange = (pid: string) => {
    setIsCustomPrimary(false);
    onRoutingChange(capKey, {
      ...routing,
      provider_id: pid,
      model: defaultModelForProvider(capKey, pid),
    });
  };

  const handleModelChange = (val: string) => {
    if (val === 'custom') {
      setIsCustomPrimary(true);
    } else {
      setIsCustomPrimary(false);
      onRoutingChange(capKey, { ...routing, model: val });
    }
  };

  const handleFallbackProviderChange = (pid: string) => {
    setIsCustomFallback(false);
    onRoutingChange(capKey, {
      ...routing,
      fallback_provider_id: pid || null,
      fallback_model: pid ? defaultModelForProvider(capKey, pid) : null,
    });
  };

  const handleFallbackModelChange = (val: string) => {
    if (val === 'custom') {
      setIsCustomFallback(true);
    } else {
      setIsCustomFallback(false);
      onRoutingChange(capKey, { ...routing, fallback_model: val });
    }
  };

  const primaryModels = models[routing.provider_id] ?? [];
  const fallbackModels = models[routing.fallback_provider_id ?? ''] ?? [];

  // Fallback providers = all providers except the primary (and fake is fine as fallback)
  const fallbackProviderOptions = providers.filter((p) => p.value !== routing.provider_id);

  return (
    <div className="card" style={{ padding: 'var(--space-4)' }}>
      <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: 'var(--space-3)', color: 'var(--neutral-800)' }}>
        {label}
      </div>

      {/* Primary */}
      <div style={{ marginBottom: 'var(--space-4)' }}>
        <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--neutral-500)', marginBottom: 'var(--space-2)' }}>
          Primary
        </div>
        <div className="form-group" style={{ marginBottom: 'var(--space-2)' }}>
          <label>Provider</label>
          <select className="form-input" value={routing.provider_id} onChange={(e) => handleProviderChange(e.target.value)}>
            {providers.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>
        {routing.provider_id !== 'fake' && (
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Model</label>
            <select
              className="form-input"
              value={isCustomPrimary ? 'custom' : routing.model}
              onChange={(e) => handleModelChange(e.target.value)}
            >
              {primaryModels.map((m) => <option key={m} value={m}>{m}</option>)}
              <option value="custom">Custom model...</option>
            </select>
            {isCustomPrimary && (
              <input
                type="text"
                className="form-input"
                style={{ marginTop: 'var(--space-2)' }}
                placeholder="e.g. gemini-1.5-pro"
                value={customPrimaryModel}
                onChange={(e) => {
                  setCustomPrimaryModel(e.target.value);
                  onRoutingChange(capKey, { ...routing, model: e.target.value });
                }}
                required
              />
            )}
          </div>
        )}
      </div>

      {/* Fallback */}
      <div style={{
        borderTop: '1px dashed var(--neutral-200)',
        paddingTop: 'var(--space-3)',
      }}>
        <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--neutral-500)', marginBottom: 'var(--space-2)', display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}>
          <GitMerge size={12} /> Fallback
        </div>
        <div className="form-group" style={{ marginBottom: 'var(--space-2)' }}>
          <label>Provider</label>
          <select
            className="form-input"
            value={routing.fallback_provider_id ?? ''}
            onChange={(e) => handleFallbackProviderChange(e.target.value)}
          >
            <option value="">None</option>
            {fallbackProviderOptions.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>
        {routing.fallback_provider_id && routing.fallback_provider_id !== 'fake' && (
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Model</label>
            <select
              className="form-input"
              value={isCustomFallback ? 'custom' : (routing.fallback_model ?? '')}
              onChange={(e) => handleFallbackModelChange(e.target.value)}
            >
              {fallbackModels.map((m) => <option key={m} value={m}>{m}</option>)}
              <option value="custom">Custom model...</option>
            </select>
            {isCustomFallback && (
              <input
                type="text"
                className="form-input"
                style={{ marginTop: 'var(--space-2)' }}
                placeholder="e.g. deepseek-reasoner"
                value={customFallbackModel}
                onChange={(e) => {
                  setCustomFallbackModel(e.target.value);
                  onRoutingChange(capKey, { ...routing, fallback_model: e.target.value });
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────
// Main Providers page
// ──────────────────────────────────────────────────
export default function Providers() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, CheckResult>>({});

  const [routing, setRouting] = useState<Record<string, CapabilityRouting>>({
    voice: { provider_id: 'sarvam', model: 'saaras:v2.5', fallback_provider_id: null, fallback_model: null },
    extraction: { provider_id: 'gemini', model: 'gemini-2.5-flash', fallback_provider_id: null, fallback_model: null },
    vision: { provider_id: 'gemini', model: 'gemini-2.5-flash', fallback_provider_id: null, fallback_model: null },
    translation: { provider_id: 'gemini', model: 'gemini-2.5-flash', fallback_provider_id: null, fallback_model: null },
    agent: { provider_id: 'gemini', model: 'gemini-2.5-flash', fallback_provider_id: null, fallback_model: null },
    agent_v2: { provider_id: 'gemini', model: 'gemini-2.5-flash', fallback_provider_id: null, fallback_model: null },
  });

  const [secretsInput, setSecretsInput] = useState<Record<string, { api_key: string; base_url: string }>>({
    gemini: { api_key: '', base_url: '' },
    deepseek: { api_key: '', base_url: '' },
    sarvam: { api_key: '', base_url: '' },
  });

  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [providersRes, configRes] = await Promise.all([
        api.get<Provider[]>('/admin/providers'),
        api.get<AIConfig>('/admin/providers/config'),
      ]);
      setProviders(providersRes.data);

      const { routing: dbRouting, secrets: dbSecrets } = configRes.data;
      setRouting(dbRouting as Record<string, CapabilityRouting>);

      const newSecrets = { ...secretsInput };
      Object.keys(dbSecrets).forEach((pid) => {
        newSecrets[pid] = {
          api_key: dbSecrets[pid].api_key || '',
          base_url: dbSecrets[pid].base_url || '',
        };
      });
      setSecretsInput(newSecrets);
    } catch (err) {
      console.error('Failed to load configurations', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAll(); }, []);

  const handleRoutingChange = (key: string, newRouting: CapabilityRouting) => {
    setRouting((prev) => ({ ...prev, [key]: newRouting }));
  };

  const runCheck = (id: string) => {
    setChecking((prev) => ({ ...prev, [id]: true }));
    api
      .post<CheckResult>(`/admin/providers/${id}/check`)
      .then((res) => setResults((prev) => ({ ...prev, [id]: res.data })))
      .catch((err) =>
        setResults((prev) => ({
          ...prev,
          [id]: { ok: false, error: err.response?.data?.detail || 'Check failed', latency_ms: null },
        }))
      )
      .finally(() => setChecking((prev) => ({ ...prev, [id]: false })));
  };

  const handleApplyConfig = (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    api
      .put('/admin/providers/config', { routing, secrets: secretsInput })
      .then(() => {
        setSaveSuccess(true);
        fetchAll();
      })
      .catch((err) => setSaveError(err.response?.data?.detail || 'Failed to apply configuration'))
      .finally(() => setSaving(false));
  };

  if (loading) {
    return <div style={{ color: 'var(--neutral-500)', padding: 'var(--space-8)' }}>Loading configurations…</div>;
  }

  return (
    <div className="animate-fade-in" style={{ maxWidth: '1100px', paddingBottom: 'var(--space-12)' }}>
      <header style={{ marginBottom: 'var(--space-6)' }}>
        <h1>AI Routing & Providers</h1>
        <p className="subtitle">Route AI capabilities to specific providers and configure fallbacks.</p>
      </header>

      {saveSuccess && (
        <div style={{
          backgroundColor: 'rgba(126, 217, 87, 0.1)',
          border: '1px solid var(--primary)',
          padding: 'var(--space-4)',
          borderRadius: 'var(--radius-md)',
          marginBottom: 'var(--space-6)',
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)'
        }}>
          <CheckCircle2 size={20} style={{ color: 'var(--primary)' }} />
          <div>
            <strong>Configuration deployed!</strong> Changes applied instantly and cached in Redis.
          </div>
        </div>
      )}

      {saveError && (
        <div style={{
          backgroundColor: 'var(--error-soft)',
          border: '1px solid var(--error)',
          padding: 'var(--space-4)',
          borderRadius: 'var(--radius-md)',
          marginBottom: 'var(--space-6)',
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)'
        }}>
          <ShieldAlert size={20} style={{ color: 'var(--error)' }} />
          <div>
            <strong>Deployment failed:</strong> {saveError}
          </div>
        </div>
      )}

      <form onSubmit={handleApplyConfig}>
        {/* SECTION 1: AI ROUTING */}
        <section style={{ marginBottom: 'var(--space-8)' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 600, marginBottom: 'var(--space-4)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <Cpu size={20} /> AI Capability Routing
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))', gap: 'var(--space-4)' }}>
            {CAPABILITY_DEFS.map((cap) => (
              <CapabilityCard
                key={cap.key}
                capKey={cap.key}
                label={cap.label}
                providers={cap.providers}
                models={cap.models}
                routing={routing[cap.key] ?? { provider_id: 'fake', model: '', fallback_provider_id: null, fallback_model: null }}
                onRoutingChange={handleRoutingChange}
              />
            ))}
          </div>
        </section>

        {/* SECTION 2: API KEYS */}
        <section style={{ marginBottom: 'var(--space-8)' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 600, marginBottom: 'var(--space-4)', display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <Key size={20} /> Provider API Credentials
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(280px, 100%), 1fr))', gap: 'var(--space-6)' }}>
            {providers.map((p) => {
              const result = results[p.id];
              return (
                <div className="card" key={p.id}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--space-3)' }}>
                    <div>
                      <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0 }}>{p.name}</h3>
                      <div style={{ fontSize: '12px', color: 'var(--neutral-500)', marginTop: 4 }}>
                        Source: <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{p.source}</span>
                      </div>
                    </div>
                    <span className={`badge ${p.configured ? 'badge-info' : 'badge-warning'}`}>
                      {p.configured ? 'Active' : 'Not set'}
                    </span>
                  </div>

                  <div className="form-group" style={{ marginBottom: 'var(--space-3)' }}>
                    <label>API Key</label>
                    <input
                      type="password"
                      className="form-input"
                      placeholder={p.key_preview ? `${p.key_preview} (unchanged)` : 'Enter API Key'}
                      value={secretsInput[p.id]?.api_key || ''}
                      onChange={(e) => setSecretsInput({
                        ...secretsInput,
                        [p.id]: { ...secretsInput[p.id], api_key: e.target.value }
                      })}
                    />
                  </div>

                  {p.id === 'deepseek' && (
                    <div className="form-group" style={{ marginBottom: 'var(--space-4)' }}>
                      <label>API Base URL</label>
                      <input
                        type="text"
                        className="form-input"
                        placeholder="https://api.deepseek.com"
                        value={secretsInput.deepseek?.base_url || ''}
                        onChange={(e) => setSecretsInput({
                          ...secretsInput,
                          deepseek: { ...secretsInput.deepseek, base_url: e.target.value }
                        })}
                      />
                    </div>
                  )}

                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={!p.configured || checking[p.id]}
                    onClick={() => runCheck(p.id)}
                    style={{ width: '100%', marginTop: 'var(--space-2)' }}
                  >
                    {checking[p.id] ? <><RefreshCw size={14} className="spin" /> Checking…</> : 'Test Health'}
                  </button>

                  {result && (
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 'var(--space-2)',
                      fontSize: '13px',
                      color: result.ok ? 'var(--success)' : 'var(--error)',
                      marginTop: 'var(--space-3)'
                    }}>
                      {result.ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                      {result.ok ? `Working (${result.latency_ms?.toFixed(0)} ms)` : result.error || 'Health check failed'}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        {/* SUBMIT */}
        <div style={{
          borderTop: '1px solid var(--neutral-200)',
          paddingTop: 'var(--space-6)',
          display: 'flex',
          justifyContent: 'flex-end',
          gap: 'var(--space-4)'
        }}>
          <button type="button" className="btn-secondary" onClick={fetchAll} disabled={saving}>
            Reset
          </button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Applying & Deploying...' : 'Apply & Deploy AI Routing'}
          </button>
        </div>
      </form>
    </div>
  );
}
