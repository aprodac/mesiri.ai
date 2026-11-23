import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, CalendarClock, Download, ExternalLink, FileText, FolderOpen, History, Lock, MapPinned, Search, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, PageError } from '@/components/dpr-page'
import { EmptyState } from '@/components/page/page-kit'
import { ModuleHeader } from '@/components/page/module-header'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import {
  alreadyKeptId, archiveDocument, DISCIPLINE_NAMES, documentError, fetchDocument, fetchDocumentFile, fetchDocuments, fileSize, FOLDER_NAMES, FOLDER_ORDER,
  MAX_UPLOAD_BYTES, updateDocument, uploadDocument, uploadRevision, type DocumentsList, type Folder, type ProjectDocument,
} from '@/lib/documents'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'
import { appNow } from '@/lib/clock'
import { DatePicker } from '@/components/ui/date-picker'
import { Pager } from '@/components/page/pager'
import { usePagedUrl } from '@/lib/paging'

// DOC-01: Planning › Documents. One place for a project's papers: drawings with their revision, permits with their
// expiry, the contract and estimate (office only, D-DOC1). Drop files in: number, title, revision and folder are read
// from the name and a drawing's title block, and a drawing PDF's rooms and levels are kept (DR-07) so WhatsApp can
// answer "first floor slab level?" (DR-08) and "send me the latest S-101" (DOC-05).

function dayLabel(iso: string | null): string {
  return iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : ''
}

export default function DocumentsPage() {
  usePageTitle('Documents')
  const projectId = usePlanningProject()
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-4 sm:px-2">
        <ModuleHeader icon={FolderOpen} title="Documents" />
        <ProjectPickList to={(id) => `/planning/documents?project=${id}`} empty="No projects yet. Add one in Projects & Sites." />
      </div>
    )
  }
  return <DocumentsView key={projectId} projectId={projectId} />
}

function DocumentsView({ projectId }: { projectId: string }) {
  const [folder, setFolder] = React.useState<Folder | null>(null)
  const [q, setQ] = React.useState('')
  const [openId, setOpenId] = React.useState<string | null>(null)
  const query = useQuery<DocumentsList>({ queryKey: ['documents', projectId, folder, q], queryFn: () => fetchDocuments(projectId, { folder: folder ?? undefined, q: q || undefined }) })
  // UX-37: numbered pages, kept in the address.
  const pagedDocs = usePagedUrl(query.data?.documents ?? [], { resetOn: `${folder}|${q}` })

  if (query.isError) return <PageError message="The documents did not load." onRetry={() => query.refetch()} back={{ to: '/planning/documents', label: 'All projects' }} />
  const data = query.data
  const total = data ? Object.values(data.counts).reduce((a, b) => a + (b ?? 0), 0) : 0
  const folders = FOLDER_ORDER.filter((f) => data?.sees_restricted || !['contract', 'boq', 'work_order'].includes(f))

  return (
    <div className="mx-auto flex w-full min-w-0 flex-col gap-4 pb-8 sm:px-2">
      <ModuleHeader icon={FolderOpen} title="Documents" />
      {data && data.expiring.length > 0 && (
        <Callout tone="draft" icon={CalendarClock}>
          <span className="flex flex-wrap gap-1.5">
            {data.expiring.map((e) => {
              const gone = new Date(`${e.valid_until}T00:00:00`) < appNow()
              return (
                <span key={`${e.title}-${e.valid_until}`} className={cn('rounded-full px-2 py-0.5 text-xs font-semibold', gone ? 'bg-destructive/10 text-destructive' : 'bg-card text-draft')} title={gone ? 'Expired' : 'Expires soon'}>
                  {e.title} · {gone ? 'expired' : 'expires'} {dayLabel(e.valid_until)}
                </span>
              )
            })}
          </span>
        </Callout>
      )}
      <Dropzone projectId={projectId} folder={folder} onOpen={setOpenId} />
      <div className="grid min-w-0 gap-4 md:grid-cols-[13rem_1fr]">
        <nav className="flex gap-1 overflow-x-auto md:flex-col" aria-label="Folders" data-guide="docs.folders">
          <FolderButton active={folder === null} onClick={() => setFolder(null)} label="All" count={total} />
          {folders.map((f) => (
            <FolderButton key={f} active={folder === f} onClick={() => setFolder(f)} label={FOLDER_NAMES[f]} count={data?.counts[f] ?? 0}
              locked={['contract', 'boq', 'work_order'].includes(f)} />
          ))}
        </nav>
        <div className="flex min-w-0 flex-col gap-3">
          <div className="relative max-w-sm" data-guide="docs.search">
            <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" placeholder="Search number or title" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search documents" />
          </div>
          {!data ? <Skeleton className="h-48 w-full" /> : data.documents.length === 0 ? (
            <EmptyState icon={q ? Search : FolderOpen} title={q || folder ? 'Nothing here' : 'No documents yet'} className="bg-card" />
          ) : (
            <>
              <ul className="divide-y rounded-lg border bg-card" data-guide="docs.list">
                {pagedDocs.shown.map((d) => <DocRow key={d.id} doc={d} onOpen={() => setOpenId(d.id)} />)}
              </ul>
              <Pager {...pagedDocs.pager} noun="documents" className="mt-2" />
            </>
          )}
        </div>
      </div>
      <DocSheet id={openId} projectId={projectId} onOpen={setOpenId} onClose={() => setOpenId(null)} />
    </div>
  )
}

function FolderButton({ active, onClick, label, count, locked }: { active: boolean; onClick: () => void; label: string; count: number; locked?: boolean }) {
  return (
    <button type="button" onClick={onClick}
      className={cn('flex shrink-0 items-center justify-between gap-2 rounded-md px-3 py-1.5 text-left text-sm whitespace-nowrap', active ? 'bg-muted font-medium' : 'hover:bg-muted/60')}>
      <span className="flex items-center gap-1.5">{label}{locked && <Lock className="size-3 text-muted-foreground" aria-label="Office only" />}</span>
      <span className="text-xs text-muted-foreground tabular-nums">{count}</span>
    </button>
  )
}

function DocRow({ doc, onOpen }: { doc: ProjectDocument; onOpen: () => void }) {
  return (
    <li>
      <button type="button" onClick={onOpen} className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-muted/40">
        <FileKind name={doc.file_name} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            {doc.number && <span className="text-sm text-muted-foreground tabular-nums">{doc.number}</span>}
            <span className="font-medium">{doc.title}</span>
            {doc.revision && <span className="rounded bg-info-soft px-1.5 text-xs font-medium text-info">rev {doc.revision}</span>}
            {(doc.restricted || doc.restricted_by_folder) && <Lock className="size-3 text-muted-foreground" aria-label="Office only" />}
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {FOLDER_NAMES[doc.folder]}{doc.discipline ? ` · ${DISCIPLINE_NAMES[doc.discipline] ?? doc.discipline}` : ''} · {dayLabel(doc.created_at)}
            {doc.uploaded_by_name ? ` · ${doc.uploaded_by_name}` : ''}{doc.source === 'whatsapp' ? ' (WhatsApp)' : ''}
          </p>
          {doc.valid_until && <ValidTo day={doc.valid_until} />}
        </div>
        <span className="shrink-0 text-xs text-muted-foreground">{fileSize(doc.size_bytes)}</span>
      </button>
      {doc.goods_receipt_number != null && (
        // PRC-52: a delivery's test certificate, back to the GRN it came with.
        <Link to={`/procurement/grn?q=GRN-${String(doc.goods_receipt_number).padStart(4, '0')}`} className="ml-10 inline-block pb-2 text-xs font-medium text-muted-foreground underline-offset-2 hover:underline">
          With GRN-{String(doc.goods_receipt_number).padStart(4, '0')}{doc.notes ? ` · ${doc.notes}` : ''}
        </Link>
      )}
    </li>
  )
}

/** A file's kind at a glance: PDF red, image blue, sheet green, drawing amber, else grey. */
const FILE_LOOK: { test: RegExp; label: string; cls: string }[] = [
  { test: /\.pdf$/i, label: 'PDF', cls: 'bg-destructive/10 text-destructive' },
  { test: /\.(jpe?g|png|heic|webp)$/i, label: 'IMG', cls: 'bg-info-soft text-info' },
  { test: /\.(xlsx?|csv)$/i, label: 'XLS', cls: 'bg-success-soft text-success' },
  { test: /\.dwg$/i, label: 'DWG', cls: 'bg-draft-soft text-draft' },
  { test: /\.docx?$/i, label: 'DOC', cls: 'bg-info-soft text-info' },
]

function FileKind({ name }: { name: string }) {
  const look = FILE_LOOK.find((l) => l.test.test(name))
  if (!look) return <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
  return <span className={cn('mt-0.5 w-9 shrink-0 rounded px-1 py-0.5 text-center text-[10px] font-bold', look.cls)} aria-label={look.label}>{look.label}</span>
}

/** A permit's last day: red once past, amber within 30 days, grey after. */
function ValidTo({ day }: { day: string }) {
  const left = Math.round((new Date(`${day}T00:00:00`).getTime() - appNow().getTime()) / 86_400_000)
  const cls = left < 0 ? 'bg-destructive/10 text-destructive' : left <= 30 ? 'bg-draft-soft text-draft' : 'bg-muted text-muted-foreground'
  return <span className={cn('mt-1 inline-flex items-center gap-1 rounded-full px-2 py-px text-[11px] font-medium', cls)}><CalendarClock className="size-3" aria-hidden /> {left < 0 ? 'Expired' : 'Valid to'} {dayLabel(day)}</span>
}

function useRefresh(projectId: string) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['documents', projectId] })
    qc.invalidateQueries({ queryKey: ['document'] })
  }
}

function Dropzone({ projectId, folder, onOpen }: { projectId: string; folder: Folder | null; onOpen: (id: string) => void }) {
  const toast = useToast()
  const refresh = useRefresh(projectId)
  const [dragging, setDragging] = React.useState(false)
  const [busy, setBusy] = React.useState<string | null>(null)
  const input = React.useRef<HTMLInputElement>(null)

  const send = async (files: FileList | null) => {
    if (!files?.length) return
    let kept = 0
    const list = Array.from(files)
    for (const file of list) {
      if (file.size > MAX_UPLOAD_BYTES) { toast.error(`${file.name} is over 25 MB`, 'Send the drawings in smaller sets.'); continue }
      setBusy(file.name)
      try {
        const out = await uploadDocument(projectId, file, folder ? { folder } : {})
        kept += 1
        const what = [out.number, out.title, out.revision ? `rev ${out.revision}` : null].filter(Boolean).join(' ')
        const more = out.superseded ? `; rev ${out.superseded.revision ?? '-'} is now out of date` : out.checks ? `; ${out.checks} thing${out.checks > 1 ? 's' : ''} to ask the architect` : ''
        const valid = out.valid_until && out.valid_until_read ? `Valid to ${dayLabel(out.valid_until)}, read from it: ${out.valid_until_read}. It shows at the top of Documents from 30 days before it runs out.` : undefined
        toast.success(`Kept: ${what} in ${FOLDER_NAMES[out.folder]}${more}`, out.revision_note ?? valid)
      } catch (e) {
        const kept = alreadyKeptId(e)
        // The same file again is not a failure: say where it is, and open it when it was the only file.
        if (kept) {
          toast.info(`${file.name} is already kept`, list.length === 1 ? 'Opened it for you.' : documentError(e))
          if (list.length === 1) onOpen(kept)
        } else toast.error(`${file.name} not kept`, documentError(e))
      }
    }
    setBusy(null)
    if (kept) refresh()
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); send(e.dataTransfer.files) }}
      data-guide="docs.drop"
      className={cn('flex flex-wrap items-center justify-between gap-3 rounded-xl border-2 border-dashed bg-card p-4', dragging && 'border-primary bg-primary/5')}
    >
      <div className="flex items-center gap-3">
        <Upload className="size-5 text-muted-foreground" />
        <div className="text-sm">
          <p className="font-medium">{busy ? `Keeping ${busy}…` : 'Drop files here'}</p>
          <p className="flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground" title="PDF, photos, Word, Excel or DWG, up to 25 MB each">
            {['PDF', 'Photo', 'Word', 'Excel', 'DWG'].map((k) => <span key={k} className="rounded bg-muted px-1.5 py-px">{k}</span>)}
            <span>≤ 25 MB{folder ? ` → ${FOLDER_NAMES[folder]}` : ''}</span>
          </p>
        </div>
      </div>
      <input ref={input} type="file" multiple hidden accept=".pdf,.jpg,.jpeg,.png,.heic,.docx,.xlsx,.dwg" onChange={(e) => { send(e.target.files); e.target.value = '' }} />
      <Button size="sm" variant="outline" disabled={!!busy} onClick={() => input.current?.click()}>Choose files</Button>
    </div>
  )
}

/** The stored file as a local link, fetched through the API: a preview that fails says so in words. */
function useFileLink(id: string | undefined, wanted: boolean) {
  const file = useQuery({ queryKey: ['document-file', id], queryFn: () => fetchDocumentFile(id!), enabled: !!id && wanted, staleTime: 10 * 60_000, retry: 1 })
  const [link, setLink] = React.useState<string | null>(null)
  React.useEffect(() => {
    if (!file.data) { setLink(null); return }
    const url = URL.createObjectURL(file.data)
    setLink(url)
    return () => URL.revokeObjectURL(url)
  }, [file.data])
  return { link, loading: file.isLoading, failed: file.isError, retry: () => file.refetch() }
}

function DocSheet({ id, projectId, onOpen, onClose }: { id: string | null; projectId: string; onOpen: (id: string) => void; onClose: () => void }) {
  const toast = useToast()
  const refresh = useRefresh(projectId)
  const query = useQuery({ queryKey: ['document', id], queryFn: () => fetchDocument(id!), enabled: !!id })
  const doc = query.data
  const [form, setForm] = React.useState<Record<string, string>>({})
  React.useEffect(() => {
    if (doc) setForm({ title: doc.title, number: doc.number ?? '', revision: doc.revision ?? '', folder: doc.folder, valid_until: doc.valid_until ?? '' })
  }, [doc])
  const revInput = React.useRef<HTMLInputElement>(null)
  // A new revision waits for its letter: empty = read from the drawing, or the next letter if it still says the old one.
  const [revFile, setRevFile] = React.useState<File | null>(null)
  const [revLetter, setRevLetter] = React.useState('')
  React.useEffect(() => { setRevFile(null); setRevLetter('') }, [id])

  const save = useMutation({
    mutationFn: () => updateDocument(id!, { title: form.title, number: form.number || null, revision: form.revision || null, folder: form.folder as Folder, valid_until: form.valid_until || null }),
    onSuccess: () => { toast.success('Saved'); refresh() },
    onError: (e) => toast.error('Not saved', documentError(e)),
  })
  const archive = useMutation({
    mutationFn: () => archiveDocument(id!),
    onSuccess: () => { toast.success('Archived'); refresh(); onClose() },
    onError: (e) => toast.error('Not archived', documentError(e)),
  })
  const revise = useMutation({
    mutationFn: ({ file, letter }: { file: File; letter: string }) => uploadRevision(id!, file, letter.trim() || undefined),
    onSuccess: (out) => {
      toast.success(`Rev ${out.revision ?? 'new'} is now current${out.superseded ? `; rev ${out.superseded.revision ?? '-'} is out of date` : ''}`, out.revision_note ?? undefined)
      refresh(); onOpen(out.id)
    },
    onError: (e) => toast.error('New revision not kept', documentError(e)),
  })
  const isImage = !!doc?.content_type.startsWith('image/')
  const isPdf = doc?.content_type === 'application/pdf'
  const file = useFileLink(doc?.id, isPdf || isImage)
  const current = doc?.history.find((h) => h.status === 'current')
  const download = async () => {
    try {
      const blob = await fetchDocumentFile(doc!.id)
      const url = URL.createObjectURL(blob)
      const a = Object.assign(document.createElement('a'), { href: url, download: doc!.file_name })
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 30_000)
    } catch (e) {
      toast.error('Download did not start', documentError(e))
    }
  }

  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{doc ? [doc.number, doc.title].filter(Boolean).join(' · ') : 'Document'}</SheetTitle>
          <SheetDescription>
            {doc ? `${FOLDER_NAMES[doc.folder]}${doc.revision ? ` · rev ${doc.revision}` : ''} · ${doc.status === 'superseded' ? 'out of date' : doc.status} · ${doc.file_name}` : ''}
          </SheetDescription>
        </SheetHeader>
        {!doc ? <Skeleton className="mx-4 h-64" /> : (
          <div className="flex flex-col gap-4 px-4 pb-6">
            {doc.status === 'superseded' && (
              <Callout tone="draft" icon={History}
                action={current && <Button size="sm" variant="outline" onClick={() => onOpen(current.id)}>Open rev {current.revision ?? '-'}</Button>}>
                Old revision: rev {current?.revision ?? '-'} is the one to build from.
              </Callout>
            )}
            {(isPdf || isImage) && (file.loading ? <Skeleton className="h-[28rem] w-full" /> : file.failed ? (
              <div className="flex h-40 flex-col items-center justify-center gap-2 rounded-md border bg-muted/30 p-4 text-center text-sm">
                <p className="font-medium">The preview did not load</p>
                <p className="text-muted-foreground">The file is kept. Try again, or download it.</p>
                <Button size="sm" variant="outline" onClick={file.retry}>Try again</Button>
              </div>
            ) : file.link && (isPdf
              ? <iframe title={doc.title} src={file.link} className="h-[28rem] w-full rounded-md border" />
              : <img src={file.link} alt={doc.title} className="max-h-[28rem] w-full rounded-md border object-contain" />))}
            <div className="flex flex-wrap gap-3 text-sm">
              <button type="button" onClick={download} className="inline-flex items-center gap-1 underline underline-offset-2"><Download className="size-3.5" /> Download</button>
              {file.link && isPdf && <a href={file.link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-2"><ExternalLink className="size-3.5" /> Open in a new tab</a>}
            </div>

            {doc.facts?.live_plan && doc.status === 'current' && (
              <Callout tone="info" icon={MapPinned} action={<Button asChild size="sm" variant="outline"><Link to={`/planning/live?project=${projectId}`}>Open live plan</Link></Button>}>
                On the live plans
              </Callout>
            )}
            {doc.facts && (
              <section className="rounded-md bg-muted/40 p-3 text-sm">
                <p className="font-medium">Read from the drawing</p>
                <p className="text-muted-foreground">
                  {doc.facts.pages} page{doc.facts.pages === 1 ? '' : 's'}{doc.facts.floors?.length ? ` · floors: ${doc.facts.floors.join(', ')}` : ''}
                  {doc.facts.levels?.length ? ` · ${doc.facts.levels.length} levels` : ''}{doc.facts.checks?.length ? ` · ${doc.facts.checks.length} to ask the architect` : ''}
                </p>
                <Link to={`/planning/drawing-check?project=${projectId}&document=${doc.id}`} className="text-xs underline underline-offset-2">Full drawing check</Link>
              </section>
            )}

            {doc.history.length > 1 && (
              <section>
                <p className="mb-1 text-sm font-medium">Revisions</p>
                <ul className="text-sm">
                  {doc.history.map((h) => (
                    <li key={h.id}>
                      <button type="button" disabled={h.id === doc.id} onClick={() => onOpen(h.id)}
                        className={cn('flex w-full justify-between gap-2 rounded px-1 py-0.5 text-left', h.id === doc.id ? 'bg-muted font-medium' : 'hover:bg-muted/60')}>
                        <span>rev {h.revision ?? '-'} <span className="font-normal text-muted-foreground">{h.status === 'current' ? 'current' : 'out of date'}{h.id === doc.id ? ' · open' : ''}</span></span>
                        <span className="text-xs font-normal text-muted-foreground">{dayLabel(h.created_at)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
              <div className="grid gap-1 sm:col-span-2"><Label htmlFor="d-title">Title</Label><Input id="d-title" value={form.title ?? ''} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} /></div>
              <div className="grid gap-1"><Label htmlFor="d-number">Number</Label><Input id="d-number" placeholder="S-101" value={form.number ?? ''} onChange={(e) => setForm((f) => ({ ...f, number: e.target.value }))} /></div>
              <div className="grid gap-1"><Label htmlFor="d-rev">Revision</Label><Input id="d-rev" placeholder="C" value={form.revision ?? ''} onChange={(e) => setForm((f) => ({ ...f, revision: e.target.value }))} /></div>
              <div className="grid gap-1">
                <Label htmlFor="d-folder">Folder</Label>
                <select id="d-folder" className="h-9 rounded-md border bg-background px-2 text-sm" value={form.folder ?? 'other'} onChange={(e) => setForm((f) => ({ ...f, folder: e.target.value }))}>
                  {FOLDER_ORDER.map((f) => <option key={f} value={f}>{FOLDER_NAMES[f]}</option>)}
                </select>
              </div>
              <div className="grid gap-1">
                <Label htmlFor="d-valid">Valid until</Label>
                <DatePicker id="d-valid" value={form.valid_until ?? ''} onChange={(v) => setForm((f) => ({ ...f, valid_until: v }))} />
                {form.folder === 'approval' && !form.valid_until && <p className="text-[11px] text-muted-foreground">Add its last day: it then shows at the top of Documents 30 days before it runs out.</p>}
              </div>
              <div className="flex flex-wrap gap-2 sm:col-span-2">
                <Button type="submit" size="sm" disabled={save.isPending}>Save details</Button>
                {doc.can_manage && doc.status === 'current' && (
                  <>
                    <input ref={revInput} type="file" hidden accept=".pdf,.jpg,.jpeg,.png,.heic,.docx,.xlsx,.dwg" onChange={(e) => { const f = e.target.files?.[0]; if (f) setRevFile(f); e.target.value = '' }} />
                    {!revFile && (
                      <Button type="button" size="sm" variant="outline" disabled={revise.isPending} onClick={() => revInput.current?.click()}>
                        <Upload className="size-3.5" /> Upload new revision
                      </Button>
                    )}
                  </>
                )}
                {doc.can_manage && doc.status !== 'archived' && (
                  <Button type="button" size="sm" variant="ghost" className="text-destructive" disabled={archive.isPending}
                    onClick={() => window.confirm(`Archive ${doc.title}? It is kept and hidden.`) && archive.mutate()}>
                    <Archive className="size-3.5" /> Archive
                  </Button>
                )}
              </div>
              {revFile && (
                <div className="grid gap-2 rounded-md border bg-muted/30 p-3 sm:col-span-2">
                  <p className="text-sm"><span className="font-medium">New revision:</span> {revFile.name}</p>
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="grid gap-1">
                      <Label htmlFor="d-newrev">Revision letter</Label>
                      <Input id="d-newrev" className="w-24" placeholder={doc.next_revision ?? ''} value={revLetter} onChange={(e) => setRevLetter(e.target.value)} />
                    </div>
                    <Button type="button" size="sm" disabled={revise.isPending} onClick={() => revise.mutate({ file: revFile, letter: revLetter })}>
                      {revise.isPending ? 'Uploading…' : 'Keep as current'}
                    </Button>
                    <Button type="button" size="sm" variant="ghost" disabled={revise.isPending} onClick={() => { setRevFile(null); setRevLetter('') }}>Cancel</Button>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    Leave it empty and Mesiri reads it from the drawing's title block. If that shows no new letter, it is kept as rev {doc.next_revision ?? 'next'}. Rev {doc.revision ?? '-'} becomes out of date.
                  </p>
                </div>
              )}
            </form>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
