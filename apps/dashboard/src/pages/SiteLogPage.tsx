import { useSearchParams } from 'react-router-dom'
import { PageHeader, Segmented } from '@/components/dpr-page'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import ActivitiesPage from './ActivitiesPage'
import OperationsGalleryPage from './OperationsGalleryPage'
import OperationsTimelinePage from './OperationsTimelinePage'

// One page for what the sites sent (sidebar sort, 24 Oct): Work (the work
// items), Photos, and Everything (the timeline of every event). Was three
// sidebar pages -- Activities, Gallery, Timeline -- whose old addresses now
// land on the matching view.

type View = 'work' | 'photos' | 'all'
const TITLES: Record<View, string> = { work: 'Work', photos: 'Photos', all: 'Everything' }

export default function SiteLogPage() {
  const { scope } = useScope()
  const [params, setParams] = useSearchParams()
  const raw = params.get('view')
  const view: View = raw === 'photos' || raw === 'all' ? raw : 'work'
  usePageTitle(`${TITLES[view]} · Site log`)
  const scopeLabel = scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'project' ? scope.projectName : `${scope.projectName} / ${scope.siteName}`

  // Each view keeps its own filters in the address; switching drops them
  // (they mean different things per view) but keeps the scope.
  const switchTo = (next: View) =>
    setParams(
      (prev) => {
        const kept = new URLSearchParams()
        for (const key of ['project', 'site']) {
          const v = prev.get(key)
          if (v) kept.set(key, v)
        }
        if (next !== 'work') kept.set('view', next)
        return kept
      },
      { replace: true },
    )

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader title="Site log" subtitle={`Everything the sites sent, newest first · ${scopeLabel}`} />
      <Segmented<View>
        label="View"
        value={view}
        onChange={switchTo}
        options={[
          { value: 'work', label: 'Work' },
          { value: 'photos', label: 'Photos' },
          { value: 'all', label: 'Everything' },
        ]}
      />
      {view === 'work' && <ActivitiesPage embedded />}
      {view === 'photos' && <OperationsGalleryPage embedded />}
      {view === 'all' && <OperationsTimelinePage embedded />}
    </div>
  )
}
