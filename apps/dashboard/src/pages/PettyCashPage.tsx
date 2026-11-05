import * as React from 'react'
import {
  Wallet,
  Plus,
  ArrowLeftRight,
  Search,
  Download,
  Building2,
  User,
  Grid,
  List,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Receipt,
  CheckCircle2,
  Clock,
  Smartphone,
} from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { KpiCard } from '@/components/ui/kpi-card'
import { BulkActionBar } from '@/components/ui/bulk-action-bar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import { RecordVoucherDialog } from '@/components/petty-cash/record-voucher-dialog'
import { ReplenishFloatDialog } from '@/components/petty-cash/replenish-float-dialog'
import { CashBoxDetailSheet } from '@/components/petty-cash/cash-box-detail-sheet'

export interface SiteCashBoxItem {
  id: string
  name: string
  opening_balance: number
  current_balance: number
  disbursed_month: number
  custodian_name: string
  project_id?: string
  project_name: string
  site_id?: string
  site_name?: string
  status: 'active' | 'inactive'
}

export interface PettyCashVoucherItem {
  id: string
  voucher_number: string
  cash_box_id: string
  cash_box_name: string
  amount: number
  category: string
  vendor_name: string
  description: string
  date: string
  custodian_name: string
  project_name: string
  status: 'verified' | 'pending'
  source: string
}

type SortField = 'date' | 'amount' | 'voucher_number'
type SortOrder = 'asc' | 'desc'

import { fetchAccountsApi, fetchVouchersApi } from '@/lib/api'
import { toLocalISODate } from '@/lib/utils'

export default function PettyCashPage() {
  const { scope } = useScope()

  const [cashBoxes, setCashBoxes] = React.useState<SiteCashBoxItem[]>([])
  const [vouchers, setVouchers] = React.useState<PettyCashVoucherItem[]>([])

  const loadBackendPettyCash = React.useCallback(async () => {
    try {
      const [data, voucherData] = await Promise.all([
        fetchAccountsApi(),
        fetchVouchersApi().catch(() => []),
      ])
      if (Array.isArray(data)) {
        const pettyBoxes = data.filter((a: any) => a.account_type === 'employee_advance' || a.account_type === 'cash' || a.account_type === 'petty_cash')
        const mappedBoxes: SiteCashBoxItem[] = pettyBoxes.map((b: any, idx: number) => ({
          id: String(b.id) || `cb_real_${idx}`,
          name: b.name || 'Site Float',
          opening_balance: parseFloat(b.opening_balance) || 0,
          current_balance: parseFloat(b.current_balance) || parseFloat(b.opening_balance) || 0,
          disbursed_month: 0,
          custodian_name: b.custodian_name || 'Site Supervisor',
          project_id: b.project_id ? String(b.project_id) : undefined,
          project_name: 'Project Site',
          site_id: b.site_id ? String(b.site_id) : undefined,
          site_name: b.site_name,
          status: 'active',
        }))
        setCashBoxes(mappedBoxes)
      }
      if (Array.isArray(voucherData)) {
        const mappedVouchers: PettyCashVoucherItem[] = voucherData.map((v: any) => ({
          id: String(v.id),
          voucher_number: `VCH-${String(v.id).slice(0, 4).toUpperCase()}`,
          cash_box_id: String(v.from_account_id || ''),
          cash_box_name: 'Site Cash Box',
          amount: parseFloat(v.amount) || 0,
          category: v.description || 'General Expense',
          category_name: v.description || 'General Expense',
          vendor_name: v.source_type || 'Direct Payee',
          description: v.description || 'Petty Cash Voucher',
          date: v.occurred_date || toLocalISODate(),
          custodian_name: 'Site Supervisor',
          project_name: 'Project Site',
          status: 'verified',
          source: 'WhatsApp Assistant',
          receipt_url: undefined,
        }))
        setVouchers(mappedVouchers)
      }
    } catch (err) {
      console.warn('Live backend petty cash fetch error:', err)
      setCashBoxes([])
      setVouchers([])
    }
  }, [])

  React.useEffect(() => {
    loadBackendPettyCash()
  }, [loadBackendPettyCash, scope])

  const [search, setSearch] = React.useState('')
  const [categoryFilter, setCategoryFilter] = React.useState('ALL')
  const [statusFilter, setStatusFilter] = React.useState('ALL')
  const [viewMode, setViewMode] = React.useState<'grid' | 'table'>('grid')

  // Selection state for bulk actions
  const [selectedIds, setSelectedIds] = React.useState<string[]>([])

  // Sort & Pagination
  const [sortField, setSortField] = React.useState<SortField>('date')
  const [sortOrder, setSortOrder] = React.useState<SortOrder>('desc')
  const [currentPage, setCurrentPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState(10)

  // Dialog & Sheet states
  const [recordDialogOpen, setRecordDialogOpen] = React.useState(false)
  const [replenishDialogOpen, setReplenishDialogOpen] = React.useState(false)
  const [selectedCashBox, setSelectedCashBox] = React.useState<SiteCashBoxItem | null>(null)
  const [sheetOpen, setSheetOpen] = React.useState(false)

  // Scope-aware Cash Box filtering
  const scopedCashBoxes = React.useMemo(() => {
    return cashBoxes.filter((box) => {
      if (scope.mode === 'portfolio') return true
      if (scope.mode === 'project') return box.project_id === scope.projectId
      if (scope.mode === 'site') return box.project_id === scope.projectId || box.site_id === scope.siteId
      return true
    })
  }, [cashBoxes, scope])

  // Filtered & Sorted Vouchers
  const filteredVouchers = React.useMemo(() => {
    return vouchers
      .filter((vch) => {
        const matchesSearch =
          vch.voucher_number.toLowerCase().includes(search.toLowerCase()) ||
          vch.description.toLowerCase().includes(search.toLowerCase()) ||
          vch.vendor_name.toLowerCase().includes(search.toLowerCase()) ||
          vch.custodian_name.toLowerCase().includes(search.toLowerCase())

        if (!matchesSearch) return false
        if (categoryFilter !== 'ALL' && vch.category !== categoryFilter) return false
        if (statusFilter !== 'ALL' && vch.status !== statusFilter) return false

        return true
      })
      .sort((a, b) => {
        const modifier = sortOrder === 'asc' ? 1 : -1
        if (sortField === 'amount') return (a.amount - b.amount) * modifier
        if (sortField === 'date') return a.date.localeCompare(b.date) * modifier
        if (sortField === 'voucher_number') return a.voucher_number.localeCompare(b.voucher_number) * modifier
        return 0
      })
  }, [vouchers, search, categoryFilter, statusFilter, sortField, sortOrder])

  // Pagination
  const totalPages = Math.ceil(filteredVouchers.length / pageSize) || 1
  const paginatedVouchers = React.useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredVouchers.slice(start, start + pageSize)
  }, [filteredVouchers, currentPage, pageSize])

  // Summary Metrics
  const metrics = React.useMemo(() => {
    const activeFloat = scopedCashBoxes.reduce((acc, curr) => acc + curr.current_balance, 0)
    const monthlyDisbursed = scopedCashBoxes.reduce((acc, curr) => acc + curr.disbursed_month, 0)
    const lowBalanceCount = scopedCashBoxes.filter((b) => b.current_balance < 50000).length
    const pendingVouchersCount = vouchers.filter((v) => v.status === 'pending').length

    return {
      activeFloat,
      monthlyDisbursed,
      lowBalanceCount,
      pendingVouchersCount,
    }
  }, [scopedCashBoxes, vouchers])

  const handleVoucherCreated = () => {
    // The dialog now records a real expense (paid from the cash box account)
    // via the backend -- reload real vouchers/balances rather than
    // fabricating a local optimistic entry we can't accurately predict
    // (the backend resolves the real category/vendor/expense id).
    loadBackendPettyCash()
  }

  const handleReplenishCompleted = (boxId: string, amount: number) => {
    setCashBoxes((prev) =>
      prev.map((box) => {
        if (box.id === boxId) {
          return {
            ...box,
            current_balance: box.current_balance + amount,
          }
        }
        return box
      })
    )
  }

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortOrder('desc')
    }
  }

  const isAllSelected = paginatedVouchers.length > 0 && paginatedVouchers.every((e) => selectedIds.includes(e.id))

  const toggleSelectAll = () => {
    if (isAllSelected) {
      setSelectedIds([])
    } else {
      setSelectedIds(paginatedVouchers.map((e) => e.id))
    }
  }

  const toggleSelectRow = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    )
  }

  const scopeLabel = React.useMemo(() => {
    if (scope.mode === 'portfolio') return 'all projects'
    if (scope.mode === 'project') return `${scope.projectName}`
    return `${scope.projectName} / ${scope.siteName}`
  }, [scope])

  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(val)
  }

  return (
    <div className="flex flex-col gap-4 w-full max-w-full relative pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3.5">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Petty cash</h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 text-xs font-semibold text-emerald-600 border-emerald-500/30 hover:bg-emerald-500/10"
            onClick={() => setReplenishDialogOpen(true)}
          >
            <ArrowLeftRight className="size-3.5" />
            Replenish Float
          </Button>
          <Button
            size="sm"
            className="h-8 gap-1.5 text-xs font-bold shadow-2xs"
            onClick={() => setRecordDialogOpen(true)}
          >
            <Plus className="size-4" />
            Record Cash Voucher
          </Button>
        </div>
      </div>

      {/* Executive KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          title="Cash at sites"
          value={<span>{formatCurrency(metrics.activeFloat)}</span>}
          description="Total active cash in hand"
          icon={<Wallet  />}
        />
        <KpiCard
          title="Paid out this month"
          value={<span>{formatCurrency(metrics.monthlyDisbursed)}</span>}
          description="Vouchers paid this month"
          icon={<Receipt  />}
        />
        <KpiCard
          title="Sites low on cash"
          value={
            <span className={metrics.lowBalanceCount > 0 ? 'text-rose-600 dark:text-rose-400' : 'text-foreground'}>
              {metrics.lowBalanceCount} Sites
            </span>
          }
          description="Float threshold alerts (< ₹50k)"
          icon={<AlertTriangle className={metrics.lowBalanceCount > 0 ? 'text-rose-500' : 'text-muted-foreground'} />}
        />
        <KpiCard
          title="Vouchers to check"
          value={<span>{metrics.pendingVouchersCount} Vouchers</span>}
          description="Pending audit verification"
          icon={<Clock  />}
        />
      </div>

      {/* Toolbar & View Mode Switcher */}
      <div className="flex flex-col sm:flex-row gap-2.5 items-center justify-between border border-border/80 p-2.5 rounded-lg bg-card/40">
        <div className="flex flex-wrap gap-2 w-full sm:w-auto flex-1 items-center">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <Input
              placeholder="Search vouchers, custodians, vendor..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-9 text-xs"
            />
          </div>

          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger className="h-9 text-xs w-full sm:w-44">
              <SelectValue placeholder="All Categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Categories</SelectItem>
              <SelectItem value="Fuel & Logistics">Fuel & Logistics</SelectItem>
              <SelectItem value="Site Refreshments & Tea">Site Refreshments & Tea</SelectItem>
              <SelectItem value="Hardware & Small Tools">Hardware & Small Tools</SelectItem>
              <SelectItem value="Emergency Repairs">Emergency Repairs</SelectItem>
            </SelectContent>
          </Select>

          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-9 text-xs w-full sm:w-36">
              <SelectValue placeholder="All Statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Statuses</SelectItem>
              <SelectItem value="verified">Verified Only</SelectItem>
              <SelectItem value="pending">Pending Audit</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* View Switcher */}
        <div className="flex items-center gap-1 bg-muted p-1 rounded-md">
          <Button
            size="sm"
            variant={viewMode === 'grid' ? 'default' : 'ghost'}
            className="h-7 px-2.5 text-xs gap-1"
            onClick={() => setViewMode('grid')}
          >
            <Grid className="size-3.5" />
            Site Boxes
          </Button>
          <Button
            size="sm"
            variant={viewMode === 'table' ? 'default' : 'ghost'}
            className="h-7 px-2.5 text-xs gap-1"
            onClick={() => setViewMode('table')}
          >
            <List className="size-3.5" />
            Voucher Ledger
          </Button>
        </div>
      </div>

      {/* Main Content (Site Cash Box Cards vs Voucher Table) */}
      {viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {scopedCashBoxes.length === 0 ? (
            <div className="col-span-full h-32 flex items-center justify-center border rounded-lg text-xs text-muted-foreground">
              No site petty cash boxes match your criteria for {scopeLabel}.
            </div>
          ) : (
            scopedCashBoxes.map((box) => {
              const isLow = box.current_balance < 50000
              const percentageLeft = Math.round((box.current_balance / box.opening_balance) * 100)
              return (
                <Card
                  key={box.id}
                  className={`hover:border-amber-500/50 transition-all duration-200 cursor-pointer group relative overflow-hidden bg-gradient-to-br from-card via-card to-amber-500/5 ${isLow ? 'border-rose-500/40 shadow-xs' : ''}`}
                  onClick={() => {
                    setSelectedCashBox(box)
                    setSheetOpen(true)
                  }}
                >
                  <div className="p-4 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <Badge className="bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20 text-[10px]">
                          Site Cash Float
                        </Badge>
                        {isLow && (
                          <Badge className="bg-rose-500/15 text-rose-700 dark:text-rose-400 border-rose-500/20 text-[10px] gap-1">
                            <AlertTriangle className="size-3" /> Low Balance
                          </Badge>
                        )}
                      </div>
                      <Badge variant="outline" className="text-[10px] font-mono">
                        {box.project_name}
                      </Badge>
                    </div>

                    <div>
                      <h3 className="font-bold text-sm text-foreground group-hover:text-amber-600 transition-colors">
                        {box.name}
                      </h3>
                      {box.site_name && (
                        <span className="text-xs font-medium text-muted-foreground flex items-center gap-1 mt-0.5">
                          <Building2 className="size-3 text-amber-500" />
                          {box.site_name}
                        </span>
                      )}
                    </div>

                    {/* Progress Bar */}
                    <div className="space-y-1">
                      <div className="flex justify-between text-[10px] font-mono text-muted-foreground">
                        <span>Float Remaining</span>
                        <span>{percentageLeft}%</span>
                      </div>
                      <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${isLow ? 'bg-rose-500' : 'bg-amber-500'}`}
                          style={{ width: `${Math.min(100, percentageLeft)}%` }}
                        />
                      </div>
                    </div>

                    <div className="pt-2 border-t flex items-end justify-between">
                      <div>
                        <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold block">
                          Current Cash Balance
                        </span>
                        <span className={`text-xl font-bold font-mono tracking-tight ${isLow ? 'text-rose-600 dark:text-rose-400' : 'text-amber-600 dark:text-amber-400'}`}>
                          {formatCurrency(box.current_balance)}
                        </span>
                      </div>

                      <div className="flex items-center gap-1 text-[11px] text-muted-foreground bg-muted/40 px-2 py-1 rounded">
                        <User className="size-3 text-amber-500" />
                        <span className="truncate max-w-[100px]">{box.custodian_name}</span>
                      </div>
                    </div>
                  </div>
                </Card>
              )
            })
          )}
        </div>
      ) : (
        /* Table View: Voucher Ledger */
        <div className="border rounded-lg overflow-hidden bg-card shadow-2xs">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[40px] px-3">
                  <input
                    type="checkbox"
                    checked={isAllSelected}
                    onChange={toggleSelectAll}
                    className="size-4 rounded border-border text-amber-600 focus:ring-amber-500 cursor-pointer accent-amber-600"
                  />
                </TableHead>
                <TableHead
                  className="text-xs font-semibold h-10 cursor-pointer select-none"
                  onClick={() => toggleSort('voucher_number')}
                >
                  Voucher # {sortField === 'voucher_number' ? (sortOrder === 'asc' ? '↑' : '↓') : ''}
                </TableHead>
                <TableHead
                  className="text-xs font-semibold h-10 cursor-pointer select-none"
                  onClick={() => toggleSort('date')}
                >
                  Date {sortField === 'date' ? (sortOrder === 'asc' ? '↑' : '↓') : ''}
                </TableHead>
                <TableHead className="text-xs font-semibold h-10">Category & Description</TableHead>
                <TableHead className="text-xs font-semibold h-10">Payee / Vendor</TableHead>
                <TableHead className="text-xs font-semibold h-10">Cash Box Float</TableHead>
                <TableHead
                  className="text-xs font-semibold h-10 text-right cursor-pointer select-none"
                  onClick={() => toggleSort('amount')}
                >
                  Amount (₹) {sortField === 'amount' ? (sortOrder === 'asc' ? '↑' : '↓') : ''}
                </TableHead>
                <TableHead className="text-xs font-semibold h-10 text-center">Status</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right w-[50px]">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedVouchers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="h-32 text-center text-xs text-muted-foreground">
                    No petty cash vouchers found.
                  </TableCell>
                </TableRow>
              ) : (
                paginatedVouchers.map((vch) => {
                  const isSelected = selectedIds.includes(vch.id)
                  return (
                    <TableRow
                      key={vch.id}
                      className={`hover:bg-muted/40 cursor-pointer transition-colors ${isSelected ? 'bg-amber-500/5' : ''}`}
                    >
                      <TableCell className="px-3" onClick={(e) => toggleSelectRow(vch.id, e)}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {}}
                          className="size-4 rounded border-border text-amber-600 focus:ring-amber-500 cursor-pointer accent-amber-600"
                        />
                      </TableCell>
                      <TableCell className="font-mono font-bold text-xs text-foreground">
                        {vch.voucher_number}
                      </TableCell>
                      <TableCell className="text-xs font-mono text-muted-foreground">{vch.date}</TableCell>
                      <TableCell className="text-xs">
                        <div className="font-semibold text-foreground">{vch.description}</div>
                        <span className="text-[10px] text-muted-foreground font-mono">{vch.category}</span>
                      </TableCell>
                      <TableCell className="text-xs text-foreground font-medium">{vch.vendor_name}</TableCell>
                      <TableCell className="text-xs text-muted-foreground truncate max-w-[140px]">
                        {vch.cash_box_name}
                      </TableCell>
                      <TableCell className="text-xs font-mono font-bold text-right tabular-nums text-foreground">
                        {formatCurrency(vch.amount)}
                      </TableCell>
                      <TableCell className="text-center">
                        {vch.status === 'verified' ? (
                          <Badge className="bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[10px] font-semibold gap-1">
                            <CheckCircle2 className="size-3" /> Verified
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-[10px] text-amber-600 border-amber-500/30 gap-1">
                            <Clock className="size-3" /> Pending Audit
                          </Badge>
                        )}
                        {vch.source === 'WhatsApp Assistant' && (
                          <span className="text-[9px] text-emerald-600 block font-medium flex items-center justify-center gap-0.5 mt-0.5">
                            <Smartphone className="size-2.5" /> WhatsApp
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>

          {/* Pagination */}
          <div className="flex items-center justify-between px-3 py-2 border-t bg-muted/20 text-xs">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Rows per page:</span>
              <Select value={pageSize.toString()} onValueChange={(val) => setPageSize(Number(val))}>
                <SelectTrigger className="h-7 text-xs w-16">
                  <SelectValue placeholder="10" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="5">5</SelectItem>
                  <SelectItem value="10">10</SelectItem>
                  <SelectItem value="25">25</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-3">
              <span className="text-muted-foreground font-mono">
                Page {currentPage} of {totalPages}
              </span>
              <div className="flex gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 size-7 p-0"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((p) => p - 1)}
                >
                  <ChevronLeft className="size-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 size-7 p-0"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage((p) => p + 1)}
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Floating Bulk Action Bar */}
      <BulkActionBar selectedCount={selectedIds.length} onClear={() => setSelectedIds([])}>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs gap-1.5 font-semibold text-emerald-600 border-emerald-500/40 hover:bg-emerald-500/10"
          onClick={() => {
            setVouchers((prev) =>
              prev.map((v) => (selectedIds.includes(v.id) ? { ...v, status: 'verified' } : v))
            )
            setSelectedIds([])
          }}
        >
          <CheckCircle2 className="size-3.5" />
          Approve Selected ({selectedIds.length})
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs gap-1.5 font-semibold"
          onClick={() => {
            const targetVouchers = vouchers.filter((v) => selectedIds.includes(v.id))
            const headers = ['Voucher ID', 'Voucher Number', 'Cash Box', 'Project', 'Custodian', 'Category', 'Amount (INR)', 'Date', 'Status', 'Description', 'Source']
            const rows = targetVouchers.map((v) => [
              v.id,
              `"${v.voucher_number}"`,
              `"${v.cash_box_name}"`,
              `"${v.project_name}"`,
              `"${v.custodian_name}"`,
              `"${v.category}"`,
              v.amount,
              v.date,
              v.status,
              `"${v.description}"`,
              v.source,
            ])
            const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map((e) => e.join(','))].join('\n')
            const link = document.createElement('a')
            link.setAttribute('href', encodeURI(csvContent))
            link.setAttribute('download', `petty_cash_vouchers_${new Date().toISOString().slice(0, 10)}.csv`)
            document.body.appendChild(link)
            link.click()
            document.body.removeChild(link)
          }}
        >
          <Download className="size-3.5" />
          Export Vouchers
        </Button>
      </BulkActionBar>

      {/* Modals & Sheet */}
      <RecordVoucherDialog
        open={recordDialogOpen}
        onOpenChange={setRecordDialogOpen}
        cashBoxes={cashBoxes}
        onVoucherCreated={handleVoucherCreated}
      />

      <ReplenishFloatDialog
        open={replenishDialogOpen}
        onOpenChange={setReplenishDialogOpen}
        cashBoxes={cashBoxes}
        onReplenishCompleted={handleReplenishCompleted}
      />

      <CashBoxDetailSheet
        cashBox={selectedCashBox}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        onReplenishClick={() => setReplenishDialogOpen(true)}
      />
    </div>
  )
}
