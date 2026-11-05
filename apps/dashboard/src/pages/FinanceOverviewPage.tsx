import * as React from 'react'
import {
  DollarSign,
  Landmark,
  ArrowLeftRight,
  Plus,
  Store,
  Tags,
  Receipt,
  AlertTriangle,
  PieChart as PieChartIcon,
  Activity,
  ChevronRight,
  BarChart3,
  Wallet,
  ShieldAlert,
  Zap,
  UserCheck,
} from 'lucide-react'
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'
import { Link } from 'react-router-dom'
import { useScope } from '@/lib/ScopeContext'
import { KpiCard } from '@/components/ui/kpi-card'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  fetchFinanceSummaryApi,
  fetchAccountsApi,
  fetchTransactionsApi,
  type FinanceSummaryItem,
  type MoneyTransactionItem,
} from '@/lib/api'
import { RecordExpenseDialog } from '@/components/expenses/record-expense-dialog'
import { TransferMoneyDialog } from '@/components/accounts/transfer-money-dialog'
import { CreateCategoryDialog } from '@/components/categories/create-category-dialog'
import { CreateVendorDialog } from '@/components/vendors/create-vendor-dialog'
import { AccountDetailSheet } from '@/components/accounts/account-detail-sheet'
import { VendorDetailSheet } from '@/components/vendors/vendor-detail-sheet'
import { CategoryDetailSheet } from '@/components/categories/category-detail-sheet'
import { ExpenseDetailSheet } from '@/components/expenses/expense-detail-sheet'

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

const CATEGORY_COLORS = [
  '#10b981', // emerald
  '#3b82f6', // blue
  '#8b5cf6', // purple
  '#f59e0b', // amber
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#6366f1', // indigo
]

export default function FinanceOverviewPage() {
  const { scope } = useScope()

  const [summary, setSummary] = React.useState<FinanceSummaryItem | null>(null)
  const [accounts, setAccounts] = React.useState<any[]>([])
  const [recentTransactions, setRecentTransactions] = React.useState<MoneyTransactionItem[]>([])
  const [loading, setLoading] = React.useState(true)

  // Dialog & Sub-sheet States
  const [recordExpenseOpen, setRecordExpenseOpen] = React.useState(false)
  const [transferOpen, setTransferOpen] = React.useState(false)
  const [createCategoryOpen, setCreateCategoryOpen] = React.useState(false)
  const [createVendorOpen, setCreateVendorOpen] = React.useState(false)

  const [accountSheetId, setAccountSheetId] = React.useState<string | null>(null)
  const [vendorSheetId, setVendorSheetId] = React.useState<string | null>(null)
  const [categorySheetId, setCategorySheetId] = React.useState<string | null>(null)
  const [expenseSheetId, setExpenseSheetId] = React.useState<string | null>(null)

  const loadData = React.useCallback(async () => {
    setLoading(true)
    try {
      const [sumData, accData, txData] = await Promise.all([
        fetchFinanceSummaryApi(),
        fetchAccountsApi(),
        fetchTransactionsApi({ limit: 6 }),
      ])
      if (sumData) setSummary(sumData)
      if (Array.isArray(accData)) setAccounts(accData)
      if (Array.isArray(txData)) setRecentTransactions(txData)
    } catch (err) {
      console.warn('Failed to load finance overview summary:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    loadData()
  }, [loadData])

  const pieChartData = React.useMemo(() => {
    if (!summary?.category_breakdown) return []
    return summary.category_breakdown
      .filter((c) => (parseFloat(String(c.amount)) || 0) > 0)
      .map((c, i) => ({
        name: c.name,
        value: parseFloat(String(c.amount)) || 0,
        color: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
      }))
  }, [summary])

  const barChartData = React.useMemo(() => {
    if (!summary?.monthly_trend) return []
    return summary.monthly_trend.map((m) => ({
      month: m.month,
      amount: parseFloat(String(m.amount)) || 0,
    }))
  }, [summary])

  const dailyAverageSpend = React.useMemo(() => {
    const total = parseFloat(String(summary?.total_expenses || 0))
    return total > 0 ? Math.round(total / 30) : 0
  }, [summary])


  return (
    <div className="flex flex-col gap-5 w-full max-w-full relative pb-12">
      {/* Page Header & Quick Action Hub */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b pb-4">
        <div className="flex items-center gap-3">
          <div className="size-11 rounded-xl border border-emerald-500/30 bg-emerald-500/10 flex items-center justify-center text-emerald-600 dark:text-emerald-400 shrink-0 shadow-2xs">
            <Activity className="size-6" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Finance</h1>
          </div>
        </div>

        {/* Action Hub Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            className="h-8 text-xs font-semibold gap-1.5 shadow-2xs"
            onClick={() => setRecordExpenseOpen(true)}
          >
            <Plus className="size-3.5" />
            Record Expense
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs font-semibold gap-1.5 shadow-2xs"
            onClick={() => setTransferOpen(true)}
          >
            <ArrowLeftRight className="size-3.5 text-blue-500" />
            Transfer Funds
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs font-semibold gap-1.5 shadow-2xs"
            onClick={() => setCreateVendorOpen(true)}
          >
            <Store className="size-3.5 text-indigo-500" />
            Add Vendor
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs font-semibold gap-1.5 shadow-2xs"
            onClick={() => setCreateCategoryOpen(true)}
          >
            <Tags className="size-3.5 text-purple-500" />
            Add Category
          </Button>
        </div>
      </div>

      {/* Financial Health Alerts Panel */}
      {summary?.health_alerts && (summary.health_alerts.low_float_count > 0 || summary.health_alerts.unpaid_invoice_count > 0) && (
        <div className="p-3.5 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs shadow-2xs">
          <div className="flex items-center gap-2.5">
            <ShieldAlert className="size-5 text-amber-600 dark:text-amber-400 shrink-0" />
            <div className="flex flex-col">
              <span className="font-bold text-xs">Financial Attention Required</span>
              <span className="text-[11px] opacity-90">
                {summary.health_alerts.low_float_count > 0 && `${summary.health_alerts.low_float_count} cash float accounts below ₹50,000 threshold.`}{' '}
                {summary.health_alerts.unpaid_invoice_count > 0 && `${summary.health_alerts.unpaid_invoice_count} unpaid invoices totaling ${formatCurrency(parseFloat(String(summary.health_alerts.total_unpaid_amount)))} require payout.`}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-[11px] font-semibold border-amber-500/40 text-amber-800 dark:text-amber-200 hover:bg-amber-500/20"
              onClick={() => setTransferOpen(true)}
            >
              Top Up Cash Float
            </Button>
          </div>
        </div>
      )}

      {/* Top Executive KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          title="Total cash & bank liquidity"
          value={
            <span>
              {formatCurrency(parseFloat(String(summary?.total_liquidity || 0)))}
            </span>
          }
          description="Available cash across all balances"
          icon={<Landmark  />}
        />
        <KpiCard
          title="Total confirmed expenses"
          value={
            <span>
              {formatCurrency(parseFloat(String(summary?.total_expenses || 0)))}
            </span>
          }
          description="Cumulative recorded disbursements"
          icon={<DollarSign  />}
        />
        <KpiCard
          title="Unpaid liabilities"
          value={
            <span>
              {formatCurrency(parseFloat(String(summary?.unpaid_expenses || 0)))}
            </span>
          }
          description="Pending vendor payouts"
          icon={<AlertTriangle  />}
        />
        <KpiCard
          title="Daily average run-rate"
          value={
            <span>
              {formatCurrency(dailyAverageSpend)}
              <span className="text-xs font-normal text-muted-foreground ml-1">/day</span>
            </span>
          }
          description="Average daily operational burn"
          icon={<Zap  />}
        />
      </div>

      {/* Analytics Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Monthly Expenditure Trend (Recharts BarChart) */}
        <Card className="p-5 flex flex-col gap-4 border shadow-2xs">
          <div className="flex items-center justify-between border-b pb-3">
            <div className="flex items-center gap-2">
              <BarChart3 className="size-4 text-blue-500" />
              <h3 className="font-bold text-sm text-foreground">Monthly Expenditure Trend</h3>
            </div>
            <span className="text-[10px] text-muted-foreground font-mono uppercase font-semibold">
              Time Series
            </span>
          </div>

          {loading ? (
            <div className="h-64 flex items-center justify-center text-xs text-muted-foreground">
              Loading financial trends...
            </div>
          ) : barChartData.length === 0 ? (
            <div className="h-64 flex flex-col items-center justify-center text-xs text-muted-foreground gap-2">
              <BarChart3 className="size-8 text-muted-foreground/30" />
              <span>No monthly expense trends recorded yet.</span>
            </div>
          ) : (
            <div className="h-64 w-full pt-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={barChartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} tickFormatter={(val) => `₹${val / 1000}k`} />
                  <Tooltip
                    formatter={(val: any) => formatCurrency(Number(val))}
                    contentStyle={{
                      fontSize: '12px',
                      backgroundColor: 'var(--card)',
                      borderColor: 'var(--border)',
                      borderRadius: '8px',
                    }}
                  />
                  <Bar dataKey="amount" fill="#3b82f6" radius={[6, 6, 0, 0]} maxBarSize={45} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        {/* Category Spend Distribution Chart (Recharts PieChart) */}
        <Card className="p-5 flex flex-col gap-4 border shadow-2xs">
          <div className="flex items-center justify-between border-b pb-3">
            <div className="flex items-center gap-2">
              <PieChartIcon className="size-4 text-emerald-500" />
              <h3 className="font-bold text-sm text-foreground">Expense Category Distribution</h3>
            </div>
            <Link
              to="/finance/categories"
              className="text-xs text-emerald-600 dark:text-emerald-400 hover:underline font-medium flex items-center gap-1"
            >
              Manage Categories <ChevronRight className="size-3" />
            </Link>
          </div>

          {loading ? (
            <div className="h-64 flex items-center justify-center text-xs text-muted-foreground">
              Loading financial breakdown...
            </div>
          ) : pieChartData.length === 0 ? (
            <div className="h-64 flex flex-col items-center justify-center text-xs text-muted-foreground gap-2">
              <PieChartIcon className="size-8 text-muted-foreground/30" />
              <span>No categorized expenses recorded yet.</span>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 items-center gap-4">
              <div className="h-60 w-full relative">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={pieChartData}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      paddingAngle={3}
                      dataKey="value"
                    >
                      {pieChartData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(val: any) => formatCurrency(Number(val))}
                      contentStyle={{
                        fontSize: '12px',
                        backgroundColor: 'var(--card)',
                        borderColor: 'var(--border)',
                        borderRadius: '8px',
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              <div className="flex flex-col gap-2 text-xs">
                {pieChartData.map((item, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-2 rounded-md bg-muted/30 border text-xs"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className="size-3 rounded-full shrink-0"
                        style={{ backgroundColor: item.color }}
                      />
                      <span className="font-semibold text-foreground truncate">{item.name}</span>
                    </div>
                    <span className="font-mono font-bold text-foreground">
                      {formatCurrency(item.value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Operational Widgets Grid (Petty Cash Floats & Top Vendors) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Petty Cash Custodian Floats Widget */}
        <Card className="p-5 flex flex-col gap-4 border shadow-2xs">
          <div className="flex items-center justify-between border-b pb-3">
            <div className="flex items-center gap-2">
              <Wallet className="size-4 text-emerald-500" />
              <h3 className="font-bold text-sm text-foreground">Petty Cash Custodian Floats</h3>
            </div>
            <Link
              to="/finance/petty-cash"
              className="text-xs text-emerald-600 dark:text-emerald-400 hover:underline font-medium flex items-center gap-1"
            >
              Petty Cash Desk <ChevronRight className="size-3" />
            </Link>
          </div>

          <div className="flex flex-col gap-3">
            {summary?.petty_cash_accounts && summary.petty_cash_accounts.length > 0 ? (
              summary.petty_cash_accounts.map((box) => {
                const bal = parseFloat(String(box.current_balance)) || 0
                const openBal = parseFloat(String(box.opening_balance)) || (bal > 0 ? bal : 1)
                const pct = Math.min(100, Math.max(0, Math.round((bal / openBal) * 100)))
                const isLow = bal < 50000
                return (
                  <div key={box.id} className="p-3 rounded-lg border bg-card/60 flex flex-col gap-2 text-xs">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <UserCheck className="size-4 text-emerald-500 shrink-0" />
                        <span className="font-bold text-foreground">{box.name}</span>
                        <span className="text-[10px] text-muted-foreground">({box.custodian_name})</span>
                      </div>
                      <span className={`font-mono font-bold ${isLow ? 'text-rose-600 dark:text-rose-400' : 'text-foreground'}`}>
                        {formatCurrency(bal)}
                      </span>
                    </div>

                    <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-full transition-all duration-300 ${isLow ? 'bg-rose-500' : 'bg-emerald-500'}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                )
              })
            ) : (
              <div className="py-8 text-center text-xs text-muted-foreground">
                No petty cash float accounts registered.
              </div>
            )}
          </div>
        </Card>

        {/* Top Vendors & Outstandings Widget */}
        <Card className="p-5 flex flex-col gap-4 border shadow-2xs">
          <div className="flex items-center justify-between border-b pb-3">
            <div className="flex items-center gap-2">
              <Store className="size-4 text-indigo-500" />
              <h3 className="font-bold text-sm text-foreground">Top Suppliers & Payees</h3>
            </div>
            <Link
              to="/finance/vendors"
              className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline font-medium flex items-center gap-1"
            >
              All Vendors <ChevronRight className="size-3" />
            </Link>
          </div>

          <div className="flex flex-col gap-2.5">
            {summary?.top_vendors && summary.top_vendors.length > 0 ? (
              summary.top_vendors.map((v) => {
                const total = parseFloat(String(v.total_spent)) || 0
                const unpaid = parseFloat(String(v.unpaid_amount)) || 0
                return (
                  <div key={v.id} className="p-3 rounded-lg border bg-card/60 flex items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="size-7 rounded-md bg-indigo-500/10 text-indigo-600 flex items-center justify-center font-bold text-xs shrink-0">
                        <Store className="size-3.5" />
                      </div>
                      <span className="font-semibold text-foreground truncate">{v.name}</span>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <div className="flex flex-col items-end">
                        <span className="font-mono font-bold text-foreground">{formatCurrency(total)}</span>
                        {unpaid > 0 && (
                          <span className="text-[10px] font-mono text-amber-600 dark:text-amber-400">
                            Unpaid: {formatCurrency(unpaid)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })
            ) : (
              <div className="py-8 text-center text-xs text-muted-foreground">
                No active vendors registered yet.
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Recent Activity Ticker */}
      <Card className="p-5 flex flex-col gap-4 border shadow-2xs">
        <div className="flex items-center justify-between border-b pb-3">
          <div className="flex items-center gap-2">
            <Activity className="size-4 text-purple-500" />
            <h3 className="font-bold text-sm text-foreground">Recent General Ledger Activity</h3>
          </div>
          <Link
            to="/finance/transactions"
            className="text-xs text-purple-600 dark:text-purple-400 hover:underline font-medium flex items-center gap-1"
          >
            All Ledger Transactions <ChevronRight className="size-3" />
          </Link>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
          {recentTransactions.length === 0 ? (
            <div className="col-span-full py-8 text-center text-xs text-muted-foreground">
              No recent general ledger transactions.
            </div>
          ) : (
            recentTransactions.map((tx: any, idx: number) => {
              const amount = parseFloat(String(tx.amount)) || 0
              return (
                <div
                  key={tx.id || idx}
                  className="p-3 rounded-lg border bg-card/60 flex items-center justify-between gap-3 text-xs"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="size-8 rounded-lg bg-muted text-foreground flex items-center justify-center font-bold text-xs shrink-0">
                      <Receipt className="size-4 text-emerald-500" />
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="font-semibold text-foreground truncate">
                        {tx.description || 'Ledger Transaction'}
                      </span>
                      <span className="text-[10px] text-muted-foreground font-mono">
                        {tx.occurred_date} • {tx.transaction_type?.toUpperCase()}
                      </span>
                    </div>
                  </div>

                  <span className="font-mono font-bold text-xs text-foreground shrink-0">
                    {formatCurrency(amount)}
                  </span>
                </div>
              )
            })
          )}
        </div>
      </Card>

      {/* Dialog Modals */}
      <RecordExpenseDialog
        open={recordExpenseOpen}
        onOpenChange={setRecordExpenseOpen}
        scope={scope}
        onExpenseCreated={loadData}
      />

      <TransferMoneyDialog
        open={transferOpen}
        onOpenChange={setTransferOpen}
        accounts={accounts}
        onTransferCompleted={loadData}
      />

      <CreateCategoryDialog
        open={createCategoryOpen}
        onOpenChange={setCreateCategoryOpen}
        onSuccess={loadData}
      />

      <CreateVendorDialog
        open={createVendorOpen}
        onOpenChange={setCreateVendorOpen}
        onSuccess={loadData}
      />

      {/* Detail Sub-sheets */}
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

      <ExpenseDetailSheet
        open={!!expenseSheetId}
        onOpenChange={(op) => !op && setExpenseSheetId(null)}
        expense={expenseSheetId ? { id: expenseSheetId, amount: 0 } : null}
      />
    </div>
  )
}
