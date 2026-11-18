import { useUrlState } from '@/lib/url-state'

// UX-44: one Bars / Numbers switch and one column sort for every list that can be read as figures (Cost overview,
// Green / red, Materials vs BOQ). The view is kept in the address (?show=numbers) and remembered per page in this
// browser; the sorted column in ?col= and ?dir=. Drawn by components/page/numbers-view.tsx.

export type ShowMode = 'bars' | 'numbers'

function remembered(key: string): string {
  try {
    return localStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

/** Bars or Numbers for one page (`key` names it in the browser's memory). */
export function useShowMode(key: string): [ShowMode, (v: ShowMode) => void] {
  const [param, setParam] = useUrlState<string>('show', '')
  const show: ShowMode = (param || remembered(`${key}.show`)) === 'numbers' ? 'numbers' : 'bars'
  const set = (v: ShowMode) => {
    setParam(v === 'bars' ? '' : v)
    try {
      localStorage.setItem(`${key}.show`, v)
    } catch {
      /* storage blocked: the address still holds it */
    }
  }
  return [show, set]
}

/** A column a Numbers table can sort by: the figure (null sorts last) or, for the name column, the text. */
export interface SortableColumn<T> {
  key: string
  sortValue: (row: T) => number | string | null
}

/**
 * Which column sorts, which way. A header pressed sorts biggest first (A to Z for text), again the other way, a
 * third time back to the page's own order.
 */
export function useColumnSort() {
  const [col, setCol] = useUrlState<string>('col', '')
  const [dir, setDir] = useUrlState<string>('dir', '')
  const onSort = (key: string, text = false) => {
    const first = text ? 'asc' : 'desc'
    const second = text ? 'desc' : 'asc'
    if (col !== key) {
      setCol(key)
      setDir(first)
    } else if ((dir || first) === first) setDir(second)
    else {
      setCol('')
      setDir('')
    }
  }
  const clear = () => {
    setCol('')
    setDir('')
  }
  return { col, dir: (dir || 'desc') as 'asc' | 'desc', onSort, clear }
}

/** The rows sorted by a column; a figure that is not there (null) always goes last. */
export function sortByColumn<T>(rows: T[], columns: SortableColumn<T>[], col: string, dir: 'asc' | 'desc'): T[] | null {
  const c = columns.find((x) => x.key === col)
  if (!c) return null
  const sign = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const va = c.sortValue(a)
    const vb = c.sortValue(b)
    if (va === null && vb === null) return 0
    if (va === null) return 1
    if (vb === null) return -1
    return typeof va === 'string' ? sign * va.localeCompare(String(vb)) : sign * (va - Number(vb))
  })
}
