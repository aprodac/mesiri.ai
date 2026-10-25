import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Search,
  MessageSquare,
  AlertCircle,
  Bot,
  Check,
  CheckCheck,
  RefreshCw,
  Phone,
  User,
  Clock,
  Info,
  HardHat,
  Receipt,
  Package,
  ClipboardCheck,
} from 'lucide-react'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn, timeAgo } from '@/lib/utils'
import {
  fetchConversations,
  fetchConversationMessages,
  type Conversation,
  type CompanyMessage,
} from '@/lib/api'

// ─── Helpers ────────────────────────────────────────────────────────────────

function initialsFor(name: string | null | undefined, waId: string): string {
  if (name && name.trim()) {
    const parts = name.trim().split(/\s+/)
    return (parts[0][0] + (parts[1]?.[0] ?? '')).toUpperCase()
  }
  return waId.slice(-2)
}

function displayNameFor(conversation: Conversation): string {
  return conversation.member?.full_name ?? conversation.sender_wa_id
}

function formatFullTimestamp(dateString: string): string {
  return new Date(dateString).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

// Detect AI intent from message preview text
type IntentType = 'expense' | 'labour' | 'materials' | 'attendance' | null
function detectIntent(preview: string | null | undefined): IntentType {
  if (!preview) return null
  const p = preview.toLowerCase()
  if (p.match(/expense|paid|payment|bill|vendor|invoice|receipt/)) return 'expense'
  if (p.match(/attendance|headcount|workers|labour|wage|mason|helper|carpenter/)) return 'labour'
  if (p.match(/material|cement|steel|sand|brick|aggregate|tiles/)) return 'materials'
  if (p.match(/attendance|report|site log|daily report/)) return 'attendance'
  return null
}

const INTENT_CONFIG: Record<NonNullable<IntentType>, { label: string; className: string; Icon: React.ElementType }> = {
  expense: {
    label: 'Expense',
    className: 'border-amber-500/30 text-amber-600 bg-amber-500/10 dark:text-amber-400',
    Icon: Receipt,
  },
  labour: {
    label: 'Labour',
    className: 'border-[#008069]/30 text-[#008069] bg-[#008069]/10 text-[#008069]',
    Icon: HardHat,
  },
  materials: {
    label: 'Materials',
    className: 'border-blue-500/30 text-blue-600 bg-blue-500/10 dark:text-blue-400',
    Icon: Package,
  },
  attendance: {
    label: 'Attendance',
    className: 'border-purple-500/30 text-purple-600 bg-purple-500/10 dark:text-purple-400',
    Icon: ClipboardCheck,
  },
}

// ─── Skeleton Loaders ────────────────────────────────────────────────────────

function ConversationListSkeleton() {
  return (
    <div className="flex flex-col gap-1 p-2">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 px-3 py-2.5">
          <Skeleton className="size-10 rounded-full shrink-0" />
          <div className="flex-1 min-w-0 flex flex-col gap-1.5">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-4/5" />
          </div>
        </div>
      ))}
    </div>
  )
}

function ThreadSkeleton() {
  return (
    <div className="flex flex-col gap-4 p-6">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className={cn('flex', i % 2 === 0 ? 'justify-start' : 'justify-end')}>
          <Skeleton className={cn('h-10 rounded-2xl', i % 2 === 0 ? 'w-56' : 'w-40')} />
        </div>
      ))}
    </div>
  )
}

// ─── Conversation Row ────────────────────────────────────────────────────────

function ConversationRow({
  conversation,
  isActive,
  onClick,
}: {
  conversation: Conversation
  isActive: boolean
  onClick: () => void
}) {
  const name = displayNameFor(conversation)
  const hasError = Boolean(conversation.error_code)
  const isUnmapped = !conversation.member
  const intent = detectIntent(conversation.last_message_preview)
  const intentConfig = intent ? INTENT_CONFIG[intent] : null

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-all',
        isActive
          ? 'bg-[#008069]/10 dark:bg-[#008069]/15 border border-[#008069]/20'
          : 'hover:bg-muted/60 border border-transparent',
        hasError && !isActive && 'border-l-2 border-l-rose-500/60 bg-rose-500/5 dark:bg-rose-500/5 rounded-l-none'
      )}
    >
      {/* Avatar */}
      <Avatar className="size-10 shrink-0">
        <AvatarFallback
          className={cn(
            'text-xs font-bold ring-2',
            isActive
              ? 'bg-[#008069] text-white ring-[#008069]/30'
              : hasError
              ? 'bg-rose-100 dark:bg-rose-950 text-rose-600 dark:text-rose-400 ring-rose-500/20'
              : 'bg-muted text-muted-foreground ring-border'
          )}
        >
          {initialsFor(conversation.member?.full_name, conversation.sender_wa_id)}
        </AvatarFallback>
      </Avatar>

      <div className="flex-1 min-w-0">
        {/* Name + timestamp */}
        <div className="flex items-center justify-between gap-2">
          <span
            className={cn(
              'text-sm truncate font-semibold',
              isActive ? 'text-foreground' : 'text-foreground/90'
            )}
          >
            {name}
          </span>
          <span className="text-[10px] text-muted-foreground shrink-0 font-mono">
            {timeAgo(conversation.last_activity)}
          </span>
        </div>

        {/* Message preview */}
        <div className="flex items-center gap-1 mt-0.5">
          {conversation.last_direction === 'outbound' && (
            <Bot className="size-3 text-[#008069] shrink-0" />
          )}
          <p className="text-xs text-muted-foreground truncate">
            {conversation.last_message_preview || 'No message content'}
          </p>
        </div>

        {/* Badge row */}
        <div className="flex items-center gap-1.5 mt-1 flex-wrap">
          {intentConfig && (
            <Badge variant="outline" className={cn('text-[9px] px-1.5 py-0 h-4 font-semibold gap-0.5', intentConfig.className)}>
              <intentConfig.Icon className="size-2.5" />
              {intentConfig.label}
            </Badge>
          )}
          {isUnmapped && (
            <Badge variant="outline" className="text-[9px] px-1.5 py-0 h-4 font-semibold text-amber-600 border-amber-500/30 bg-amber-500/10">
              Unmapped
            </Badge>
          )}
          {hasError && (
            <Badge variant="outline" className="text-[9px] px-1.5 py-0 h-4 font-semibold gap-0.5 text-rose-600 border-rose-500/30 bg-rose-500/10">
              <AlertCircle className="size-2.5" />
              Error
            </Badge>
          )}
        </div>
      </div>
    </button>
  )
}

// ─── Message Bubble ──────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: CompanyMessage }) {
  const isOutbound = message.direction === 'outbound'
  const hasError = Boolean(message.error_code)

  return (
    <div className={cn('flex w-full', isOutbound ? 'justify-end' : 'justify-start')}>
      {/* Inbound: small bot avatar */}
      {!isOutbound && (
        <div className="size-7 rounded-full bg-[#008069]/15 border border-[#008069]/20 flex items-center justify-center shrink-0 mr-2 mt-1">
          <Bot className="size-3.5 text-[#008069]" />
        </div>
      )}

      <div className={cn('flex flex-col max-w-[68%]', isOutbound ? 'items-end' : 'items-start')}>
        <div
          className={cn(
            'rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap break-words shadow-sm',
            isOutbound
              ? 'bg-[#008069] text-white rounded-br-sm'
              : 'bg-card border border-border text-foreground rounded-bl-sm',
            hasError && 'ring-1 ring-rose-500/50'
          )}
        >
          {isOutbound && (
            <div className="flex items-center gap-1 mb-1 opacity-70">
              <Bot className="size-3" />
              <span className="text-[10px] font-semibold uppercase tracking-wide">Mesiri AI</span>
            </div>
          )}
          {message.body || <span className="italic opacity-60">No text content</span>}
        </div>

        <div className="flex items-center gap-1.5 mt-1 px-1">
          <span className="text-[10px] text-muted-foreground font-mono">
            {formatFullTimestamp(message.timestamp)}
          </span>
          {isOutbound && !hasError && (
            <CheckCheck className="size-3 text-[#008069]" />
          )}
          {hasError && (
            <>
              <AlertCircle className="size-3 text-rose-500" />
              <span className="text-[10px] text-rose-500 font-medium">{message.error_code}</span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Contact Metadata Panel ──────────────────────────────────────────────────

function ContactMetadataPanel({ conversation }: { conversation: Conversation }) {
  const name = displayNameFor(conversation)
  const hasError = Boolean(conversation.error_code)

  return (
    <div className="w-60 shrink-0 border-l border-border flex flex-col bg-card/60 hidden lg:flex">
      {/* Header */}
      <div className="px-4 py-3 border-b bg-muted/20 shrink-0">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          <Info className="size-3" />
          Contact Info
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Avatar + Name */}
        <div className="flex flex-col items-center gap-2 py-2">
          <Avatar className="size-14">
            <AvatarFallback className="text-base font-bold bg-[#008069] text-white ring-2 ring-[#008069]/30">
              {initialsFor(conversation.member?.full_name, conversation.sender_wa_id)}
            </AvatarFallback>
          </Avatar>
          <div className="text-center">
            <p className="text-sm font-bold text-foreground">{name}</p>
            {conversation.member?.role && (
              <Badge variant="outline" className="mt-1 text-[10px] font-semibold border-[#008069]/30 text-[#008069] bg-[#008069]/10">
                {conversation.member.role}
              </Badge>
            )}
          </div>
        </div>

        {/* Details */}
        <div className="space-y-2.5 border-t pt-3">
          <div className="flex items-start gap-2">
            <Phone className="size-3.5 text-muted-foreground shrink-0 mt-0.5" />
            <div>
              <p className="text-[10px] text-muted-foreground font-medium uppercase">WhatsApp Number</p>
              <p className="text-xs font-mono text-foreground">{conversation.sender_wa_id}</p>
            </div>
          </div>

          <div className="flex items-start gap-2">
            <User className="size-3.5 text-muted-foreground shrink-0 mt-0.5" />
            <div>
              <p className="text-[10px] text-muted-foreground font-medium uppercase">Member Status</p>
              <p className="text-xs font-semibold text-foreground">
                {conversation.member ? 'Mapped & Active' : 'Unmapped Number'}
              </p>
            </div>
          </div>

          <div className="flex items-start gap-2">
            <Clock className="size-3.5 text-muted-foreground shrink-0 mt-0.5" />
            <div>
              <p className="text-[10px] text-muted-foreground font-medium uppercase">Last Activity</p>
              <p className="text-xs text-foreground">{timeAgo(conversation.last_activity)}</p>
            </div>
          </div>

          {hasError && (
            <div className="flex items-start gap-2 p-2 rounded-lg bg-rose-500/10 border border-rose-500/20">
              <AlertCircle className="size-3.5 text-rose-500 shrink-0 mt-0.5" />
              <div>
                <p className="text-[10px] text-rose-600 font-semibold uppercase">Error Detected</p>
                <p className="text-xs text-rose-600 font-mono">{conversation.error_code}</p>
              </div>
            </div>
          )}
        </div>

        {/* Intent Detection */}
        {(() => {
          const intent = detectIntent(conversation.last_message_preview)
          const cfg = intent ? INTENT_CONFIG[intent] : null
          if (!cfg) return null
          return (
            <div className="border-t pt-3">
              <p className="text-[10px] text-muted-foreground font-medium uppercase mb-2">Last Intent Detected</p>
              <Badge variant="outline" className={cn('text-[10px] font-semibold gap-1', cfg.className)}>
                <cfg.Icon className="size-3" />
                {cfg.label}
              </Badge>
            </div>
          )
        })()}
      </div>
    </div>
  )
}

// ─── Main Page ───────────────────────────────────────────────────────────────

type FilterTab = 'all' | 'errors' | 'unmapped'

export default function WhatsAppInboxPage({ embedded = false }: { embedded?: boolean } = {}) {
  const [search, setSearch] = React.useState('')
  const [selectedWaId, setSelectedWaId] = React.useState<string | null>(null)
  const [filterTab, setFilterTab] = React.useState<FilterTab>('all')
  const threadEndRef = React.useRef<HTMLDivElement>(null)

  const {
    data: conversationsData,
    isLoading: isConversationsLoading,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['whatsapp-conversations', search],
    queryFn: () => fetchConversations({ search: search || undefined, limit: 100 }),
    refetchInterval: 30_000,
  })

  const allConversations = conversationsData?.items ?? []

  // Apply filter tab
  const conversations = React.useMemo(() => {
    if (filterTab === 'errors') return allConversations.filter((c) => Boolean(c.error_code))
    if (filterTab === 'unmapped') return allConversations.filter((c) => !c.member)
    return allConversations
  }, [allConversations, filterTab])

  const errorCount = allConversations.filter((c) => Boolean(c.error_code)).length
  const unmappedCount = allConversations.filter((c) => !c.member).length

  React.useEffect(() => {
    if (!selectedWaId && conversations.length > 0) {
      setSelectedWaId(conversations[0].sender_wa_id)
    }
  }, [conversations, selectedWaId])

  const selectedConversation = allConversations.find((c) => c.sender_wa_id === selectedWaId) ?? null

  const { data: messages, isLoading: isMessagesLoading } = useQuery({
    queryKey: ['whatsapp-conversation-messages', selectedWaId],
    queryFn: () => fetchConversationMessages(selectedWaId as string),
    enabled: Boolean(selectedWaId),
    refetchInterval: 15_000,
  })

  React.useEffect(() => {
    threadEndRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, selectedWaId])

  return (
    <div className={embedded ? 'flex min-h-0 flex-1 flex-col' : 'flex flex-col h-[calc(100vh-57px)] min-h-0 -m-4'}>

      {/* ── Top Header Bar (the WhatsApp page has its own) ───── */}
      {!embedded && (
      <div className="px-5 py-3.5 border-b shrink-0 flex items-center justify-between gap-4 bg-card">
        <div className="flex items-center gap-3">
          <div className="size-9 rounded-lg bg-[#008069]/10 border border-[#008069]/30 flex items-center justify-center shrink-0">
            <MessageSquare className="size-4 text-[#008069]" />
          </div>
          <div>
            <h1 className="text-base font-bold text-foreground flex items-center gap-2">
              WhatsApp Inbox
              <Badge variant="outline" className="text-[10px] font-mono border-[#008069]/30 text-[#008069]">
                {allConversations.length} Conversations
              </Badge>
            </h1>
            <p className="text-xs text-muted-foreground">
              Every site supervisor's conversation, monitored by Mesiri AI
            </p>
          </div>
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
          className="h-8 gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className={cn('size-3.5', isFetching && 'animate-spin')} />
          Refresh
        </Button>
      </div>
      )}

      {/* ── Body ─────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">

        {/* ── Conversation List ─────────────────────────────── */}
        <div className="w-[300px] xl:w-[320px] shrink-0 border-r border-border flex flex-col min-h-0 bg-card">

          {/* Search */}
          <div className="p-2.5 border-b shrink-0">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search name or number..."
                className="pl-8 h-9 text-xs"
              />
            </div>
          </div>

          {/* Filter Tabs */}
          <div className="px-2.5 py-2 border-b shrink-0">
            <Tabs value={filterTab} onValueChange={(v) => setFilterTab(v as FilterTab)}>
              <TabsList className="w-full h-8 text-xs bg-muted/60 p-0.5 grid grid-cols-3">
                <TabsTrigger value="all" className="text-[11px] h-full">
                  All
                  <span className="ml-1 font-mono text-[9px] bg-muted-foreground/20 px-1 rounded">{allConversations.length}</span>
                </TabsTrigger>
                <TabsTrigger value="errors" className="text-[11px] h-full">
                  Errors
                  {errorCount > 0 && <span className="ml-1 font-mono text-[9px] bg-rose-500/20 text-rose-600 px-1 rounded">{errorCount}</span>}
                </TabsTrigger>
                <TabsTrigger value="unmapped" className="text-[11px] h-full">
                  Unmapped
                  {unmappedCount > 0 && <span className="ml-1 font-mono text-[9px] bg-amber-500/20 text-amber-600 px-1 rounded">{unmappedCount}</span>}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          {/* Conversation list body */}
          <div className="flex-1 overflow-y-auto">
            {isConversationsLoading ? (
              <ConversationListSkeleton />
            ) : conversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center px-6 py-12 gap-3">
                <div className="size-12 rounded-full bg-[#008069]/10 border border-[#008069]/20 flex items-center justify-center">
                  <MessageSquare className="size-5 text-[#008069]/60" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-foreground">No conversations</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {filterTab !== 'all' ? 'Try switching to the All tab' : 'No WhatsApp messages found'}
                  </p>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-0.5 p-2">
                {conversations.map((conversation) => (
                  <ConversationRow
                    key={conversation.sender_wa_id}
                    conversation={conversation}
                    isActive={conversation.sender_wa_id === selectedWaId}
                    onClick={() => setSelectedWaId(conversation.sender_wa_id)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Thread Panel ──────────────────────────────────── */}
        <div className="flex-1 flex flex-col min-h-0 bg-[#efeae2] dark:bg-[#0b141a]">
          {!selectedConversation ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center px-6">
              <div className="size-16 rounded-full bg-[#008069]/10 border-2 border-[#008069]/20 flex items-center justify-center">
                <MessageSquare className="size-7 text-[#008069]/50" />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground/70">Select a conversation</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Choose a conversation from the left to view the full thread
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* Thread header */}
              <div className="flex items-center gap-3 px-5 py-3 border-b border-border/60 bg-card/90 backdrop-blur-sm shrink-0">
                <Avatar className="size-9 shrink-0">
                  <AvatarFallback className="text-xs font-bold bg-[#008069] text-white ring-2 ring-[#008069]/30">
                    {initialsFor(selectedConversation.member?.full_name, selectedConversation.sender_wa_id)}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-bold text-foreground truncate">
                    {displayNameFor(selectedConversation)}
                  </p>
                  <p className="text-xs text-muted-foreground font-mono truncate">
                    {selectedConversation.sender_wa_id}
                    {selectedConversation.member?.role ? ` · ${selectedConversation.member.role}` : ''}
                  </p>
                </div>
                {!selectedConversation.member && (
                  <Badge variant="outline" className="text-[10px] font-semibold text-amber-600 border-amber-500/30 bg-amber-500/10 shrink-0">
                    Unmapped
                  </Badge>
                )}
                {Boolean(selectedConversation.error_code) && (
                  <Badge variant="outline" className="text-[10px] font-semibold gap-1 text-rose-600 border-rose-500/30 bg-rose-500/10 shrink-0">
                    <AlertCircle className="size-3" />
                    Error
                  </Badge>
                )}
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto">
                {isMessagesLoading ? (
                  <ThreadSkeleton />
                ) : !messages || messages.length === 0 ? (
                  <div className="flex h-full items-center justify-center">
                    <p className="text-sm text-muted-foreground bg-card/70 backdrop-blur-sm px-4 py-2 rounded-full border">
                      No messages in this thread yet
                    </p>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3 p-5">
                    {messages.map((message) => (
                      <MessageBubble key={message.id} message={message} />
                    ))}
                    <div ref={threadEndRef} />
                  </div>
                )}
              </div>

              {/* Read-only footer */}
              <div className="px-5 py-2.5 border-t border-border/60 bg-card/80 backdrop-blur-sm shrink-0 flex items-center justify-center gap-2">
                <div className="flex items-center gap-1.5 bg-muted/60 border border-border px-3 py-1.5 rounded-full text-[11px] text-muted-foreground">
                  <Bot className="size-3 text-[#008069]" />
                  <span>Read-only monitoring view · Replies sent automatically by</span>
                  <span className="font-semibold text-[#008069]">Mesiri AI</span>
                  <Check className="size-3 text-[#008069]" />
                </div>
              </div>
            </>
          )}
        </div>

        {/* ── Right Metadata Panel ──────────────────────────── */}
        {selectedConversation && (
          <ContactMetadataPanel conversation={selectedConversation} />
        )}
      </div>
    </div>
  )
}

