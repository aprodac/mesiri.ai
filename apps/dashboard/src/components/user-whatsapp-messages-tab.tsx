import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  MessageSquare,
  ArrowUpDown,
  Search,
  SlidersHorizontal,
  ChevronRight,
  Info,
  Loader2,
  Settings,
  Inbox,
  Sparkles,
  Mic,
  Image as ImageIcon,
  FileText,
  MapPin,
  MessageCircle,
  ExternalLink,
} from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  fetchUserWhatsAppMessages,
  fetchUserWhatsAppMessageDetail,
  type User,
  type UserWhatsAppMessageFilters,
  type MessageOutcome,
} from '@/lib/api'
import { fetchProjects, fetchSites } from '@/lib/projects'

interface UserWhatsAppMessagesTabProps {
  user: User
  setActiveTab: (tab: any) => void
  setWhatsappOpen: (open: boolean) => void
}

export function UserWhatsAppMessagesTab({
  user,
  setWhatsappOpen,
}: UserWhatsAppMessagesTabProps) {
  // Filter States
  const [waIdFilter, setWaIdFilter] = React.useState<string>('ALL')
  const [directionFilter, setDirectionFilter] = React.useState<string>('ALL')
  const [typeFilter, setTypeFilter] = React.useState<string>('ALL')
  const [statusFilter, setStatusFilter] = React.useState<string>('ALL')
  const [clarificationFilter, setClarificationFilter] = React.useState<string>('ALL')
  const [hasAttachmentsFilter, setHasAttachmentsFilter] = React.useState<string>('ALL')
  const [searchFilter, setSearchFilter] = React.useState<string>('')
  const [projectFilter, setProjectFilter] = React.useState<string>('ALL')
  const [siteFilter, setSiteFilter] = React.useState<string>('ALL')
  const [dateFromFilter, setDateFromFilter] = React.useState<string>('')
  const [dateToFilter, setDateToFilter] = React.useState<string>('')
  const [sortOrder, setSortOrder] = React.useState<'asc' | 'desc'>('desc')
  const [page, setPage] = React.useState(1)
  const limit = 10

  // Filters Sheet state
  const [filterSheetOpen, setFilterSheetOpen] = React.useState(false)

  // Details Sheet state
  const [selectedMessageId, setSelectedMessageId] = React.useState<string | null>(null)
  const [detailsTab, setDetailsTab] = React.useState<'details' | 'conversation'>('details')

  // Fetch Projects for filters
  const { data: projects = [] } = useQuery({
    queryKey: ['whatsapp-projects-list'],
    queryFn: fetchProjects,
  })

  // Fetch Sites when a project is selected in filters
  const { data: sites = [] } = useQuery({
    queryKey: ['whatsapp-sites-list', projectFilter],
    queryFn: () => fetchSites(projectFilter),
    enabled: projectFilter !== 'ALL',
  })

  // Derived filter payload
  const filtersPayload = React.useMemo<UserWhatsAppMessageFilters>(() => {
    const payload: UserWhatsAppMessageFilters = {
      limit,
      offset: (page - 1) * limit,
      sort: sortOrder,
    }
    if (waIdFilter !== 'ALL') payload.wa_id = waIdFilter
    if (directionFilter !== 'ALL') payload.direction = directionFilter.toLowerCase()
    if (typeFilter !== 'ALL') payload.message_type = typeFilter.toLowerCase()
    if (statusFilter !== 'ALL') payload.processing_status = statusFilter.toLowerCase()
    if (clarificationFilter !== 'ALL') payload.clarification_status = clarificationFilter
    if (hasAttachmentsFilter !== 'ALL') payload.has_attachments = hasAttachmentsFilter === 'TRUE'
    if (searchFilter.trim()) payload.search = searchFilter.trim()
    if (projectFilter !== 'ALL') payload.project_id = projectFilter
    if (siteFilter !== 'ALL') payload.site_id = siteFilter
    if (dateFromFilter) payload.date_from = new Date(dateFromFilter).toISOString()
    if (dateToFilter) payload.date_to = new Date(dateToFilter).toISOString()
    return payload
  }, [
    waIdFilter,
    directionFilter,
    typeFilter,
    statusFilter,
    clarificationFilter,
    hasAttachmentsFilter,
    searchFilter,
    projectFilter,
    siteFilter,
    dateFromFilter,
    dateToFilter,
    sortOrder,
    page,
  ])

  // Reset page on filters changes
  React.useEffect(() => {
    setPage(1)
  }, [
    waIdFilter,
    directionFilter,
    typeFilter,
    statusFilter,
    clarificationFilter,
    hasAttachmentsFilter,
    searchFilter,
    projectFilter,
    siteFilter,
    dateFromFilter,
    dateToFilter,
    sortOrder,
  ])

  // Fetch messages list
  const { data: messagesData, isLoading: isMessagesLoading, isError: isMessagesError } = useQuery({
    queryKey: ['user-whatsapp-messages', user.id, filtersPayload],
    queryFn: () => fetchUserWhatsAppMessages(user.id, filtersPayload),
    enabled: !!user.id && !!user.whatsapp_number,
  })

  // Fetch message details
  const { data: messageDetail, isLoading: isDetailLoading } = useQuery({
    queryKey: ['user-whatsapp-message-detail', user.id, selectedMessageId],
    queryFn: () => fetchUserWhatsAppMessageDetail(user.id, selectedMessageId!),
    enabled: !!selectedMessageId && !!user.id,
  })

  // Fetch full conversation history for the identity when in conversation view
  const conversationWaId = messageDetail?.sender_wa_id
  const { data: conversationData, isLoading: isConversationLoading } = useQuery({
    queryKey: ['user-whatsapp-conversation', user.id, conversationWaId],
    queryFn: () =>
      fetchUserWhatsAppMessages(user.id, {
        wa_id: conversationWaId,
        sort: 'asc',
        limit: 100,
      }),
    enabled: detailsTab === 'conversation' && !!conversationWaId && !!user.id,
  })

  const hasNoMapping = !user.whatsapp_number

  if (hasNoMapping) {
    return (
      <div className="flex flex-col items-start gap-2 text-sm">
        <p className="text-muted-foreground">Add their WhatsApp number to see the messages they send.</p>
        <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setWhatsappOpen(true)}>
          <Settings className="size-3.5" /> Add WhatsApp number
        </Button>
      </div>
    )
  }

  const messagesList = messagesData?.items || []
  const totalCount = messagesData?.total || 0
  const totalPages = Math.ceil(totalCount / limit)

  const activeFiltersCount = [
    waIdFilter !== 'ALL',
    directionFilter !== 'ALL',
    typeFilter !== 'ALL',
    statusFilter !== 'ALL',
    clarificationFilter !== 'ALL',
    hasAttachmentsFilter !== 'ALL',
    projectFilter !== 'ALL',
    siteFilter !== 'ALL',
    !!dateFromFilter,
    !!dateToFilter,
  ].filter(Boolean).length

  const handleResetFilters = () => {
    setWaIdFilter('ALL')
    setDirectionFilter('ALL')
    setTypeFilter('ALL')
    setStatusFilter('ALL')
    setClarificationFilter('ALL')
    setHasAttachmentsFilter('ALL')
    setProjectFilter('ALL')
    setSiteFilter('ALL')
    setDateFromFilter('')
    setDateToFilter('')
    setSearchFilter('')
  }

  const renderModalityIcon = (type: string) => {
    switch (type.toLowerCase()) {
      case 'audio':
        return <Mic className="size-3 text-sky-500 shrink-0" />
      case 'image':
        return <ImageIcon className="size-3 text-emerald-500 shrink-0" />
      case 'document':
        return <FileText className="size-3 text-indigo-500 shrink-0" />
      case 'location':
        return <MapPin className="size-3 text-rose-500 shrink-0" />
      default:
        return <MessageCircle className="size-3 text-slate-500 shrink-0" />
    }
  }

  const renderOutcomeBadge = (outcome?: MessageOutcome | null) => {
    if (!outcome) return <span className="text-[10px] text-muted-foreground/60 italic">No record created</span>
    const recordLabel = outcome.record_type.replace(/([A-Z])/g, ' $1').trim()
    return (
      <Badge variant="outline" className="text-[9px] rounded-sm py-0 bg-primary/5 text-primary border-primary/20 flex items-center gap-1 shrink-0 w-fit">
        <Sparkles className="size-2.5" />
        {recordLabel}
      </Badge>
    )
  }

  return (
    <div className="space-y-3 text-sm">
      {/* Toolbar / Filters */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 ">
        <div className="flex items-center gap-2 flex-1 max-w-md relative">
          <Search className="size-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
          <Input
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
            placeholder="Search message text..."
            className="pl-9 h-8 text-xs flex-1 rounded-md"
          />
        </div>

        <div className="flex items-center gap-2">
          {activeFiltersCount > 0 && (
            <Button size="sm" variant="ghost" onClick={handleResetFilters} className="h-8 text-[11px] font-bold text-muted-foreground hover:text-foreground">
              Clear Filters
            </Button>
          )}

          <Button size="sm" variant="outline" onClick={() => setFilterSheetOpen(true)} className="h-8 text-xs gap-1.5 font-bold rounded-md border border-primary/20 text-primary">
            <SlidersHorizontal className="size-3.5" />
            Filters
            {activeFiltersCount > 0 && (
              <Badge className="bg-primary text-white size-4 rounded-full p-0 flex items-center justify-center text-[9px]">
                {activeFiltersCount}
              </Badge>
            )}
          </Button>

          <Button size="sm" variant="outline" onClick={() => setSortOrder(prev => prev === 'desc' ? 'asc' : 'desc')} className="h-8 text-xs gap-1.5 font-bold rounded-md">
            <ArrowUpDown className="size-3.5 text-muted-foreground" />
            {sortOrder === 'desc' ? 'Newest' : 'Oldest'}
          </Button>
        </div>
      </div>

      {/* Table view */}
      {isMessagesLoading ? (
        <div className="flex h-48 items-center justify-center text-xs text-muted-foreground gap-2">
          <Loader2 className="size-4 animate-spin text-primary" />
          Loading user message history...
        </div>
      ) : isMessagesError ? (
        <div className="bg-destructive/10 border border-destructive text-destructive text-xs p-4 rounded text-center">
          Failed to load messages from backend. Please retry.
        </div>
      ) : messagesList.length === 0 ? (
        <div className="border border-dashed py-12 text-center text-xs italic text-muted-foreground bg-muted/5 flex flex-col items-center justify-center gap-2">
          <Inbox className="size-8 text-muted-foreground/50" />
          {activeFiltersCount > 0 ? 'No messages match selected filter criteria.' : 'No messages logged for this user.'}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="hidden md:block border rounded overflow-x-auto w-full">
            <Table className="text-xs w-full min-w-[1000px] table-fixed">
              <TableHeader className="bg-muted/30">
                <TableRow>
                  <TableHead className="w-20">Direction</TableHead>
                  {user.whatsapp_number && <TableHead className="w-32">Number</TableHead>}
                  <TableHead>Message Preview</TableHead>
                  <TableHead className="w-28">AI Status</TableHead>
                  <TableHead className="w-28">Clarification</TableHead>
                  <TableHead className="w-36">Project/Site Context</TableHead>
                  <TableHead className="w-36">Outcome</TableHead>
                  <TableHead className="w-32">Occurred At</TableHead>
                  <TableHead className="w-20 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {messagesList.map((msg) => {
                  const hasProject = !!msg.project
                  const hasSite = !!msg.site

                  return (
                    <TableRow key={msg.id} className="hover:bg-muted/5">
                      <TableCell>
                        <Badge variant="outline" className={`rounded-sm py-0 text-[10px] capitalize font-medium ${
                          msg.direction === 'inbound' 
                            ? 'bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-400 border-sky-200 dark:border-sky-500/20' 
                            : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20'
                        }`}>
                          {msg.direction}
                        </Badge>
                      </TableCell>
                      {user.whatsapp_number && (
                        <TableCell className="font-mono text-muted-foreground">
                          {msg.sender_wa_id}
                        </TableCell>
                      )}
                      <TableCell className="font-normal text-foreground">
                        <div className="flex items-center gap-1.5 max-w-sm lg:max-w-md">
                          {renderModalityIcon(msg.message_type)}
                          <span className="truncate block" title={msg.body_text || ''}>
                            {msg.body_text || <span className="text-muted-foreground/50 italic">[Media message]</span>}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={`rounded-sm py-0 text-[10px] capitalize font-medium ${
                          msg.processing_status === 'completed'
                            ? 'bg-emerald-500/5 text-emerald-700 dark:text-emerald-400 border-emerald-500/20'
                            : msg.processing_status === 'failed'
                            ? 'bg-rose-500/5 text-rose-700 dark:text-rose-400 border-rose-500/20'
                            : 'bg-amber-500/5 text-amber-700 dark:text-amber-400 border-amber-500/20'
                        }`}>
                          {msg.processing_status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={`rounded-sm py-0 text-[10px] capitalize font-medium ${
                          msg.clarification_status === 'awaiting_user'
                            ? 'bg-yellow-500/5 text-yellow-800 dark:text-yellow-400 border-yellow-500/20'
                            : msg.clarification_status === 'resolved'
                            ? 'bg-emerald-500/5 text-emerald-700 dark:text-emerald-400 border-emerald-500/20'
                            : 'bg-muted text-muted-foreground'
                        }`}>
                          {msg.clarification_status === 'none' ? 'none' : msg.clarification_status.replace('_', ' ')}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-0.5 font-medium">
                          {hasProject ? (
                            <Link to={`/today?project=${msg.project!.id}`} className="text-primary hover:underline truncate block">
                              {msg.project!.name}
                            </Link>
                          ) : (
                            <span className="text-muted-foreground/60 italic text-[11px]">No project</span>
                          )}
                          {hasSite ? (
                            <Link to={`/today?project=${msg.project!.id}&site=${msg.site!.id}`} className="text-muted-foreground hover:text-foreground text-[10px] hover:underline truncate block">
                              {msg.site!.name}
                            </Link>
                          ) : hasProject ? (
                            <span className="text-muted-foreground/50 italic text-[10px]">No site</span>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        {renderOutcomeBadge(msg.outcome)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {new Date(msg.occurred_at).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button size="sm" variant="ghost" onClick={() => {
                          setSelectedMessageId(msg.id)
                          setDetailsTab('details')
                        }} className="font-bold text-[10px] text-primary h-7 px-2">
                          Details
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>

          {/* Responsive Mobile Card View */}
          <div className="md:hidden space-y-3">
            {messagesList.map((msg) => (
              <Card key={msg.id} className="rounded-none border-border/70 shadow-none p-4 space-y-3 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <Badge variant="outline" className={`rounded-sm py-0.5 text-[9px] capitalize ${
                    msg.direction === 'inbound'
                      ? 'bg-sky-50 text-sky-700 border-sky-200'
                      : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  }`}>
                    {msg.direction}
                  </Badge>
                  <span className="text-muted-foreground text-[10px]">
                    {new Date(msg.occurred_at).toLocaleString()}
                  </span>
                </div>

                <div className="flex items-center gap-1.5 text-foreground font-medium bg-muted/10 p-2 border">
                  {renderModalityIcon(msg.message_type)}
                  <p className="line-clamp-2 leading-relaxed">
                    {msg.body_text || <span className="text-muted-foreground/50 italic">[Media message]</span>}
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-2 text-[11px] pt-1">
                  <div>
                    <span className="text-muted-foreground block text-[10px] uppercase font-semibold">AI Status</span>
                    <span className="capitalize">{msg.processing_status}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground block text-[10px] uppercase font-semibold">Clarification</span>
                    <span className="capitalize">{msg.clarification_status === 'none' ? 'None' : msg.clarification_status.replace('_', ' ')}</span>
                  </div>
                  <div className="col-span-2">
                    <span className="text-muted-foreground block text-[10px] uppercase font-semibold">Context</span>
                    {msg.project ? (
                      <span className="font-medium text-foreground block">
                        {msg.project.name} {msg.site ? `· ${msg.site.name}` : ''}
                      </span>
                    ) : (
                      <span className="text-muted-foreground/60 italic block">Not added</span>
                    )}
                  </div>
                  {msg.outcome && (
                    <div className="col-span-2">
                      <span className="text-muted-foreground block text-[10px] uppercase font-semibold">Created Record</span>
                      {renderOutcomeBadge(msg.outcome)}
                    </div>
                  )}
                </div>

                <div className="flex justify-end pt-2 border-t">
                  <Button size="sm" variant="outline" onClick={() => {
                    setSelectedMessageId(msg.id)
                    setDetailsTab('details')
                  }} className="h-7 text-[10px] font-bold">
                    View Details
                  </Button>
                </div>
              </Card>
            ))}
          </div>

          {/* Pagination Controls */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-xs py-2">
              <span className="text-muted-foreground">
                Showing page <strong className="text-foreground">{page}</strong> of <strong className="text-foreground">{totalPages}</strong> ({totalCount} total)
              </span>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="h-8 w-16 font-bold rounded-sm">
                  Previous
                </Button>
                <Button size="sm" variant="outline" onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="h-8 w-16 font-bold rounded-sm">
                  Next
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Filters Slide-out Sheet */}
      <Sheet open={filterSheetOpen} onOpenChange={setFilterSheetOpen}>
        <SheetContent className="sm:max-w-[360px] text-xs">
          <SheetHeader className="pb-4 border-b">
            <SheetTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground">Search & Filter Criteria</SheetTitle>
            <SheetDescription className="text-[10px] text-muted-foreground">Refine WhatsApp message history query parameters.</SheetDescription>
          </SheetHeader>
          <div className="space-y-4 py-4 max-h-[80vh] overflow-y-auto font-normal">
            <div className="grid gap-1.5">
              <Label htmlFor="fltWaId">Filter Identity</Label>
              <Select value={waIdFilter} onValueChange={setWaIdFilter}>
                <SelectTrigger id="fltWaId" className="h-8 text-xs rounded-sm">
                  <SelectValue placeholder="All Identities" />
                </SelectTrigger>
                <SelectContent className="text-xs">
                  <SelectItem value="ALL">All numbers</SelectItem>
                  {user.whatsapp_number && (
                    <SelectItem value={user.whatsapp_number}>{user.whatsapp_number}</SelectItem>
                  )}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="fltDirection">Direction</Label>
              <Select value={directionFilter} onValueChange={setDirectionFilter}>
                <SelectTrigger id="fltDirection" className="h-8 text-xs rounded-sm">
                  <SelectValue placeholder="All" />
                </SelectTrigger>
                <SelectContent className="text-xs">
                  <SelectItem value="ALL">All Directions</SelectItem>
                  <SelectItem value="INBOUND">Inbound (User → Mesiri)</SelectItem>
                  <SelectItem value="OUTBOUND">Outbound (Mesiri → User)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="fltMsgType">Message Type</Label>
              <Select value={typeFilter} onValueChange={setTypeFilter}>
                <SelectTrigger id="fltMsgType" className="h-8 text-xs rounded-sm">
                  <SelectValue placeholder="All" />
                </SelectTrigger>
                <SelectContent className="text-xs">
                  <SelectItem value="ALL">All Modalities</SelectItem>
                  <SelectItem value="TEXT">Text Message</SelectItem>
                  <SelectItem value="AUDIO">Voice Message</SelectItem>
                  <SelectItem value="IMAGE">Image</SelectItem>
                  <SelectItem value="DOCUMENT">Document</SelectItem>
                  <SelectItem value="LOCATION">Location</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="fltAiStatus">AI Processing Status</Label>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger id="fltAiStatus" className="h-8 text-xs rounded-sm">
                  <SelectValue placeholder="All" />
                </SelectTrigger>
                <SelectContent className="text-xs">
                  <SelectItem value="ALL">All Processing States</SelectItem>
                  <SelectItem value="PENDING">Pending</SelectItem>
                  <SelectItem value="COMPLETED">Completed</SelectItem>
                  <SelectItem value="FAILED">Failed</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="fltClarification">Clarification State</Label>
              <Select value={clarificationFilter} onValueChange={setClarificationFilter}>
                <SelectTrigger id="fltClarification" className="h-8 text-xs rounded-sm">
                  <SelectValue placeholder="All" />
                </SelectTrigger>
                <SelectContent className="text-xs">
                  <SelectItem value="ALL">All Clarification States</SelectItem>
                  <SelectItem value="none">None (No clarification requested)</SelectItem>
                  <SelectItem value="awaiting_user">Awaiting User</SelectItem>
                  <SelectItem value="resolved">Resolved</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="fltAttachments">Has Attachments</Label>
              <Select value={hasAttachmentsFilter} onValueChange={setHasAttachmentsFilter}>
                <SelectTrigger id="fltAttachments" className="h-8 text-xs rounded-sm">
                  <SelectValue placeholder="All" />
                </SelectTrigger>
                <SelectContent className="text-xs">
                  <SelectItem value="ALL">All Messages</SelectItem>
                  <SelectItem value="TRUE">Yes (Contains media attachment)</SelectItem>
                  <SelectItem value="FALSE">No (Text only)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="fltProject">Filter Project</Label>
              <Select value={projectFilter} onValueChange={setProjectFilter}>
                <SelectTrigger id="fltProject" className="h-8 text-xs rounded-sm">
                  <SelectValue placeholder="All Projects" />
                </SelectTrigger>
                <SelectContent className="text-xs">
                  <SelectItem value="ALL">All projects</SelectItem>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {projectFilter !== 'ALL' && (
              <div className="grid gap-1.5">
                <Label htmlFor="fltSite">Filter Site</Label>
                <Select value={siteFilter} onValueChange={setSiteFilter}>
                  <SelectTrigger id="fltSite" className="h-8 text-xs rounded-sm">
                    <SelectValue placeholder="All Sites" />
                  </SelectTrigger>
                  <SelectContent className="text-xs">
                    <SelectItem value="ALL">All Project Sites</SelectItem>
                    {sites.map((s) => (
                      <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="grid gap-1.5">
              <Label htmlFor="fltDateFrom">Date Range — From</Label>
              <Input
                type="date"
                id="fltDateFrom"
                value={dateFromFilter}
                onChange={(e) => setDateFromFilter(e.target.value)}
                className="h-8 text-xs rounded-sm"
              />
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="fltDateTo">Date Range — To</Label>
              <Input
                type="date"
                id="fltDateTo"
                value={dateToFilter}
                onChange={(e) => setDateToFilter(e.target.value)}
                className="h-8 text-xs rounded-sm"
              />
            </div>
          </div>
          <div className="flex border-t pt-4 gap-2">
            <Button size="sm" variant="outline" onClick={handleResetFilters} className="h-8 flex-1 font-bold rounded-sm">
              Reset
            </Button>
            <Button size="sm" onClick={() => setFilterSheetOpen(false)} className="h-8 flex-1 font-bold rounded-sm">
              Apply Filters
            </Button>
          </div>
        </SheetContent>
      </Sheet>

      {/* Message Details Sheet (reusing details and conversation timelines) */}
      <Sheet open={!!selectedMessageId} onOpenChange={(open) => {
        if (!open) setSelectedMessageId(null)
      }}>
        <SheetContent className="w-full sm:max-w-[480px] p-0 flex flex-col text-xs">
          <SheetHeader className="p-4 pb-3 border-b flex flex-row justify-between items-center bg-muted/10 shrink-0">
            <div>
              <SheetTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <MessageSquare className="size-4" /> Message Inspector
              </SheetTitle>
              <SheetDescription className="text-[10px] text-muted-foreground leading-none">
                Details and surrounding conversation context.
              </SheetDescription>
            </div>
          </SheetHeader>

          {/* Toggle Tab buttons */}
          <div className="flex border-b text-[11px] font-bold text-muted-foreground shrink-0 bg-muted/5">
            <button
              onClick={() => setDetailsTab('details')}
              className={`flex-1 py-2 text-center border-b-2 transition-colors ${
                detailsTab === 'details' ? 'border-primary text-foreground bg-background' : 'border-transparent hover:text-foreground'
              }`}
            >
              Trace Details
            </button>
            <button
              onClick={() => setDetailsTab('conversation')}
              className={`flex-1 py-2 text-center border-b-2 transition-colors ${
                detailsTab === 'conversation' ? 'border-primary text-foreground bg-background' : 'border-transparent hover:text-foreground'
              }`}
            >
              Conversation Context
            </button>
          </div>

          <div className="flex-1 overflow-y-auto min-h-0 bg-background">
            {isDetailLoading ? (
              <div className="flex h-64 items-center justify-center text-xs text-muted-foreground gap-2">
                <Loader2 className="size-4 animate-spin text-primary" />
                Loading trace details...
              </div>
            ) : !messageDetail ? (
              <div className="p-4 text-center text-xs text-muted-foreground">
                Message trace not found.
              </div>
            ) : detailsTab === 'details' ? (
              /* Trace Details Content */
              <div className="p-4 space-y-4">
                {/* Bubble flow preview */}
                <div className="bg-muted/15 border p-3.5 space-y-2.5">
                  <div className="flex flex-col space-y-1 self-start max-w-[90%]">
                    <span className="text-[9px] font-bold text-muted-foreground uppercase tracking-wider">
                      User ({messageDetail.sender_wa_id})
                    </span>
                    <div className="bg-muted border rounded-lg p-2.5 text-xs text-foreground font-normal leading-relaxed whitespace-pre-wrap">
                      {messageDetail.body_text || <span className="text-muted-foreground/60 italic">[Media message]</span>}
                    </div>
                  </div>

                  {messageDetail.assistant_reply && (
                    <div className="flex flex-col space-y-1 items-end self-end max-w-[90%] ml-auto text-right">
                      <span className="text-[9px] font-bold text-muted-foreground uppercase tracking-wider">
                        Assistant Reply
                      </span>
                      <div className="bg-primary/5 text-primary border border-primary/20 rounded-lg p-2.5 text-xs text-foreground font-normal leading-relaxed text-left whitespace-pre-wrap">
                        {messageDetail.assistant_reply}
                      </div>
                    </div>
                  )}
                </div>

                {/* Status and Mappings metadata */}
                <div className="grid gap-2 border p-3 bg-muted/5 font-medium">
                  <div className="flex justify-between items-center py-1">
                    <span className="text-muted-foreground font-normal">AI Processing Status</span>
                    <Badge variant="outline" className={`rounded-sm py-0 text-[10px] capitalize ${
                      messageDetail.processing_status === 'completed'
                        ? 'bg-emerald-500/5 text-emerald-700 border-emerald-500/20'
                        : 'bg-rose-500/5 text-rose-700 border-rose-500/20'
                    }`}>
                      {messageDetail.processing_status}
                    </Badge>
                  </div>
                  <div className="flex justify-between items-center py-1 border-t">
                    <span className="text-muted-foreground font-normal">Clarification State</span>
                    <Badge variant="outline" className="rounded-sm py-0 text-[10px] capitalize bg-muted text-muted-foreground">
                      {messageDetail.clarification_status.replace('_', ' ')}
                    </Badge>
                  </div>
                  {messageDetail.project && (
                    <div className="flex justify-between items-center py-1 border-t">
                      <span className="text-muted-foreground font-normal">Associated Project</span>
                      <Link to={`/today?project=${messageDetail.project.id}`} className="text-primary hover:underline font-semibold flex items-center gap-1">
                        {messageDetail.project.name} <ExternalLink className="size-2.5" />
                      </Link>
                    </div>
                  )}
                  {messageDetail.site && (
                    <div className="flex justify-between items-center py-1 border-t">
                      <span className="text-muted-foreground font-normal">Associated Site</span>
                      <Link to={`/today?project=${messageDetail.project?.id}&site=${messageDetail.site.id}`} className="text-primary hover:underline font-semibold flex items-center gap-1">
                        {messageDetail.site.name} <ExternalLink className="size-2.5" />
                      </Link>
                    </div>
                  )}
                  {messageDetail.outcome && (
                    <div className="flex justify-between items-start py-1 border-t">
                      <span className="text-muted-foreground font-normal">Created Record</span>
                      <div className="flex flex-col items-end gap-1">
                        {renderOutcomeBadge(messageDetail.outcome)}
                        <span className="text-[10px] text-muted-foreground font-mono text-right">{messageDetail.outcome.summary}</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* ID keys */}
                <div className="text-[10px] font-mono text-muted-foreground bg-muted/20 border p-2.5 grid gap-1">
                  <div>Correlation ID: {messageDetail.correlation_id}</div>
                  <div>Internal Msg ID: {messageDetail.id}</div>
                  {messageDetail.media_object_key && (
                    <div className="truncate">Media Storage Key: {messageDetail.media_object_key}</div>
                  )}
                </div>

                {/* AI execution and debugging traces */}
                {messageDetail.traces && messageDetail.traces.length > 0 && (
                  <div className="space-y-2.5">
                    <h4 className="font-semibold text-foreground uppercase tracking-wider text-[9px] border-b pb-1 text-muted-foreground">
                      Pipeline Execution Logs (Admin Debugging)
                    </h4>
                    <div className="border rounded divide-y overflow-hidden max-h-56 overflow-y-auto">
                      {messageDetail.traces.map((trace, idx) => (
                        <div key={idx} className="p-2.5 flex justify-between gap-4 items-start hover:bg-muted/10 bg-muted/5 font-medium">
                          <div>
                            <span className="font-bold text-foreground capitalize block">{trace.stage}</span>
                            {trace.error_message && (
                              <span className="text-rose-500 block text-[10px] mt-0.5 leading-tight">{trace.error_message}</span>
                            )}
                            <span className="text-[9px] text-muted-foreground block mt-0.5">
                              {trace.event_source} · {new Date(trace.created_at).toLocaleTimeString()}
                            </span>
                          </div>
                          <div className="flex flex-col items-end gap-1">
                            <Badge variant="outline" className={`rounded-sm py-0 text-[8px] font-semibold ${
                              trace.succeeded ? 'bg-emerald-500/5 text-emerald-700 border-emerald-500/20' : 'bg-rose-500/5 text-rose-700 border-rose-500/20'
                            }`}>
                              {trace.succeeded ? 'SUCCESS' : 'FAILED'}
                            </Badge>
                            {trace.duration_ms !== null && (
                              <span className="text-[9px] text-muted-foreground">{trace.duration_ms}ms</span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Raw Payloads toggle panel */}
                {messageDetail.normalized_message && (
                  <div className="border rounded overflow-hidden">
                    <details className="group">
                      <summary className="flex justify-between items-center p-2.5 bg-muted/20 border-b cursor-pointer select-none font-bold uppercase tracking-wider text-[9px] text-muted-foreground">
                        <span>Raw Internal Message Normalized Schema</span>
                        <ChevronRight className="size-3 text-muted-foreground transition-transform group-open:rotate-90" />
                      </summary>
                      <div className="p-2 bg-neutral-950 text-neutral-200 font-mono text-[10px] overflow-x-auto leading-relaxed max-h-48">
                        <pre>{JSON.stringify(messageDetail.normalized_message, null, 2)}</pre>
                      </div>
                    </details>
                  </div>
                )}
              </div>
            ) : (
              /* Conversation Context view */
              <div className="flex flex-col h-full p-4 space-y-4">
                <div className="bg-yellow-500/5 border border-yellow-500/20 text-muted-foreground p-3 rounded-[4px] text-[10px] flex gap-1.5 shrink-0">
                  <Info className="size-3.5 text-yellow-600 dark:text-yellow-400 shrink-0 mt-0.5" />
                  <span>
                    Showing up to 100 chronological messages for this identity. The message inspected to open this context is <strong>highlighted</strong>.
                  </span>
                </div>

                {isConversationLoading ? (
                  <div className="flex h-32 items-center justify-center text-xs text-muted-foreground gap-2">
                    <Loader2 className="size-4 animate-spin text-primary" />
                    Loading conversation timeline...
                  </div>
                ) : !conversationData || conversationData.items.length === 0 ? (
                  <div className="text-center italic text-muted-foreground text-xs py-8">
                    No message history found for this number.
                  </div>
                ) : (
                  <div className="space-y-3 flex-1">
                    {conversationData.items.map((msg) => {
                      const isInspected = msg.id === selectedMessageId || msg.id.replace('_reply', '') === selectedMessageId
                      const isInbound = msg.direction === 'inbound'

                      return (
                        <div
                          key={msg.id}
                          className={`flex flex-col max-w-[85%] space-y-0.5 p-2 rounded-lg border ${
                            isInbound 
                              ? 'bg-muted/30 border-border/80 self-start' 
                              : 'bg-primary/5 text-primary border-primary/20 self-end ml-auto'
                          } ${isInspected ? 'ring-2 ring-yellow-400 ring-offset-1 border-yellow-400' : ''}`}
                        >
                          <div className="flex justify-between items-center gap-4 text-[9px] text-muted-foreground font-semibold">
                            <span>{isInbound ? `USER (${msg.sender_wa_id})` : 'ASSISTANT'}</span>
                            <span>{new Date(msg.occurred_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                          </div>
                          <p className="text-xs text-foreground font-normal leading-relaxed whitespace-pre-wrap">
                            {msg.body_text || <span className="text-muted-foreground/60 italic">[Media message]</span>}
                          </p>
                          {isInspected && (
                            <span className="text-[8px] text-yellow-600 dark:text-yellow-400 font-bold block text-right">
                              (Inspected Message)
                            </span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="p-3 border-t bg-muted/10 flex justify-end shrink-0">
            <Button size="sm" onClick={() => setSelectedMessageId(null)} className="h-8 w-20 font-bold rounded-sm">
              Close
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
