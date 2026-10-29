import * as React from 'react'
import { useSearchParams } from 'react-router-dom'

/** A page filter kept in the address (?q=slab&status=COMPLETED), so it
 * survives Back, refresh and a shared link. The default value is left out of
 * the address. Updates replace the history entry rather than adding one per
 * keystroke, and keep every other parameter (the scope's project/site). */
export function useUrlState<T extends string>(key: string, fallback: T): [T, (value: T) => void] {
  const [params, setParams] = useSearchParams()
  const value = (params.get(key) as T | null) ?? fallback
  const set = React.useCallback(
    (next: T) => {
      setParams(
        (prev) => {
          if (next === fallback || next === '') prev.delete(key)
          else prev.set(key, next)
          return prev
        },
        { replace: true },
      )
    },
    [key, fallback, setParams],
  )
  return [value, set]
}
