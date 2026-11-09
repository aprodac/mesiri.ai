import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, FolderPlus, Link2, ListTree, Pencil, Plus, Search, Sparkles } from 'lucide-react'
import { BooksClosed, BooksTabs } from '@/components/accounts/books'
import { Callout, DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import {
  LINK_LABEL,
  NATURE_LABEL,
  addGroup,
  addLedger,
  drCr,
  editLedger,
  fetchChart,
  linkedRecord,
  mayReadBooks,
  renameGroup,
  type Ledger,
  type LedgerGroup,
} from '@/lib/accounts'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-01 (D-ACC8): the chart the books post to: Tally's groups and the construction ledgers, seeded; one ledger per
// supplier, client, money account, expense category and member of staff, made on its own. The company adds ledgers and
// groups, renames them, moves a ledger to another group. A linked ledger is named after its record (rename it there).
// Backend: GET /accounts/chart, POST/PATCH /accounts/ledgers, /accounts/groups.

type Edit =
  | { kind: 'ledger'; ledger: Ledger | null; group_id: string }
  | { kind: 'group'; group: LedgerGroup | null; parent_id: string }
  | null

function path(groups: Map<string, LedgerGroup>, id: string): string {
  const names: string[] = []
  let g = groups.get(id)
  while (g) {
    names.unshift(g.name)
    g = g.parent_id ? groups.get(g.parent_id) : undefined
  }
  return names.join(' › ')
}

export default function ChartOfAccountsPage() {
  usePageTitle('Chart of accounts')
  const { me } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const allowed = mayReadBooks(me?.role)
  const chart = useQuery({ queryKey: ['accounts', 'chart'], queryFn: fetchChart, enabled: allowed })
  const [q, setQ] = React.useState('')
  const [closed, setClosed] = React.useState<Set<string>>(new Set())
  const [edit, setEdit] = React.useState<Edit>(null)
  const [form, setForm] = React.useState({ name: '', group_id: '', notes: '' })

  const done = (word: string) => {
    toast.success(word)
    qc.invalidateQueries({ queryKey: ['accounts'] })
    setEdit(null)
  }
  const fail = (err: unknown) => toast.error('Not saved', apiErrorMessage(err))
  const save = useMutation({
    mutationFn: async () => {
      if (edit?.kind === 'ledger') {
        if (edit.ledger) {
          const body: { name?: string; group_id?: string; notes?: string } = { group_id: form.group_id, notes: form.notes }
          if (!edit.ledger.link_kind && form.name.trim() !== edit.ledger.name) body.name = form.name.trim()
          return editLedger(edit.ledger.id, body)
        }
        return addLedger({ name: form.name.trim(), group_id: form.group_id, notes: form.notes || undefined })
      }
      if (edit?.kind === 'group') {
        if (edit.group) return renameGroup(edit.group.id, form.name.trim())
        return addGroup({ name: form.name.trim(), parent_id: edit.parent_id })
      }
    },
    onSuccess: () => done(edit?.kind === 'group' ? 'Group saved' : 'Ledger saved'),
    onError: fail,
  })
  const toggleActive = useMutation({
    mutationFn: (l: Ledger) => editLedger(l.id, { is_active: !l.is_active }),
    onSuccess: () => done('Ledger updated'),
    onError: fail,
  })

  const d = chart.data
  const groups = React.useMemo(() => new Map((d?.groups ?? []).map((g) => [g.id, g])), [d])
  if (!allowed) return <BooksClosed />
  if (chart.isError) return <PageError message="The chart of accounts could not be loaded." onRetry={() => chart.refetch()} back={{ to: '/accounts/trial-balance', label: 'Trial balance' }} />

  const words = q.trim().toLowerCase()
  const ledgersOf = (gid: string) =>
    (d?.ledgers ?? []).filter((l) => l.group_id === gid && (!words || l.name.toLowerCase().includes(words))).sort((a, b) => a.name.localeCompare(b.name))
  const childrenOf = (gid: string | null) => (d?.groups ?? []).filter((g) => g.parent_id === gid)
  const hasAny = (gid: string): boolean => ledgersOf(gid).length > 0 || childrenOf(gid).some((c) => hasAny(c.id))

  const openLedger = (ledger: Ledger | null, group_id: string) => {
    setForm({ name: ledger?.name ?? '', group_id: ledger?.group_id ?? group_id, notes: ledger?.notes ?? '' })
    setEdit({ kind: 'ledger', ledger, group_id })
  }
  const openGroup = (group: LedgerGroup | null, parent_id: string) => {
    setForm({ name: group?.name ?? '', group_id: '', notes: '' })
    setEdit({ kind: 'group', group, parent_id })
  }

  const renderGroup = (g: LedgerGroup, depth: number): React.ReactNode => {
    if (words && !hasAny(g.id)) return null
    const isOpen = !!words || !closed.has(g.id)
    const ls = ledgersOf(g.id)
    const kids = childrenOf(g.id)
    return (
      <li key={g.id}>
        <div className={cn('group flex items-center gap-2 px-3 py-2 text-sm', depth === 0 && 'bg-muted/30')} style={{ paddingLeft: `${0.75 + depth}rem` }}>
          <button
            type="button"
            className="flex min-w-0 flex-1 items-center gap-1 text-left font-medium"
            onClick={() => setClosed((s) => {
              const n = new Set(s)
              if (n.has(g.id)) n.delete(g.id)
              else n.add(g.id)
              return n
            })}
          >
            <ChevronRight className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
            <span className="truncate">{g.name}</span>
            <span className="shrink-0 text-xs font-normal text-muted-foreground">{ls.length ? `· ${ls.length}` : ''}</span>
          </button>
          <div className="flex shrink-0 gap-0.5 opacity-70 group-hover:opacity-100">
            <Button size="icon" variant="ghost" className="size-7" title="Add a ledger here" aria-label={`Add a ledger to ${g.name}`} onClick={() => openLedger(null, g.id)}>
              <Plus className="size-3.5" />
            </Button>
            <Button size="icon" variant="ghost" className="size-7" title="Add a group under it" aria-label={`Add a group under ${g.name}`} onClick={() => openGroup(null, g.id)}>
              <FolderPlus className="size-3.5" />
            </Button>
            <Button size="icon" variant="ghost" className="size-7" title="Rename" aria-label={`Rename ${g.name}`} onClick={() => openGroup(g, g.parent_id ?? '')}>
              <Pencil className="size-3.5" />
            </Button>
          </div>
        </div>
        {isOpen && (
          <ul>
            {kids.map((c) => renderGroup(c, depth + 1))}
            {ls.map((l) => {
              const record = linkedRecord(l.link_kind, l.link_id)
              return (
                <li key={l.id} className="flex flex-col gap-0.5 px-3 py-2 text-sm hover:bg-muted/30 sm:flex-row sm:items-center sm:gap-3" style={{ paddingLeft: `${2 + depth}rem` }}>
                  <div className="min-w-0 flex-1">
                    <Link to={`/accounts/ledgers/${l.id}`} className={cn('font-medium hover:underline', !l.is_active && 'text-muted-foreground line-through')}>
                      {l.name}
                    </Link>
                    <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                      {l.link_kind && (
                        <span className="inline-flex items-center gap-1">
                          <Link2 className="size-3" /> {LINK_LABEL[l.link_kind]}
                          {record && (
                            <Link to={record.to} className="underline">
                              {record.label}
                            </Link>
                          )}
                        </span>
                      )}
                      {l.seeded && (
                        <span className="inline-flex items-center gap-1">
                          <Sparkles className="size-3" /> Mesiri posts here{l.purpose ? `: ${l.purpose}` : ''}
                        </span>
                      )}
                      {!l.seeded && !l.link_kind && l.notes && <span>{l.notes}</span>}
                      <span>{l.lines ? `${l.lines} ${l.lines === 1 ? 'entry' : 'entries'}` : 'not used yet'}</span>
                    </p>
                  </div>
                  <span className="tabular-nums">{drCr(l.balance)}</span>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" className="h-7" onClick={() => openLedger(l, l.group_id)}>
                      Edit
                    </Button>
                    {!l.seeded && (
                      <Button size="sm" variant="ghost" className="h-7 text-muted-foreground" disabled={toggleActive.isPending} onClick={() => toggleActive.mutate(l)}>
                        {l.is_active ? 'Switch off' : 'Switch on'}
                      </Button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </li>
    )
  }

  const roots = childrenOf(null)
  const byNature = (['asset', 'liability', 'equity', 'income', 'expense'] as const).map((n) => ({ nature: n, roots: roots.filter((g) => g.nature === n) }))
  const editingLinked = edit?.kind === 'ledger' && !!edit.ledger?.link_kind

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/accounts/trial-balance', label: 'Trial balance' }} crumb="Accounts" title="Chart of accounts" date={d ? `${d.groups.length} groups · ${d.ledgers.length} ledgers` : undefined} />
      <BooksTabs current="/accounts/chart" />
      <Callout tone="info" icon={ListTree}>
        Tally's groups, so your CA reads it as theirs. Each supplier, client, bank or cash account, expense category and member of staff who paid from their own pocket gets its ledger on its own, the first time the books need it. Nothing to set up.
      </Callout>
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <DprSection icon={ListTree} title="Groups and ledgers">
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a ledger" className="h-9 pl-8" aria-label="Find a ledger" />
          </div>
          <div className="flex flex-col gap-4">
            {byNature
              .filter((x) => x.roots.some((g) => !words || hasAny(g.id)))
              .map((x) => (
                <section key={x.nature} className="overflow-hidden rounded-lg border">
                  <h3 className="border-b px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">{NATURE_LABEL[x.nature]}</h3>
                  <ul className="divide-y">{x.roots.map((g) => renderGroup(g, 0))}</ul>
                </section>
              ))}
          </div>
        </DprSection>
      )}
      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {edit?.kind === 'group' ? (edit.group ? 'Rename group' : 'New group') : edit?.ledger ? 'Edit ledger' : 'New ledger'}
            </DialogTitle>
            <DialogDescription>
              {edit?.kind === 'group'
                ? edit.group
                  ? 'Its ledgers stay where they are.'
                  : `Under ${groups.get(edit.parent_id)?.name ?? 'the group'}; it takes that group's place in the reports.`
                : editingLinked
                  ? `Named after its ${LINK_LABEL[edit!.ledger!.link_kind!].toLowerCase()}: rename it there. You can move it to another group.`
                  : 'A ledger for what has no record in Mesiri yet (office rent, a loan, capital).'}
            </DialogDescription>
          </DialogHeader>
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              save.mutate()
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="acc-name">Name</Label>
              <Input id="acc-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} disabled={editingLinked} autoFocus maxLength={160} />
            </div>
            {edit?.kind === 'ledger' && (
              <>
                <div className="flex flex-col gap-1.5">
                  <Label>Group</Label>
                  <Select value={form.group_id} onValueChange={(v) => setForm({ ...form, group_id: v })}>
                    <SelectTrigger>
                      <SelectValue placeholder="Pick a group" />
                    </SelectTrigger>
                    <SelectContent>
                      {(d?.groups ?? [])
                        .map((g) => ({ id: g.id, label: path(groups, g.id) }))
                        .sort((a, b) => a.label.localeCompare(b.label))
                        .map((g) => (
                          <SelectItem key={g.id} value={g.id}>
                            {g.label}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
                {!edit.ledger?.seeded && (
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="acc-notes">Note (optional)</Label>
                    <Input id="acc-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} maxLength={500} placeholder="What goes here" />
                  </div>
                )}
              </>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setEdit(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={save.isPending || (!editingLinked && !form.name.trim()) || (edit?.kind === 'ledger' && !form.group_id)}>
                {save.isPending ? 'Saving…' : 'Save'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
