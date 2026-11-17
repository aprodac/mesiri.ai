import { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { SETTINGS_PATHS, urlWithScope } from '@/lib/scope-url'
import { flushSync } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LogOut,
  ArrowLeft,
  Activity,
  BarChart3,
  FileText,
  ChevronRight,
  CalendarDays,
  Sun,
  Moon,
  Clock,
  AlertCircle,
  Palette,
  ListChecks,
  Map as MapIcon,
  Radio,
  Search,
  Settings as SettingsIcon,
  Upload,
  GraduationCap,
  ChevronsUpDown,
  Plus,
} from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar'
import { useAuth } from '@/lib/AuthContext'
import { useAllowedScopes, useScope } from '@/lib/ScopeContext'
import { fetchBranding, logout, type Me } from '@/lib/api'
import { MesiriMark, MesiriWordmark } from '@/components/brand/mesiri-logo'
import { SETUP_URL, setupCounts, useGuideSteps, useSetupProgress } from '@/lib/setup'
import { useTrial } from '@/lib/trial'
import type { ScopeKind } from '@/lib/scope-types'
import { cn } from '@/lib/utils'
import { useModuleEnabled, type ModuleKey } from '@/lib/modules'
import { SIDEBAR_THEME_NAMES, useSidebarTheme, type SidebarTheme } from '@/lib/sidebar-theme'
import { openTellMesiri } from '@/lib/tell-mesiri-events'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useNavCounts, useTaskCounts } from '@/lib/nav-counts'
import { MODULE_GROUPS, PAGE_ICONS, SECTION_TITLES, findPage, sectionOrder, type ModuleGroup, type NavSection } from '@/lib/module-map'
import { openJump } from '@/lib/jump'
import { usePlannedPreview } from '@/lib/preview'
import { useShowEverything, useStartMode } from '@/lib/start-mode'

type NavItem = {
  title: string
  url: string
  icon: React.ComponentType<{ className?: string }>
  requiredScope?: ScopeKind
  requiredRole?: string
  // Shown only to these roles (SEC-01: who may read expenses).
  allowedRoles?: readonly string[]
  // Switched-off modules are hidden (WEB-02); see lib/modules.tsx.
  module?: ModuleKey
  // Which live count to show as a badge (WEB-20).
  badge?: 'drafts' | 'issues'
  // A page's own live count (TSK-06), as on a drawer's page.
  count?: SubCount
  // Lit only on its own view (?view=), as a drawer's page is: a section's flat rows (Tasks).
  exact?: boolean
  // Small text at the row's end, e.g. "3/6" on Finish setup (SS-19).
  note?: string
  // A planned page (WEB-72), shown only with the preview on.
  soon?: boolean
}

// A collapsible module in the sidebar (WEB-72): its pages come from lib/module-map.ts.
// A live count on a drawer's page (TSK-06): `tone` is the badge colour, `label` what the number means.
type SubCount = { n: number; tone: keyof typeof BADGE; label: string }
type SubItem = { title: string; url: string; soon?: boolean; phase?: string; count?: SubCount }
type NavCategory = {
  key: string
  title: string
  icon: React.ElementType
  items: SubItem[]
}

const NON_ADMIN_ROLES = ['PROJECT_MANAGER', 'SITE_ENGINEER', 'FINANCE'] as const

// The sidebar tells the project's story (UX-04, docs/plans/ui-story-plan.md section 4): the daily pages, then
// PLAN, SITE, BUY and MONEY (in the order the role reaches for them, lib/module-map.ts sectionOrder), then
// Settings. Each page has one home; a module with one page is a link, with several a drawer. Modules a
// company has not switched on (WEB-02) and pages a role may not see are hidden.
const PRIMARY_ITEMS: NavItem[] = [
  { title: 'Today', url: '/today', icon: CalendarDays, badge: 'drafts' },
  { title: 'Daily reports', url: '/reports', icon: FileText },
  { title: 'Issues', url: '/issues', icon: AlertCircle, badge: 'issues' },
  { title: 'Live', url: '/live', icon: Radio },
]

// Site records live in the SITE section.
const RECORD_ITEMS: NavItem[] = [
  { title: 'Site log', url: '/site-log', icon: Activity },
  { title: 'Analytics', url: '/analytics', icon: BarChart3 },
]

const ROOT_MANAGEMENT_ITEMS: NavItem[] = [
  { title: 'Settings', url: '/settings', icon: SettingsIcon, requiredRole: 'ADMIN' },
  // WEB-31: the inbox APIs answer admins only. Others who have Automations
  // get that view of the WhatsApp page on its own.
  { title: 'Automations', url: '/whatsapp?view=automations', icon: Clock, module: 'automations', allowedRoles: NON_ADMIN_ROLES },
]

// UX-16: "+ New" next to Search. Each line opens Tell Mesiri (the same assistant as WhatsApp) with its first words
// typed in, so the person finishes the sentence instead of hunting for a form. Only what the role records, and only
// in switched-on modules.
const OFFICE = ['ADMIN', 'OWNER', 'SUPER_ADMIN'] as const
type NewAction = { key: string; label: string; example: string; starter: string; roles: readonly string[]; module?: ModuleKey }
const NEW_ACTIONS: NewAction[] = [
  { key: 'update', label: 'Site update', example: '6 masons, slab shuttering done', starter: 'Today at site: ', roles: ['SITE_ENGINEER', 'PROJECT_MANAGER', ...OFFICE], module: 'dpr' },
  { key: 'request', label: 'Material request', example: 'Need 50 bags cement by Thursday', starter: 'Need ', roles: ['SITE_ENGINEER', 'PROJECT_MANAGER', ...OFFICE], module: 'materials' },
  { key: 'issue', label: 'Report an issue', example: 'Water tank leaking near block B', starter: 'Problem: ', roles: ['SITE_ENGINEER', 'PROJECT_MANAGER', ...OFFICE] },
  { key: 'task', label: 'Task', example: 'Ravi: fix the shuttering by Friday', starter: 'Task for ', roles: ['PROJECT_MANAGER', ...OFFICE], module: 'tasks' },
  { key: 'expense', label: 'Expense', example: 'Paid 2,400 for diesel at Lake View', starter: 'Paid ', roles: ['FINANCE', 'PROJECT_MANAGER', ...OFFICE], module: 'finance' },
]

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase()
}

function roleLabel(role: string | undefined): string {
  if (!role) return ''
  return role
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

// Visual tokens per sidebar theme. Taupe is the default (UX-16); Light follows the
// app's shadcn tokens (so it also darkens correctly in dark mode). `aside` also
// re-points the --sidebar-* variables, so the shadcn sidebar parts' own hover,
// active and focus styles match the theme without changing ui/sidebar.tsx.
const SIDEBAR_THEMES = {
  light: {
    aside:
      'bg-[#EEF1F6] text-foreground dark:bg-card [--sidebar:#EEF1F6] dark:[--sidebar:var(--card)] [--sidebar-foreground:var(--foreground)] [--sidebar-accent:#FFFFFF] dark:[--sidebar-accent:var(--muted)] [--sidebar-accent-foreground:var(--foreground)] [--sidebar-border:rgba(0,0,0,0.06)] dark:[--sidebar-border:var(--border)] [--sidebar-ring:var(--ring)]',
    edge: 'border-black/[0.06] dark:border-border',
    ring: 'focus-visible:ring-ring',
    rowIdle: 'text-foreground/70 hover:bg-black/[0.04] hover:text-foreground dark:hover:bg-muted',
    rowActive: 'bg-white text-foreground font-semibold shadow-xs dark:bg-muted',
    hoverBg: 'hover:bg-black/[0.04] dark:hover:bg-muted',
    label: 'text-muted-foreground',
    icon: 'text-muted-foreground group-hover/row:text-foreground',
    iconActive: 'text-foreground',
    iconBtn: 'text-muted-foreground hover:text-foreground hover:bg-white dark:hover:bg-background',
    divider: 'border-black/[0.06] dark:border-border',
    guide: 'border-black/[0.08] dark:border-border',
    chevron: 'text-muted-foreground',
    groupIdle: 'text-foreground/70 hover:text-foreground',
    groupActive: 'text-foreground font-semibold',
    card: 'border-black/[0.06] bg-white dark:border-border dark:bg-background',
    soon: 'bg-black/[0.06] text-foreground/60 dark:bg-muted dark:text-muted-foreground',
    headerBg: '[--sidebar-header:#FFFFFF] dark:[--sidebar-header:var(--background)]',
    headerText: 'text-foreground',
    headerBtn: 'text-muted-foreground hover:text-foreground hover:bg-black/[0.04] dark:hover:bg-muted',
    avatar: 'bg-white text-foreground border border-black/[0.06] dark:bg-background dark:border-border',
    danger: 'hover:text-destructive',
    name: 'text-foreground',
    role: 'text-muted-foreground',
    scrollbar: 'sidebar-scrollbar-light',
    bar: '#FACC15',
    swatch: '#EEF1F6',
  },
  // UX-16 (17 Nov 2026): warm taupe, the default. Text is a near-white solid (not white at an opacity) so rows and
  // labels keep 4.5:1 on #6E665B.
  taupe: {
    aside:
      'bg-[#6E665B] text-[#F2EFEA] [--sidebar:#6E665B] [--sidebar-foreground:#F2EFEA] [--sidebar-accent:rgba(255,255,255,0.12)] [--sidebar-accent-foreground:#FFFFFF] [--sidebar-border:rgba(255,255,255,0.12)] [--sidebar-ring:rgba(255,255,255,0.40)]',
    edge: 'border-white/[0.08]',
    ring: 'focus-visible:ring-white/40',
    rowIdle: 'text-[#F2EFEA] hover:bg-white/[0.10] hover:text-white',
    rowActive: 'bg-white/[0.16] text-white font-semibold',
    hoverBg: 'hover:bg-white/[0.10]',
    label: 'text-[#EAE5DD]',
    icon: 'text-white/70 group-hover/row:text-white',
    iconActive: 'text-white',
    iconBtn: 'text-white/75 hover:text-white hover:bg-white/10',
    divider: 'border-white/[0.14]',
    guide: 'border-white/20',
    chevron: 'text-white/70',
    groupIdle: 'text-[#F2EFEA] hover:text-white',
    groupActive: 'text-white font-semibold',
    card: 'border-white/15 bg-white/[0.08]',
    soon: 'bg-white/15 text-white/80',
    headerBg: '[--sidebar-header:#F3EFE8]',
    headerText: 'text-[#4A443C]',
    headerBtn: 'text-[#4A443C]/70 hover:text-[#4A443C] hover:bg-black/[0.06]',
    avatar: 'bg-white/15 text-white',
    danger: 'hover:text-[#FFD0C7]',
    name: 'text-white',
    role: 'text-[#EAE5DD]',
    scrollbar: 'sidebar-scrollbar',
    bar: '#FACC15',
    swatch: '#6E665B',
  },
  sand: {
    aside:
      'bg-[#F7F3EA] text-[#45403A] [--sidebar:#F7F3EA] [--sidebar-foreground:#45403A] [--sidebar-accent:#EFE8DA] [--sidebar-accent-foreground:#1C1A17] [--sidebar-border:#E3DBCB] [--sidebar-ring:#6E665B]',
    edge: 'border-[#E3DBCB]',
    ring: 'focus-visible:ring-[#6E665B]',
    rowIdle: 'text-[#45403A] hover:bg-[#EFE8DA] hover:text-[#1C1A17]',
    rowActive: 'bg-[#E8DCC2] text-[#1C1A17] font-semibold',
    hoverBg: 'hover:bg-[#EFE8DA]',
    label: 'text-[#6E665B]',
    icon: 'text-[#6E665B] group-hover/row:text-[#1C1A17]',
    iconActive: 'text-[#1C1A17]',
    iconBtn: 'text-[#6E665B] hover:text-[#1C1A17] hover:bg-[#EFE8DA]',
    divider: 'border-[#E3DBCB]',
    guide: 'border-[#DDD3BF]',
    chevron: 'text-[#6E665B]',
    groupIdle: 'text-[#45403A] hover:text-[#1C1A17]',
    groupActive: 'text-[#1C1A17] font-semibold',
    card: 'border-[#E3DBCB] bg-white',
    soon: 'bg-[#EFE8DA] text-[#6E665B]',
    headerBg: '[--sidebar-header:#3E3C3D]',
    headerText: 'text-white',
    headerBtn: 'text-white/70 hover:text-white hover:bg-white/10',
    avatar: 'bg-white text-[#1C1A17] border border-[#E3DBCB]',
    danger: 'hover:text-destructive',
    name: 'text-[#1C1A17]',
    role: 'text-[#6E665B]',
    scrollbar: 'sidebar-scrollbar-light',
    bar: '#FACC15',
    swatch: '#F7F3EA',
  },
  green: {
    aside:
      'bg-[#14342B] text-[#EAF2EE] [--sidebar:#14342B] [--sidebar-foreground:#EAF2EE] [--sidebar-accent:rgba(255,255,255,0.10)] [--sidebar-accent-foreground:#FFFFFF] [--sidebar-border:rgba(255,255,255,0.08)] [--sidebar-ring:rgba(255,255,255,0.35)]',
    edge: 'border-white/[0.06]',
    ring: 'focus-visible:ring-white/35',
    rowIdle: 'text-white/75 hover:bg-white/[0.07] hover:text-white',
    rowActive: 'bg-white/[0.12] text-white font-semibold',
    hoverBg: 'hover:bg-white/[0.07]',
    label: 'text-white/55',
    icon: 'text-white/50 group-hover/row:text-white/85',
    iconActive: 'text-white',
    iconBtn: 'text-white/50 hover:text-white hover:bg-white/10',
    divider: 'border-white/[0.08]',
    guide: 'border-white/10',
    chevron: 'text-white/45',
    groupIdle: 'text-white/75 hover:text-white',
    groupActive: 'text-white font-semibold',
    card: 'border-white/10 bg-white/[0.06]',
    soon: 'bg-white/10 text-white/60',
    headerBg: '[--sidebar-header:#E8F0EC]',
    headerText: 'text-[#14342B]',
    headerBtn: 'text-[#14342B]/60 hover:text-[#14342B] hover:bg-black/[0.06]',
    avatar: 'bg-white/10 text-white',
    danger: 'hover:text-[#FF9A8B]',
    name: 'text-white',
    role: 'text-white/55',
    scrollbar: 'sidebar-scrollbar',
    bar: '#FACC15',
    swatch: '#14342B',
  },
} as const

// One icon colour (UX-03): icons are muted and the active row's icon takes the ink, so colour in the
// sidebar means only a badge (orange: waiting on someone, red: something is wrong).
// Badges: orange = waiting on someone, red = something is wrong.
const BADGE = {
  drafts: 'bg-orange-500 text-white',
  issues: 'bg-rose-500 text-white',
} as const

const NAV_LINK_BASE =
  'group/row flex items-center gap-2.5 w-full px-2.5 py-2 rounded-lg text-sm transition-colors'

// Settings' pages keep their own addresses (UX-04); the Settings row lights up on any of them (lib/scope-url.ts).

function checkIsItemActive(pathname: string, itemUrl: string): boolean {
  if (pathname === itemUrl) return true
  if (itemUrl === '/settings') return SETTINGS_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))
  if (itemUrl === '/today' && pathname === '/') return true
  if (itemUrl === '/operations/dashboard' && (pathname === '/operations' || pathname === '/operations/dashboard' || pathname === '/overview')) return true
  if (itemUrl === '/finance/expenses' && pathname === '/finance') return true
  if (itemUrl === '/materials/overview' && pathname === '/materials') return true
  if (itemUrl !== '/' && pathname.startsWith(itemUrl)) return true
  return false
}

/** Is this sub-item the page on screen? Views (?view=) of one page count separately. */
function isSubItemActive(pathname: string, search: string, url: string): boolean {
  const hit = findPage(pathname, search)
  if (hit) return hit.page.url === url
  return checkIsItemActive(pathname, url.split('?')[0])
}

function CollapsibleNavCategory({
  category,
  getUrlWithScope,
  pathname,
  search,
  theme,
}: {
  category: NavCategory
  getUrlWithScope: (url: string) => string
  pathname: string
  search: string
  theme: SidebarTheme
}) {
  const S = SIDEBAR_THEMES[theme]
  const { state, isMobile } = useSidebar()
  const navigate = useNavigate()
  const isCollapsedMode = state === 'collapsed' && !isMobile
  const isChildActive = category.items.some((item) => isSubItemActive(pathname, search, item.url))
  const [isOpen, setIsOpen] = useState(isChildActive)
  // UX-16: hover a closed drawer (or any drawer in icon mode) and its pages appear beside it, so a page is one move
  // away without opening the drawer. Mouse only; a tap or the keyboard still opens the drawer in place.
  const canHover = useCanHover()
  const flyAllowed = canHover && !isMobile && (isCollapsedMode || !isOpen)
  // `at` is the page and drawer state the list opened on: a click, a route change or the drawer opening hides it.
  const flyAt = `${pathname}${search}|${isOpen}|${state}`
  const [flyState, setFly] = useState<{ top: number; left: number; at: string } | null>(null)
  const fly = flyState && flyState.at === flyAt ? flyState : null
  const flyTimer = useRef<number | undefined>(undefined)
  const openFly = (e: React.MouseEvent<HTMLElement>) => {
    if (!flyAllowed) return
    const r = e.currentTarget.getBoundingClientRect()
    // Open beside the sidebar's edge, not over it.
    const edge = e.currentTarget.closest('[data-sidebar="sidebar"]')?.getBoundingClientRect().right ?? r.right
    window.clearTimeout(flyTimer.current)
    flyTimer.current = window.setTimeout(() => setFly({ top: r.top, left: edge + 6, at: flyAt }), 120)
  }
  const closeFly = () => {
    window.clearTimeout(flyTimer.current)
    flyTimer.current = window.setTimeout(() => setFly(null), 160)
  }
  const keepFly = () => window.clearTimeout(flyTimer.current)

  useEffect(() => {
    if (isChildActive) setIsOpen(true)
  }, [pathname, isChildActive])
  useEffect(() => () => window.clearTimeout(flyTimer.current), [])
  useEffect(() => {
    if (!fly) return
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setFly(null)
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [fly])

  if (category.items.length === 0) return null
  const IconComp = category.icon
  const allSoon = category.items.every((i) => i.soon)
  // Closed, the drawer shows its most urgent count (red before orange), so nothing waits unseen.
  const counted = category.items.map((i) => i.count).filter((c): c is SubCount => !!c && c.n > 0)
  const headline = counted.find((c) => c.tone === 'issues') ?? counted[0]

  return (
    <SidebarMenuItem onMouseEnter={openFly} onMouseLeave={closeFly}>
      <SidebarMenuButton
        // Icons only: open the module's first page instead of a list nobody can see.
        onClick={() => (isCollapsedMode ? navigate(getUrlWithScope(category.items[0].url)) : setIsOpen((prev) => !prev))}
        // With a mouse the hover list names the module; the tooltip stays for touch.
        tooltip={canHover ? undefined : allSoon ? `${category.title} · planned` : category.title}
        aria-haspopup={canHover ? 'menu' : undefined}
        aria-label={category.title}
        aria-expanded={isOpen}
        className={cn(
          'relative flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-sm transition-colors',
          S.hoverBg,
          S.ring,
          isChildActive ? S.groupActive : S.groupIdle,
        )}
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="relative shrink-0">
            <IconComp className={cn('size-4', isChildActive ? S.iconActive : S.icon)} />
            {headline && (
              <span aria-hidden className={cn('absolute -top-1 -right-1 hidden size-2 rounded-full ring-2 ring-sidebar group-data-[collapsible=icon]:block', BADGE[headline.tone])} />
            )}
          </span>
          <span className={cn('truncate group-data-[collapsible=icon]:hidden', allSoon && !isChildActive && 'opacity-70')}>{category.title}</span>
        </div>
        <span className={cn('flex items-center gap-1.5 group-data-[collapsible=icon]:hidden', S.chevron)}>
          {headline && !isOpen && <CountPill count={headline} />}
          <ChevronRight className={cn('size-3.5 transition-transform duration-200', isOpen && 'rotate-90')} />
        </span>
      </SidebarMenuButton>

      {isOpen && !isCollapsedMode && (
        <div className={cn('my-0.5 ml-4 flex flex-col gap-0.5 border-l pl-2.5 group-data-[collapsible=icon]:hidden', S.guide)}>
          {category.items.map((item) => {
            const active = isSubItemActive(pathname, search, item.url)
            return (
              <Link
                key={item.url}
                to={getUrlWithScope(item.url)}
                title={item.soon ? `${item.title} · planned (${item.phase}), not built yet` : undefined}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'group/row relative flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] transition-colors',
                  S.ring,
                  active ? S.rowActive : S.rowIdle,
                  item.soon && !active && 'opacity-75',
                )}
              >
                {active && <span aria-hidden className="absolute top-1.5 bottom-1.5 -left-[13px] w-[3px] rounded-full" style={{ backgroundColor: S.bar }} />}
                <span className="truncate">{item.title}</span>
                {item.soon && <SoonDot className="ml-auto" />}
                {item.count && item.count.n > 0 && <CountPill count={item.count} className="ml-auto" />}
              </Link>
            )
          })}
        </div>
      )}
      {fly &&
        createPortal(
          <div
            role="menu"
            aria-label={category.title}
            onMouseEnter={keepFly}
            onMouseLeave={closeFly}
            style={{
              position: 'fixed',
              left: fly.left,
              // Stay on screen: a drawer near the bottom opens its list upwards.
              top: Math.max(8, Math.min(fly.top - 6, window.innerHeight - (48 + category.items.length * 34) - 8)),
              zIndex: 60,
            }}
            className="min-w-56 max-w-72 rounded-xl border bg-popover p-1.5 text-popover-foreground shadow-lg animate-in fade-in-0 zoom-in-95"
          >
            <div className="px-2.5 pt-1.5 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{category.title}</div>
            {category.items.map((item) => {
              const active = isSubItemActive(pathname, search, item.url)
              return (
                <Link
                  key={item.url}
                  role="menuitem"
                  to={getUrlWithScope(item.url)}
                  onClick={() => setFly(null)}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none',
                    active && 'bg-muted font-semibold',
                    item.soon && !active && 'opacity-70',
                  )}
                >
                  <span className="truncate">{item.title}</span>
                  {item.soon && <SoonDot className="ml-auto" />}
                  {item.count && item.count.n > 0 && <CountPill count={item.count} className="ml-auto" />}
                </Link>
              )
            })}
          </div>,
          document.body,
        )}
    </SidebarMenuItem>
  )
}

/** A mouse or trackpad that can hover (not a phone or tablet), read once. */
function useCanHover(): boolean {
  const [can] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.('(hover: hover) and (pointer: fine)').matches)
  return can
}

function CountPill({ count, className }: { count: SubCount; className?: string }) {
  return (
    <span className={cn('min-w-5 rounded-full px-1.5 py-px text-center text-[11px] font-semibold tabular-nums', BADGE[count.tone], className)} title={`${count.n} ${count.label}`}>
      {count.n > 99 ? '99+' : count.n}
      <span className="sr-only"> {count.label}</span>
    </span>
  )
}

/** A planned page (WEB-72): a small hollow dot, named for screen readers. */
function SoonDot({ className }: { className?: string }) {
  return <span role="img" aria-label="planned" className={cn('size-1.5 shrink-0 rounded-full border border-current opacity-60', className)} />
}

const GROUP_LABEL = 'px-2.5 text-[11px] font-semibold uppercase tracking-wider'
const SOON_PILL = 'shrink-0 rounded-full px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide'

export function AppSidebar() {
  const { me } = useAuth()
  const allowed = useAllowedScopes()
  const { scope } = useScope()
  const location = useLocation()
  const [sidebarTheme, setSidebarTheme] = useSidebarTheme(me?.user_id || me?.org_id)
  const S = SIDEBAR_THEMES[sidebarTheme]

  const [isDark, setIsDark] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('theme')
      if (saved) return saved === 'dark'
      return document.documentElement.classList.contains('dark')
    }
    return false
  })

  useEffect(() => {
    if (isDark) {
      document.documentElement.classList.add('dark')
      localStorage.setItem('theme', 'dark')
    } else {
      document.documentElement.classList.remove('dark')
      localStorage.setItem('theme', 'light')
    }
  }, [isDark])

  const toggleTheme = (event: React.MouseEvent<HTMLButtonElement>) => {
    const isSupported = typeof document !== 'undefined' && 'startViewTransition' in document

    if (!isSupported) {
      setIsDark((prev) => !prev)
      return
    }

    const x = event.clientX
    const y = event.clientY
    const endRadius =
      Math.hypot(
        Math.max(x, window.innerWidth - x),
        Math.max(y, window.innerHeight - y)
      ) + 20

    const transition = (document as Document & { startViewTransition?: (callback: () => void) => { ready: Promise<void> } }).startViewTransition!(() => {
      flushSync(() => {
        setIsDark((prev) => {
          const next = !prev
          if (next) {
            document.documentElement.classList.add('dark')
            localStorage.setItem('theme', 'dark')
          } else {
            document.documentElement.classList.remove('dark')
            localStorage.setItem('theme', 'light')
          }
          return next
        })
      })
    })

    transition.ready.then(() => {
      document.documentElement.animate(
        {
          clipPath: [
            `circle(0px at ${x}px ${y}px)`,
            `circle(${endRadius}px at ${x}px ${y}px)`,
          ],
        },
        {
          duration: 450,
          easing: 'cubic-bezier(0.25, 1, 0.5, 1)',
          pseudoElement: '::view-transition-new(root)',
        }
      )
    })
  }

  const getUrlWithScope = (baseUrl: string) => urlWithScope(baseUrl, scope)

  const showBackButton = location.pathname.startsWith('/projects/') || location.pathname.startsWith('/team/')

  const isModuleEnabled = useModuleEnabled()
  const visibleManagementItems = ROOT_MANAGEMENT_ITEMS.filter(
    (item) =>
      isModuleEnabled(item.module) &&
      (!item.requiredScope || allowed.includes(item.requiredScope)) &&
      (!item.requiredRole || me?.role === item.requiredRole) &&
      (!item.allowedRoles || item.allowedRoles.includes((me?.role || '').toUpperCase()))
  )

  // Production's /auth/me returns org_name/name; the older identity router
  // shape used organization_name/full_name (see lib/api.ts's Me).
  const companyName = me?.org_name || me?.organization_name || 'Mesiri'
  const userName = me?.name || me?.full_name || ''

  const counts = useNavCounts()
  const taskCounts = useTaskCounts()
  // TSK-06: My tasks counts what is mine still open (orange: waiting on me); Overdue counts what is late (red).
  const pageCounts: Record<string, SubCount | undefined> = {
    '/tasks': taskCounts ? { n: taskCounts.mine_open, tone: 'drafts', label: taskCounts.mine_overdue ? `open for you, ${taskCounts.mine_overdue} late` : 'open for you' } : undefined,
    '/tasks?view=overdue': taskCounts ? { n: taskCounts.overdue, tone: 'issues', label: 'late' } : undefined,
  }
  // "Finish setup" (SS-19): the getting-started card stays one click away,
  // hidden or not, until everything is done.
  const setup = useSetupProgress()
  const guideSteps = useGuideSteps()
  const trial = useTrial()
  const setupDone = setup.data ? setupCounts(setup.data, guideSteps) : null
  const finishSetup: NavItem | null =
    setup.isCompanyAdmin && !trial.readOnly && setupDone && setupDone.done < setupDone.total
      ? { title: 'Finish setup', url: SETUP_URL, icon: ListChecks, note: `${setupDone.done}/${setupDone.total}` }
      : null
  // WEB-72 / UX-04: modules from lib/module-map.ts, each with only the pages this role may see and only their
  // home entry (a `shortcut` lives in another module). Without the preview, only working pages.
  const [showPlanned, setShowPlanned] = usePlannedPreview()
  const role = (me?.role || '').toUpperCase()
  const pageVisible = (p: ModuleGroup['pages'][number]) =>
    !p.shortcut && (showPlanned || p.status === 'built') && (!p.roles || p.roles.includes(role)) && (!p.module || isModuleEnabled(p.module))
  const toCategory = (group: ModuleGroup): NavCategory => ({
    key: group.key,
    title: group.title,
    icon: group.icon,
    items: group.pages.filter(pageVisible).map((p) => ({ title: p.navTitle ?? p.title, url: p.url, soon: p.status === 'planned', phase: p.phase, count: pageCounts[p.url] })),
  })
  // A section's entries: a module with one page is a plain link, with several a drawer.
  type Entry = { kind: 'link'; item: NavItem } | { kind: 'category'; category: NavCategory }
  const siteGroup = MODULE_GROUPS.find((g) => g.key === 'site')!
  const sectionEntries = (section: NavSection): Entry[] => {
    const entries: Entry[] = []
    if (section === 'site') {
      // The daily group's other pages (Site log, Analytics; planned ones with the preview) open the SITE section.
      for (const p of siteGroup.pages.filter((p) => pageVisible(p) && !PRIMARY_ITEMS.some((i) => i.url === p.url))) {
        entries.push({ kind: 'link', item: { title: p.navTitle ?? p.title, url: p.url, icon: PAGE_ICONS[p.url] ?? RECORD_ITEMS.find((r) => r.url === p.url)?.icon ?? Activity, soon: p.status === 'planned' } })
      }
    }
    for (const group of MODULE_GROUPS.filter((g) => g.section === section && isModuleEnabled(g.module))) {
      const category = toCategory(group)
      if (category.items.length === 0) continue
      if (group.flat) {
        // Its own section (Tasks): each page is a row, with its icon and its count.
        for (const p of category.items) {
          entries.push({ kind: 'link', item: { title: p.title, url: p.url, icon: PAGE_ICONS[p.url] ?? group.icon, soon: p.soon, count: p.count, exact: true } })
        }
        continue
      }
      if (category.items.length === 1) {
        const only = category.items[0]
        entries.push({ kind: 'link', item: { title: group.key === 'labour' ? only.title : group.title, url: only.url, icon: group.icon, soon: only.soon } })
      } else {
        entries.push({ kind: 'category', category })
      }
    }
    return entries
  }
  const allSections = sectionOrder(role)
    .map((key) => ({ key, title: SECTION_TITLES[key], entries: sectionEntries(key) }))
    .filter((section) => section.entries.length > 0)
  // SS-31 (guided-onboarding-plan.md 6.2): step-by-step mode starts with the everyday pages and the role's own
  // first section (UX-04: each role's day comes first), and one row
  // shows the rest. Help only: search and every link still reach every page this role may see.
  const guide = useStartMode()
  const [showEverything, setShowEverything] = useShowEverything()
  const canShorten = guide.ready && guide.rules.shortSidebar && !showPlanned
  const sections = canShorten && !showEverything ? allSections.slice(0, 1) : allSections
  const hiddenEntries = allSections.filter((s) => !sections.includes(s)).reduce((n, s) => n + s.entries.length, 0)
  const bringData: NavItem | null =
    guide.ready && guide.rules.bringDataInSidebar && setup.isCompanyAdmin && !trial.readOnly
      ? { title: 'Bring your data', url: '/bring-data', icon: Upload }
      : null
  // SS-41: Learn Mesiri with the everyday pages, for everyone who gets guidance; "I'll find my way" reaches it from Help.
  const learn: NavItem | null = guide.ready && guide.rules.tours !== 'none' ? { title: 'Learn Mesiri', url: '/learn', icon: GraduationCap } : null
  const newActions = trial.readOnly ? [] : NEW_ACTIONS.filter((a) => a.roles.includes(role) && (!a.module || isModuleEnabled(a.module)))
  const renderCategory = (category: NavCategory) => (
    <CollapsibleNavCategory
      key={category.key}
      category={category}
      getUrlWithScope={getUrlWithScope}
      pathname={location.pathname}
      search={location.search}
      theme={sidebarTheme}
    />
  )

  const renderLink = (item: NavItem) => {
    const ItemIcon = item.icon
    const active = item.exact ? isSubItemActive(location.pathname, location.search, item.url) : checkIsItemActive(location.pathname, item.url)
    const tone = item.count?.tone ?? item.badge
    const count = item.count ? item.count.n : item.badge === 'drafts' ? counts.drafts : item.badge === 'issues' ? counts.openIssues : 0
    // A plain string className: SidebarMenuButton (asChild -> Radix Slot) merges className as text, which silently
    // drops a function, so the active state never rendered. A Link, not a NavLink: NavLink sets aria-current from
    // the path alone, so every ?view= of a page (the Tasks rows, Automations under /whatsapp) was "current".
    return (
      <SidebarMenuItem key={item.title}>
        <SidebarMenuButton asChild tooltip={item.title} isActive={active}>
          <Link
            to={getUrlWithScope(item.url)}
            aria-current={active ? 'page' : undefined}
            className={cn(NAV_LINK_BASE, S.ring, active ? S.rowActive : S.rowIdle, 'data-[active=true]:font-semibold')}
          >
            <span className="relative shrink-0">
              <ItemIcon className={cn('size-4', active ? S.iconActive : S.icon)} />
              {count > 0 && (
                <span
                  aria-hidden
                  className={cn('absolute -top-1 -right-1 hidden size-2 rounded-full ring-2 ring-sidebar group-data-[collapsible=icon]:block', BADGE[tone!])}
                />
              )}
            </span>
            <span className="truncate">{item.title}</span>
            {item.soon && <SoonDot className="ml-auto group-data-[collapsible=icon]:hidden" />}
            {item.note && (
              <span className="ml-auto text-[11px] tabular-nums opacity-70 group-data-[collapsible=icon]:hidden">{item.note}</span>
            )}
            {count > 0 && (
              <span
                className={cn(
                  'ml-auto min-w-5 rounded-full px-1.5 py-px text-center text-[11px] font-semibold tabular-nums group-data-[collapsible=icon]:hidden',
                  BADGE[tone!],
                )}
                title={item.count ? `${count} ${item.count.label}` : item.badge === 'drafts' ? `${count} items to confirm today` : `${count} open issues`}
              >
                {count > 99 ? '99+' : count}
              </span>
            )}
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    )
  }

  return (
    <Sidebar collapsible="icon" className={cn('border-r', S.edge)}>
      {/* The themed surface wraps everything so it also covers the mobile sheet,
          which ui/sidebar.tsx renders without our className. */}
      <div className={cn('flex h-full w-full flex-col', S.aside)}>
        <SidebarHeader className={cn('gap-0 p-0', S.headerBg)}>
          {/* A 64px band with a wedge sloping into the sidebar body and a
              yellow stripe on its edge. The wedge is filled with --sidebar so
              it always matches the body; preserveAspectRatio="none" stretches
              it to any width (collapsed too), and the -10 / 290 ends run the
              stripe past both edges so the corners stay clean. */}
          <div className="relative h-16 shrink-0">
            <svg
              className="absolute inset-0 size-full"
              viewBox="0 0 280 64"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <rect width="280" height="64" fill="var(--sidebar-header)" />
              <path d="M -10 64 H 290 V 34 L -10 58 Z" fill="var(--sidebar)" />
              <path
                d="M -10 58 L 290 34"
                stroke={S.bar}
                strokeWidth="2"
                strokeLinecap="round"
                opacity="0.85"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
            <div className="relative flex h-full items-center justify-between gap-2 px-3.5 -mt-3 group-data-[collapsible=icon]:px-2">
              <div className="flex items-center gap-2.5 min-w-0">
                <MesiriMark
                  className={cn('hidden text-lg px-1.5 group-data-[collapsible=icon]:inline', S.headerText)}
                />
                <MesiriWordmark
                  className={cn('text-[19px] group-data-[collapsible=icon]:hidden', S.headerText)}
                />
              </div>
              {showBackButton && (
                <Link
                  to={location.pathname.startsWith('/team/') ? '/team' : '/projects'}
                  className={cn(
                    'transition-colors group-data-[collapsible=icon]:hidden size-8 flex items-center justify-center rounded-lg',
                    S.headerBtn,
                    S.ring
                  )}
                  title="Back"
                  aria-label="Back"
                >
                  <ArrowLeft className="size-4" />
                </Link>
              )}
            </div>
          </div>
          <div className="bg-sidebar px-2 pt-2 pb-1 group-data-[collapsible=icon]:hidden">
            <CompanyRow name={companyName} isAdmin={me?.role === 'ADMIN'} company={me?.company ?? null} S={S} />
          </div>
        </SidebarHeader>

        <SidebarContent className={cn('px-1.5 py-1 gap-1', S.scrollbar)} data-guide="app.nav">
          <SidebarGroup className="p-1">
            <SidebarGroupContent>
              <SidebarMenu className="gap-0.5">
                <SidebarMenuItem className="mb-1 flex items-center gap-1.5 group-data-[collapsible=icon]:flex-col">
                  <SidebarMenuButton
                    onClick={openJump}
                    data-guide="app.search"
                    tooltip="Search (Ctrl K)"
                    className={cn(NAV_LINK_BASE, 'min-w-0 flex-1 border', S.divider, S.rowIdle, S.ring)}
                  >
                    <Search className={cn('size-4 shrink-0', S.icon)} />
                    <span className="truncate">Search</span>
                    {/* Beside "+ New" there is no room for the key hint; the tooltip and the app tour name it. */}
                    {newActions.length === 0 && (
                      <kbd className="ml-auto rounded border border-current/20 px-1 text-[10px] opacity-60 group-data-[collapsible=icon]:hidden">Ctrl K</kbd>
                    )}
                  </SidebarMenuButton>
                  {newActions.length > 0 && <NewButton actions={newActions} bar={S.bar} ring={S.ring} />}
                </SidebarMenuItem>
                {PRIMARY_ITEMS.map(renderLink)}
                {bringData && renderLink(bringData)}
                {learn && renderLink(learn)}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          {sections.map((section) => (
            <SidebarGroup key={section.key} className="p-1">
              <SidebarGroupLabel className={cn(GROUP_LABEL, 'flex items-center justify-between', S.label)}>
                {section.title}
                {showPlanned && section.key === sections[0].key && (
                  <span className={cn(SOON_PILL, 'normal-case tracking-normal', S.soon)}>Preview</span>
                )}
              </SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu className="gap-0.5">
                  {section.entries.map((entry) => (entry.kind === 'link' ? renderLink(entry.item) : renderCategory(entry.category)))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}

          {canShorten && (hiddenEntries > 0 || showEverything) && (
            <SidebarGroup className="p-1">
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    onClick={() => setShowEverything(!showEverything)}
                    tooltip={showEverything ? 'Show fewer' : `Show all (${hiddenEntries} more)`}
                    className={cn(NAV_LINK_BASE, S.rowIdle, S.ring)}
                    aria-expanded={showEverything}
                  >
                    <ChevronsUpDown className={cn('size-4 shrink-0', S.icon)} />
                    <span className="truncate">{showEverything ? 'Show fewer' : 'Show all'}</span>
                    {!showEverything && (
                      <span className="ml-auto text-[11px] tabular-nums opacity-70 group-data-[collapsible=icon]:hidden">+{hiddenEntries}</span>
                    )}
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroup>
          )}

          {visibleManagementItems.length > 0 && (
            <SidebarGroup className="p-1">
              <SidebarGroupLabel className={cn(GROUP_LABEL, S.label)}>{SECTION_TITLES.settings}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu className="gap-0.5">
                  {finishSetup && renderLink(finishSetup)}
                  {visibleManagementItems.map(renderLink)}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          )}

        </SidebarContent>

        <SidebarFooter className={cn('border-t p-2', S.divider)}>
          <div className="flex items-center gap-2.5 px-1 group-data-[collapsible=icon]:hidden">
            <div
              className={cn(
                'size-8 rounded-full flex items-center justify-center text-xs font-semibold shrink-0',
                S.avatar
              )}
              aria-hidden="true"
            >
              {initialsOf(userName || companyName)}
            </div>
            <div className="flex flex-col min-w-0 flex-1">
              <span className={cn('text-sm font-semibold truncate', S.name)}>
                {userName || 'Signed in'}
              </span>
              <span className={cn('text-xs truncate', S.role)}>{roleLabel(me?.role)}</span>
            </div>
            {me?.is_platform_admin && (
            <button
              type="button"
              onClick={() => setShowPlanned(!showPlanned)}
              title={showPlanned ? 'Hide planned modules' : 'Show planned modules (preview)'}
              aria-label={showPlanned ? 'Hide planned modules' : 'Show planned modules'}
              aria-pressed={showPlanned}
              className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', S.iconBtn, S.ring, showPlanned && 'text-orange-400 hover:text-orange-300')}
            >
              <MapIcon className="size-4" />
            </button>
            )}
          </div>
          <SidebarMenu>
            <SidebarMenuItem className="flex items-center gap-1 group-data-[collapsible=icon]:flex-col">
              <SidebarMenuButton
                onClick={() => logout().then(() => window.location.assign('/login'))}
                tooltip="Log out"
                className={cn(
                  'flex-1 rounded-lg px-2.5 py-2 text-sm transition-colors',
                  S.rowIdle,
                  S.danger,
                  S.ring
                )}
              >
                <LogOut className="size-4 shrink-0" />
                <span>Log out</span>
              </SidebarMenuButton>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    title="Sidebar colour"
                    aria-label={`Sidebar colour: ${SIDEBAR_THEME_NAMES[sidebarTheme]}`}
                    className={cn('size-8 p-0 flex items-center justify-center rounded-lg shrink-0 outline-hidden focus-visible:ring-2', S.iconBtn, S.ring)}
                  >
                    <Palette className="size-4 shrink-0" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent side="top" align="end" className="min-w-48">
                  <DropdownMenuLabel className="text-xs text-muted-foreground">Sidebar colour</DropdownMenuLabel>
                  <DropdownMenuRadioGroup value={sidebarTheme} onValueChange={(v) => setSidebarTheme(v as SidebarTheme)}>
                    {(Object.keys(SIDEBAR_THEME_NAMES) as SidebarTheme[]).map((key) => (
                      <DropdownMenuRadioItem key={key} value={key} className="gap-2.5">
                        <span
                          aria-hidden
                          className="size-5 shrink-0 rounded-full border border-black/15"
                          style={{ background: `linear-gradient(135deg, ${SIDEBAR_THEMES[key].swatch} 0 58%, ${SIDEBAR_THEMES[key].bar} 58% 100%)` }}
                        />
                        {SIDEBAR_THEME_NAMES[key]}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
              <SidebarMenuButton
                onClick={toggleTheme}
                tooltip={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
                aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
                className={cn('size-8 p-0 flex items-center justify-center rounded-lg shrink-0', S.iconBtn, S.ring)}
              >
                {isDark ? <Sun className="size-4 shrink-0" /> : <Moon className="size-4 shrink-0" />}
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </div>
    </Sidebar>
  )
}

// UX-16: the "+ New" button (see NEW_ACTIONS). A menu of what this role records; each opens Tell Mesiri with the
// sentence started.
function NewButton({ actions, bar, ring }: { actions: NewAction[]; bar: string; ring: string }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          data-guide="app.new"
          title="New: record something"
          aria-label="New"
          style={{ backgroundColor: bar }}
          className={cn(
            'inline-flex h-9 shrink-0 items-center gap-1 rounded-lg px-2.5 text-sm font-semibold text-[#2A2829] outline-hidden transition-[filter] hover:brightness-105 focus-visible:ring-2 group-data-[collapsible=icon]:size-8 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0',
            ring,
          )}
        >
          <Plus className="size-4 shrink-0" strokeWidth={2.5} aria-hidden />
          <span className="group-data-[collapsible=icon]:hidden">New</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="bottom" align="end" className="w-64">
        <DropdownMenuLabel className="text-xs text-muted-foreground">Tell Mesiri, like on WhatsApp</DropdownMenuLabel>
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

// WEB-38: the company at the top of the sidebar, as a row rather than a
// labelled box: its logo (or initials on its brand colour), the name, and
// one useful line -- the trial's days left, or what an admin can open here.
// Admins tap it to open the Company page.
function CompanyRow({
  name,
  isAdmin,
  company,
  S,
}: {
  name: string
  isAdmin: boolean
  company: Me['company']
  S: (typeof SIDEBAR_THEMES)[SidebarTheme]
}) {
  // The branding API answers admins only; everyone else gets initials.
  const branding = useQuery({ queryKey: ['company-branding'], queryFn: fetchBranding, enabled: isAdmin, retry: false, staleTime: 10 * 60_000 })
  const logo = branding.data?.logo_url
  const colour = branding.data?.brand_color || undefined
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
  const trialLeft = company?.status === 'trial' ? company.trial_days_left : null
  const line =
    trialLeft !== null && trialLeft !== undefined
      ? trialLeft <= 0
        ? 'Free trial ends today'
        : `Free trial · ${trialLeft} ${trialLeft === 1 ? 'day' : 'days'} left`
      : company?.status === 'expired'
        ? 'Trial ended'
        : isAdmin
          ? 'Company settings'
          : 'Your company'
  const body = (
    <>
      <span
        className={cn(
          'flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-lg text-xs font-bold',
          logo ? 'bg-white p-1' : colour ? 'text-white' : S.avatar,
        )}
        style={!logo && colour ? { backgroundColor: colour } : undefined}
        aria-hidden="true"
      >
        {logo ? <img src={logo} alt="" className="max-h-full max-w-full object-contain" /> : letters || 'M'}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className={cn('truncate text-sm leading-tight font-semibold', S.name)}>{name}</span>
        <span className={cn('truncate text-xs', trialLeft !== null && trialLeft !== undefined && trialLeft <= 3 ? 'text-amber-400' : S.role)}>{line}</span>
      </span>
      {isAdmin && <ChevronRight className={cn('size-4 shrink-0 opacity-0 transition-opacity group-hover/company:opacity-100', S.chevron)} aria-hidden="true" />}
    </>
  )
  return isAdmin ? (
    <Link to="/company" className={cn('group/company flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors', S.hoverBg, S.ring)} title="Open company settings">
      {body}
    </Link>
  ) : (
    <div className="flex items-center gap-2.5 px-2 py-1.5">{body}</div>
  )
}
