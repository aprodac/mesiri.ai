import { useQuery } from '@tanstack/react-query'
import { api, getToken } from './api'
import { SANDBOX_KEY } from './clock'

// SS-67 (docs/plans/guided-demo-plan.md section 17.2): the person's private sample company ("the sandbox"), made and
// removed by the backend (`GET/POST/DELETE /learn/sandbox`, SS-66b). While the person is in it, every API call goes
// with the sandbox token instead of their own; their own token is never touched, so Leave is just forgetting the
// sandbox token. Kept in sessionStorage: one browser tab is in the sample company, any other tab (and a new one) is
// the real company, so a tab already open on the real company never starts saving into the sample by surprise.
//
// The sandbox token can only reach the sandbox company, and the /learn/sandbox routes refuse it (no sandbox inside a
// sandbox), so those three calls always go with the person's own token (api.ts's request interceptor).

const KEY = SANDBOX_KEY
/** A walkthrough to start once the page has loaded inside the sandbox ("Start the guided project"). */
const START_KEY = 'mesiri_sandbox_start'
/** Why the person was brought back to their own company, said once on the Learn page. */
const ENDED_KEY = 'mesiri_sandbox_ended'

export const SANDBOX_PATH = '/learn/sandbox'

export type SandboxRole = 'ADMIN' | 'PROJECT_MANAGER' | 'SITE_ENGINEER' | 'FINANCE'

export const SANDBOX_ROLES: { value: SandboxRole; label: string; who: string; sees: string }[] = [
  { value: 'ADMIN', label: 'Owner', who: 'you', sees: 'Everything, every project and every rupee' },
  { value: 'PROJECT_MANAGER', label: 'Project manager', who: 'Anil', sees: 'His projects: orders, the BOQ, the team' },
  { value: 'SITE_ENGINEER', label: 'Site engineer', who: 'Ravi', sees: "The site's day; no rupees" },
  { value: 'FINANCE', label: 'Accounts', who: 'Meera', sees: 'Bills, payments, wages and accounts' },
]

export interface SandboxInfo {
  exists: boolean
  organization_id?: string
  name?: string
  expires_at?: string
  created_at?: string
}

export interface SandboxOpened {
  token: string
  expires_at: string
  organization_id: string
  name: string
  role: SandboxRole
  user_name: string
  created: boolean
  /** The sample company's own date (SS-74a): this tab's "today" while in it (lib/clock.ts). */
  today?: string | null
  seeded?: Record<string, number>
  failed?: unknown[]
}

export interface SandboxSession {
  token: string
  /** When the sandbox token stops working (8 hours); after it the tab is back in the real company. */
  expires_at: string
  name: string
  role: SandboxRole
  user_name: string
  /** The sample company's own date (YYYY-MM-DD), read by lib/clock.ts. */
  today?: string | null
  /** The person's own token this was opened under: another login in this tab drops the sandbox. */
  real: string
}

function fingerprint(token: string): string {
  let h = 5381
  for (let i = 0; i < token.length; i++) h = ((h << 5) + h + token.charCodeAt(i)) | 0
  return `${token.length}.${(h >>> 0).toString(36)}`
}

function store(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

/** The sandbox this tab is in, if any: one opened under the person signed in now, and not yet expired. */
export function sandboxSession(): SandboxSession | null {
  const real = getToken()
  if (!real) return null
  try {
    const s = JSON.parse(store()?.getItem(KEY) || 'null') as SandboxSession | null
    if (!s?.token || s.real !== fingerprint(real)) return null
    if (Date.parse(s.expires_at) <= Date.now()) return null
    return s
  } catch {
    return null
  }
}

/** The token API calls go with: the sandbox's while this tab is in one, else the person's own. */
export function activeToken(url: string | undefined): string | null {
  if (url?.startsWith(SANDBOX_PATH)) return getToken()
  return sandboxSession()?.token ?? getToken()
}

export function inSandbox(): boolean {
  return sandboxSession() !== null
}

/** Load the app fresh at `to`: every page's data, the top bar's project and the sign-in are read again, so nothing
 *  from one company is ever shown under the other. */
function reload(to: string) {
  window.location.assign(to)
}

/** Is there a sample company for me? Asked with my own token. A server without the routes yet (before SS-66b is
 *  deployed) answers 404/405: `available` is then false and the Learn page says it is coming. */
export function useSandboxInfo(enabled = true) {
  return useQuery({
    queryKey: ['learn-sandbox'],
    enabled,
    retry: false,
    queryFn: async () => {
      try {
        const res = await api.get<SandboxInfo>(SANDBOX_PATH)
        return { available: true, ...res.data }
      } catch (error) {
        const status = (error as { response?: { status?: number } }).response?.status
        if (status === 404 || status === 405) return { available: false, exists: false } as SandboxInfo & { available: boolean }
        throw error
      }
    },
  })
}

/** Open my sample company (made first if there is none; the first time takes about 10 seconds) as `role`, then load
 *  the app inside it. `start`: a walkthrough to run once it has loaded. */
export async function enterSandbox(role: SandboxRole = 'ADMIN', start?: string, to = '/today', opening = true): Promise<void> {
  const real = getToken()
  if (!real) throw new Error('Sign in first.')
  const res = await api.post<SandboxOpened>(SANDBOX_PATH, { role })
  const d = res.data
  const session: SandboxSession = {
    token: d.token, expires_at: d.expires_at, name: d.name, role: d.role, user_name: d.user_name, today: d.today ?? null,
    real: fingerprint(real),
  }
  const s = store()
  if (!s) throw new Error('This browser blocks storage, so the sample company cannot open here.')
  s.setItem(KEY, JSON.stringify(session))
  if (start) s.setItem(START_KEY, start)
  else s.removeItem(START_KEY)
  if (opening) markOpening({ kind: d.created ? 'new' : 'back', name: d.name })
  reload(to)
}

/** UX-72: the page that loads inside the sample company opens with a scene: a new one with its title sequence (the
 *  company's name, the site at dawn, the cast, Day 1), one opened again with a short "back on site". Read once. */
const OPENING_KEY = 'mesiri_sandbox_opening'
export type SandboxOpening = { kind: 'new' | 'back'; name: string }
/** The opening is on screen now; the guided project waits for it (`whenOpeningDone`). */
let openingOnScreen = false
export const OPENING_DONE_EVENT = 'mesiri:sandbox-opening-done'

function markOpening(o: SandboxOpening) {
  try {
    sessionStorage.setItem(OPENING_KEY, JSON.stringify(o))
  } catch {
    // Storage blocked: the sample company simply opens without its scene.
  }
}

/** Read once: the opening this page load should play, if the person just came into the sample company. */
export function takeOpening(): SandboxOpening | null {
  try {
    const raw = sessionStorage.getItem(OPENING_KEY)
    if (!raw) return null
    sessionStorage.removeItem(OPENING_KEY)
    openingOnScreen = true
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/** The opening has finished (played, skipped, or not played at all). */
export function openingDone() {
  if (!openingOnScreen) return
  openingOnScreen = false
  window.dispatchEvent(new Event(OPENING_DONE_EVENT))
}

/** Run `then` once no opening is waiting or playing (at most `limit` ms later, so nothing ever waits for good). */
export function whenOpeningDone(then: () => void, limit = 25000): () => void {
  let pending = openingOnScreen
  try {
    pending ||= !!sessionStorage.getItem(OPENING_KEY)
  } catch {
    // no storage, no opening
  }
  if (!pending) {
    then()
    return () => {}
  }
  let ran = false
  const go = () => {
    if (ran) return
    ran = true
    window.removeEventListener(OPENING_DONE_EVENT, go)
    window.clearTimeout(t)
    then()
  }
  window.addEventListener(OPENING_DONE_EVENT, go)
  const t = window.setTimeout(go, limit)
  return () => {
    ran = true
    window.removeEventListener(OPENING_DONE_EVENT, go)
    window.clearTimeout(t)
  }
}

function forget() {
  const s = store()
  s?.removeItem(KEY)
  s?.removeItem(START_KEY)
}

/** SS-76: be someone else in the sample company (the same company, another of its people), staying on this page
 *  when that role may open it, else Today. `allowed` says whether a role may open a page (lib/walkthroughs
 *  `pageOpenFor`, passed in so this file keeps no import of the walkthroughs). */
export async function switchSandboxRole(role: SandboxRole, allowed: (url: string, role: string) => boolean): Promise<void> {
  const here = `${window.location.pathname}${window.location.search}`
  await enterSandbox(role, undefined, allowed(here, role) ? here : '/today', false)
}

/** Back to my own company. The sample company stays as it is, to pick up later (D-PG1). */
export function leaveSandbox(to = '/learn') {
  forget()
  reload(to)
}

/** Remove my sample company now (its records go with it), and stay in my own company. */
export async function removeSandbox(): Promise<void> {
  await api.delete(SANDBOX_PATH)
  forget()
}

/** Start again: remove it and make a fresh one, in the same role. */
export async function resetSandbox(role?: SandboxRole): Promise<void> {
  const was = sandboxSession()?.role
  await api.delete(SANDBOX_PATH)
  forget()
  await enterSandbox(role ?? was ?? 'ADMIN')
}

/** The sandbox token was refused (expired, or the sample company is gone): back to the person's own company, never
 *  signed out (their own token is still good). Called by api.ts on a 401 while in a sandbox. */
let ending = false

export function sandboxEnded(): boolean {
  if (ending) return false
  ending = true
  forget()
  store()?.setItem(ENDED_KEY, '1')
  reload('/learn')
  return true
}

/** Switching back to the person's own company is under way (the page is about to load again). */
export function sandboxLeaving(): boolean {
  return ending
}

/** Read once: the sample company's session ended by itself, so the Learn page can say why the person is back. */
export function takeSandboxEnded(): boolean {
  const s = store()
  if (!s?.getItem(ENDED_KEY)) return false
  s.removeItem(ENDED_KEY)
  return true
}

/** The walkthrough waiting to start inside the sandbox, left in place (`takeSandboxStart` uses it up). Read with this
 *  and take it only when it starts: React runs a mount effect twice in development, and a start taken by the first
 *  run, which is then cancelled, would never happen. */
export function peekSandboxStart(): string | null {
  return store()?.getItem(START_KEY) ?? null
}

/** Read once: the walkthrough to start now that the app has loaded inside the sandbox. */
export function takeSandboxStart(): string | null {
  const s = store()
  const id = s?.getItem(START_KEY) ?? null
  if (id) s?.removeItem(START_KEY)
  return id
}

/** A day of the sample company as people say it. Day 0 is the seeded weeks' last day (a Saturday), before the plan's
 *  day 1: "Before day 1", never "Day 0" (20 Nov test). */
export function dayTitle(day: number): string {
  return day <= 0 ? 'Before day 1' : `Day ${day}`
}

/** A day title's size class for the scenes' big type: "Before day 1" is twice as long as "Day 12". */
export function dayTitleSize(day: number, big: string, long: string): string {
  return day <= 0 ? long : big
}

/** The role's name as the banner says it. */
export function sandboxRoleLabel(role: string | undefined): string {
  return SANDBOX_ROLES.find((r) => r.value === role)?.label ?? 'Owner'
}

// --- SS-74e: days pass in the sample company (guided-demo-plan.md section 18) -----------------------------------

/** What the person playing a role has to do (the plan's entries for that role the cast left for them). */
export interface ForYou {
  id: string
  day: number
  what: string
  kind: string
  page: string
  done: boolean
}

export interface SandboxClock {
  day: number
  date: string
  last_day: number
  for_you: ForYou[]
  /** SS-74d: earlier days this sample can go back to (the days the person stood on). */
  can_go_back_to?: { day: number; date: string }[]
}

export interface DaysPassed {
  day: number
  date: string
  token: string
  expires_at: string
  summary: { who: string; kind: string; count: number }[]
  for_you: ForYou[]
  waiting: { id: string; day: number; who: string; what: string }[]
  failed: { id: string; what: string; error: string }[]
  /** UX-71: the days' notable moments, for the "a day passes" scene (in plan order). */
  highlights?: { day: number; who: string; kind: string; what: string }[]
  /** UX-71: on handover, the whole run's totals for the end credits. */
  finale?: { days: number; entries: number; by_kind: Record<string, number> } | null
}

/** UX-71: the page loads again after a scene; it opens through an iris, then the briefing (or the credits). */
const SCENE_KEY = 'mesiri_sandbox_scene'
export type SceneArrival = { kind: 'day' | 'back'; day: number; date: string }

function markArrival(a: SceneArrival) {
  try {
    sessionStorage.setItem(SCENE_KEY, JSON.stringify(a))
  } catch {
    // Storage blocked: the page simply loads without the reveal.
  }
}

/** Read once: the scene the page should open with, if it was just reloaded by one. */
export function takeArrival(): SceneArrival | null {
  try {
    const raw = sessionStorage.getItem(SCENE_KEY)
    if (!raw) return null
    sessionStorage.removeItem(SCENE_KEY)
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/** Shown once after the page loads again: what happened while days passed. */
const AWAY_KEY = 'mesiri_sandbox_away'
/** This tab re-opened itself because another tab moved the days on: once per date, never a loop. */
const CAUGHT_UP_KEY = 'mesiri_sandbox_caught_up'

/** Where my sample company's days are, for the role this tab plays. Asked with my own token (/learn/sandbox).
 *  A 409 (a sample made before days could pass) comes back as `old: true`. */
export function useSandboxClock() {
  const session = sandboxSession()
  return useQuery({
    queryKey: ['learn-sandbox-clock', session?.role, session?.today],
    enabled: !!session,
    retry: false,
    queryFn: async (): Promise<SandboxClock & { old?: boolean }> => {
      try {
        return (await api.get<SandboxClock>(`${SANDBOX_PATH}/clock`, { params: { role: session?.role } })).data
      } catch (error) {
        if ((error as { response?: { status?: number } }).response?.status === 409) {
          return { day: 0, date: session?.today ?? '', last_day: 0, for_you: [], old: true }
        }
        throw error
      }
    },
  })
}

/** Days pass (1..7): the cast plays them; this tab takes the new token (its date moved) and loads the page again, so
 *  every page shows the new day. What happened is kept to say once ("While you were away"). */
export async function passDays(days: number, beforeReload?: (d: DaysPassed) => Promise<void>): Promise<void> {
  const s = store()
  const session = sandboxSession()
  if (!s || !session) throw new Error('Open your sample company first.')
  const res = await api.post<DaysPassed>(`${SANDBOX_PATH}/next-day`, { days, role: session.role })
  const d = res.data
  s.setItem(KEY, JSON.stringify({ ...session, token: d.token, expires_at: d.expires_at, today: d.date }))
  s.setItem(AWAY_KEY, JSON.stringify({ from: d.day - days, ...d, token: undefined }))
  // UX-71: the scene finishes telling the days (it was showing while the cast played them), then the page opens on
  // the new day through an iris.
  if (beforeReload) await beforeReload(d)
  markArrival({ kind: 'day', day: d.day, date: d.date })
  reload(`${window.location.pathname}${window.location.search}`)
}

/** Read once: what happened in the days that just passed. */
export function takeDaysPassed(): (Omit<DaysPassed, 'token'> & { from: number }) | null {
  const s = store()
  const raw = s?.getItem(AWAY_KEY)
  if (!raw) return null
  s?.removeItem(AWAY_KEY)
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/** Another tab moved the days on: open the sample again here (its token then carries the current date), once. */
export async function catchUp(date: string): Promise<void> {
  const s = store()
  const session = sandboxSession()
  if (!s || !session || s.getItem(CAUGHT_UP_KEY) === date) return
  s.setItem(CAUGHT_UP_KEY, date)
  await enterSandbox(session.role, undefined, `${window.location.pathname}${window.location.search}`)
}

/** SS-74d: back to an earlier day (a save point): the sample company exactly as it was then; the days after it are
 *  gone. This tab takes the new token (that day's date) and loads the page again. */
export async function goBackTo(day: number, beforeReload?: (d: DaysPassed) => Promise<void>): Promise<void> {
  const s = store()
  const session = sandboxSession()
  if (!s || !session) throw new Error('Open your sample company first.')
  const res = await api.post<DaysPassed>(`${SANDBOX_PATH}/go-back`, { day, role: session.role })
  const d = res.data
  s.setItem(KEY, JSON.stringify({ ...session, token: d.token, expires_at: d.expires_at, today: d.date }))
  s.removeItem(AWAY_KEY)
  if (beforeReload) await beforeReload(d)
  markArrival({ kind: 'back', day: d.day, date: d.date })
  reload(`${window.location.pathname}${window.location.search}`)
}


// -- The guided project plays the story's days (21 Nov 2026: "fill its gaps"): each chapter on its own story day ----

const TARGET_KEY = 'mesiri_sandbox_target'
export const PLAY_TO_EVENT = 'mesiri:sandbox-play-to'
export const SCENE_BUSY_EVENT = 'mesiri:sandbox-scene-busy'
let sceneBusy = false

/** The day the guided project asked the sample company to reach, kept across the reloads days passing make. */
export function sandboxTarget(): number | null {
  const n = Number(store()?.getItem(TARGET_KEY) ?? '')
  return Number.isFinite(n) && n > 0 ? n : null
}

export function clearSandboxTarget() {
  store()?.removeItem(TARGET_KEY)
}

/** Play the days up to `day` (never back): the clock plays them a week at a time with its own scenes, then the
 *  morning briefing of that day. */
export function playToDay(day: number) {
  store()?.setItem(TARGET_KEY, String(day))
  window.dispatchEvent(new CustomEvent(PLAY_TO_EVENT, { detail: day }))
}

/** A scene or the morning briefing is on screen: the guided project waits under it. */
export function setSandboxSceneBusy(busy: boolean) {
  if (busy === sceneBusy) return
  sceneBusy = busy
  window.dispatchEvent(new CustomEvent(SCENE_BUSY_EVENT, { detail: busy }))
}

export function sandboxSceneBusy(): boolean {
  return sceneBusy || sandboxTarget() !== null
}
