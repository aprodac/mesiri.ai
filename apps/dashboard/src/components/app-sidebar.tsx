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
  items: NavItem[]
  requiredRole?: string
  module?: ModuleKey
}

const OPERATIONS_CATEGORY: NavCategory = {
  title: 'Operations',
  icon: Activity,
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

const NAV_LINK_BASE =
  'flex items-center gap-2.5 w-full px-2.5 py-2 rounded-lg text-sm transition-colors'
// data-[active=true]:font-semibold so it outranks SidebarMenuButton's own
// data-[active=true]:font-medium for the primary links.
const NAV_LINK_ACTIVE =
  'bg-sidebar-accent text-sidebar-accent-foreground font-semibold data-[active=true]:font-semibold'
const NAV_LINK_IDLE =
  'text-sidebar-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground'

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
}: {
  category: NavCategory
  getUrlWithScope: (url: string) => string
  pathname: string
  allowedScopes: ScopeKind[]
  userRole?: string
}) {
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
          isChildActive ? 'font-semibold text-sidebar-accent-foreground' : NAV_LINK_IDLE
        )}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <IconComp className="size-4 shrink-0" />
          <span className="truncate group-data-[collapsible=icon]:hidden">{category.title}</span>
        </div>
        <span className="group-data-[collapsible=icon]:hidden text-muted-foreground">
          {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </span>
      </SidebarMenuButton>

      {/* Submenu Items */}
      {isOpen && !isCollapsedMode && (
        <div className="ml-4 pl-2.5 border-l border-sidebar-border my-0.5 flex flex-col gap-0.5 group-data-[collapsible=icon]:hidden">
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
                    'flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[13px] transition-colors',
                    isLinkActive || isActive ? NAV_LINK_ACTIVE : NAV_LINK_IDLE
                  )
                }
              >
                <ItemIcon className="size-3.5 shrink-0" />
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
            className={cn(NAV_LINK_BASE, active ? NAV_LINK_ACTIVE : NAV_LINK_IDLE)}
          >
            <ItemIcon className="size-4 shrink-0" />
            <span className="truncate">{item.title}</span>
          </NavLink>
        </SidebarMenuButton>
      </SidebarMenuItem>
    )
  }

  return (
    <Sidebar collapsible="icon" className="border-r border-sidebar-border">
      <SidebarHeader className="gap-3 px-2.5 pt-3 pb-1">
        <div className="flex items-center justify-between gap-2 px-1">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="size-8 rounded-lg bg-sidebar-primary text-sidebar-primary-foreground flex items-center justify-center font-bold text-sm shrink-0">
              M
            </div>
            <span className="font-bold text-[17px] tracking-tight text-sidebar-accent-foreground group-data-[collapsible=icon]:hidden">
              Mesiri
            </span>
          </div>
          {showBackButton && (
            <Link
              to={location.pathname.startsWith('/users/') ? '/users' : '/projects'}
              className="text-muted-foreground hover:text-foreground transition-colors group-data-[collapsible=icon]:hidden size-8 flex items-center justify-center hover:bg-sidebar-accent rounded-lg"
              title="Back"
              aria-label="Back"
            >
              <ArrowLeft className="size-4" />
            </Link>
          )}
        </div>
        <div className="rounded-xl border border-sidebar-border bg-background/60 px-3 py-2 group-data-[collapsible=icon]:hidden">
          <div className="text-xs text-muted-foreground">Company</div>
          <div className="text-sm font-semibold text-sidebar-accent-foreground truncate">
            {companyName}
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent className="px-1.5 py-1 gap-1">
        <SidebarGroup className="p-1">
          <SidebarGroupContent>
            <SidebarMenu className="gap-0.5">{PRIMARY_ITEMS.map(renderLink)}</SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {visibleManagementItems.length > 0 && (
          <SidebarGroup className="p-1">
            <SidebarGroupLabel className="px-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
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
                className="w-full flex items-center justify-between rounded-lg px-2.5 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground hover:bg-sidebar-accent/70"
              >
                <span className="group-data-[collapsible=icon]:hidden">More</span>
                {isMoreOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
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
                  />
                ))}
              </>
            )}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t border-sidebar-border p-2">
        <div className="flex items-center gap-2.5 px-1 group-data-[collapsible=icon]:hidden">
          <div
            className="size-8 rounded-full bg-secondary text-secondary-foreground flex items-center justify-center text-xs font-semibold shrink-0"
            aria-hidden="true"
          >
            {initialsOf(userName || companyName)}
          </div>
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-sm font-semibold text-sidebar-accent-foreground truncate">
              {userName || 'Signed in'}
            </span>
            <span className="text-xs text-muted-foreground truncate">{roleLabel(me?.role)}</span>
          </div>
        </div>
        <SidebarMenu>
          <SidebarMenuItem className="flex items-center gap-1">
            <SidebarMenuButton
              onClick={() => logout().then(() => window.location.assign('/login'))}
              tooltip="Log out"
              className="flex-1 rounded-lg px-2.5 py-2 text-sm text-sidebar-foreground hover:bg-sidebar-accent/70 hover:text-destructive transition-colors"
            >
              <LogOut className="size-4 shrink-0" />
              <span>Log out</span>
            </SidebarMenuButton>
            <SidebarMenuButton
              onClick={toggleTheme}
              tooltip={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
              aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
              className="size-8 p-0 flex items-center justify-center rounded-lg text-sidebar-foreground hover:bg-sidebar-accent/70 shrink-0"
            >
              {isDark ? <Sun className="size-4 shrink-0" /> : <Moon className="size-4 shrink-0" />}
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
