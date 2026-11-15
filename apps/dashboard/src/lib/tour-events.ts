// components/tour.tsx listens for this event; Help's "Show me around this page" fires it (like lib/jump.ts).
export const TOUR_EVENT = 'mesiri:tour'

/** Play this page's guided tour now, whether or not it was seen. */
export function showMeAround() {
  window.dispatchEvent(new Event(TOUR_EVENT))
}

// Learn Mesiri (SS-42): components/walkthrough.tsx listens for this; the Learn page's Start fires it.
export const WALKTHROUGH_EVENT = 'mesiri:walkthrough'

/** Start a walkthrough (lib/walkthroughs.ts) by its id. */
export function startWalkthrough(id: string) {
  window.dispatchEvent(new CustomEvent<string>(WALKTHROUGH_EVENT, { detail: id }))
}

let walking = false

/** While a walkthrough runs, the page tours don't start by themselves on the pages it visits. */
export function setWalkthroughRunning(on: boolean) {
  walking = on
}

export function walkthroughRunning(): boolean {
  return walking
}
