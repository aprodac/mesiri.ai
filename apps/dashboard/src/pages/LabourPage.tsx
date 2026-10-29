import * as React from 'react'
import { UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PageHeader, Segmented } from '@/components/dpr-page'
import { AttendanceView } from '@/components/workforce/attendance-view'
import { WorkersView } from '@/components/workforce/workers-view'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'

// WEB-22 (approved by Alan, 24 Oct): Labour is one page -- Attendance (who
// was on site, by day; the figures, chart and statements that used to be
// Overview, Analytics and Reports) and Workers (the register). The old
// WhatsApp Automations and Settings pages are gone: nothing read their
// toggles (labour_settings is only stored and echoed back).

type View = 'attendance' | 'workers'

export default function LabourPage() {
  const { scope } = useScope()
  const readOnly = useReadOnly()
  const [view, setView] = useUrlState<View>('view', 'attendance')
  const [addOpen, setAddOpen] = React.useState(false)
  usePageTitle(view === 'workers' ? 'Workers · Labour' : 'Labour')
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const scopeLabel = scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'project' ? scope.projectName : `${scope.projectName} / ${scope.siteName}`

  const switcher = (
    <Segmented<View>
      label="View"
      value={view}
      onChange={setView}
      options={[
        { value: 'attendance', label: 'Attendance' },
        { value: 'workers', label: 'Workers' },
      ]}
    />
  )

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Labour"
        subtitle={`Who was on site, and the worker register · ${scopeLabel}`}
        actions={
          !readOnly && (
            <Button
              size="sm"
              variant={view === 'workers' ? 'default' : 'outline'}
              className="gap-1.5"
              onClick={() => {
                setView('workers')
                setAddOpen(true)
              }}
            >
              <UserPlus className="size-4" /> Add worker
            </Button>
          )
        }
      />
      {/* WEB-40: the view switch sits in the same toolbar row as each view's
          filters and export, so the top of the page is one line. */}
      {view === 'attendance' ? (
        <AttendanceView projectId={projectId} siteId={siteId} leading={switcher} />
      ) : (
        <WorkersView addOpen={addOpen} setAddOpen={setAddOpen} leading={switcher} />
      )}
    </div>
  )
}
