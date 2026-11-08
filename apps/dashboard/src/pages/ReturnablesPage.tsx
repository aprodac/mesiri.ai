import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRightLeft, Download, Layers, Settings2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { usePageTitle } from '@/lib/page-title'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import { errorWords, fetchReturnables, setReturnable } from '@/lib/equipment'

// NXT-14: Equipment > Shuttering & tools. Plates, props, scaffold pipes and tools are materials in a returnable
// category (no second stock system): this page shows how many each site holds, what went out lost or damaged, and
// links to the material transfer to send them to another site. The office marks which categories are returnable.

const n = (v: string) => Number(v).toLocaleString('en-IN')

export default function ReturnablesPage() {
  usePageTitle('Shuttering & tools')
  const { scope } = useScope()
  const { me } = useAuth()
  const office = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'PROJECT_MANAGER'].includes((me?.role || '').toUpperCase())
  const toast = useToast()
  const qc = useQueryClient()
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : null
  const siteId = scope.mode === 'site' ? scope.siteId : null
  const [setup, setSetup] = React.useState(false)
  const { data, isLoading, isError } = useQuery({ queryKey: ['equipment', 'returnables', projectId, siteId], queryFn: () => fetchReturnables({ project_id: projectId, site_id: siteId }) })
  const toggle = useMutation({
    mutationFn: ({ id, on }: { id: string; on: boolean }) => setReturnable(id, on),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['equipment', 'returnables'] }),
    onError: (e) => toast.error('Not changed', errorWords(e)),
  })
  const items = data?.items ?? []
  const sites = data?.sites ?? []
  const anyReturnable = (data?.categories ?? []).some((c) => c.returnable || c.via_parent)
  const exportIt = () => exportCsv(`shuttering-and-tools-${new Date().toISOString().slice(0, 10)}.csv`,
    ['Item', 'Category', 'Unit', ...sites.map((s) => s.site_name ?? ''), 'Total held', 'Lost / damaged'],
    items.map((it) => [it.name, it.category ?? '', it.unit, ...sites.map((s) => it.sites.find((x) => x.site_id === s.site_id)?.held ?? ''), it.total, it.lost]))

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <Link to="/equipment" className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Machines</Link>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-200"><Layers className="size-5" /></span>
          <div>
            <div className="text-xs text-muted-foreground">Equipment</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">Shuttering & tools</h1>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" className="gap-2" asChild><Link to="/materials?view=movements"><ArrowRightLeft className="size-4" /><span className="hidden sm:inline">Send to a site</span></Link></Button>
          <Button variant="outline" className="gap-2" disabled={!items.length} onClick={exportIt}><Download className="size-4" /><span className="hidden sm:inline">Export</span></Button>
          {office && <Button variant={setup || !anyReturnable ? 'default' : 'outline'} className="gap-2" onClick={() => setSetup((s) => !s)}><Settings2 className="size-4" />Categories</Button>}
        </div>
      </header>

      {(setup || (office && data && !anyReturnable)) && (
        <section aria-label="Returnable categories" className="flex flex-col gap-2 rounded-xl border bg-card p-4">
          <p className="text-sm"><strong>Which material categories come back?</strong> <span className="text-muted-foreground">Shuttering plates, props, scaffolding, tools: their stock per site shows here. A main category includes its sub-categories.</span></p>
          <div className="flex flex-wrap gap-2">
            {(data?.categories ?? []).filter((c) => !c.parent_id || !c.via_parent).map((c) => {
              const on = c.returnable || c.via_parent
              return (
                <button key={c.id} type="button" aria-pressed={on} disabled={c.via_parent || toggle.isPending} onClick={() => toggle.mutate({ id: c.id, on: !c.returnable })}
                  className={cn('h-8 rounded-full border px-3 text-sm transition', on ? 'border-teal-500 bg-teal-50 font-semibold text-teal-900 dark:bg-teal-950 dark:text-teal-100' : 'bg-background hover:border-foreground/40')}>
                  {c.parent_name ? `${c.parent_name} › ` : ''}{c.name}
                </button>
              )
            })}
            {data && !data.categories.length && <span className="text-sm text-muted-foreground">No material categories yet: add one (Shuttering) in <Link className="underline" to="/materials?view=items">Materials › Items</Link>.</span>}
          </div>
        </section>
      )}

      {isLoading && <div className="h-40 animate-pulse rounded-xl bg-muted/40" />}
      {isError && <p className="text-sm text-destructive">Did not load. Refresh to try again.</p>}
      {data && items.length === 0 && anyReturnable && (
        <p className="rounded-xl border p-8 text-center text-sm text-muted-foreground">Nothing in the returnable categories is at a site yet. Record plates or props coming to a site in Materials, as any delivery.</p>
      )}
      {items.length > 0 && (
        <section className="overflow-x-auto rounded-xl border">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Item</th>
                {sites.map((s) => <th key={s.site_id} className="px-3 py-2 text-right font-medium">{s.site_name}<span className="block font-normal">{s.project_name}</span></th>)}
                <th className="px-3 py-2 text-right font-medium">Total</th>
                <th className="px-4 py-2 text-right font-medium">Lost / damaged</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.material_id} className="border-t">
                  <td className="px-4 py-2.5"><span className="font-semibold">{it.name}</span><span className="block text-xs text-muted-foreground">{it.category}</span></td>
                  {sites.map((s) => {
                    const at = it.sites.find((x) => x.site_id === s.site_id)
                    const held = at ? Number(at.held) : 0
                    return <td key={s.site_id} className={cn('px-3 py-2.5 text-right tabular-nums', !held && 'text-muted-foreground/50', held < 0 && 'text-destructive')}>{at ? n(at.held) : '–'}{at && <span className="ml-1 text-xs text-muted-foreground">{it.unit}</span>}</td>
                  })}
                  <td className="px-3 py-2.5 text-right font-semibold tabular-nums">{n(it.total)} <span className="text-xs font-normal text-muted-foreground">{it.unit}</span></td>
                  <td className={cn('px-4 py-2.5 text-right tabular-nums', Number(it.lost) > 0 ? 'font-semibold text-red-700 dark:text-red-300' : 'text-muted-foreground/60')}>{Number(it.lost) ? n(it.lost) : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <p className="text-xs text-muted-foreground">Send plates to another site with a material transfer (Materials › Movements, or on WhatsApp: "60 plates villa-il ninnu Chennai-ilekku ayachu"). Lost or damaged: record a usage marked wastage.</p>
    </div>
  )
}
