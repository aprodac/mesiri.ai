import {
  Wallet,
  Building2,
  User,
  ShieldCheck,
  ArrowUpRight,
  ArrowDownLeft,
  AlertTriangle,
  Download,
} from 'lucide-react'
import {
  Sheet,
  SheetContent,
} from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Separator } from '@/components/ui/separator'

import { useNavigate } from 'react-router-dom'
import * as React from 'react'
import { exportCsv } from '@/lib/export'
import { fetchVouchersApi } from '@/lib/api'

interface CashBoxDetailSheetProps {
  cashBox: any | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onReplenishClick?: (cashBox: any) => void
}

export function CashBoxDetailSheet({
  cashBox,
  open,
  onOpenChange,
  onReplenishClick,
}: CashBoxDetailSheetProps) {
  const navigate = useNavigate()
  const [vouchers, setVouchers] = React.useState<any[]>([])
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    if (!open || !cashBox?.id) return
    let active = true
    async function loadVouchers() {
      setLoading(true)
      try {
        const data = await fetchVouchersApi(cashBox.id)
        if (active && Array.isArray(data)) {
          setVouchers(data)
        }
      } catch (err) {
        console.warn('Failed to load live cash box vouchers:', err)
        if (active) setVouchers([])
      } finally {
        if (active) setLoading(false)
      }
    }
    loadVouchers()
    return () => {
      active = false
    }
  }, [open, cashBox?.id])

  if (!cashBox) return null

  const isLow = cashBox.current_balance < 50000

  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(val || 0)
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-[480px] w-full p-0 flex flex-col gap-0 overflow-y-auto">
        {/* Header Banner */}
        <div className="p-5 border-b bg-gradient-to-r from-amber-500/10 via-muted/30 to-transparent flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-md bg-background border shadow-2xs text-amber-500">
                <Wallet className="size-4" />
              </div>
              <span className="font-semibold text-sm text-foreground">{cashBox.name}</span>
            </div>

            <div className="flex items-center gap-1.5">
              {isLow && (
                <Badge className="bg-rose-500/15 text-rose-700 dark:text-rose-400 border-rose-500/20 text-[10px] gap-1">
                  <AlertTriangle className="size-3" /> Low Float
                </Badge>
              )}
              <Badge className="bg-amber-500/15 text-amber-700 dark:text-amber-300 font-semibold text-[10px]">
                Site Float
              </Badge>
            </div>
          </div>

          <div className="flex items-end justify-between pt-1">
            <div>
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">
                Available Cash Float Balance
              </span>
              <div className={`text-2xl font-bold font-mono tracking-tight ${isLow ? 'text-rose-600 dark:text-rose-400' : 'text-foreground'}`}>
                {formatCurrency(cashBox.current_balance)}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5 font-medium">
                Custodian: <strong className="text-foreground">{cashBox.custodian_name}</strong>
              </p>
            </div>

            {onReplenishClick && (
              <Button
                size="sm"
                className="h-8 gap-1 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white"
                onClick={() => onReplenishClick(cashBox)}
              >
                Top-Up Float
              </Button>
            )}
          </div>
        </div>

        {/* Content Tabs */}
        <div className="p-5 flex-1 flex flex-col gap-4">
          <Tabs defaultValue="ledger" className="w-full">
            <TabsList className="w-full grid grid-cols-2 h-9">
              <TabsTrigger value="ledger" className="text-xs">
                Cash-In / Cash-Out Ledger
              </TabsTrigger>
              <TabsTrigger value="details" className="text-xs">
                Custodian & Scope
              </TabsTrigger>
            </TabsList>

            {/* Ledger Tab */}
            <TabsContent value="ledger" className="pt-3 flex flex-col gap-2.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                  Recent Cash Transactions
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 text-[11px] text-muted-foreground gap-1"
                  disabled={vouchers.length === 0}
                  onClick={() =>
                    exportCsv(
                      `${cashBox.name} cash book.csv`,
                      ['Date', 'Kind', 'Amount', 'Description'],
                      vouchers.map((tx: any) => [String(tx.occurred_date ?? tx.transaction_date ?? tx.created_at ?? '').slice(0, 10), tx.transaction_type ?? '', tx.amount ?? '', tx.description ?? tx.notes ?? '']),
                    )
                  }
                >
                  <Download className="size-3" /> CSV Export
                </Button>
              </div>

              <div className="flex flex-col gap-2">
                {loading ? (
                  <div className="text-center py-6 text-muted-foreground text-xs">Loading float activity...</div>
                ) : vouchers.length === 0 ? (
                  <div className="text-center py-6 border rounded-lg bg-card/40 text-muted-foreground text-xs">
                    No vouchers recorded for this cash box yet.
                  </div>
                ) : (
                  vouchers.map((tx) => {
                    const isInflow = tx.to_account_id === cashBox.id || tx.transaction_type === 'fund_received'
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
                              isInflow
                                ? 'bg-emerald-500/10 text-emerald-600'
                                : 'bg-rose-500/10 text-rose-600'
                            }`}
                          >
                            {isInflow ? (
                              <ArrowDownLeft className="size-3.5" />
                            ) : (
                              <ArrowUpRight className="size-3.5" />
                            )}
                          </div>
                          <div className="flex flex-col min-w-0">
                            <span className="font-semibold text-foreground group-hover:text-emerald-600 transition-colors truncate">
                              {tx.description || tx.transaction_type.replace('_', ' ').toUpperCase()}
                            </span>
                            <span className="text-[10px] text-muted-foreground">
                              {tx.occurred_date} • {tx.source_type || 'Voucher'}
                            </span>
                          </div>
                        </div>
                        <div
                          className={`font-mono font-bold text-xs shrink-0 ${
                            isInflow ? 'text-emerald-600' : 'text-foreground'
                          }`}
                        >
                          {isInflow ? '+' : '-'}{formatCurrency(parseFloat(tx.amount))}
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </TabsContent>

            {/* Details Tab */}
            <TabsContent value="details" className="pt-3 flex flex-col gap-3 text-xs">
              <div className="grid grid-cols-2 gap-3 p-3 rounded-lg border bg-card/60">
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold block mb-0.5">
                    Assigned Project
                  </span>
                  <div className="font-medium flex items-center gap-1.5 text-foreground truncate">
                    <Building2 className="size-3.5 text-amber-500" />
                    {cashBox.project_name}
                  </div>
                </div>

                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold block mb-0.5">
                    Site Location
                  </span>
                  <div className="font-medium text-foreground">{cashBox.site_name || 'Main Site'}</div>
                </div>

                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold block mb-0.5">
                    Opening Float
                  </span>
                  <div className="font-medium font-mono text-foreground">{formatCurrency(cashBox.opening_balance || 150000)}</div>
                </div>

                <div>
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold block mb-0.5">
                    Disbursed This Month
                  </span>
                  <div className="font-medium font-mono text-rose-600">{formatCurrency(cashBox.disbursed_month || 45000)}</div>
                </div>
              </div>

              <Separator />

              <div className="flex flex-col gap-2">
                <h4 className="font-semibold text-foreground text-xs flex items-center gap-1.5">
                  <ShieldCheck className="size-4 text-emerald-500" />
                  Custodian & Site Manager Info
                </h4>
                <div className="flex flex-col gap-1.5 text-muted-foreground bg-muted/20 p-2.5 rounded border text-[11px]">
                  <div className="flex justify-between items-center">
                    <span>Cash Box Custodian:</span>
                    <span className="font-semibold text-foreground flex items-center gap-1">
                      <User className="size-3 text-muted-foreground" />
                      {cashBox.custodian_name}
                    </span>
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
