import { FileText } from 'lucide-react'
import type { DprVersion } from '@/lib/api'
import { dateTime } from '@/lib/site-day'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// A DPR's versions, newest first, each with its PDF. Shared by the site DPR
// page (WEB-04) and the project DPR page (WEB-05).

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
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Versions</CardTitle>
      </CardHeader>
      <CardContent>
        {!reportId || versions.length === 0 ? (
          <p className="text-sm text-muted-foreground">{empty}</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {versions.map((v) => (
              <li key={v.id} className="flex items-center justify-between gap-2 py-2">
                <div className="flex min-w-0 flex-col">
                  <span className="text-sm font-semibold">
                    Version {v.version_no}
                    {v.is_current && <span className="ml-2 text-xs font-normal text-muted-foreground">current</span>}
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
      </CardContent>
    </Card>
  )
}
