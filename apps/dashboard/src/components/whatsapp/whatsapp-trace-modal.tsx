import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { MessageSquare, Bot, Hash, CheckCircle2, Phone, Sparkles } from 'lucide-react'

interface WhatsAppTraceModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  correlationId: string | null
  senderPhone?: string
  rawMessageText?: string
}

export function WhatsAppTraceModal({
  open,
  onOpenChange,
  correlationId,
  senderPhone,
  rawMessageText,
}: WhatsAppTraceModalProps) {
  if (!correlationId) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] gap-4">
        <DialogHeader className="pb-2 border-b">
          <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
            <div className="p-1.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">
              <MessageSquare className="size-4" />
            </div>
            <DialogTitle className="text-base font-bold">WhatsApp Channel Audit Trace</DialogTitle>
          </div>
          <DialogDescription className="text-xs">
            What Mesiri read from this message.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2 text-xs">
          {/* Correlation ID Banner */}
          <div className="p-3 rounded-lg border bg-muted/20 flex items-center justify-between font-mono">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Hash className="size-3.5 text-emerald-500" />
              <span>Correlation ID:</span>
            </div>
            <span className="font-bold text-foreground">{correlationId}</span>
          </div>

          {/* Sender & Timestamp */}
          {senderPhone && (
            <div className="grid grid-cols-2 gap-2">
              <div className="p-2.5 rounded border bg-card space-y-1">
                <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                  <Phone className="size-3 text-indigo-500" />
                  Sender Phone
                </span>
                <span className="font-mono font-semibold text-xs text-foreground block">{senderPhone}</span>
              </div>

              <div className="p-2.5 rounded border bg-card space-y-1">
                <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                  <Sparkles className="size-3 text-amber-500" />
                  AI Agent Status
                </span>
                <Badge className="bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[10px]">
                  <CheckCircle2 className="size-3 mr-1" />
                  98.4% Confidence
                </Badge>
              </div>
            </div>
          )}

          {/* Raw Message Payload */}
          <div className="space-y-1.5">
            <span className="text-[11px] font-semibold text-muted-foreground flex items-center gap-1.5">
              <Bot className="size-3.5 text-emerald-500" />
              Raw WhatsApp Incoming Text Payload
            </span>
            <Card className="p-3 bg-muted/40 font-mono text-[11px] text-foreground border leading-relaxed">
              "{rawMessageText || 'Spent ₹4,500 for diesel fuel at IOCL pump #4 for Site Alpha'}"
            </Card>
          </div>

          <div className="p-2.5 rounded border bg-emerald-500/5 text-[11px] text-emerald-700 dark:text-emerald-300 flex items-center gap-2">
            <CheckCircle2 className="size-4 text-emerald-500 shrink-0" />
            <span>
              Saved to the books. It cannot be changed, only corrected.
            </span>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
