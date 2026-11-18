import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { updateParams } from '@/lib/url-state'

// UX-36: paging a list in the browser; drawn by components/page/pager.tsx.

/** When a person last clicked, tapped or typed: a filter they changed resets the page; the app settling never does. */
let lastInput = 0
if (typeof window !== 'undefined') {
  for (const type of ['pointerdown', 'keydown', 'input'] as const) window.addEventListener(type, () => { lastInput = Date.now() }, { capture: true, passive: true })
}
const byPerson = () => Date.now() - lastInput < 1500
/** The scope bar's own parameters: it writes them as a page settles. */
const SCOPE_KEYS = new Set(['project', 'site', 'id'])

export const PAGE_SIZES = [25, 50, 100] as const

/** The page to show and its rows, with the page clamped to the list. */
export function usePaged<T>(rows: T[], page: number, size: number) {
  const pages = Math.max(1, Math.ceil(rows.length / size))
  const current = Math.min(Math.max(1, page), pages)
  const shown = React.useMemo(() => rows.slice((current - 1) * size, current * size), [rows, current, size])
  return { shown, page: current, pages, from: rows.length ? (current - 1) * size + 1 : 0, to: Math.min(current * size, rows.length), total: rows.length }
}

/**
 * `usePaged` with the page kept in the address (`?page=`, or `key` when a page has two lists), back to page 1 when
 * `resetOn` changes (the filters), and the props `<Pager>` takes: `<Pager {...paged.pager} noun="bills" />`.
 */
export function usePagedUrl<T>(rows: T[], { key = 'page', size: fixed, resetOn = '' }: { key?: string; size?: number; resetOn?: string } = {}) {
  const [params, setParams] = useSearchParams()
  const sizeKey = key === 'page' ? 'size' : `${key}size`
  const asked = Number(params.get(sizeKey))
  const size = fixed ?? ((PAGE_SIZES as readonly number[]).includes(asked) ? asked : PAGE_SIZES[0])
  const paged = usePaged(rows, Number(params.get(key)) || 1, size)
  const set = React.useCallback(
    (changes: Record<string, string | null>) =>
      updateParams(setParams, (next) => {
        for (const [k, v] of Object.entries(changes)) {
          if (v === null) next.delete(k)
          else next.set(k, v)
        }
      }),
    [setParams],
  )
  // A changed filter starts again from the first page (not on the first render: a link may name a page). With no
  // `resetOn`, the filters are the address's other parameters (most pages keep them there) and how many rows match
  // (a search kept in the page's own state).
  const others = [...params.entries()].filter(([k]) => k !== key && k !== sizeKey && !SCOPE_KEYS.has(k)).map(([k, v]) => `${k}=${v}`).join('&')
  const watch = resetOn || `${others}|${rows.length}`
  // Not while the list is still arriving (0 rows to some is a load, not a filter).
  // Only `watch` triggers it: the router's setter is a new function after every change of address.
  const loaded = React.useRef(false)
  const setRef = React.useRef(set)
  setRef.current = set
  React.useEffect(() => {
    if (!loaded.current) {
      loaded.current = rows.length > 0
      return
    }
    if (byPerson()) setRef.current({ [key]: null })
  }, [watch, key]) // eslint-disable-line react-hooks/exhaustive-deps
  return {
    ...paged,
    pager: {
      page: paged.page,
      pages: paged.pages,
      from: paged.from,
      to: paged.to,
      total: paged.total,
      size: fixed === undefined ? size : undefined,
      onPage: (p: number) => set({ [key]: p <= 1 ? null : String(p) }),
      onSize: fixed === undefined ? (n: number) => set({ [sizeKey]: n === PAGE_SIZES[0] ? null : String(n), [key]: null }) : undefined,
    },
  }
}

/**
 * For a list the server pages: the `offset` and `limit` to ask for, from the page in the address, and the props
 * `<Pager>` takes once the answer says how many there are: `<Pager {...server.pager(total)} noun="reports" />`.
 */
export function useServerPage({ key = 'page', size, resetOn = '' }: { key?: string; size: number; resetOn?: string }) {
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get(key)) || 1)
  const setPage = React.useCallback(
    (p: number) =>
      updateParams(setParams, (next) => {
        if (p <= 1) next.delete(key)
        else next.set(key, String(p))
      }),
    [key, setParams],
  )
  const pageRef = React.useRef(setPage)
  pageRef.current = setPage
  const first = React.useRef(true)
  React.useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    if (byPerson()) pageRef.current(1)
  }, [resetOn])
  return {
    page,
    offset: (page - 1) * size,
    limit: size,
    pager: (total: number, shown: number) => {
      const pages = Math.max(1, Math.ceil(total / size))
      // A page past the end (the list got shorter): go to the last one.
      if (total > 0 && page > pages) queueMicrotask(() => setPage(pages))
      const from = total ? (page - 1) * size + 1 : 0
      return { page: Math.min(page, pages), pages, from, to: from ? from + shown - 1 : 0, total, onPage: setPage }
    },
  }
}
