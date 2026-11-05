import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'

// Mesiri as a character on the company Live (WEB-53): a hard hat in the
// brand colour over a line-drawn face (chosen 5 Nov, option "C · With a
// face"). Flat: black line, one orange accent, no glow. Its mood follows
// what Mesiri is doing with the message in front of it: it blinks while
// waiting, perks up when a message comes, listens to a voice note, looks
// at a photo through a glass, thinks, hops when something is saved, frowns
// with a red "!" when it catches a mistake, and sends a paper plane when a
// report goes out. SVG and CSS only (the `spark-*` keyframes in index.css).
// The colours are fixed, not themed: it reads as a sticker in dark mode too.

export type SparkMood = 'idle' | 'alert' | 'listen' | 'think' | 'look' | 'happy' | 'worry' | 'send'

const INK = '#1a1d21'
const HAT = '#c2410c'
const RED = '#b42318'

const MOUTHS: Record<SparkMood, string> = {
  idle: 'M45 83 Q50 86 55 83',
  alert: 'M47 83 Q50 87 53 83 Q50 80 47 83',
  listen: 'M45 83 Q50 86 55 83',
  think: 'M46 84 L54 83',
  look: 'M46 84 Q50 85 54 84',
  happy: 'M42 81 Q50 90 58 81',
  worry: 'M44 86 Q50 81 56 86',
  send: 'M42 81 Q50 90 58 81',
}

/** Where the eyes look, per mood (dx, dy). */
const GAZE: Record<SparkMood, [number, number]> = {
  idle: [0, 0],
  alert: [0, 0],
  listen: [3, 0],
  think: [4, -2],
  look: [4, 2],
  happy: [0, 0],
  worry: [0, 1],
  send: [2, -1],
}

const MOOD_WORDS: Record<SparkMood, string> = {
  idle: 'waiting for the next message',
  alert: 'a message arrived',
  listen: 'listening to a voice note',
  think: 'thinking',
  look: 'looking at a photo',
  happy: 'saved',
  worry: 'noticed something',
  send: 'sending the report',
}

export function Spark({
  mood = 'idle',
  beat = 0,
  size = 120,
  className,
  label = 'Mesiri',
}: {
  mood?: SparkMood
  /** Bump it to make it perk up once (a message arrived). */
  beat?: number
  size?: number
  className?: string
  label?: string
}) {
  const still = prefersReducedMotion()
  const [dx, dy] = GAZE[mood]
  const happy = mood === 'happy' || mood === 'send'
  const anim = (name: string | undefined) => (still ? undefined : name)
  const motion =
    mood === 'happy'
      ? 'spark-hop 700ms cubic-bezier(.3,1.6,.5,1) 2'
      : mood === 'worry'
        ? 'live-shake 600ms ease-out'
        : 'spark-perk 450ms ease-out'

  return (
    <svg viewBox="0 0 100 100" width={size} height={size} role="img" aria-label={`${label}: ${MOOD_WORDS[mood]}`} className={cn('overflow-visible', className)}>
      {/* A shadow on the ground: shrinks as it hops. */}
      <ellipse cx="50" cy="98" rx="20" ry="2.5" fill={INK} opacity="0.12" />

      <g key={`${mood}-${beat}`} style={{ transformOrigin: '50px 96px', animation: anim(motion) }}>
        {/* The face. */}
        <path d="M24 60 V70 Q24 92 50 92 Q76 92 76 70 V60 Z" fill="#fff" />
        <path d="M24 60 V70 Q24 92 50 92 Q76 92 76 70 V60" fill="none" stroke={INK} strokeWidth="3.5" strokeLinecap="round" />

        {/* Eyes: they blink while waiting and look where Mesiri looks. */}
        <g style={{ transform: `translate(${dx}px, ${dy}px)`, transition: 'transform 400ms ease' }}>
          <g style={{ transformOrigin: '50px 72px', animation: anim(mood === 'idle' || mood === 'listen' ? 'spark-blink 4.6s ease-in-out infinite' : undefined) }}>
            {happy ? (
              <path d="M36 72 Q41 66 46 72M54 72 Q59 66 64 72" stroke={INK} strokeWidth="3.5" fill="none" strokeLinecap="round" />
            ) : (
              <>
                <circle cx="41" cy="72" r={mood === 'alert' ? 4.8 : 4} fill={INK} />
                <circle cx="59" cy="72" r={mood === 'alert' ? 4.8 : 4} fill={INK} />
              </>
            )}
          </g>
        </g>
        {mood === 'worry' && <path d="M34 65 L44 68M66 65 L56 68" stroke={INK} strokeWidth="3" strokeLinecap="round" />}
        <path d={MOUTHS[mood]} stroke={INK} strokeWidth="3" fill={mood === 'alert' ? INK : 'none'} strokeLinecap="round" strokeLinejoin="round" />

        {/* The hard hat. */}
        <path d="M22 54 Q22 22 50 22 Q78 22 78 54Z" fill={HAT} />
        <path d="M50 22V52" stroke={INK} strokeWidth="3" />
        <rect x="14" y="52" width="72" height="8" rx="2" fill={INK} />
      </g>

      <Prop mood={mood} still={still} />
    </svg>
  )
}

/** What it holds or shows for its mood. */
function Prop({ mood, still }: { mood: SparkMood; still: boolean }) {
  const anim = (name: string) => (still ? undefined : name)
  switch (mood) {
    case 'listen':
      return (
        <g stroke={INK} strokeWidth="2.5" fill="none" strokeLinecap="round">
          {[0, 1, 2].map((i) => (
            <path
              key={i}
              d={`M${84 + i * 6} ${64 - i * 4} Q${89 + i * 7} 74 ${84 + i * 6} ${84 + i * 4}`}
              style={{ animation: anim(`spark-wave 1.2s ease-in-out ${i * 0.18}s infinite`) }}
            />
          ))}
        </g>
      )
    case 'think':
      return (
        <g fill={INK}>
          {[0, 1, 2].map((i) => (
            <circle key={i} cx={84 + i * 7} cy={26 - i * 8} r={2 + i * 0.8} style={{ animation: anim(`spark-wave 1.1s ease-in-out ${i * 0.2}s infinite`) }} />
          ))}
        </g>
      )
    case 'look':
      return (
        <g style={{ transformOrigin: '88px 86px', animation: anim('spark-peer 1.6s ease-in-out infinite') }}>
          <circle cx="86" cy="82" r="9" fill="#fff" stroke={INK} strokeWidth="3" />
          <path d="M92.5 88.5 L100 96" stroke={INK} strokeWidth="4" strokeLinecap="round" />
        </g>
      )
    case 'worry':
      return (
        <text x="90" y="40" fontSize="24" fontWeight="800" fill={RED} textAnchor="middle" style={{ transformOrigin: '90px 32px', animation: anim('spark-perk 400ms ease-out') }}>
          !
        </text>
      )
    case 'happy':
      return (
        <path
          d="M84 34 L88 38 L96 28"
          stroke="#0f5132"
          strokeWidth="3.5"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ animation: anim('spark-perk 500ms ease-out') }}
        />
      )
    case 'send':
      return (
        <g style={{ animation: anim('spark-plane 1.4s ease-in both') }}>
          <path d="M80 44 L100 34 L92 54 L88 47 Z" fill="#fff" stroke={INK} strokeWidth="2" strokeLinejoin="round" />
          <path d="M88 47 L100 34" stroke={INK} strokeWidth="1.5" />
        </g>
      )
    default:
      return null
  }
}
