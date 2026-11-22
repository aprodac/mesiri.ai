import * as React from 'react'
import { SCENE_AUDIO, type SceneAudioId } from './scene-audio.gen'
import { sceneBegin } from './narration'

// UX-73: the sound of the sample company's scenes (components/sandbox-scenes.tsx): the narrator's lines (made once with
// ElevenLabs) and the sound under them, static files in public/learn/scenes made by
// scripts/scene_audio/make_scene_audio.py. On or off is the guide voice's own choice (components/guide-voice.tsx,
// `mesiri_guide_voice`), so muting the narrator mutes the scenes too, and the other way round.
// A scene that starts with no click behind it (after the page loads again) may not play sound yet: the browser holds
// it. The sound then waits, the scene shows "Tap for sound", and the first tap or key plays it.
// UX-101: a scene with sound on screen has the floor (lib/narration.ts): the guide voice waits, or pauses, until it goes.

const VOICE_KEY = 'mesiri_guide_voice'

function readPrefs(): { on?: boolean; rate?: number } {
  try {
    return (JSON.parse(localStorage.getItem(VOICE_KEY) ?? 'null') as { on?: boolean; rate?: number } | null) ?? {}
  } catch {
    return {}
  }
}

export function sceneSoundOn(): boolean {
  return readPrefs().on !== false
}

/** Length of a sound in ms (0 for an unknown id). */
export function soundMs(id: string): number {
  return (SCENE_AUDIO as Record<string, number>)[id] ?? 0
}

export function hasSound(id: string): id is SceneAudioId {
  return id in SCENE_AUDIO
}

type Playing = { el: HTMLAudioElement; volume: number }
const playing = new Set<Playing>()
const waiting = new Set<Playing>()
const listeners = new Set<() => void>()
let held = false

function changed() {
  for (const l of listeners) l()
}

function setHeld(next: boolean) {
  if (held === next) return
  held = next
  changed()
}

/** The first tap or key after the browser held the sound plays what waits. */
function release() {
  if (!waiting.size) return
  const now = [...waiting]
  waiting.clear()
  setHeld(false)
  for (const p of now) start(p)
}
if (typeof window !== 'undefined') {
  window.addEventListener('pointerdown', release, true)
  window.addEventListener('keydown', release, true)
}

function start(p: Playing) {
  playing.add(p)
  p.el.play().catch((e: unknown) => {
    playing.delete(p)
    if ((e as { name?: string })?.name === 'NotAllowedError') {
      waiting.add(p)
      setHeld(true)
    }
  })
}

export type SoundHandle = { stop: (fadeMs?: number) => void }
const SILENT: SoundHandle = { stop: () => {} }

/** Play a scene sound once (or looped), unless sound is off or the file is unknown. */
export function playSound(id: string, opts: { volume?: number; loop?: boolean; delay?: number } = {}): SoundHandle {
  if (!hasSound(id) || !sceneSoundOn()) return SILENT
  const el = new Audio(`/learn/scenes/${id}.mp3`)
  const p: Playing = { el, volume: opts.volume ?? 1 }
  el.volume = p.volume
  el.loop = !!opts.loop
  el.preload = 'auto'
  el.addEventListener('ended', () => playing.delete(p))
  let timer = 0
  if (opts.delay) timer = window.setTimeout(() => start(p), opts.delay)
  else start(p)
  return {
    stop: (fadeMs = 350) => {
      window.clearTimeout(timer)
      waiting.delete(p)
      if (!waiting.size) setHeld(false)
      if (!playing.has(p)) return
      playing.delete(p)
      fade(el, fadeMs)
    },
  }
}

function fade(el: HTMLAudioElement, ms: number) {
  if (ms <= 0 || el.paused) {
    el.pause()
    return
  }
  const from = el.volume
  const t0 = performance.now()
  const step = () => {
    const k = Math.min(1, (performance.now() - t0) / ms)
    el.volume = from * (1 - k)
    if (k < 1) requestAnimationFrame(step)
    else el.pause()
  }
  requestAnimationFrame(step)
}

/** Sound on or off: saved as the guide voice's choice; off stops what plays now. */
export function setSceneSoundOn(on: boolean) {
  try {
    localStorage.setItem(VOICE_KEY, JSON.stringify({ ...readPrefs(), on }))
  } catch {
    // Blocked storage: the choice lasts for this page only.
  }
  if (!on) {
    for (const p of playing) fade(p.el, 200)
    playing.clear()
    waiting.clear()
    setHeld(false)
  }
  changed()
}

/** Play these sounds while the component is on screen; they fade out when it goes. */
export function useSounds(cues: { id: string; volume?: number; loop?: boolean; delay?: number }[] | null, key: string) {
  React.useEffect(() => {
    if (!cues) return
    const handles = cues.map((c) => playSound(c.id, c))
    // Holds the guide voice while these lines are being said (a briefing that stays open frees it once its line ends).
    const lasts = Math.max(0, ...cues.filter((c) => !c.loop && hasSound(c.id)).map((c) => (c.delay ?? 0) + soundMs(c.id)))
    const end = sceneSoundOn() && lasts > 0 ? sceneBegin() : () => {}
    const timer = window.setTimeout(end, lasts + 300)
    return () => {
      window.clearTimeout(timer)
      handles.forEach((h) => h.stop())
      end()
    }
    // `key` names the cues; the array itself is new on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
}

/** On or off, and whether the browser is holding the sound until a tap. */
export function useSceneSound(): { on: boolean; held: boolean; toggle: () => void } {
  const [, bump] = React.useReducer((n: number) => n + 1, 0)
  React.useEffect(() => {
    listeners.add(bump)
    return () => {
      listeners.delete(bump)
    }
  }, [])
  const on = sceneSoundOn()
  return { on, held: on && held, toggle: () => setSceneSoundOn(!on) }
}
