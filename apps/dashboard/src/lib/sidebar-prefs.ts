import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import { AS_ME, api } from './api'
import { useAuth } from './AuthContext'
import { useModuleEnabled } from './modules'
import { MODULE_GROUPS, PAGE_ICONS, SECTION_TITLES, sectionOrder, type ModuleGroup, type ModulePage, type NavSection } from './module-map'
import { usePlannedPreview } from './preview'
import { inSandbox } from './sandbox'
import { usePreferences, type Preferences } from './start-mode'

// UX-65 (asked 18 Nov 2026: "their sidebar, and them being able to keep a custom sidebar which they like"): each role
// starts with its own pinned pages ("Your pages", ROLE_PINS) and its sections in its own order (module-map
// SECTION_ORDER); a person can pin and unpin pages, put them in their order, and order or hide the sections. Saved on
// their account (users.sidebar, PUT /me/sidebar), so it follows them to any computer or phone. It changes only what
// the sidebar shows: a page they may not open is never shown even if pinned, and search reaches every page.

/** The sections a person can order or hide (the everyday pages and Settings always show). */
export const ORDERABLE: NavSection[] = ['tasks', 'plan', 'site', 'buy', 'money']

/** Pages that are always at the top of the sidebar, so never pinned. */
export const EVERYDAY = ['/home', '/today', '/reports', '/issues']

/** At most this many pinned pages: past it the pinned list stops being a shortcut. */
// UX-74: 8, so the sidebar never scrolls (everyday rows + pins + All pages fit a laptop screen); everything else is
// one click away in All pages.
export const MAX_PINS = 8

/** Each role's first pinned pages: the ones that role opens most days, in the order of their day. */
export const ROLE_PINS: Record<string, string[]> = {
  OWNER: ['/site/approvals', '/cost', '/accounts/cash-flow', '/accounts/receivables', '/billing/ra-bills', '/billing/variations'],
  ADMIN: ['/site/approvals', '/cost', '/accounts/cash-flow', '/accounts/receivables', '/billing/ra-bills', '/billing/variations'],
  SUPER_ADMIN: ['/site/approvals', '/cost', '/accounts/cash-flow', '/accounts/receivables', '/billing/ra-bills', '/billing/variations'],
  PROJECT_MANAGER: ['/site/approvals', '/materials/requests', '/procurement/pending', '/cost/green-red', '/planning/schedule', '/subcontract/bills'],
  SITE_ENGINEER: ['/materials/requests', '/materials?view=stock', '/labour', '/procurement/pending', '/site-log'],
  FINANCE: ['/finance/expenses', '/finance/vendors', '/accounts/receivables', '/accounts/cash-bank', '/accounts/cash-flow', '/accounts/gst'],
}

export const ROLE_NAMES: Record<string, string> = {
  OWNER: 'owner',
  ADMIN: 'admin',
  SUPER_ADMIN: 'admin',
  PROJECT_MANAGER: 'project manager',
  SITE_ENGINEER: 'site engineer',
  FINANCE: 'finance',
}

export const CUSTOMISE_EVENT = 'mesiri:customise-sidebar'
/** Open "Your sidebar" (components/sidebar-customise.tsx, mounted once in the app layout) from anywhere. */
export function openSidebarCustomise(tab: 'pages' | 'sections' = 'pages') {
  window.dispatchEvent(new CustomEvent(CUSTOMISE_EVENT, { detail: tab }))
}

export type SidebarPrefs = { pins: string[]; order: NavSection[]; hidden: NavSection[] }

/** A page someone can pin: one the sidebar would show them in a section. */
export interface PinnablePage {
  url: string
  /** The name in "Your pages": a page's own name, or "Module · name" when the name alone says little. */
  title: string
  page: ModulePage
  group: ModuleGroup
  section: NavSection
  icon: LucideIcon
}

// A page's name in "Your pages", where its own name says little away from its module.
const PIN_TITLES: Record<string, string> = {
  '/cost': 'Cost overview',
  '/materials/requests': 'Material requests',
  '/subcontract/bills': 'Subcontract bills',
  '/finance/money': 'Money accounts',
  '/finance/settings': 'Finance settings',
  '/materials?view=items': 'Material items',
  '/materials?view=movements': 'Stock movements',
  '/labour?view=teams': 'Labour teams',
  '/equipment/log': 'Machine log',
  '/procurement/returns': 'Supplier returns',
  '/procurement/rates': 'Supplier rates',
}
// Names that need their module to mean anything on their own.
const GENERIC = new Set(['Overview', 'Settings', 'Money', 'Items', 'Requests', 'Movements', 'Teams', 'Bills & checks', 'Daily log', 'Rates', 'Returns', 'Accounts home', 'Machines'])

/** Every page this person's sidebar shows in its sections (the role, the company's modules, the preview switch). */
export function usePinnable(): { pages: PinnablePage[]; byUrl: Map<string, PinnablePage>; role: string } {
  const { me } = useAuth()
  const on = useModuleEnabled()
  const [showPlanned] = usePlannedPreview()
  const role = (me?.role || '').toUpperCase()
  // Not memoised: useModuleEnabled gives a new function each render, and the list is under a hundred pages.
  {
    const pages: PinnablePage[] = []
    const seen = new Set<string>()
    for (const group of MODULE_GROUPS) {
      if (group.section === 'settings' || !on(group.module)) continue
      for (const page of group.pages) {
        const visible = !page.shortcut && (showPlanned || page.status === 'built') && (!page.roles || page.roles.includes(role)) && (!page.module || on(page.module))
        if (!visible || EVERYDAY.includes(page.url) || seen.has(page.url)) continue
        seen.add(page.url)
        const name = page.navTitle ?? page.title
        // The daily group's pages sit in the SITE section (app-sidebar sectionEntries).
        const section: NavSection = group.section === 'daily' ? 'site' : group.section
        pages.push({
          url: page.url,
          title: PIN_TITLES[page.url] ?? (GENERIC.has(name) ? `${group.title} · ${name}` : name),
          page,
          group,
          section,
          icon: PAGE_ICONS[page.url] ?? group.icon,
        })
      }
    }
    return { pages, byUrl: new Map(pages.map((p) => [p.url, p])), role }
  }
}

/** The role's own sidebar, before the person changes anything. */
export function roleDefault(role: string): SidebarPrefs {
  const order = sectionOrder(role).filter((s): s is NavSection => ORDERABLE.includes(s))
  return { pins: ROLE_PINS[role] ?? ROLE_PINS.ADMIN, order, hidden: [] }
}

function complete(order: NavSection[], role: string): NavSection[] {
  // A section left out (a new one, or an old save) keeps its role's place after the person's own.
  const rest = roleDefault(role).order.filter((s) => !order.includes(s))
  return [...order.filter((s) => ORDERABLE.includes(s)), ...rest]
}

const KEY = ['me-preferences']

/**
 * This person's sidebar, and how to change it. `prefs` is what to show (their saved sidebar, else their role's);
 * `custom` says whether they changed it. Each change is shown at once and saved behind it; a failed save puts the
 * last saved sidebar back.
 */
export function useSidebarPrefs() {
  const prefsQ = usePreferences()
  const { me } = useAuth()
  const role = (me?.role || '').toUpperCase()
  const qc = useQueryClient()
  const saved = prefsQ.data?.sidebar ?? null
  const prefs: SidebarPrefs = React.useMemo(() => {
    if (!saved) return roleDefault(role)
    return { pins: saved.pins, order: complete(saved.order as NavSection[], role), hidden: (saved.hidden as NavSection[]).filter((s) => ORDERABLE.includes(s)) }
  }, [saved, role])

  const put = useMutation({
    mutationFn: async (next: SidebarPrefs | null) => {
      const call = (config?: typeof AS_ME) => (next ? api.put('/me/sidebar', next, config) : api.delete('/me/sidebar', config))
      await call()
      // Inside the sample company the sidebar is still the person's own (the same as their start mode, SS-66).
      if (inSandbox()) await call(AS_ME)
    },
    onMutate: async (next) => {
      await qc.cancelQueries({ queryKey: KEY })
      const before = qc.getQueryData<Preferences>(KEY)
      qc.setQueryData<Preferences>(KEY, (old) => (old ? { ...old, sidebar: next } : old))
      return { before }
    },
    onError: (_err, _next, ctx) => {
      if (ctx?.before) qc.setQueryData(KEY, ctx.before)
    },
  })

  const save = React.useCallback((next: SidebarPrefs) => put.mutate({ ...next, pins: next.pins.slice(0, MAX_PINS) }), [put])
  const reset = React.useCallback(() => put.mutate(null), [put])
  const togglePin = React.useCallback(
    (url: string) => {
      const pinned = prefs.pins.includes(url)
      save({ ...prefs, pins: pinned ? prefs.pins.filter((p) => p !== url) : [...prefs.pins, url] })
      return !pinned
    },
    [prefs, save],
  )
  return {
    prefs,
    custom: !!saved,
    ready: prefsQ.isSuccess,
    saving: put.isPending,
    failed: put.isError,
    full: prefs.pins.length >= MAX_PINS,
    save,
    reset,
    togglePin,
    role,
  }
}

export function sectionTitle(s: NavSection): string {
  return SECTION_TITLES[s]
}
