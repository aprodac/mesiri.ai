import { useCallback, useState } from 'react'

/**
 * Sidebar look. One look since UX-16 (17 Nov 2026): Sand, which follows the app's light/dark switch (cream in light
 * mode, dark in dark mode). The colour menu and the other looks (Charcoal, Light, Taupe, Midnight, Site green) were
 * dropped on request; any saved choice now opens as Sand. Kept as a per-user setting so a look can come back without
 * touching the sidebar.
 */
export const SIDEBAR_THEME_NAMES = {
  sand: 'Sand',
} as const

export type SidebarTheme = keyof typeof SIDEBAR_THEME_NAMES

export const DEFAULT_SIDEBAR_THEME: SidebarTheme = 'sand'

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
