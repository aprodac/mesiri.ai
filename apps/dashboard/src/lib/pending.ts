import { type OrderLine, type PurchaseOrder } from './orders'

// PRC-45: what is still to come on open orders, line by line, and the message that chases a supplier for it.
// Read from the same order list as Procurement › Purchase orders (what came is read from deliveries).

export type Bucket = 'late' | 'today' | 'week' | 'later' | 'none'
export type GroupBy = 'date' | 'supplier'

export interface PendingLine {
  key: string
  order: PurchaseOrder
  line: OrderLine
  pending: number
  /** Days until due (negative: late); null without a date. */
  days: number | null
  bucket: Bucket
  /** Still to come in rupees, when the rate is known and the viewer sees money. */
  value: number | null
}

export function startOfToday(): Date {
  const t = new Date()
  return new Date(t.getFullYear(), t.getMonth(), t.getDate())
}

export function pendingLines(orders: PurchaseOrder[], today = startOfToday()): PendingLine[] {
  const out: PendingLine[] = []
  for (const o of orders) {
    if (o.status !== 'open' && o.status !== 'part') continue
    const days = o.expected_date ? Math.round((new Date(`${o.expected_date}T00:00:00`).getTime() - today.getTime()) / 86_400_000) : null
    const bucket: Bucket = days === null ? 'none' : days < 0 ? 'late' : days === 0 ? 'today' : days <= 7 ? 'week' : 'later'
    for (const line of o.lines) {
      const pending = Number(line.pending)
      if (!(pending > 0)) continue
      out.push({ key: `${o.id}:${line.id}`, order: o, line, pending, days, bucket, value: line.rate === null ? null : pending * Number(line.rate) })
    }
  }
  return out.sort((a, b) => (a.days ?? 9999) - (b.days ?? 9999) || a.order.vendor_name.localeCompare(b.order.vendor_name) || a.order.number - b.order.number)
}

export const n = (v: number) => v.toLocaleString('en-IN', { maximumFractionDigits: 3 })

export function lateWords(p: PendingLine): string {
  if (p.days === null) return 'No date'
  if (p.days < 0) return `${-p.days} day${p.days === -1 ? '' : 's'} late`
  if (p.days === 0) return 'Due today'
  if (p.days === 1) return 'Tomorrow'
  return new Date(`${p.order.expected_date}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

/** One WhatsApp message to a supplier for everything still to come from them (the person sends it). */
export function chaseMessage(lines: PendingLine[], company?: string | null): string {
  const byOrder = new Map<string, PendingLine[]>()
  for (const p of lines) byOrder.set(p.order.id, [...(byOrder.get(p.order.id) ?? []), p])
  const parts = [...byOrder.values()].map((ps) => {
    const o = ps[0].order
    const when = ps[0].days !== null && ps[0].days < 0 ? ` (was due ${new Date(`${o.expected_date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })})` : ''
    return [`*${o.ref}*${o.their_ref ? ` / ${o.their_ref}` : ''} → ${o.project_name} › ${o.site_name}${when}`,
      ...ps.map((p) => `• ${p.line.material}: ${n(p.pending)} ${p.line.unit} still to come`)].join('\n')
  })
  return [`Hello${company ? ` from ${company}` : ''}, these have not reached the site yet:`, '', ...parts, '', 'When will they come? Please reply with the date.'].join('\n')
}

