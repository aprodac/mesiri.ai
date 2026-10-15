import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { Boxes, PackagePlus, PackageMinus, ListTree, ShoppingBag, ArrowLeftRight } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { InflowsView } from '@/components/materials/inflows-view'
import { OutflowsView } from '@/components/materials/outflows-view'
import { InventoryView } from '@/components/materials/inventory-view'
import { CatalogueView } from '@/components/materials/catalogue-view'
import { PurchaseHistoryView } from '@/components/materials/purchase-history-view'
import { RecordInflowDialog } from '@/components/materials/record-inflow-dialog'
import { RecordOutflowDialog } from '@/components/materials/record-outflow-dialog'
import { RecordTransferDialog } from '@/components/materials/record-transfer-dialog'
import { TransfersView } from '@/components/materials/transfers-view'

type MaterialsView = 'inventory' | 'inflows' | 'outflows' | 'transfers' | 'purchases' | 'catalogue'

const VALID_VIEWS: MaterialsView[] = ['inventory', 'inflows', 'outflows', 'transfers', 'purchases', 'catalogue']

export default function MaterialsPage() {
  const { scope } = useScope()
  const { me } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  const isAdmin = me?.role === 'ADMIN'
  const rawView = searchParams.get('view')
  const requestedView: MaterialsView = VALID_VIEWS.includes(rawView as MaterialsView)
    ? (rawView as MaterialsView)
    : 'inventory'
  // Catalogue is admin-only -- a non-admin landing on ?view=catalogue
  // (stale link, role change) falls back to Inventory rather than rendering
  // a tab they can't see the trigger for.
  const view: MaterialsView = requestedView === 'catalogue' && !isAdmin ? 'inventory' : requestedView

  const [inflowDialogOpen, setInflowDialogOpen] = React.useState(false)
  const [outflowDialogOpen, setOutflowDialogOpen] = React.useState(false)
  const [transferDialogOpen, setTransferDialogOpen] = React.useState(false)

  const selectView = (next: string) => {
    setSearchParams((prev) => {
      if (next === 'inventory') {
        prev.delete('view')
      } else {
        prev.set('view', next)
      }
      return prev
    })
  }

  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null

  const scopeLabel = React.useMemo(() => {
    if (scope.mode === 'portfolio') return 'Portfolio Scope (All Projects)'
    if (scope.mode === 'project') return `Project Scope: ${scope.projectName}`
    return `Site Scope: ${scope.projectName} / ${scope.siteName}`
  }, [scope])

  // Every authenticated role that can reach a Project/Site scope can record
  // ordinary material movements; ADMIN/PROJECT_MANAGER-only reasons
  // (ADJUSTMENT_IN/ADJUSTMENT_OUT) are gated further inside the record
  // dialogs themselves.
  const canRecordMovements = !!me && me.role !== 'FINANCE'

  return (
    <div className="flex flex-col gap-4 text-sm">
      {/* Header section */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-4">
        <div className="flex items-center gap-3">
          <div className="size-10 rounded-full border border-primary/20 bg-primary/10 flex items-center justify-center text-primary shrink-0">
            <Boxes className="size-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-foreground leading-tight">Materials</h1>
            <p className="text-xs text-muted-foreground font-semibold">{scopeLabel}</p>
          </div>
        </div>
        <div className="flex gap-2">
          {canRecordMovements && (
            <>
              <Button
                size="sm"
                variant="outline"
                className="h-8 gap-1.5 text-xs font-bold"
                onClick={() => setInflowDialogOpen(true)}
              >
                <PackagePlus className="size-3.5" />
                Record Inflow
              </Button>
              <Button
                size="sm"
                className="h-8 gap-1.5 text-xs font-bold"
                onClick={() => setOutflowDialogOpen(true)}
              >
                <PackageMinus className="size-3.5" />
                Record Outflow
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-8 gap-1.5 text-xs font-bold"
                onClick={() => setTransferDialogOpen(true)}
              >
                <ArrowLeftRight className="size-3.5" />
                Transfer
              </Button>
            </>
          )}
        </div>
      </div>

      {/* View switch */}
      <Tabs value={view} onValueChange={selectView}>
        <TabsList>
          <TabsTrigger value="inventory">Inventory</TabsTrigger>
          <TabsTrigger value="inflows">Inflows</TabsTrigger>
          <TabsTrigger value="outflows">Outflows</TabsTrigger>
          <TabsTrigger value="transfers">Transfers</TabsTrigger>
          <TabsTrigger value="purchases" className="gap-1.5">
            <ShoppingBag className="size-3.5" />
            Purchase History
          </TabsTrigger>
          {isAdmin && (
            <TabsTrigger value="catalogue" className="gap-1.5">
              <ListTree className="size-3.5" />
              Catalogue
            </TabsTrigger>
          )}
        </TabsList>
      </Tabs>

      {view === 'inventory' && <InventoryView projectId={projectId} siteId={siteId} />}
      {view === 'inflows' && <InflowsView projectId={projectId} siteId={siteId} />}
      {view === 'outflows' && <OutflowsView projectId={projectId} siteId={siteId} />}
      {view === 'transfers' && <TransfersView projectId={projectId} siteId={siteId} />}
      {view === 'purchases' && <PurchaseHistoryView projectId={projectId} siteId={siteId} />}
      {view === 'catalogue' && <CatalogueView />}

      <RecordInflowDialog
        open={inflowDialogOpen}
        onOpenChange={setInflowDialogOpen}
        scope={scope}
      />
      <RecordOutflowDialog
        open={outflowDialogOpen}
        onOpenChange={setOutflowDialogOpen}
        scope={scope}
      />
      <RecordTransferDialog
        open={transferDialogOpen}
        onOpenChange={setTransferDialogOpen}
        scope={scope}
      />
    </div>
  )
}
