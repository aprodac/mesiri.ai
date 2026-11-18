import * as React from 'react'
import { useSearchParams } from 'react-router-dom'

type SetParams = ReturnType<typeof useSearchParams>[1]

// UX-43: React Router hands a change function the address as it was at the last render, so two changes in the same
// moment ("clear the search" and "clear the filter", "set the column" and "set the direction", a filter and "back to
// page 1") lost all but the last. Every change goes through here: one made in the same tick builds on the one before.
let pending: URLSearchParams | null = null

/** Change some of the address's parameters, on top of any other change made in this same moment. */
export function updateParams(setParams: SetParams, change: (params: URLSearchParams) => void, replace = true): void {
  setParams(
    (prev) => {
      const next = new URLSearchParams(pending ?? prev)
      change(next)
      if (!pending) queueMicrotask(() => { pending = null })
      pending = next
      return next
    },
    { replace },
  )
}

/** A page filter kept in the address (?q=slab&status=COMPLETED), so it
 * survives Back, refresh and a shared link. The default value is left out of
 * the address. Updates replace the history entry rather than adding one per
 * keystroke, and keep every other parameter (the scope's project/site). */
export function useUrlState<T extends string>(key: string, fallback: T): [T, (value: T) => void] {
  const [params, setParams] = useSearchParams()
  const value = (params.get(key) as T | null) ?? fallback
  const set = React.useCallback(
    (next: T) => {
      updateParams(setParams, (p) => {
        if (next === fallback || next === '') p.delete(key)
        else p.set(key, next)
      })
    },
    [key, fallback, setParams],
  )
  return [value, set]
}
