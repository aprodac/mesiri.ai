// SA-38 / SA-39: What works -- what the page's views share: the filters, how a message was sent, who sent it.
// The components (the WhatsApp conversation, the icons) are in WhatWorksChat.tsx.

export type State = 'works' | 'broken' | 'unsure';

export const WINDOWS = [
  { days: 1, label: 'Last 24 hours' },
  { days: 7, label: 'Last 7 days' },
  { days: 14, label: 'Last 14 days' },
  { days: 30, label: 'Last 30 days' },
];

export const STATE_COLOR: Record<State, { ink: string; soft: string }> = {
  works: { ink: 'var(--success)', soft: 'var(--success-soft)' },
  broken: { ink: 'var(--error)', soft: 'var(--error-soft)' },
  unsure: { ink: 'var(--warning)', soft: 'var(--warning-soft)' },
};

const HOW: Record<string, string> = {
  text: 'typed',
  voice: 'voice note',
  audio: 'voice note',
  image: 'photo',
  document: 'document',
  interactive: 'button tap',
  button: 'button tap',
  unknown: 'other',
};

export const muted = { color: 'var(--neutral-500)', fontSize: '12.5px' } as const;

export function how(type: string | null): string {
  return HOW[type || 'unknown'] || type || 'other';
}

export function when(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

export function role(value: string | null): string {
  return value ? value.replace(/_/g, ' ').toLowerCase() : '';
}

export function who(e: { sender: string | null; role: string | null; company: string | null; phone_tail?: string }): string {
  const name = e.sender || (e.phone_tail ? `Number ending ${e.phone_tail}` : 'Unknown sender');
  return [name, role(e.role), e.company].filter(Boolean).join(' · ');
}

/** On a phone the panel is below the list: bring it into view after a pick. */
export function showPanel() {
  if (window.matchMedia('(max-width: 1024px)').matches) {
    window.setTimeout(() => document.getElementById('ww-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  }
}


// SA-39: requests (intents) as the route answers them, and how they ended.

export type Ending = 'finished' | 'finished_after_question' | 'abandoned' | 'cancelled' | 'failed' | 'complained' | 'unsure' | 'open';
export type Bar = Record<Ending, number>;

export interface Intent {
  id: string;
  started_at: string;
  how: string;
  company: string | null;
  messages: string[];
  text: string;
  sender_name: string | null;
  sender_role: string | null;
  capability: string;
  section: string;
  ending: Ending;
  reason: string;
  journeys: string[];
  correlation_ids: string[];
}

/** The endings, in the order the bars draw them. */
export const ENDINGS: { key: Ending; label: string; color: string; note: string }[] = [
  { key: 'finished', label: 'Finished', color: 'var(--success)', note: 'Saved, sent, or answered from the records.' },
  { key: 'finished_after_question', label: 'Finished after a question', color: '#6FBF8A', note: 'Mesiri asked one thing first, then it was saved or answered.' },
  { key: 'abandoned', label: 'Left without Save', color: 'var(--warning)', note: 'A card or a question was still waiting when the person stopped.' },
  { key: 'cancelled', label: 'Cancelled', color: 'var(--neutral-400)', note: 'The person cancelled the card.' },
  { key: 'failed', label: 'Failed', color: 'var(--error)', note: 'No reply, an outage, a refusal, or a save that did not save.' },
  { key: 'complained', label: "Complaint or 'not yet'", color: '#9F1239', note: 'The person said the reply was bad or wrong, or Mesiri cannot do it yet and told the team.' },
  { key: 'unsure', label: 'Not sure', color: 'var(--neutral-200)', note: 'Mesiri replied but the record shows nothing done (no tool, a question back). Each one says why.' },
];
export const ENDING = Object.fromEntries(ENDINGS.map((e) => [e.key, e])) as Record<Ending, (typeof ENDINGS)[number]>;
export const GOOD: Ending[] = ['finished', 'finished_after_question'];

export function pct(part: number, whole: number): number {
  return whole ? Math.round((part / whole) * 100) : 0;
}

export function finished(bar: Bar): number {
  return GOOD.reduce((n, k) => n + (bar[k] || 0), 0);
}

