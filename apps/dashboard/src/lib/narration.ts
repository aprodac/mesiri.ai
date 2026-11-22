// UX-101: one narrator at a time. Two systems speak on the dashboard: the scenes of the sample company
// (lib/scene-sound.ts: chapter cards, the opening, the days passing) and the guide voice (lib/voice.ts: the tours,
// walkthroughs and hints). They used to play over each other: a chapter card read its line while the tour step under
// it read its own. The rule now: a scene on screen has the floor. A guide line asked for meanwhile waits until the
// scene is gone, and one already playing pauses and goes on after it. Between guide voices, a new line stops any
// other voice's line (the tour and a hint never talk at once).

let scenes = 0
const sceneListeners = new Set<(on: boolean) => void>()

/** A scene with sound is on screen. */
export function scenePlaying(): boolean {
  return scenes > 0
}

/** A scene with sound came on screen; call the returned function when it goes. */
export function sceneBegin(): () => void {
  scenes++
  if (scenes === 1) for (const l of sceneListeners) l(true)
  let ended = false
  return () => {
    if (ended) return
    ended = true
    scenes--
    // A scene that hands over to the next (one phase to the next) ends and begins in the same commit: let it settle
    // before telling the voices the floor is free.
    if (scenes === 0)
      window.setTimeout(() => {
        if (scenes === 0) for (const l of sceneListeners) l(false)
      }, 400)
  }
}

/** Told `true` when the first scene comes on, `false` when the last has gone (and stayed gone a moment). */
export function onScenes(listener: (on: boolean) => void): () => void {
  sceneListeners.add(listener)
  return () => {
    sceneListeners.delete(listener)
  }
}

/** Resolves once no scene is on screen. */
export function noScene(): Promise<void> {
  if (!scenePlaying()) return Promise.resolve()
  return new Promise((resolve) => {
    const off = onScenes((on) => {
      if (!on) {
        off()
        resolve()
      }
    })
  })
}

// The guide and Live voices' players: a new line from one stops the others.
const players = new Set<HTMLAudioElement>()

export function addPlayer(el: HTMLAudioElement): void {
  players.add(el)
}

export function removePlayer(el: HTMLAudioElement): void {
  players.delete(el)
}

/** Pause every voice player but `el`. */
export function quietOthers(el: HTMLAudioElement): void {
  for (const p of players) if (p !== el && !p.paused) p.pause()
}
