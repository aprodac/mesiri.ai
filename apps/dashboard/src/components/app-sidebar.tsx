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

type NavItem = {
  title: string
  url: string
  icon: React.ComponentType<{ className?: string }>
  requiredScope?: ScopeKind
  requiredRole?: string
}

type NavCategory = {
  title: string
  icon: React.ElementType
  items: NavItem[]
  requiredRole?: string
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
    { title: 'Automations', url: '/operations/automations', icon: Clock },
    { title: 'Settings', url: '/operations/settings', icon: SlidersHorizontal },
  ],
}

const FINANCE_CATEGORY: NavCategory = {
  title: 'Finance',
  icon: Landmark,
  items: [
    { title: 'Overview', url: '/finance/overview', icon: PieChart },
    { title: 'Expenses', url: '/finance/expenses', icon: DollarSign },
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
  icon: Boxes,
  items: [
    { title: 'Overview', url: '/materials/overview', icon: Boxes },
    { title: 'Inventory', url: '/materials/inventory', icon: Warehouse },
    { title: 'Purchases', url: '/materials/purchases', icon: ShoppingBag },
    { title: 'Suppliers', url: '/materials/suppliers', icon: Truck },
    { title: 'Categories', url: '/materials/categories', icon: Layers },
  ],
}

const ROOT_MANAGEMENT_ITEMS: NavItem[] = [
  { title: 'Projects & Sites', url: '/projects', icon: Building2, requiredRole: 'ADMIN' },
  { title: 'Users', url: '/users', icon: Users, requiredRole: 'ADMIN' },
  { title: 'Company', url: '/company', icon: Building, requiredRole: 'ADMIN' },
]

function checkIsItemActive(pathname: string, itemUrl: string): boolean {
  if (pathname === itemUrl) return true
  if (itemUrl === '/overview' && pathname === '/') return true
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
        className={cn(
          'w-full flex items-center justify-between font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800/80 rounded-md px-2 py-1.5 text-xs transition-colors',
          isChildActive && 'bg-slate-100 dark:bg-slate-800 font-semibold text-slate-900 dark:text-white'
        )}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <IconComp className={cn('size-4 shrink-0', isChildActive ? 'text-slate-900 dark:text-white font-bold' : 'text-slate-600 dark:text-slate-400')} />
          <span className="truncate group-data-[collapsible=icon]:hidden">{category.title}</span>
        </div>
        <div className="flex items-center gap-1.5 group-data-[collapsible=icon]:hidden">
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border border-slate-200/60 dark:border-slate-700/60">
            {filteredItems.length}
          </span>
          {isOpen ? (
            <ChevronDown className="size-3.5 text-slate-400 transition-transform duration-200" />
          ) : (
            <ChevronRight className="size-3.5 text-slate-400 transition-transform duration-200" />
          )}
        </div>
      </SidebarMenuButton>

      {/* Submenu Items */}
      {isOpen && !isCollapsedMode && (
        <div className="ml-3 pl-2.5 border-l border-slate-200 dark:border-slate-800 my-0.5 flex flex-col gap-0.5 group-data-[collapsible=icon]:hidden">
          {filteredItems.map((item) => {
            const ItemIcon = item.icon
            const targetUrl = getUrlWithScope(item.url)
            const isActive = checkIsItemActive(pathname, item.url)

            return (
              <NavLink
                key={item.title}
                to={targetUrl}
                className={({ isActive: isLinkActive }) => {
                  const active = isLinkActive || isActive
                  return cn(
                    'flex items-center gap-2 px-2 py-1.5 rounded-md text-xs font-medium transition-all duration-150',
                    active
                      ? 'bg-blue-50 text-blue-600 border-l-2 border-blue-600 dark:bg-zinc-800 dark:text-zinc-100 dark:border-zinc-300 font-semibold rounded-l-none pl-1.5'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100/70 dark:hover:bg-zinc-800/60'
                  )
                }}
              >
                {({ isActive: isLinkActive }) => {
                  const active = isLinkActive || isActive
                  return (
                    <>
                      <ItemIcon className={cn('size-3.5 shrink-0', active ? 'text-blue-600 dark:text-zinc-100 font-bold' : 'text-slate-500 dark:text-slate-400')} />
                      <span className="truncate">{item.title}</span>
                    </>
                  )
                }}
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

  const isDashboardActive = checkIsItemActive(location.pathname, '/overview')

  return (
    <Sidebar collapsible="icon" className="border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950">
      <SidebarHeader>
        <div className="flex items-center justify-between px-2.5 py-2 border-b border-slate-200/80 dark:border-slate-800/80">
          <div className="flex items-center gap-2 overflow-hidden">
            <div className="size-7 rounded-md bg-blue-600 text-white flex items-center justify-center font-bold text-xs shadow-xs shrink-0">
              M
            </div>
            <div className="flex flex-col min-w-0 group-data-[collapsible=icon]:hidden">
              <span className="font-semibold text-xs truncate leading-tight text-slate-900 dark:text-slate-100">
                {me?.organization_name ?? 'Mesiri'}
              </span>
              <span className="text-[9px] text-slate-500 dark:text-slate-400 uppercase tracking-wider font-medium">
                Enterprise App
              </span>
            </div>
          </div>
          {showBackButton && (
            <Link
              to={location.pathname.startsWith('/users/') ? '/users' : '/projects'}
              className="text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors group-data-[collapsible=icon]:hidden size-6 flex items-center justify-center hover:bg-slate-100 dark:hover:bg-slate-800 rounded-md"
              title="Back"
            >
              <ArrowLeft className="size-3.5" />
            </Link>
          )}
        </div>
      </SidebarHeader>

      <SidebarContent className="px-1.5 py-1 gap-1">
        {/* Core Operations Section */}
        <SidebarGroup className="p-1 py-0.5">
          <SidebarGroupLabel className="flex items-center gap-1.5 text-[10px] font-bold tracking-wider text-blue-600 dark:text-blue-400 uppercase whitespace-nowrap px-1.5 h-6">
            <span className="size-1.5 rounded-full bg-blue-600 dark:bg-blue-400 shrink-0" />
            <span>Core Operations</span>
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-0.5">
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="Dashboard">
                  <NavLink
                    to={getUrlWithScope('/overview')}
                    end
                    className={({ isActive: isLinkActive }) => {
                      const active = isLinkActive || isDashboardActive
                      return cn(
                        'flex items-center justify-between w-full px-2 py-1.5 rounded-md text-xs font-medium transition-colors',
                        active
                          ? 'bg-blue-50 text-blue-600 border-l-2 border-blue-600 dark:bg-zinc-800 dark:text-zinc-100 dark:border-zinc-300 font-semibold rounded-l-none pl-1.5'
                          : 'text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-zinc-800/60'
                      )
                    }}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <LayoutDashboard className={cn('size-4 shrink-0', isDashboardActive ? 'text-blue-600 dark:text-zinc-100 font-bold' : 'text-slate-600 dark:text-slate-400')} />
                      <span className="truncate">Dashboard</span>
                    </div>
                  </NavLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="WhatsApp Inbox">
                  <NavLink
                    to={getUrlWithScope('/whatsapp/inbox')}
                    className={({ isActive: isLinkActive }) => {
                      const active = isLinkActive || checkIsItemActive(location.pathname, '/whatsapp/inbox')
                      return cn(
                        'flex items-center justify-between w-full px-2 py-1.5 rounded-md text-xs font-medium transition-colors',
                        active
                          ? 'bg-blue-50 text-blue-600 border-l-2 border-blue-600 dark:bg-zinc-800 dark:text-zinc-100 dark:border-zinc-300 font-semibold rounded-l-none pl-1.5'
                          : 'text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-zinc-800/60'
                      )
                    }}
                  >
                    {({ isActive: isLinkActive }) => {
                      const active = isLinkActive || checkIsItemActive(location.pathname, '/whatsapp/inbox')
                      return (
                        <div className="flex items-center gap-2.5 min-w-0">
                          <MessageSquare className={cn('size-4 shrink-0', active ? 'text-blue-600 dark:text-zinc-100 font-bold' : 'text-slate-600 dark:text-slate-400')} />
                          <span className="truncate">WhatsApp Inbox</span>
                        </div>
                      )
                    }}
                  </NavLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <CollapsibleNavCategory
                category={OPERATIONS_CATEGORY}
                getUrlWithScope={getUrlWithScope}
                pathname={location.pathname}
                allowedScopes={allowed}
                userRole={me?.role}
              />
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Financial Management Section */}
        <SidebarGroup className="p-1 py-0.5">
          <SidebarGroupLabel className="flex items-center gap-1.5 text-[10px] font-bold tracking-wider text-emerald-600 dark:text-emerald-400 uppercase whitespace-nowrap px-1.5 h-6">
            <span className="size-1.5 rounded-full bg-emerald-600 dark:bg-emerald-400 shrink-0" />
            <span>Financial Management</span>
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-0.5">
              <CollapsibleNavCategory
                category={FINANCE_CATEGORY}
                getUrlWithScope={getUrlWithScope}
                pathname={location.pathname}
                allowedScopes={allowed}
                userRole={me?.role}
              />
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Labour & Workforce Section */}
        <SidebarGroup className="p-1 py-0.5">
          <SidebarGroupLabel className="flex items-center gap-1.5 text-[10px] font-bold tracking-wider text-amber-600 dark:text-amber-400 uppercase whitespace-nowrap px-1.5 h-6">
            <span className="size-1.5 rounded-full bg-amber-600 dark:bg-amber-400 shrink-0" />
            <span>Labour & Workforce</span>
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-0.5">
              <CollapsibleNavCategory
                category={LABOUR_CATEGORY}
                getUrlWithScope={getUrlWithScope}
                pathname={location.pathname}
                allowedScopes={allowed}
                userRole={me?.role}
              />
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Business & Materials Section */}
        <SidebarGroup className="p-1 py-0.5">
          <SidebarGroupLabel className="flex items-center gap-1.5 text-[10px] font-bold tracking-wider text-purple-600 dark:text-purple-400 uppercase whitespace-nowrap px-1.5 h-6">
            <span className="size-1.5 rounded-full bg-purple-600 dark:bg-purple-400 shrink-0" />
            <span>Business Operations</span>
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-0.5">
              <CollapsibleNavCategory
                category={MATERIALS_CATEGORY}
                getUrlWithScope={getUrlWithScope}
                pathname={location.pathname}
                allowedScopes={allowed}
                userRole={me?.role}
              />
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Management & Admin Section */}
        {visibleManagementItems.length > 0 && (
          <SidebarGroup className="p-1 py-0.5">
            <SidebarGroupLabel className="flex items-center gap-1.5 text-[10px] font-bold tracking-wider text-cyan-600 dark:text-cyan-400 uppercase whitespace-nowrap px-1.5 h-6">
              <span className="size-1.5 rounded-full bg-cyan-600 dark:bg-cyan-400 shrink-0" />
              <span>Management & Admin</span>
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-0.5">
                {visibleManagementItems.map((item) => {
                  const ItemIcon = item.icon
                  return (
                    <SidebarMenuItem key={item.title}>
                      <SidebarMenuButton asChild tooltip={item.title}>
                        <NavLink
                          to={getUrlWithScope(item.url)}
                          className="flex items-center gap-2.5 w-full px-2 py-1.5 rounded-md text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-zinc-800/60 transition-colors"
                        >
                          <ItemIcon className="size-4 shrink-0 text-slate-600 dark:text-slate-400" />
                          <span className="truncate">{item.title}</span>
                        </NavLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>

      <SidebarFooter className="border-t border-slate-200 dark:border-slate-800 p-1.5">
        <SidebarMenu>
          <SidebarMenuItem className="flex items-center gap-1">
            <SidebarMenuButton
              onClick={() => logout().then(() => window.location.assign('/login'))}
              tooltip="Log out"
              className="flex-1 hover:bg-red-50 dark:hover:bg-red-950/50 text-slate-700 dark:text-slate-300 hover:text-red-600 dark:hover:text-red-400 transition-colors rounded-md px-2 py-1.5 text-xs"
            >
              <LogOut className="size-4 text-slate-500 shrink-0" />
              <span className="font-medium">Log out</span>
            </SidebarMenuButton>

            <SidebarMenuButton
              onClick={toggleTheme}
              tooltip={isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
              className="size-7 p-0 flex items-center justify-center hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 transition-colors rounded-md shrink-0"
            >
              {isDark ? (
                <Sun className="size-3.5 text-amber-500 shrink-0" />
              ) : (
                <Moon className="size-3.5 text-slate-600 dark:text-slate-400 shrink-0" />
              )}
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
