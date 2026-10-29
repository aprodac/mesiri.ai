import { useQuery } from '@tanstack/react-query'
import { fetchSetupProgress, type SetupProgress } from './api'
import { useAuth } from './AuthContext'

// The getting-started checklist (SS-07, SS-19), read once and shared by the
// card on Today and the sidebar's "Finish setup" link.

/** Company admins only: /company/setup-progress refuses anyone else. */
export function useSetupProgress() {
  const { me } = useAuth()
  const orgId = me?.org_id || me?.organization_id || ''
  const isCompanyAdmin = (me?.role ?? '').toUpperCase() === 'ADMIN' && !me?.is_platform_admin && !!orgId
  const query = useQuery({
    queryKey: ['setup-progress'],
    queryFn: fetchSetupProgress,
    enabled: isCompanyAdmin,
    refetchInterval: 60_000,
  })
  return { ...query, isCompanyAdmin }
}

/** Each step done or not, in the card's order. */
export function setupSteps(p: SetupProgress): boolean[] {
  return [
    p.has_site,
    p.has_team,
    p.first_update_at !== null,
    p.report_time_set,
    p.has_logo,
    p.first_dpr_sent_at !== null,
  ]
}

export function setupCounts(p: SetupProgress): { done: number; total: number } {
  const steps = setupSteps(p)
  return { done: steps.filter(Boolean).length, total: steps.length }
}

/** Where the sidebar's "Finish setup" goes: Today, with the card shown. */
export const SETUP_URL = '/today?setup=1'
