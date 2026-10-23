import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Search,
  ArrowDownLeft,
  ArrowUpRight,
  User,
  HelpCircle,
  FileText,
  Video,
  Mic,
  Image as ImageIcon,
  MessageSquare,
  AlertTriangle,
  CheckCircle,
  Clock,
  SlidersHorizontal,
  ChevronLeft,
  ChevronRight,
  Eye,
  RotateCw,
  Paperclip,
  FileCode,
  Globe,
  Database,
  ArrowRightLeft,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  fetchCompanyMessages,
  fetchCompanyMessageDetail,
  fetchConversationMessages,
  type FetchMessagesParams,
} from '@/lib/api'
import { fetchProjects, fetchSites } from '@/lib/projects'
import type { ProjectItem, SiteItem } from '@/lib/scope-types'

export function WhatsAppMessagesTab() {

  const [params, setParams] = React.useState<FetchMessagesParams>({
    direction: 'all',
    search: '',
    member_id: undefined,
    message_type: 'all',
    project_id: 'all',
    site_id: 'all',
    processing_status: 'all',
    has_attachments: undefined,
    mapped_participant: 'all',
    limit: 15,
    offset: 0,
  })

  const [showAdvanced, setShowAdvanced] = React.useState(false)
  const [selectedMessageId, setSelectedMessageId] = React.useState<string | null>(null)
  const [selectedConversationWaId, setSelectedConversationWaId] = React.useState<string | null>(null)
  const [showRawPayload, setShowRawPayload] = React.useState(false)
  const [showNormalized, setShowNormalized] = React.useState(false)

  // Fetch projects and sites for filters
  const { data: projects = [] } = useQuery<ProjectItem[]>({
    queryKey: ['filter-projects'],
    queryFn: fetchProjects,
  })

  const { data: sites = [] } = useQuery<SiteItem[]>({
    queryKey: ['filter-sites', params.project_id],
    queryFn: () => (params.project_id && params.project_id !== 'all' ? fetchSites(params.project_id) : Promise.resolve([])),
    enabled: !!params.project_id && params.project_id !== 'all',
  })

  // Format Query Params
  const queryParams = React.useMemo(() => {
    const formatted: FetchMessagesParams = {
      limit: params.limit,
      offset: params.offset,
    }
    if (params.direction && params.direction !== 'all') formatted.direction = params.direction
    if (params.search?.trim()) formatted.search = params.search.trim()
    if (params.message_type && params.message_type !== 'all') formatted.message_type = params.message_type
    if (params.project_id && params.project_id !== 'all') formatted.project_id = params.project_id
    if (params.site_id && params.site_id !== 'all') formatted.site_id = params.site_id
    if (params.processing_status && params.processing_status !== 'all') formatted.processing_status = params.processing_status
    if (params.mapped_participant && params.mapped_participant !== 'all') formatted.mapped_participant = params.mapped_participant
    if (params.has_attachments !== undefined) formatted.has_attachments = params.has_attachments
    return formatted
  }, [params])

  // Fetch Message History
  const { data: messagesResponse, isLoading } = useQuery({
    queryKey: ['company-messages', queryParams],
    queryFn: () => fetchCompanyMessages(queryParams),
  })

  // Fetch Message Detail
  const { data: detail, isLoading: isLoadingDetail } = useQuery({
    queryKey: ['message-detail', selectedMessageId],
    queryFn: () => fetchCompanyMessageDetail(selectedMessageId!),
    enabled: !!selectedMessageId,
  })

  // Fetch Conversation History
  const { data: conversationMessages = [], isLoading: isLoadingConversation } = useQuery({
    queryKey: ['conversation', selectedConversationWaId],
    queryFn: () => fetchConversationMessages(selectedConversationWaId!),
    enabled: !!selectedConversationWaId,
  })

  const updateParam = (key: keyof FetchMessagesParams, val: any) => {
    setParams((prev) => ({ ...prev, [key]: val, offset: 0 }))
  }

  const clearFilters = () => {
    setParams({
      direction: 'all',
      search: '',
      member_id: undefined,
      message_type: 'all',
      project_id: 'all',
      site_id: 'all',
      processing_status: 'all',
      has_attachments: undefined,
      mapped_participant: 'all',
      limit: 15,
      offset: 0,
    })
  }

  // Icons Helper
  const getMessageIcon = (type: string) => {
    switch (type?.toLowerCase()) {
      case 'text':
        return <MessageSquare className="size-3 text-muted-foreground" />
      case 'voice':
      case 'audio':
        return <Mic className="size-3 text-sky-500" />
      case 'image':
        return <ImageIcon className="size-3 text-emerald-500" />
      case 'video':
        return <Video className="size-3 text-rose-500" />
      case 'document':
        return <FileText className="size-3 text-amber-500" />
      default:
        return <HelpCircle className="size-3 text-muted-foreground" />
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status?.toLowerCase()) {
      case 'completed':
      case 'processed':
        return (
          <Badge className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-none rounded text-[10px] gap-1 px-1.5 py-0.5">
            <CheckCircle className="size-3" /> Processed
          </Badge>
        )
      case 'failed':
        return (
          <Badge className="bg-rose-500/10 text-rose-700 dark:text-rose-400 border-none rounded text-[10px] gap-1 px-1.5 py-0.5">
            <AlertTriangle className="size-3" /> Failed
          </Badge>
        )
      case 'processing':
        return (
          <Badge className="bg-blue-500/10 text-blue-700 dark:text-blue-400 border-none rounded text-[10px] gap-1 px-1.5 py-0.5 animate-pulse">
            <Clock className="size-3" /> Processing
          </Badge>
        )
      default:
        return (
          <Badge className="bg-muted text-muted-foreground border-none rounded text-[10px] gap-1 px-1.5 py-0.5">
            <Clock className="size-3" /> Pending
          </Badge>
        )
    }
  }

  return (
    <div className="space-y-4">
      {/* Search and Filters Toolbar */}
      <div className="flex flex-col gap-3 border border-border/60 p-3 rounded bg-card">
        <div className="flex flex-col md:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search body text, sender number, member name..."
              value={params.search || ''}
              onChange={(e) => updateParam('search', e.target.value)}
              className="pl-9 h-9 text-xs"
            />
          </div>
          <div className="flex gap-2">
            <Select value={params.direction} onValueChange={(val) => updateParam('direction', val)}>
              <SelectTrigger className="w-[120px] h-9 text-xs">
                <SelectValue placeholder="Direction" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Directions</SelectItem>
                <SelectItem value="inbound">Inbound</SelectItem>
                <SelectItem value="outbound">Outbound</SelectItem>
              </SelectContent>
            </Select>

            <Select value={params.processing_status} onValueChange={(val) => updateParam('processing_status', val)}>
              <SelectTrigger className="w-[120px] h-9 text-xs">
                <SelectValue placeholder="AI Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="processing">Processing</SelectItem>
                <SelectItem value="completed">Processed</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
              </SelectContent>
            </Select>

            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="h-9 text-xs gap-1.5"
            >
              <SlidersHorizontal className="size-3.5" />
              Filters
            </Button>
            {JSON.stringify(queryParams) !== JSON.stringify({ limit: params.limit, offset: params.offset }) && (
              <Button variant="ghost" size="sm" onClick={clearFilters} className="h-9 text-xs">
                Clear
              </Button>
            )}
          </div>
        </div>

        {/* Expandable Advanced Filters */}
        {showAdvanced && (
          <div className="grid gap-3 border-t pt-3 grid-cols-1 sm:grid-cols-4">
            <div className="grid gap-1">
              <label className="text-[10px] uppercase font-semibold text-muted-foreground">Participant Mapping</label>
              <Select value={params.mapped_participant} onValueChange={(val) => updateParam('mapped_participant', val)}>
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue placeholder="Mapping" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Participants</SelectItem>
                  <SelectItem value="mapped">From your team</SelectItem>
                  <SelectItem value="unmapped">Unknown numbers</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1">
              <label className="text-[10px] uppercase font-semibold text-muted-foreground">Message Type</label>
              <Select value={params.message_type} onValueChange={(val) => updateParam('message_type', val)}>
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue placeholder="Type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  <SelectItem value="text">Text</SelectItem>
                  <SelectItem value="voice">Voice / Audio</SelectItem>
                  <SelectItem value="image">Image</SelectItem>
                  <SelectItem value="video">Video</SelectItem>
                  <SelectItem value="document">Document</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1">
              <label className="text-[10px] uppercase font-semibold text-muted-foreground">Project Scope</label>
              <Select value={params.project_id} onValueChange={(val) => {
                setParams((prev) => ({ ...prev, project_id: val, site_id: 'all', offset: 0 }))
              }}>
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue placeholder="Project" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Projects</SelectItem>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1">
              <label className="text-[10px] uppercase font-semibold text-muted-foreground">Site Scope</label>
              <Select
                value={params.site_id}
                onValueChange={(val) => updateParam('site_id', val)}
                disabled={!params.project_id || params.project_id === 'all'}
              >
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue placeholder="Site" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Sites</SelectItem>
                  {sites.map((s) => (
                    <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
      </div>

      {/* Main Table */}
      {isLoading ? (
        <div className="flex h-64 items-center justify-center text-xs text-muted-foreground gap-2">
          <RotateCw className="size-4 animate-spin text-primary" />
          Loading WhatsApp message logs...
        </div>
      ) : !messagesResponse || messagesResponse.items.length === 0 ? (
        <div className="border border-dashed p-12 text-center text-xs text-muted-foreground rounded bg-card">
          No WhatsApp messages matched the active search filters.
        </div>
      ) : (
        <div className="border border-border/60 rounded bg-card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/10">
                <TableHead className="w-12">Dir</TableHead>
                <TableHead className="w-40">Sender / Member</TableHead>
                <TableHead>Message Preview</TableHead>
                <TableHead className="w-24">Type</TableHead>
                <TableHead className="w-40">Project / Site Context</TableHead>
                <TableHead className="w-24">AI Status</TableHead>
                <TableHead className="w-28">Timestamp</TableHead>
                <TableHead className="w-12 text-center">Clip</TableHead>
                <TableHead className="w-20 text-right pr-4">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {messagesResponse.items.map((msg) => {
                const isOut = msg.direction === 'outbound'
                const isMapped = !!msg.member

                return (
                  <TableRow key={`${msg.id}-${msg.direction}`} className="hover:bg-muted/5">
                    <TableCell className="pl-4">
                      {isOut ? (
                        <div className="size-6 bg-blue-500/10 text-blue-600 rounded flex items-center justify-center" title="Outbound Reply">
                          <ArrowUpRight className="size-3.5" />
                        </div>
                      ) : (
                        <div className="size-6 bg-emerald-500/10 text-emerald-600 rounded flex items-center justify-center" title="Inbound Message">
                          <ArrowDownLeft className="size-3.5" />
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      {isMapped ? (
                        <div className="flex flex-col gap-0.5">
                          <span className="font-semibold text-xs text-foreground">{msg.member?.full_name}</span>
                          <span className="text-[9px] font-mono text-muted-foreground tracking-wider uppercase">{msg.member?.role}</span>
                        </div>
                      ) : (
                        <div className="flex flex-col gap-0.5">
                          <span className="font-mono text-xs text-rose-500 font-semibold">{msg.sender_wa_id}</span>
                          <span className="text-[9px] italic text-rose-400">Unknown number</span>
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-xs text-foreground font-normal">
                      {msg.body || <span className="italic text-muted-foreground/50">Empty body</span>}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        {getMessageIcon(msg.message_type)}
                        <span className="capitalize">{msg.message_type}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      {msg.project_name ? (
                        <div className="flex flex-col text-[11px] leading-tight">
                          <span className="font-medium text-foreground">{msg.project_name}</span>
                          <span className="text-muted-foreground/80">{msg.site_name || 'Global'}</span>
                        </div>
                      ) : (
                        <span className="text-muted-foreground/30 italic text-xs">Unresolved</span>
                      )}
                    </TableCell>
                    <TableCell>{getStatusBadge(msg.processing_status)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(msg.timestamp).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                      <span className="text-[10px] block opacity-70">
                        {new Date(msg.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                      </span>
                    </TableCell>
                    <TableCell className="text-center">
                      {!isOut && msg.message_type !== 'text' && (
                        <span title="Has attachment">
                          <Paperclip className="size-3.5 text-muted-foreground inline" />
                        </span>
                      )}

                    </TableCell>
                    <TableCell className="text-right pr-4">
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7"
                          onClick={() => setSelectedMessageId(msg.id)}
                          title="View Ingestion Detail"
                        >
                          <Eye className="size-3.5 text-muted-foreground hover:text-foreground" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7"
                          onClick={() => setSelectedConversationWaId(msg.sender_wa_id)}
                          title="View Conversation Thread"
                        >
                          <MessageSquare className="size-3.5 text-muted-foreground hover:text-foreground" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pagination Footer */}
      {messagesResponse && messagesResponse.total > 0 && (
        <div className="flex items-center justify-between border border-border/60 bg-card rounded p-3 text-xs text-muted-foreground">
          <div>
            Showing <span className="font-semibold text-foreground font-mono">{params.offset! + 1}</span> to{' '}
            <span className="font-semibold text-foreground font-mono">
              {Math.min(params.offset! + params.limit!, messagesResponse.total)}
            </span>{' '}
            of <span className="font-semibold text-foreground font-mono">{messagesResponse.total}</span> messages
          </div>
          <div className="flex gap-1.5">
            <Button
              variant="outline"
              size="icon"
              className="size-7"
              disabled={params.offset === 0}
              onClick={() => setParams((prev) => ({ ...prev, offset: Math.max(0, prev.offset! - prev.limit!) }))}
            >
              <ChevronLeft className="size-3.5" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="size-7"
              disabled={params.offset! + params.limit! >= messagesResponse.total}
              onClick={() =>
                setParams((prev) => ({ ...prev, offset: Math.min(messagesResponse.total - 1, prev.offset! + prev.limit!) }))
              }
            >
              <ChevronRight className="size-3.5" />
            </Button>
          </div>
        </div>
      )}

      {/* --------------------------------------------------------------------- */}
      {/* 1. Message Detail Ingestion Modal */}
      {/* --------------------------------------------------------------------- */}
      <Dialog open={!!selectedMessageId} onOpenChange={(open) => !open && setSelectedMessageId(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader className="border-b pb-2 flex flex-row items-center justify-between">
            <DialogTitle className="text-sm font-semibold">WhatsApp Ingestion Detail & Trace Logs</DialogTitle>
          </DialogHeader>

          {isLoadingDetail || !detail ? (
            <div className="flex h-64 items-center justify-center text-xs text-muted-foreground gap-2">
              <RotateCw className="size-4 animate-spin text-primary" />
              Loading trace logs...
            </div>
          ) : (
            <div className="space-y-5 text-xs">
              {/* Profile Bar */}
              <div className="flex items-start justify-between border border-border/50 bg-muted/20 p-3 rounded">
                <div className="flex items-center gap-3">
                  <div className="size-8 rounded bg-primary/10 text-primary flex items-center justify-center font-bold">
                    {detail.member ? detail.member.full_name.substring(0, 2).toUpperCase() : <User className="size-4" />}
                  </div>
                  <div>
                    <div className="font-semibold text-foreground">
                      {detail.member ? detail.member.full_name : 'Unknown number'}
                    </div>
                    <div className="text-muted-foreground flex items-center gap-1.5 mt-0.5">
                      <span className="font-mono">{detail.sender_wa_id}</span>
                      {detail.member && (
                        <>
                          <span>•</span>
                          <span className="uppercase tracking-wider text-[9px] font-semibold bg-muted px-1.5 py-0.2 rounded">
                            {detail.member.role}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                <div className="text-right">
                  <div className="text-[10px] text-muted-foreground">Correlation ID</div>
                  <div className="font-mono font-medium text-foreground">{detail.correlation_id}</div>
                </div>
              </div>

              {/* Message Context */}
              <div className="grid grid-cols-2 gap-4">
                <div className="border border-border/50 p-3 rounded">
                  <h4 className="font-semibold text-muted-foreground uppercase text-[9px] tracking-wider mb-2">Message Exchange</h4>
                  <div className="space-y-1.5">
                    <div>
                      <span className="text-muted-foreground">Modality:</span>{' '}
                      <span className="capitalize font-medium text-foreground">{detail.message_type}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Ingested:</span>{' '}
                      <span className="font-medium text-foreground">{new Date(detail.received_at).toLocaleString()}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">AI Processing:</span>{' '}
                      <span className="inline-block">{getStatusBadge(detail.processing_status)}</span>
                    </div>
                  </div>
                </div>

                <div className="border border-border/50 p-3 rounded">
                  <h4 className="font-semibold text-muted-foreground uppercase text-[9px] tracking-wider mb-2">Resolved Context</h4>
                  <div className="space-y-1.5">
                    <div>
                      <span className="text-muted-foreground">Project:</span>{' '}
                      <span className="font-medium text-foreground">{detail.project_name || 'Unresolved'}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Site:</span>{' '}
                      <span className="font-medium text-foreground">{detail.site_name || 'Unresolved'}</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Inbound & Outbound Texts */}
              <div className="space-y-3">
                <div className="border border-border/60 rounded overflow-hidden">
                  <div className="bg-muted/40 px-3 py-1.5 border-b font-medium text-muted-foreground uppercase tracking-wider text-[9px]">
                    User Inbound Content
                  </div>
                  <div className="p-3 bg-muted/10 font-normal leading-relaxed text-foreground">
                    {detail.body_text || <span className="italic text-muted-foreground/40">No body text</span>}
                  </div>
                </div>

                {detail.assistant_reply && (
                  <div className="border border-border/60 rounded overflow-hidden">
                    <div className="bg-blue-500/10 px-3 py-1.5 border-b font-medium text-blue-700 dark:text-blue-400 uppercase tracking-wider text-[9px]">
                      Assistant Outbound Reply
                    </div>
                    <div className="p-3 bg-blue-500/5 font-mono text-foreground font-normal leading-relaxed">
                      {detail.assistant_reply}
                    </div>
                  </div>
                )}
              </div>

              {/* Journey Traces */}
              <div>
                <h4 className="font-semibold text-foreground text-xs mb-3 flex items-center gap-1.5">
                  <ArrowRightLeft className="size-4 text-primary" />
                  Journey Stage Traces
                </h4>
                {detail.traces.length === 0 ? (
                  <div className="text-muted-foreground italic border border-dashed p-4 rounded text-center">
                    No stage traces recorded for this message execution.
                  </div>
                ) : (
                  <div className="border border-border/60 rounded overflow-hidden">
                    <Table>
                      <TableHeader className="bg-muted/30">
                        <TableRow>
                          <TableHead>Stage</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Latency</TableHead>
                          <TableHead>Error Code / Detail</TableHead>
                          <TableHead>Logged At</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {detail.traces.map((trace, idx) => (
                          <TableRow key={idx}>
                            <TableCell className="font-medium capitalize text-foreground">{trace.stage}</TableCell>
                            <TableCell>
                              {trace.succeeded ? (
                                <Badge className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-none rounded text-[9px] px-1 py-0">
                                  Success
                                </Badge>
                              ) : (
                                <Badge className="bg-rose-500/10 text-rose-700 dark:text-rose-400 border-none rounded text-[9px] px-1 py-0">
                                  Failed
                                </Badge>
                              )}
                            </TableCell>
                            <TableCell className="font-mono">
                              {trace.duration_ms !== null && trace.duration_ms !== undefined ? `${trace.duration_ms}ms` : '—'}
                            </TableCell>
                            <TableCell className="max-w-xs truncate text-muted-foreground">
                              {trace.error_code ? (
                                <span className="text-rose-500" title={trace.error_message || ''}>
                                  [{trace.error_code}] {trace.error_message}
                                </span>
                              ) : (
                                '—'
                              )}
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {new Date(trace.created_at).toLocaleTimeString()}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </div>

              {/* Provider Executions */}
              <div>
                <h4 className="font-semibold text-foreground text-xs mb-3 flex items-center gap-1.5">
                  <Database className="size-4 text-primary" />
                  AI/LLM Provider Executions
                </h4>
                {detail.providers.length === 0 ? (
                  <div className="text-muted-foreground italic border border-dashed p-4 rounded text-center">
                    No LLM or API provider executions logged.
                  </div>
                ) : (
                  <div className="border border-border/60 rounded overflow-hidden">
                    <Table>
                      <TableHeader className="bg-muted/30">
                        <TableRow>
                          <TableHead>Stage</TableHead>
                          <TableHead>Provider</TableHead>
                          <TableHead>Operation</TableHead>
                          <TableHead>Model</TableHead>
                          <TableHead>Latency</TableHead>
                          <TableHead>Status</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {detail.providers.map((p, idx) => (
                          <TableRow key={idx}>
                            <TableCell className="font-medium capitalize text-foreground">{p.stage}</TableCell>
                            <TableCell className="font-semibold uppercase">{p.provider}</TableCell>
                            <TableCell className="font-mono">{p.operation}</TableCell>
                            <TableCell className="text-muted-foreground">{p.model || '—'}</TableCell>
                            <TableCell className="font-mono">
                              {p.latency_ms !== null && p.latency_ms !== undefined ? `${p.latency_ms.toFixed(0)}ms` : '—'}
                            </TableCell>
                            <TableCell>
                              {p.succeeded ? (
                                <Badge className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-none rounded text-[9px] px-1 py-0">
                                  Success
                                </Badge>
                              ) : (
                                <Badge className="bg-rose-500/10 text-rose-700 dark:text-rose-400 border-none rounded text-[9px] px-1 py-0">
                                  Failed
                                </Badge>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </div>

              {/* Linked Records & Outbox Timeline */}
              {detail.timeline_entries.length > 0 && (
                <div>
                  <h4 className="font-semibold text-foreground text-xs mb-3 flex items-center gap-1.5">
                    <Globe className="size-4 text-primary" />
                    Ingested Timeline Events
                  </h4>
                  <div className="space-y-2">
                    {detail.timeline_entries.map((te) => (
                      <div key={te.id} className="border border-border/60 p-2.5 rounded bg-muted/5 flex justify-between items-center">
                        <div>
                          <div className="font-medium text-foreground">{te.summary}</div>
                          <div className="text-[10px] text-muted-foreground mt-0.5">
                            Aggregate: <span className="font-mono">{te.source_aggregate_type}</span> ({te.source_aggregate_id})
                          </div>
                        </div>
                        <Badge variant="outline" className="text-[9px] rounded font-mono">
                          {te.event_type}
                        </Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* RAW JSON Payloads */}
              <div className="grid grid-cols-2 gap-4">
                <div className="border border-border/50 rounded overflow-hidden">
                  <button
                    onClick={() => setShowRawPayload(!showRawPayload)}
                    className="w-full bg-muted/40 px-3 py-2 border-b flex justify-between items-center font-medium text-muted-foreground uppercase text-[9px] tracking-wider text-left"
                  >
                    <span>Raw Webhook Payload JSON</span>
                    <FileCode className="size-3.5" />
                  </button>
                  {showRawPayload && (
                    <pre className="p-3 bg-muted/10 font-mono text-[10px] overflow-auto max-h-48 text-foreground whitespace-pre-wrap">
                      {JSON.stringify(detail.raw_payload, null, 2)}
                    </pre>
                  )}
                </div>

                <div className="border border-border/50 rounded overflow-hidden">
                  <button
                    onClick={() => setShowNormalized(!showNormalized)}
                    className="w-full bg-muted/40 px-3 py-2 border-b flex justify-between items-center font-medium text-muted-foreground uppercase text-[9px] tracking-wider text-left"
                  >
                    <span>Normalized Message JSON</span>
                    <FileCode className="size-3.5" />
                  </button>
                  {showNormalized && (
                    <pre className="p-3 bg-muted/10 font-mono text-[10px] overflow-auto max-h-48 text-foreground whitespace-pre-wrap">
                      {JSON.stringify(detail.normalized_message, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* --------------------------------------------------------------------- */}
      {/* 2. Conversation Chat Thread Modal */}
      {/* --------------------------------------------------------------------- */}
      <Dialog open={!!selectedConversationWaId} onOpenChange={(open) => !open && setSelectedConversationWaId(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col p-0 overflow-hidden">
          <DialogHeader className="border-b px-5 py-4 flex flex-row items-center justify-between bg-muted/20">
            <div>
              <DialogTitle className="text-sm font-semibold flex items-center gap-1.5">
                <MessageSquare className="size-4 text-emerald-500" />
                Conversation History Thread
              </DialogTitle>
              <span className="text-[10px] font-mono text-muted-foreground tracking-wider block mt-0.5">
                WA ID: {selectedConversationWaId}
              </span>
            </div>
          </DialogHeader>

          {isLoadingConversation ? (
            <div className="flex h-96 items-center justify-center text-xs text-muted-foreground gap-2">
              <RotateCw className="size-4 animate-spin text-primary" />
              Loading messages...
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto p-5 bg-muted/5 space-y-4 min-h-[400px]">
              {conversationMessages.length === 0 ? (
                <div className="text-muted-foreground italic text-center p-8">No messages in this chat.</div>
              ) : (
                conversationMessages.map((chatMsg, idx) => {
                  const isInbound = chatMsg.direction === 'inbound'
                  return (
                    <div
                      key={idx}
                      className={`flex ${isInbound ? 'justify-start' : 'justify-end'}`}
                    >
                      <div
                        className={`max-w-[75%] rounded-lg p-3 text-xs shadow-sm ${
                          isInbound
                            ? 'bg-card text-foreground border border-border/70 rounded-tl-none'
                            : 'bg-primary text-primary-foreground rounded-tr-none'
                        }`}
                      >
                        {/* Header for inbound */}
                        {isInbound && chatMsg.member && (
                          <div className="font-semibold text-[10px] text-muted-foreground uppercase tracking-wider mb-1">
                            {chatMsg.member.full_name} ({chatMsg.member.role})
                          </div>
                        )}

                        {/* Body */}
                        <div className="whitespace-pre-wrap font-normal leading-relaxed">{chatMsg.body}</div>

                        {/* Footer (timestamp + metadata) */}
                        <div
                          className={`mt-1.5 text-[9px] flex items-center justify-end gap-1 ${
                            isInbound ? 'text-muted-foreground' : 'text-primary-foreground/70'
                          }`}
                        >
                          {chatMsg.message_type !== 'text' && (
                            <span className="capitalize font-mono opacity-80">[{chatMsg.message_type}]</span>
                          )}
                          <span>
                            {new Date(chatMsg.timestamp).toLocaleTimeString(undefined, {
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </span>
                        </div>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
