import * as React from 'react'
import { AlertCircle, ImageOff, UserPlus } from 'lucide-react'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchAttendanceReportDetailApi, type LabourAttendanceDetailItem, type LabourAttendanceLineItem } from '@/lib/api'
import { useSiteNames } from '@/lib/site-names'
import { CHIP, longDate } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { AddWorkerDialog } from './add-worker-dialog'

interface AttendanceDetailSheetProps {
  reportId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function AttendanceDetailSheet({
  reportId,
  open,
  onOpenChange,
}: AttendanceDetailSheetProps) {
  const [detail, setDetail] = React.useState<LabourAttendanceDetailItem | null>(null)
  const [loading, setLoading] = React.useState(false)
  // Surfaced, not swallowed. This used to console.warn and render an empty
  // sheet, so a failing request looked identical to a report with no workers
  // in it -- which is exactly how a 500 here got reported as "the worker
  // names are missing".
  const [loadError, setLoadError] = React.useState<string | null>(null)
  // The line currently being promoted -- drives both the "Save as permanent
  // worker" dialog's open state and what it's pre-filled with. null means
  // closed; kept as the whole line (not just booleans) so the dialog can
  // read name/trade/wage straight off it.
  const siteNames = useSiteNames()
  const [promotingLine, setPromotingLine] = React.useState<LabourAttendanceLineItem | null>(null)

  React.useEffect(() => {
    if (reportId && open) {
      setLoading(true)
      setLoadError(null)
      fetchAttendanceReportDetailApi(reportId)
        .then((data) => setDetail(data))
        .catch((err) => {
          console.warn('Failed to load attendance report details:', err)
          setDetail(null)
          setLoadError(
            "Couldn't load this report's details. The attendance itself is safely recorded — please try again, or refresh the page.",
          )
        })
        .finally(() => setLoading(false))
    } else {
      setDetail(null)
      setLoadError(null)
    }
  }, [reportId, open])

  const site = detail?.site_id ? siteNames.get(detail.site_id) : undefined
  const trade = (v: string | null) => (v ? v.charAt(0).toUpperCase() + v.slice(1).replace(/_/g, ' ') : 'Workers')

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col overflow-y-auto sm:max-w-[520px]">
        <SheetHeader>
          <SheetTitle>Attendance</SheetTitle>
          <SheetDescription>
            {detail
              ? [longDate(detail.occurred_date), site && `${site.name} · ${site.project}`, detail.recorded_via?.includes('whatsapp') ? 'sent on WhatsApp' : 'entered on the dashboard']
                  .filter(Boolean)
                  .join(' · ')
              : 'Who was on site that day.'}
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-4 px-4 pb-6 text-sm">
          {loading ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-10 w-40" />
              <Skeleton className="h-32 rounded-lg" />
            </div>
          ) : loadError ? (
            <p className="flex items-start gap-2 text-sm">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-draft" /> {loadError}
            </p>
          ) : !detail ? (
            <p className="text-muted-foreground">This report could not be found.</p>
          ) : (
            <>
              <p>
                <span className="text-2xl font-semibold tabular-nums">{detail.total_headcount}</span>{' '}
                <span className="text-muted-foreground">workers</span>
                {detail.total_cost > 0 && (
                  <span className="ml-3 text-muted-foreground">
                    · labour cost <strong className="font-semibold text-foreground">₹{detail.total_cost.toLocaleString('en-IN')}</strong>
                  </span>
                )}
              </p>
              {detail.notes && detail.notes !== 'Daily site attendance log' && <p className="text-muted-foreground">{detail.notes}</p>}

              {!detail.lines || detail.lines.length === 0 ? (
                <p className="text-muted-foreground">No trades recorded on this report.</p>
              ) : (
                <ul className="divide-y rounded-lg border">
                  {detail.lines.map((line, idx) => {
                    const rate = line.daily_wage || 0
                    // A headcount group ("12 helpers") names nobody -- there
                    // is no one to match or promote, so the register /
                    // temporary distinction only applies to a named person.
                    const named = Boolean(line.worker_name)
                    const onRegister = Boolean(line.worker_id)
                    return (
                      <li key={line.id || idx} className="flex items-center gap-3 px-3 py-2">
                        <div className="flex min-w-0 flex-1 flex-col">
                          <span className="font-medium">
                            {named ? line.worker_name : trade(line.trade)}
                            {named && line.trade && <span className="font-normal text-muted-foreground"> · {trade(line.trade)}</span>}
                            {named && !onRegister && <span className={cn(CHIP, 'ml-2 bg-muted text-muted-foreground')}>Not on register</span>}
                          </span>
                          {/* The reading as originally written (e.g. a
                              Malayalam-script name), so a mis-transliteration
                              is catchable here as at WhatsApp confirmation. */}
                          <span className="text-xs text-muted-foreground">
                            {[
                              line.worker_name_original && line.worker_name_original !== line.worker_name && `As written: ${line.worker_name_original}`,
                              line.contractor,
                              line.activity,
                              rate ? `₹${rate.toLocaleString('en-IN')}/day` : null,
                            ]
                              .filter(Boolean)
                              .join(' · ')}
                          </span>
                        </div>
                        {named && !onRegister && (
                          <Button type="button" variant="outline" size="sm" className="gap-1" onClick={() => setPromotingLine(line)}>
                            <UserPlus className="size-3.5" /> Add
                          </Button>
                        )}
                        <span className="w-10 text-right font-semibold tabular-nums">{line.headcount}</span>
                      </li>
                    )
                  })}
                </ul>
              )}

              {detail.attachments && detail.attachments.length > 0 && (
                <div className="flex flex-col gap-2">
                  <h3 className="font-semibold">Photos</h3>
                  <div className="grid grid-cols-2 gap-2">
                    {detail.attachments.map((att, idx) =>
                      att.url ? (
                        <a key={att.id || idx} href={att.url} target="_blank" rel="noreferrer" className="overflow-hidden rounded-lg border">
                          <img src={att.url} alt="Attendance photo" className="aspect-video w-full object-cover" />
                        </a>
                      ) : (
                        // Captured but not servable right now: say so,
                        // never a broken image.
                        <div key={att.id || idx} className="flex aspect-video flex-col items-center justify-center gap-1 rounded-lg border border-dashed text-xs text-muted-foreground">
                          <ImageOff className="size-4" /> Photo unavailable
                        </div>
                      ),
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </SheetContent>

      {/* Attendance never writes the register as a side effect of recording
          (principle P1) -- this dialog is the explicit, separate act that
          promotes a temporary line into it, pre-filled with what the site
          already reported so nobody retypes a name and trade that were
          already typed once on WhatsApp. */}
      <AddWorkerDialog
        open={promotingLine !== null}
        onOpenChange={(next) => {
          if (!next) setPromotingLine(null)
        }}
        onSuccess={() => setPromotingLine(null)}
        initialValues={
          promotingLine
            ? {
                name: promotingLine.worker_name ?? undefined,
                trade: promotingLine.trade ?? undefined,
                dailyWage: promotingLine.daily_wage,
                contractor: promotingLine.contractor,
              }
            : undefined
        }
      />
    </Sheet>
  )
}
