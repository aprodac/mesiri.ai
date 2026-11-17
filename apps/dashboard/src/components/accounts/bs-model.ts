import type { BalanceSheet, BsGroup, BsSub } from '@/lib/accounts'

// UX-33: the balance sheet read for an owner. Tally's groups sorted into buckets with plain names, by the chart's
// group codes (backend chart.py GROUPS), so a renamed group still lands right. Shared by the owner's view and the
// Tally view (its comparison figures).

export type Side = 'own' | 'owe' | 'worth'
export type BucketKey = 'cash' | 'clients' | 'held' | 'fixed' | 'own_other' | 'suppliers' | 'taxes' | 'loans' | 'owe_other' | 'suspense' | 'worth'

export interface BucketMeta {
  key: BucketKey
  side: Side
  label: string
  hint: string
}

export const BUCKETS: BucketMeta[] = [
  { key: 'cash', side: 'own', label: 'Cash and bank', hint: 'In the bank and in hand on this day' },
  { key: 'clients', side: 'own', label: 'Clients owe you', hint: 'RA bills sent and not yet paid' },
  { key: 'held', side: 'own', label: 'Held back and advances', hint: 'Retention and TDS clients keep, advances you paid, deposits' },
  { key: 'fixed', side: 'own', label: 'Equipment and property', hint: 'Machines, vehicles and other things you bought to keep' },
  { key: 'own_other', side: 'own', label: 'Other things you own', hint: 'Anything else the company has' },
  { key: 'suppliers', side: 'owe', label: 'You owe suppliers', hint: 'Bills not yet paid, to suppliers and subcontractors' },
  { key: 'taxes', side: 'owe', label: 'Taxes to pay', hint: 'GST collected less the GST you claim back, and TDS to deposit' },
  { key: 'loans', side: 'owe', label: 'Loans', hint: 'Money borrowed' },
  { key: 'owe_other', side: 'owe', label: 'Other dues', hint: 'Advances from clients, retention you hold, staff and unpaid expenses' },
  { key: 'suspense', side: 'owe', label: 'To be sorted', hint: 'Opening differences and adjustments your accountant should place' },
  { key: 'worth', side: 'worth', label: 'What the company is worth', hint: 'Money put in, and the profit kept over the years' },
]

const BY_CODE: Record<string, BucketKey> = {
  bank_accounts: 'cash',
  cash_in_hand: 'cash',
  sundry_debtors: 'clients',
  loans_advances: 'held',
  deposits: 'held',
  fixed_assets: 'fixed',
  sundry_creditors: 'suppliers',
  duties_taxes: 'taxes',
  loans: 'loans',
  suspense: 'suspense',
}

export function bucketOf(group: BsGroup, sub: BsSub): BucketKey {
  if (group.nature === 'equity') return 'worth'
  const byCode = (sub.code && BY_CODE[sub.code]) || (group.code && BY_CODE[group.code])
  if (byCode) return byCode
  return group.nature === 'asset' ? 'own_other' : 'owe_other'
}

export interface BucketLine {
  key: string
  name: string
  amount: number
  ledgers: { ledger_id: string; name: string; amount: number }[]
}
export interface Bucket extends BucketMeta {
  amount: number
  lines: BucketLine[]
}

const subKey = (g: BsGroup, s: BsSub) => `${g.group_id}/${s.group_id ?? s.code ?? s.name}`

/** The buckets with their lines (a Tally subgroup each), in BUCKETS order; empty buckets left out. */
export function buckets(bs: BalanceSheet): Bucket[] {
  const out = new Map<BucketKey, Bucket>()
  for (const g of [...bs.assets, ...bs.liabilities]) {
    for (const s of g.subgroups) {
      const k = bucketOf(g, s)
      const meta = BUCKETS.find((b) => b.key === k)!
      const b = out.get(k) ?? { ...meta, amount: 0, lines: [] }
      const amount = Number(s.amount)
      b.amount += amount
      b.lines.push({ key: subKey(g, s), name: s.name, amount, ledgers: s.ledgers.map((l) => ({ ledger_id: l.ledger_id, name: l.name, amount: Number(l.amount) })) })
      out.set(k, b)
    }
  }
  return BUCKETS.map((m) => out.get(m.key)).filter((b): b is Bucket => !!b && (Math.abs(b.amount) >= 0.005 || b.lines.length > 0))
}

/** Every figure of a balance sheet by key (group, subgroup, ledger, bucket), to set another date beside it. */
export function figures(bs: BalanceSheet | undefined): Map<string, number> | null {
  if (!bs) return null
  const m = new Map<string, number>()
  for (const g of [...bs.assets, ...bs.liabilities]) {
    m.set(`g:${g.group_id}`, Number(g.amount))
    for (const s of g.subgroups) {
      m.set(`s:${subKey(g, s)}`, Number(s.amount))
      for (const l of s.ledgers) m.set(`l:${l.ledger_id}`, (m.get(`l:${l.ledger_id}`) ?? 0) + Number(l.amount))
    }
  }
  for (const b of buckets(bs)) m.set(`b:${b.key}`, b.amount)
  m.set('total_assets', Number(bs.total_assets))
  m.set('total_liabilities', Number(bs.total_liabilities))
  return m
}

/** A figure on the comparison date: 0 when it did not exist then, null when not comparing. */
export const then = (m: Map<string, number> | null, key: string) => (m === null ? null : m.get(key) ?? 0)

export { subKey }
