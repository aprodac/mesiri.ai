import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowLeftRight, PackageMinus, PackagePlus } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { Button } from '@/components/ui/button'
import { PageHeader, Segmented } from '@/components/dpr-page'
import { LedgerView } from '@/components/materials/ledger-view'
import { CatalogueView } from '@/components/materials/catalogue-view'
import { SizesView } from '@/components/materials/sizes-view'
import { CategoryView } from '@/components/materials/category-view'
import { RecordInflowDialog } from '@/components/materials/record-inflow-dialog'
import { RecordOutflowDialog } from '@/components/materials/record-outflow-dialog'
import { RecordTransferDialog } from '@/components/materials/record-transfer-dialog'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'

// WEB-50 (Ilan, 5 Nov: "too many tabs"): three views, each with its filters as dropdowns on one toolbar row.
//   Stock      -- what each site holds, by category, for a period; running low (the default).
//   Movements  -- everything that came in and went out (the ledger, WEB-30).
//   Items      -- the list of items, their categories, sizes and the Excel import (admin, owner, project manager).
// "Stock now" (a side panel showing the same stock again) is gone: Stock is it. Old links still land on the
// right view (?view=ledger / inventory / catalogue / sizes / inflows ...).

type MaterialsView = 'stock' | 'movements' | 'items'

function viewFor(requested: string, canManage: boolean): MaterialsView {
  if (['ledger', 'movements', 'inflows', 'outflows', 'transfers', 'purchases'].includes(requested)) return 'movements'
  if (['items', 'catalogue', 'sizes'].includes(requested) && canManage) return 'items'
  return 'stock'
}

export default function MaterialsPage() {
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  usePageTitle('Materials')
  // The company-setup roles (Sizes and the import API allow the same): admin, owner, project manager.
  const canManage = me?.role === 'ADMIN' || me?.role === 'PROJECT_MANAGER' || me?.role === 'OWNER'
  const [requested, setView] = useUrlState<string>('view', 'stock')
  const view = viewFor(requested, canManage)

  // Older links (?view=inflows / outflows / purchases ...) open Movements, filtered the way they meant.
  const [, setParams] = useSearchParams()
  React.useEffect(() => {
    if (!['inflows', 'outflows', 'transfers', 'purchases'].includes(requested)) return
    setParams(
      (prev) => {
        prev.set('view', 'movements')
        if (requested === 'inflows' || requested === 'purchases') prev.set('dir', 'in')
        if (requested === 'outflows') prev.set('dir', 'out')
        return prev
      },
      { replace: true },
    )
  }, [requested, setParams])

  const [dialog, setDialog] = React.useState<'in' | 'out' | 'transfer' | null>(null)
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  // ADMIN/PROJECT_MANAGER-only reasons (stock corrections) are gated inside the record dialogs themselves.
  const canRecord = !!me && me.role !== 'FINANCE' && !readOnly

  const switcher = (
    <Segmented<MaterialsView>
      label="View"
      value={view}
      onChange={setView}
      options={[
        { value: 'stock', label: 'Stock' },
        { value: 'movements', label: 'Movements' },
        ...(canManage ? [{ value: 'items' as const, label: 'Items' }] : []),
      ]}
    />
  )

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Materials"
        actions={
          canRecord && (
            <>
              <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setDialog('in')}>
                <PackagePlus className="size-4" /> <span className="sm:hidden">Delivery</span>
                <span className="hidden sm:inline">Record delivery</span>
              </Button>
              <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setDialog('out')}>
                <PackageMinus className="size-4" /> <span className="sm:hidden">Use</span>
                <span className="hidden sm:inline">Record use</span>
              </Button>
              <Button size="icon" variant="outline" className="size-8 sm:w-auto sm:px-3" title="Move between sites" onClick={() => setDialog('transfer')}>
                <ArrowLeftRight className="size-4" /> <span className="hidden sm:inline">Move</span>
              </Button>
            </>
          )
        }
      />

      {view === 'stock' && <CategoryView projectId={projectId} siteId={siteId} leading={switcher} />}
      {view === 'movements' && <LedgerView projectId={projectId} siteId={siteId} leading={switcher} />}
      {view === 'items' && <CatalogueView leading={switcher} sizes={<SizesView />} />}

      <RecordInflowDialog open={dialog === 'in'} onOpenChange={(o) => setDialog(o ? 'in' : null)} scope={scope} />
      <RecordOutflowDialog open={dialog === 'out'} onOpenChange={(o) => setDialog(o ? 'out' : null)} scope={scope} />
      <RecordTransferDialog open={dialog === 'transfer'} onOpenChange={(o) => setDialog(o ? 'transfer' : null)} scope={scope} />
    </div>
  )
}
