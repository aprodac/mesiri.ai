import * as React from 'react'
import {
  Store,
  Plus,
  Search,
  DollarSign,
  TrendingUp,
  MoreVertical,
  Edit2,
  Power,
  Eye,
  Grid,
  List,
} from 'lucide-react'
import { KpiCard } from '@/components/ui/kpi-card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { fetchVendorsApi, updateVendorApi, type VendorItem } from '@/lib/api'
import { VendorDetailSheet } from '@/components/vendors/vendor-detail-sheet'
import { CreateVendorDialog } from '@/components/vendors/create-vendor-dialog'

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

import { useToast } from '@/components/ui/toast-notification'

export default function VendorsPage() {
  const toast = useToast()

  const [vendors, setVendors] = React.useState<VendorItem[]>([])
  const [loading, setLoading] = React.useState(true)
  const [search, setSearch] = React.useState('')
  const [statusFilter, setStatusFilter] = React.useState('ALL')
  const [viewMode, setViewMode] = React.useState<'grid' | 'table'>('grid')

  // Sheet & Dialog state
  const [selectedVendor, setSelectedVendor] = React.useState<VendorItem | null>(null)
  const [detailSheetOpen, setDetailSheetOpen] = React.useState(false)

  const [createDialogOpen, setCreateDialogOpen] = React.useState(false)
  const [vendorToEdit, setVendorToEdit] = React.useState<VendorItem | null>(null)

  const loadVendors = React.useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchVendorsApi()
      if (Array.isArray(data)) {
        setVendors(data)
      }
    } catch (err) {
      console.warn('Failed to load vendors:', err)
      setVendors([])
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    loadVendors()
  }, [loadVendors])

  const filteredVendors = React.useMemo(() => {
    return vendors.filter((v) => {
      const matchesSearch = v.name.toLowerCase().includes(search.toLowerCase())
      const matchesStatus =
        statusFilter === 'ALL' || v.status.toLowerCase() === statusFilter.toLowerCase()

      return matchesSearch && matchesStatus
    })
  }, [vendors, search, statusFilter])

  // Summary Metrics
  const metrics = React.useMemo(() => {
    const activeVendors = vendors.filter((v) => v.status === 'active')
    const totalPaid = vendors.reduce((acc, curr) => acc + (curr.total_amount_paid || 0), 0)
    const totalRecords = vendors.reduce((acc, curr) => acc + (curr.expense_count || 0), 0)

    let topVendor = activeVendors.length > 0 ? activeVendors[0] : null
    for (const v of activeVendors) {
      if (!topVendor || (v.total_amount_paid || 0) > (topVendor.total_amount_paid || 0)) {
        topVendor = v
      }
    }

    return {
      activeCount: activeVendors.length,
      totalCount: vendors.length,
      totalPaid,
      totalRecords,
      topVendorName: topVendor ? topVendor.name : 'None',
      topVendorAmount: topVendor ? topVendor.total_amount_paid || 0 : 0,
    }
  }, [vendors])

  const handleToggleStatus = async (vendor: VendorItem) => {
    const nextStatus = vendor.status === 'active' ? 'inactive' : 'active'
    try {
      await updateVendorApi(vendor.id, { status: nextStatus })
      toast.success(`Vendor "${vendor.name}" updated`, `Status set to ${nextStatus.toUpperCase()}`)
      loadVendors()
    } catch (err: any) {
      toast.error('Failed to update vendor status', err.message || 'Server error')
    }
  }


  return (
    <div className="flex flex-col gap-4 w-full max-w-full relative pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3.5">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Vendors</h1>
          </div>
        </div>

        <Button
          size="sm"
          className="h-9 px-3.5 text-xs font-semibold gap-1.5 shadow-2xs"
          onClick={() => {
            setVendorToEdit(null)
            setCreateDialogOpen(true)
          }}
        >
          <Plus className="size-4" />
          Add Vendor
        </Button>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          title="Active vendors"
          value={<span>{metrics.activeCount} Active</span>}
          description="Verified suppliers & contractors"
          icon={<Store  />}
        />
        <KpiCard
          title="Paid to vendors"
          value={<span>{formatCurrency(metrics.totalPaid)}</span>}
          description="Total confirmed payouts"
          icon={<DollarSign  />}
        />
        <KpiCard
          title="Top vendor"
          value={<span className="truncate block">{metrics.topVendorName}</span>}
          description="Highest disbursement payee"
          icon={<TrendingUp  />}
        />
      </div>

      {/* Filter & View Controls */}
      <div className="flex flex-col sm:flex-row gap-2.5 items-center justify-between bg-card p-3 rounded-lg border shadow-2xs">
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
            <Input
              placeholder="Search by vendor or payee name..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-8 text-xs"
            />
          </div>

          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-8 text-xs w-[130px]">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL" className="text-xs">All Statuses</SelectItem>
              <SelectItem value="ACTIVE" className="text-xs">Active Only</SelectItem>
              <SelectItem value="INACTIVE" className="text-xs">Inactive Only</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-1.5 self-end sm:self-auto">
          <Button
            size="sm"
            variant={viewMode === 'grid' ? 'secondary' : 'ghost'}
            className="size-8 p-0"
            onClick={() => setViewMode('grid')}
            title="Grid View"
          >
            <Grid className="size-4" />
          </Button>
          <Button
            size="sm"
            variant={viewMode === 'table' ? 'secondary' : 'ghost'}
            className="size-8 p-0"
            onClick={() => setViewMode('table')}
            title="Table View"
          >
            <List className="size-4" />
          </Button>
        </div>
      </div>

      {/* Vendor Content View */}
      {loading ? (
        <div className="py-20 text-center text-xs text-muted-foreground">
          Loading vendors & payees...
        </div>
      ) : filteredVendors.length === 0 ? (
        <div className="py-20 border rounded-lg bg-card text-center flex flex-col items-center justify-center p-6 gap-2">
          <Store className="size-10 text-muted-foreground/40" />
          <h3 className="text-sm font-semibold text-foreground">No Vendors Found</h3>
          <p className="text-xs text-muted-foreground max-w-sm">
            {search ? 'No vendors match your search query.' : 'Register your first vendor or state payees over WhatsApp.'}
          </p>
          <Button
            size="sm"
            className="mt-2 text-xs font-semibold gap-1.5"
            onClick={() => {
              setVendorToEdit(null)
              setCreateDialogOpen(true)
            }}
          >
            <Plus className="size-3.5" />
            Add Vendor
          </Button>
        </div>
      ) : viewMode === 'grid' ? (
        /* Grid View */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filteredVendors.map((vendor) => (
            <div
              key={vendor.id}
              className="group p-4 rounded-lg border bg-card hover:border-indigo-500/40 transition-all shadow-2xs flex flex-col justify-between gap-3 relative"
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2.5">
                    <div className="size-9 rounded-lg bg-indigo-500/10 text-indigo-600 flex items-center justify-center font-bold text-sm shrink-0">
                      <Store className="size-4.5" />
                    </div>
                    <div>
                      <h3 className="font-bold text-sm text-foreground truncate max-w-[170px]">
                        {vendor.name}
                      </h3>
                      <span className="text-[10px] text-muted-foreground">
                        Registered Payee
                      </span>
                    </div>
                  </div>

                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button size="sm" variant="ghost" className="size-7 p-0 text-muted-foreground">
                        <MoreVertical className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="text-xs">
                      <DropdownMenuItem
                        onClick={() => {
                          setSelectedVendor(vendor)
                          setDetailSheetOpen(true)
                        }}
                      >
                        <Eye className="size-3.5 mr-2 text-indigo-500" />
                        View Payments History
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={() => {
                          setVendorToEdit(vendor)
                          setCreateDialogOpen(true)
                        }}
                      >
                        <Edit2 className="size-3.5 mr-2 text-blue-500" />
                        Edit Vendor
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => handleToggleStatus(vendor)}>
                        <Power className="size-3.5 mr-2 text-amber-500" />
                        {vendor.status === 'active' ? 'Deactivate' : 'Activate'}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-2 gap-2 p-2.5 rounded-md bg-muted/40 border text-xs">
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase font-semibold block">
                    Recorded Invoices
                  </span>
                  <span className="font-bold font-mono text-foreground">
                    {vendor.expense_count} Payments
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase font-semibold block">
                    Total Paid
                  </span>
                  <span className="font-bold font-mono text-emerald-600">
                    {formatCurrency(vendor.total_amount_paid || 0)}
                  </span>
                </div>
              </div>

              {/* Action Button */}
              <Button
                variant="outline"
                size="sm"
                className="w-full text-xs h-8 font-semibold gap-1.5 text-foreground hover:bg-muted"
                onClick={() => {
                  setSelectedVendor(vendor)
                  setDetailSheetOpen(true)
                }}
              >
                <Eye className="size-3.5 text-indigo-500" />
                View Payment History
              </Button>
            </div>
          ))}
        </div>
      ) : (
        /* Table View */
        <div className="border rounded-lg overflow-hidden bg-card shadow-2xs">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs font-semibold h-10">Vendor / Payee Name</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right">Invoices / Payments</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right">Total Paid (₹)</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-center">Status</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right w-[60px]">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredVendors.map((vendor) => (
                <TableRow key={vendor.id} className="hover:bg-muted/40 text-xs">
                  <TableCell className="font-semibold text-foreground">
                    <div className="flex items-center gap-2">
                      <Store className="size-3.5 text-indigo-500" />
                      <span>{vendor.name}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono font-medium text-foreground">
                    {vendor.expense_count}
                  </TableCell>
                  <TableCell className="text-right font-mono font-bold text-emerald-600">
                    {formatCurrency(vendor.total_amount_paid || 0)}
                  </TableCell>
                  <TableCell className="text-center">
                    <Badge
                      className={
                        vendor.status === 'active'
                          ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20 text-[10px]'
                          : 'bg-muted text-muted-foreground text-[10px]'
                      }
                    >
                      {vendor.status.toUpperCase()}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="size-7 p-0"
                      onClick={() => {
                        setSelectedVendor(vendor)
                        setDetailSheetOpen(true)
                      }}
                    >
                      <Eye className="size-4 text-indigo-500" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Vendor Transaction History Detail Sheet */}
      <VendorDetailSheet
        vendor={selectedVendor}
        open={detailSheetOpen}
        onOpenChange={setDetailSheetOpen}
      />

      {/* Create / Edit Dialog */}
      <CreateVendorDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        vendorToEdit={vendorToEdit}
        onSuccess={loadVendors}
      />
    </div>
  )
}
