import * as React from 'react'
import { Check, UserPlus, X } from 'lucide-react'
import type { JoiningPerson } from '@/lib/api'
import { prefersReducedMotion } from '@/lib/timeline'
import { cn } from '@/lib/utils'
import { QrCode } from '@/components/onboarding/qr-code'
import { WhatsAppIcon } from '@/components/brand/whatsapp-icon'
import { Label } from '@/components/onboarding/conversation'

// WEB-71 (Ilan, 6 Nov): in a live meeting people scan the QR code on Live and join the company. The QR code
// sends the company's join code ("JOIN ACME-4821"); the admin gets "X is trying to join, let them in?" on
// WhatsApp, taps Approve, then the role, then the project, and they are in. Live shows each person moving
// through those steps as they happen (GET /company/joining), and people added by number on WhatsApp too.

const STEPS = ['Asked', 'Approved', 'Role', 'Project', 'In'] as const
const ADDED_STEPS = ['Number sent', 'Role', 'Project', 'In'] as const

/** How many steps are done, for the track. */
function done(p: JoiningPerson): number {
  if (p.source === 'added') return ADDED_STEPS.length
  return { asked: 1, approved: 2, role: 3, joined: 5, rejected: 1 }[p.step]
}

const ROLE: Record<string, string> = {
  SITE_ENGINEER: 'Site Engineer',
  PROJECT_MANAGER: 'Project Manager',
  ADMIN: 'Admin',
  FINANCE: 'Finance',
}
const roleName = (role: string | null) => (role ? (ROLE[role.toUpperCase()] ?? role) : null)

/** What the admin is doing now, in a few words. */
function waitingOn(p: JoiningPerson): string {
  if (p.step === 'asked') return 'Waiting for the admin to approve on WhatsApp'
  if (p.step === 'approved') return 'Approved: the admin is picking their role'
  if (p.step === 'role') return `${roleName(p.role)}: the admin is picking the project`
  if (p.step === 'rejected') return 'Not approved'
  return [roleName(p.role), p.project].filter(Boolean).join(' · ')
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('') || '?'

/** What Mesiri says when someone moves on a step (presenter mode talks). */
export function joiningLine(p: JoiningPerson, before: JoiningPerson['step'] | undefined): string | null {
  const first = p.name.split(/\s+/)[0] || 'Someone'
  if (before === undefined && p.step === 'asked') return `${first} wants to join. The admin is asked on WhatsApp.`
  if (p.step === 'approved' && before !== 'approved') return `${first} is approved.`
  if (p.step === 'joined' && before !== 'joined') return `Welcome to the team, ${first}!`
  return null
}

function Burst() {
  if (prefersReducedMotion()) return null
  return (
    <span className="pointer-events-none absolute inset-0 overflow-visible" aria-hidden="true">
      {Array.from({ length: 14 }, (_, i) => {
        const angle = (i / 14) * Math.PI * 2
        const dist = 46 + (i % 3) * 14
        return (
          <span
            key={i}
            className={cn('absolute left-6 top-1/2 size-2 rounded-[2px]', i % 3 === 0 ? 'bg-primary' : i % 3 === 1 ? 'bg-[#25d366]' : 'bg-foreground')}
            style={
              {
                '--jx': `${Math.cos(angle) * dist}px`,
                '--jy': `${Math.sin(angle) * dist}px`,
                animation: `join-burst 900ms cubic-bezier(.2,.8,.3,1) ${i * 15}ms both`,
              } as React.CSSProperties
            }
          />
        )
      })}
    </span>
  )
}

function Person({ p, fresh, big }: { p: JoiningPerson; fresh: 'new' | 'step' | 'in' | null; big: boolean }) {
  const steps = p.source === 'added' ? ADDED_STEPS : STEPS
  const n = done(p)
  const still = prefersReducedMotion()
  const rejected = p.step === 'rejected'
  const joined = p.step === 'joined'
  return (
    <li
      className={cn('relative border border-foreground/15 bg-background p-3', rejected && 'opacity-50', joined && 'border-foreground/40')}
      style={!still && fresh === 'new' ? { animation: 'meet-deal 600ms cubic-bezier(.2,.9,.3,1) both' } : undefined}
    >
      {fresh === 'in' && <Burst />}
      <div className="flex items-center gap-3">
        <span
          className={cn(
            'grid size-11 shrink-0 place-items-center rounded-full font-semibold',
            joined ? 'bg-[#25d366] text-[#0b3d1f]' : rejected ? 'bg-muted text-muted-foreground' : 'bg-foreground text-background',
            big && 'size-14 text-lg',
          )}
          style={!still && fresh === 'in' ? { animation: 'meet-stamp 700ms cubic-bezier(.2,.9,.3,1) both' } : undefined}
        >
          {joined ? <Check className="size-5" /> : rejected ? <X className="size-5" /> : initials(p.name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className={cn('m-0 truncate font-semibold', big ? 'text-xl' : 'text-base')}>
            {p.name || 'New person'} <span className="font-mono text-xs font-normal text-muted-foreground">…{p.phone_tail}</span>
          </p>
          <p
            key={p.step}
            className={cn('m-0 truncate text-muted-foreground', big ? 'text-base' : 'text-sm')}
            style={!still && fresh ? { animation: 'meet-rise 450ms ease-out both' } : undefined}
          >
            {joined ? <span className="font-medium text-foreground">In · {waitingOn(p)}</span> : waitingOn(p)}
          </p>
        </div>
        <span className="hidden shrink-0 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground sm:inline">
          {p.source === 'added' ? 'Added by number' : 'Scanned'}
        </span>
      </div>
      {/* The track: each step fills as the admin taps on WhatsApp. */}
      <ol className="m-0 mt-3 flex list-none gap-1 p-0" aria-label={`${p.name}: ${steps.slice(0, n).join(', ')}`}>
        {steps.map((label, i) => {
          const on = i < n && !(rejected && i > 0)
          const now = !rejected && !joined && i === n
          return (
            <li key={label} className="min-w-0 flex-1">
              <span
                className={cn('block h-1.5 origin-left bg-foreground/15', on && (joined ? 'bg-[#25d366]' : 'bg-foreground'), now && 'bg-primary/40')}
                style={
                  !still && on && fresh && i === n - 1
                    ? { animation: 'meet-strike 500ms cubic-bezier(.2,.9,.3,1) both' }
                    : !still && now
                      ? { animation: 'meet-dots 1400ms ease-in-out infinite' }
                      : undefined
                }
              />
              <span className={cn('mt-1 block truncate text-[11px]', on ? 'text-foreground' : 'text-muted-foreground')}>{label}</span>
            </li>
          )
        })}
      </ol>
    </li>
  )
}

/**
 * The QR code to join (presenter mode) and everyone joining today, each moving through the steps.
 * `fresh` marks who just changed, for their animation.
 */
export function Joining({
  people,
  fresh,
  qrLink,
  number,
  code,
  company,
  presenting,
}: {
  people: JoiningPerson[]
  fresh: Map<string, 'new' | 'step' | 'in'>
  qrLink: string | null
  number: string | null
  code: string | null
  company: string
  presenting: boolean
}) {
  const shown = [...people].reverse().slice(0, presenting ? 4 : 6)
  const inCount = people.filter((p) => p.step === 'joined').length
  if (!presenting && !people.length) return null
  return (
    <section aria-label="Joining the team" className="mt-2 border-t border-foreground/15 pt-6 text-left">
      {presenting && qrLink && (
        <div className="flex items-center gap-5">
          <QrCode value={qrLink} label={`QR code to join ${company} on Mesiri at ${number}`} className="size-36 shrink-0" />
          <div className="min-w-0">
            <p className="m-0 flex items-center gap-2 text-xl font-semibold">
              <WhatsAppIcon className="size-5" /> {code ? `Scan to join ${company}` : 'Send Mesiri a message'}
            </p>
            <p className="m-0 mt-1 text-base text-muted-foreground">
              {code
                ? 'Scan, send the message, and watch yourself join here. The admin lets you in on WhatsApp.'
                : `Scan, send anything about site, and watch it land here. ${number ?? ''}`}
            </p>
            {code && (
            <ol className="m-0 mt-2 flex flex-wrap gap-x-3 gap-y-1 p-0 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
              {['1 Scan & send', '2 Admin approves', '3 Role', '4 Project', '✓ In'].map((s) => (
                <li key={s} className="list-none">
                  {s}
                </li>
              ))}
            </ol>
            )}
            {code && <p className="m-0 mt-1 text-sm text-muted-foreground">Or send JOIN {code} to {number}</p>}
          </div>
        </div>
      )}
      {people.length > 0 && (
        <>
          <div className={cn('flex items-baseline justify-between gap-3', presenting && qrLink && 'mt-5')}>
            <Label className="flex items-center gap-2">
              <UserPlus className="size-3.5" /> Joining today
            </Label>
            <span className="font-mono text-xs text-muted-foreground">
              {inCount} in · {people.length - inCount - people.filter((p) => p.step === 'rejected').length} on the way
            </span>
          </div>
          <ul className="m-0 mt-3 grid list-none gap-2 p-0">
            {shown.map((p) => (
              <Person key={p.key} p={p} fresh={fresh.get(p.key) ?? null} big={presenting} />
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
