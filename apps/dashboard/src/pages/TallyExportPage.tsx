import * as React from 'react'
import { BOOKS_PEOPLE } from '@/lib/permissions'
import { NoAccess } from '@/components/page/page-kit'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BookOpenCheck, FileCode2, Info } from 'lucide-react'
import { Callout, DprHeader, DprSection, PageError, StatStrip } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
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
import { appNow } from '@/lib/clock'
import { DatePicker } from '@/components/ui/date-picker'

// NXT-12: the books for the CA. A period's confirmed expenses (Journal vouchers) and payments (Payment vouchers),
// with the ledgers they use, as one XML file Tally imports (Gateway of Tally › Import › Vouchers). One way: nothing
// comes back from Tally. Owner, admin and finance only.

function iso(d: Date): string {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}
function monthOf(offset: number): { date_from: string; date_to: string } {
  const now = appNow()
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
      <NoAccess roles={BOOKS_PEOPLE} />
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
  const empty = s && (books ? s.vouchers === 0 : s.journals + s.payments + s.sales + s.receipts === 0)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/finance/expenses', label: 'Expenses' }} crumb="Accounts" title="Tally export" />
      <div className="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-end">
        <div data-guide="tally.period" className="flex flex-wrap gap-2" role="group" aria-label="Period">
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
            <DatePicker id="tally-from" value={period.date_from} max={period.date_to} onChange={(v) => v && setPeriod((p) => ({ ...p, date_from: v }))} />
          </div>
          <div className="flex flex-1 flex-col gap-1">
            <Label htmlFor="tally-to" className="text-xs">To</Label>
            <DatePicker id="tally-to" value={period.date_to} min={period.date_from} onChange={(v) => v && setPeriod((p) => ({ ...p, date_to: v }))} />
          </div>
        </div>
        <Button data-guide="tally.download" className="gap-1.5" onClick={download} disabled={busy || !s || !!empty}>
          <FileCode2 className="size-4" /> {busy ? 'Preparing…' : 'Download for Tally'}
        </Button>
      </div>

      {q.isError ? (
        <PageError message="The export could not be prepared." onRetry={() => q.refetch()} back={{ to: '/finance/expenses', label: 'Expenses' }} />
      ) : q.isLoading || !s ? (
        <Skeleton className="h-24 rounded-lg" />
      ) : (
        <>
          <StatStrip guide="tally.stats"
            stats={books ? [
              // ACC-19: from the books, every voucher of its own type, so Tally holds what the trial balance holds.
              { label: 'Vouchers', value: String(s.vouchers ?? 0), hint: `${s.purchases ?? 0} purchase · ${s.payments} payment · ${s.receipts} receipt` },
              { label: 'Sales / Contra', value: `${s.sales} / ${s.contra ?? 0}` },
              { label: 'Journals', value: String(s.journals), hint: s.manual ? `${s.manual} entered by hand` : undefined },
              { label: 'Ledgers', value: String(s.ledgers), hint: 'from the chart, created if missing' },
              { label: 'Changed after close', value: String(s.after_close ?? 0), hint: 'carried on the first open day' },
            ] : [
              { label: 'Expenses', value: String(s.journals), hint: 'Journal vouchers' },
              { label: 'Payments', value: String(s.payments), hint: 'Payment vouchers' },
              { label: 'RA bills / received', value: `${s.sales} / ${s.receipts}`, hint: 'Sales / Receipt vouchers' },
              { label: 'Ledgers', value: String(s.ledgers), hint: 'created if missing' },
              { label: 'GST split out', value: String(s.gst_split), hint: s.gst_not_split ? `${s.gst_not_split} said as not included` : 'to Input GST' },
            ]}
          />
          {empty && <p className="text-sm text-muted-foreground">No confirmed expense or payment in this period.</p>}
        </>
      )}

      {/* UX-13: how records become vouchers, as a map rather than paragraphs; the ? help has the detail. */}
      <DprSection icon={BookOpenCheck} title="Into Tally as">
        <ul data-guide="tally.as" className="flex flex-wrap gap-2 text-sm">
          {[
            ['Expense', 'Journal'],
            ['Payment', 'Payment'],
            ['RA bill', 'Sales'],
            ['Money received', 'Receipt'],
            ...(books ? [['Your journals', 'Journal']] : []),
          ].map(([from, to]) => (
            <li key={from} className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1">
              <span>{from}</span>
              <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
              <span className="font-medium">{to}</span>
            </li>
          ))}
        </ul>
      </DprSection>
      <Callout tone="draft" icon={Info}>
        Import each period once: twice makes duplicates.
      </Callout>
    </div>
  )
}
