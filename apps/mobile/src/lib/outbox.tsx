import * as React from 'react'
import { AppState, Platform } from 'react-native'
import NetInfo from '@react-native-community/netinfo'
import * as FileSystem from 'expo-file-system/legacy'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError, fileBody } from './api'
import { newKey, saveRecord, sendTap, sendText, sendVoice, type AssistantResponse } from './mesiri'
import { getValue, setValue } from './storage'
import { useSession } from './session'
import { useOnline } from './online'

// MOB-07: nothing said or filled in on site is lost for want of signal. Every voice note, typed message and form
// save goes through this outbox: kept on the phone (the recording copied out of the recorder's cache), sent at once
// when there is signal, else when it comes back (signal returns, the app is opened, every 30 s while waiting).
// Never twice: a voice note or message carries its own id (the assistant's door answers the same id once,
// X-Mesiri-Message-Id) and a form save its idempotency key (the API answers the same key with the first record).
// A queued note's answer, which comes later, waits on Today until it is opened.

export type OutboxKind = 'voice' | 'text' | 'record'
export type OutboxStatus = 'waiting' | 'sending' | 'answered' | 'failed'

export interface OutboxItem {
  /** The message id (voice, text) or the idempotency key (record). */
  id: string
  kind: OutboxKind
  /** Whose it is: only its owner's sign-in sends it. */
  userId: string
  createdAt: number
  /** "Green Villa · Annex": where it was said, for the card on Today. */
  place: string
  /** What it is, for the card: "Voice note 0:14", the typed words, "Materials in: 20 bags Cement". */
  title: string
  status: OutboxStatus
  attempts: number
  nextAt: number
  error?: string
  fileUri?: string
  contentType?: string
  text?: string
  method?: string
  path?: string
  body?: Record<string, unknown>
  removeId?: string | null
  answer?: AssistantResponse
}

export type Sent = { status: 'answered'; answer: AssistantResponse | null } | { status: 'queued' }

const KEY = 'mesiri_app_outbox'
const DIR = FileSystem.documentDirectory ? `${FileSystem.documentDirectory}outbox/` : null
const WEB = Platform.OS === 'web'

/** Worth trying again later: no connection, the server busy or down, signed out, or still being worked on. */
function later(e: unknown): boolean {
  if (!(e instanceof ApiError)) return true
  return e.status === 0 || e.status >= 500 || e.status === 401 || e.status === 409 || e.status === 429 || e.status === 408
}

/** No connection: try again soon (the next chance is usually the signal coming back). */
const NO_SIGNAL_RETRY_MS = 15_000

function backoff(attempts: number): number {
  return Math.min(300_000, 10_000 * 2 ** Math.min(attempts, 5))
}

const noSignal = (e: unknown) => e instanceof ApiError && e.status === 0

async function keepFile(uri: string, id: string): Promise<string> {
  if (WEB || !DIR) return uri // the web build is for looking only: its blob lives as long as the tab
  await FileSystem.makeDirectoryAsync(DIR, { intermediates: true }).catch(() => undefined)
  const to = `${DIR}${id}.m4a`
  await FileSystem.copyAsync({ from: uri, to })
  return to
}

async function dropFile(uri?: string): Promise<void> {
  if (!uri || WEB || !DIR || !uri.startsWith(DIR)) return
  await FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => undefined)
}

interface Outbox {
  items: OutboxItem[]
  /** Waiting or sending (not yet at Mesiri). */
  pending: number
  /** False after a send found no way through (bars but no data happen on site); true after any send got through. */
  reachable: boolean
  sendVoice: (uri: string, contentType: string, seconds: number, place: string) => Promise<Sent>
  sendText: (text: string, place: string) => Promise<Sent>
  saveRecord: (r: { method: string; path: string; body: Record<string, unknown>; key: string; removeId?: string | null; title: string; place: string }) => Promise<Sent>
  retry: (id: string) => void
  dismiss: (id: string) => void
  take: (id: string) => OutboxItem | undefined
}

const Ctx = React.createContext<Outbox | null>(null)

export function OutboxProvider({ children }: { children: React.ReactNode }) {
  const { me, state } = useSession()
  const client = useQueryClient()
  const [items, setItems] = React.useState<OutboxItem[]>([])
  const itemsRef = React.useRef<OutboxItem[]>([])
  const loaded = React.useRef(false)
  const busy = React.useRef(false)
  // The last known connection, kept from NetInfo's events: asking NetInfo.fetch() waits on its reachability check,
  // which with no signal can take seconds (a Save button spinning on site).
  const connected = React.useRef(true)
  const [reachable, setReachable] = React.useState(true)
  const userId = me?.user_id ?? ''

  const commit = React.useCallback((next: OutboxItem[]) => {
    itemsRef.current = next
    setItems(next)
    void setValue(KEY, next)
  }, [])
  const update = React.useCallback(
    (id: string, change: Partial<OutboxItem> | null) => {
      const next = change === null ? itemsRef.current.filter((x) => x.id !== id) : itemsRef.current.map((x) => (x.id === id ? { ...x, ...change } : x))
      commit(next)
    },
    [commit],
  )

  React.useEffect(() => {
    void getValue<OutboxItem[]>(KEY).then((saved) => {
      // A send cut off when the app closed is simply sent again: its id makes that safe.
      const restored = (saved ?? []).map((x) => (x.status === 'sending' ? { ...x, status: 'waiting' as const, nextAt: 0 } : x))
      itemsRef.current = [...restored, ...itemsRef.current]
      setItems(itemsRef.current)
      loaded.current = true
    })
  }, [])

  const refresh = React.useCallback(() => {
    void client.invalidateQueries({ queryKey: ['site-day'] })
    void client.invalidateQueries({ queryKey: ['stock'] })
    void client.invalidateQueries({ queryKey: ['requests'] })
  }, [client])

  /** One try at one item. Answered and saved records leave the list; a later answer stays for Today. */
  const attempt = React.useCallback(
    async (item: OutboxItem, live: boolean): Promise<Sent> => {
      update(item.id, { status: 'sending' })
      try {
        let answer: AssistantResponse | null = null
        if (item.kind === 'voice') {
          answer = await sendVoice(await fileBody(item.fileUri as string), item.contentType ?? 'audio/mp4', item.id)
        } else if (item.kind === 'text') {
          answer = await sendText(item.text as string, item.id)
        } else {
          await saveRecord(item.method as string, item.path as string, item.body ?? {}, item.id)
          if (item.removeId) void sendTap(item.removeId).catch(() => undefined)
        }
        refresh()
        setReachable(true)
        if (live || item.kind === 'record') {
          await dropFile(item.fileUri)
          update(item.id, null)
        } else {
          await dropFile(item.fileUri)
          update(item.id, { status: 'answered', answer: answer ?? undefined, fileUri: undefined })
        }
        return { status: 'answered', answer }
      } catch (e) {
        if (later(e)) {
          const attempts = item.attempts + 1
          if (noSignal(e)) setReachable(false)
          // No signal: soon again. The server busy or refusing for now: wait longer each time.
          update(item.id, { status: 'waiting', attempts, nextAt: Date.now() + (noSignal(e) ? NO_SIGNAL_RETRY_MS : backoff(attempts)) })
          return { status: 'queued' }
        }
        if (live) {
          // Refused while the person is on the screen: they see why there and can say it again; nothing to keep.
          await dropFile(item.fileUri)
          update(item.id, null)
        } else {
          update(item.id, { status: 'failed', error: e instanceof Error ? e.message : String(e) })
        }
        throw e
      }
    },
    [update, refresh],
  )

  const flush = React.useCallback(async () => {
    if (busy.current || !loaded.current || state !== 'signed_in' || !userId) return
    // Only "no connection at all" counts as offline: the reachability check pings a third-party address some
    // networks block, and a try that fails keeps the item anyway.
    if (!connected.current) return
    busy.current = true
    try {
      for (;;) {
        const next = itemsRef.current.find((x) => x.userId === userId && x.status === 'waiting' && x.nextAt <= Date.now())
        if (!next) break
        const sent = await attempt(next, false).catch(() => ({ status: 'failed' as const }))
        if (sent.status === 'queued') break // still no way through: wait for the next chance
      }
    } finally {
      busy.current = false
    }
  }, [attempt, state, userId])

  // Signal back, app opened, and every 30 s while something waits.
  React.useEffect(
    () =>
      NetInfo.addEventListener((s) => {
        const was = connected.current
        connected.current = s.isConnected !== false
        if (connected.current && !was) {
          // Signal is back: everything waiting goes now, whatever wait it was given.
          commit(itemsRef.current.map((x) => (x.status === 'waiting' ? { ...x, nextAt: 0 } : x)))
        }
        if (connected.current) void flush()
      }),
    [flush, commit],
  )
  React.useEffect(() => {
    const sub = AppState.addEventListener('change', (s) => s === 'active' && void flush())
    return () => sub.remove()
  }, [flush])
  React.useEffect(() => {
    void flush()
    const timer = setInterval(() => void flush(), 30_000)
    return () => clearInterval(timer)
  }, [flush])

  /** Keep it, then try it now; the caller waits for the answer only if it can get through now. */
  const submit = React.useCallback(
    async (item: OutboxItem): Promise<Sent> => {
      commit([...itemsRef.current, item])
      if (!connected.current) return { status: 'queued' }
      return attempt(item, true)
    },
    [attempt, commit],
  )

  const base = React.useCallback(
    (kind: OutboxKind, place: string, title: string, id = newKey()): OutboxItem => ({
      id,
      kind,
      userId,
      createdAt: Date.now(),
      place,
      title,
      status: 'waiting',
      attempts: 0,
      nextAt: 0,
    }),
    [userId],
  )

  const value = React.useMemo<Outbox>(
    () => ({
      items: items.filter((x) => x.userId === userId),
      pending: items.filter((x) => x.userId === userId && (x.status === 'waiting' || x.status === 'sending')).length,
      reachable,
      sendVoice: async (uri, contentType, seconds, place) => {
        const item = base('voice', place, `0:${String(Math.round(seconds)).padStart(2, '0')}`)
        return submit({ ...item, fileUri: await keepFile(uri, item.id), contentType })
      },
      sendText: (text, place) => submit({ ...base('text', place, text), text }),
      saveRecord: (r) => submit({ ...base('record', r.place, r.title, r.key), method: r.method, path: r.path, body: r.body, removeId: r.removeId }),
      retry: (id) => {
        update(id, { status: 'waiting', nextAt: 0, error: undefined })
        void flush()
      },
      dismiss: (id) => {
        const item = itemsRef.current.find((x) => x.id === id)
        void dropFile(item?.fileUri)
        update(id, null)
      },
      take: (id) => {
        const item = itemsRef.current.find((x) => x.id === id)
        if (item?.status === 'answered') update(id, null)
        return item
      },
    }),
    [items, userId, reachable, base, submit, update, flush],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useOutbox(): Outbox {
  const value = React.useContext(Ctx)
  if (!value) throw new Error('useOutbox outside OutboxProvider')
  return value
}

/** Whether Mesiri can be reached now: the phone says it is connected and the last send got through. */
export function useSignal(): boolean {
  const online = useOnline()
  const { reachable } = useOutbox()
  return online && reachable
}
