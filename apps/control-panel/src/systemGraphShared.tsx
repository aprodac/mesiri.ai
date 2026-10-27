import { useEffect, useId, useRef, useState } from 'react';
import { AlertCircle, ArrowRight } from 'lucide-react';
import mermaid from 'mermaid';

export interface StageNode {
  id: string;
  label: string;
  description: string | null;
}
export interface PipelineStage {
  key: string;
  title: string;
  summary: string;
  nodes: StageNode[];
}
export interface WorkflowGraphInfo {
  workflow_key: string;
  title: string;
  implemented: boolean;
  canonical_event: string | null;
  semantic_type: string | null;
  required_fields: string[];
  required_field_labels: string[];
  node_names: string[];
  example_messages: string[];
  mermaid: string | null;
  lifecycle_mermaid: string | null;
}
export interface FastPathInfo {
  key: string;
  title: string;
  description: string;
  example_messages: string[];
}
export interface HardcodedReplyInfo {
  key: string;
  title: string;
  source: string;
  trigger: string;
  template: string;
  flag: string | null;
}
export interface SemanticTypeInfo {
  semantic_type: string;
  description: string;
  detection: string;
  canonical_events: string[];
  workflow_keys: string[];
  implemented: boolean;
  routes_to_reply: string | null;
  required_field_labels: string[];
  example_messages: string[];
}
export interface SystemGraphResponse {
  mermaid: string;
  fast_paths: FastPathInfo[];
  hardcoded_replies: HardcodedReplyInfo[];
  stages: PipelineStage[];
  semantic_types: SemanticTypeInfo[];
  workflows: WorkflowGraphInfo[];
}

export interface Organization {
  id: string;
  name: string;
}
export interface OrgUser {
  id: string;
  full_name: string | null;
  email: string | null;
  role: string | null;
  whatsapp_number: string | null;
}
export interface ProviderExecution {
  provider: string;
  operation: string;
  model: string | null;
  latency_ms: number | null;
  succeeded: boolean;
  error_code: string | null;
}
export interface ReplyOption {
  id: string;
  title: string;
  description?: string | null;
}

export interface StructuredReply {
  type: 'text' | 'buttons' | 'list';
  text: string;
  buttons?: ReplyOption[];
  list_rows?: ReplyOption[];
  button_label?: string | null;
}

export interface SimulateRequest {
  organization_id: string;
  user_id: string;
  text?: string;
  modality?: 'text' | 'interactive';
  interactive_reply_id?: string;
}

export interface SimulateResponse {
  dry_run: boolean;
  ran_as_wa_id: string;
  routed_via: string;
  replies: string[];
  structured_replies?: StructuredReply[];
  understanding: {
    semantic_type?: string;
    transcript?: string;
    translated_text?: string;
    provider_executions?: ProviderExecution[];
  } | null;
  resolved_context: unknown | null;
  canonical_event: { event_type?: string } | null;
  planner_decision: { decision_type?: string; workflow_key?: string } | null;
  workflow_run: { status?: string; workflow_key?: string } | null;
}

mermaid.initialize({
  startOnLoad: false,
  theme: 'neutral',
  securityLevel: 'strict',
  flowchart: { curve: 'basis', htmlLabels: true },
});

/** Renders one Mermaid source string into an <svg>, showing parse errors inline. */
export function MermaidDiagram({ source }: { source: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rawId = useId();
  const id = `mmd-${rawId.replace(/[^a-zA-Z0-9]/g, '')}`;
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    mermaid
      .render(id, source)
      .then(({ svg }) => {
        if (!cancelled && containerRef.current) containerRef.current.innerHTML = svg;
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || 'Failed to render diagram');
      });
    return () => {
      cancelled = true;
    };
  }, [id, source]);

  if (error) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--danger, #d33)', fontSize: '13px' }}>
        <AlertCircle size={14} /> {error}
      </div>
    );
  }
  return <div ref={containerRef} style={{ overflowX: 'auto' }} />;
}

export const ROUTED_VIA_LABELS: Record<string, string> = {
  identity_gate: 'Identity gate (unregistered / no org / suspended)',
  confirmation_fast_path: 'Confirmation fast path — no AI',
  category_tap: 'Category menu tap — no AI',
  greeting_trigger: 'Greeting trigger — no AI',
  whoami_trigger: 'Who-am-I trigger — no AI',
  material_gate_resume: 'Material gate resolution — no AI',
  unit_gate_resume: 'Unit mismatch resolution — no AI',
  stock_gate_resume: 'Stock choice resolution — no AI',
  project_gate_resume: 'Project picker resolution — no AI',
  site_gate_resume: 'Site picker resolution — no AI',
  ai_pipeline: 'AI pipeline',
};

export const chipStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '6px',
  padding: '4px 10px',
  borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--neutral-200, #e5e5e5)',
  background: 'var(--neutral-50, #fafafa)',
  fontSize: '12px',
  cursor: 'pointer',
  color: 'var(--neutral-700, #444)',
};

// Small monospace pill used to render the semantic-type routing flow
// (semantic → event → workflow) inline.
export const pillStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '3px 8px',
  borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--neutral-200, #e5e5e5)',
  background: 'var(--neutral-50, #fafafa)',
  fontSize: '11px',
  fontFamily: 'monospace',
  color: 'var(--neutral-700, #444)',
  // Short labels stay on one line; a long one wraps inside the card.
  maxWidth: '100%',
  overflowWrap: 'anywhere',
};

/** One `pill → pill → …` chain, wrapping gracefully at narrow widths. */
export const RoutingFlow = ({ steps }: { steps: { label: string; muted?: boolean }[] }) => (
  <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '6px' }}>
    {steps.map((step, i) => (
      <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', maxWidth: '100%' }}>
        <span style={step.muted ? { ...pillStyle, color: 'var(--neutral-500)', fontStyle: 'italic' } : pillStyle}>
          {step.label}
        </span>
        {i < steps.length - 1 && <ArrowRight size={12} style={{ color: 'var(--neutral-400, #aaa)', flexShrink: 0 }} />}
      </span>
    ))}
  </div>
);
