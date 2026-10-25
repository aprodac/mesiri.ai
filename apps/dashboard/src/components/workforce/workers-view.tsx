import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, History, MoreHorizontal, Pencil, Search, TriangleAlert, UserCheck, UserPlus, UserX, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, DprSection, Segmented } from '@/components/dpr-page'
import { fetchWorkersApi, fetchWorkerStatisticsApi, updateWorkerApi, type WorkerStatistics, type WorkforceWorkerItem } from '@/lib/api'
import { downloadTextFile, toCsv } from '@/lib/export'
import { CHIP, localIsoDate } from '@/lib/site-day'
import { useUrlState } from '@/lib/url-state'
import { apiErrorMessage } from '@/lib/logo-upload'
import { cn } from '@/lib/utils'
import { AddWorkerDialog } from './add-worker-dialog'
import { EditWorkerSheet } from './edit-worker-sheet'
import { WorkerStatisticsSheet } from './worker-statistics-sheet'

// WEB-22: the worker register as rows -- trade, type, wage, and what
// attendance actually shows (days worked, last seen) -- plus the people
// attendance names who are not on the register yet, one tap from adding.
// Bulk select and the delete (a development-only endpoint, 403 in
// production) are gone; retiring a worker keeps their history.

type Kind = 'all' | 'permanent' | 'temporary' | 'contractor'
const KIND_WORDS: Record<WorkforceWorkerItem['worker_type'], string> = { permanent: 'Permanent', temporary: 'Temporary', contractor: 'Contractor' }
const shortDay = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString([], { day: 'numeric', month: 'short' })
const cap = (v: string | null) => (v ? v.charAt(0).toUpperCase() + v.slice(1).replace(/_/g, ' ') : '')

export function WorkersView({ addOpen, setAddOpen }: { addOpen: boolean; setAddOpen: (open: boolean) => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [search, setSearch] = useUrlState<string>('q', '')
  const [kind, setKind] = useUrlState<Kind>('type', 'all')
  const [showRetired, setShowRetired] = useUrlState<'no' | 'yes'>('retired', 'no')
  const [editing, setEditing] = React.useState<WorkforceWorkerItem | null>(null)
  const [history, setHistory] = React.useState<{ id: string; name: string } | null>(null)
  const [retiring, setRetiring] = React.useState<WorkforceWorkerItem | null>(null)
  const [prefill, setPrefill] = React.useState<WorkerStatistics | null>(null)
  const [today] = React.useState(() => localIsoDate(new Date()))

  // 200 is the endpoint's maximum; filters below work on what this returns.
  const workers = useQuery({ queryKey: ['labour', 'workers'], queryFn: () => fetchWorkersApi({ limit: 200 }) })
  // Attendance history fails on its own: the register still shows.
  const stats = useQuery({ queryKey: ['labour', 'worker-stats'], queryFn: () => fetchWorkerStatisticsApi(), retry: false })
  const statsById = React.useMemo(() => new Map((stats.data?.items ?? []).filter((s) => s.worker_id).map((s) => [s.worker_id!, s])), [stats.data])
  const unregistered = (stats.data?.items ?? []).filter((s) => !s.is_registered).sort((a, b) => b.days_worked - a.days_worked)
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['labour', 'workers'] })
    queryClient.invalidateQueries({ queryKey: ['labour', 'worker-stats'] })
  }

  const all = workers.data?.items ?? []
  const retiredCount = all.filter((w) => w.status !== 'active').length
  const pool = all.filter((w) => (showRetired === 'yes' ? w.status !== 'active' : w.status === 'active'))
  const counts = { permanent: 0, temporary: 0, contractor: 0 } as Record<WorkforceWorkerItem['worker_type'], number>
  for (const w of pool) counts[w.worker_type] = (counts[w.worker_type] ?? 0) + 1
  const visible = pool
    .filter((w) => kind === 'all' || w.worker_type === kind)
    .filter((w) => {
      const q = search.trim().toLowerCase()
      return !q || [w.name, w.trade, w.contractor].some((v) => v?.toLowerCase().includes(q))
    })
    .sort((a, b) => a.name.localeCompare(b.name))

  const setStatus = async (w: WorkforceWorkerItem, status: 'active' | 'inactive') => {
    try {
      await updateWorkerApi(w.id, { status })
      toast.success(status === 'active' ? 'Back on the register' : 'Retired', status === 'active' ? `${w.name} is active again.` : `${w.name}'s attendance history is kept.`)
      setRetiring(null)
      refresh()
    } catch (err) {
      toast.error('Could not change', apiErrorMessage(err))
    }
  }

  const exportCsv = () =>
    downloadTextFile(
      `workers-${today}.csv`,
      toCsv(
        ['Name', 'Trade', 'Type', 'Contractor', 'Daily wage (INR)', 'Status', 'Days worked', 'Last seen'],
        visible.map((w) => {
          const s = statsById.get(w.id)
          return [w.name, w.trade, KIND_WORDS[w.worker_type], w.contractor, w.default_daily_wage, w.status === 'active' ? 'Active' : 'Retired', s?.days_worked ?? '', s?.last_seen ?? '']
        }),
      ),
    )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-60">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input placeholder="Name, trade or contractor…" aria-label="Search workers" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 pl-8" />
        </div>
        <Segmented<Kind>
          label="Type"
          value={kind}
          onChange={setKind}
          options={[
            { value: 'all', label: 'Everyone', count: pool.length },
            { value: 'permanent', label: 'Permanent', count: counts.permanent },
            { value: 'temporary', label: 'Temporary', count: counts.temporary },
            { value: 'contractor', label: 'Contractor', count: counts.contractor },
          ]}
        />
        {retiredCount > 0 && (
          <Segmented<'no' | 'yes'>
            label="Status"
            value={showRetired}
            onChange={setShowRetired}
            options={[
              { value: 'no', label: 'Active' },
              { value: 'yes', label: 'Retired', count: retiredCount },
            ]}
          />
        )}
        <Button variant="outline" size="sm" className="ml-auto gap-1.5" disabled={visible.length === 0} onClick={exportCsv}>
          <Download className="size-3.5" /> CSV
        </Button>
      </div>

      {workers.isError ? (
        <Callout
          tone="draft"
          icon={TriangleAlert}
          action={
            <Button variant="outline" size="sm" className="bg-background" onClick={() => workers.refetch()}>
              Try again
            </Button>
          }
        >
          The worker register could not be loaded.
        </Callout>
      ) : workers.isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-lg" />
          ))}
        </div>
      ) : all.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-10 text-center">
          <Users className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">No one on the register yet</p>
          <p className="max-w-md text-sm text-muted-foreground">
            Attendance works without it: sites send "24 workers: 8 mason, 12 helper". Add named workers to track days and wages per person.
          </p>
          <Button size="sm" className="mt-1 gap-1.5" onClick={() => setAddOpen(true)}>
            <UserPlus className="size-4" /> Add worker
          </Button>
        </div>
      ) : visible.length === 0 ? (
        <p className="rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">No workers match.</p>
      ) : (
        <ul className="divide-y rounded-xl border">
          {visible.map((w) => {
            const s = statsById.get(w.id)
            return (
              <li key={w.id} className={cn('flex items-center gap-3 px-4 py-2.5', w.status !== 'active' && 'text-muted-foreground')}>
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="flex flex-wrap items-center gap-x-2">
                    <span className="font-semibold">{w.name}</span>
                    <span className="text-sm text-muted-foreground">{[cap(w.trade), KIND_WORDS[w.worker_type], w.contractor].filter(Boolean).join(' · ')}</span>
                    {w.status !== 'active' && <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Retired</span>}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {s && s.days_worked > 0 ? `${s.days_worked} days worked · last seen ${s.last_seen ? shortDay(s.last_seen) : '—'}` : stats.isLoading ? '…' : 'Not in any attendance yet'}
                  </span>
                </div>
                <span className="hidden w-24 text-right text-sm tabular-nums sm:inline">
                  {w.default_daily_wage ? `₹${w.default_daily_wage.toLocaleString('en-IN')}/day` : <span className="text-muted-foreground">No wage</span>}
                </span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" className="size-8 shrink-0" aria-label={`More for ${w.name}`}>
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-48">
                    <DropdownMenuItem onClick={() => setHistory({ id: w.id, name: w.name })}>
                      <History className="mr-2 size-3.5" /> Days and wages
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => setEditing(w)}>
                      <Pencil className="mr-2 size-3.5" /> Edit
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    {w.status === 'active' ? (
                      <DropdownMenuItem onClick={() => setRetiring(w)}>
                        <UserX className="mr-2 size-3.5" /> Retire
                      </DropdownMenuItem>
                    ) : (
                      <DropdownMenuItem onClick={() => setStatus(w, 'active')}>
                        <UserCheck className="mr-2 size-3.5" /> Make active
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              </li>
            )
          })}
        </ul>
      )}

      {unregistered.length > 0 && (
        <DprSection icon={UserPlus} title="Named in attendance, not on the register" meta={unregistered.length}>
          <ul className="divide-y rounded-xl border">
            {unregistered.slice(0, 20).map((s) => (
              <li key={s.key} className="flex items-center gap-3 px-4 py-2">
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="font-medium">{s.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {[s.trades.map(cap).join(', '), `${s.days_worked} days`, s.last_seen && `last ${shortDay(s.last_seen)}`].filter(Boolean).join(' · ')}
                  </span>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  onClick={() => {
                    setPrefill(s)
                    setAddOpen(true)
                  }}
                >
                  <UserPlus className="size-3.5" /> Add to register
                </Button>
              </li>
            ))}
          </ul>
        </DprSection>
      )}

      <Dialog open={retiring !== null} onOpenChange={(open) => !open && setRetiring(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Retire {retiring?.name}?</DialogTitle>
            <DialogDescription>They leave the active register. Every day they worked stays in the attendance history, and you can make them active again.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRetiring(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => retiring && setStatus(retiring, 'inactive')}>
              Retire
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AddWorkerDialog
        open={addOpen}
        onOpenChange={(open) => {
          setAddOpen(open)
          if (!open) setPrefill(null)
        }}
        onSuccess={refresh}
        initialValues={prefill ? { name: prefill.name, trade: prefill.trades[0], contractor: prefill.contractors[0] ?? null, dailyWage: prefill.avg_daily_wage || null } : undefined}
      />
      <EditWorkerSheet worker={editing} open={editing !== null} onOpenChange={(open) => !open && setEditing(null)} onSuccess={refresh} />
      <WorkerStatisticsSheet workerId={history?.id ?? null} workerName={history?.name ?? ''} open={history !== null} onOpenChange={(open) => !open && setHistory(null)} />
    </div>
  )
}
