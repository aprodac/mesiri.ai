import { useQuery } from '@tanstack/react-query'
import { fetchSetupProgress, type SetupProgress } from './api'
import { useAuth } from './AuthContext'
import { useStartMode } from './start-mode'

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

/** SS-30: the extra steps a person's start mode adds (guided-onboarding-plan.md 6.2). */
export interface GuideSteps {
  /** Bring your vendors and materials list; bring your BOQ. */
  dataSteps: boolean
  /** "Where things are", for people coming from other software. */
  whereThingsAre: boolean
  /** That step was read. */
  whereSeen: boolean
}

/** The page key "Where things are" is remembered under in the person's guide_seen (SS-27). */
export const WHERE_THINGS_ARE = '/where-things-are'

/** The start mode's extra steps, for this person. */
export function useGuideSteps(): GuideSteps {
  const guide = useStartMode()
  return {
    dataSteps: guide.rules.dataSteps,
    whereThingsAre: guide.rules.whereThingsAre,
    whereSeen: guide.seen[WHERE_THINGS_ARE] !== undefined,
  }
}

/** Each step done or not, in the card's order: the six everyone gets, then the start mode's (SS-30). The one list
 *  the card, the sidebar's "Finish setup" and Settings all count from. */
export function setupSteps(p: SetupProgress, guide?: GuideSteps): boolean[] {
  const steps = [
    p.has_site,
    p.has_team,
    p.first_update_at !== null,
    p.report_time_set,
    p.has_logo,
    p.first_dpr_sent_at !== null,
  ]
  if (guide?.dataSteps) steps.push(p.has_vendors, p.has_boq)
  if (guide?.whereThingsAre) steps.push(guide.whereSeen)
  return steps
}

export function setupCounts(p: SetupProgress, guide?: GuideSteps): { done: number; total: number } {
  const steps = setupSteps(p, guide)
  return { done: steps.filter(Boolean).length, total: steps.length }
}

/** Where the sidebar's "Finish setup" goes: Today, with the card shown. */
export const SETUP_URL = '/today?setup=1'
