import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, CalendarClock, FileText, FolderOpen, Lock, Search, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, PageError } from '@/components/dpr-page'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import {
  archiveDocument, DISCIPLINE_NAMES, documentError, fetchDocument, fetchDocuments, fileSize, FOLDER_NAMES, FOLDER_ORDER,
  MAX_UPLOAD_BYTES, updateDocument, uploadDocument, uploadRevision, type DocumentsList, type Folder, type ProjectDocument,
} from '@/lib/documents'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// DOC-01: Planning › Documents. One place for a project's papers: drawings with their revision, permits with their
// expiry, the contract and estimate (office only, D-DOC1). Drop files in: number, title, revision and folder are read
// from the name and a drawing's title block, and a drawing PDF's rooms and levels are kept (DR-07) so WhatsApp can
// answer "first floor slab level?" (DR-08) and "send me the latest S-101" (DOC-05).

function dayLabel(iso: string | null): string {
  return iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : ''
}

function Heading() {
  return (
    <header className="flex min-w-0 items-center gap-3">
      <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-200">
        <FolderOpen className="size-5" />
      </span>
      <div className="min-w-0">
        <div className="text-xs text-muted-foreground">Planning</div>
        <h1 className="text-2xl leading-tight font-semibold tracking-tight">Documents</h1>
      </div>
    </header>
  )
}

export default function DocumentsPage() {
  usePageTitle('Documents')
  const projectId = usePlanningProject()
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 pb-8 sm:px-2">
        <Heading />
        <p className="text-sm text-muted-foreground">Pick a project to see its drawings, permits and papers.</p>
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

  if (query.isError) return <PageError message="The documents did not load." onRetry={() => query.refetch()} back={{ to: '/planning/documents', label: 'All projects' }} />
  const data = query.data
  const total = data ? Object.values(data.counts).reduce((a, b) => a + (b ?? 0), 0) : 0
  const folders = FOLDER_ORDER.filter((f) => data?.sees_restricted || !['contract', 'boq', 'work_order'].includes(f))

  return (
    <div className="mx-auto flex w-full max-w-6xl min-w-0 flex-col gap-4 pb-8 sm:px-2">
      <Heading />
      <p className="max-w-3xl text-sm text-muted-foreground">
        The project's papers in one place. Drop drawings in and their number and revision are read for you; a new revision marks the old one out of date.
        On WhatsApp, anyone on the project can ask “send me the latest S-101”.
      </p>
      {data && data.expiring.length > 0 && (
        <Callout tone="draft" icon={CalendarClock}>
          {data.expiring.map((e) => `${e.title}: ${new Date(`${e.valid_until}T00:00:00`) < new Date() ? 'expired' : 'expires'} ${dayLabel(e.valid_until)}`).join(' · ')}
        </Callout>
      )}
      <Dropzone projectId={projectId} folder={folder} />
      <div className="grid min-w-0 gap-4 md:grid-cols-[13rem_1fr]">
        <nav className="flex gap-1 overflow-x-auto md:flex-col" aria-label="Folders">
          <FolderButton active={folder === null} onClick={() => setFolder(null)} label="All" count={total} />
          {folders.map((f) => (
            <FolderButton key={f} active={folder === f} onClick={() => setFolder(f)} label={FOLDER_NAMES[f]} count={data?.counts[f] ?? 0}
              locked={['contract', 'boq', 'work_order'].includes(f)} />
          ))}
        </nav>
        <div className="flex min-w-0 flex-col gap-3">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input className="pl-8" placeholder="Search number or title" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search documents" />
          </div>
          {!data ? <Skeleton className="h-48 w-full" /> : data.documents.length === 0 ? (
            <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
              {q || folder ? 'Nothing here.' : 'No documents yet. Drop the drawings, permits and contract above.'}
            </p>
          ) : (
            <ul className="divide-y rounded-lg border">
              {data.documents.map((d) => <DocRow key={d.id} doc={d} onOpen={() => setOpenId(d.id)} />)}
            </ul>
          )}
        </div>
      </div>
      <DocSheet id={openId} projectId={projectId} onClose={() => setOpenId(null)} />
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
        <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            {doc.number && <span className="font-mono text-xs text-muted-foreground">{doc.number}</span>}
            <span className="font-medium">{doc.title}</span>
            {doc.revision && <span className="rounded bg-sky-100 px-1.5 text-xs font-medium text-sky-900 dark:bg-sky-950 dark:text-sky-200">rev {doc.revision}</span>}
            {(doc.restricted || doc.restricted_by_folder) && <Lock className="size-3 text-muted-foreground" aria-label="Office only" />}
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {FOLDER_NAMES[doc.folder]}{doc.discipline ? ` · ${DISCIPLINE_NAMES[doc.discipline] ?? doc.discipline}` : ''} · {dayLabel(doc.created_at)}
            {doc.uploaded_by_name ? ` · ${doc.uploaded_by_name}` : ''}{doc.source === 'whatsapp' ? ' (WhatsApp)' : ''}
            {doc.valid_until ? ` · valid to ${dayLabel(doc.valid_until)}` : ''}
          </p>
        </div>
        <span className="shrink-0 text-xs text-muted-foreground">{fileSize(doc.size_bytes)}</span>
      </button>
    </li>
  )
}

function useRefresh(projectId: string) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['documents', projectId] })
    qc.invalidateQueries({ queryKey: ['document'] })
  }
}

function Dropzone({ projectId, folder }: { projectId: string; folder: Folder | null }) {
  const toast = useToast()
  const refresh = useRefresh(projectId)
  const [dragging, setDragging] = React.useState(false)
  const [busy, setBusy] = React.useState<string | null>(null)
  const input = React.useRef<HTMLInputElement>(null)

  const send = async (files: FileList | null) => {
    if (!files?.length) return
    let kept = 0
    for (const file of Array.from(files)) {
      if (file.size > MAX_UPLOAD_BYTES) { toast.error(`${file.name} is over 25 MB`, 'Send the drawings in smaller sets.'); continue }
      setBusy(file.name)
      try {
        const out = await uploadDocument(projectId, file, folder ? { folder } : {})
        kept += 1
        const what = [out.number, out.title, out.revision ? `rev ${out.revision}` : null].filter(Boolean).join(' ')
        const more = out.superseded ? `; rev ${out.superseded.revision ?? '-'} is now out of date` : out.checks ? `; ${out.checks} thing${out.checks > 1 ? 's' : ''} to ask the architect` : ''
        toast.success(`Kept: ${what} in ${FOLDER_NAMES[out.folder]}${more}`)
      } catch (e) {
        toast.error(`${file.name} not kept`, documentError(e))
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
      className={cn('flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed p-4', dragging && 'border-primary bg-primary/5')}
    >
      <div className="flex items-center gap-3">
        <Upload className="size-5 text-muted-foreground" />
        <div className="text-sm">
          <p className="font-medium">{busy ? `Keeping ${busy}…` : 'Drop files here'}</p>
          <p className="text-xs text-muted-foreground">PDF, photos, Word, Excel or DWG, up to 25 MB each{folder ? `, into ${FOLDER_NAMES[folder]}` : ''}</p>
        </div>
      </div>
      <input ref={input} type="file" multiple hidden accept=".pdf,.jpg,.jpeg,.png,.heic,.docx,.xlsx,.dwg" onChange={(e) => { send(e.target.files); e.target.value = '' }} />
      <Button size="sm" variant="outline" disabled={!!busy} onClick={() => input.current?.click()}>Choose files</Button>
    </div>
  )
}

function DocSheet({ id, projectId, onClose }: { id: string | null; projectId: string; onClose: () => void }) {
  const toast = useToast()
  const refresh = useRefresh(projectId)
  const query = useQuery({ queryKey: ['document', id], queryFn: () => fetchDocument(id!), enabled: !!id })
  const doc = query.data
  const [form, setForm] = React.useState<Record<string, string>>({})
  React.useEffect(() => {
    if (doc) setForm({ title: doc.title, number: doc.number ?? '', revision: doc.revision ?? '', folder: doc.folder, valid_until: doc.valid_until ?? '' })
  }, [doc])
  const revInput = React.useRef<HTMLInputElement>(null)

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
    mutationFn: (file: File) => uploadRevision(id!, file),
    onSuccess: (out) => { toast.success(`Rev ${out.revision ?? 'new'} is now current`); refresh(); onClose() },
    onError: (e) => toast.error('New revision not kept', documentError(e)),
  })
  const isImage = doc?.content_type.startsWith('image/')
  const isPdf = doc?.content_type === 'application/pdf'

  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{doc ? [doc.number, doc.title].filter(Boolean).join(' · ') : 'Document'}</SheetTitle>
          <SheetDescription>
            {doc ? `${FOLDER_NAMES[doc.folder]}${doc.revision ? ` · rev ${doc.revision}` : ''} · ${doc.status === 'current' ? 'current' : doc.status} · ${doc.file_name}` : ''}
          </SheetDescription>
        </SheetHeader>
        {!doc ? <Skeleton className="mx-4 h-64" /> : (
          <div className="flex flex-col gap-4 px-4 pb-6">
            {doc.url && isPdf && <iframe title={doc.title} src={doc.url} className="h-[28rem] w-full rounded-md border" />}
            {doc.url && isImage && <img src={doc.url} alt={doc.title} className="max-h-[28rem] w-full rounded-md border object-contain" />}
            {doc.url && <a href={doc.url} target="_blank" rel="noreferrer" className="text-sm underline underline-offset-2">Open / download</a>}

            {doc.facts && (
              <section className="rounded-md bg-muted/40 p-3 text-sm">
                <p className="font-medium">Read from the drawing</p>
                <p className="text-muted-foreground">
                  {doc.facts.pages} page{doc.facts.pages === 1 ? '' : 's'}{doc.facts.floors?.length ? ` · floors: ${doc.facts.floors.join(', ')}` : ''}
                  {doc.facts.levels?.length ? ` · ${doc.facts.levels.length} levels` : ''}{doc.facts.checks?.length ? ` · ${doc.facts.checks.length} to ask the architect` : ''}
                </p>
                <Link to="/planning/drawing-check" className="text-xs underline underline-offset-2">Full drawing check</Link>
              </section>
            )}

            {doc.history.length > 1 && (
              <section>
                <p className="mb-1 text-sm font-medium">Revisions</p>
                <ul className="text-sm">
                  {doc.history.map((h) => (
                    <li key={h.id} className="flex justify-between gap-2 py-0.5">
                      <span>rev {h.revision ?? '-'} <span className="text-muted-foreground">{h.status}</span></span>
                      <span className="text-xs text-muted-foreground">{dayLabel(h.created_at)}</span>
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
              <div className="grid gap-1"><Label htmlFor="d-valid">Valid until</Label><Input id="d-valid" type="date" value={form.valid_until ?? ''} onChange={(e) => setForm((f) => ({ ...f, valid_until: e.target.value }))} /></div>
              <div className="flex flex-wrap gap-2 sm:col-span-2">
                <Button type="submit" size="sm" disabled={save.isPending}>Save details</Button>
                {doc.can_manage && doc.status === 'current' && (
                  <>
                    <input ref={revInput} type="file" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) revise.mutate(f); e.target.value = '' }} />
                    <Button type="button" size="sm" variant="outline" disabled={revise.isPending} onClick={() => revInput.current?.click()}>
                      <Upload className="size-3.5" /> {revise.isPending ? 'Uploading…' : 'Upload new revision'}
                    </Button>
                  </>
                )}
                {doc.can_manage && doc.status !== 'archived' && (
                  <Button type="button" size="sm" variant="ghost" className="text-destructive" disabled={archive.isPending}
                    onClick={() => window.confirm(`Archive ${doc.title}? It is kept and hidden.`) && archive.mutate()}>
                    <Archive className="size-3.5" /> Archive
                  </Button>
                )}
              </div>
            </form>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
