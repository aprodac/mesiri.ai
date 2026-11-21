import type { SiteDayDetail, SiteDayReport } from './mesiri'
import type { Words } from './i18n'

// The site's day as the rows on Today: each says what was told, or that it is still to tell.
// Read from the site DPR page's own data (GET /dpr/site-days/{site}), drafts included, so what
// was said a minute ago on WhatsApp or in the app shows at once.

export type Section = 'labour' | 'work' | 'received' | 'used' | 'issues' | 'photos' | 'conditions'
export const SECTIONS: Section[] = ['labour', 'work', 'received', 'used', 'issues', 'photos', 'conditions']

export interface DayLine {
  section: Section
  title: string
  detail: string
  tone: 'done' | 'todo' | 'warn'
}

const num = (v: string | null | undefined) => Number(v ?? 0) || 0

function trim(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')
}

/** "LABOUR_SHORTAGE" (an issue's type, as stored) as words: "Labour shortage". Anything else as it is. */
export function words(text: string | null | undefined): string {
  if (!text) return ''
  if (!/^[A-Z][A-Z0-9_]*$/.test(text)) return text
  const plain = text.toLowerCase().replace(/_/g, ' ')
  return plain.charAt(0).toUpperCase() + plain.slice(1)
}

/** "3.500" as "3.5". */
export function amount(value: string | number | null | undefined): string {
  const n = Number(value ?? 0)
  return Number.isFinite(n) ? trim(n) : String(value)
}

export function reportOf(day: SiteDayDetail): SiteDayReport {
  return day.report_with_drafts ?? day.report
}

export function sectionTitle(section: Section, t: Words): string {
  return {
    labour: t.attendance,
    work: t.workDone,
    received: t.materialsIn,
    used: t.materialsUsed,
    issues: t.problems,
    photos: t.photos,
    conditions: t.weather,
  }[section]
}

const WEATHER: Record<string, string> = {
  sunny: 'Sunny',
  cloudy: 'Cloudy',
  rainy: 'Rain',
  windy: 'Windy',
  extreme_heat: 'Very hot',
}

export function dayLines(day: SiteDayDetail, t: Words): DayLine[] {
  const report = reportOf(day)
  const lines: DayLine[] = []
  const todo = (section: Section): DayLine => ({ section, title: sectionTitle(section, t), detail: t.notToldYet, tone: 'todo' })

  const labour = report.labour
  if (labour.headcount > 0) {
    const trades = labour.trades.map((x) => `${x.headcount} ${x.trade}`).join(', ')
    lines.push({ section: 'labour', title: t.attendance, detail: [t.people(labour.headcount), trades].filter(Boolean).join(' · '), tone: 'done' })
  } else lines.push(todo('labour'))

  const work = day.items.filter((i) => i.section === 'work')
  if (work.length) {
    const first = work[0]
    const q = first.quantities?.[0]
    const what = [first.title, q ? `${amount(q.quantity)} ${q.unit}` : null].filter(Boolean).join(' · ')
    lines.push({ section: 'work', title: t.workDone, detail: work.length > 1 ? `${what} +${work.length - 1}` : what, tone: 'done' })
  } else lines.push(todo('work'))

  for (const [section, field] of [
    ['received', 'received'],
    ['used', 'used'],
  ] as const) {
    const moved = report.materials.filter((m) => num(m[field]) > 0)
    if (moved.length) {
      const text = moved
        .slice(0, 2)
        .map((m) => `${trim(num(m[field]))} ${m.unit ?? ''} ${m.material_name ?? ''}`.replace(/\s+/g, ' ').trim())
        .join(', ')
      lines.push({ section, title: sectionTitle(section, t), detail: moved.length > 2 ? `${text} +${moved.length - 2}` : text, tone: 'done' })
    } else lines.push(todo(section))
  }

  const issues = day.items.filter((i) => i.section === 'issues')
  const open = day.day?.open_issues ?? 0
  if (issues.length || open) {
    const first = issues[0] ? words(issues[0].title) : null
    lines.push({
      section: 'issues',
      title: t.problems,
      detail: [open ? t.openProblems(open) : null, first].filter(Boolean).join(' · '),
      tone: open ? 'warn' : 'done',
    })
  } else lines.push({ section: 'issues', title: t.problems, detail: t.notToldYet, tone: 'todo' })

  const photos = day.day?.photos ?? report.evidence_count ?? 0
  lines.push(photos ? { section: 'photos', title: t.photos, detail: t.photosToday(photos), tone: 'done' } : todo('photos'))

  const c = report.conditions
  if (c.weather || c.site_working) {
    const working = c.site_working === 'half' ? 'Half day' : c.site_working === 'none' ? 'No work' : null
    lines.push({
      section: 'conditions',
      title: t.weather,
      detail: [c.weather ? WEATHER[c.weather] ?? c.weather : null, working, c.tomorrow_plan ? `Tomorrow: ${c.tomorrow_plan}` : null]
        .filter(Boolean)
        .join(' · '),
      tone: 'done',
    })
  } else lines.push(todo('conditions'))

  return lines
}
