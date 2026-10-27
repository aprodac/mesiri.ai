// SA-17: shapes and formatters shared by the Reply Insights page
// (Replies.tsx), its charts (replyCharts.tsx) and its feed (ReplyFeed.tsx).
// Reads GET /admin/replies, /admin/replies/messages and
// /admin/replies/messages/{correlation_id}/calls.

export interface TokenSums {
  ai_calls: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  ai_cost_inr: string;
  unpriced: number;
}

export interface ReplySummary extends TokenSums {
  messages: number;
  replied: number;
  failed: number;
  no_ai: number;
  with_ai: number;
  avg_ms: number | null;
  p50_ms: number | null;
  p90_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
  [band: `band_${number}`]: number;
}

export interface TimelinePoint {
  bucket: string; // Indian local time, no zone
  messages: number;
  p50_ms: number | null;
  p95_ms: number | null;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  ai_cost_inr: string;
}

export interface ModelRow {
  provider: string;
  model: string | null;
  calls: number;
  avg_ms: number | null;
  p95_ms: number | null;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  ai_cost_inr: string;
  unpriced: number;
}

export interface StepRow {
  step: string;
  calls: number;
  avg_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  ai_cost_inr: string;
}

export interface Overview {
  since: string;
  until: string;
  step_minutes: number;
  bands_ms: number[];
  summary: ReplySummary;
  timeline: TimelinePoint[];
  by_model: ModelRow[];
  by_step: StepRow[];
}

export interface FeedItem {
  correlation_id: string;
  received_at: string;
  processed_at: string | null;
  reply_ms: number | null;
  message_type: string;
  processing_status: string;
  organization_id: string | null;
  organization_name: string | null;
  sender_wa_id: string;
  sender_name: string | null;
  text: string | null;
  reply: string | null;
  ai_calls: number;
  ai_ms: number | null;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  total_tokens: number | null;
  ai_cost_inr: string;
  unpriced: number;
}

export interface Feed {
  total: number;
  items: FeedItem[];
}

export interface CallRow {
  created_at: string;
  provider: string;
  model: string | null;
  operation: string;
  purpose: string | null;
  latency_ms: number | null;
  input_tokens: number | null;
  cached_input_tokens: number | null;
  audio_input_tokens: number | null;
  output_tokens: number | null;
  ai_cost_inr: string | null;
}

/** 850 ms · 3.4 s · 2m 05s */
export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  const n = Number(ms);
  if (n < 1000) return `${Math.round(n)} ms`;
  if (n < 60_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)} s`;
  const s = Math.round(n / 1000);
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
}

/** 980 · 12.4K · 3.1M -- K/M, as tokens are counted everywhere (not lakh). */
export function compact(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 1 });
}

export function full(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : Number(n).toLocaleString('en-IN');
}

/** ₹ with paise kept for the small amounts most rows are (as Costs does). */
export function inr(value: string | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: n < 1 ? 4 : 2 })}`;
}

export function when(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  });
}

/** A timeline bucket (already Indian local time) as a short label. */
export function bucketLabel(bucket: string, stepMinutes: number): string {
  const d = new Date(bucket.replace(' ', 'T'));
  if (stepMinutes >= 1440) return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  const time = d.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
  if (stepMinutes >= 360) return `${d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}, ${time}`;
  return time;
}

/** "just now" · "12 min ago" · "3 days ago" */
export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return 'never';
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

/** Speed of a reply, for its pill: good under 5 s, slow from 15 s, very slow from 30 s. */
export type Speed = 'fast' | 'ok' | 'slow' | 'very-slow' | 'none';

export function speedOf(ms: number | null | undefined): Speed {
  if (ms === null || ms === undefined) return 'none';
  if (ms < 5_000) return 'fast';
  if (ms < 15_000) return 'ok';
  if (ms < 30_000) return 'slow';
  return 'very-slow';
}

export const SPEED_BADGE: Record<Speed, string> = {
  fast: 'badge badge-success',
  ok: 'badge badge-info',
  slow: 'badge badge-warning',
  'very-slow': 'badge badge-error',
  none: 'badge',
};

/** Chart series colours (validated: CVD-safe on the white surface). */
export const SERIES = {
  blue: '#2a78d6',
  orange: '#eb6834',
  aqua: '#1baf7a',
} as const;

export const muted = { color: 'var(--neutral-500)', fontSize: '13px' } as const;
export const right = { textAlign: 'right' } as const;
export const num = { textAlign: 'right', fontVariantNumeric: 'tabular-nums' } as const;
