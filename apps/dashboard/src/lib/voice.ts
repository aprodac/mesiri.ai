import * as React from 'react'
import { api } from './api'
import { GUIDE_AUDIO } from './guide-audio.gen'

// Mesiri's voice on Live (WEB-63): a short line spoken at a moment ("Saved: 50
// bags of cement", the Meet Mesiri narration), from Sarvam through the API
// (GET /dpr/live/voice; the voice follows the line's script: Malayalam letters
// speak Malayalam). One line at a time: a new line stops the one playing. A
// line's audio is kept for the page's life, so a repeat costs nothing. Sound
// is off until asked for (browsers only play sound after a click anyway);
// presenter mode turns it on, and Mute turns it off. If the voice is not set
// up or fails, Live stays silent and says so once.
//
// The walkthroughs (SS-61) use the same hook with `voice: 'guide'`: the narrator's voice (UX-76: their steps recorded
// once with ElevenLabs, static files in public/learn/voice; any other line from the server's voice), longer lines (a step's title and text), MP3, a speed (1x to 2x, the pitch kept), pause and
// resume, and the next step's audio fetched ahead so it starts at once.

export type VoiceName = 'live' | 'guide'

const MAX_CHARS: Record<VoiceName, number> = { live: 280, guide: 680 }

export interface Voice {
  on: boolean
  setOn: (on: boolean) => void
  /** Says `line` if the sound is on; nothing otherwise. */
  say: (line: string | null | undefined) => void
  /** Stops what is being said. */
  hush: () => void
  /** The voice could not be reached (not set up, or down). */
  unavailable: boolean
  /** Something is being said now. */
  playing: boolean
  /** Pause what is being said; `resume` goes on from there. */
  pause: () => void
  resume: () => void
  /** How fast it speaks (1 = as recorded). */
  rate: number
  setRate: (rate: number) => void
  /** Fetch `line`'s audio now, to say it later without waiting. */
  prefetch: (line: string | null | undefined) => void
  /** The words of the line loaded to play (what `resume` goes on with), as sent. */
  said: string | null
}

/** The words as they are sent: a dot between items is a pause, never read out. */
export function voiceWords(line: string | null | undefined, voice: VoiceName = 'live'): string {
  return (line ?? '').replace(/\s*[·•|]\s*/g, ', ').replace(/\s+/g, ' ').trim().slice(0, MAX_CHARS[voice])
}

export function useVoice(options: { voice?: VoiceName; on?: boolean; rate?: number } = {}): Voice {
  const name = options.voice ?? 'live'
  const [on, setOnState] = React.useState(options.on ?? false)
  const [unavailable, setUnavailable] = React.useState(false)
  const [playing, setPlaying] = React.useState(false)
  const [rate, setRateState] = React.useState(options.rate ?? 1)
  const [said, setSaid] = React.useState<string | null>(null)
  const onRef = React.useRef(options.on ?? false)
  const rateRef = React.useRef(options.rate ?? 1)
  const audio = React.useRef<HTMLAudioElement | null>(null)
  const clips = React.useRef(new Map<string, Promise<string>>())
  const turn = React.useRef(0)

  const player = React.useCallback(() => {
    if (!audio.current) {
      const a = new Audio()
      a.addEventListener('play', () => setPlaying(true))
      a.addEventListener('pause', () => setPlaying(false))
      a.addEventListener('ended', () => setPlaying(false))
      audio.current = a
    }
    return audio.current
  }, [])

  const clip = React.useCallback(
    (words: string): Promise<string> => {
      let url = clips.current.get(words)
      if (!url) {
        const params = name === 'live' ? { text: words } : { text: words, voice: name }
        const server = () =>
          api.get<Blob>('/dpr/live/voice', { params, responseType: 'blob' }).then((res) => URL.createObjectURL(res.data))
        // UX-76: a walkthrough line recorded with ElevenLabs plays from its static file; any other line (a step
        // changed since it was recorded, a hint) is read by the server's voice.
        const recorded = name === 'guide' ? GUIDE_AUDIO[words] : undefined
        url = recorded
          ? fetch(`/learn/voice/${recorded}.mp3`)
              .then((res) => (res.ok ? res.blob() : Promise.reject(new Error(String(res.status)))))
              .then((blob) => URL.createObjectURL(blob))
              .catch(server)
          : server()
        url.catch(() => clips.current.delete(words)) // a failed fetch is tried again next time
        clips.current.set(words, url)
      }
      return url
    },
    [name],
  )

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

  const setRate = React.useCallback((next: number) => {
    rateRef.current = next
    setRateState(next)
    if (audio.current) audio.current.playbackRate = next
  }, [])

  const say = React.useCallback(
    (line: string | null | undefined) => {
      const words = voiceWords(line, name)
      if (!onRef.current || !words) return
      const mine = ++turn.current
      audio.current?.pause()
      void (async () => {
        try {
          const url = await clip(words)
          if (mine !== turn.current || !onRef.current) return // a newer line, or muted meanwhile
          const a = player()
          a.src = url
          setSaid(words)
          a.playbackRate = rateRef.current // a new source resets the speed
          await a.play()
          setUnavailable(false)
        } catch (err) {
          // The browser holds sound until the person clicks (a tour that opened by itself): not a failure; the
          // player's Play starts it.
          if ((err as { name?: string } | null)?.name !== 'NotAllowedError') setUnavailable(true)
        }
      })()
    },
    [clip, name, player],
  )

  const prefetch = React.useCallback(
    (line: string | null | undefined) => {
      const words = voiceWords(line, name)
      if (onRef.current && words) clip(words).catch(() => undefined)
    },
    [clip, name],
  )

  const pause = React.useCallback(() => audio.current?.pause(), [])
  const resume = React.useCallback(() => {
    const a = audio.current
    if (a?.src && onRef.current) void a.play().catch(() => setUnavailable(true))
  }, [])

  React.useEffect(
    () => () => {
      audio.current?.pause()
      for (const url of clips.current.values()) void url.then((u) => URL.revokeObjectURL(u)).catch(() => undefined)
    },
    [],
  )

  return { on, setOn, say, hush, unavailable, playing, pause, resume, rate, setRate, prefetch, said }
}
