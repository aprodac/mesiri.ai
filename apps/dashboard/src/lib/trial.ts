import { useSyncExternalStore } from 'react'
import { useAuth } from './AuthContext'

/**
 * Whether the company's free trial has ended, so the dashboard is read-only
 * (SS-15; the backend guard is SS-08's domains/shared/trial_guard.py).
 *
 * Known from /auth/me on page load, and also the moment any save is refused
 * with TRIAL_EXPIRED (api.ts calls `markTrialExpired`): the backend caches the
 * status for a minute, so a page loaded just before the trial ended still
 * switches to read-only at the first refused save.
 */

export const TRIAL_EXPIRED_CODE = 'TRIAL_EXPIRED'

let refusedMessage: string | null = null
const listeners = new Set<() => void>()

export function markTrialExpired(message: string): void {
  if (refusedMessage === message) return
  refusedMessage = message
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export interface TrialState {
  /** Trial over: saves are refused, show the banner, hide edit actions. */
  readOnly: boolean
  /** The company's owner, who may ask to continue. */
  isOwner: boolean
  continueRequested: boolean
  trialDaysLeft: number | null
}

export function useTrial(): TrialState {
  const { me } = useAuth()
  const refused = useSyncExternalStore(subscribe, () => refusedMessage)
  const company = me?.company ?? null
  return {
    readOnly: company?.status === 'expired' || refused !== null,
    isOwner: (me?.role ?? '').toUpperCase() === 'ADMIN' && !me?.is_platform_admin,
    continueRequested: company?.continue_requested ?? false,
    trialDaysLeft: company?.status === 'trial' ? company.trial_days_left : null,
  }
}

/** Shorthand for pages that only need to hide or disable edit actions. */
export function useReadOnly(): boolean {
  return useTrial().readOnly
}
