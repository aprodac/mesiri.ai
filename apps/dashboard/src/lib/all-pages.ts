// UX-74: open All pages (components/all-pages.tsx, mounted once in the app layout) from anywhere.
export const ALL_PAGES_EVENT = 'mesiri:all-pages'

export function openAllPages() {
  window.dispatchEvent(new Event(ALL_PAGES_EVENT))
}
