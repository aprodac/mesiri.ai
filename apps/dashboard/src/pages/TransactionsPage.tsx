import * as React from 'react'
import {
  ArrowLeftRight,
  ArrowUpRight,
  ArrowDownLeft,
  Search,
  DollarSign,
  Receipt,
  RotateCcw,
  Building2,
  Calendar,
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  fetchTransactionsApi,
  fetchAccountsApi,
  reverseTransferApi,
  type MoneyTransactionItem,
} from '@/lib/api'
import { AccountDetailSheet } from '@/components/accounts/account-detail-sheet'
import { ExpenseDetailSheet } from '@/components/expenses/expense-detail-sheet'
import { WhatsAppTraceModal } from '@/components/whatsapp/whatsapp-trace-modal'
import { useToast } from '@/components/ui/toast-notification'

interface SimpleAccountItem {
  id: string
  name: string
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

function getTransactionTypeBadge(type: string) {
  const normalized = (type || '').toLowerCase()
  switch (normalized) {
    case 'transfer':
      return (
        <Badge variant="outline" className="border-blue-500/30 text-blue-600 dark:text-blue-400 bg-blue-500/10 text-[10px] gap-1">
          <ArrowLeftRight className="size-3" />
          TRANSFER
        </Badge>
      )
    case 'expense_payment':
      return (
        <Badge variant="outline" className="border-rose-500/30 text-rose-600 dark:text-rose-400 bg-rose-500/10 text-[10px] gap-1">
          <ArrowUpRight className="size-3" />
          EXPENSE PAYOUT
        </Badge>
      )
    case 'petty_cash_voucher':
      return (
        <Badge variant="outline" className="border-amber-500/30 text-amber-600 dark:text-amber-400 bg-amber-500/10 text-[10px] gap-1">
          <Receipt className="size-3" />
          VOUCHER
        </Badge>
      )
    case 'inflow':
      return (
        <Badge variant="outline" className="border-emerald-500/30 text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 text-[10px] gap-1">
          <ArrowDownLeft className="size-3" />
          INFLOW
        </Badge>
      )
    case 'reversal':
      return (
        <Badge variant="outline" className="border-purple-500/30 text-purple-600 dark:text-purple-400 bg-purple-500/10 text-[10px] gap-1">
          <RotateCcw className="size-3" />
          REVERSAL
        </Badge>
      )
    default:
      return (
        <Badge variant="outline" className="text-[10px] uppercase">
          {type || 'TRANSACTION'}
        </Badge>
      )
  }
}

export default function TransactionsPage() {
  const toast = useToast()

  const [transactions, setTransactions] = React.useState<MoneyTransactionItem[]>([])
  const [reversingId, setReversingId] = React.useState<string | null>(null)
  const [accounts, setAccounts] = React.useState<SimpleAccountItem[]>([])
  const [loading, setLoading] = React.useState(true)
  const [search, setSearch] = React.useState('')
  const [typeFilter, setTypeFilter] = React.useState('ALL')
  const [accountFilter, setAccountFilter] = React.useState('ALL')

  // Sub-sheet States
  const [accountSheetId, setAccountSheetId] = React.useState<string | null>(null)
  const [expenseSheetId, setExpenseSheetId] = React.useState<string | null>(null)
  const [whatsappTraceId, setWhatsappTraceId] = React.useState<string | null>(null)

  const loadData = React.useCallback(async () => {
    setLoading(true)
    try {
      const [txData, accData] = await Promise.all([
        fetchTransactionsApi({
          transaction_type: typeFilter !== 'ALL' ? typeFilter : undefined,
          account_id: accountFilter !== 'ALL' ? accountFilter : undefined,
        }),
        fetchAccountsApi(),
      ])

      if (Array.isArray(txData)) setTransactions(txData)
      if (Array.isArray(accData)) setAccounts(accData)
    } catch (err) {
      console.warn('Failed to load transaction ledger:', err)
      setTransactions([])
    } finally {
      setLoading(false)
    }
  }, [typeFilter, accountFilter])

  React.useEffect(() => {
    loadData()
  }, [loadData])

  const handleReverseTransfer = async (tx: MoneyTransactionItem) => {
    if (!confirm('Reverse this transfer? This posts an offsetting entry and cannot be undone.')) return
    setReversingId(tx.id)
    try {
      await reverseTransferApi(tx.id)
      toast.success('Transfer reversed', 'An offsetting ledger entry has been posted.')
      loadData()
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.join(', ') : detail || err.message || 'Reverse failed'
      toast.error('Reverse failed', msg)
    } finally {
      setReversingId(null)
    }
  }

  const filteredTransactions = React.useMemo(() => {
    return transactions.filter((tx) => {
      const query = search.toLowerCase()
      const matchesSearch =
        (tx.description || '').toLowerCase().includes(query) ||
        (tx.correlation_id || '').toLowerCase().includes(query) ||
        (tx.from_account_name || '').toLowerCase().includes(query) ||
        (tx.to_account_name || '').toLowerCase().includes(query) ||
        (tx.id || '').toLowerCase().includes(query)

      return matchesSearch
    })
  }, [transactions, search])

  // Summary Metrics
  const metrics = React.useMemo(() => {
    let totalVolume = 0
    let totalTransfers = 0
    let totalExpensePayouts = 0
    let totalVouchers = 0

    for (const tx of transactions) {
      const amt = parseFloat(String(tx.amount)) || 0
      totalVolume += amt
      const tType = (tx.transaction_type || '').toLowerCase()
      if (tType === 'transfer') totalTransfers += amt
      else if (tType === 'expense_payment') totalExpensePayouts += amt
      else if (tType === 'petty_cash_voucher') totalVouchers += amt
    }

    return {
      totalVolume,
      totalTransfers,
      totalExpensePayouts,
      totalVouchers,
      count: transactions.length,
    }
  }, [transactions])


  return (
    <div className="flex flex-col gap-4 w-full max-w-full relative pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3.5">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Transactions</h1>
          </div>
        </div>

        <Button
          size="sm"
          variant="outline"
          className="h-9 px-3.5 text-xs font-semibold gap-1.5 shadow-2xs"
          onClick={loadData}
        >
          <RotateCcw className="size-3.5" />
          Refresh Ledger
        </Button>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          title="Total moved"
          value={<span>{formatCurrency(metrics.totalVolume)}</span>}
          description="Cumulative financial movement"
          icon={<DollarSign  />}
        />
        <KpiCard
          title="Expenses paid"
          value={<span>{formatCurrency(metrics.totalExpensePayouts)}</span>}
          description="Confirmed vendor payouts"
          icon={<ArrowUpRight  />}
        />
        <KpiCard
          title="Account transfers"
          value={<span>{formatCurrency(metrics.totalTransfers)}</span>}
          description="Inter-account bank transfers"
          icon={<ArrowLeftRight  />}
        />
        <KpiCard
          title="Petty cash vouchers"
          value={<span>{formatCurrency(metrics.totalVouchers)}</span>}
          description="Field vouchers paid in cash"
          icon={<Receipt  />}
        />
      </div>

      {/* Filter Bar */}
      <div className="flex flex-col sm:flex-row gap-2.5 items-center justify-between bg-card p-3 rounded-lg border shadow-2xs">
        <div className="flex flex-col sm:flex-row items-center gap-2 w-full">
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
            <Input
              placeholder="Search description, account name, correlation ID..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-8 text-xs"
            />
          </div>

          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger className="h-8 text-xs w-full sm:w-[170px]">
              <SelectValue placeholder="Transaction Type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL" className="text-xs">All Types</SelectItem>
              <SelectItem value="transfer" className="text-xs">Account Transfer</SelectItem>
              <SelectItem value="expense_payment" className="text-xs">Expense Payout</SelectItem>
              <SelectItem value="petty_cash_voucher" className="text-xs">Petty Cash Voucher</SelectItem>
              <SelectItem value="inflow" className="text-xs">Client Inflow</SelectItem>
              <SelectItem value="reversal" className="text-xs">Reversal</SelectItem>
            </SelectContent>
          </Select>

          <Select value={accountFilter} onValueChange={setAccountFilter}>
            <SelectTrigger className="h-8 text-xs w-full sm:w-[200px]">
              <SelectValue placeholder="Account Filter" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL" className="text-xs">All Money Accounts</SelectItem>
              {accounts.map((acc) => (
                <SelectItem key={acc.id} value={acc.id} className="text-xs">
                  {acc.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Ledger Table View */}
      {loading ? (
        <div className="py-20 text-center text-xs text-muted-foreground">
          Loading company transaction ledger...
        </div>
      ) : filteredTransactions.length === 0 ? (
        <div className="py-20 border rounded-lg bg-card text-center flex flex-col items-center justify-center p-6 gap-2">
          <ArrowLeftRight className="size-10 text-muted-foreground/40" />
          <h3 className="text-sm font-semibold text-foreground">No Transactions Found</h3>
          <p className="text-xs text-muted-foreground max-w-sm">
            {search ? 'No ledger transactions match your query.' : 'Money movements recorded via WhatsApp or Dashboard will appear here.'}
          </p>
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden bg-card shadow-2xs">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs font-semibold h-10">Occurred Date</TableHead>
                <TableHead className="text-xs font-semibold h-10">Type</TableHead>
                <TableHead className="text-xs font-semibold h-10">From Account</TableHead>
                <TableHead className="text-xs font-semibold h-10">To Account</TableHead>
                <TableHead className="text-xs font-semibold h-10">Description / Payee</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right">Amount (₹)</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredTransactions.map((tx, idx) => {
                const amount = parseFloat(String(tx.amount)) || 0
                const tType = (tx.transaction_type || '').toLowerCase()
                return (
                  <TableRow key={tx.id || idx} className="hover:bg-muted/40 text-xs">
                    <TableCell className="font-mono text-muted-foreground shrink-0">
                      <div className="flex items-center gap-1.5">
                        <Calendar className="size-3.5 text-muted-foreground" />
                        <span>{tx.occurred_date}</span>
                      </div>
                    </TableCell>

                    <TableCell>{getTransactionTypeBadge(tx.transaction_type)}</TableCell>

                    <TableCell className="font-medium text-foreground">
                      {tx.from_account_name ? (
                        <button
                          type="button"
                          onClick={() => tx.from_account_id && setAccountSheetId(String(tx.from_account_id))}
                          className="flex items-center gap-1.5 hover:text-blue-600 transition-colors text-left font-medium"
                        >
                          <Building2 className="size-3.5 text-muted-foreground" />
                          <span>{tx.from_account_name}</span>
                        </button>
                      ) : (
                        <span className="text-muted-foreground italic">— External Source —</span>
                      )}
                    </TableCell>

                    <TableCell className="font-medium text-foreground">
                      {tx.to_account_name ? (
                        <button
                          type="button"
                          onClick={() => tx.to_account_id && setAccountSheetId(String(tx.to_account_id))}
                          className="flex items-center gap-1.5 hover:text-blue-600 transition-colors text-left font-medium"
                        >
                          <Building2 className="size-3.5 text-muted-foreground" />
                          <span>{tx.to_account_name}</span>
                        </button>
                      ) : (
                        <span className="text-muted-foreground italic">— External Payee —</span>
                      )}
                    </TableCell>

                    <TableCell className="max-w-[240px] truncate text-foreground font-medium">
                      <span>{tx.description || 'General Ledger Entry'}</span>
                      {tx.correlation_id && (
                        <button
                          type="button"
                          onClick={() => setWhatsappTraceId(tx.correlation_id || null)}
                          className="text-[10px] font-mono text-muted-foreground hover:text-emerald-600 block truncate transition-colors text-left"
                        >
                          Ref: {tx.correlation_id}
                        </button>
                      )}
                    </TableCell>

                    <TableCell className="text-right font-mono font-bold">
                      <span
                        className={
                          tType === 'inflow'
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : tType === 'expense_payment' || tType === 'petty_cash_voucher'
                            ? 'text-rose-600 dark:text-rose-400'
                            : 'text-blue-600 dark:text-blue-400'
                        }
                      >
                        {formatCurrency(amount)}
                      </span>
                    </TableCell>

                    <TableCell className="text-right">
                      {tType === 'transfer' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs px-2 gap-1 text-purple-600 hover:text-purple-700"
                          disabled={reversingId === tx.id}
                          onClick={() => handleReverseTransfer(tx)}
                        >
                          <RotateCcw className="size-3" />
                          {reversingId === tx.id ? 'Reversing...' : 'Reverse'}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Sub-sheets */}
      <AccountDetailSheet
        open={!!accountSheetId}
        onOpenChange={(op) => !op && setAccountSheetId(null)}
        account={accountSheetId ? { id: accountSheetId, name: 'Money Account', account_type: 'bank', currency: 'INR', opening_balance: 0, current_balance: 0, status: 'active', created_at: '' } : null}
      />

      <ExpenseDetailSheet
        open={!!expenseSheetId}
        onOpenChange={(op) => !op && setExpenseSheetId(null)}
        expense={expenseSheetId ? { id: expenseSheetId, amount: 0 } : null}
      />

      <WhatsAppTraceModal
        open={!!whatsappTraceId}
        onOpenChange={(op) => !op && setWhatsappTraceId(null)}
        correlationId={whatsappTraceId}
      />
    </div>
  )
}
