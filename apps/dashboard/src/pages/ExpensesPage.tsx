import * as React from 'react'
import { exportCsv } from '@/lib/export'
import {
  DollarSign,
  Plus,
  Search,
  Download,
  CheckCircle2,
  AlertCircle,
  MessageSquare,
  Laptop,
  MoreVertical,
  Eye,
  Receipt,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Calendar,
  Image as ImageIcon,
} from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { KpiCard } from '@/components/ui/kpi-card'
import { BulkActionBar } from '@/components/ui/bulk-action-bar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useSearchParams } from 'react-router-dom'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { RecordExpenseDialog } from '@/components/expenses/record-expense-dialog'
import { ExpenseDetailSheet } from '@/components/expenses/expense-detail-sheet'
import { AccountDetailSheet } from '@/components/accounts/account-detail-sheet'
import { VendorDetailSheet } from '@/components/vendors/vendor-detail-sheet'
import { CategoryDetailSheet } from '@/components/categories/category-detail-sheet'
import { CustodianProfileSheet } from '@/components/accounts/custodian-profile-sheet'
import { WhatsAppTraceModal } from '@/components/whatsapp/whatsapp-trace-modal'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface ExpenseItem {
  id: string
  expense_number: string
  amount: number
  currency: string
  category_name: string
  category_id: string
  description: string
  vendor_name: string
  occurred_date: string
  payment_status: 'paid' | 'partially_paid' | 'unpaid'
  workflow_status: 'confirmed' | 'pending' | 'reversed'
  source: 'whatsapp' | 'web'
  project_name: string
  site_name: string
  payment_method?: string
  tax_rate?: number | null
  tax_amount?: number | null
  is_tax_inclusive?: boolean
}

type SortField = 'date' | 'amount' | 'number' | 'category'
type SortOrder = 'asc' | 'desc'

import { fetchExpensesApi, reverseExpenseApi, fetchAllExpenseAttachmentsApi } from '@/lib/api'
import { useToast } from '@/components/ui/toast-notification'
import { toLocalISODate } from '@/lib/utils'

export default function ExpensesPage() {
  const { scope } = useScope()
  const toast = useToast()

  const [expenses, setExpenses] = React.useState<ExpenseItem[]>([])
  const [search, setSearch] = React.useState('')
  const [categoryFilter, setCategoryFilter] = React.useState('ALL')
  const [paymentStatusFilter, setPaymentStatusFilter] = React.useState('ALL')
  const [sourceFilter, setSourceFilter] = React.useState('ALL')
  const [datePreset, setDatePreset] = React.useState('ALL')
  // expense_id -> first receipt's presigned URL. Fetched once alongside the
  // expenses list (one batched call, not one per row) -- see
  // GET /expenses/attachments in backend/src/mesiri/domains/expenses/router.py.
  const [receiptUrlByExpenseId, setReceiptUrlByExpenseId] = React.useState<Record<string, string>>({})

  React.useEffect(() => {
    let active = true
    async function loadBackendExpenses() {
      try {
        const rawData = await fetchExpensesApi({
          project_id: scope.mode !== 'portfolio' ? scope.projectId : undefined,
          site_id: scope.mode === 'site' ? scope.siteId : undefined,
        })
        if (active && Array.isArray(rawData)) {
          const mapped: ExpenseItem[] = rawData.map((item: any, idx: number) => ({
            id: String(item.id) || `exp_real_${idx}`,
            expense_number: `EXP-${String(item.id || '').slice(0, 4).toUpperCase() || String(1000 + idx)}`,
            amount: parseFloat(item.amount) || 0,
            currency: item.currency || 'INR',
            category_name: item.category_name || item.category_id || 'General Expense',
            category_id: String(item.category_id || 'general'),
            description: item.description || 'Recorded Expense',
            vendor_name: 'Direct Payee',
            occurred_date: item.occurred_date || toLocalISODate(),
            payment_status: item.payment_status === 'paid' ? 'paid' : item.payment_status === 'partially_paid' ? 'partially_paid' : 'unpaid',
            workflow_status: item.workflow_status === 'reversed' ? 'reversed' : item.workflow_status === 'pending' ? 'pending' : 'confirmed',
            source: item.source === 'whatsapp' ? 'whatsapp' : 'web',
            project_name: scope.mode === 'portfolio' ? 'Org Wide' : scope.projectName,
            site_name: scope.mode === 'site' ? scope.siteName : 'All Sites',
          }))
          setExpenses(mapped)
        }
      } catch (err) {
        console.warn('Live backend expenses fetch error:', err)
        if (active) setExpenses([])
      }
    }
    async function loadReceiptUrls() {
      try {
        const attachments = await fetchAllExpenseAttachmentsApi({
          project_id: scope.mode !== 'portfolio' ? scope.projectId : undefined,
          site_id: scope.mode === 'site' ? scope.siteId : undefined,
          limit: 200,
        })
        if (!active) return
        const byExpenseId: Record<string, string> = {}
        for (const a of attachments) {
          // First attachment wins when an expense has more than one -- the
          // lightbox only shows one image today.
          if (!byExpenseId[a.expense_id]) byExpenseId[a.expense_id] = a.url
        }
        setReceiptUrlByExpenseId(byExpenseId)
      } catch (err) {
        console.warn('Live backend receipt attachments fetch error:', err)
        if (active) setReceiptUrlByExpenseId({})
      }
    }
    loadBackendExpenses()
    loadReceiptUrls()
    return () => {
      active = false
    }
  }, [scope])

  // Selection & Bulk Action state
  const [selectedIds, setSelectedIds] = React.useState<string[]>([])

  // Sorting state
  const [sortField, setSortField] = React.useState<SortField>('date')
  const [sortOrder, setSortOrder] = React.useState<SortOrder>('desc')

  // Pagination state
  const [currentPage, setCurrentPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState(10)

  // Dialog & Sheet state
  const [searchParams] = useSearchParams()
  const [recordDialogOpen, setRecordDialogOpen] = React.useState(false)
  const [selectedExpense, setSelectedExpense] = React.useState<ExpenseItem | null>(null)
  const [sheetOpen, setSheetOpen] = React.useState(false)
  const [previewReceiptUrl, setPreviewReceiptUrl] = React.useState<string | null>(null)

  // Connected Sub-sheet States
  const [accountSheetId, setAccountSheetId] = React.useState<string | null>(null)
  const [vendorSheetId, setVendorSheetId] = React.useState<string | null>(null)
  const [categorySheetId, setCategorySheetId] = React.useState<string | null>(null)
  const [custodianSheetId, setCustodianSheetId] = React.useState<string | null>(null)
  const [whatsappTraceId, setWhatsappTraceId] = React.useState<string | null>(null)

  React.useEffect(() => {
    const paramId = searchParams.get('id')
    const paramCatId = searchParams.get('category_id')
    const paramVendorId = searchParams.get('vendor_id')

    if (paramCatId) {
      setCategoryFilter(paramCatId)
    }
    if (paramVendorId) {
      setSearch(paramVendorId)
    }
    if (paramId && expenses.length > 0) {
      const match = expenses.find((e) => e.id === paramId || e.expense_number === paramId)
      if (match) {
        setSelectedExpense(match)
        setSheetOpen(true)
      }
    }
  }, [searchParams, expenses])

  const handleExpenseCreated = (newExpense: ExpenseItem) => {
    setExpenses((prev) => [newExpense, ...prev])
  }

  // Handle Sort Toggle
  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortOrder('desc')
    }
  }

  // Filtered & Sorted expenses
  const filteredExpenses = React.useMemo(() => {
    const today = toLocalISODate()

    return expenses
      .filter((item) => {
        const matchesSearch =
          item.expense_number.toLowerCase().includes(search.toLowerCase()) ||
          item.description.toLowerCase().includes(search.toLowerCase()) ||
          item.vendor_name.toLowerCase().includes(search.toLowerCase()) ||
          item.category_name.toLowerCase().includes(search.toLowerCase())

        if (!matchesSearch) return false

        if (categoryFilter !== 'ALL' && item.category_id !== categoryFilter) return false
        if (paymentStatusFilter !== 'ALL' && item.payment_status !== paymentStatusFilter) return false
        if (sourceFilter !== 'ALL' && item.source !== sourceFilter) return false

        // Date Preset filter
        if (datePreset === 'TODAY' && item.occurred_date !== today) return false
        if (datePreset === 'THIS_MONTH') {
          const itemMonth = item.occurred_date.substring(0, 7)
          const currentMonth = today.substring(0, 7)
          if (itemMonth !== currentMonth) return false
        }

        return true
      })
      .sort((a, b) => {
        let modifier = sortOrder === 'asc' ? 1 : -1
        if (sortField === 'date') return a.occurred_date.localeCompare(b.occurred_date) * modifier
        if (sortField === 'amount') return (a.amount - b.amount) * modifier
        if (sortField === 'number') return a.expense_number.localeCompare(b.expense_number) * modifier
        if (sortField === 'category') return a.category_name.localeCompare(b.category_name) * modifier
        return 0
      })
  }, [expenses, search, categoryFilter, paymentStatusFilter, sourceFilter, datePreset, sortField, sortOrder])

  // Pagination calculation
  const totalPages = Math.ceil(filteredExpenses.length / pageSize) || 1
  const paginatedExpenses = React.useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredExpenses.slice(start, start + pageSize)
  }, [filteredExpenses, currentPage, pageSize])

  // Summary Metrics calculation
  const metrics = React.useMemo(() => {
    const totalSpent = expenses.reduce((acc, curr) => acc + curr.amount, 0)
    const unpaidAmount = expenses
      .filter((e) => e.payment_status === 'unpaid')
      .reduce((acc, curr) => acc + curr.amount, 0)
    const paidAmount = expenses
      .filter((e) => e.payment_status === 'paid')
      .reduce((acc, curr) => acc + curr.amount, 0)
    const whatsappCount = expenses.filter((e) => e.source === 'whatsapp').length
    const webCount = expenses.filter((e) => e.source === 'web').length

    return {
      totalSpent,
      unpaidAmount,
      paidAmount,
      count: expenses.length,
      whatsappCount,
      webCount,
    }
  }, [expenses])

  // Filtered total sum
  const filteredSum = React.useMemo(() => {
    return filteredExpenses.reduce((acc, curr) => acc + curr.amount, 0)
  }, [filteredExpenses])

  // Bulk Selection Handlers
  const isAllSelected = paginatedExpenses.length > 0 && paginatedExpenses.every((e) => selectedIds.includes(e.id))
  
  const toggleSelectAll = () => {
    if (isAllSelected) {
      setSelectedIds([])
    } else {
      setSelectedIds(paginatedExpenses.map((e) => e.id))
    }
  }

  const toggleSelectRow = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    )
  }

  const handleBulkMarkAsPaid = () => {
    setExpenses((prev) =>
      prev.map((item) => (selectedIds.includes(item.id) ? { ...item, payment_status: 'paid' as const } : item))
    )
    setSelectedIds([])
  }

  const handleVoidExpense = async (id: string, expenseNumber: string) => {
    if (!confirm(`Void expense ${expenseNumber}? This will reverse any associated payment entries in the ledger.`)) return
    try {
      await reverseExpenseApi(id)
      setExpenses((prev) =>
        prev.map((e) => (e.id === id ? { ...e, workflow_status: 'reversed' as const } : e))
      )
      toast.success(`Expense ${expenseNumber} voided`, 'Reversal entry posted to general ledger')
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.join(', ') : detail || err.message || 'Server connection error'
      toast.error('Failed to void expense', msg)
    }
  }

  const handleBulkVoid = async () => {
    if (!confirm(`Are you sure you want to void ${selectedIds.length} selected expenses?`)) return
    const idsToVoid = [...selectedIds]
    setSelectedIds([])
    let successCount = 0
    for (const id of idsToVoid) {
      try {
        await reverseExpenseApi(id)
        setExpenses((prev) =>
          prev.map((e) => (e.id === id ? { ...e, workflow_status: 'reversed' as const } : e))
        )
        successCount++
      } catch (err: any) {
        console.warn(`Failed to void expense ${id}:`, err)
      }
    }
    if (successCount > 0) {
      toast.success(`${successCount} expenses voided`, 'Reversal transactions recorded')
    }
  }

  // WEB-48: real exports (they used to only show "Exporting..." and download nothing).
  const exportRows = (rows: typeof expenses, name: string) =>
    exportCsv(
      name,
      ['Number', 'Date', 'Category', 'Vendor', 'Description', 'Amount', 'Payment', 'From'],
      rows.map((e) => [e.expense_number, e.occurred_date, e.category_name, e.vendor_name, e.description, e.amount, e.payment_status, e.source]),
    )
  const handleBulkExport = () => exportRows(expenses.filter((e) => selectedIds.includes(e.id)), 'expenses-selected.csv')


  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(val)
  }

  const renderSortIcon = (field: SortField) => {
    if (sortField !== field) return <ArrowUpDown className="size-3 text-muted-foreground/60 ml-1 inline" />
    return sortOrder === 'asc' ? (
      <ArrowUp className="size-3 text-emerald-500 ml-1 inline" />
    ) : (
      <ArrowDown className="size-3 text-emerald-500 ml-1 inline" />
    )
  }

  return (
    <div className="flex flex-col gap-4 w-full max-w-full relative pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3.5">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Expenses</h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 text-xs font-medium"
            disabled={filteredExpenses.length === 0}
            onClick={() => exportRows(filteredExpenses, 'expenses.csv')}
          >
            <Download className="size-3.5" />
            Export CSV
          </Button>
          <Button
            size="sm"
            className="h-8 gap-1.5 text-xs font-bold shadow-2xs"
            onClick={() => setRecordDialogOpen(true)}
          >
            <Plus className="size-4" />
            Record Expense
          </Button>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          title="Total spent"
          value={<span>{formatCurrency(metrics.totalSpent)}</span>}
          description="Total recorded spend"
          icon={<Receipt  />}
        />
        <KpiCard
          title="Unpaid"
          value={<span>{formatCurrency(metrics.unpaidAmount)}</span>}
          description="Outstanding invoices"
          icon={<AlertCircle  />}
        />
        <KpiCard
          title="Paid"
          value={<span>{formatCurrency(metrics.paidAmount)}</span>}
          description="Paid disbursements"
          icon={<CheckCircle2  />}
        />
        <KpiCard
          title="Recorded"
          value={<span>{metrics.count} Entries</span>}
          description="WhatsApp & Web logs"
          icon={<MessageSquare  />}
        />
      </div>

      {/* Filter & Toolbar */}
      <div className="flex flex-col sm:flex-row gap-2.5 items-center justify-between border border-border/80 p-2.5 rounded-lg bg-card/40">
        <div className="flex flex-wrap gap-2 w-full sm:w-auto flex-1 items-center">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <Input
              placeholder="Search expenses, vendors, number..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-9 text-xs"
            />
          </div>

          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger className="h-9 text-xs w-full sm:w-40">
              <SelectValue placeholder="All Categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Categories</SelectItem>
              <SelectItem value="fuel">Fuel & Transportation</SelectItem>
              <SelectItem value="equipment">Equipment & Hire</SelectItem>
              <SelectItem value="labor">Labor & Wages</SelectItem>
              <SelectItem value="materials">Raw Materials</SelectItem>
              <SelectItem value="maintenance">Maintenance</SelectItem>
            </SelectContent>
          </Select>

          <Select value={datePreset} onValueChange={setDatePreset}>
            <SelectTrigger className="h-9 text-xs w-full sm:w-36">
              <Calendar className="size-3.5 mr-1 text-muted-foreground" />
              <SelectValue placeholder="All Dates" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Dates</SelectItem>
              <SelectItem value="TODAY">Today</SelectItem>
              <SelectItem value="THIS_MONTH">This Month</SelectItem>
            </SelectContent>
          </Select>

          <Select value={sourceFilter} onValueChange={setSourceFilter}>
            <SelectTrigger className="h-9 text-xs w-full sm:w-32">
              <SelectValue placeholder="All Sources" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Sources</SelectItem>
              <SelectItem value="whatsapp">WhatsApp</SelectItem>
              <SelectItem value="web">Web Dashboard</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Payment Status Tab Filter */}
        <Tabs value={paymentStatusFilter} onValueChange={setPaymentStatusFilter} className="w-full sm:w-auto">
          <TabsList className="h-9 text-xs grid grid-cols-4 w-full sm:w-auto">
            <TabsTrigger value="ALL" className="text-xs px-2.5">All</TabsTrigger>
            <TabsTrigger value="paid" className="text-xs px-2.5">Paid</TabsTrigger>
            <TabsTrigger value="partially_paid" className="text-xs px-2.5">Partial</TabsTrigger>
            <TabsTrigger value="unpaid" className="text-xs px-2.5">Unpaid</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {/* Filter Summary Banner */}
      <div className="flex items-center justify-between text-xs px-1 text-muted-foreground font-medium">
        <div>
          Showing <span className="text-foreground font-semibold">{filteredExpenses.length}</span> of {expenses.length} records
          {filteredExpenses.length !== expenses.length && (
            <span> • Filtered Total: <span className="font-mono text-emerald-600 dark:text-emerald-400 font-semibold">{formatCurrency(filteredSum)}</span></span>
          )}
        </div>
        {selectedIds.length > 0 && (
          <span className="text-emerald-600 font-semibold text-xs">
            {selectedIds.length} items checked
          </span>
        )}
      </div>

      {/* Main Expense Table */}
      <div className="border rounded-lg overflow-hidden bg-card shadow-2xs">
        <Table>
          <TableHeader className="bg-muted/40">
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[40px] px-3">
                <input
                  type="checkbox"
                  checked={isAllSelected}
                  onChange={toggleSelectAll}
                  className="size-4 rounded border-border text-emerald-600 focus:ring-emerald-500 cursor-pointer accent-emerald-600"
                  title="Select All"
                />
              </TableHead>
              <TableHead
                className="text-xs font-semibold h-10 w-[110px] cursor-pointer select-none"
                onClick={() => toggleSort('number')}
              >
                Expense # {renderSortIcon('number')}
              </TableHead>
              <TableHead
                className="text-xs font-semibold h-10 cursor-pointer select-none"
                onClick={() => toggleSort('date')}
              >
                Date {renderSortIcon('date')}
              </TableHead>
              <TableHead
                className="text-xs font-semibold h-10 cursor-pointer select-none"
                onClick={() => toggleSort('category')}
              >
                Category {renderSortIcon('category')}
              </TableHead>
              <TableHead className="text-xs font-semibold h-10">Description / Payee</TableHead>
              <TableHead className="text-xs font-semibold h-10">Channel</TableHead>
              <TableHead
                className="text-xs font-semibold h-10 text-right cursor-pointer select-none"
                onClick={() => toggleSort('amount')}
              >
                Amount (₹) {renderSortIcon('amount')}
              </TableHead>
              <TableHead className="text-xs font-semibold h-10 text-center">Status</TableHead>
              <TableHead className="text-xs font-semibold h-10 text-right w-[60px]">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {paginatedExpenses.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} className="h-32 text-center text-xs text-muted-foreground">
                  No expense records match your search or filter criteria.
                </TableCell>
              </TableRow>
            ) : (
              paginatedExpenses.map((row) => {
                const isSelected = selectedIds.includes(row.id)
                return (
                  <TableRow
                    key={row.id}
                    className={`hover:bg-muted/40 cursor-pointer transition-colors ${isSelected ? 'bg-emerald-500/5' : ''}`}
                    onClick={() => {
                      setSelectedExpense(row)
                      setSheetOpen(true)
                    }}
                  >
                    <TableCell className="px-3" onClick={(e) => toggleSelectRow(row.id, e)}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => {}}
                        className="size-4 rounded border-border text-emerald-600 focus:ring-emerald-500 cursor-pointer accent-emerald-600"
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs font-semibold text-foreground">
                      {row.expense_number}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                      {row.occurred_date}
                    </TableCell>
                    <TableCell className="text-xs font-medium">
                      <Badge
                        variant="outline"
                        onClick={(e) => {
                          e.stopPropagation()
                          setCategorySheetId(row.category_id || row.category_name)
                        }}
                        className="font-normal text-[11px] bg-background hover:border-indigo-500/50 hover:text-indigo-600 transition-colors cursor-pointer"
                      >
                        {row.category_name}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs">
                      <div className="font-medium text-foreground truncate max-w-[200px] flex items-center gap-1.5">
                        {row.description}
                        {receiptUrlByExpenseId[row.id] && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              setPreviewReceiptUrl(receiptUrlByExpenseId[row.id])
                            }}
                            className="text-muted-foreground hover:text-emerald-600"
                            title="View Receipt"
                          >
                            <ImageIcon className="size-3.5" />
                          </button>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          setVendorSheetId(row.vendor_name)
                        }}
                        className="text-[11px] text-muted-foreground hover:text-emerald-600 truncate transition-colors font-medium text-left"
                      >
                        {row.vendor_name}
                      </button>
                    </TableCell>
                    <TableCell className="text-xs">
                      {row.source === 'whatsapp' ? (
                        <Badge className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-[10px] gap-1 font-normal">
                          <MessageSquare className="size-3" />
                          WhatsApp
                        </Badge>
                      ) : (
                        <Badge className="bg-indigo-500/10 text-indigo-700 dark:text-indigo-400 border-indigo-500/20 text-[10px] gap-1 font-normal">
                          <Laptop className="size-3" />
                          Web
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs font-mono font-bold text-right tabular-nums text-foreground">
                      {formatCurrency(row.amount)}
                    </TableCell>
                    <TableCell className="text-center">
                      <Badge
                        className={
                          row.payment_status === 'paid'
                            ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[10px] font-semibold'
                            : row.payment_status === 'partially_paid'
                            ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300 text-[10px] font-semibold'
                            : 'bg-rose-500/15 text-rose-700 dark:text-rose-300 text-[10px] font-semibold'
                        }
                      >
                        {row.payment_status === 'paid'
                          ? 'Paid'
                          : row.payment_status === 'partially_paid'
                          ? 'Partial'
                          : 'Unpaid'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="size-7">
                            <MoreVertical className="size-4 text-muted-foreground" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="text-xs">
                          <DropdownMenuItem
                            onClick={() => {
                              setSelectedExpense(row)
                              setSheetOpen(true)
                            }}
                          >
                            <Eye className="size-3.5 mr-1.5" /> View Details
                          </DropdownMenuItem>
                          {row.payment_status !== 'paid' && (
                            <DropdownMenuItem
                              onClick={() => {
                                setSelectedExpense(row)
                                setSheetOpen(true)
                              }}
                            >
                              <DollarSign className="size-3.5 mr-1.5 text-emerald-500" /> Record Settlement
                            </DropdownMenuItem>
                          )}
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            className="text-rose-600"
                            onClick={() => handleVoidExpense(row.id, row.expense_number)}
                          >
                            <Trash2 className="size-3.5 mr-1.5" /> Void Expense
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>

        {/* Pagination Bar */}
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

      {/* Floating Bulk Action Bar */}
      <BulkActionBar selectedCount={selectedIds.length} onClear={() => setSelectedIds([])}>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs gap-1.5 font-semibold text-emerald-600 border-emerald-500/40 hover:bg-emerald-500/10"
          onClick={handleBulkMarkAsPaid}
        >
          <CheckCircle2 className="size-3.5" />
          Mark as Paid
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs gap-1.5 font-semibold"
          onClick={handleBulkExport}
        >
          <Download className="size-3.5" />
          Export Selected
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs gap-1.5 font-semibold text-rose-600 border-rose-500/40 hover:bg-rose-500/10"
          onClick={handleBulkVoid}
        >
          <Trash2 className="size-3.5" />
          Void Selected
        </Button>
      </BulkActionBar>

      {/* Receipt Image Lightbox Dialog */}
      <Dialog open={!!previewReceiptUrl} onOpenChange={() => setPreviewReceiptUrl(null)}>
        <DialogContent className="sm:max-w-[500px] p-2">
          <DialogHeader className="px-3 pt-2">
            <DialogTitle className="text-sm font-semibold flex items-center gap-1.5">
              <ImageIcon className="size-4 text-emerald-500" />
              Receipt / Invoice Attachment
            </DialogTitle>
          </DialogHeader>
          {previewReceiptUrl && (
            <div className="p-2 flex items-center justify-center bg-black/90 rounded-md overflow-hidden">
              <img
                src={previewReceiptUrl}
                alt="Receipt Attachment"
                className="max-h-[400px] w-auto object-contain rounded"
              />
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Dialogs & Sheets */}
      <RecordExpenseDialog
        open={recordDialogOpen}
        onOpenChange={setRecordDialogOpen}
        scope={scope}
        onExpenseCreated={handleExpenseCreated}
      />

      <ExpenseDetailSheet
        expense={
          selectedExpense
            ? {
                id: selectedExpense.id,
                amount: selectedExpense.amount,
                category_name: selectedExpense.category_name,
                category_id: selectedExpense.category_id,
                vendor_name: selectedExpense.vendor_name,
                status: selectedExpense.workflow_status,
                recorded_date: selectedExpense.occurred_date,
                payment_method: selectedExpense.payment_method,
                receipt_url: receiptUrlByExpenseId[selectedExpense.id],
                description: selectedExpense.description,
              }
            : null
        }
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        onOpenAccount={(accId) => setAccountSheetId(accId)}
        onOpenVendor={(venId) => setVendorSheetId(venId)}
        onOpenCategory={(catId) => setCategorySheetId(catId)}
        onOpenCustodian={(custodian) => setCustodianSheetId(custodian)}
        onOpenWhatsAppTrace={(traceId) => setWhatsappTraceId(traceId)}
      />

      <AccountDetailSheet
        open={!!accountSheetId}
        onOpenChange={(op) => !op && setAccountSheetId(null)}
        account={accountSheetId ? { id: accountSheetId, name: 'Money Account', account_type: 'bank', currency: 'INR', opening_balance: 0, current_balance: 0, status: 'active', created_at: '' } : null}
      />

      <VendorDetailSheet
        open={!!vendorSheetId}
        onOpenChange={(op) => !op && setVendorSheetId(null)}
        vendor={vendorSheetId ? { id: vendorSheetId, name: 'Vendor', status: 'active', expense_count: 0, total_amount_paid: 0 } : null}
      />

      <CategoryDetailSheet
        open={!!categorySheetId}
        onOpenChange={(op) => !op && setCategorySheetId(null)}
        category={categorySheetId ? { id: categorySheetId, code: 'CAT', name: 'Expense Category', status: 'active', total_amount_spent: 0, expense_count: 0 } : null}
      />

      <CustodianProfileSheet
        open={!!custodianSheetId}
        onOpenChange={(op) => !op && setCustodianSheetId(null)}
        custodianIdOrName={custodianSheetId}
        onOpenAccount={(accId) => setAccountSheetId(accId)}
      />

      <WhatsAppTraceModal
        open={!!whatsappTraceId}
        onOpenChange={(op) => !op && setWhatsappTraceId(null)}
        correlationId={whatsappTraceId}
      />
    </div>
  )
}
