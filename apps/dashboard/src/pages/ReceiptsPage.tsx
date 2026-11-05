import * as React from 'react'
import { Image as ImageIcon, Calendar, Store, Tag } from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { fetchAllExpenseAttachmentsApi, type ExpenseAttachmentGalleryApiItem } from '@/lib/api'
import { toLocalISODate } from '@/lib/utils'

export default function ReceiptsPage() {
  const { scope } = useScope()
  const [items, setItems] = React.useState<ExpenseAttachmentGalleryApiItem[]>([])
  const [loading, setLoading] = React.useState(true)
  const [datePreset, setDatePreset] = React.useState<'ALL' | 'TODAY' | 'THIS_MONTH'>('ALL')
  const [selected, setSelected] = React.useState<ExpenseAttachmentGalleryApiItem | null>(null)

  React.useEffect(() => {
    let active = true
    async function load() {
      setLoading(true)
      const today = new Date()
      const params: Parameters<typeof fetchAllExpenseAttachmentsApi>[0] = {
        project_id: scope.mode !== 'portfolio' ? scope.projectId : undefined,
        site_id: scope.mode === 'site' ? scope.siteId : undefined,
        limit: 100,
      }
      if (datePreset === 'TODAY') {
        const iso = toLocalISODate(today)
        params.start_date = iso
        params.end_date = iso
      } else if (datePreset === 'THIS_MONTH') {
        params.start_date = `${today.toISOString().slice(0, 7)}-01`
      }
      try {
        const data = await fetchAllExpenseAttachmentsApi(params)
        if (active) setItems(data)
      } catch (err) {
        console.warn('Receipt gallery fetch error:', err)
        if (active) setItems([])
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [scope, datePreset])


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
            <h1 className="text-2xl font-semibold tracking-tight">Receipts</h1>
          </div>
        </div>

        <Select value={datePreset} onValueChange={(v) => setDatePreset(v as typeof datePreset)}>
          <SelectTrigger className="h-8 w-[160px] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All Time</SelectItem>
            <SelectItem value="TODAY">Today</SelectItem>
            <SelectItem value="THIS_MONTH">This Month</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <p className="text-xs text-muted-foreground -mt-1">
        Every receipt photo captured via WhatsApp, in one place — {items.length} shown
        {items.length >= 100 && ' (showing the most recent 100)'}.
      </p>

      {/* Gallery */}
      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="aspect-square rounded-lg bg-muted animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-20 text-center border border-dashed rounded-lg">
          <ImageIcon className="size-8 text-muted-foreground/50" />
          <p className="text-sm font-medium text-muted-foreground">No receipts yet</p>
          <p className="text-xs text-muted-foreground/70 max-w-xs">
            Receipts captured via the WhatsApp assistant's image-purpose picker (tap "Expense" on
            a photo) will show up here automatically.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setSelected(item)}
              className="group relative aspect-square rounded-lg overflow-hidden border border-border bg-muted text-left focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <img
                src={item.url}
                alt={item.description || 'Receipt'}
                className="size-full object-cover transition-transform group-hover:scale-105"
                loading="lazy"
              />
              <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-2 pt-4 pb-1.5">
                <p className="text-[11px] font-semibold text-white truncate">
                  {formatCurrency(item.amount)}
                </p>
                <p className="text-[10px] text-white/70 truncate">
                  {item.vendor_name || item.category_name || '—'}
                </p>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Receipt Lightbox */}
      <Dialog open={!!selected} onOpenChange={() => setSelected(null)}>
        <DialogContent className="sm:max-w-[500px] p-2">
          <DialogHeader className="px-3 pt-2">
            <DialogTitle className="text-sm font-semibold flex items-center gap-1.5">
              <ImageIcon className="size-4 text-emerald-500" />
              Receipt / Invoice Attachment
            </DialogTitle>
          </DialogHeader>
          {selected && (
            <div className="flex flex-col gap-2">
              <div className="p-2 flex items-center justify-center bg-black/90 rounded-md overflow-hidden">
                <img
                  src={selected.url}
                  alt="Receipt Attachment"
                  className="max-h-[400px] w-auto object-contain rounded"
                />
              </div>
              <div className="px-2 pb-2 flex flex-col gap-1 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-foreground">
                    {formatCurrency(selected.amount)}
                  </span>
                  <span className="flex items-center gap-1 text-muted-foreground">
                    <Calendar className="size-3" />
                    {selected.occurred_date}
                  </span>
                </div>
                {selected.description && (
                  <p className="text-muted-foreground">{selected.description}</p>
                )}
                <div className="flex items-center justify-between gap-3 text-muted-foreground pt-1 border-t">
                  <div className="flex items-center gap-3">
                    {selected.vendor_name && (
                      <span className="flex items-center gap-1">
                        <Store className="size-3" /> {selected.vendor_name}
                      </span>
                    )}
                    {selected.category_name && (
                      <span className="flex items-center gap-1">
                        <Tag className="size-3" /> {selected.category_name}
                      </span>
                    )}
                  </div>

                  <a
                    href={`/finance/expenses?id=${selected.expense_id}`}
                    className="text-[11px] font-semibold text-emerald-600 hover:text-emerald-700 flex items-center gap-1"
                  >
                    View Expense #{selected.expense_id.slice(0, 8)} →
                  </a>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
