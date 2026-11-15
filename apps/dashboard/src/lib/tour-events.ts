// components/tour.tsx listens for this event; Help's "Show me around this page" fires it (like lib/jump.ts).
export const TOUR_EVENT = 'mesiri:tour'

/** Play this page's guided tour now, whether or not it was seen. */
export function showMeAround() {
  window.dispatchEvent(new Event(TOUR_EVENT))
}
