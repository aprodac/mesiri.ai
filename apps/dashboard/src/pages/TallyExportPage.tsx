import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookOpenCheck, FileCode2, Info } from 'lucide-react'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { mayManageMoney } from '@/lib/cost'
import { downloadBlob } from '@/lib/export'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { downloadTallyXml, fetchTallySummary } from '@/lib/tally'
import { cn } from '@/lib/utils'

// NXT-12: the books for the CA. A period's confirmed expenses (Journal vouchers) and payments (Payment vouchers),
// with the ledgers they use, as one XML file Tally imports (Gateway of Tally › Import › Vouchers). One way: nothing
// comes back from Tally. Owner, admin and finance only.

function iso(d: Date): string {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}
function monthOf(offset: number): { date_from: string; date_to: string } {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth() + offset, 1)
  const end = offset === 0 ? now : new Date(now.getFullYear(), now.getMonth() + offset + 1, 0)
  return { date_from: iso(start), date_to: iso(end) }
}

export default function TallyExportPage() {
  const { me } = useAuth()
  const toast = useToast()
  usePageTitle('Tally export')
  const allowed = mayManageMoney(me?.role)
  const [period, setPeriod] = React.useState(() => monthOf(0))
  const [busy, setBusy] = React.useState(false)
  const q = useQuery({ queryKey: ['tally', period], queryFn: () => fetchTallySummary(period), enabled: allowed })

  if (!allowed) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">The Tally export takes the company's books out of Mesiri.</p>
        <p className="text-sm text-muted-foreground">Only the owner, an admin or finance can make it.</p>
      </div>
    )
  }
  const presets = [
    { label: 'This month', value: monthOf(0) },
    { label: 'Last month', value: monthOf(-1) },
  ]
  const download = async () => {
    setBusy(true)
    try {
      const { blob, filename } = await downloadTallyXml(period)
      downloadBlob(filename, blob)
    } catch (err) {
      toast.error('Could not make the Tally file', apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  const s = q.data
  const books = s?.source === 'books'
  const empty = s && (books ? !s.vouchers : s.journals + s.payments + s.sales + s.receipts === 0)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/finance/expenses', label: 'Expenses' }} crumb="Accounts" title="Tally export" date={books ? 'Your books, voucher by voucher, for your CA' : 'Expenses and payments for your CA'} />
      <div className="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-end">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Period">
          {presets.map((p) => {
            const on = p.value.date_from === period.date_from && p.value.date_to === period.date_to
            return (
              <button
                key={p.label}
                type="button"
                aria-pressed={on}
                onClick={() => setPeriod(p.value)}
                className={cn('rounded-full border px-3 py-1 text-sm', on ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-muted/60')}
              >
                {p.label}
              </button>
            )
          })}
        </div>
        <div className="flex flex-1 gap-2">
          <div className="flex flex-1 flex-col gap-1">
            <Label htmlFor="tally-from" className="text-xs">From</Label>
            <Input id="tally-from" type="date" value={period.date_from} max={period.date_to} onChange={(e) => e.target.value && setPeriod((p) => ({ ...p, date_from: e.target.value }))} />
          </div>
          <div className="flex flex-1 flex-col gap-1">
            <Label htmlFor="tally-to" className="text-xs">To</Label>
            <Input id="tally-to" type="date" value={period.date_to} min={period.date_from} onChange={(e) => e.target.value && setPeriod((p) => ({ ...p, date_to: e.target.value }))} />
          </div>
        </div>
        <Button className="gap-1.5" onClick={download} disabled={busy || !s || !!empty}>
          <FileCode2 className="size-4" /> {busy ? 'Preparing…' : 'Download for Tally'}
        </Button>
      </div>

      {q.isError ? (
        <PageError message="The export could not be prepared." onRetry={() => q.refetch()} back={{ to: '/finance/expenses', label: 'Expenses' }} />
      ) : q.isLoading || !s ? (
        <Skeleton className="h-24 rounded-lg" />
      ) : (
        books ? (
          <>
            <StatStrip
              stats={[
                { label: 'Vouchers', value: String(s.vouchers ?? 0), hint: `₹${Number(s.total ?? 0).toLocaleString('en-IN')} debited` },
                { label: 'Journals / purchases', value: String(s.journals), hint: 'expenses, provisions, depreciation' },
                { label: 'Payments / receipts', value: `${s.payments} / ${s.receipts}`, hint: 'bank and cash' },
                { label: 'Sales / contra', value: `${s.sales} / ${s.contras ?? 0}`, hint: 'RA bills / own transfers' },
                { label: 'Ledgers', value: String(s.ledgers), hint: s.groups ? `and ${s.groups} groups of your own` : "in Tally's own groups" },
              ]}
            />
            <Callout tone="info" icon={BookOpenCheck}>
              Accounts is on, so this is exactly what your books hold for the period: every voucher in the day book, manual vouchers, depreciation and the month-end accruals included{s.after_close ? `, and ${s.after_close} change${s.after_close === 1 ? '' : 's'} posted after a month was closed` : ''}. Importing the same period again updates the same vouchers.
            </Callout>
            {empty && <p className="text-sm text-muted-foreground">Nothing in the books in this period.</p>}
          </>
        ) : (
        <>
          <StatStrip
            stats={[
              { label: 'Expenses', value: String(s.journals), hint: 'Journal vouchers' },
              { label: 'Payments', value: String(s.payments), hint: 'Payment vouchers' },
              { label: 'RA bills / received', value: `${s.sales} / ${s.receipts}`, hint: 'Sales / Receipt vouchers' },
              { label: 'Ledgers', value: String(s.ledgers), hint: 'created if missing' },
              { label: 'GST split out', value: String(s.gst_split ?? 0), hint: s.gst_not_split ? `${s.gst_not_split} said as not included` : 'to Input GST' },
            ]}
          />
          {empty && <p className="text-sm text-muted-foreground">No confirmed expense or payment in this period.</p>}
        </>
        )
      )}

      <DprSection icon={BookOpenCheck} title="What goes into Tally">
        <ul className="flex list-disc flex-col gap-1.5 pl-5 text-sm text-muted-foreground">
          <li>
            <span className="font-medium text-foreground">Each expense</span> is a Journal: its category is debited, and the supplier (or the person who
            paid from their own pocket, or "Expenses payable") is credited. GST that the bill says is included goes to "Input GST".
          </li>
          <li>
            <span className="font-medium text-foreground">Each payment</span> is a Payment: the same party is debited and the bank or cash account it
            left is credited. Advances paid to a supplier come in once, when paid.
          </li>
          <li>
            <span className="font-medium text-foreground">Each RA bill sent</span> is a Sales voucher: the client is debited what they pay, with TDS,
            retention and the advance recovered on their own ledgers; contract revenue and output GST are credited.{' '}
            <span className="font-medium text-foreground">Money received</span> is a Receipt into the bank or cash account.
          </li>
          <li>
            <span className="font-medium text-foreground">Ledgers</span> come first: suppliers under Sundry Creditors, categories under Indirect
            Expenses, bank and cash under their groups. Your CA can move any of them in Tally.
          </li>
        </ul>
      </DprSection>
      <Callout tone="muted" icon={Info}>
        One way: nothing comes back from Tally. Each voucher carries Mesiri's number, so importing the same period twice makes duplicates; import each
        period once.
      </Callout>
    </div>
  )
}
