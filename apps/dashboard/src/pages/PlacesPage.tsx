import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Camera, ChevronDown, ChevronRight, Layers, MapPinned, Pencil, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, PageError, PageHeader, StatStrip, type Stat } from '@/components/dpr-page'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import {
  addPlace, fetchPlaces, fetchPlacesProgress, fetchPlaceWork, nameLines, removePlace, renamePlace, setupPlaces,
  type CellState, type PlaceProgressRow, type PlacesList, type PlacesProgress,
} from '@/lib/places'
import { cn } from '@/lib/utils'
import { Link } from 'react-router-dom'
import { fetchLiveMaps } from '@/lib/live-maps'

// LP-01..05: Planning › Places. The project's floors and rooms, coloured by the work site has reported at each one
// (done / in progress / not started), with the work and photos of a room one tap away. Nothing is typed to fill
// it: "first floor Room-2 plastering done" on WhatsApp lands on that room.

// Status tokens only (docs/DESIGN.md §3): green done, blue in progress, grey not started.
const CELL: Record<CellState, string> = {
  done: 'bg-success text-white dark:text-background',
  in_progress: 'bg-info-soft text-info',
  not_started: 'bg-muted text-muted-foreground',
}
const CELL_WORD: Record<CellState, string> = { done: 'Done', in_progress: 'In progress', not_started: 'Not started' }

function dayLabel(iso: string | null): string {
  return iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : ''
}

export default function PlacesPage() {
  usePageTitle('Places')
  const projectId = usePlanningProject()
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 pb-4 sm:px-2">
        <PageHeader title="Places" subtitle="Progress floor by floor and room by room. Pick a project." />
        <ProjectPickList to={(id) => `/planning/places?project=${id}`} empty="No projects yet. Add one in Projects & Sites." />
      </div>
    )
  }
  return <PlacesView key={projectId} projectId={projectId} />
}

function PlacesView({ projectId }: { projectId: string }) {
  const list = useQuery<PlacesList>({ queryKey: ['places', projectId], queryFn: () => fetchPlaces(projectId) })
  const grid = useQuery<PlacesProgress>({ queryKey: ['places-progress', projectId], queryFn: () => fetchPlacesProgress(projectId), staleTime: 0, refetchInterval: 30_000 })
  const [editing, setEditing] = React.useState(false)
  const [open, setOpen] = React.useState<PlaceProgressRow | null>(null)
  // DR-10 / DR-11: the drawings as live maps have their own page (Live plans); here, the way to them.
  const live = useQuery({ queryKey: ['live-maps', projectId], queryFn: () => fetchLiveMaps(projectId), staleTime: 0, refetchInterval: 30_000 })

  if (list.isError || grid.isError) {
    return <PageError message="The places did not load." onRetry={() => { list.refetch(); grid.refetch() }} back={{ to: '/planning/places', label: 'All projects' }} />
  }
  if (!list.data || !grid.data) {
    return <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-4 sm:px-2"><PageHeader title="Places" /><Skeleton className="h-64 w-full" /></div>
  }
  const places = list.data.places
  const rows = grid.data.places
  const floors = rows.filter((r) => r.depth === 0)
  const kinds = grid.data.kinds
  // Footings tracked from a structural drawing sit under "Foundation": counted as footings, never as rooms.
  const foundation = new Set(floors.filter((f) => f.name.toLowerCase() === 'foundation').map((f) => f.id))
  const footings = rows.filter((r) => r.parent_id && foundation.has(r.parent_id)).length
  const rooms = rows.filter((r) => r.depth > 0 && !(r.parent_id && foundation.has(r.parent_id)))
  const finished = rooms.filter((r) => r.done.length > 0 && r.left.length === 0).length
  const underWay = rooms.filter((r) => r.left.length > 0 && Object.values(r.cells).some((c) => c.state !== 'not_started')).length
  const stats: Stat[] = [
    { label: 'Floors', value: floors.length - foundation.size || '—', hint: footings ? `and ${footings} footings` : undefined },
    { label: 'Rooms', value: rooms.length || '—' },
    { label: 'Rooms finished', value: finished || '—', tone: finished ? 'good' : undefined, hint: 'every trade reported there done' },
    { label: 'Under way', value: underWay || '—', tone: underWay ? 'info' : undefined },
  ]
  const hasLive = !!live.data?.maps.length

  return (
    <div className="mx-auto flex w-full max-w-6xl min-w-0 flex-col gap-4 pb-4 sm:px-2">
      <PageHeader title="Places"
        subtitle="Every floor and room, coloured by the work site reports. “First floor Room-2 plastering done” on WhatsApp lands on that room."
        actions={<>
          {hasLive && <Button asChild variant="outline" size="sm" className="gap-1.5"><Link to={`/planning/live?project=${projectId}`}><MapPinned className="size-3.5" /> On the drawings</Link></Button>}
          {list.data.can_edit && places.length > 0 && (
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setEditing((e) => !e)}>
              <Pencil className="size-3.5" /> {editing ? 'Done editing' : 'Edit'}
            </Button>
          )}
        </>} />
      {places.length === 0 ? (
        list.data.can_edit ? <QuickSetup projectId={projectId} suggested={list.data.suggested} /> : (
          <Callout tone="info" icon={Layers}>Floors and rooms are not set up for this project yet. The owner, an admin or the project manager sets them up here.</Callout>
        )
      ) : editing ? (
        <EditPlaces projectId={projectId} list={list.data} />
      ) : (
        <>
          <StatStrip stats={stats} phoneCols={2} />
          {kinds.length === 0 ? (
            <Callout tone="info" icon={Layers}>
              Nothing recorded by room yet. When site names the place in a work update (“FF R2 tiling 40 sqft”, “onnam nila kitchen wiring kazhinju”), it shows here.
            </Callout>
          ) : (
            <>
              <Legend />
              <Grid rows={rows} kinds={kinds} onOpen={setOpen} />
            </>
          )}
        </>
      )}
      <PlaceSheet projectId={projectId} row={open} kinds={kinds} onClose={() => setOpen(null)} />
    </div>
  )
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
      {(Object.keys(CELL) as CellState[]).map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5"><span className={cn('inline-block size-3 rounded-sm', CELL[s])} />{CELL_WORD[s]}</span>
      ))}
      <span>A floor is done when every room on it is.</span>
    </div>
  )
}

function Grid({ rows, kinds, onOpen }: { rows: PlaceProgressRow[]; kinds: PlacesProgress['kinds']; onOpen: (r: PlaceProgressRow) => void }) {
  const [shut, setShut] = React.useState<Set<string>>(new Set())
  const hasKids = (id: string) => rows.some((r) => r.parent_id === id)
  const hidden = (r: PlaceProgressRow): boolean => {
    let parent = r.parent_id
    while (parent) {
      if (shut.has(parent)) return true
      parent = rows.find((x) => x.id === parent)?.parent_id ?? null
    }
    return false
  }
  const toggle = (id: string) => setShut((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  return (
    <div className="overflow-x-auto rounded-lg border [contain:inline-size]">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            <th className="sticky left-0 z-10 bg-muted px-3 py-2 text-left font-medium">Place</th>
            {kinds.map((k) => <th key={k.key} className="px-1 py-2 text-center font-medium whitespace-nowrap">{k.name}</th>)}
            <th className="px-2 py-2 text-right font-medium">Photos</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.filter((r) => !hidden(r)).map((r) => (
            <tr key={r.id} className={cn(r.depth === 0 && 'bg-muted/20')}>
              <td className="sticky left-0 z-10 bg-background px-2 py-1.5 whitespace-nowrap">
                <div className="flex items-center gap-1" style={{ paddingLeft: r.depth * 16 }}>
                  {hasKids(r.id) ? (
                    <button type="button" className="rounded p-0.5 hover:bg-muted" aria-label={shut.has(r.id) ? `Show ${r.name}'s rooms` : `Hide ${r.name}'s rooms`} onClick={() => toggle(r.id)}>
                      {shut.has(r.id) ? <ChevronRight className="size-4" /> : <ChevronDown className="size-4" />}
                    </button>
                  ) : <span className="w-5" />}
                  <button type="button" className={cn('text-left hover:underline', r.depth === 0 && 'font-medium')} onClick={() => onOpen(r)}>{r.name}</button>
                </div>
              </td>
              {kinds.map((k) => {
                const c = r.cells[k.key]
                return (
                  <td key={k.key} className="px-1 py-1">
                    <button type="button" onClick={() => onOpen(r)} title={`${r.label}: ${k.name} ${CELL_WORD[c.state].toLowerCase()}${c.last ? `, last ${dayLabel(c.last)}` : ''}`}
                      className={cn('block h-7 w-full min-w-14 rounded text-[11px] font-medium', CELL[c.state])}>
                      {c.state === 'not_started' ? '' : c.state === 'done' ? '✓' : dayLabel(c.last)}
                    </button>
                  </td>
                )
              })}
              <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">{r.photos || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PlaceSheet({ projectId, row, kinds, onClose }: { projectId: string; row: PlaceProgressRow | null; kinds: PlacesProgress['kinds']; onClose: () => void }) {
  const work = useQuery({ queryKey: ['place-work', projectId, row?.id], queryFn: () => fetchPlaceWork(projectId, row!.id), enabled: !!row })
  return (
    <Sheet open={!!row} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{row?.label}</SheetTitle>
          <SheetDescription>
            {row && kinds.length ? (row.left.length ? `Left: ${row.left.join(', ')}` : 'Everything reported here is done') : 'Nothing recorded here yet'}
          </SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-3 px-4 pb-6">
          {row && row.done.length > 0 && <p className="text-sm"><span className="font-medium">Done:</span> {row.done.join(', ')}</p>}
          {!work.data ? <Skeleton className="h-32 w-full" /> : work.data.work.length === 0 ? (
            <p className="text-sm text-muted-foreground">No work recorded at this place yet.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {work.data.work.map((w) => (
                <li key={w.id} className="rounded-lg border p-3">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">{w.work_type || 'Work'}{w.finished && <span className="ml-1.5 text-xs text-success">finished</span>}</span>
                    <span className="text-xs text-muted-foreground">{dayLabel(w.date)}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">{w.place}{w.reported_by ? ` · ${w.reported_by}` : ''}</p>
                  {w.narrative && <p className="mt-1 text-sm">{w.narrative}</p>}
                  {w.photos.length > 0 && (
                    <div className="mt-2 grid grid-cols-3 gap-1.5">
                      {w.photos.map((url) => (
                        <a key={url} href={url} target="_blank" rel="noreferrer" className="block aspect-square overflow-hidden rounded-md bg-muted">
                          <img src={url} alt={`${w.work_type ?? 'Work'} at ${w.place}`} className="size-full object-cover" loading="lazy" />
                        </a>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          {row && row.photos > 0 && <p className="flex items-center gap-1 text-xs text-muted-foreground"><Camera className="size-3" /> {row.photos} photo{row.photos > 1 ? 's' : ''} here and in its rooms</p>}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function useRefresh(projectId: string) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['places', projectId] })
    qc.invalidateQueries({ queryKey: ['places-progress', projectId] })
  }
}

function QuickSetup({ projectId, suggested }: { projectId: string; suggested: PlacesList['suggested'] }) {
  const toast = useToast()
  const refresh = useRefresh(projectId)
  const [floors, setFloors] = React.useState(suggested.floors.join('\n'))
  const [rooms, setRooms] = React.useState(suggested.rooms.join('\n'))
  const f = nameLines(floors)
  const r = nameLines(rooms)
  const save = useMutation({
    mutationFn: () => setupPlaces(projectId, f, r),
    onSuccess: (out) => { toast.success(`${out.made.floors} floors and ${out.made.rooms} rooms set up`); refresh() },
    onError: (e) => toast.error('Could not set up the places', apiErrorMessage(e)),
  })
  return (
    <section className="flex flex-col">
      <h2 className="font-medium">Set up floors and rooms</h2>
      <p className="mb-3 text-sm text-muted-foreground">One per line. Every floor gets the same rooms; rename, add or remove any of them after.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1">
          <Label htmlFor="pl-floors">Floors</Label>
          <textarea id="pl-floors" rows={6} className="rounded-md border bg-background p-2 text-sm" value={floors} onChange={(e) => setFloors(e.target.value)} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="pl-rooms">Rooms on each floor</Label>
          <textarea id="pl-rooms" rows={6} className="rounded-md border bg-background p-2 text-sm" value={rooms} onChange={(e) => setRooms(e.target.value)} />
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{f.length} floors × {r.length} rooms = {f.length * r.length} rooms</span>
        <Button disabled={!f.length || save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Setting up…' : 'Set up'}</Button>
      </div>
    </section>
  )
}

function EditPlaces({ projectId, list }: { projectId: string; list: PlacesList }) {
  const toast = useToast()
  const refresh = useRefresh(projectId)
  const [names, setNames] = React.useState<Record<string, string>>({})
  const [adding, setAdding] = React.useState<Record<string, string>>({})
  const run = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: refresh,
    onError: (e) => toast.error('Could not change the place', apiErrorMessage(e)),
  })
  const add = (parent: string | null) => {
    const name = (adding[parent ?? 'root'] ?? '').trim()
    if (!name) return
    run.mutate(() => addPlace(projectId, name, parent))
    setAdding((a) => ({ ...a, [parent ?? 'root']: '' }))
  }
  const remove = (id: string, label: string) => {
    if (!window.confirm(`Remove ${label} and its rooms? Places with work recorded are kept on that work and hidden here.`)) return
    run.mutate(async () => {
      const out = await removePlace(projectId, id)
      toast.success(out.outcome === 'archived' ? `${label} hidden (its work is kept)` : `${label} removed`)
    })
  }
  const AddRow = ({ parent, placeholder }: { parent: string | null; placeholder: string }) => (
    <form className="flex gap-2" style={{ paddingLeft: parent ? 24 : 0 }} onSubmit={(e) => { e.preventDefault(); add(parent) }}>
      <Input className="h-8 max-w-64" placeholder={placeholder} value={adding[parent ?? 'root'] ?? ''} onChange={(e) => setAdding((a) => ({ ...a, [parent ?? 'root']: e.target.value }))} />
      <Button type="submit" size="sm" variant="outline" className="h-8 gap-1"><Plus className="size-3.5" /> Add</Button>
    </form>
  )
  return (
    <section className="flex flex-col gap-2">
      {list.places.map((p) => (
        <React.Fragment key={p.id}>
          <div className="flex items-center gap-2" style={{ paddingLeft: p.depth * 24 }}>
            <Input className={cn('h-8 max-w-64', p.depth === 0 && 'font-medium')} value={names[p.id] ?? p.name} aria-label={`Name of ${p.label}`}
              onChange={(e) => setNames((n) => ({ ...n, [p.id]: e.target.value }))}
              onBlur={() => { const v = (names[p.id] ?? p.name).trim(); if (v && v !== p.name) run.mutate(() => renamePlace(projectId, p.id, v)) }} />
            <Button size="icon" variant="ghost" className="size-8" aria-label={`Remove ${p.label}`} onClick={() => remove(p.id, p.label)}><Trash2 className="size-3.5" /></Button>
          </div>
          {endsFloor(list.places, p.id) && <AddRow parent={floorOf(list.places, p.id)} placeholder={`Add a room on ${list.places.find((f) => f.id === floorOf(list.places, p.id))?.name}`} />}
        </React.Fragment>
      ))}
      <div className="mt-2 border-t pt-3"><AddRow parent={null} placeholder="Add a floor (e.g. Terrace)" /></div>
    </section>
  )
}

type PlaceRow = PlacesList['places'][number]

/** The floor (root) a place is on. */
function floorOf(places: PlaceRow[], id: string): string {
  let p = places.find((x) => x.id === id)
  while (p?.parent_id) p = places.find((x) => x.id === p!.parent_id)
  return p?.id ?? id
}

/** True for the last place of a floor in tree order: the floor's "add a room" box goes after it. */
function endsFloor(places: PlaceRow[], id: string): boolean {
  const i = places.findIndex((x) => x.id === id)
  const next = places[i + 1]
  return !next || next.depth === 0
}
