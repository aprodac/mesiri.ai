import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { BadgeCheck, FilePlus2, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { documentError, fetchDocument } from '@/lib/documents'
import { CERTIFICATE_KINDS, addGrnCertificate, type GoodsReceipt } from '@/lib/orders'

// PRC-52: a delivery's test certificates (mill test, cement test, RMC batch / cube) on its GRN. They are kept in the
// project's documents register (test-reports folder), so they also show on the project's Documents page. Steel,
// cement and RMC get a gentle "No test certificate yet": never a blocker.

export function GrnCertificates({ grn }: { grn: GoodsReceipt }) {
  const [adding, setAdding] = React.useState(false)
  const certificates = grn.certificates ?? []
  const open = async (id: string) => {
    const doc = await fetchDocument(id)
    if (doc.url) window.open(doc.url, '_blank', 'noopener')
  }
  return (
    <div className="flex flex-col gap-1">
      {certificates.map((c) => (
        <button key={c.id} type="button" onClick={() => open(c.id)} className="inline-flex w-fit max-w-full items-center gap-1.5 text-left text-xs font-medium text-emerald-800 underline-offset-2 hover:underline dark:text-emerald-300">
          <BadgeCheck className="size-3.5 shrink-0" /><span className="truncate">{c.title}{c.notes ? ` · ${c.notes}` : ''}</span>
        </button>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        {certificates.length === 0 && grn.needs_certificate && (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" data-testid="no-certificate"><FileText className="size-3.5" /> No test certificate yet</span>
        )}
        <Button type="button" variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={() => setAdding(true)}><FilePlus2 className="size-3.5" /> Add certificate</Button>
      </div>
      <AddCertificateDialog grn={grn} open={adding} onClose={() => setAdding(false)} />
    </div>
  )
}

function AddCertificateDialog({ grn, open, onClose }: { grn: GoodsReceipt; open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [kind, setKind] = React.useState<string>('other')
  const [file, setFile] = React.useState<File | null>(null)
  const [number, setNumber] = React.useState('')
  const [batch, setBatch] = React.useState('')
  React.useEffect(() => {
    if (open) { setFile(null); setNumber(''); setBatch('') }
  }, [open])
  const save = useMutation({
    mutationFn: () => addGrnCertificate(grn.id, file!, { kind, number: number.trim(), batch: batch.trim() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['procurement'] })
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      toast.success('Certificate kept', `On ${grn.ref} and in ${grn.project_name}'s Documents (test reports)`)
      onClose()
    },
    onError: (e) => toast.error('Not saved', documentError(e)),
  })
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add certificate to {grn.ref}</DialogTitle>
          <DialogDescription>{grn.vendor_name} · {grn.lines.map((l) => l.material).join(', ')}</DialogDescription>
        </DialogHeader>
        <form id="grn-cert" className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (file) save.mutate() }}>
          <div className="flex flex-col gap-1.5">
            <Label>Kind</Label>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{CERTIFICATE_KINDS.map((k) => <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="grn-cert-file">Photo or PDF</Label>
            <Input id="grn-cert-file" type="file" accept="application/pdf,image/*" capture="environment" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="grn-cert-no">Certificate no. <span className="font-normal text-muted-foreground">(optional)</span></Label>
              <Input id="grn-cert-no" value={number} maxLength={60} onChange={(e) => setNumber(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="grn-cert-batch">Heat / batch no. <span className="font-normal text-muted-foreground">(optional)</span></Label>
              <Input id="grn-cert-batch" value={batch} maxLength={60} onChange={(e) => setBatch(e.target.value)} />
            </div>
          </div>
        </form>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="grn-cert" disabled={!file || save.isPending}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
