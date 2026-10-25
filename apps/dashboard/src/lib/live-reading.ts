import type { ReviewItem } from './api'

// What the Live report shows of Mesiri reading a message (WEB-37): the
// fields the AI took from it, as it stored them (extractions.extracted =
// {action_type, fields}), and each item's chip and key value. Ids and
// bookkeeping are left out; what's left is what someone can read.

const HIDDEN = /(^|_)(id|ids|uuid)$|idempotency|correlation|organization|^project|^site|user|actor|_source$|^occurred|timezone|^raw|^confidence/

function humanize(key: string): string {
  return key.replace(/_/g, ' ').toLowerCase()
}

function show(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    const parts = value
      .map((v) =>
        v && typeof v === 'object'
          ? Object.entries(v as Record<string, unknown>)
              .filter(([k, x]) => !HIDDEN.test(k) && x !== null && x !== '' && typeof x !== 'object')
              .map(([, x]) => String(x))
              .join(' ')
          : show(v),
      )
      .filter(Boolean)
    return parts.length ? parts.join(' · ') : null
  }
  return null
}

/** "headcount: 5", "material: holobricks", … from one reading; at most `max`. */
export function readingLines(extracted: Record<string, unknown> | null | undefined, max = 6): string[] {
  if (!extracted) return []
  const fields = (extracted.fields && typeof extracted.fields === 'object' ? extracted.fields : extracted) as Record<
    string,
    unknown
  >
  const lines: string[] = []
  const action = typeof extracted.action_type === 'string' ? extracted.action_type : null
  if (action) lines.push(`→ ${humanize(action)}`)
  for (const [key, value] of Object.entries(fields)) {
    if (HIDDEN.test(key)) continue
    const text = show(value)
    if (!text) continue
    const line = `${humanize(key)}: ${text}`
    lines.push(line.length > 60 ? `${line.slice(0, 57)}…` : line)
    if (lines.length >= max) break
  }
  return lines
}

/** The number or tag a row is about: "10 nos", "120 sqm", a severity. */
export function keyValue(item: ReviewItem): string | null {
  const q = item.quantities?.[0]
  if (q && q.quantity) return [q.quantity, q.unit].filter(Boolean).join(' ')
  if (item.severity) return item.severity
  return null
}

export function rowLines(item: ReviewItem): { main: string; sub: string | null } {
  const main = item.title || item.detail || 'Update'
  const sub = item.title && item.detail && item.detail !== item.title ? item.detail : null
  return { main, sub }
}
