import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  Clock,
  FileText,
  Image as ImageIcon,
  MapPin,
  MessageSquare,
  Mic,
  RefreshCw,
  Search,
  UserPlus,
  Video,
} from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Segmented } from '@/components/dpr-page'
import { cn, timeAgo } from '@/lib/utils'
import { useUrlState } from '@/lib/url-state'
import { roleLabel } from '@/lib/permissions'
import { initials } from '@/lib/team'
import { fetchConversations, fetchConversationMessages, type Conversation, type CompanyMessage } from '@/lib/api'

// WEB-35: the chat screen redone. A list of people and their thread, like
// WhatsApp itself: the person's messages on the left, Mesiri's replies on
// the right, a line per day, the site each update was filed to, and a plain
// sentence when Mesiri could not handle one. The guessed "intent" badges
// (a keyword match on the preview, often wrong) and the side panel are gone;
// who the person is sits in the thread header with a link to their Team
// page. On phones the list and the thread are one screen each.

type Filter = 'all' | 'failed' | 'unknown'

/** "919800000002" → "+91 98000 00002"; other numbers get a "+". */
function phone(waId: string): string {
  const d = waId.replace(/\D/g, '')
  if (d.length === 12 && d.startsWith('91')) return `+91 ${d.slice(2, 7)} ${d.slice(7)}`
  return d ? `+${d}` : waId
}

function nameOf(c: Conversation): string {
  return c.member?.full_name || phone(c.sender_wa_id)
}

const failed = (c: { error_code?: string | null; processing_status?: string | null }) =>
  Boolean(c.error_code) || c.processing_status === 'failed'

// What went wrong, in words. The code stays in the tooltip for support.
const ERROR_WORDS: Record<string, string> = {
  AI_UNAVAILABLE: 'Mesiri was busy and could not read this. Ask them to send it again.',
  TRANSCRIPTION_FAILED: 'This voice note could not be understood. Ask them to type it.',
  VALIDATION_ERROR: 'Mesiri could not read this message.',
}
const errorWords = (code: string | null | undefined) => (code && ERROR_WORDS[code]) || 'Mesiri could not handle this message.'

const MEDIA: Record<string, { label: string; Icon: React.ElementType }> = {
  image: { label: 'Photo', Icon: ImageIcon },
  audio: { label: 'Voice note', Icon: Mic },
  voice: { label: 'Voice note', Icon: Mic },
  video: { label: 'Video', Icon: Video },
  document: { label: 'Document', Icon: FileText },
  location: { label: 'Location', Icon: MapPin },
}

const time = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

function dayLabel(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date()
  yesterday.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}

// ─── List ────────────────────────────────────────────────────────────────────

function ConversationRow({ c, active, onClick }: { c: Conversation; active: boolean; onClick: () => void }) {
  const bad = failed(c)
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        aria-current={active || undefined}
        className={cn('flex w-full items-start gap-3 px-3 py-2.5 text-left', active ? 'bg-muted' : 'hover:bg-muted/50')}
      >
        <span
          className={cn(
            'flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
            c.member ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
          )}
          aria-hidden="true"
        >
          {c.member ? initials(c.member.full_name) : <MessageSquare className="size-4" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{nameOf(c)}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{timeAgo(c.last_activity)}</span>
          </span>
          <span className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            {bad && <AlertCircle className="size-3.5 shrink-0 text-destructive" aria-label="Not handled" />}
            <span className="truncate">
              {c.last_direction === 'outbound' && <span className="font-medium text-foreground/70">Mesiri: </span>}
              {c.last_message_preview || 'No text'}
            </span>
          </span>
          {!c.member && <span className="mt-1 inline-block text-xs font-medium text-draft">Not on your team</span>}
        </span>
      </button>
    </li>
  )
}

// ─── Thread ──────────────────────────────────────────────────────────────────

function Bubble({ m }: { m: CompanyMessage }) {
  const mine = m.direction === 'outbound'
  const bad = !mine && (Boolean(m.error_code) || m.processing_status === 'failed')
  const waiting = !mine && (m.processing_status === 'pending' || m.processing_status === 'processing')
  const media = !m.body ? MEDIA[m.message_type] : undefined
  return (
    <div className={cn('flex flex-col', mine ? 'items-end' : 'items-start')}>
      <div
        className={cn(
          'max-w-[85%] rounded-xl border px-3 py-2 text-sm sm:max-w-[70%]',
          mine
            ? 'rounded-br-sm border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/50'
            : 'rounded-bl-sm bg-background',
          bad && 'border-destructive/40',
        )}
      >
        {mine && <p className="mb-0.5 text-xs font-semibold text-emerald-700 dark:text-emerald-400">Mesiri</p>}
        {media ? (
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <media.Icon className="size-4" aria-hidden="true" /> {media.label}
          </span>
        ) : (
          <p className="whitespace-pre-wrap break-words">{m.body || <span className="text-muted-foreground">No text</span>}</p>
        )}
        <p className="mt-1 flex items-center justify-end gap-2 text-[11px] text-muted-foreground">
          {!mine && m.site_name && (
            <span className="inline-flex min-w-0 items-center gap-0.5 truncate">
              <MapPin className="size-3 shrink-0" aria-hidden="true" />
              {m.site_name}
            </span>
          )}
          <span className="shrink-0 tabular-nums">{time(m.timestamp)}</span>
        </p>
      </div>
      {bad && (
        <p className="mt-1 flex max-w-[85%] items-start gap-1 text-xs text-destructive sm:max-w-[70%]" title={m.error_code ?? undefined}>
          <AlertCircle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          {errorWords(m.error_code)}
        </p>
      )}
      {waiting && (
        <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="size-3.5" aria-hidden="true" /> Mesiri hasn't replied yet
        </p>
      )}
    </div>
  )
}

function Thread({ c, onBack }: { c: Conversation; onBack: () => void }) {
  const endRef = React.useRef<HTMLDivElement>(null)
  const { data: messages, isLoading, isError, refetch } = useQuery({
    queryKey: ['whatsapp-conversation-messages', c.sender_wa_id],
    queryFn: () => fetchConversationMessages(c.sender_wa_id),
    refetchInterval: 15_000,
  })
  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, c.sender_wa_id])

  const days = React.useMemo(() => {
    const out: { label: string; items: CompanyMessage[] }[] = []
    for (const m of messages ?? []) {
      const label = dayLabel(m.timestamp)
      if (out.at(-1)?.label === label) out.at(-1)!.items.push(m)
      else out.push({ label, items: [m] })
    }
    return out
  }, [messages])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b px-3 py-2.5 sm:px-5">
        <Button variant="ghost" size="icon" className="-ml-1 size-8 sm:hidden" onClick={onBack} aria-label="Back to conversations">
          <ArrowLeft className="size-4" />
        </Button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{nameOf(c)}</p>
          <p className="truncate text-xs text-muted-foreground">
            {c.member ? (
              <>
                {roleLabel(c.member.role)} · <span className="tabular-nums">{phone(c.sender_wa_id)}</span>
              </>
            ) : (
              'Not on your team'
            )}
          </p>
        </div>
        {c.member ? (
          <Button asChild variant="outline" size="sm" className="shrink-0">
            <Link to={`/team/${c.member.id}`}>Profile</Link>
          </Button>
        ) : (
          <Button asChild variant="outline" size="sm" className="shrink-0 gap-1.5">
            <Link to="/team">
              <UserPlus className="size-3.5" /> <span className="hidden sm:inline">Add to team</span>
              <span className="sm:hidden">Add</span>
            </Link>
          </Button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto bg-muted/30">
        {isLoading ? (
          <div className="flex flex-col gap-3 p-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className={cn('h-12 rounded-xl', i % 2 ? 'w-48 self-end' : 'w-64')} />
            ))}
          </div>
        ) : isError ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm">
            <p>The messages could not be loaded.</p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Try again
            </Button>
          </div>
        ) : days.length === 0 ? (
          <p className="p-10 text-center text-sm text-muted-foreground">No messages yet.</p>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-2 px-3 py-4 sm:px-6">
            {!c.member && (
              <p className="mb-2 rounded-lg border border-draft/30 bg-draft/5 px-3 py-2 text-xs">
                This number isn't on your team, so Mesiri can't file what it sends. Add them in Team with this WhatsApp number.
              </p>
            )}
            {days.map((d) => (
              <React.Fragment key={d.label}>
                <p className="my-2 self-center rounded-full border bg-background px-2.5 py-0.5 text-xs text-muted-foreground">{d.label}</p>
                {d.items.map((m) => (
                  <Bubble key={`${m.id}-${m.direction}`} m={m} />
                ))}
              </React.Fragment>
            ))}
            <div ref={endRef} />
          </div>
        )}
      </div>

      <p className="shrink-0 border-t px-4 py-2 text-center text-xs text-muted-foreground">
        Read only. Mesiri answers on WhatsApp by itself.
      </p>
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function WhatsAppInboxPage({ embedded = false }: { embedded?: boolean } = {}) {
  const [search, setSearch] = React.useState('')
  const [filter, setFilter] = React.useState<Filter>('all')
  // The open conversation is in the address (?with=<number>), so a link can
  // open someone's thread and Back on a phone returns to the list.
  const [selected, setSelected] = useUrlState<string>('with', '')

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['whatsapp-conversations', search],
    queryFn: () => fetchConversations({ search: search || undefined, limit: 100 }),
    refetchInterval: 30_000,
  })
  const all = React.useMemo(() => data?.items ?? [], [data])
  const failedCount = all.filter(failed).length
  const unknownCount = all.filter((c) => !c.member).length
  const shown = filter === 'failed' ? all.filter(failed) : filter === 'unknown' ? all.filter((c) => !c.member) : all

  // Wide screens open the newest thread; phones start on the list.
  React.useEffect(() => {
    if (!selected && all.length > 0 && window.matchMedia('(min-width: 640px)').matches) setSelected(all[0].sender_wa_id)
  }, [all, selected, setSelected])

  const current = all.find((c) => c.sender_wa_id === selected) ?? null

  return (
    <div className={embedded ? 'flex min-h-0 flex-1' : '-m-4 flex h-[calc(100vh-57px)] min-h-0'}>
      <aside className={cn('min-h-0 w-full shrink-0 flex-col border-r sm:flex sm:w-[300px] xl:w-[340px]', current ? 'hidden' : 'flex')}>
        <div className="flex shrink-0 flex-col gap-2 border-b p-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or number" className="h-9 pl-8" aria-label="Search" />
            </div>
            <Button variant="ghost" size="icon" className="size-9" onClick={() => refetch()} disabled={isFetching} aria-label="Refresh">
              <RefreshCw className={cn('size-4', isFetching && 'animate-spin')} />
            </Button>
          </div>
          <Segmented<Filter>
            label="Show"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: 'All', count: all.length },
              { value: 'failed', label: 'Not handled', count: failedCount },
              { value: 'unknown', label: 'Not on team', count: unknownCount },
            ]}
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex flex-col gap-3 p-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : isError ? (
            <div className="flex flex-col items-center gap-2 p-6 text-center text-sm">
              <p>Conversations could not be loaded.</p>
              <Button variant="outline" size="sm" onClick={() => refetch()}>
                Try again
              </Button>
            </div>
          ) : shown.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">
              {search ? 'No one matches.' : filter === 'all' ? 'No WhatsApp messages yet.' : 'None right now.'}
            </p>
          ) : (
            <ul className="divide-y">
              {shown.map((c) => (
                <ConversationRow key={c.sender_wa_id} c={c} active={c.sender_wa_id === selected} onClick={() => setSelected(c.sender_wa_id)} />
              ))}
            </ul>
          )}
        </div>
      </aside>

      <section className={cn('min-h-0 min-w-0 flex-1 flex-col', current ? 'flex' : 'hidden sm:flex')}>
        {current ? (
          <Thread key={current.sender_wa_id} c={current} onBack={() => setSelected('')} />
        ) : (
          <div className="flex flex-1 items-center justify-center bg-muted/30 p-6 text-center text-sm text-muted-foreground">
            {isLoading ? '' : 'Pick a conversation.'}
          </div>
        )}
      </section>
    </div>
  )
}
