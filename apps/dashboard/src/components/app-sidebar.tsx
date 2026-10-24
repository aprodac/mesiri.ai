import { useState, useEffect } from 'react'
import { flushSync } from 'react-dom'
import {
  LayoutDashboard,
  Building2,
  Building,
  LogOut,
  Users,
  ArrowLeft,
  History,
  BarChart3,
  Image as ImageIcon,
  FileText,
  DollarSign,
  Wallet,
  Boxes,
  Activity,
  Landmark,
  PieChart,
  ArrowLeftRight,
  Store,
  Tags,
  SlidersHorizontal,
  Warehouse,
  ShoppingBag,
  Truck,
  Layers,
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
import type { ScopeKind } from '@/lib/scope-types'
import { cn } from '@/lib/utils'
import { useModuleEnabled, type ModuleKey } from '@/lib/modules'
import { useSidebarTheme, type SidebarTheme } from '@/lib/sidebar-theme'

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
}

type NavCategory = {
  title: string
  icon: React.ElementType
  tone: SectionTone
  items: NavItem[]
  requiredRole?: string
  module?: ModuleKey
}

const OPERATIONS_CATEGORY: NavCategory = {
  title: 'Operations',
  icon: Activity,
  tone: 'operations',
  items: [
    { title: 'Dashboard', url: '/operations/dashboard', icon: LayoutDashboard },
    { title: 'Activities', url: '/operations/activities', icon: Activity },
    { title: 'Timeline', url: '/operations/timeline', icon: History },
    { title: 'Daily Reports', url: '/operations/daily-reports', icon: FileText },
    { title: 'Issues', url: '/operations/issues', icon: AlertCircle },
    { title: 'Gallery', url: '/operations/gallery', icon: ImageIcon },
    { title: 'Analytics', url: '/operations/analytics', icon: BarChart3 },
    { title: 'Automations', url: '/operations/automations', icon: Clock, module: 'automations' },
    { title: 'Settings', url: '/operations/settings', icon: SlidersHorizontal },
  ],
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
  title: 'Labour & Workforce',
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

const MATERIALS_CATEGORY: NavCategory = {
  title: 'Materials',
  module: 'materials',
  icon: Boxes,
  tone: 'materials',
  items: [
    { title: 'Overview', url: '/materials/overview', icon: Boxes },
    { title: 'Inventory', url: '/materials/inventory', icon: Warehouse },
    { title: 'Purchases', url: '/materials/purchases', icon: ShoppingBag },
    { title: 'Suppliers', url: '/materials/suppliers', icon: Truck },
    { title: 'Categories', url: '/materials/categories', icon: Layers },
  ],
}

// V1 primary navigation (tracker WEB-01). "Today" is the WEB-03 page; the
// older overview stays reachable under More > Operations.
const PRIMARY_ITEMS: NavItem[] = [
  { title: 'Today', url: '/today', icon: CalendarDays },
  { title: 'Daily Reports', url: '/operations/daily-reports', icon: FileText },
  { title: 'Issues', url: '/operations/issues', icon: AlertCircle },
]

const ROOT_MANAGEMENT_ITEMS: NavItem[] = [
  { title: 'Projects & Sites', url: '/projects', icon: Building2, requiredRole: 'ADMIN' },
  { title: 'Team', url: '/users', icon: Users, requiredRole: 'ADMIN' },
  { title: 'Company', url: '/company', icon: Building, requiredRole: 'ADMIN' },
]

// Everything outside V1's core, kept reachable under "More". WEB-02 hides
// these per company with the module switch rather than deleting them.
const OPERATIONS_MORE_CATEGORY: NavCategory = {
  ...OPERATIONS_CATEGORY,
  items: OPERATIONS_CATEGORY.items.filter(
    (item) =>
      !['/operations/daily-reports', '/operations/issues'].includes(
        item.url
      )
  ),
}

const MORE_CATEGORIES: NavCategory[] = [
  OPERATIONS_MORE_CATEGORY,
  LABOUR_CATEGORY,
  MATERIALS_CATEGORY,
  FINANCE_CATEGORY,
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
    brand: 'bg-[#3E3C3D] text-white',
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
    brand: 'bg-[#3E3C3D] text-white dark:bg-foreground dark:text-background',
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
  operations: { charcoal: 'text-sky-300', light: 'text-sky-700 dark:text-sky-300' },
  labour: { charcoal: 'text-amber-300', light: 'text-amber-700 dark:text-amber-300' },
  materials: { charcoal: 'text-emerald-300', light: 'text-emerald-700 dark:text-emerald-300' },
  finance: { charcoal: 'text-violet-300', light: 'text-violet-700 dark:text-violet-300' },
} as const

type SectionTone = keyof typeof SECTION_TONES

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
    const isOperational = !['/projects', '/users', '/company'].includes(baseUrl)
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

  const showBackButton = location.pathname.startsWith('/projects/') || location.pathname.startsWith('/users/')

  const visibleManagementItems = ROOT_MANAGEMENT_ITEMS.filter(
    (item) =>
      (!item.requiredScope || allowed.includes(item.requiredScope)) &&
      (!item.requiredRole || me?.role === item.requiredRole)
  )

  // Production's /auth/me returns org_name/name; the older identity router
  // shape used organization_name/full_name (see lib/api.ts's Me).
  const companyName = me?.org_name || me?.organization_name || 'Mesiri'
  const userName = me?.name || me?.full_name || ''

  const isModuleEnabled = useModuleEnabled()
  const visibleMoreCategories = MORE_CATEGORIES.filter((category) =>
    isModuleEnabled(category.module)
  ).map((category) => ({
    ...category,
    items: category.items.filter(
      (item) =>
        isModuleEnabled(item.module) &&
        (!item.allowedRoles || item.allowedRoles.includes((me?.role || '').toUpperCase()))
    ),
  }))

  const isMoreActive =
    visibleMoreCategories.some((category) =>
      category.items.some((item) => checkIsItemActive(location.pathname, item.url))
    ) || checkIsItemActive(location.pathname, '/whatsapp/inbox')
  const [isMoreOpen, setIsMoreOpen] = useState(isMoreActive)
  useEffect(() => {
    if (isMoreActive) setIsMoreOpen(true)
  }, [isMoreActive])

  const renderLink = (item: NavItem) => {
    const ItemIcon = item.icon
    const active = checkIsItemActive(location.pathname, item.url)
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
            <ItemIcon className={cn('size-4 shrink-0', active ? S.iconActive : S.icon)} />
            <span className="truncate">{item.title}</span>
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
          {/* A 64px band with a wedge sloping into the sidebar body and an
              accent stripe on its edge. The wedge is filled with --sidebar so
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
                stroke="var(--primary)"
                strokeWidth="2"
                strokeLinecap="round"
                opacity="0.85"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
            <div className="relative flex h-full items-center justify-between gap-2 px-3.5 -mt-3 group-data-[collapsible=icon]:px-2">
              <div className="flex items-center gap-2.5 min-w-0">
                <div
                  className={cn(
                    'size-8 rounded-lg flex items-center justify-center font-bold text-sm shrink-0',
                    S.brand
                  )}
                >
                  M
                </div>
                <span
                  className={cn(
                    'font-bold text-[17px] tracking-tight group-data-[collapsible=icon]:hidden',
                    S.headerText
                  )}
                >
                  Mesiri
                </span>
              </div>
              {showBackButton && (
                <Link
                  to={location.pathname.startsWith('/users/') ? '/users' : '/projects'}
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

          <SidebarGroup className="p-1">
            <SidebarMenu className="gap-0.5">
              <SidebarMenuItem>
                <SidebarMenuButton
                  onClick={() => setIsMoreOpen((prev) => !prev)}
                  tooltip="More"
                  aria-expanded={isMoreOpen}
                  className={cn(
                    'w-full flex items-center justify-between rounded-lg px-2.5 py-2 text-[11px] font-semibold uppercase tracking-wider',
                    S.label,
                    S.hoverBg,
                    S.ring
                  )}
                >
                  <span className="group-data-[collapsible=icon]:hidden">More</span>
                  <span className={S.chevron}>
                    {isMoreOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                  </span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              {isMoreOpen && (
                <>
                  {renderLink({ title: 'WhatsApp Inbox', url: '/whatsapp/inbox', icon: MessageSquare })}
                  {visibleMoreCategories.map((category) => (
                    <CollapsibleNavCategory
                      key={category.title}
                      category={category}
                      getUrlWithScope={getUrlWithScope}
                      pathname={location.pathname}
                      allowedScopes={allowed}
                      userRole={me?.role}
                      theme={sidebarTheme}
                    />
                  ))}
                </>
              )}
            </SidebarMenu>
          </SidebarGroup>
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
