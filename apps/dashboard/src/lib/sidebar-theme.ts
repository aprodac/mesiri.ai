import { useCallback, useState } from 'react'

/**
 * Sidebar look, picked per user and remembered in this browser.
 * Charcoal is the default; Light follows the app's tokens (so it also
 * darkens in dark mode). Separate from the app's light/dark switch.
 */
export type SidebarTheme = 'charcoal' | 'light'

const STORAGE_PREFIX = 'mesiri.sidebar-theme'

function storageKey(userId: string | undefined): string {
  return userId ? `${STORAGE_PREFIX}.${userId}` : STORAGE_PREFIX
}

function readSaved(userId: string | undefined): SidebarTheme {
  try {
    return localStorage.getItem(storageKey(userId)) === 'light' ? 'light' : 'charcoal'
  } catch {
    return 'charcoal'
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
