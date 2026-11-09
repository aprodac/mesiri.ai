import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { Building2, CornerDownLeft, Search } from 'lucide-react'
import { Dialog, DialogTitle } from '@/components/ui/dialog'
import { useAuth } from '@/lib/AuthContext'
import { useModuleEnabled } from '@/lib/modules'
import { MODULE_GROUPS, PAGE_ICONS, SECTION_TITLES } from '@/lib/module-map'
import { fetchProjects } from '@/lib/projects'
import { cn } from '@/lib/utils'
import { JUMP_EVENT } from '@/lib/jump'

// UX-04: one box that jumps to any page or project (Ctrl K / Cmd K, or Search in the sidebar). Built on the
// existing dialog rather than a new library; pages come from lib/module-map.ts, so a new page is findable
// as soon as it is in the map.


type Result = { key: string; title: string; hint: string; url: string; icon: React.ElementType; words: string }

function score(result: Result, query: string): number {
  if (!query) return 1
  const q = query.toLowerCase()
  const title = result.title.toLowerCase()
  if (title.startsWith(q)) return 3
  if (title.includes(q)) return 2
  return q.split(/\s+/).every((part) => result.words.includes(part)) ? 1 : 0
}

export function JumpBox() {
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState('')
  const [active, setActive] = React.useState(0)
  const navigate = useNavigate()
  const { me } = useAuth()
  const isModuleEnabled = useModuleEnabled()
  const role = (me?.role || '').toUpperCase()
  const isAdmin = role === 'ADMIN'
  const projects = useQuery({ queryKey: ['jump', 'projects'], queryFn: fetchProjects, enabled: open, staleTime: 60_000 })

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen((value) => !value)
      }
    }
    const onOpen = () => setOpen(true)
    window.addEventListener('keydown', onKey)
    window.addEventListener(JUMP_EVENT, onOpen)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener(JUMP_EVENT, onOpen)
    }
  }, [])

  React.useEffect(() => {
    if (!open) {
      setQuery('')
      setActive(0)
    }
  }, [open])

  const results = React.useMemo(() => {
    const pages: Result[] = MODULE_GROUPS.filter((group) => isModuleEnabled(group.module)).flatMap((group) =>
      group.pages
        .filter((p) => !p.shortcut && p.status === 'built' && (!p.roles || p.roles.includes(role)) && (!p.module || isModuleEnabled(p.module)))
        .map((p) => ({
          key: p.url,
          title: p.title,
          hint: group.key === 'site' ? SECTION_TITLES.daily : (SECTION_TITLES[group.section] === group.title ? group.title : `${SECTION_TITLES[group.section]} · ${group.title}`),
          url: p.url,
          icon: PAGE_ICONS[p.url] ?? group.icon,
          words: `${p.title} ${p.navTitle ?? ''} ${group.title} ${p.about}`.toLowerCase(),
        })),
    )
    const projectRows: Result[] = (projects.data ?? []).map((p) => ({
      key: `project-${p.id}`,
      title: p.name,
      hint: 'Project',
      url: isAdmin ? `/projects/${p.id}` : `/today?project=${p.id}`,
      icon: Building2,
      words: `${p.name} project`.toLowerCase(),
    }))
    return [...projectRows, ...pages]
      .map((r) => ({ r, s: score(r, query.trim()) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, query ? 12 : 9)
      .map((x) => x.r)
  }, [query, projects.data, role, isAdmin, isModuleEnabled])

  const go = (result: Result | undefined) => {
    if (!result) return
    setOpen(false)
    navigate(result.url)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <DialogPrimitive.Content
          className="fixed top-[12vh] left-1/2 z-50 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 overflow-hidden rounded-xl border bg-background shadow-xl"
          aria-describedby={undefined}
        >
          <DialogTitle className="sr-only">Search Mesiri</DialogTitle>
          <div className="flex items-center gap-2 border-b px-3">
            <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <input
              autoFocus
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setActive(0)
              }}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') {
                  event.preventDefault()
                  setActive((i) => Math.min(i + 1, results.length - 1))
                } else if (event.key === 'ArrowUp') {
                  event.preventDefault()
                  setActive((i) => Math.max(i - 1, 0))
                } else if (event.key === 'Enter') {
                  event.preventDefault()
                  go(results[active])
                }
              }}
              placeholder="Jump to a page or project…"
              aria-label="Search pages and projects"
              className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <ul role="listbox" aria-label="Results" className="max-h-[50vh] overflow-y-auto p-1.5">
            {results.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted-foreground">Nothing matches “{query}”.</li>}
            {results.map((result, index) => {
              const Icon = result.icon
              return (
                <li key={result.key} role="option" aria-selected={index === active}>
                  <button
                    type="button"
                    onMouseEnter={() => setActive(index)}
                    onClick={() => go(result)}
                    className={cn('flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-sm', index === active && 'bg-muted')}
                  >
                    <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1 truncate font-medium">{result.title}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">{result.hint}</span>
                    {index === active && <CornerDownLeft className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />}
                  </button>
                </li>
              )
            })}
          </ul>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </Dialog>
  )
}
