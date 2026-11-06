import * as React from 'react'
import { api } from './api'

// Mesiri's voice on Live (WEB-63): a short line spoken at a moment ("Saved: 50
// bags of cement", the Meet Mesiri narration), from Sarvam through the API
// (GET /dpr/live/voice; the voice follows the line's script: Malayalam letters
// speak Malayalam). One line at a time: a new line stops the one playing. A
// line's audio is kept for the page's life, so a repeat costs nothing. Sound
// is off until asked for (browsers only play sound after a click anyway);
// presenter mode turns it on, and Mute turns it off. If the voice is not set
// up or fails, Live stays silent and says so once.

const MAX_CHARS = 280

export interface Voice {
  on: boolean
  setOn: (on: boolean) => void
  /** Says `line` if the sound is on; nothing otherwise. */
  say: (line: string | null | undefined) => void
  /** Stops what is being said. */
  hush: () => void
  /** The voice could not be reached (not set up, or down). */
  unavailable: boolean
}

export function useVoice(): Voice {
  const [on, setOnState] = React.useState(false)
  const [unavailable, setUnavailable] = React.useState(false)
  const onRef = React.useRef(false)
  const audio = React.useRef<HTMLAudioElement | null>(null)
  const clips = React.useRef(new Map<string, string>())
  const turn = React.useRef(0)

  const hush = React.useCallback(() => {
    turn.current++
    audio.current?.pause()
  }, [])

  const setOn = React.useCallback(
    (next: boolean) => {
      onRef.current = next
      setOnState(next)
      if (!next) hush()
    },
    [hush],
  )

  const say = React.useCallback((line: string | null | undefined) => {
    // "Cement 50 bags in · Malabar Traders": the dot is a pause, never read out.
    const words = (line ?? '').replace(/\s*[·•|]\s*/g, ', ').replace(/\s+/g, ' ').trim().slice(0, MAX_CHARS)
    if (!onRef.current || !words) return
    const mine = ++turn.current
    audio.current?.pause()
    void (async () => {
      try {
        let url = clips.current.get(words)
        if (!url) {
          const res = await api.get<Blob>('/dpr/live/voice', { params: { text: words }, responseType: 'blob' })
          url = URL.createObjectURL(res.data)
          clips.current.set(words, url)
        }
        if (mine !== turn.current || !onRef.current) return // a newer line, or muted meanwhile
        audio.current ??= new Audio()
        audio.current.src = url
        await audio.current.play()
        setUnavailable(false)
      } catch {
        setUnavailable(true)
      }
    })()
  }, [])

  React.useEffect(
    () => () => {
      audio.current?.pause()
      for (const url of clips.current.values()) URL.revokeObjectURL(url)
    },
    [],
  )

  return { on, setOn, say, hush, unavailable }
}
