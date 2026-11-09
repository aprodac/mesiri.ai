import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertCircle, Ban, Camera, Check, CirclePause, FileText, MapPin, MessageCircle, Paperclip, Play, Ruler, RotateCcw, Send, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { Avatar, ProjectDot, WhatsAppMark } from '@/components/requests/parts'
import { BILL_ACCEPT, billFile } from '@/lib/bill-upload'
import { apiErrorMessage } from '@/lib/logo-upload'
import { ago } from '@/lib/requests'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'
import {
  PRIORITY_LABEL,
  STATUS_LOOK,
  commentOnTask,
  dueWords,
  eventWords,
  fetchTask,
  fetchTaskOptions,
  moveTask,
  updateTask,
  type Task,
  type TaskPriority,
  type TaskStatus,
} from '@/lib/tasks'

// TSK-02: one task on the right of the Tasks page (a sheet on a phone): what it is, the buttons for the moves this
// person may make (the API's own `may`), the details the giver or a manager may change, and its history with photos.
// TSK-12: a photo or PDF is added from here, with a comment or when finishing (shrunk first, like an expense bill).

export function StatusChip({ status }: { status: TaskStatus }) {
  const look = STATUS_LOOK[status]
  return <span className={cn('inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-semibold', look.chip)}>{look.label}</span>
}

export function TaskDetail({ task: row, today, inSheet = false }: { task: Task; today: string; inSheet?: boolean }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const readOnly = useReadOnly()
  const { data: task } = useQuery({ queryKey: ['tasks', 'one', row.id], queryFn: () => fetchTask(row.id) })
  const { data: options } = useQuery({
    queryKey: ['tasks', 'options', row.project_id],
    queryFn: () => fetchTaskOptions(row.project_id),
    enabled: !!task?.may.edit,
    staleTime: 60_000,
  })
  const [blocking, setBlocking] = React.useState(false)
  const [reason, setReason] = React.useState('')
  const [comment, setComment] = React.useState('')
  const [attached, setAttached] = React.useState<File | null>(null)
  const commentFile = React.useRef<HTMLInputElement>(null)
  const doneFile = React.useRef<HTMLInputElement>(null)
  React.useEffect(() => { setBlocking(false); setReason(''); setComment(''); setAttached(null) }, [row.id])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['tasks'] })
  const fail = (err: unknown) => toast.error('Not saved', apiErrorMessage(err))
  const move = useMutation({
    mutationFn: async ({ status, note, file }: { status: TaskStatus; note?: string; file?: File }) =>
      moveTask(row.id, status, note, file ? await billFile(file, 'the work') : null),
    onSuccess: (t) => { refresh(); setBlocking(false); setReason(''); toast.success(`${t.ref} ${STATUS_LOOK[t.status].label.toLowerCase()}`) },
    onError: fail,
  })
  const change = useMutation({
    mutationFn: (payload: Parameters<typeof updateTask>[1]) => updateTask(row.id, payload),
    onSuccess: () => refresh(),
    onError: fail,
  })
  const say = useMutation({
    mutationFn: async () => commentOnTask(row.id, comment.trim(), attached ? await billFile(attached, 'the work') : null),
    onSuccess: () => { setComment(''); setAttached(null); refresh() },
    onError: fail,
  })

  const t = task ?? { ...row, history: [], may: { edit: false, cancel: false, move: false, comment: false } }
  const live = t.status === 'open' || t.status === 'doing' || t.status === 'blocked'
  const busy = move.isPending || readOnly

  const who = t.assignee_user_id ? `u:${t.assignee_user_id}` : t.assignee_vendor_id ? `v:${t.assignee_vendor_id}` : ''
  const pickWho = (value: string) => change.mutate(
    value.startsWith('u:') ? { assignee_user_id: value.slice(2) } :
      value.startsWith('v:') ? { assignee_vendor_id: value.slice(2) } :
        { assignee_user_id: null, assignee_vendor_id: null },
  )

  return (
    <div className={cn('flex flex-col gap-4 p-4', inSheet && 'pb-8')}>
      <header className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground tabular-nums">{t.ref}</span>
          <ProjectDot id={t.project_id} />
          <span className="truncate">{t.project_name}{t.site_name ? ` › ${t.site_name}` : ''}</span>
          {t.source === 'whatsapp' && <WhatsAppMark />}
        </div>
        <h2 className="text-lg leading-snug font-semibold">{t.title}</h2>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <StatusChip status={t.status} />
          <span className={cn('tabular-nums', t.overdue ? 'font-semibold text-destructive' : 'text-muted-foreground')}>{dueWords(t, today)}</span>
          {t.priority !== 'normal' && <span className="rounded-md bg-destructive/10 px-1.5 py-0.5 text-xs font-semibold text-destructive">{PRIORITY_LABEL[t.priority]}</span>}
        </div>
        {t.status === 'blocked' && t.blocked_reason && (
          <p className="rounded-lg bg-orange-100 px-3 py-2 text-sm text-orange-950 dark:bg-orange-950 dark:text-orange-100">Blocked: {t.blocked_reason}</p>
        )}
      </header>

      {t.may.move && (
        <div className="flex flex-wrap gap-2">
          {t.status === 'open' && <Button size="sm" variant="outline" className="gap-1.5" disabled={busy} onClick={() => move.mutate({ status: 'doing' })}><Play className="size-4" /> Start</Button>}
          {t.status === 'blocked' && <Button size="sm" variant="outline" className="gap-1.5" disabled={busy} onClick={() => move.mutate({ status: 'doing' })}><Play className="size-4" /> Unblocked</Button>}
          {live && <Button size="sm" className="gap-1.5" disabled={busy} onClick={() => move.mutate({ status: 'done' })}><Check className="size-4" /> Done</Button>}
          {live && (
            <Button size="sm" variant="outline" className="gap-1.5" disabled={busy} onClick={() => doneFile.current?.click()}>
              <Camera className="size-4" /> Done with photo
            </Button>
          )}
          {live && t.status !== 'blocked' && <Button size="sm" variant="outline" className="gap-1.5" disabled={busy} onClick={() => setBlocking(true)}><CirclePause className="size-4" /> Blocked…</Button>}
          {!live && <Button size="sm" variant="outline" className="gap-1.5" disabled={busy} onClick={() => move.mutate({ status: 'open' })}><RotateCcw className="size-4" /> Reopen</Button>}
          {live && t.may.cancel && <Button size="sm" variant="ghost" className="gap-1.5 text-muted-foreground" disabled={busy} onClick={() => move.mutate({ status: 'cancelled' })}><Ban className="size-4" /> Cancel task</Button>}
        </div>
      )}
      <input ref={doneFile} type="file" accept={BILL_ACCEPT} className="hidden" aria-hidden tabIndex={-1}
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) move.mutate({ status: 'done', file: f }) }} />
      {blocking && (
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (reason.trim()) move.mutate({ status: 'blocked', note: reason.trim() }) }}>
          <Input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="What is blocking it? (no shuttering, waiting for drawing…)" />
          <Button type="submit" size="sm" disabled={!reason.trim() || busy}>Save</Button>
        </form>
      )}

      <dl className="grid grid-cols-[7rem_1fr] items-center gap-x-3 gap-y-2 text-sm">
        <dt className="text-muted-foreground">For</dt>
        <dd>
          {t.may.edit && options && !readOnly ? (
            <Select value={who || 'none'} onValueChange={(v) => pickWho(v === 'none' ? '' : v)}>
              <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Nobody yet</SelectItem>
                {options.people.map((p) => <SelectItem key={p.id} value={`u:${p.id}`}>{p.name}</SelectItem>)}
                {options.subcontractors.map((s) => <SelectItem key={s.id} value={`v:${s.id}`}>{s.name} (subcontractor)</SelectItem>)}
              </SelectContent>
            </Select>
          ) : (
            <span className="inline-flex items-center gap-1.5"><Avatar id={t.assignee_user_id ?? t.assignee_vendor_id} name={t.assigned_to} />{t.assigned_to ?? 'Nobody yet'}</span>
          )}
        </dd>
        <dt className="text-muted-foreground">Due</dt>
        <dd>
          {t.may.edit && !readOnly ? (
            <Input type="date" className="h-8 w-44" value={t.due_date ?? ''} onChange={(e) => change.mutate({ due_date: e.target.value || null })} />
          ) : (t.due_date ?? 'No date')}
        </dd>
        <dt className="text-muted-foreground">Priority</dt>
        <dd>
          {t.may.edit && !readOnly ? (
            <Select value={t.priority} onValueChange={(v) => change.mutate({ priority: v as TaskPriority })}>
              <SelectTrigger className="h-8 w-32"><SelectValue /></SelectTrigger>
              <SelectContent>{(['normal', 'high', 'urgent'] as TaskPriority[]).map((p) => <SelectItem key={p} value={p}>{PRIORITY_LABEL[p]}</SelectItem>)}</SelectContent>
            </Select>
          ) : PRIORITY_LABEL[t.priority]}
        </dd>
        {(t.place_name || t.activity_name) && (
          <>
            <dt className="text-muted-foreground">Where</dt>
            <dd className="inline-flex items-center gap-1.5"><MapPin className="size-3.5 text-muted-foreground" />{[t.place_name, t.activity_name].filter(Boolean).join(' · ')}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Given by</dt>
        <dd>{t.created_by_name ?? 'Someone'} · {ago(t.created_at)}</dd>
      </dl>
      {t.notes && <p className="rounded-lg bg-muted/50 px-3 py-2 text-sm whitespace-pre-line">{t.notes}</p>}

      {(t.issue || t.line) && (
        <section className="flex flex-col gap-2" aria-label="Linked">
          {t.issue && (
            <Link to={`/issues?id=${t.issue.id}&project=${t.project_id}`} className="flex items-start gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-muted/40">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0">
                <span className="text-muted-foreground">Fixes the issue: </span>
                <span className="font-medium">{t.issue.narrative || (t.issue.type ?? '').replace(/_/g, ' ').toLowerCase()}</span>
                {t.issue.status && <span className="ml-1.5 text-xs text-muted-foreground">({t.issue.status.toLowerCase().replace('_', ' ')})</span>}
              </span>
            </Link>
          )}
          {t.line && <LineProgress task={t} />}
        </section>
      )}

      <section className="flex flex-col gap-3 border-t pt-3" aria-label="History">
        <h3 className="text-sm font-semibold">History</h3>
        {task === undefined && <div className="h-16 animate-pulse rounded-lg bg-muted/50" />}
        <ol className="flex flex-col gap-3">
          {t.history.map((e) => (
            <li key={e.id} className="flex gap-2.5 text-sm">
              <Avatar id={e.actor_user_id} name={e.actor_name} />
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <p>
                  <span className="font-medium">{e.actor_name ?? 'Someone'}</span> <span className="text-muted-foreground">{eventWords(e)}</span>
                  {e.source === 'whatsapp' && <span className="ml-1.5 inline-flex align-middle"><WhatsAppMark /></span>}
                  <span className="ml-1.5 text-xs text-muted-foreground tabular-nums">{ago(e.created_at)}</span>
                </p>
                {e.text && <p className="rounded-lg bg-muted/50 px-2.5 py-1.5">{e.text}</p>}
                {e.photo_url && e.photo_is_pdf && (
                  <a href={e.photo_url} target="_blank" rel="noreferrer" className="inline-flex w-fit items-center gap-1.5 rounded-lg border px-2.5 py-1.5 hover:bg-muted/40">
                    <FileText className="size-4 text-muted-foreground" /> Open the PDF
                  </a>
                )}
                {e.photo_url && !e.photo_is_pdf && (
                  <a href={e.photo_url} target="_blank" rel="noreferrer" className="block w-40 overflow-hidden rounded-lg border">
                    <img src={e.photo_url} alt={`Photo on ${t.ref}`} className="h-28 w-40 object-cover" loading="lazy" />
                  </a>
                )}
              </div>
            </li>
          ))}
        </ol>
        {t.may.comment && !readOnly && (
          <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); if (comment.trim() || attached) say.mutate() }}>
            {attached && (
              <span className="inline-flex w-fit max-w-full items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs">
                {attached.type === 'application/pdf' ? <FileText className="size-3.5 shrink-0" /> : <Camera className="size-3.5 shrink-0" />}
                <span className="truncate">{attached.name}</span>
                <button type="button" className="rounded p-0.5 hover:bg-background" onClick={() => setAttached(null)} aria-label="Remove the file"><X className="size-3.5" /></button>
              </span>
            )}
            <div className="flex gap-2">
              <label className="sr-only" htmlFor={`comment-${t.id}`}>Comment</label>
              <div className="relative flex-1">
                <MessageCircle className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
                <Input id={`comment-${t.id}`} value={comment} onChange={(e) => setComment(e.target.value)} placeholder={attached ? 'Say what it shows (optional)' : 'Add a comment'} className="pl-8" />
              </div>
              <input ref={commentFile} type="file" accept={BILL_ACCEPT} className="hidden" aria-hidden tabIndex={-1}
                onChange={(e) => { setAttached(e.target.files?.[0] ?? null); e.target.value = '' }} />
              <Button type="button" size="icon" variant="outline" onClick={() => commentFile.current?.click()} aria-label="Add a photo or PDF"><Paperclip className="size-4" /></Button>
              <Button type="submit" size="icon" variant="outline" disabled={(!comment.trim() && !attached) || say.isPending} aria-label="Send comment"><Send className="size-4" /></Button>
            </div>
          </form>
        )}
      </section>
    </div>
  )
}

/** The BOQ line a task counts against, and how much site recorded on it since the task started (never typed). */
export function LineProgress({ task: t, compact = false }: { task: Task; compact?: boolean }) {
  const p = t.progress
  if (!t.line) return null
  const words = p ? `${p.done}${p.expected ? ` of ${p.expected}` : ''} ${p.unit ?? t.line.unit ?? ''} done` : ''
  if (compact) {
    return p?.pct != null ? (
      <span className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="h-1.5 w-24 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-success" style={{ width: `${p.pct}%` }} /></span>
        <span className="tabular-nums">{words}</span>
      </span>
    ) : null
  }
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border px-3 py-2 text-sm">
      <span className="flex items-start gap-2">
        <Ruler className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <span><span className="text-muted-foreground">BOQ line: </span><span className="font-medium">{t.line.work}</span></span>
      </span>
      {p && (
        <>
          {p.pct != null && (
            <span className="h-2 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-success" style={{ width: `${p.pct}%` }} /></span>
          )}
          <span className="text-xs text-muted-foreground tabular-nums">
            {words} since the task started{t.site_name ? `, at ${t.site_name}` : ''}, from site's work updates
            {p.other_unit > 0 && ` · ${p.other_unit} update${p.other_unit > 1 ? 's' : ''} in another unit not added`}
          </span>
        </>
      )}
    </div>
  )
}
