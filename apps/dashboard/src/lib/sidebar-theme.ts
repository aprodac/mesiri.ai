import { useCallback, useState } from 'react'

/**
 * Sidebar look, picked per user and remembered in this browser.
 * Taupe is the default (UX-14, 17 Nov 2026: #6E665B chosen after customer demos; Charcoal and Midnight dropped the same
 * day, and a saved Charcoal choice now opens as Taupe). Light follows the app's tokens (so it also darkens in dark mode).
 * Separate from the app's light/dark switch.
 */
export const SIDEBAR_THEME_NAMES = {
  taupe: 'Taupe',
  light: 'Light',
  sand: 'Sand',
  green: 'Site green',
} as const

export type SidebarTheme = keyof typeof SIDEBAR_THEME_NAMES

export const DEFAULT_SIDEBAR_THEME: SidebarTheme = 'taupe'

const STORAGE_PREFIX = 'mesiri.sidebar-theme'

function storageKey(userId: string | undefined): string {
  return userId ? `${STORAGE_PREFIX}.${userId}` : STORAGE_PREFIX
}

function isTheme(value: string | null): value is SidebarTheme {
  return value !== null && Object.prototype.hasOwnProperty.call(SIDEBAR_THEME_NAMES, value)
}

function readSaved(userId: string | undefined): SidebarTheme {
  try {
    const saved = localStorage.getItem(storageKey(userId))
    return isTheme(saved) ? saved : DEFAULT_SIDEBAR_THEME
  } catch {
    return DEFAULT_SIDEBAR_THEME
  }
}

export function useSidebarTheme(
  userId: string | undefined
): [SidebarTheme, (theme: SidebarTheme) => void] {
  // Keyed by user so a shared office computer keeps each person's choice;
  // re-read when the signed-in user changes.
  const [saved, setSaved] = useState(() => ({ userId, theme: readSaved(userId) }))
  const theme = saved.userId === userId ? saved.theme : readSaved(userId)
  if (saved.userId !== userId) setSaved({ userId, theme })

  const setTheme = useCallback(
    (next: SidebarTheme) => {
      setSaved({ userId, theme: next })
      try {
        localStorage.setItem(storageKey(userId), next)
      } catch {
        // Private window or blocked storage: the choice lasts this visit only.
      }
    },
    [userId]
  )

  return [theme, setTheme]
}
