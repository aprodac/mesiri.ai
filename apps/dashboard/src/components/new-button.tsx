import { ChevronDown, MessageSquarePlus, Plus } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth } from '@/lib/AuthContext'
import { useModuleEnabled, type ModuleKey } from '@/lib/modules'
import { openTellMesiri } from '@/lib/tell-mesiri-events'
import { useTrial } from '@/lib/trial'

// UX-74 (asked 20 Nov 2026: the top bar "has On WhatsApp, then a help, then an issues icon ... very messy"): the
// sidebar's "+ New" (UX-16) and the top bar's "Tell Mesiri" were two doors to one assistant. Now one button: New
// opens the list of what this role records, each line starting the sentence in Tell Mesiri (the same assistant as
// WhatsApp), and "Tell Mesiri anything" at its top for a question or anything else.

const OFFICE = ['ADMIN', 'OWNER', 'SUPER_ADMIN'] as const
type NewAction = { key: string; label: string; example: string; starter: string; roles: readonly string[]; module?: ModuleKey }
const NEW_ACTIONS: NewAction[] = [
  { key: 'update', label: 'Site update', example: '6 masons, slab shuttering done', starter: 'Today at site: ', roles: ['SITE_ENGINEER', 'PROJECT_MANAGER', ...OFFICE], module: 'dpr' },
  { key: 'request', label: 'Material request', example: 'Need 50 bags cement by Thursday', starter: 'Need ', roles: ['SITE_ENGINEER', 'PROJECT_MANAGER', ...OFFICE], module: 'materials' },
  { key: 'issue', label: 'Report an issue', example: 'Water tank leaking near block B', starter: 'Problem: ', roles: ['SITE_ENGINEER', 'PROJECT_MANAGER', ...OFFICE] },
  { key: 'task', label: 'Task', example: 'Ravi: fix the shuttering by Friday', starter: 'Task for ', roles: ['PROJECT_MANAGER', ...OFFICE], module: 'tasks' },
  { key: 'expense', label: 'Expense', example: 'Paid 2,400 for diesel at Lake View', starter: 'Paid ', roles: ['FINANCE', 'PROJECT_MANAGER', ...OFFICE], module: 'finance' },
  // WEB-100: who may make one (mayCreateProject); the form itself is New project on Projects & Sites and Project start.
  { key: 'project', label: 'Project', example: 'Lake View for Mr Thomas at Kakkanad, starts 1 Dec', starter: 'New project ', roles: ['ADMIN', 'PROJECT_MANAGER'] },
]

const YELLOW =
  'inline-flex h-8 items-center gap-1.5 rounded-full bg-[#ffd23f] px-3 text-sm font-semibold text-[#2A2829] hover:brightness-105 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#ffd23f]'

export function NewButton() {
  const { me } = useAuth()
  const trial = useTrial()
  const on = useModuleEnabled()
  const role = (me?.role || '').toUpperCase()
  const actions = trial.readOnly ? [] : NEW_ACTIONS.filter((a) => a.roles.includes(role) && (!a.module || on(a.module)))
  if (actions.length === 0) {
    return (
      <button type="button" onClick={() => openTellMesiri()} data-guide="app.tell" className={YELLOW} title="Tell Mesiri: type or speak an update or a question" aria-label="Tell Mesiri">
        <MessageSquarePlus className="size-4" aria-hidden />
        <span className="hidden sm:inline">Tell Mesiri</span>
      </button>
    )
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" data-guide="app.tell" className={YELLOW} title="New: record something, or tell Mesiri" aria-label="New">
          <Plus className="size-4" strokeWidth={2.5} aria-hidden />
          <span className="hidden sm:inline">New</span>
          <ChevronDown className="-mr-1 hidden size-3.5 opacity-70 sm:inline" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuItem onSelect={() => openTellMesiri()} className="gap-2.5">
          <MessageSquarePlus className="size-4" aria-hidden />
          <span className="flex flex-col">
            <span className="text-sm font-medium">Tell Mesiri anything</span>
            <span className="text-xs text-muted-foreground">Type or speak, like on WhatsApp</span>
          </span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs text-muted-foreground">Or start one of these</DropdownMenuLabel>
        {actions.map((a) => (
          <DropdownMenuItem key={a.key} onSelect={() => openTellMesiri(a.starter)} className="flex-col items-start gap-0.5">
            <span className="text-sm font-medium">{a.label}</span>
            <span className="text-xs text-muted-foreground">{a.example}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
