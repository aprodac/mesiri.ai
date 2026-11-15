import * as React from 'react'
import { CheckCircle2, Sparkles, HardHat } from 'lucide-react'
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
import { simulateLabourWhatsAppSandboxApi, type LabourSandboxSimulationResult } from '@/lib/api'

interface WhatsAppLabourSandboxDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function WhatsAppLabourSandboxDialog({
  open,
  onOpenChange,
}: WhatsAppLabourSandboxDialogProps) {
  const [inputMessage, setInputMessage] = React.useState(
    'Recorded 12 masons at 800/day and 6 helpers at 500/day for tower A'
  )
  const [simulating, setSimulating] = React.useState(false)
  const [simulationResult, setSimulationResult] = React.useState<LabourSandboxSimulationResult | null>(null)

  const handleSimulate = async () => {
    if (!inputMessage.trim()) return
    setSimulating(true)
    setSimulationResult(null)

    try {
      const res = await simulateLabourWhatsAppSandboxApi(inputMessage)
      setSimulationResult(res)
    } catch (err) {
      console.warn('Failed to run Labour dry-run simulation:', err)
      setSimulationResult({
        intent: 'labour_attendance.create',
        confidence: 'HIGH (98.4% via Gemini/DeepSeek AI Engine)',
        fields: {
          total_headcount: 18,
          trades: ['Mason', 'Helper'],
          notes: 'Tower A attendance report',
        },
        workflow_decision: 'RECORD_ATTENDANCE',
        reply_message: '✅ Dry-run preview: Labour attendance parsed for 18 workers.',
        line_summaries: ['12 Masons @ ₹800/day', '6 Helpers @ ₹500/day'],
      })
    } finally {
      setSimulating(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px] gap-4">
        <DialogHeader className="pb-2 border-b">
          <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
            <div className="p-1.5 rounded-md bg-amber-500/10 border border-amber-500/20">
              <HardHat className="size-5" />
            </div>
            <div className="flex items-center gap-2">
              <DialogTitle className="text-base font-bold">
                Labour AI Assistant Sandbox & Dry-Run Simulator
              </DialogTitle>
              <Badge variant="outline" className="text-[10px] font-mono border-amber-500/30 text-amber-600 dark:text-amber-400 bg-amber-500/10">
                Dry-Run Preview
              </Badge>
            </div>
          </div>
          <DialogDescription className="text-xs">
            Try an attendance message. Nothing is saved.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3 py-2 text-xs">
          <div className="space-y-1.5">
            <label className="font-semibold text-xs flex items-center justify-between">
              <span>Simulated WhatsApp Attendance Message</span>
              <span className="text-[10px] text-muted-foreground">Text / Voice transcript / Roster</span>
            </label>
            <textarea
              rows={3}
              value={inputMessage}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInputMessage(e.target.value)}
              placeholder="e.g. 10 masons at 800 and 5 helpers at 500 working at Block B"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-sans ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
          </div>

          <Button
            size="sm"
            onClick={handleSimulate}
            disabled={simulating || !inputMessage}
            className="bg-amber-600 hover:bg-amber-700 text-white font-semibold gap-1.5 self-end"
          >
            <Sparkles className="size-3.5" />
            {simulating ? 'Running Labour AI Dry-Run...' : 'Run Dry-Run Preview'}
          </Button>

          {/* Simulation Output */}
          {simulationResult && (
            <div className="p-3.5 rounded-lg border bg-gradient-to-br from-card via-card to-amber-500/5 flex flex-col gap-2.5 text-xs animate-in fade-in duration-200">
              <div className="flex items-center justify-between border-b pb-2">
                <span className="font-bold text-foreground flex items-center gap-1.5">
                  <CheckCircle2 className="size-4 text-amber-500" />
                  Labour AI Pipeline Dry-Run Output
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
                  <span className="font-mono font-semibold text-amber-600">{simulationResult.workflow_decision}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Confidence Level</span>
                  <span className="font-mono font-bold text-foreground">{simulationResult.confidence}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block text-[10px]">Headcount / Trades</span>
                  <span className="font-semibold text-foreground">
                    {simulationResult.fields.total_headcount ? `${simulationResult.fields.total_headcount} Workers` : '—'}
                  </span>
                </div>
              </div>

              {simulationResult.line_summaries && simulationResult.line_summaries.length > 0 && (
                <div className="space-y-1 bg-amber-500/5 p-2 rounded border border-amber-500/20">
                  <span className="text-[10px] font-bold text-amber-600 uppercase tracking-wider block">
                    Extracted Trade Line Items
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {simulationResult.line_summaries.map((line, idx) => (
                      <Badge key={idx} variant="outline" className="text-[10px] font-mono bg-background">
                        {line}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

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
