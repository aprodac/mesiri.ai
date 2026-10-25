import { useState, useEffect } from 'react'
import { flushSync } from 'react-dom'
import {
  Building2,
  Building,
  LogOut,
  Users,
  ArrowLeft,
  Activity,
  History,
  Image as ImageIcon,
  BarChart3,
  FileText,
  DollarSign,
  Wallet,
  Boxes,
  Landmark,
  PieChart,
  ArrowLeftRight,
  Store,
  Tags,
  SlidersHorizontal,
  ChevronRight,
  ChevronDown,
  CalendarDays,
  Bot,
  Sun,
  Moon,
  HardHat,
  ClipboardCheck,
  MessageSquare,
  AlertCircle,
  Clock,
  Palette,
} from 'lucide-react'
import { NavLink, Link, useLocation } from 'react-router-dom'
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
import { logout } from '@/lib/api'
import { MesiriMark, MesiriWordmark } from '@/components/brand/mesiri-logo'
import type { ScopeKind } from '@/lib/scope-types'
import { cn } from '@/lib/utils'
import { useModuleEnabled, type ModuleKey } from '@/lib/modules'
import { useSidebarTheme, type SidebarTheme } from '@/lib/sidebar-theme'
import { useNavCounts } from '@/lib/nav-counts'

// Mirrors backend mesiri/authorization/roles.py EXPENSE_VIEW_ROLES (SEC-01);
// the API refuses everyone else, this only keeps the link out of their way.
const EXPENSE_VIEW_ROLES = ['ADMIN', 'OWNER', 'SUPER_ADMIN', 'FINANCE', 'PROJECT_MANAGER'] as const

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
  // The icon's colour (WEB-20), like the More sections' icons.
  tone?: NavTone
  // Which live count to show as a badge (WEB-20).
  badge?: 'drafts' | 'issues'
}

type NavCategory = {
  title: string
  icon: React.ElementType
  tone: SectionTone
  items: NavItem[]
  requiredRole?: string
  module?: ModuleKey
}

const FINANCE_CATEGORY: NavCategory = {
  title: 'Finance',
  module: 'finance',
  icon: Landmark,
  tone: 'finance',
  items: [
    { title: 'Overview', url: '/finance/overview', icon: PieChart },
    { title: 'Expenses', url: '/finance/expenses', icon: DollarSign, allowedRoles: EXPENSE_VIEW_ROLES },
    { title: 'Accounts', url: '/finance/accounts', icon: Landmark },
    { title: 'WhatsApp Automations', url: '/finance/whatsapp', icon: Bot },
    { title: 'Transactions', url: '/finance/transactions', icon: ArrowLeftRight },
    { title: 'Petty Cash', url: '/finance/petty-cash', icon: Wallet },
    { title: 'Vendors', url: '/finance/vendors', icon: Store },
    { title: 'Categories', url: '/finance/categories', icon: Tags },
    { title: 'Reports', url: '/finance/reports', icon: FileText },
    { title: 'Settings', url: '/finance/settings', icon: SlidersHorizontal },
  ],
}

const LABOUR_CATEGORY: NavCategory = {
  title: 'Labour',
  module: 'labour',
  icon: HardHat,
  tone: 'labour',
  items: [
    { title: 'Overview', url: '/labour/overview', icon: PieChart },
    { title: 'Attendance', url: '/labour/attendance', icon: ClipboardCheck },
    { title: 'Workers Roster', url: '/labour/workers', icon: Users },
    { title: 'Analytics', url: '/labour/analytics', icon: BarChart3 },
    { title: 'WhatsApp Automations', url: '/labour/whatsapp', icon: Bot },
    { title: 'Reports', url: '/labour/reports', icon: FileText },
    { title: 'Settings', url: '/labour/settings', icon: SlidersHorizontal },
  ],
}

// V1 navigation (WEB-21, docs/DESIGN.md "Pages and routes"): the daily
// pages, then setup. No "More": pages outside V1 were removed, and modules a
// company has not switched on (WEB-02) are hidden.
const PRIMARY_ITEMS: NavItem[] = [
  { title: 'Today', url: '/today', icon: CalendarDays, tone: 'orange', badge: 'drafts' },
  { title: 'Reports', url: '/reports', icon: FileText, tone: 'sky' },
  { title: 'Issues', url: '/issues', icon: AlertCircle, tone: 'rose', badge: 'issues' },
]

// Site records: everything the sites sent, across days and sites.
const RECORD_ITEMS: NavItem[] = [
  { title: 'Activities', url: '/activities', icon: Activity, tone: 'sky' },
  { title: 'Gallery', url: '/gallery', icon: ImageIcon, tone: 'violet' },
  { title: 'Timeline', url: '/timeline', icon: History, tone: 'teal' },
  { title: 'Analytics', url: '/analytics', icon: BarChart3, tone: 'indigo' },
]

const MATERIALS_ITEM: NavItem = { title: 'Materials', url: '/materials', icon: Boxes, module: 'materials', tone: 'emerald' }

const ROOT_MANAGEMENT_ITEMS: NavItem[] = [
  { title: 'Projects & Sites', url: '/projects', icon: Building2, requiredRole: 'ADMIN', tone: 'teal' },
  { title: 'Team', url: '/team', icon: Users, requiredRole: 'ADMIN', tone: 'violet' },
  { title: 'Company', url: '/company', icon: Building, requiredRole: 'ADMIN', tone: 'indigo' },
  { title: 'WhatsApp Inbox', url: '/whatsapp/inbox', icon: MessageSquare, requiredRole: 'ADMIN', tone: 'green' },
  { title: 'Automations', url: '/automations', icon: Clock, module: 'automations', tone: 'sky' },
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

// Visual tokens per sidebar theme. Charcoal is the default; Light follows the
// app's shadcn tokens (so it also darkens correctly in dark mode). `aside` also
// re-points the --sidebar-* variables, so the shadcn sidebar parts' own hover,
// active and focus styles match the theme without changing ui/sidebar.tsx.
const SIDEBAR_THEMES = {
  charcoal: {
    aside:
      'bg-[#3E3C3D] text-[#EEF1F6] [--sidebar:#3E3C3D] [--sidebar-foreground:#EEF1F6] [--sidebar-accent:rgba(255,255,255,0.10)] [--sidebar-accent-foreground:#FFFFFF] [--sidebar-border:rgba(255,255,255,0.06)] [--sidebar-ring:rgba(255,255,255,0.30)]',
    edge: 'border-white/[0.06]',
    ring: 'focus-visible:ring-white/30',
    rowIdle: 'text-white/65 hover:bg-white/[0.06] hover:text-white',
    rowActive: 'bg-white/[0.10] text-white font-semibold',
    hoverBg: 'hover:bg-white/[0.06]',
    label: 'text-white/40',
    icon: 'text-white/45 group-hover/row:text-white/80',
    iconActive: 'text-white',
    iconBtn: 'text-white/40 hover:text-white hover:bg-white/10',
    divider: 'border-white/[0.06]',
    guide: 'border-white/10',
    chevron: 'text-white/35',
    groupIdle: 'text-white/65 hover:text-white',
    groupActive: 'text-white font-semibold',
    card: 'border-white/10 bg-white/[0.06]',
    // Header band above the wedge: light band, charcoal ink.
    headerBg: '[--sidebar-header:#EEF1F6]',
    headerText: 'text-[#3E3C3D]',
    headerBtn: 'text-[#3E3C3D]/60 hover:text-[#3E3C3D] hover:bg-black/[0.06]',
    avatar: 'bg-white/10 text-white',
    danger: 'hover:text-[#FF9A8B]',
    name: 'text-white',
    role: 'text-white/45',
    scrollbar: 'sidebar-scrollbar',
  },
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
    headerBg: '[--sidebar-header:#FFFFFF] dark:[--sidebar-header:var(--background)]',
    headerText: 'text-foreground',
    headerBtn: 'text-muted-foreground hover:text-foreground hover:bg-black/[0.04] dark:hover:bg-muted',
    avatar: 'bg-white text-foreground border border-black/[0.06] dark:bg-background dark:border-border',
    danger: 'hover:text-destructive',
    name: 'text-foreground',
    role: 'text-muted-foreground',
    scrollbar: 'sidebar-scrollbar-light',
  },
} as const

// Each More section keeps its own icon colour, in the shade that reads on the
// theme's background (on-dark for charcoal, on-light for light).
const SECTION_TONES = {
  labour: { charcoal: 'text-amber-300', light: 'text-amber-700 dark:text-amber-300' },
  finance: { charcoal: 'text-violet-300', light: 'text-violet-700 dark:text-violet-300' },
} as const

type SectionTone = keyof typeof SECTION_TONES

// Main navigation icon colours (WEB-20): the same treatment as the More
// sections -- a coloured icon, no background -- in the shade that reads on
// the theme. Palette classes are allowed here only: identity colours, not
// states (docs/DESIGN.md).
const NAV_TONES = {
  orange: { charcoal: 'text-orange-300', light: 'text-orange-700 dark:text-orange-300' },
  sky: { charcoal: 'text-sky-300', light: 'text-sky-700 dark:text-sky-300' },
  rose: { charcoal: 'text-rose-300', light: 'text-rose-700 dark:text-rose-300' },
  emerald: { charcoal: 'text-emerald-300', light: 'text-emerald-700 dark:text-emerald-300' },
  violet: { charcoal: 'text-violet-300', light: 'text-violet-700 dark:text-violet-300' },
  amber: { charcoal: 'text-amber-300', light: 'text-amber-700 dark:text-amber-300' },
  green: { charcoal: 'text-green-300', light: 'text-green-700 dark:text-green-300' },
  teal: { charcoal: 'text-teal-300', light: 'text-teal-700 dark:text-teal-300' },
  indigo: { charcoal: 'text-indigo-300', light: 'text-indigo-700 dark:text-indigo-300' },
} as const

type NavTone = keyof typeof NAV_TONES

// Badges: orange = waiting on someone, red = something is wrong.
const BADGE = {
  drafts: 'bg-orange-500 text-white',
  issues: 'bg-rose-500 text-white',
} as const

const NAV_LINK_BASE =
  'group/row flex items-center gap-2.5 w-full px-2.5 py-2 rounded-lg text-sm transition-colors'

function checkIsItemActive(pathname: string, itemUrl: string): boolean {
  if (pathname === itemUrl) return true
  if (itemUrl === '/today' && pathname === '/') return true
  if (itemUrl === '/operations/dashboard' && (pathname === '/operations' || pathname === '/operations/dashboard' || pathname === '/overview')) return true
  if (itemUrl === '/finance/overview' && pathname === '/finance') return true
  if (itemUrl === '/materials/overview' && pathname === '/materials') return true
  if (itemUrl !== '/' && pathname.startsWith(itemUrl)) return true
  return false
}

function CollapsibleNavCategory({
  category,
  getUrlWithScope,
  pathname,
  allowedScopes,
  userRole,
  theme,
}: {
  category: NavCategory
  getUrlWithScope: (url: string) => string
  pathname: string
  allowedScopes: ScopeKind[]
  userRole?: string
  theme: SidebarTheme
}) {
  const S = SIDEBAR_THEMES[theme]
  const { state } = useSidebar()
  const isCollapsedMode = state === 'collapsed'

  const filteredItems = category.items.filter(
    (item) =>
      (!item.requiredScope || allowedScopes.includes(item.requiredScope)) &&
      (!item.requiredRole || userRole === item.requiredRole)
  )

  const isChildActive = filteredItems.some((item) => checkIsItemActive(pathname, item.url))

  const [isOpen, setIsOpen] = useState(isChildActive)

  useEffect(() => {
    if (isChildActive) {
      setIsOpen(true)
    }
  }, [pathname, isChildActive])

  if (filteredItems.length === 0) return null

  const IconComp = category.icon

  return (
    <SidebarMenuItem>
      {/* Category Toggle Header */}
      <SidebarMenuButton
        onClick={() => setIsOpen((prev) => !prev)}
        tooltip={category.title}
        aria-expanded={isOpen}
        className={cn(
          'w-full flex items-center justify-between rounded-lg px-2.5 py-2 text-sm transition-colors',
          S.hoverBg,
          S.ring,
          isChildActive ? S.groupActive : S.groupIdle
        )}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <IconComp className={cn('size-4 shrink-0', SECTION_TONES[category.tone][theme])} />
          <span className="truncate group-data-[collapsible=icon]:hidden">{category.title}</span>
        </div>
        <span className={cn('group-data-[collapsible=icon]:hidden', S.chevron)}>
          {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </span>
      </SidebarMenuButton>

      {/* Submenu Items */}
      {isOpen && !isCollapsedMode && (
        <div className={cn('ml-4 pl-2.5 border-l my-0.5 flex flex-col gap-0.5 group-data-[collapsible=icon]:hidden', S.guide)}>
          {filteredItems.map((item) => {
            const ItemIcon = item.icon
            const targetUrl = getUrlWithScope(item.url)
            const isActive = checkIsItemActive(pathname, item.url)

            return (
              <NavLink
                key={item.title}
                to={targetUrl}
                className={({ isActive: isLinkActive }) =>
                  cn(
                    'group/row flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[13px] transition-colors',
                    S.ring,
                    isLinkActive || isActive ? S.rowActive : S.rowIdle
                  )
                }
              >
                <ItemIcon className={cn('size-3.5 shrink-0', isActive ? S.iconActive : S.icon)} />
                <span className="truncate">{item.title}</span>
              </NavLink>
            )
          })}
        </div>
      )}
    </SidebarMenuItem>
  )
}

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

  const getUrlWithScope = (baseUrl: string) => {
    const isOperational = !['/projects', '/team', '/company', '/whatsapp/inbox', '/automations'].includes(baseUrl)
    if (!isOperational) return baseUrl

    const params = new URLSearchParams()
    if (scope.mode === 'project' || scope.mode === 'site') {
      params.set('project', scope.projectId)
    }
    if (scope.mode === 'site') {
      params.set('site', scope.siteId)
    }
    const qs = params.toString()
    return qs ? `${baseUrl}?${qs}` : baseUrl
  }

  const showBackButton = location.pathname.startsWith('/projects/') || location.pathname.startsWith('/team/')

  const isModuleEnabled = useModuleEnabled()
  const visibleManagementItems = ROOT_MANAGEMENT_ITEMS.filter(
    (item) =>
      isModuleEnabled(item.module) &&
      (!item.requiredScope || allowed.includes(item.requiredScope)) &&
      (!item.requiredRole || me?.role === item.requiredRole)
  )


  // Production's /auth/me returns org_name/name; the older identity router
  // shape used organization_name/full_name (see lib/api.ts's Me).
  const companyName = me?.org_name || me?.organization_name || 'Mesiri'
  const userName = me?.name || me?.full_name || ''

  const counts = useNavCounts()
  // Module sections (Labour, Finance) with only the items this role may see.
  const moduleCategories = [LABOUR_CATEGORY, FINANCE_CATEGORY]
    .filter((category) => isModuleEnabled(category.module))
    .map((category) => ({
      ...category,
      items: category.items.filter(
        (item) =>
          isModuleEnabled(item.module) &&
          (!item.allowedRoles || item.allowedRoles.includes((me?.role || '').toUpperCase()))
      ),
    }))
  const renderCategory = (category: NavCategory) => (
    <CollapsibleNavCategory
      key={category.title}
      category={category}
      getUrlWithScope={getUrlWithScope}
      pathname={location.pathname}
      allowedScopes={allowed}
      userRole={me?.role}
      theme={sidebarTheme}
    />
  )

  const renderLink = (item: NavItem) => {
    const ItemIcon = item.icon
    const active = checkIsItemActive(location.pathname, item.url)
    const count = item.badge === 'drafts' ? counts.drafts : item.badge === 'issues' ? counts.openIssues : 0
    // A plain string className, not NavLink's function form: SidebarMenuButton
    // (asChild -> Radix Slot) merges className as text, which silently drops
    // a function, so the active state never rendered.
    return (
      <SidebarMenuItem key={item.title}>
        <SidebarMenuButton asChild tooltip={item.title} isActive={active}>
          <NavLink
            to={getUrlWithScope(item.url)}
            aria-current={active ? 'page' : undefined}
            className={cn(NAV_LINK_BASE, S.ring, active ? S.rowActive : S.rowIdle, 'data-[active=true]:font-semibold')}
          >
            <span className="relative shrink-0">
              <ItemIcon className={cn('size-4', item.tone ? NAV_TONES[item.tone][sidebarTheme] : active ? S.iconActive : S.icon)} />
              {count > 0 && (
                <span
                  aria-hidden
                  className={cn('absolute -top-1 -right-1 hidden size-2 rounded-full ring-2 ring-sidebar group-data-[collapsible=icon]:block', BADGE[item.badge!])}
                />
              )}
            </span>
            <span className="truncate">{item.title}</span>
            {count > 0 && (
              <span
                className={cn(
                  'ml-auto min-w-5 rounded-full px-1.5 py-px text-center text-[11px] font-semibold tabular-nums group-data-[collapsible=icon]:hidden',
                  BADGE[item.badge!],
                )}
                title={item.badge === 'drafts' ? `${count} items to confirm today` : `${count} open issues`}
              >
                {count > 99 ? '99+' : count}
              </span>
            )}
          </NavLink>
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
                stroke="#FACC15"
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
          <div className="bg-sidebar px-2.5 pt-2 pb-1 group-data-[collapsible=icon]:hidden">
            <div className={cn('rounded-xl border px-3 py-2', S.card)}>
              <div className={cn('text-xs', S.label)}>Company</div>
              <div className={cn('text-sm font-semibold truncate', S.name)}>{companyName}</div>
            </div>
          </div>
        </SidebarHeader>

        <SidebarContent className={cn('px-1.5 py-1 gap-1', S.scrollbar)}>
          <SidebarGroup className="p-1">
            <SidebarGroupContent>
              <SidebarMenu className="gap-0.5">{PRIMARY_ITEMS.map(renderLink)}</SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          <SidebarGroup className="p-1">
            <SidebarGroupLabel className={cn('px-2.5 text-[11px] font-semibold uppercase tracking-wider', S.label)}>
              Site records
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-0.5">
                {RECORD_ITEMS.map(renderLink)}
                {moduleCategories.filter((c) => c.module === 'labour').map(renderCategory)}
                {isModuleEnabled(MATERIALS_ITEM.module) && renderLink(MATERIALS_ITEM)}
                {moduleCategories.filter((c) => c.module !== 'labour').map(renderCategory)}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          {visibleManagementItems.length > 0 && (
            <SidebarGroup className="p-1">
              <SidebarGroupLabel
                className={cn('px-2.5 text-[11px] font-semibold uppercase tracking-wider', S.label)}
              >
                Setup
              </SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu className="gap-0.5">{visibleManagementItems.map(renderLink)}</SidebarMenu>
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
              <SidebarMenuButton
                onClick={() => setSidebarTheme(sidebarTheme === 'charcoal' ? 'light' : 'charcoal')}
                tooltip={sidebarTheme === 'charcoal' ? 'Light sidebar' : 'Charcoal sidebar'}
                aria-label={sidebarTheme === 'charcoal' ? 'Switch to light sidebar' : 'Switch to charcoal sidebar'}
                className={cn('size-8 p-0 flex items-center justify-center rounded-lg shrink-0', S.iconBtn, S.ring)}
              >
                <Palette className="size-4 shrink-0" />
              </SidebarMenuButton>
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
