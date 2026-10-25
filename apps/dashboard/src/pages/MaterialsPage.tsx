import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowLeftRight, Boxes, PackageMinus, PackagePlus } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { PageHeader, Segmented } from '@/components/dpr-page'
import { LedgerView } from '@/components/materials/ledger-view'
import { InventoryView } from '@/components/materials/inventory-view'
import { CatalogueView } from '@/components/materials/catalogue-view'
import { RecordInflowDialog } from '@/components/materials/record-inflow-dialog'
import { RecordOutflowDialog } from '@/components/materials/record-outflow-dialog'
import { RecordTransferDialog } from '@/components/materials/record-transfer-dialog'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'

// WEB-30: two views. The Ledger -- everything that came in and went out, as
// one table (In green, Out red), narrowed by material, site, dates -- and
// the Catalogue. What each site holds now opens from "Stock now".

type MaterialsView = 'ledger' | 'catalogue'

export default function MaterialsPage() {
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  usePageTitle('Materials')
  const isAdmin = me?.role === 'ADMIN'
  const [requested, setView] = useUrlState<string>('view', 'ledger')
  // Catalogue is admin-only; every other (older) view is the ledger.
  const view: MaterialsView = requested === 'catalogue' && isAdmin ? 'catalogue' : 'ledger'
  const [stockOpen, setStockOpen] = React.useState(false)

  // Older links (?view=inflows / outflows / inventory …) open the ledger,
  // filtered the way they meant.
  const [, setParams] = useSearchParams()
  React.useEffect(() => {
    if (!['inflows', 'outflows', 'inventory', 'transfers', 'purchases'].includes(requested)) return
    setParams(
      (prev) => {
        prev.delete('view')
        if (requested === 'inflows' || requested === 'purchases') prev.set('dir', 'in')
        if (requested === 'outflows') prev.set('dir', 'out')
        return prev
      },
      { replace: true },
    )
    if (requested === 'inventory') setStockOpen(true)
  }, [requested, setParams])

  const [dialog, setDialog] = React.useState<'in' | 'out' | 'transfer' | null>(null)
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const scopeLabel = scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'project' ? scope.projectName : `${scope.projectName} / ${scope.siteName}`
  // ADMIN/PROJECT_MANAGER-only reasons (stock corrections) are gated inside
  // the record dialogs themselves.
  const canRecord = !!me && me.role !== 'FINANCE' && !readOnly

  const switcher = (
    <>
      {isAdmin && (
        <Segmented<MaterialsView>
          label="View"
          value={view}
          onChange={setView}
          options={[
            { value: 'ledger', label: 'Ledger' },
            { value: 'catalogue', label: 'Catalogue' },
          ]}
        />
      )}
      <Button variant="outline" size="sm" className="h-8 gap-1.5" onClick={() => setStockOpen(true)}>
        <Boxes className="size-3.5" /> Stock now
      </Button>
    </>
  )

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Materials"
        subtitle={`Everything that came in and went out · ${scopeLabel}`}
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

      {/* WEB-40: the view switch and Stock now open the ledger's filter row,
          so the top of the page is one line of controls. */}
      {view === 'ledger' && <LedgerView projectId={projectId} siteId={siteId} leading={switcher} />}
      {view === 'catalogue' && (
        <>
          <div className="flex flex-wrap items-center gap-2">{switcher}</div>
          <CatalogueView />
        </>
      )}

      <Sheet open={stockOpen} onOpenChange={setStockOpen}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>Stock now</SheetTitle>
            <SheetDescription>What each site holds. Tap a material for its stock book.</SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-6">
            <InventoryView projectId={projectId} siteId={siteId} />
          </div>
        </SheetContent>
      </Sheet>

      <RecordInflowDialog open={dialog === 'in'} onOpenChange={(o) => setDialog(o ? 'in' : null)} scope={scope} />
      <RecordOutflowDialog open={dialog === 'out'} onOpenChange={(o) => setDialog(o ? 'out' : null)} scope={scope} />
      <RecordTransferDialog open={dialog === 'transfer'} onOpenChange={(o) => setDialog(o ? 'transfer' : null)} scope={scope} />
    </div>
  )
}
