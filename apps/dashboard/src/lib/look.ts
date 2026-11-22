import { useCallback, useSyncExternalStore } from 'react'

/**
 * The dashboard's look (WEB-103, asked 22 Nov 2026: "keep the current theme also as an option"). Blueprint is the
 * design system shared with the phone app (WEB-102, docs/DESIGN.md "Brand"); Classic is the look before it (sand
 * page, charcoal sidebar, site yellow, IBM Plex Sans). One choice per browser, set from the account menu beside
 * Dark mode. It sets `data-look` on <html>: index.css swaps the tokens and fonts, and the sidebar and the title
 * block read `useLook()` for their shape. Replaces lib/sidebar-theme.ts (one look since UX-16).
 */
export const LOOKS = {
  blueprint: 'Blueprint',
  classic: 'Classic',
} as const

export type Look = keyof typeof LOOKS

export const DEFAULT_LOOK: Look = 'blueprint'

const KEY = 'mesiri.look'

function isLook(value: string | null): value is Look {
  return value !== null && Object.prototype.hasOwnProperty.call(LOOKS, value)
}

function readSaved(): Look {
  try {
    const saved = localStorage.getItem(KEY)
    return isLook(saved) ? saved : DEFAULT_LOOK
  } catch {
    return DEFAULT_LOOK
  }
}

let current: Look = typeof window === 'undefined' ? DEFAULT_LOOK : readSaved()
const listeners = new Set<() => void>()

function apply(look: Look) {
  if (typeof document !== 'undefined') document.documentElement.dataset.look = look
}

// Applied when this module loads (main.tsx imports it before the first render), so the page never flashes the
// other look.
apply(current)

export function setLook(next: Look) {
  current = next
  apply(next)
  try {
    localStorage.setItem(KEY, next)
  } catch {
    // Private window or blocked storage: the choice lasts this visit only.
  }
  listeners.forEach((l) => l())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useLook(): [Look, (look: Look) => void] {
  const look = useSyncExternalStore(subscribe, () => current, () => DEFAULT_LOOK)
  const set = useCallback((next: Look) => setLook(next), [])
  return [look, set]
}
