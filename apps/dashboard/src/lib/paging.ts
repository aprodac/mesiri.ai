import * as React from 'react'

// UX-36: paging a list in the browser; drawn by components/page/pager.tsx.

export const PAGE_SIZES = [25, 50, 100] as const

/** The page to show and its rows, with the page clamped to the list. */
export function usePaged<T>(rows: T[], page: number, size: number) {
  const pages = Math.max(1, Math.ceil(rows.length / size))
  const current = Math.min(Math.max(1, page), pages)
  const shown = React.useMemo(() => rows.slice((current - 1) * size, current * size), [rows, current, size])
  return { shown, page: current, pages, from: rows.length ? (current - 1) * size + 1 : 0, to: Math.min(current * size, rows.length), total: rows.length }
}
