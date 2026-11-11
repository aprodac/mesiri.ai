import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, FileText, History, Lock, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import { documentError as errorText } from '@/lib/documents'
import { cn } from '@/lib/utils'
import { addVendorPaper, archiveVendorPaper, fetchVendorPapers, paperLink, paperStatusWords, type Paper, type PaperKindRow, type PaperStatus } from '@/lib/vendor-documents'

// PRC-52: Supplier page > Documents -- the supplier's own papers, one card per kind with its status. A new upload of a
// kind replaces the current one (the old one stays in the history); archive keeps the file. Same upload rules as the
// project documents register (photo or PDF, 25 MB).

export const PAPER_TONE: Record<PaperStatus, string> = {
  valid: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300',
  expiring: 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300',
  expired: 'bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300',
  missing: 'bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300',
  none: 'bg-muted text-muted-foreground',
}

function day(iso: string): string {
  return new Date(iso.length > 10 ? iso : `${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

function PaperLine({ vendorId, p, onArchive, mayArchive, old }: { vendorId: string; p: Paper; onArchive?: () => void; mayArchive: boolean; old?: boolean }) {
  const open = async () => {
    const url = await paperLink(vendorId, p.id)
    if (url) window.open(url, '_blank', 'noopener')
  }
  return (
    <div className={cn('flex items-center gap-2 text-xs', old && 'text-muted-foreground')}>
      <button type="button" onClick={open} className="inline-flex min-w-0 items-center gap-1.5 font-medium underline-offset-2 hover:underline">
        <FileText className="size-3.5 shrink-0" /><span className="truncate">{p.file_name}</span>
      </button>
      <span className="min-w-0 flex-1 truncate text-muted-foreground">
        {[p.number, p.valid_until ? `valid till ${day(p.valid_until)}` : null, `${p.uploaded_by_name ?? 'someone'}, ${day(p.created_at)}`].filter(Boolean).join(' · ')}
      </span>
      {mayArchive && onArchive && (
        <Button type="button" variant="ghost" size="icon" className="size-7 shrink-0" aria-label={`Archive ${p.file_name}`} title="Archive (the file is kept)" onClick={onArchive}><Archive className="size-3.5" /></Button>
      )}
    </div>
  )
}

function KindCard({ vendorId, row, mayAdd, onChanged }: { vendorId: string; row: PaperKindRow; mayAdd: boolean; onChanged: () => void }) {
  const toast = useToast()
  const [adding, setAdding] = React.useState(false)
  const [file, setFile] = React.useState<File | null>(null)
  const [number, setNumber] = React.useState('')
  const [until, setUntil] = React.useState('')
  const [showHistory, setShowHistory] = React.useState(false)
  const save = useMutation({
    mutationFn: () => addVendorPaper(vendorId, file!, { kind: row.kind, number: number.trim(), valid_until: until }),
    onSuccess: () => { setAdding(false); setFile(null); setNumber(''); setUntil(''); onChanged(); toast.success(`${row.label} kept`) },
    onError: (e) => toast.error('Not saved', errorText(e)),
  })
  const archive = useMutation({
    mutationFn: (id: string) => archiveVendorPaper(vendorId, id),
    onSuccess: () => { onChanged(); toast.success('Archived; the file is kept') },
    onError: (e) => toast.error('Not archived', errorText(e)),
  })
  const replace = row.kind !== 'other' && row.current.length > 0
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{row.label}</span>
        {row.restricted && <Lock className="size-3.5 text-muted-foreground" aria-label="Seen by owner, admin, finance and project managers" />}
        <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-semibold', PAPER_TONE[row.status])} data-testid={`paper-${row.kind}`}>{paperStatusWords(row.status, row.days_left)}</span>
        {row.on_record && <span className="text-xs text-muted-foreground">On record: <span className="font-mono text-foreground">{row.on_record}</span></span>}
        {mayAdd && !adding && (
          <Button type="button" variant="outline" size="sm" className="ml-auto h-8 gap-1.5" onClick={() => { setAdding(true); setNumber(row.current[0]?.number ?? (row.kind === 'gst' || row.kind === 'pan' ? row.on_record ?? '' : '')) }}>
            <Upload className="size-3.5" /> {replace ? 'Replace' : 'Upload'}
          </Button>
        )}
      </div>
      {row.current.map((p) => <PaperLine key={p.id} vendorId={vendorId} p={p} mayArchive={mayAdd} onArchive={() => archive.mutate(p.id)} />)}
      {row.status === 'missing' && <p className="text-xs text-muted-foreground">Needed for a supplier registered for GST: the accountant asks for it at payment and audit.</p>}
      {adding && (
        <form className="grid gap-2 rounded-lg bg-muted/40 p-2 sm:grid-cols-[1fr_9rem_9rem_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); if (file) save.mutate() }}>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`paper-file-${row.kind}`} className="text-xs">Photo or PDF</Label>
            <Input id={`paper-file-${row.kind}`} type="file" accept="application/pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`paper-no-${row.kind}`} className="text-xs">Number <span className="font-normal text-muted-foreground">(optional)</span></Label>
            <Input id={`paper-no-${row.kind}`} value={number} maxLength={60} onChange={(e) => setNumber(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`paper-until-${row.kind}`} className="text-xs">Valid until <span className="font-normal text-muted-foreground">(optional)</span></Label>
            <Input id={`paper-until-${row.kind}`} type="date" value={until} onChange={(e) => setUntil(e.target.value)} className="dark:[color-scheme:dark]" />
          </div>
          <div className="flex gap-1.5">
            <Button type="submit" size="sm" className="h-9" disabled={!file || save.isPending}>Save</Button>
            <Button type="button" variant="ghost" size="sm" className="h-9" onClick={() => setAdding(false)}>Cancel</Button>
          </div>
          {replace && <p className="text-xs text-muted-foreground sm:col-span-4">The one on file now moves to the history.</p>}
        </form>
      )}
      {row.history.length > 0 && (
        <div className="flex flex-col gap-1">
          <button type="button" onClick={() => setShowHistory((s) => !s)} className="inline-flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <History className="size-3.5" /> {showHistory ? 'Hide' : 'Show'} {row.history.length} older
          </button>
          {showHistory && row.history.map((p) => <PaperLine key={p.id} vendorId={vendorId} p={p} mayArchive={false} old />)}
        </div>
      )}
    </li>
  )
}

export function VendorDocuments({ vendorId }: { vendorId: string }) {
  const queryClient = useQueryClient()
  const { data, isLoading, isError } = useQuery({ queryKey: ['finance', 'vendor-papers', vendorId], queryFn: () => fetchVendorPapers(vendorId), retry: false })
  const changed = () => queryClient.invalidateQueries({ queryKey: ['finance', 'vendor-papers'] })
  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (isError || !data) return <p className="text-sm text-muted-foreground">The papers could not be loaded.</p>
  return (
    <section className="flex flex-col gap-2" aria-label="Supplier documents">
      <ul className="grid gap-2 lg:grid-cols-2">
        {data.kinds.map((row) => <KindCard key={row.kind} vendorId={vendorId} row={row} mayAdd={data.may_add} onChanged={changed} />)}
      </ul>
      <p className="text-xs text-muted-foreground">Delivery test certificates (mill test, cement, RMC) are kept on the delivery's GRN and in the project's Documents.</p>
    </section>
  )
}
