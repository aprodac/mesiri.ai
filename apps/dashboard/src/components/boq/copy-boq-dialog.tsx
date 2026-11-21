import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { copyBoqFrom } from '@/lib/boq'
import { fetchProjectsFull, type Project } from '@/lib/projects'

/**
 * PS phase 2: start a BOQ from an earlier project's (the way ERPs copy an estimate): sections, lines, rates and
 * materials per unit. Never overwrites: lines this BOQ already has are kept as they are (the server counts them).
 */
export function CopyBoqDialog({ projectId, open, onOpenChange }: { projectId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const projects = useQuery<Project[]>({ queryKey: ['projects-list'], queryFn: fetchProjectsFull, enabled: open })
  const [source, setSource] = React.useState('')
  const [withQuantities, setWithQuantities] = React.useState(true)
  const [withRates, setWithRates] = React.useState(true)
  const [error, setError] = React.useState('')
  const others = (projects.data ?? []).filter((p) => p.id !== projectId)

  const copy = useMutation({
    mutationFn: () => copyBoqFrom(projectId, { source_project_id: source, with_quantities: withQuantities, with_rates: withRates }),
    onSuccess: (r) => {
      for (const k of ['boq', 'schedule', 'project-start', 'lifecycle']) queryClient.invalidateQueries({ queryKey: [k] })
      toast.success(
        `${r.lines_added} line${r.lines_added === 1 ? '' : 's'} copied`,
        [r.sections_added && `${r.sections_added} new sections`, r.material_lines && `materials per unit on ${r.material_lines}`,
          r.lines_kept && `${r.lines_kept} already here, kept`].filter(Boolean).join(' · ') || undefined,
      )
      onOpenChange(false)
    },
    onError: (e: any) => setError(e?.response?.data?.detail || 'The BOQ could not be copied. Try again.'),
  })

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { setSource(''); setError('') } onOpenChange(o) }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Copy className="size-4" /> Copy the BOQ from a past project</DialogTitle>
          <DialogDescription>Sections, lines, rates and materials per unit come across. Lines already here stay as they are.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-1.5">
            <Label>From</Label>
            {others.length === 0 && !projects.isLoading ? (
              <p className="text-sm text-muted-foreground">No other project yet.</p>
            ) : (
              <Select value={source} onValueChange={(v) => { setSource(v); setError('') }}>
                <SelectTrigger className="h-10"><SelectValue placeholder="Choose a project" /></SelectTrigger>
                <SelectContent>{others.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
              </Select>
            )}
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5 size-4" checked={withRates} onChange={(e) => setWithRates(e.target.checked)} />
            <span><span className="font-medium">Keep the rates</span><span className="block text-xs text-muted-foreground">Client and budget rates. Off: price them again for this project.</span></span>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5 size-4" checked={withQuantities} onChange={(e) => setWithQuantities(e.target.checked)} />
            <span><span className="font-medium">Keep the quantities</span><span className="block text-xs text-muted-foreground">Off: each line comes in at 1 unit, to measure for this project.</span></span>
          </label>
          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => copy.mutate()} disabled={!source || copy.isPending}>{copy.isPending ? 'Copying…' : 'Copy the BOQ'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
