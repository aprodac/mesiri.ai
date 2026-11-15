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

