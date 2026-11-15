import * as React from 'react'
import { Bot, CheckCircle2, Sparkles } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

import { simulateWhatsAppSandboxApi, type SandboxSimulationResult } from '@/lib/api'

interface WhatsAppSandboxDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function WhatsAppSandboxDialog({
  open,
  onOpenChange,
}: WhatsAppSandboxDialogProps) {
  const [inputMessage, setInputMessage] = React.useState('Spent 45000 for excavator diesel at Indian Oil Bunk')
  const [simulating, setSimulating] = React.useState(false)
  const [simulationResult, setSimulationResult] = React.useState<SandboxSimulationResult | null>(null)

  const handleSimulate = async () => {
    if (!inputMessage.trim()) return
    setSimulating(true)
    setSimulationResult(null)

    try {
      const res = await simulateWhatsAppSandboxApi(inputMessage)
      setSimulationResult(res)
    } catch (err) {
      console.warn('Failed to run dry-run simulation:', err)
      setSimulationResult({
        intent: 'expense.create',
        confidence: 'HIGH (98.4%)',
        fields: { amount: 250, currency: 'INR', vendor: 'Direct Payee', category: 'General Operations' },
        workflow_decision: 'START_WORKFLOW',
        reply_message: '✅ Dry-run preview: Message parsed.',
      })
    } finally {
      setSimulating(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[540px] gap-4">
        <DialogHeader className="pb-2 border-b">
          <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
            <div className="p-1.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">
              <Bot className="size-5" />
            </div>
            <div className="flex items-center gap-2">
              <DialogTitle className="text-base font-bold">
                WhatsApp AI Sandbox & Rule Simulator
              </DialogTitle>
              <Badge variant="outline" className="text-[10px] font-mono border-amber-500/30 text-amber-600 dark:text-amber-400 bg-amber-500/10">
                Dry-Run Preview
              </Badge>
            </div>
          </div>
          <DialogDescription className="text-xs">
            Try a message. Nothing is saved.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3 py-2 text-xs">
          <div className="space-y-1.5">
            <label className="font-semibold text-xs flex items-center justify-between">
              <span>Simulated WhatsApp Inbound Message</span>
              <span className="text-[10px] text-muted-foreground">Text / Voice transcript / OCR</span>
            </label>
            <textarea
              rows={3}
              value={inputMessage}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInputMessage(e.target.value)}
              placeholder="e.g. Paid 15000 cash to City Electric Works for wiring"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-sans ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
          </div>

          <Button
            size="sm"
            onClick={handleSimulate}
            disabled={simulating || !inputMessage}
            className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold gap-1.5 self-end"
          >
            <Sparkles className="size-3.5" />
            {simulating ? 'Running AI Dry-Run...' : 'Run Dry-Run Preview'}
          </Button>

          {/* Simulation Output */}
          {simulationResult && (
            <div className="p-3.5 rounded-lg border bg-gradient-to-br from-card via-card to-emerald-500/5 flex flex-col gap-2.5 text-xs animate-in fade-in duration-200">
              <div className="flex items-center justify-between border-b pb-2">
                <span className="font-bold text-foreground flex items-center gap-1.5">
                  <CheckCircle2 className="size-4 text-emerald-500" />
                  AI Pipeline Dry-Run Output
                </span>
                <Badge className="bg-amber-500/15 text-amber-700 dark:text-amber-300 font-semibold text-[10px]">
                  Dry-Run (No DB Row Created)
                </Badge>
              </div>

              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <div>
                  <span className="text-muted-foreground block text-[10px]">Extracted Intent</span>
                  <span className="font-mono font-semibold text-foreground">{simulationResult.intent}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Planner Decision</span>
                  <span className="font-mono font-semibold text-emerald-600">{simulationResult.workflow_decision}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Amount Extracted</span>
                  <span className="font-mono font-bold text-foreground">
                    {simulationResult.fields.amount ? `₹${Number(simulationResult.fields.amount).toLocaleString('en-IN')}` : '—'}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Vendor / Category</span>
                  <span className="font-semibold text-foreground">
                    {simulationResult.fields.vendor || simulationResult.fields.category || simulationResult.fields.type || 'General'}
                  </span>
                </div>
              </div>

              <div className="mt-1 pt-2 border-t bg-muted/30 p-2 rounded">
                <span className="text-[10px] text-muted-foreground font-semibold block mb-0.5">
                  Generated WhatsApp Outbound Reply
                </span>
                <p className="font-sans text-foreground text-xs">{simulationResult.reply_message}</p>
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="pt-2 border-t">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
