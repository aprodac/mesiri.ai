import * as React from 'react'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'

// The Spark (WEB-53): Mesiri as a character. A small glowing orb in the
// brand colour with two eyes and a hard hat, the one on site who hears
// everything and writes it down. Its mood follows what Mesiri is doing with
// the message in front of it, so the company Live always shows something
// alive: it breathes and blinks while waiting, perks up when a message
// comes, cups an ear for a voice note, thinks, looks through a glass at a
// photo, hops when something is saved, holds up a hand when it catches a
// mistake, and throws a paper plane when a report goes out. SVG and CSS
// only (the keyframes are the `spark-*` ones in index.css).

export type SparkMood = 'idle' | 'alert' | 'listen' | 'think' | 'look' | 'happy' | 'worry' | 'send'

const MOUTHS: Record<SparkMood, string> = {
  idle: 'M52 83 Q60 88 68 83',
  alert: 'M56 84 Q60 89 64 84 Q60 80 56 84',
  listen: 'M53 84 Q60 87 67 84',
  think: 'M54 85 L66 83',
  look: 'M55 84 Q60 86 65 84',
  happy: 'M48 80 Q60 94 72 80',
  worry: 'M51 88 Q60 81 69 88',
  send: 'M49 81 Q60 92 71 81',
}

/** Where the eyes look, per mood (dx, dy). */
const GAZE: Record<SparkMood, [number, number]> = {
  idle: [0, 0],
  alert: [0, -1],
  listen: [3, 0],
  think: [3, -4],
  look: [4, 3],
  happy: [0, 0],
  worry: [0, 1],
  send: [2, -2],
}

export function Spark({
  mood = 'idle',
  beat = 0,
  size = 120,
  className,
  label = 'Mesiri',
}: {
  mood?: SparkMood
  /** Bump it to make the Spark's heart beat once (a message arrived). */
  beat?: number
  size?: number
  className?: string
  label?: string
}) {
  const still = prefersReducedMotion()
  const id = React.useId().replace(/:/g, '')
  const [dx, dy] = GAZE[mood]
  const happy = mood === 'happy' || mood === 'send'
  const anim = (name: string | undefined) => (still ? undefined : name)

  return (
    <svg
      viewBox="0 0 120 120"
      width={size}
      height={size}
      role="img"
      aria-label={`${label}: ${MOOD_WORDS[mood]}`}
      className={cn('overflow-visible', className)}
    >
      <defs>
        <radialGradient id={`body-${id}`} cx="40%" cy="35%" r="70%">
          <stop offset="0%" stopColor="#ffe3c9" />
          <stop offset="45%" stopColor="#fb923c" />
          <stop offset="100%" stopColor="var(--primary)" />
        </radialGradient>
        <radialGradient id={`halo-${id}`}>
          <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* The glow: breathes all the time, and flares once on each beat. */}
      <circle
        key={`halo-${beat}`}
        cx="60"
        cy="66"
        r="56"
        fill={`url(#halo-${id})`}
        style={{
          transformOrigin: '60px 66px',
          animation: anim(beat ? 'spark-beat 900ms ease-out, spark-breathe 3.2s ease-in-out 900ms infinite' : 'spark-breathe 3.2s ease-in-out infinite'),
        }}
      />

      {/* Everything that moves together: the body, its hat and face. */}
      <g
        key={`body-${mood}`}
        style={{
          transformOrigin: '60px 100px',
          animation: anim(
            mood === 'happy'
              ? 'spark-hop 700ms cubic-bezier(.3,1.6,.5,1) 2'
              : mood === 'alert'
                ? 'spark-perk 500ms ease-out'
                : mood === 'worry'
                  ? 'live-shake 600ms ease-out'
                  : 'spark-float 4s ease-in-out infinite',
          ),
        }}
      >
        <circle cx="60" cy="68" r="32" fill={`url(#body-${id})`} />
        {/* A small shine, so it reads as a glowing ball. */}
        <ellipse cx="47" cy="55" rx="7" ry="4" fill="#fff" opacity="0.55" transform="rotate(-25 47 55)" />

        {/* The hard hat. */}
        <g>
          <path d="M34 48 Q34 24 60 24 Q86 24 86 48 Z" fill="#f5b301" />
          <path d="M60 24 L60 46" stroke="#d99a00" strokeWidth="3" />
          <rect x="27" y="45" width="66" height="7" rx="3.5" fill="#e0a300" />
        </g>

        {/* Eyes: they blink while waiting and look where Mesiri looks. */}
        <g
          style={{
            transform: `translate(${dx}px, ${dy}px)`,
            transition: 'transform 400ms ease',
          }}
        >
          <g
            style={{
              transformOrigin: '60px 70px',
              animation: anim(mood === 'idle' || mood === 'listen' ? 'spark-blink 4.6s ease-in-out infinite' : undefined),
            }}
          >
            {happy ? (
              <>
                <path d="M44 70 Q49 64 54 70" stroke="#1a1d21" strokeWidth="3" fill="none" strokeLinecap="round" />
                <path d="M66 70 Q71 64 76 70" stroke="#1a1d21" strokeWidth="3" fill="none" strokeLinecap="round" />
              </>
            ) : (
              <>
                <ellipse cx="49" cy="70" rx="4.2" ry={mood === 'alert' ? 6.5 : 5.5} fill="#1a1d21" />
                <ellipse cx="71" cy="70" rx="4.2" ry={mood === 'alert' ? 6.5 : 5.5} fill="#1a1d21" />
                <circle cx="50.5" cy="68" r="1.4" fill="#fff" />
                <circle cx="72.5" cy="68" r="1.4" fill="#fff" />
              </>
            )}
            {mood === 'worry' && (
              <>
                <path d="M42 60 L54 63" stroke="#1a1d21" strokeWidth="2.5" strokeLinecap="round" />
                <path d="M78 60 L66 63" stroke="#1a1d21" strokeWidth="2.5" strokeLinecap="round" />
              </>
            )}
          </g>
        </g>

        <path d={MOUTHS[mood]} stroke="#1a1d21" strokeWidth="2.6" fill={mood === 'alert' ? '#1a1d21' : 'none'} strokeLinecap="round" style={{ transition: 'd 300ms ease' }} />
        {happy && (
          <>
            <circle cx="41" cy="80" r="4" fill="#f43f5e" opacity="0.35" />
            <circle cx="79" cy="80" r="4" fill="#f43f5e" opacity="0.35" />
          </>
        )}
      </g>

      <Prop mood={mood} still={still} />
    </svg>
  )
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

/** What the Spark holds or shows for its mood. */
function Prop({ mood, still }: { mood: SparkMood; still: boolean }) {
  const anim = (name: string) => (still ? undefined : name)
  switch (mood) {
    case 'listen':
      return (
        <g stroke="var(--primary)" strokeWidth="3" fill="none" strokeLinecap="round">
          {[0, 1, 2].map((i) => (
            <path
              key={i}
              d={`M${98 + i * 7} ${56 - i * 4} Q${104 + i * 8} 68 ${98 + i * 7} ${80 + i * 4}`}
              style={{ animation: anim(`spark-wave 1.2s ease-in-out ${i * 0.18}s infinite`) }}
            />
          ))}
        </g>
      )
    case 'think':
      return (
        <g fill="var(--primary)">
          {[0, 1, 2].map((i) => (
            <circle
              key={i}
              cx={92 + i * 9}
              cy={30 - i * 7}
              r={2.5 + i * 1.2}
              style={{ animation: anim(`spark-wave 1.1s ease-in-out ${i * 0.2}s infinite`) }}
            />
          ))}
        </g>
      )
    case 'look':
      return (
        <g style={{ transformOrigin: '96px 90px', animation: anim('spark-peer 1.6s ease-in-out infinite') }}>
          <circle cx="92" cy="86" r="11" fill="#e0f2fe" fillOpacity="0.6" stroke="#1a1d21" strokeWidth="3.5" />
          <path d="M100 94 L110 104" stroke="#1a1d21" strokeWidth="5" strokeLinecap="round" />
        </g>
      )
    case 'happy':
      return (
        <g fill="#f5b301">
          {[
            [18, 40],
            [102, 34],
            [108, 82],
            [14, 86],
          ].map(([x, y], i) => (
            <path
              key={i}
              d={`M${x} ${y - 6} L${x + 2} ${y - 2} L${x + 6} ${y} L${x + 2} ${y + 2} L${x} ${y + 6} L${x - 2} ${y + 2} L${x - 6} ${y} L${x - 2} ${y - 2} Z`}
              style={{ transformOrigin: `${x}px ${y}px`, animation: anim(`spark-twinkle 900ms ease-out ${i * 0.1}s both`) }}
            />
          ))}
        </g>
      )
    case 'worry':
      return (
        <g style={{ transformOrigin: '100px 60px', animation: anim('spark-perk 400ms ease-out') }}>
          <rect x="90" y="38" width="22" height="22" rx="4" fill="var(--destructive)" />
          <text x="101" y="55" textAnchor="middle" fontSize="16" fontWeight="700" fill="#fff">!</text>
          <rect x="99" y="60" width="4" height="16" fill="#1a1d21" />
        </g>
      )
    case 'send':
      return (
        <g style={{ animation: anim('spark-plane 1.4s ease-in both') }}>
          <path d="M88 52 L116 40 L104 66 L99 56 Z" fill="#fff" stroke="#1a1d21" strokeWidth="2" strokeLinejoin="round" />
          <path d="M99 56 L116 40" stroke="#1a1d21" strokeWidth="1.5" />
        </g>
      )
    default:
      return null
  }
}
