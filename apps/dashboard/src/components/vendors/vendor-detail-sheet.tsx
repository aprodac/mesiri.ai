import * as React from 'react'
import {
  Store,
  Search,
  ExternalLink,
  Calendar,
  Receipt,
} from 'lucide-react'
import {
  Sheet,
  SheetContent,
} from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { fetchExpensesApi, type VendorItem } from '@/lib/api'
import { Link } from 'react-router-dom'
import { VendorRates } from '@/components/rates/vendor-rates'

interface VendorDetailSheetProps {
  vendor: VendorItem | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

export function VendorDetailSheet({
  vendor,
  open,
  onOpenChange,
}: VendorDetailSheetProps) {
  const [expenses, setExpenses] = React.useState<any[]>([])
  const [loading, setLoading] = React.useState(false)
  const [search, setSearch] = React.useState('')

  React.useEffect(() => {
    if (!open || !vendor?.id) return
    let active = true
    const vendorId = vendor.id
    async function loadVendorExpenses() {
      setLoading(true)
      try {
        const data = await fetchExpensesApi({ vendor_id: vendorId })
        if (active && Array.isArray(data)) {
          setExpenses(data)
        }
      } catch (err) {
        console.warn('Failed to load vendor expenses:', err)
        if (active) setExpenses([])
      } finally {
        if (active) setLoading(false)
      }
    }
    loadVendorExpenses()
    return () => {
      active = false
    }
  }, [open, vendor?.id])

  const filteredExpenses = React.useMemo(() => {
    return expenses.filter(
      (e) =>
        (e.description || '').toLowerCase().includes(search.toLowerCase()) ||
        (e.id || '').toLowerCase().includes(search.toLowerCase()) ||
        (e.source || '').toLowerCase().includes(search.toLowerCase())
    )
  }, [expenses, search])

  const totalFilteredAmount = React.useMemo(() => {
    return filteredExpenses.reduce((acc, curr) => acc + (parseFloat(curr.amount) || 0), 0)
  }, [filteredExpenses])

  if (!vendor) return null

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-md w-full p-0 flex flex-col gap-0 bg-background overflow-hidden border-l">
        {/* Header */}
        <div className="p-5 border-b bg-muted/30">
          <div className="flex items-center justify-between gap-2 mb-2">
            <div className="flex items-center gap-2">
              <div className="size-8 rounded-lg bg-indigo-500/10 text-indigo-600 flex items-center justify-center font-bold text-xs shrink-0">
                <Store className="size-4" />
              </div>
              <div>
                <h2 className="text-base font-bold text-foreground leading-snug">
                  {vendor.name}
                </h2>
                <span className="text-xs text-muted-foreground">
                  Vendor Transaction Ledger
                </span>
              </div>
            </div>
            <Badge
              className={
                vendor.status === 'active'
                  ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20 text-[10px]'
                  : 'bg-muted text-muted-foreground text-[10px]'
              }
            >
              {vendor.status.toUpperCase()}
            </Badge>
          </div>

          {/* Quick Metrics Cards */}
          <div className="grid grid-cols-2 gap-2 mt-4 pt-3 border-t">
            <div className="p-2.5 rounded-lg border bg-card/60">
              <span className="text-[10px] text-muted-foreground uppercase font-semibold block">
                Total Invoices
              </span>
              <div className="font-bold font-mono text-base text-foreground mt-0.5">
                {expenses.length} Records
              </div>
            </div>
            <div className="p-2.5 rounded-lg border bg-card/60">
              <span className="text-[10px] text-muted-foreground uppercase font-semibold block">
                Total Disbursements
              </span>
              <div className="font-bold font-mono text-base text-indigo-600 dark:text-indigo-400 mt-0.5">
                {formatCurrency(vendor.total_amount_paid || totalFilteredAmount)}
              </div>
            </div>
          </div>
        </div>

        {/* PRC-16: what this supplier charged, item by item, against the cheapest */}
        <VendorRates vendorId={vendor.id} onNavigate={() => onOpenChange(false)} />

        {/* Search & Expense List */}
        <div className="p-4 flex-1 flex flex-col gap-3 overflow-hidden">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
            <Input
              placeholder="Search vendor payments..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-8 text-xs"
            />
          </div>

          <div className="flex-1 overflow-y-auto flex flex-col gap-2 pr-0.5">
            {loading ? (
              <div className="py-12 text-center text-xs text-muted-foreground">
                Loading vendor transactions...
              </div>
            ) : filteredExpenses.length === 0 ? (
              <div className="py-12 text-center text-xs text-muted-foreground border rounded-lg bg-card/40">
                No payment transactions recorded for this vendor.
              </div>
            ) : (
              filteredExpenses.map((exp: any, idx: number) => {
                const amount = parseFloat(exp.amount) || 0
                const expNumber = `EXP-${String(exp.id || '').slice(0, 4).toUpperCase() || 1000 + idx}`
                return (
                  <div
                    key={exp.id || idx}
                    className="p-3 rounded-lg border bg-card/60 hover:bg-card transition-colors flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="size-8 rounded-full bg-indigo-500/10 text-indigo-600 flex items-center justify-center shrink-0">
                        <Receipt className="size-4" />
                      </div>
                      <div className="flex flex-col min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="font-semibold text-foreground truncate">
                            {exp.description || 'Vendor Expense'}
                          </span>
                          <span className="text-[10px] font-mono text-muted-foreground">
                            {expNumber}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-[10px] text-muted-foreground mt-0.5">
                          <span className="flex items-center gap-1">
                            <Calendar className="size-3" />
                            {exp.occurred_date}
                          </span>
                          <span>•</span>
                          <span className="capitalize">{exp.source || 'web'}</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-col items-end shrink-0">
                      <span className="font-mono font-bold text-xs text-foreground">
                        {formatCurrency(amount)}
                      </span>
                      <Badge
                        variant="outline"
                        className={
                          exp.payment_status === 'paid'
                            ? 'border-emerald-500/30 text-emerald-600 text-[9px] px-1 py-0'
                            : 'border-amber-500/30 text-amber-600 text-[9px] px-1 py-0'
                        }
                      >
                        {exp.payment_status?.toUpperCase() || 'CONFIRMED'}
                      </Badge>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="p-3 border-t bg-muted/20 flex items-center justify-between text-xs">
          <span className="text-muted-foreground">
            Showing {filteredExpenses.length} of {expenses.length} records
          </span>
          <Link
            to="/finance/expenses"
            onClick={() => onOpenChange(false)}
            className="text-xs text-blue-600 dark:text-blue-400 font-semibold hover:underline flex items-center gap-1"
          >
            All Expenses <ExternalLink className="size-3" />
          </Link>
        </div>
      </SheetContent>
    </Sheet>
  )
}
