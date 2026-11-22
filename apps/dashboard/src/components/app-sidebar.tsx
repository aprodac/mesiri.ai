import { useState, useEffect, useLayoutEffect } from 'react'
import { SETTINGS_PATHS, urlWithScope } from '@/lib/scope-url'
import { flushSync } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LogOut,
  ArrowLeft,
  Check,
  House,
  FileText,
  ChevronRight,
  CalendarDays,
  Sun,
  Moon,
  Clock,
  AlertCircle,
  ListChecks,
  Circle,
  LayoutGrid,
  Lock,
  Map as MapIcon,
  Settings as SettingsIcon,
  GraduationCap,
  ChevronsUpDown,
  Plus,
  Pin,
  PinOff,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
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
} from '@/components/ui/sidebar'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { fetchBranding, logout, type Me } from '@/lib/api'
import { MesiriMark, MesiriWordmark } from '@/components/brand/mesiri-logo'
import { SETUP_URL, setupCounts, setupNavSteps, useGuideSteps, useSetupProgress } from '@/lib/setup'
import { useTrial } from '@/lib/trial'
import { cn } from '@/lib/utils'
import { useModuleEnabled, type ModuleKey } from '@/lib/modules'
import { LOOKS, useLook, type Look } from '@/lib/look'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useNavCounts, useTaskCounts, useWaitingCounts } from '@/lib/nav-counts'
import { MODULE_GROUPS, findPage, pagePath } from '@/lib/module-map'
import { usePlannedPreview } from '@/lib/preview'
import { useStartMode } from '@/lib/start-mode'
import { initialsOf } from '@/lib/initials'
import { EVERYDAY, MAX_PINS, openSidebarCustomise, useSidebarPrefs, usePinnable } from '@/lib/sidebar-prefs'
import { SUGGEST_DAYS, SUGGEST_SCORE, dismissSuggestion, dismissedSuggestions, usePageUsage } from '@/lib/page-usage'
import { openAllPages } from '@/lib/all-pages'

type NavItem = {
  title: string
  url: string
  icon: React.ComponentType<{ className?: string }>
  requiredRole?: string
  // Shown only to these roles (SEC-01: who may read expenses).
  allowedRoles?: readonly string[]
  // Switched-off modules are hidden (WEB-02); see lib/modules.tsx.
  module?: ModuleKey
  // Which live count to show as a badge (WEB-20).
  badge?: 'drafts' | 'issues'
  // A page's own live count (TSK-06).
  count?: SubCount
  // Lit only on its own view (?view=).
  exact?: boolean
  // A planned page (WEB-72), shown only with the preview on.
  soon?: boolean
}

// A live count on a row (TSK-06): `tone` is the badge colour, `label` what the number means.
type SubCount = { n: number; tone: BadgeTone; label: string }
type BadgeTone = 'drafts' | 'issues'

const NON_ADMIN_ROLES = ['PROJECT_MANAGER', 'SITE_ENGINEER', 'FINANCE'] as const

// UX-74 (asked 20 Nov 2026: "what that user needs at that particular time only should be there ... the need to scroll
// the sidebar should not be there. The sidebar should look very simple"; docs/plans/ui-story-plan.md section 4.4):
// the sidebar shows what this person needs now, never scrolls, and everything else is one click away in All pages.
//   1. Set up (a company still setting up, its admin): the setup steps still to do, the next one marked;
//   2. the everyday pages of this role (EVERYDAY_BY_ROLE); while no site has sent an update yet the pages that
//      need one are shown locked, with why (hidden would hide what is coming; disabled with no reason feels broken);
//   3. Your pages: the person's pins (UX-65), at most MAX_PINS;
//   4. All pages (components/all-pages.tsx): every page this role may open, by section and module;
//   then Learn and Settings at the foot, and one menu on the person's name (theme, Customise, Log out).
// Live (WEB-37) is a presenter's page for demos, reached from Learn, not a row here.
const EVERYDAY_ITEMS: Record<string, NavItem> = {
  '/home': { title: 'Home', url: '/home', icon: House },
  '/today': { title: 'Today', url: '/today', icon: CalendarDays, badge: 'drafts' },
  '/reports': { title: 'Daily reports', url: '/reports', icon: FileText },
  '/issues': { title: 'Issues', url: '/issues', icon: AlertCircle, badge: 'issues' },
}
/** Each role's everyday pages, in the order of its day (UX-68: site engineers land on Today; accounts on Home). */
const EVERYDAY_BY_ROLE: Record<string, string[]> = {
  SITE_ENGINEER: ['/today', '/reports', '/issues'],
  FINANCE: ['/home', '/issues'],
}
const EVERYDAY_DEFAULT = ['/home', '/today', '/reports', '/issues']
/** Pages with nothing to show until a site has sent its first update (locked during setup, with this reason). */
const NEEDS_FIRST_UPDATE = new Set(['/today', '/reports', '/issues'])
const LOCKED_WHY = 'Opens when your first site update arrives'

const ROOT_MANAGEMENT_ITEMS: NavItem[] = [
  { title: 'Settings', url: '/settings', icon: SettingsIcon, requiredRole: 'ADMIN' },
  // WEB-31: the inbox APIs answer admins only. Others who have Automations get that view of the WhatsApp page.
  { title: 'Automations', url: '/whatsapp?view=automations', icon: Clock, module: 'automations', allowedRoles: NON_ADMIN_ROLES },
]

function roleLabel(role: string | undefined): string {
  if (!role) return ''
  return role
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

// Visual tokens for the sidebar. `aside` also re-points the --sidebar-* variables, so the shadcn sidebar parts' own
// hover, active and focus styles match without changing ui/sidebar.tsx.
/** One look's sidebar: colours and shape (both looks have every key; `panel`, `header` and `badge` are typed). */
type SidebarLook = Omit<Record<keyof (typeof SIDEBAR_THEMES)['blueprint'], string>, 'panel' | 'header' | 'badge'> & {
  panel: 'sidebar' | 'floating'
  header: 'tile' | 'wedge'
  badge: Record<BadgeTone, string>
}

const SIDEBAR_THEMES = {
  // UX-16 (17 Nov 2026): one sidebar, two versions picked by the app's own light/dark switch (the moon button).
  // WEB-102 (22 Nov 2026): the blueprint system. The sidebar is drawing ink (deep navy), the page bright paper, and the
  // highlighter yellow bar marks the page you are on.
  // UX-35 (18 Nov, asked: "the sidebar should be a different colour, it's the same as the background"): the sand
  // sidebar was the page's own colour. Now warm charcoal in light mode (the page stays sand, the brand's yellow bar
  // marks the page you are on), and a shade darker than the page in dark mode.
  blueprint: {
    // Shape (WEB-103: each look owns its layout as well as its colours).
    panel: 'floating' as const,
    panelClass: '[&>[data-sidebar=sidebar]]:overflow-hidden [&>[data-sidebar=sidebar]]:rounded-[22px] [&>[data-sidebar=sidebar]]:border-0 [&>[data-sidebar=sidebar]]:shadow-[0_12px_32px_-18px_rgba(21,35,63,0.55)]',
    header: 'tile' as const,
    navBase: 'group/row flex items-center gap-3 w-full h-9 px-3 rounded-full text-[14px] transition-colors group-data-[collapsible=icon]:h-8',
    groupLabel: 'px-3 font-mono text-[10px] font-medium uppercase tracking-[0.14em]',
    // Badges in the cue system's words (WEB-102): highlighter = waiting on someone, brick = something is wrong.
    badge: { drafts: 'bg-[#ffd23f] text-[#15233f]', issues: 'bg-[#c4472f] text-white' },
    companyWrap: 'px-3 pb-3',
    companyBox: 'rounded-2xl border px-2.5 py-2',
    content: 'gap-1 px-2 py-1 group-data-[collapsible=icon]:px-1.5',
    setupGroup: 'mx-1 mb-2 w-auto rounded-2xl border px-1.5 pt-2.5 pb-2 group-data-[collapsible=icon]:mx-0 group-data-[collapsible=icon]:border-0 group-data-[collapsible=icon]:bg-transparent',
    setupBar: 'mx-3 mt-0.5 mb-2',
    stepRow: 'h-auto min-h-9 rounded-[14px] py-2',
    stepFirst: 'bg-[#ffd23f]/12 font-medium text-white hover:bg-[#ffd23f]/20 dark:text-foreground',
    stepText: 'line-clamp-2 leading-snug whitespace-normal! text-clip!',
    footer: 'p-3 group-data-[collapsible=icon]:p-2',
    footerBtn: 'rounded-2xl border px-2 py-2 group-data-[collapsible=icon]:border-0 group-data-[collapsible=icon]:bg-transparent group-data-[collapsible=icon]:p-0',
    aside:
      'bg-[#15233F] text-[#C9D3E6] dark:bg-[#091121] dark:text-foreground [--sidebar:#15233F] dark:[--sidebar:#091121] [--sidebar-foreground:#C9D3E6] dark:[--sidebar-foreground:var(--foreground)] [--sidebar-accent:#1F3052] dark:[--sidebar-accent:var(--muted)] [--sidebar-accent-foreground:#FFFFFF] dark:[--sidebar-accent-foreground:var(--foreground)] [--sidebar-border:#26385C] dark:[--sidebar-border:var(--border)] [--sidebar-ring:#ffd23f] dark:[--sidebar-ring:var(--ring)]',
    edge: 'border-[#26385C] dark:border-border',
    ring: 'focus-visible:ring-[#ffd23f] dark:focus-visible:ring-ring',
    rowIdle: 'text-[#C9D3E6] hover:bg-white/[0.07] hover:text-white dark:text-foreground/75 dark:hover:bg-white/[0.06] dark:hover:text-foreground',
    // The page you are on: a sheet of paper on the drawing ink (the phone's bottom bar marks its tab the same way).
    rowActive: 'bg-[#f8f7f3]! text-[#15233f]! font-semibold shadow-[0_1px_0_rgba(0,0,0,0.25)] hover:bg-white! dark:bg-[#e8ecf4]! dark:text-[#0d1629]!',
    hoverBg: 'hover:bg-[#1F3052] dark:hover:bg-muted',
    label: 'text-[#7f8fb0] dark:text-muted-foreground',
    icon: 'text-[#9FB3DA] group-hover/row:text-white dark:text-muted-foreground dark:group-hover/row:text-foreground',
    iconActive: 'text-[#1e3a6e]',
    iconBtn: 'text-[#9FB3DA] hover:text-white hover:bg-[#1F3052] dark:text-muted-foreground dark:hover:text-foreground dark:hover:bg-background',
    divider: 'border-[#26385C] dark:border-border',
    guide: 'border-[#2A3E66] dark:border-border',
    chevron: 'text-[#8D9BB8] dark:text-muted-foreground',
    groupIdle: 'text-[#C9D3E6] hover:text-white dark:text-foreground/70 dark:hover:text-foreground',
    groupActive: 'text-white font-semibold dark:text-foreground',
    card: 'border-white/10 bg-white/[0.045] dark:border-white/[0.07] dark:bg-white/[0.03]',
    soon: 'bg-[#1F3052] text-[#8D9BB8] dark:bg-muted dark:text-muted-foreground',
    headerBg: '[--sidebar-header:#15233F] dark:[--sidebar-header:#091121]',
    headerText: 'text-white dark:text-foreground',
    headerBtn: 'text-[#9FB3DA] hover:text-white hover:bg-white/[0.06] dark:text-muted-foreground dark:hover:text-foreground dark:hover:bg-muted',
    avatar: 'bg-[#dfe6f3] text-[#1e3a6e] dark:bg-[#1c2d50] dark:text-[#b9c8e6]',
    danger: 'hover:text-red-400',
    name: 'text-white dark:text-foreground',
    role: 'text-[#8D9BB8] dark:text-muted-foreground',
    scrollbar: 'sidebar-scrollbar',
    bar: '#ffd23f',
  },
  // WEB-103: Classic, the sidebar before the blueprint system (charcoal, the wedge header), kept as a choice.
  classic: {
    panel: 'sidebar' as const,
    panelClass: 'border-r border-[#34302A] dark:border-border',
    header: 'wedge' as const,
    navBase: 'group/row flex items-center gap-2.5 w-full px-2.5 py-1.5 rounded-lg text-sm transition-colors',
    groupLabel: 'px-2.5 text-[11px] font-semibold uppercase tracking-wider',
    badge: { drafts: 'bg-orange-500 text-white', issues: 'bg-rose-500 text-white' },
    companyWrap: 'bg-sidebar px-2 pt-2 pb-1',
    companyBox: 'rounded-lg px-2 py-1.5',
    content: 'gap-0 px-1.5 py-1',
    setupGroup: 'px-1 py-0.5',
    setupBar: 'mx-2.5 mb-1.5',
    stepRow: '',
    stepFirst: 'bg-[#FACC15]/10 text-white dark:text-foreground',
    stepText: 'truncate',
    footer: 'border-t border-[#34302A] p-1.5 dark:border-border',
    footerBtn: 'rounded-lg px-1.5 py-1.5',
    card: '',
    aside:
      'bg-[#1F1D1A] text-[#D9D3C7] dark:bg-[#0E0F11] dark:text-foreground [--sidebar:#1F1D1A] dark:[--sidebar:#0E0F11] [--sidebar-foreground:#D9D3C7] dark:[--sidebar-foreground:var(--foreground)] [--sidebar-accent:#2C2924] dark:[--sidebar-accent:var(--muted)] [--sidebar-accent-foreground:#FFFFFF] dark:[--sidebar-accent-foreground:var(--foreground)] [--sidebar-border:#34302A] dark:[--sidebar-border:var(--border)] [--sidebar-ring:#FACC15] dark:[--sidebar-ring:var(--ring)]',
    edge: 'border-[#34302A] dark:border-border',
    ring: 'focus-visible:ring-[#FACC15] dark:focus-visible:ring-ring',
    rowIdle: 'text-[#CFC8BB] hover:bg-[#2C2924] hover:text-white dark:text-foreground/70 dark:hover:bg-muted dark:hover:text-foreground',
    rowActive: 'bg-[#3A352D] text-white font-semibold dark:bg-muted dark:text-foreground',
    hoverBg: 'hover:bg-[#2C2924] dark:hover:bg-muted',
    label: 'text-[#968E80] dark:text-muted-foreground',
    icon: 'text-[#A29A8C] group-hover/row:text-white dark:text-muted-foreground dark:group-hover/row:text-foreground',
    iconActive: 'text-[#FACC15] dark:text-foreground',
    iconBtn: 'text-[#A29A8C] hover:text-white hover:bg-[#2C2924] dark:text-muted-foreground dark:hover:text-foreground dark:hover:bg-background',
    divider: 'border-[#34302A] dark:border-border',
    guide: 'border-[#3A352D] dark:border-border',
    chevron: 'text-[#968E80] dark:text-muted-foreground',
    groupIdle: 'text-[#CFC8BB] hover:text-white dark:text-foreground/70 dark:hover:text-foreground',
    groupActive: 'text-white font-semibold dark:text-foreground',
    soon: 'bg-[#2C2924] text-[#968E80] dark:bg-muted dark:text-muted-foreground',
    headerBg: '[--sidebar-header:#1F1D1A] dark:[--sidebar-header:#0E0F11]',
    headerText: 'text-white dark:text-foreground',
    headerBtn: 'text-[#A29A8C] hover:text-white hover:bg-white/[0.06] dark:text-muted-foreground dark:hover:text-foreground dark:hover:bg-muted',
    avatar: 'bg-[#2A2722] text-white border border-[#3A352D] dark:bg-background dark:text-foreground dark:border-border',
    danger: 'hover:text-red-400',
    name: 'text-white dark:text-foreground',
    role: 'text-[#968E80] dark:text-muted-foreground',
    scrollbar: 'sidebar-scrollbar',
    bar: '#FACC15',
  },
} as const

// One icon colour (UX-03): icons are muted and the active row's icon takes the look's accent, so colour in the
// sidebar means only a badge (each look's `badge`).

// Settings' pages keep their own addresses (UX-04); the Settings row lights up on any of them (lib/scope-url.ts).
// A page whose address sits under another module (a project's BOQ under /projects) lights its own row, never
// Settings: the same table the breadcrumb reads (module-map `SAME_AS`).

function checkIsItemActive(rawPathname: string, itemUrl: string): boolean {
  const pathname = pagePath(rawPathname)
  if (pathname === itemUrl) return true
  if (itemUrl === '/settings') return SETTINGS_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))
  if (itemUrl === '/home' && pathname === '/') return true
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

/** A planned page (WEB-72): a small hollow dot, named for screen readers. */
function SoonDot({ className }: { className?: string }) {
  return <span role="img" aria-label="planned" className={cn('size-1.5 shrink-0 rounded-full border border-current opacity-60', className)} />
}

/** UX-65: the pin on a row, shown when the mouse is over the row or the keyboard reaches it. Phones use "Customise". */
function PinButton({ pinned, title, onClick, group }: { pinned: boolean; title: string; onClick: () => void; group: 'pin' | 'menu' }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        onClick()
      }}
      aria-label={pinned ? `Unpin ${title} from your pages` : `Pin ${title} to your pages`}
      title={pinned ? 'Unpin from your pages' : 'Pin to your pages'}
      className={cn(
        'absolute top-1/2 right-1 hidden size-6 -translate-y-1/2 items-center justify-center rounded-md bg-[#1F3052] text-[#9FB3DA] opacity-0 transition-opacity hover:text-[#ffd23f] focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-[#ffd23f] pointer-fine:flex group-data-[collapsible=icon]:hidden! dark:bg-muted dark:text-muted-foreground dark:hover:text-primary-ink',
        group === 'pin' ? 'group-hover/pin:opacity-100' : 'group-hover/menu-item:opacity-100',
      )}
    >
      {pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
    </button>
  )
}


export function AppSidebar() {
  const { me } = useAuth()
  const { scope } = useScope()
  const location = useLocation()
  const [look, setLook] = useLook()
  const S: SidebarLook = SIDEBAR_THEMES[look]

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

  const toggleTheme = (event: React.MouseEvent<HTMLElement>) => {
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
  const role = (me?.role || '').toUpperCase()
  const isModuleEnabled = useModuleEnabled()
  const [showPlanned, setShowPlanned] = usePlannedPreview()
  const trial = useTrial()
  const companyName = me?.org_name || me?.organization_name || 'Mesiri'
  const userName = me?.name || me?.full_name || ''

  const counts = useNavCounts()
  const taskCounts = useTaskCounts()
  const waiting = useWaitingCounts()
  const pageCounts: Record<string, SubCount | undefined> = {
    '/tasks': taskCounts ? { n: taskCounts.mine_open, tone: 'drafts', label: taskCounts.mine_overdue ? `open for you, ${taskCounts.mine_overdue} late` : 'open for you' } : undefined,
    '/tasks?view=overdue': taskCounts ? { n: taskCounts.overdue, tone: 'issues', label: 'late' } : undefined,
    '/site/approvals': waiting ? { n: waiting.total, tone: waiting.urgent ? 'issues' : 'drafts', label: waiting.urgent ? `waiting, ${waiting.urgent} urgent` : 'waiting' } : undefined,
  }

  // 1. Setting up: the company admin's steps still to do (lib/setup.ts, the same list the card on Home counts).
  const setup = useSetupProgress()
  const guideSteps = useGuideSteps()
  const steps = setup.data && setup.isCompanyAdmin && !trial.readOnly ? setupNavSteps(setup.data, guideSteps) : []
  const setupDone = setup.data ? setupCounts(setup.data, guideSteps) : null
  const settingUp = steps.length > 0 && !!setupDone && setupDone.done < setupDone.total
  const toDo = steps.filter((s) => !s.done)
  // The next step only; the rest are on Home's checklist ("N more steps"), so the sidebar stays one screen.
  const shownSteps = toDo.slice(0, 1)
  // Until a site sends its first update, the pages that show updates have nothing in them yet.
  const noUpdateYet = settingUp && setup.data?.first_update_at === null

  // 2. The everyday pages: the role's, each only if this role may open it (lib/module-map.ts roles).
  const siteGroup = MODULE_GROUPS.find((g) => g.key === 'site')
  const mayOpen = (url: string) => {
    const page = siteGroup?.pages.find((p) => p.url === url)
    return !page || ((!page.roles || page.roles.includes(role)) && (!page.module || isModuleEnabled(page.module)))
  }
  const everyday = (EVERYDAY_BY_ROLE[role] ?? EVERYDAY_DEFAULT).filter(mayOpen).map((url) => EVERYDAY_ITEMS[url])

  // 3. Your pages (UX-65): the person's pins, then (UX-70) one page they keep opening, offered once.
  const sb = useSidebarPrefs()
  const pinnable = usePinnable()
  const [justPinned, setJustPinned] = useState<string | null>(null)
  useEffect(() => {
    if (!justPinned) return
    const t = window.setTimeout(() => setJustPinned(null), 1600)
    return () => window.clearTimeout(t)
  }, [justPinned])
  const canPin = (url: string) => pinnable.byUrl.has(url) && !trial.readOnly && (sb.prefs.pins.includes(url) || !sb.full)
  const togglePin = (url: string) => {
    if (sb.togglePin(url)) setJustPinned(url)
  }
  const usage = usePageUsage()
  const person = me?.user_id ?? ''
  const suggestion =
    sb.ready && !trial.readOnly && !sb.full && !settingUp
      ? usage
          .filter((u) => u.days >= SUGGEST_DAYS && u.score >= SUGGEST_SCORE)
          .map((u) => pinnable.byUrl.get(u.url))
          .find((p) => !!p && !sb.prefs.pins.includes(p.url) && !EVERYDAY.includes(p.url) && !dismissedSuggestions(person).includes(p.url))
      : undefined
  // The sidebar never scrolls: on a short screen, the pins that don't fit wait in All pages (its row says how many).
  const [fitPins, setFitPins] = useState(MAX_PINS)
  const allPins = sb.prefs.pins.map((url) => pinnable.byUrl.get(url)).filter((p): p is NonNullable<typeof p> => !!p)
  const hiddenPins = Math.max(0, Math.min(allPins.length, MAX_PINS) - fitPins)
  useLayoutEffect(() => {
    const nav = document.querySelector<HTMLElement>('[data-sidebar="sidebar"] [data-guide="app.nav"]')
    if (!nav) return
    const over = nav.scrollHeight - nav.clientHeight
    if (over > 1 && fitPins > 0) setFitPins((n) => Math.max(0, n - Math.ceil(over / 32)))
  }, [fitPins, allPins.length, settingUp, noUpdateYet, sb.ready, suggestion?.url])
  useEffect(() => {
    // A taller window (or a closed setup group) has room again: measure from all of them.
    const grow = () => setFitPins(MAX_PINS)
    window.addEventListener('resize', grow)
    return () => window.removeEventListener('resize', grow)
  }, [])
  const yourPages: NavItem[] = allPins
    .slice(0, Math.min(MAX_PINS, fitPins))
    .map((p) => ({ title: p.title, url: p.url, icon: p.icon, soon: p.page.status === 'planned', count: pageCounts[p.url], exact: p.url.includes('?') }))

  // The foot: Learn (for everyone who gets guidance, SS-41) and Settings.
  const guide = useStartMode()
  const learn: NavItem | null = guide.ready && guide.rules.tours !== 'none' ? { title: 'Learn Mesiri', url: '/learn', icon: GraduationCap } : null
  const management = ROOT_MANAGEMENT_ITEMS.filter(
    (item) =>
      isModuleEnabled(item.module) &&
      (!item.requiredRole || me?.role === item.requiredRole) &&
      (!item.allowedRoles || item.allowedRoles.includes(role)),
  )

  const renderLink = (item: NavItem, pinMode?: 'unpin') => {
    const ItemIcon = item.icon
    const active = item.exact ? isSubItemActive(location.pathname, location.search, item.url) : checkIsItemActive(location.pathname, item.url)
    const tone = item.count?.tone ?? item.badge
    const count = item.count ? item.count.n : item.badge === 'drafts' ? counts.drafts : item.badge === 'issues' ? counts.openIssues : 0
    const pinnable = pinMode && canPin(item.url)
    return (
      <SidebarMenuItem key={item.url} className={cn(justPinned === item.url && 'rounded-lg rounded-full ring-2 ring-[#ffd23f]/70 transition-shadow dark:ring-primary/60')}>
        <SidebarMenuButton asChild tooltip={item.title} isActive={active}>
          <Link
            to={getUrlWithScope(item.url)}
            aria-current={active ? 'page' : undefined}
            className={cn(S.navBase, S.ring, active ? S.rowActive : S.rowIdle, 'data-[active=true]:font-semibold')}
          >
            <span className="relative shrink-0">
              <ItemIcon className={cn('size-4', active ? S.iconActive : S.icon)} />
              {count > 0 && (
                <span aria-hidden className={cn('absolute -top-1 -right-1 hidden size-2 rounded-full ring-2 ring-sidebar group-data-[collapsible=icon]:block', S.badge[tone!])} />
              )}
            </span>
            <span className="truncate">{item.title}</span>
            {item.soon && <SoonDot className="ml-auto group-data-[collapsible=icon]:hidden" />}
            {count > 0 && (
              <span
                className={cn('ml-auto min-w-5 rounded-full px-1.5 py-px text-center text-[11px] font-semibold tabular-nums group-data-[collapsible=icon]:hidden', S.badge[tone!])}
                title={item.count ? `${count} ${item.count.label}` : item.badge === 'drafts' ? `${count} items to confirm today` : `${count} open issues`}
              >
                {count > 99 ? '99+' : count}
              </span>
            )}
          </Link>
        </SidebarMenuButton>
        {pinnable && <PinButton pinned={sb.prefs.pins.includes(item.url)} title={item.title} onClick={() => togglePin(item.url)} group="menu" />}
      </SidebarMenuItem>
    )
  }

  return (
    <Sidebar collapsible="icon" variant={S.panel} className={S.panelClass}>
      {/* The themed surface wraps everything so it also covers the mobile sheet,
          which ui/sidebar.tsx renders without our className. */}
      <div className={cn('flex h-full w-full flex-col', S.aside)}>
        <SidebarHeader className={cn('gap-0 p-0', S.headerBg)}>
          {S.header === 'tile' ? (
            <>
          {/* WEB-102: the mark on a highlighter tile (the phone's M), the wordmark beside it. The wedge and its stripe
                went with the hazard tape. */}
            <div className="relative h-16 shrink-0">
              <div className="relative flex h-full items-center justify-between gap-2 px-3 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
                <div className="flex min-w-0 items-center gap-2.5">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-[12px] bg-[#ffd23f] shadow-[inset_0_-2px_0_rgba(21,35,63,0.18)]" aria-hidden>
                    <MesiriMark className="text-[20px] text-[#15233f]" />
                  </span>
                  <MesiriWordmark className={cn('text-[22px] group-data-[collapsible=icon]:hidden', S.headerText)} />
                </div>
              {showBackButton && <BackLink to={location.pathname.startsWith('/team/') ? '/team' : '/projects'} S={S} />}
            </div>
          </div>
            </>
          ) : (
            <>
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
              {showBackButton && <BackLink to={location.pathname.startsWith('/team/') ? '/team' : '/projects'} S={S} />}
            </div>
          </div>
            </>
          )}
          <div className={cn('group-data-[collapsible=icon]:hidden', S.companyWrap)}>
            <CompanyRow name={companyName} isAdmin={me?.role === 'ADMIN'} company={me?.company ?? null} S={S} />
          </div>
        </SidebarHeader>

        <SidebarContent className={cn(S.content, S.scrollbar)} data-guide="app.nav">
          {settingUp && (
            <SidebarGroup className={cn(S.setupGroup, S.card)} data-guide="app.setup">
              <SidebarGroupLabel className={cn(S.groupLabel, 'flex items-center justify-between', S.label)}>
                <span>Set up</span>
                <span className="tabular-nums normal-case tracking-normal">
                  {setupDone!.done} of {setupDone!.total}
                </span>
              </SidebarGroupLabel>
              <div className={cn('h-1 overflow-hidden rounded-full bg-white/10 group-data-[collapsible=icon]:hidden dark:bg-muted', S.setupBar)} aria-hidden>
                <div className="h-full rounded-full" style={{ width: `${(setupDone!.done / setupDone!.total) * 100}%`, backgroundColor: S.bar }} />
              </div>
              <SidebarGroupContent>
                <SidebarMenu className="gap-0.5">
                  {shownSteps.map((step, i) => {
                    const active = isSubItemActive(location.pathname, location.search, step.url)
                    return (
                      <SidebarMenuItem key={step.key}>
                        <SidebarMenuButton asChild tooltip={step.title} isActive={active}>
                          <Link to={getUrlWithScope(step.url)} className={cn(S.navBase, S.stepRow, S.ring, i === 0 ? S.stepFirst : S.rowIdle)}>
                            {i === 0 ? (
                              <span className="flex size-4 shrink-0 items-center justify-center rounded-full" style={{ backgroundColor: S.bar }} aria-hidden>
                                <ChevronRight className="size-3 text-[#15233f]" strokeWidth={3} />
                              </span>
                            ) : (
                              <Circle className={cn('size-4 shrink-0', S.icon)} aria-hidden />
                            )}
                            <span className={S.stepText}>{step.title}</span>
                          </Link>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    )
                  })}
                  {toDo.length > shownSteps.length && (
                    <li className="group-data-[collapsible=icon]:hidden">
                      <Link to={getUrlWithScope(SETUP_URL)} className={cn('flex items-center gap-2 rounded-md px-2.5 py-1 text-xs hover:underline', S.label, S.ring)}>
                        <ListChecks className="size-3.5" aria-hidden /> {toDo.length - shownSteps.length} more {toDo.length - shownSteps.length === 1 ? 'step' : 'steps'}
                      </Link>
                    </li>
                  )}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          )}

          <SidebarGroup className="px-1 py-0.5">
            <SidebarGroupContent>
              <SidebarMenu className="gap-0.5">
                {everyday.map((item) =>
                  noUpdateYet && NEEDS_FIRST_UPDATE.has(item.url) ? <LockedRow key={item.url} item={item} why={LOCKED_WHY} S={S} /> : renderLink(item),
                )}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          {sb.ready && !noUpdateYet && (yourPages.length > 0 || suggestion || (allPins.length === 0 && !trial.readOnly)) && (
            <SidebarGroup className="px-1 py-0.5" data-guide="app.pins">
              <SidebarGroupLabel className={cn(S.groupLabel, 'flex items-center justify-between pr-1', S.label)}>
                <span className="flex items-center gap-1.5">
                  <Pin className="size-3 rotate-45" aria-hidden /> Your pages
                </span>
                {!trial.readOnly && (
                  <button
                    type="button"
                    onClick={() => openSidebarCustomise('pages')}
                    className={cn('flex size-6 items-center justify-center rounded-md normal-case', S.iconBtn, S.ring)}
                    title="Customise your pages"
                    aria-label="Customise your pages"
                  >
                    <SlidersHorizontal className="size-3.5" />
                  </button>
                )}
              </SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu className="gap-0.5">
                  {yourPages.map((i) => renderLink(i, 'unpin'))}
                  {suggestion && (
                    <SidebarMenuItem className="group-data-[collapsible=icon]:hidden">
                      <div className={cn('flex items-center gap-1 rounded-lg border border-dashed pr-1', S.divider)}>
                        <button
                          type="button"
                          onClick={() => togglePin(suggestion.url)}
                          title="You open this often. Pin it here"
                          aria-label={`Pin ${suggestion.title}: you open it often`}
                          className={cn('flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm', S.rowIdle, S.ring)}
                        >
                          <suggestion.icon className={cn('size-4 shrink-0', S.icon)} />
                          <span className="truncate">{suggestion.title}</span>
                          <span className="ml-auto flex size-5 shrink-0 items-center justify-center rounded-full text-[#15233f]" style={{ backgroundColor: S.bar }} aria-hidden>
                            <Pin className="size-3 rotate-45" />
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => dismissSuggestion(person, suggestion.url)}
                          title="Not now"
                          aria-label={`Don't suggest ${suggestion.title}`}
                          className={cn('flex size-6 shrink-0 items-center justify-center rounded-md', S.iconBtn, S.ring)}
                        >
                          <X className="size-3.5" />
                        </button>
                      </div>
                    </SidebarMenuItem>
                  )}
                  {allPins.length === 0 && !trial.readOnly && (
                    <SidebarMenuItem>
                      <SidebarMenuButton onClick={openAllPages} tooltip="Pin a page" className={cn(S.navBase, 'border border-dashed', S.divider, S.rowIdle, S.ring)}>
                        <Plus className={cn('size-4 shrink-0', S.icon)} />
                        <span className="truncate">Pin the pages you use</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          )}

          <SidebarGroup className="px-1 py-0.5">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton onClick={openAllPages} tooltip="All pages" data-guide="app.all" className={cn(S.navBase, S.rowIdle, S.ring)}>
                  <LayoutGrid className={cn('size-4 shrink-0', S.icon)} />
                  <span className="truncate">All pages</span>
                  {hiddenPins > 0 && (
                    <span className="ml-auto text-[11px] tabular-nums opacity-70 group-data-[collapsible=icon]:hidden" title={`${hiddenPins} pinned pages are here: the screen is too short to show them all`}>
                      +{hiddenPins} pinned
                    </span>
                  )}
                  <ChevronRight className={cn('ml-auto size-3.5 group-data-[collapsible=icon]:hidden', S.chevron)} aria-hidden />
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroup>

          {(learn || management.length > 0) && (
            <SidebarGroup className="mt-auto px-1 py-0.5">
              <SidebarGroupContent>
                <SidebarMenu className="gap-0.5">
                  {learn && renderLink(learn)}
                  {management.map((i) => renderLink(i))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          )}
        </SidebarContent>

        <SidebarFooter className={S.footer}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                data-guide="app.me"
                className={cn('flex w-full items-center gap-2.5 text-left transition-colors', S.footerBtn, S.card, S.hoverBg, S.ring)}
                title="Your account: theme, sidebar, log out"
              >
                <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold', S.avatar)} aria-hidden>
                  {initialsOf(userName || companyName)}
                </span>
                <span className="flex min-w-0 flex-1 flex-col group-data-[collapsible=icon]:hidden">
                  <span className={cn('truncate text-sm font-semibold', S.name)}>{userName || 'Signed in'}</span>
                  <span className={cn('truncate text-xs', S.role)}>{roleLabel(me?.role)}</span>
                </span>
                <ChevronsUpDown className={cn('size-4 shrink-0 group-data-[collapsible=icon]:hidden', S.chevron)} aria-hidden />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-60">
              <DropdownMenuLabel className="flex flex-col">
                <span className="truncate text-sm">{userName || 'Signed in'}</span>
                <span className="truncate text-xs font-normal text-muted-foreground">
                  {roleLabel(me?.role)} · {companyName}
                </span>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={toggleTheme} className="gap-2">
                {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
                {isDark ? 'Light mode' : 'Dark mode'}
              </DropdownMenuItem>
              {/* WEB-103: the look, Blueprint (the phone app's) or Classic (before 22 Nov 2026). */}
              <DropdownMenuLabel className="pt-2 pb-1 font-mono text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">Look</DropdownMenuLabel>
              {(Object.keys(LOOKS) as Look[]).map((l) => (
                <DropdownMenuItem key={l} onSelect={(e) => { e.preventDefault(); setLook(l) }} className="gap-2" aria-checked={look === l} role="menuitemradio">
                  <span className={cn('flex size-4 items-center justify-center rounded-full border', look === l ? 'border-foreground bg-foreground text-background' : 'border-muted-foreground/50')} aria-hidden>
                    {look === l && <Check className="size-3" strokeWidth={3} />}
                  </span>
                  {LOOKS[l]}
                </DropdownMenuItem>
              ))}
              {!trial.readOnly && (
                <DropdownMenuItem onSelect={() => openSidebarCustomise('pages')} className="gap-2">
                  <SlidersHorizontal className="size-4" /> Customise your sidebar
                </DropdownMenuItem>
              )}
              {me?.is_platform_admin && (
                <DropdownMenuItem onSelect={() => setShowPlanned(!showPlanned)} className="gap-2">
                  <MapIcon className="size-4" /> {showPlanned ? 'Hide planned modules' : 'Show planned modules'}
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => logout().then(() => window.location.assign('/login'))} className="gap-2 text-destructive focus:text-destructive">
                <LogOut className="size-4" /> Log out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarFooter>
      </div>
    </Sidebar>
  )
}

/** UX-74: an everyday page that has nothing to show yet: dimmed with a lock; a tap says why instead of opening it. */
function LockedRow({ item, why, S }: { item: NavItem; why: string; S: SidebarLook }) {
  const [told, setTold] = useState(false)
  const ItemIcon = item.icon
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        onClick={() => setTold((t) => !t)}
        tooltip={`${item.title}: ${why.toLowerCase()}`}
        // Not aria-disabled: the sidebar's button style turns clicks off for it, and a tap here says why.
        aria-label={`${item.title}, not open yet: ${why.toLowerCase()}`}
        aria-expanded={told}
        className={cn(S.navBase, S.rowIdle, S.ring, 'opacity-55')}
      >
        <ItemIcon className={cn('size-4 shrink-0', S.icon)} />
        <span className="truncate">{item.title}</span>
        <Lock className="ml-auto size-3.5 shrink-0 group-data-[collapsible=icon]:hidden" aria-label="not open yet" />
      </SidebarMenuButton>
      {told && <p className={cn('m-0 px-2.5 pb-1.5 pl-9 text-xs group-data-[collapsible=icon]:hidden', S.label)}>{why}.</p>}
    </SidebarMenuItem>
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
  S: SidebarLook
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
          'flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-[11px] text-xs font-bold',
          logo ? 'bg-white p-1' : colour ? 'text-white' : S.avatar,
        )}
        style={!logo && colour ? { backgroundColor: colour } : undefined}
        aria-hidden="true"
      >
        {logo ? <img src={logo} alt="" className="max-h-full max-w-full object-contain" /> : letters || 'M'}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className={cn('truncate text-sm leading-tight font-semibold', S.name)}>{name}</span>
        <span className={cn('truncate text-xs', trialLeft !== null && trialLeft !== undefined && trialLeft <= 3 ? 'text-[#ffd23f]' : S.role)}>{line}</span>
      </span>
      {isAdmin && <ChevronRight className={cn('size-4 shrink-0 opacity-0 transition-opacity group-hover/company:opacity-100', S.chevron)} aria-hidden="true" />}
    </>
  )
  return isAdmin ? (
    <Link to="/company" className={cn('group/company flex items-center gap-2.5 transition-colors', S.companyBox, S.card, S.hoverBg, S.ring)} title="Open company settings">
      {body}
    </Link>
  ) : (
    <div className={cn('flex items-center gap-2.5', S.companyBox, S.card)}>{body}</div>
  )
}

/** The header's Back button (on a project's or a person's page). */
function BackLink({ to, S }: { to: string; S: SidebarLook }) {
  return (
    <Link
      to={to}
      className={cn('flex size-8 items-center justify-center rounded-lg transition-colors group-data-[collapsible=icon]:hidden', S.headerBtn, S.ring)}
      title="Back"
      aria-label="Back"
    >
      <ArrowLeft className="size-4" />
    </Link>
  )
}
