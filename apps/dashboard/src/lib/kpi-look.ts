import type { LucideIcon } from 'lucide-react'
import {
  Banknote, Boxes, CalendarDays, Camera, CircleCheck, ClipboardList, Clock, FileText, Gauge, Hammer, HardHat, Hash,
  IndianRupee, MapPin, TrendingUp, Package, Percent, ShoppingCart, Tractor, TriangleAlert, Truck, Users, Wallet,
} from 'lucide-react'

// UX-15 (asked by Ilan 17 Nov 2026): every figure on every page carries an icon that says what kind of figure it
// is, from this one table, so "workers" look like workers and money looks like money on every page. A page names
// the kind (`kind: 'money'`) or passes its own icon; when it gives neither, `guessKind` reads the figure (a ₹ is
// money) and then the label's first matching word below. A new kind is one line here.

export type KpiKind =
  | 'money' | 'cash' | 'bill' | 'count' | 'percent' | 'progress' | 'done' | 'sites' | 'workers' | 'people' | 'work'
  | 'margin' | 'materials' | 'stock' | 'delivery' | 'order' | 'request' | 'issue' | 'time' | 'day' | 'photo' | 'machine' | 'rate'

export const KPI_ICON: Record<KpiKind, LucideIcon> = {
  money: IndianRupee,
  cash: Wallet,
  bill: Banknote,
  count: Hash,
  percent: Percent,
  progress: Gauge,
  done: CircleCheck,
  sites: MapPin,
  workers: HardHat,
  people: Users,
  work: Hammer,
  margin: TrendingUp,
  materials: Package,
  stock: Boxes,
  delivery: Truck,
  order: ShoppingCart,
  request: ClipboardList,
  issue: TriangleAlert,
  time: Clock,
  day: CalendarDays,
  photo: Camera,
  machine: Tractor,
  rate: FileText,
}

// First match wins: the more specific words come first ("worker-days" is workers, not days).
const WORDS: [RegExp, KpiKind][] = [
  [/issue|critical|stopped|stuck|late|overdue|problem|short/i, 'issue'],
  [/worker|man-day|labour|mason|helper|attendance|wage/i, 'workers'],
  [/deliver|came in|received|grn|went out/i, 'delivery'],
  [/order|\bpo\b/i, 'order'],
  [/request|asked/i, 'request'],
  [/stock|store|in hand/i, 'stock'],
  [/material|cement|steel|sand|brick/i, 'materials'],
  [/machine|equipment|jcb|hire/i, 'machine'],
  [/photo|picture/i, 'photo'],
  [/cash|bank|petty/i, 'cash'],
  [/margin|profit/i, 'margin'],
  [/bill|invoice|voucher|payment|paid|owe|spent|cost|budget|value|gst|tds|sales|purchase|earned/i, 'money'],
  [/people|team|staff|supplier|client|vendor|contractor/i, 'people'],
  [/site|place|floor|level|room/i, 'sites'],
  [/progress|complete|% done/i, 'progress'],
  [/done|confirm|approved|sent|finished/i, 'done'],
  [/work|task|activit|item|line/i, 'work'],
  [/hour|time lost|minute/i, 'time'],
  [/day|week|month|date|yesterday|today/i, 'day'],
]

/** The kind of a figure, from its value first (₹ is money, % a share), then its label. */
export function guessKind(label: string, value?: unknown): KpiKind | undefined {
  const v = typeof value === 'string' ? value : typeof value === 'number' ? String(value) : ''
  if (v.includes('₹')) return 'money'
  if (/%\s*$/.test(v)) return 'percent'
  for (const [re, kind] of WORDS) if (re.test(label)) return kind
  return undefined
}
