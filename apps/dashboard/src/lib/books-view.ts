import { useSearchParams } from 'react-router-dom'
import { useIsMobile } from '@/hooks/use-mobile'
import { useAuth } from '@/lib/AuthContext'
import { useStartMode } from '@/lib/start-mode'

// UX-31 / UX-33: which way a statement opens (Profit & loss, Balance sheet). The same numbers, a different first view:
// the person's last pick (this browser) -> on a phone, the owner's view -> the Tally view for finance people and for
// those who came from other accounting software (start mode "switching") -> the owner's view. `?view=` wins.

export type BooksView = 'simple' | 'statement' | 'months'

function saved(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function useBooksView<V extends BooksView>(page: string, allowed: readonly V[], aliases: Record<string, V> = {}): [V, (v: V) => void] {
  const [params, setParams] = useSearchParams()
  const phone = useIsMobile()
  const { mode } = useStartMode()
  const { me } = useAuth()
  const key = `mesiri.${page}.view`
  const as = (v: string | null): V | null => (v === null ? null : aliases[v] ?? ((allowed as readonly string[]).includes(v) ? (v as V) : null))
  const fallback = (): V => {
    if (phone) return 'simple' as V
    if (String(me?.role ?? '').toUpperCase() === 'FINANCE' || mode === 'switching') return 'statement' as V
    return 'simple' as V
  }
  const view = as(params.get('view')) ?? as(saved(key)) ?? fallback()
  const pick = (v: V) => {
    try {
      localStorage.setItem(key, v)
    } catch {
      // A browser without storage still switches; the pick is just not remembered.
    }
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        n.set('view', v)
        return n
      },
      { replace: true },
    )
  }
  return [view, pick]
}
