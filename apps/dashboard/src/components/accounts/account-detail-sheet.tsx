import { useNavigate } from 'react-router-dom'
import {
  Landmark,
  Wallet,
  CreditCard,
  Building2,
  User,
  ShieldCheck,
  ArrowUpRight,
  ArrowDownLeft,
  Download,
  AlertTriangle,
} from 'lucide-react'
import {
  Sheet,
  SheetContent,
} from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Separator } from '@/components/ui/separator'

interface AccountDetailSheetProps {
  account: any | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onDepositClick?: (account: any) => void
  onTransferClick?: (account: any) => void
}

import * as React from 'react'
import { exportCsv } from '@/lib/export'
import { fetchAccountTransactionsApi } from '@/lib/api'

export function AccountDetailSheet({
  account,
  open,
  onOpenChange,
  onDepositClick,
}: AccountDetailSheetProps) {
  const navigate = useNavigate()
  const [transactions, setTransactions] = React.useState<any[]>([])
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    let active = true
    async function loadTx() {
      if (!account?.id) return
      setLoading(true)
      try {
        const list = await fetchAccountTransactionsApi(account.id)
        if (active && Array.isArray(list)) setTransactions(list)
      } catch (err) {
        console.warn('Failed to load account transactions:', err)
        if (active) setTransactions([])
      } finally {
        if (active) setLoading(false)
      }
    }
    if (open) loadTx()
    return () => {
      active = false
    }
  }, [open, account?.id])

  if (!account) return null

  const isLowBalance = account.current_balance < 50000

  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: account.currency || 'INR',
      maximumFractionDigits: 2,
    }).format(val || 0)
  }

  const getAccountTypeIcon = (type: string) => {
    switch (type) {
      case 'bank':
      case 'bank_account':
        return <Landmark className="size-4 text-emerald-500" />
      case 'cash':
        return <Wallet className="size-4 text-amber-500" />
      case 'employee_advance':
      case 'petty_cash':
        return <Wallet className="size-4 text-purple-500" />
      case 'corporate_card':
        return <CreditCard className="size-4 text-indigo-500" />
      default:
        return <Landmark className="size-4 text-cyan-500" />
    }
  }

  // WEB-48: a real statement (it used to only show "Exporting...").
  const exportTx = (rows: any[], name: string) =>
    exportCsv(
      name,
      ['Date', 'Kind', 'Amount', 'Description'],
      rows.map((tx) => [String(tx.occurred_date ?? tx.transaction_date ?? tx.created_at ?? '').slice(0, 10), tx.transaction_type ?? '', tx.amount ?? '', tx.description ?? tx.notes ?? '']),
    )
  const handleExportStatement = () => exportTx(transactions, `${account.name} statement.csv`)

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-[480px] w-full p-0 flex flex-col gap-0 overflow-y-auto">
        {/* Header Banner */}
        <div className="p-5 border-b bg-muted/30 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-md bg-background border shadow-2xs">
                {getAccountTypeIcon(account.account_type)}
              </div>
              <span className="font-semibold text-sm text-foreground">{account.name}</span>
            </div>

            <div className="flex items-center gap-1.5">
              {isLowBalance && (
                <Badge className="bg-rose-500/15 text-rose-700 dark:text-rose-400 border-rose-500/20 text-[10px] gap-1">
                  <AlertTriangle className="size-3" /> Low Balance
                </Badge>
              )}
              <Badge
                className={
                  account.status === 'active'
                    ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 font-semibold'
                    : 'bg-muted text-muted-foreground font-semibold'
                }
              >
                {account.status === 'active' ? 'Active' : 'Inactive'}
              </Badge>
            </div>
          </div>

          <div className="flex items-end justify-between">
            <div>
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">
                Current Available Balance
              </span>
              <div className="text-2xl font-bold font-mono text-foreground tracking-tight">
                {formatCurrency(account.current_balance)}
              </div>
              {account.account_number_masked && (
                <p className="text-xs font-mono text-muted-foreground mt-0.5">
                  {account.account_number_masked}
                </p>
              )}
            </div>

            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5 text-xs font-medium"
              onClick={handleExportStatement}
            >
              <Download className="size-3.5" />
              Statement
            </Button>
          </div>
        </div>

        {/* Content Tabs */}
        <div className="p-5 flex-1 flex flex-col gap-4">
          <Tabs defaultValue="transactions" className="w-full">
            <TabsList className="w-full grid grid-cols-2 h-9">
              <TabsTrigger value="transactions" className="text-xs">
                Ledger Activity
              </TabsTrigger>
              <TabsTrigger value="overview" className="text-xs">
                Scope & Custodian
              </TabsTrigger>
            </TabsList>

            {/* Ledger Transactions Tab */}
            <TabsContent value="transactions" className="pt-3 flex flex-col gap-2.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                  Recent Transactions
                </span>
                {onDepositClick && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 text-[11px] text-emerald-600 font-semibold hover:bg-emerald-500/10"
                    onClick={() => onDepositClick(account)}
                  >
                    + Add Funds
                  </Button>
                )}
              </div>

              <div className="flex flex-col gap-2">
                {loading ? (
                  <div className="text-center py-6 text-muted-foreground text-xs">Loading ledger activity...</div>
                ) : transactions.length === 0 ? (
                  <div className="text-center py-6 border rounded-lg bg-card/40 text-muted-foreground text-xs">
                    No transactions recorded for this account yet.
                  </div>
                ) : (
                  transactions.map((tx) => {
                    const isInbound = tx.to_account_id === account.id || tx.transaction_type === 'fund_received'
                    const targetExpenseId = tx.source_id || tx.id
                    return (
                      <div
                        key={tx.id}
                        onClick={() => {
                          onOpenChange(false)
                          navigate(`/finance/expenses/${targetExpenseId}`)
                        }}
                        className="flex items-center justify-between p-2.5 rounded-lg border bg-card/60 hover:bg-muted/40 hover:border-emerald-500/50 cursor-pointer transition-all group"
                      >
                        <div className="flex items-center gap-2.5">
                          <div
                            className={`size-7 rounded-full flex items-center justify-center shrink-0 ${
                              isInbound
                                ? 'bg-emerald-500/10 text-emerald-600'
                                : 'bg-rose-500/10 text-rose-600'
                            }`}
                          >
                            {isInbound ? (
                              <ArrowDownLeft className="size-3.5" />
                            ) : (
                              <ArrowUpRight className="size-3.5" />
                            )}
                          </div>
                          <div className="flex flex-col min-w-0">
                            <span className="font-semibold text-foreground group-hover:text-emerald-600 transition-colors truncate">
                              {tx.description || `${tx.transaction_type.replace('_', ' ').toUpperCase()}`}
                            </span>
                            <span className="text-[10px] text-muted-foreground">
                              {tx.occurred_date} • {tx.source_type || tx.transaction_type}
                            </span>
                          </div>
                        </div>
                        <div
                          className={`font-mono font-bold text-xs shrink-0 ${
                            isInbound ? 'text-emerald-600' : 'text-foreground'
                          }`}
                        >
                          {isInbound ? '+' : '-'}{formatCurrency(parseFloat(tx.amount))}
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </TabsContent>

            {/* Overview & Scope Tab */}
            <TabsContent value="overview" className="pt-3 flex flex-col gap-3 text-xs">
              <div className="grid grid-cols-2 gap-3 p-3 rounded-lg border bg-card/60">
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold block mb-0.5">
                    Account Type
                  </span>
                  <div className="font-medium text-foreground uppercase">{account.account_type.replace('_', ' ')}</div>
                </div>

                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold block mb-0.5">
                    Opening Balance
                  </span>
                  <div className="font-medium font-mono text-foreground">{formatCurrency(account.opening_balance)}</div>
                </div>

                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold block mb-0.5">
                    Project Scope
                  </span>
                  <div className="font-medium flex items-center gap-1.5 text-foreground truncate">
                    <Building2 className="size-3.5 text-amber-500" />
                    {account.project_name || 'Org Wide'}
                  </div>
                </div>

                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold block mb-0.5">
                    Site Location
                  </span>
                  <div className="font-medium flex items-center gap-1.5 text-foreground truncate">
                    <Building2 className="size-3.5 text-indigo-500" />
                    {account.site_name || 'All Sites'}
                  </div>
                </div>
              </div>

              <Separator />

              <div className="flex flex-col gap-2">
                <h4 className="font-semibold text-foreground text-xs flex items-center gap-1.5">
                  <ShieldCheck className="size-4 text-emerald-500" />
                  Custodian & Audit Info
                </h4>
                <div className="flex flex-col gap-1.5 text-muted-foreground bg-muted/20 p-2.5 rounded border text-[11px]">
                  <div className="flex justify-between">
                    <span>Account Custodian:</span>
                    <span className="font-semibold text-foreground flex items-center gap-1">
                      <User className="size-3 text-muted-foreground" />
                      {account.custodian_name}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Created Date:</span>
                    <span className="font-semibold text-foreground">{account.created_at || '2026-07-01'}</span>
                  </div>
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </SheetContent>
    </Sheet>
  )
}
