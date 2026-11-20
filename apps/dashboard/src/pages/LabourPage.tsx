import * as React from 'react'
import { ClipboardList, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PageHeader, Segmented } from '@/components/dpr-page'
import { AttendanceView } from '@/components/workforce/attendance-view'
import { WorkersView } from '@/components/workforce/workers-view'
import { MusterView, TeamsView } from '@/components/workforce/muster-view'
import { RecordAttendanceDialog } from '@/components/workforce/record-attendance-dialog'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'

// WEB-22 (approved by Alan, 24 Oct): Labour is one page -- Attendance (who
// was on site, by day; the figures, chart and statements that used to be
// Overview, Analytics and Reports) and Workers (the register). The old
// WhatsApp Automations and Settings pages are gone: nothing read their
// toggles (labour_settings is only stored and echoed back).

type View = 'attendance' | 'muster' | 'workers' | 'teams'

export default function LabourPage() {
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const [view, setView] = useUrlState<View>('view', 'attendance')
  const [addOpen, setAddOpen] = React.useState(false)
  const [recordOpen, setRecordOpen] = React.useState(false)
  // Who may record attendance on the dashboard: everyone who records on site
  // (site engineers, PMs, admins, owners), the same as Materials — Finance and
  // read-only trials don't. The backend re-checks project/site authorization.
  const canRecord = !!me && me.role !== 'FINANCE' && !readOnly
  usePageTitle({ attendance: 'Labour', muster: 'Muster roll · Labour', workers: 'Workers · Labour', teams: 'Teams · Labour' }[view] ?? 'Labour')
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null

  const switcher = (
    <Segmented<View>
      guide="labour.views"
      label="View"
      value={view}
      onChange={setView}
      options={[
        { value: 'attendance', label: 'Attendance' },
        { value: 'muster', label: 'Muster roll' },
        { value: 'workers', label: 'Workers' },
        { value: 'teams', label: 'Teams' },
      ]}
    />
  )

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Labour"
        actions={
          !readOnly && (
            <div className="flex items-center gap-2">
              {canRecord && view !== 'workers' && (
                <Button
                  size="sm"
                  className="gap-1.5 font-semibold"
                  data-guide="labour.record"
                  onClick={() => setRecordOpen(true)}
                >
                  <ClipboardList className="size-4" /> Record attendance
                </Button>
              )}
              <Button
                size="sm"
                variant={view === 'workers' ? 'default' : 'outline'}
                className="gap-1.5"
                data-guide="labour.add"
                onClick={() => {
                  setView('workers')
                  setAddOpen(true)
                }}
              >
                <UserPlus className="size-4" /> Add worker
              </Button>
            </div>
          )
        }
      />
      {/* WEB-40: the view switch sits in the same toolbar row as each view's
          filters and export, so the top of the page is one line. */}
      {view === 'attendance' ? (
        <AttendanceView projectId={projectId} siteId={siteId} leading={switcher} />
      ) : view === 'muster' ? (
        <MusterView siteId={siteId} leading={switcher} />
      ) : view === 'teams' ? (
        <TeamsView leading={switcher} />
      ) : (
        <WorkersView addOpen={addOpen} setAddOpen={setAddOpen} leading={switcher} />
      )}

      <RecordAttendanceDialog open={recordOpen} onOpenChange={setRecordOpen} scope={scope} />
    </div>
  )
}
