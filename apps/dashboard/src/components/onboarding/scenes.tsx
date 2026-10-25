import * as React from 'react'
import { cn } from '@/lib/utils'
import { Conversation } from './conversation'

// One frame, several scenes (SS-18): the onboarding conversation plays a
// scene at a time instead of growing down the page. Every scene sits in the
// same grid cell, so the frame keeps the height of the tallest and nothing
// jumps when it changes. The numbered bar above shows where you are and how
// far the current scene has run; each step is a button.

export interface SceneStep {
  key: string
  label: string
  /** Not reachable yet (the welcome screen before the first update). */
  disabled?: boolean
}

export function SceneSteps({
  steps,
  index,
  progress,
  onSelect,
}: {
  steps: SceneStep[]
  index: number
  /** How far the current scene has run, 0 → 1. */
  progress: number
  onSelect: (i: number) => void
}) {
  return (
    <div role="tablist" aria-label="Steps" className="grid gap-4 py-4" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
      {steps.map((step, i) => {
        const fill = i < index ? 1 : i === index ? progress : 0
        return (
          <button
            key={step.key}
            type="button"
            role="tab"
            aria-selected={i === index}
            disabled={step.disabled}
            onClick={() => onSelect(i)}
            className="group grid gap-2 text-left disabled:cursor-default focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-foreground"
          >
            <span className="relative block h-[2px] overflow-hidden bg-border" aria-hidden="true">
              <span className="absolute inset-y-0 left-0 bg-foreground" style={{ width: `${fill * 100}%` }} />
            </span>
            <span
              className={cn(
                'truncate font-mono text-[11px] uppercase tracking-[0.06em] tabular-nums',
                i === index ? 'text-foreground' : 'text-muted-foreground',
                !step.disabled && i !== index && 'group-hover:text-foreground',
                step.disabled && 'opacity-50',
              )}
            >
              {String(i + 1).padStart(2, '0')}
              <span className="hidden @md:inline"> · {step.label}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}

/** The scenes, stacked in one cell; only the current one shows. It gets the
 * running clock, the others rest at Infinity (hidden, fully drawn). With
 * `stacked` off only the current scene is rendered, for scenes of very
 * different heights (the welcome screen's live report). */
export function SceneStage({
  index,
  now,
  scenes,
  stacked = true,
}: {
  index: number
  now: number
  scenes: React.ReactNode[]
  stacked?: boolean
}) {
  if (!stacked) {
    return (
      <div key={index} role="tabpanel" className="min-w-0 animate-in fade-in slide-in-from-bottom-2 duration-500 motion-reduce:animate-none">
        <Conversation now={now}>{scenes[index]}</Conversation>
      </div>
    )
  }
  return (
    <div className="grid">
      {scenes.map((scene, i) => (
        <div
          key={i}
          role="tabpanel"
          aria-hidden={i !== index}
          inert={i !== index}
          className={cn(
            'col-start-1 row-start-1 min-w-0 transition-[opacity,transform] duration-500 ease-[cubic-bezier(.2,.7,.2,1)] motion-reduce:transition-none',
            i === index ? 'opacity-100' : i < index ? 'pointer-events-none -translate-y-3 opacity-0' : 'pointer-events-none translate-y-3 opacity-0',
          )}
        >
          <Conversation now={i === index ? now : Infinity}>{scene}</Conversation>
        </div>
      ))}
    </div>
  )
}
