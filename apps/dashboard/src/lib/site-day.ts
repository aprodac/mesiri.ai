import type { SiteDayItem } from '@/lib/api'

// Shared by the Today page (WEB-03) and the site DPR page (WEB-04): how a
// site's working day is labelled and what its missing sections are called.

export const CHIP = 'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap'

export const MISSING_LABELS: Record<string, string> = {
  work_done: 'work done',
  labour: 'labour count',
  photos: 'photos',
  materials: 'materials',
  weather: 'weather',
  tomorrow_plan: "tomorrow's plan",
}

/** Confirmed by the engineer, or sent: nothing on the day can change. */
export const FROZEN = ['approved', 'published']

export function localIsoDate(d: Date): string {
  const offset = d.getTimezoneOffset() * 60_000
  return new Date(d.getTime() - offset).toISOString().slice(0, 10)
}

// The API's own reason ("today's DPR ... has already been sent"), which
// reaches the page since BE-28 stopped turning such errors into 500s.
export function errorDetail(err: unknown): string | null {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail !== 'string' || !detail) return null
  return detail.charAt(0).toUpperCase() + detail.slice(1)
}

export function hasUpdates(site: SiteDayItem): boolean {
  // WEB-32: anything the site sent that day counts, not only work and labour:
  // a site that sent only materials, an issue or progress has reported.
  return (
    site.work_items > 0 ||
    site.workers > 0 ||
    (site.materials ?? 0) > 0 ||
    (site.issues_today ?? 0) > 0 ||
    (site.progress_updates ?? 0) > 0 ||
    (site.drafts ?? 0) > 0 ||
    site.site_working === 'none'
  )
}

export function siteStatus(site: SiteDayItem): { label: string; className: string } {
  switch (site.status) {
    case 'needs_details':
      return { label: 'Needs details', className: 'bg-draft-soft text-draft' }
    case 'ready':
      return { label: 'Ready', className: 'bg-info-soft text-info' }
    case 'in_review':
      return { label: 'With engineer', className: 'bg-info-soft text-info' }
    case 'approved':
      return { label: 'Confirmed', className: 'bg-success-soft text-success' }
    case 'published':
      return { label: 'Sent', className: 'bg-success-soft text-success' }
    case 'not_reported':
      return { label: 'Not reported', className: 'bg-muted text-muted-foreground' }
    default:
      return hasUpdates(site)
        ? { label: 'Collecting', className: 'bg-info-soft text-info' }
        : { label: 'No updates', className: 'bg-muted text-muted-foreground' }
  }
}

export function missingText(site: SiteDayItem): string | null {
  const missing = site.missing_sections
  if (!missing) return null
  const parts = [...missing.blocking, ...missing.optional].map((key) => MISSING_LABELS[key] ?? key)
  return parts.length ? `Missing: ${parts.join(', ')}` : null
}

/** The page for one site's day: review drafts, see sources, approve. */
export function siteDayPath(siteId: string, date: string): string {
  return `/reports/${date}/sites/${siteId}`
}

/** The page for one project's day: every site and the project DPR (WEB-05). */
export function projectDayPath(projectId: string, date: string): string {
  return `/reports/${date}/projects/${projectId}`
}

export function longDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString([], {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

export function dateTime(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`
}

/** "40.000" -> "40", "12.50" -> "12.5": quantities arrive as stored decimals. */
export function qty(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 3 }) : value
}

/** Issue severity as a coloured chip: red, orange, blue, grey. */
export function severityChip(severity: string | null | undefined): { label: string; className: string } | null {
  if (!severity) return null
  const key = severity.toUpperCase()
  const label = key.charAt(0) + key.slice(1).toLowerCase()
  switch (key) {
    case 'CRITICAL':
      return { label, className: 'bg-destructive/10 text-destructive' }
    case 'HIGH':
      return { label, className: 'bg-draft-soft text-draft' }
    case 'MEDIUM':
      return { label, className: 'bg-info-soft text-info' }
    default:
      return { label, className: 'bg-muted text-muted-foreground' }
  }
}
