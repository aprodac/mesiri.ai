import * as React from 'react'
import { Pause, Play, Volume2, VolumeX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useVoice, voiceWords, type Voice } from '@/lib/voice'
import { typingIn } from '@/lib/keys'

// SS-61: the narrator of the walkthroughs and the page tours: one voice hook with the person's choice (on or muted,
// the speed), and one player for the Spark's bubble. lib/voice.ts fetches and plays; the server makes the audio.

// SS-61: the narrator's controls, remembered per browser (on or muted, and the speed).
const VOICE_KEY = 'mesiri_guide_voice'
const RATES = [1, 1.25, 1.5, 2] as const

function readVoicePrefs(): { on: boolean; rate: number } {
  try {
    const saved = JSON.parse(localStorage.getItem(VOICE_KEY) ?? 'null') as { on?: boolean; rate?: number } | null
    return { on: saved?.on !== false, rate: RATES.includes(saved?.rate as (typeof RATES)[number]) ? (saved?.rate as number) : 1 }
  } catch {
    return { on: true, rate: 1 }
  }
}

function saveVoicePrefs(prefs: { on: boolean; rate: number }): void {
  try {
    localStorage.setItem(VOICE_KEY, JSON.stringify(prefs))
  } catch {
    // Private window or blocked storage: the choice lasts for this page only.
  }
}

/** The guide voice, starting from the person's last choice (on by default, decided 16 Nov) and saving changes. */
export function useGuideVoice(): Voice {
  const [prefs] = React.useState(readVoicePrefs)
  const voice = useVoice({ voice: 'guide', on: prefs.on, rate: prefs.rate })
  const { setOn: turn, setRate: speed, on, rate } = voice
  const setOn = React.useCallback((next: boolean) => {
    turn(next)
    saveVoicePrefs({ on: next, rate })
  }, [turn, rate])
  const setRate = React.useCallback((next: number) => {
    speed(next)
    saveVoicePrefs({ on, rate: next })
  }, [speed, on])
  return React.useMemo(() => ({ ...voice, setOn, setRate }), [voice, setOn, setRate])
}

export function VoicePlayer({ voice, words }: { voice: Voice; words: string }) {
  const here = voice.said === voiceWords(words, 'guide')
  const play = () => {
    if (!voice.on) {
      voice.setOn(true)
      voice.say(words)
    } else if (here) voice.resume()
    else voice.say(words)
  }
  // Keyboard (asked 17 Nov): K or P play / pause, M mute, [ ] slower / faster. Never while typing.
  const latest = React.useRef({ play, voice })
  latest.current = { play, voice }
  React.useEffect(() => {
    const keys = (e: KeyboardEvent) => {
      if (typingIn(e) || e.metaKey || e.ctrlKey || e.altKey) return
      const { play: go, voice: v } = latest.current
      const k = e.key.toLowerCase()
      if (k === 'k' || k === 'p') {
        e.preventDefault()
        if (v.playing) v.pause()
        else go()
      } else if (k === 'm') {
        e.preventDefault()
        v.setOn(!v.on)
      } else if (e.key === '[' || e.key === ']') {
        e.preventDefault()
        const at = RATES.indexOf(v.rate as (typeof RATES)[number])
        v.setRate(RATES[Math.min(RATES.length - 1, Math.max(0, at + (e.key === ']' ? 1 : -1)))])
      }
    }
    window.addEventListener('keydown', keys)
    return () => window.removeEventListener('keydown', keys)
  }, [])
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Voice">
      {voice.playing ? (
        <Button type="button" size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs" onClick={voice.pause} aria-label="Pause the voice">
          <Pause className="size-3.5" aria-hidden /> Pause
        </Button>
      ) : (
        <Button type="button" size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs" onClick={play} aria-label={here ? 'Play the voice' : 'Read this step aloud'}>
          <Play className="size-3.5" aria-hidden /> {here ? 'Play' : 'Listen'}
        </Button>
      )}
      <div className="flex overflow-hidden rounded-md border" role="group" aria-label="Speed">
        {RATES.map((r) => (
          <button
            key={r}
            type="button"
            aria-pressed={voice.rate === r}
            onClick={() => voice.setRate(r)}
            className={`px-1.5 py-0.5 text-[11px] tabular-nums ${voice.rate === r ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground'}`}
          >
            {r}x
          </button>
        ))}
      </div>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="h-7 px-1.5"
        onClick={() => {
          if (voice.on) voice.setOn(false)
          else play() // turning it back on reads this step
        }}
        aria-pressed={!voice.on}
        aria-label={voice.on ? 'Mute the voice' : 'Turn the voice on'}
        title={voice.on ? 'Mute' : 'Voice on'}
      >
        {voice.on ? <Volume2 className="size-3.5" aria-hidden /> : <VolumeX className="size-3.5" aria-hidden />}
      </Button>
      {voice.unavailable && voice.on && <span className="text-[11px] text-muted-foreground">Voice not available right now</span>}
    </div>
  )
}
