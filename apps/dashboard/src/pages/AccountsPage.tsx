import * as React from 'react'
import { exportCsv } from '@/lib/export'
import {
  Landmark,
  Plus,
  ArrowLeftRight,
  Search,
  Download,
  Wallet,
  Building2,
  User,
  MoreVertical,
  Eye,
  Grid,
  List,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Trash2,
  Pencil,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { CreateAccountDialog } from '@/components/accounts/create-account-dialog'
import { TransferMoneyDialog } from '@/components/accounts/transfer-money-dialog'
import { RenameAccountDialog } from '@/components/accounts/rename-account-dialog'
import { AccountDetailSheet } from '@/components/accounts/account-detail-sheet'

export interface MoneyAccountItem {
  id: string
  name: string
  code?: string
  account_type: 'bank' | 'cash' | 'employee_advance' | 'other'
  currency: string
  opening_balance: number
  current_balance: number
  account_number_masked?: string
  custodian_name: string
  project_id?: string
  project_name: string
  site_id?: string
  site_name?: string
  scope_level: 'portfolio' | 'project' | 'site'
  status: 'active' | 'inactive'
  created_at: string
}

type SortField = 'name' | 'balance' | 'type'
type SortOrder = 'asc' | 'desc'

import { fetchAccountsApi, deleteAccountApi } from '@/lib/api'
import { useToast } from '@/components/ui/toast-notification'
import { toLocalISODate } from '@/lib/utils'

export default function AccountsPage() {
  const { scope } = useScope()
  const toast = useToast()

  const [accounts, setAccounts] = React.useState<MoneyAccountItem[]>([])
  const [search, setSearch] = React.useState('')
  const [typeFilter, setTypeFilter] = React.useState('ALL')
  const [statusFilter, setStatusFilter] = React.useState('ALL')
  const [viewMode, setViewMode] = React.useState<'grid' | 'table'>('grid')

  React.useEffect(() => {
    let active = true
    async function loadBackendAccounts() {
      try {
        const data = await fetchAccountsApi({
          project_id: scope.mode !== 'portfolio' ? scope.projectId : undefined,
          site_id: scope.mode === 'site' ? scope.siteId : undefined,
        })
        if (active && Array.isArray(data)) {
          const typeMap: Record<string, 'bank' | 'cash' | 'employee_advance' | 'other'> = {
            bank: 'bank',
            cash: 'cash',
            employee_advance: 'employee_advance',
            other: 'other',
            bank_account: 'bank',
            petty_cash: 'cash',
            corporate_card: 'other',
            digital_wallet: 'other',
          }
          const mapped: MoneyAccountItem[] = data.map((a: any) => ({
            id: String(a.id),
            name: a.name,
            account_type: typeMap[a.account_type] ?? 'bank',
            currency: a.currency || 'INR',
            opening_balance: parseFloat(a.opening_balance) || 0,
            current_balance: parseFloat(a.current_balance) || parseFloat(a.opening_balance) || 0,
            custodian_name: a.custodian_name || (a.owner_user_id ? String(a.owner_user_id).slice(0, 8) : 'Finance Admin'),
            project_id: a.project_id ? String(a.project_id) : undefined,
            project_name: 'Org Wide',
            site_id: a.site_id ? String(a.site_id) : undefined,
            scope_level: a.project_id ? (a.site_id ? 'site' : 'project') : 'portfolio',
            status: (a.status === 'active' || a.status === 'inactive') ? a.status : 'active',
            created_at: a.opening_balance_date || toLocalISODate(),
          }))
          setAccounts(mapped)
        }
      } catch (err) {
        console.warn('Live backend accounts fetch error:', err)
        if (active) setAccounts([])
      }
    }
    loadBackendAccounts()
    return () => {
      active = false
    }
  }, [scope])

  const handleDeactivateAccount = async (acc: MoneyAccountItem) => {
    if (!confirm(`Are you sure you want to deactivate/archive account "${acc.name}"? Historical ledger entries will be preserved.`)) return
    try {
      await deleteAccountApi(acc.id)
      setAccounts((prev) => prev.filter((a) => a.id !== acc.id))
      toast.success(`Account "${acc.name}" deactivated`, 'Archived from active money accounts')
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err.message || 'Failed to deactivate account'
      toast.error('Deactivation failed', msg)
    }
  }

  // Selection state
  const [selectedIds, setSelectedIds] = React.useState<string[]>([])

  // Sort state
  const [sortField, setSortField] = React.useState<SortField>('balance')
  const [sortOrder, setSortOrder] = React.useState<SortOrder>('desc')

  // Pagination state
  const [currentPage, setCurrentPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState(10)

  // Dialog & Sheet state
  const [createDialogOpen, setCreateDialogOpen] = React.useState(false)
  const [transferDialogOpen, setTransferDialogOpen] = React.useState(false)
  const [renameDialogOpen, setRenameDialogOpen] = React.useState(false)
  const [accountToRename, setAccountToRename] = React.useState<MoneyAccountItem | null>(null)
  const [selectedAccount, setSelectedAccount] = React.useState<MoneyAccountItem | null>(null)
  const [sheetOpen, setSheetOpen] = React.useState(false)

  // Scope-aware account filtering
  const scopedAccounts = React.useMemo(() => {
    return accounts.filter((acc) => {
      if (scope.mode === 'portfolio') return true
      if (scope.mode === 'project') {
        return acc.scope_level === 'portfolio' || acc.project_id === scope.projectId
      }
      if (scope.mode === 'site') {
        return (
          acc.scope_level === 'portfolio' ||
          acc.project_id === scope.projectId ||
          acc.site_id === scope.siteId
        )
      }
      return true
    })
  }, [accounts, scope])

  // Filtered & Sorted accounts
  const filteredAccounts = React.useMemo(() => {
    return scopedAccounts
      .filter((item) => {
        const matchesSearch =
          item.name.toLowerCase().includes(search.toLowerCase()) ||
          item.custodian_name.toLowerCase().includes(search.toLowerCase()) ||
          item.project_name.toLowerCase().includes(search.toLowerCase())

        if (!matchesSearch) return false
        if (typeFilter !== 'ALL' && item.account_type !== typeFilter) return false
        if (statusFilter !== 'ALL' && item.status !== statusFilter) return false

        return true
      })
      .sort((a, b) => {
        let modifier = sortOrder === 'asc' ? 1 : -1
        if (sortField === 'balance') return (a.current_balance - b.current_balance) * modifier
        if (sortField === 'name') return a.name.localeCompare(b.name) * modifier
        if (sortField === 'type') return a.account_type.localeCompare(b.account_type) * modifier
        return 0
      })
  }, [scopedAccounts, search, typeFilter, statusFilter, sortField, sortOrder])

  // Pagination
  const totalPages = Math.ceil(filteredAccounts.length / pageSize) || 1
  const paginatedAccounts = React.useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredAccounts.slice(start, start + pageSize)
  }, [filteredAccounts, currentPage, pageSize])

  // Summary Metrics
  const metrics = React.useMemo(() => {
    const netTreasury = scopedAccounts.reduce((acc, curr) => acc + curr.current_balance, 0)
    const bankTotal = scopedAccounts
      .filter((a) => a.account_type === 'bank')
      .reduce((acc, curr) => acc + curr.current_balance, 0)
    const pettyCashTotal = scopedAccounts
      .filter((a) => a.account_type === 'cash' || a.account_type === 'employee_advance')
      .reduce((acc, curr) => acc + curr.current_balance, 0)
    const lowBalanceCount = scopedAccounts.filter((a) => a.current_balance < 50000).length

    return {
      netTreasury,
      bankTotal,
      pettyCashTotal,
      lowBalanceCount,
      count: scopedAccounts.length,
    }
  }, [scopedAccounts])

  const handleAccountCreated = (newAccount: MoneyAccountItem) => {
    setAccounts((prev) => [newAccount, ...prev])
  }

  const handleAccountRenamed = (accountId: string, newName: string) => {
    setAccounts((prev) => prev.map((a) => (a.id === accountId ? { ...a, name: newName } : a)))
    toast.success('Account renamed', `Now shown as "${newName}"`)
  }

  const handleTransferCompleted = (fromId: string, toId: string, amount: number) => {
    setAccounts((prev) =>
      prev.map((acc) => {
        if (acc.id === fromId) {
          return { ...acc, current_balance: acc.current_balance - amount }
        }
        if (acc.id === toId) {
          return { ...acc, current_balance: acc.current_balance + amount }
        }
        return acc
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

  const isAllSelected = paginatedAccounts.length > 0 && paginatedAccounts.every((e) => selectedIds.includes(e.id))
  
  const toggleSelectAll = () => {
    if (isAllSelected) {
      setSelectedIds([])
    } else {
      setSelectedIds(paginatedAccounts.map((e) => e.id))
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

  const getAccountBadge = (type: string) => {
    switch (type) {
      case 'bank':
      case 'bank_account':
        return <Badge className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-[10px]">Bank Account</Badge>
      case 'cash':
        return <Badge className="bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20 text-[10px]">Operating Cash</Badge>
      case 'employee_advance':
      case 'petty_cash':
        return <Badge className="bg-purple-500/10 text-purple-700 dark:text-purple-400 border-purple-500/20 text-[10px]">Petty Cash Float</Badge>
      default:
        return <Badge variant="outline" className="text-[10px]">Other / Wallet</Badge>
    }
  }

  return (
    <div className="flex flex-col gap-4 w-full max-w-full relative pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3.5">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Accounts</h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 text-xs font-semibold text-cyan-600 border-cyan-500/30 hover:bg-cyan-500/10"
            onClick={() => setTransferDialogOpen(true)}
          >
            <ArrowLeftRight className="size-3.5" />
            Transfer Money
          </Button>
          <Button
            size="sm"
            className="h-8 gap-1.5 text-xs font-bold shadow-2xs"
            onClick={() => setCreateDialogOpen(true)}
          >
            <Plus className="size-4" />
            Create Account
          </Button>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          title="Cash and bank"
          value={<span>{formatCurrency(metrics.netTreasury)}</span>}
          description="Combined active balance"
          icon={<Landmark  />}
        />
        <KpiCard
          title="In bank"
          value={<span>{formatCurrency(metrics.bankTotal)}</span>}
          description="Main operating funds"
          icon={<Building2  />}
        />
        <KpiCard
          title="Petty cash"
          value={<span>{formatCurrency(metrics.pettyCashTotal)}</span>}
          description="Field cash availability"
          icon={<Wallet  />}
        />
        <KpiCard
          title="Low balance"
          value={
            <span className={metrics.lowBalanceCount > 0 ? 'text-rose-600 dark:text-rose-400' : 'text-foreground'}>
              {metrics.lowBalanceCount} Accounts
            </span>
          }
          description="Float threshold alerts (< ₹50k)"
          icon={<AlertTriangle className={metrics.lowBalanceCount > 0 ? 'text-rose-500' : 'text-muted-foreground'} />}
        />
      </div>

      {/* Toolbar & Layout Switcher */}
      <div className="flex flex-col sm:flex-row gap-2.5 items-center justify-between border border-border/80 p-2.5 rounded-lg bg-card/40">
        <div className="flex flex-wrap gap-2 w-full sm:w-auto flex-1 items-center">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <Input
              placeholder="Search accounts, custodians, project..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-9 text-xs"
            />
          </div>

          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger className="h-9 text-xs w-full sm:w-40">
              <SelectValue placeholder="All Account Types" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Account Types</SelectItem>
              <SelectItem value="bank_account">Bank Accounts</SelectItem>
              <SelectItem value="petty_cash">Petty Cash Boxes</SelectItem>
              <SelectItem value="corporate_card">Corporate Cards</SelectItem>
            </SelectContent>
          </Select>

          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-9 text-xs w-full sm:w-32">
              <SelectValue placeholder="All Statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Statuses</SelectItem>
              <SelectItem value="active">Active Only</SelectItem>
              <SelectItem value="inactive">Inactive Only</SelectItem>
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
            Cards
          </Button>
          <Button
            size="sm"
            variant={viewMode === 'table' ? 'default' : 'ghost'}
            className="h-7 px-2.5 text-xs gap-1"
            onClick={() => setViewMode('table')}
          >
            <List className="size-3.5" />
            Table
          </Button>
        </div>
      </div>

      {/* Main Content (Cards Grid vs Table View) */}
      {viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filteredAccounts.length === 0 ? (
            <div className="col-span-full h-32 flex items-center justify-center border rounded-lg text-xs text-muted-foreground">
              No money accounts match your criteria for {scopeLabel}.
            </div>
          ) : (
            filteredAccounts.map((acc) => {
              const isLow = acc.current_balance < 50000
              return (
                <Card
                  key={acc.id}
                  className={`hover:border-primary/50 transition-all duration-200 cursor-pointer group relative overflow-hidden bg-gradient-to-br from-card via-card to-muted/20 ${isLow ? 'border-rose-500/40 shadow-xs' : ''}`}
                  onClick={() => {
                    setSelectedAccount(acc)
                    setSheetOpen(true)
                  }}
                >
                  <div className="p-4 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        {getAccountBadge(acc.account_type)}
                        {isLow && (
                          <Badge className="bg-rose-500/15 text-rose-700 dark:text-rose-400 border-rose-500/20 text-[10px] gap-1">
                            <AlertTriangle className="size-3" /> Low Float
                          </Badge>
                        )}
                      </div>
                      <Badge variant="outline" className="text-[10px] font-mono">
                        {acc.project_name}
                      </Badge>
                    </div>

                    <div>
                      <h3 className="font-bold text-sm text-foreground group-hover:text-primary transition-colors">
                        {acc.name}
                      </h3>
                      {acc.account_number_masked && (
                        <span className="text-xs font-mono text-muted-foreground block">
                          {acc.account_number_masked}
                        </span>
                      )}
                    </div>

                    <div className="pt-2 border-t flex items-end justify-between">
                      <div>
                        <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold block">
                          Available Balance
                        </span>
                        <span className={`text-xl font-bold font-mono tracking-tight ${isLow ? 'text-rose-600 dark:text-rose-400' : 'text-foreground'}`}>
                          {formatCurrency(acc.current_balance)}
                        </span>
                      </div>

                      <div className="flex items-center gap-1 text-[11px] text-muted-foreground bg-muted/40 px-2 py-1 rounded">
                        <User className="size-3 text-emerald-500" />
                        <span className="truncate max-w-[100px]">{acc.custodian_name}</span>
                      </div>
                    </div>
                  </div>
                </Card>
              )
            })
          )}
        </div>
      ) : (
        /* Table View */
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
                  />
                </TableHead>
                <TableHead
                  className="text-xs font-semibold h-10 cursor-pointer select-none"
                  onClick={() => toggleSort('name')}
                >
                  Account Name {sortField === 'name' ? (sortOrder === 'asc' ? '↑' : '↓') : ''}
                </TableHead>
                <TableHead
                  className="text-xs font-semibold h-10 cursor-pointer select-none"
                  onClick={() => toggleSort('type')}
                >
                  Type {sortField === 'type' ? (sortOrder === 'asc' ? '↑' : '↓') : ''}
                </TableHead>
                <TableHead className="text-xs font-semibold h-10">Custodian</TableHead>
                <TableHead className="text-xs font-semibold h-10">Scope</TableHead>
                <TableHead
                  className="text-xs font-semibold h-10 text-right cursor-pointer select-none"
                  onClick={() => toggleSort('balance')}
                >
                  Current Balance (₹) {sortField === 'balance' ? (sortOrder === 'asc' ? '↑' : '↓') : ''}
                </TableHead>
                <TableHead className="text-xs font-semibold h-10 text-center">Status</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right w-[60px]">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedAccounts.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="h-32 text-center text-xs text-muted-foreground">
                    No accounts found for current scope.
                  </TableCell>
                </TableRow>
              ) : (
                paginatedAccounts.map((acc) => {
                  const isSelected = selectedIds.includes(acc.id)
                  const isLow = acc.current_balance < 50000
                  return (
                    <TableRow
                      key={acc.id}
                      className={`hover:bg-muted/40 cursor-pointer transition-colors ${isSelected ? 'bg-emerald-500/5' : ''}`}
                      onClick={() => {
                        setSelectedAccount(acc)
                        setSheetOpen(true)
                      }}
                    >
                      <TableCell className="px-3" onClick={(e) => toggleSelectRow(acc.id, e)}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {}}
                          className="size-4 rounded border-border text-emerald-600 focus:ring-emerald-500 cursor-pointer accent-emerald-600"
                        />
                      </TableCell>
                      <TableCell className="font-semibold text-xs text-foreground">
                        <div className="flex items-center gap-1.5">
                          {acc.name}
                          {isLow && (
                            <Badge className="bg-rose-500/15 text-rose-700 dark:text-rose-400 border-rose-500/20 text-[9px] px-1 py-0">
                              Low Float
                            </Badge>
                          )}
                        </div>
                        {acc.account_number_masked && (
                          <span className="font-mono text-[10px] text-muted-foreground block">
                            {acc.account_number_masked}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs">{getAccountBadge(acc.account_type)}</TableCell>
                      <TableCell className="text-xs font-medium text-foreground">{acc.custodian_name}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{acc.project_name}</TableCell>
                      <TableCell className={`text-xs font-mono font-bold text-right tabular-nums ${isLow ? 'text-rose-600 dark:text-rose-400' : 'text-foreground'}`}>
                        {formatCurrency(acc.current_balance)}
                      </TableCell>
                      <TableCell className="text-center">
                        <Badge className="bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[10px] font-semibold">
                          Active
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
                                setSelectedAccount(acc)
                                setSheetOpen(true)
                              }}
                            >
                              <Eye className="size-3.5 mr-1.5" /> View Ledger
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => setTransferDialogOpen(true)}>
                              <ArrowLeftRight className="size-3.5 mr-1.5 text-cyan-500" /> Transfer Funds
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={() => {
                                setAccountToRename(acc)
                                setRenameDialogOpen(true)
                              }}
                            >
                              <Pencil className="size-3.5 mr-1.5 text-indigo-500" /> Rename Account
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => handleDeactivateAccount(acc)} className="text-rose-600 focus:text-rose-600">
                              <Trash2 className="size-3.5 mr-1.5" /> Deactivate Account
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
          className="h-7 text-xs gap-1.5 font-semibold text-cyan-600 border-cyan-500/40 hover:bg-cyan-500/10"
          onClick={() => setTransferDialogOpen(true)}
        >
          <ArrowLeftRight className="size-3.5" />
          Transfer Selected
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs gap-1.5 font-semibold"
          onClick={() =>
            exportCsv(
              'accounts-selected.csv',
              ['Account', 'Kind', 'Balance'],
              accounts.filter((a) => selectedIds.includes(a.id)).map((a) => [a.name, a.account_type, a.current_balance]),
            )
          }
        >
          <Download className="size-3.5" />
          Export Selected
        </Button>
      </BulkActionBar>

      {/* Modals & Sheet */}
      <CreateAccountDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        scope={scope}
        onAccountCreated={handleAccountCreated}
      />

      <TransferMoneyDialog
        open={transferDialogOpen}
        onOpenChange={setTransferDialogOpen}
        accounts={accounts}
        onTransferCompleted={handleTransferCompleted}
      />

      <AccountDetailSheet
        account={selectedAccount}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        onDepositClick={() => setTransferDialogOpen(true)}
      />

      <RenameAccountDialog
        open={renameDialogOpen}
        onOpenChange={setRenameDialogOpen}
        accountId={accountToRename?.id ?? null}
        currentName={accountToRename?.name ?? ''}
        onRenamed={handleAccountRenamed}
      />
    </div>
  )
}
