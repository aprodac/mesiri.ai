import * as React from 'react'

// "Show planned modules" (WEB-72, decided 7 Nov 2026): the construction-ERP pages Mesiri has
// planned but not built appear in the sidebar only while this is on. Off by default, so a
// customer sees only working pages (docs/DESIGN.md "Pages and routes"); the team turns it on
// for planning and demos. Kept per browser.

const KEY = 'mesiri_show_planned_modules'
const EVENT = 'mesiri-preview-change'

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function usePlannedPreview(): [boolean, (on: boolean) => void] {
  const [on, setOn] = React.useState(read)
  React.useEffect(() => {
    const sync = () => setOn(read())
    window.addEventListener(EVENT, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(EVENT, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])
  const set = React.useCallback((next: boolean) => {
    try {
      if (next) localStorage.setItem(KEY, '1')
      else localStorage.removeItem(KEY)
    } catch {
      // Private mode: the switch lasts until reload.
    }
    setOn(next)
    window.dispatchEvent(new Event(EVENT))
  }, [])
  return [on, set]
}
