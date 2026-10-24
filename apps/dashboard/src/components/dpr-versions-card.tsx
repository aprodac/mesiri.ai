import { FileText } from 'lucide-react'
import type { DprVersion } from '@/lib/api'
import { dateTime } from '@/lib/site-day'
import { Button } from '@/components/ui/button'

// A DPR's versions, newest first, each with its PDF. Shared by the site DPR
// page (WEB-04) and the project DPR page (WEB-05); sits in the page's side
// column (WEB-25).

export function DprVersionsCard({
  reportId,
  versions,
  onPdf,
  empty = "The report is built at the project's cutoff time.",
}: {
  reportId: string | null
  versions: DprVersion[]
  onPdf: (version: DprVersion) => void
  empty?: string
}) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold">Versions</h2>
      {!reportId || versions.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {versions.map((v) => (
            <li key={v.id} className="-mx-2 flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-muted/60">
              <div className="flex min-w-0 flex-col">
                <span className="text-sm font-medium">
                  Version {v.version_no}
                  {v.is_current && (
                    <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">current</span>
                  )}
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  {v.approved_at
                    ? `Approved${v.approved_by ? ` by ${v.approved_by}` : ''} · ${dateTime(v.approved_at)}`
                    : dateTime(v.created_at)}
                  {v.revision_reason ? ` · ${v.revision_reason}` : ''}
                </span>
              </div>
              <Button variant="ghost" size="sm" onClick={() => onPdf(v)}>
                <FileText /> PDF
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
