import * as React from 'react'
import { ArrowLeftRight, PackageMinus, PackagePlus } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { Button } from '@/components/ui/button'
import { PageHeader, Segmented } from '@/components/dpr-page'
import { MovementsView } from '@/components/materials/movements-view'
import { InventoryView } from '@/components/materials/inventory-view'
import { CatalogueView } from '@/components/materials/catalogue-view'
import { PurchaseHistoryView } from '@/components/materials/purchase-history-view'
import { RecordInflowDialog } from '@/components/materials/record-inflow-dialog'
import { RecordOutflowDialog } from '@/components/materials/record-outflow-dialog'
import { RecordTransferDialog } from '@/components/materials/record-transfer-dialog'
import { TransfersView } from '@/components/materials/transfers-view'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'

// WEB-29: Materials in plain words -- Stock, Delivered, Used, Between sites,
// Spend -- with the three ways stock changes as the page's actions.

type MaterialsView = 'inventory' | 'inflows' | 'outflows' | 'transfers' | 'purchases' | 'catalogue'

export default function MaterialsPage() {
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  usePageTitle('Materials')
  const isAdmin = me?.role === 'ADMIN'
  const [requested, setView] = useUrlState<MaterialsView>('view', 'inventory')
  // Catalogue is admin-only: a stale link falls back to Stock.
  const view: MaterialsView = requested === 'catalogue' && !isAdmin ? 'inventory' : requested

  const [dialog, setDialog] = React.useState<'in' | 'out' | 'transfer' | null>(null)
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const scopeLabel = scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'project' ? scope.projectName : `${scope.projectName} / ${scope.siteName}`
  // ADMIN/PROJECT_MANAGER-only reasons (stock corrections) are gated inside
  // the record dialogs themselves.
  const canRecord = !!me && me.role !== 'FINANCE' && !readOnly

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Materials"
        subtitle={`What each site holds, received and used · ${scopeLabel}`}
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

      <Segmented<MaterialsView>
        label="View"
        value={view}
        onChange={setView}
        options={[
          { value: 'inventory', label: 'Stock' },
          { value: 'inflows', label: 'Delivered' },
          { value: 'outflows', label: 'Used' },
          { value: 'transfers', label: 'Between sites' },
          { value: 'purchases', label: 'Spend' },
          ...(isAdmin ? [{ value: 'catalogue' as const, label: 'Catalogue' }] : []),
        ]}
      />

      {view === 'inventory' && <InventoryView projectId={projectId} siteId={siteId} />}
      {view === 'inflows' && <MovementsView key="in" direction="IN" projectId={projectId} siteId={siteId} />}
      {view === 'outflows' && <MovementsView key="out" direction="OUT" projectId={projectId} siteId={siteId} />}
      {view === 'transfers' && <TransfersView projectId={projectId} siteId={siteId} />}
      {view === 'purchases' && <PurchaseHistoryView projectId={projectId} siteId={siteId} />}
      {view === 'catalogue' && <CatalogueView />}

      <RecordInflowDialog open={dialog === 'in'} onOpenChange={(o) => setDialog(o ? 'in' : null)} scope={scope} />
      <RecordOutflowDialog open={dialog === 'out'} onOpenChange={(o) => setDialog(o ? 'out' : null)} scope={scope} />
      <RecordTransferDialog open={dialog === 'transfer'} onOpenChange={(o) => setDialog(o ? 'transfer' : null)} scope={scope} />
    </div>
  )
}
