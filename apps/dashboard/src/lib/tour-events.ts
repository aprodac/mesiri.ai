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

// UX-22: Help's "On this page" lights one thing up on the page, with what it means (components/tour.tsx draws it).
export const SPOT_EVENT = 'mesiri:spot'

export interface Spot {
  target: string
  title: string
  text: string
}

/** Light up one marked thing on the page and say what it is. */
export function spotOnPage(spot: Spot) {
  window.dispatchEvent(new CustomEvent<Spot>(SPOT_EVENT, { detail: spot }))
}

// The help panel opens again from the lit thing's "Back to help".
export const HELP_EVENT = 'mesiri:help'

export function openHelp() {
  window.dispatchEvent(new Event(HELP_EVENT))
}
