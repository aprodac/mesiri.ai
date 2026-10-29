import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  MessageSquare,
  ArrowUpDown,
  Search,
  SlidersHorizontal,
  ChevronRight,
  AlertTriangle,
  Loader2,
  Settings,
  Inbox,
  Sparkles,
  Mic,
  Image as ImageIcon,
  FileText,
  MapPin,
  MessageCircle,
} from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { Fact, Facts, SheetHero, SheetSection } from '@/components/detail-sheet'
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
      {/* WEB-39: one message, laid out like every side panel (detail-sheet.tsx):
          what was sent and what Mesiri replied as chat bubbles, what it became,
          a link to the whole chat; ids, pipeline steps and raw data folded
          under "For support". */}
      <Sheet open={!!selectedMessageId} onOpenChange={(open) => {
        if (!open) setSelectedMessageId(null)
      }}>
        <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-[480px]">
          {isDetailLoading ? (
            <div className="flex h-64 items-center justify-center gap-2 text-sm text-muted-foreground">
              <SheetTitle className="sr-only">Loading</SheetTitle>
              <Loader2 className="size-4 animate-spin" /> Loading…
            </div>
          ) : !messageDetail ? (
            <div className="p-6 text-center text-sm text-muted-foreground">
              <SheetTitle className="sr-only">Not found</SheetTitle>
              This message could not be found.
            </div>
          ) : (
            (() => {
              const failed = messageDetail.processing_status === 'failed' || Boolean(messageDetail.error_code)
              const waiting = ['pending', 'processing'].includes(messageDetail.processing_status)
              const asking = messageDetail.clarification_status === 'awaiting_user'
              const at = (iso: string) => new Date(iso).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
              const number = messageDetail.sender_wa_id.replace(/\D/g, '')
              return (
                <>
                  <SheetHero
                    tone={failed ? 'out' : waiting || asking ? 'warn' : messageDetail.outcome ? 'in' : 'neutral'}
                    kicker={failed ? 'Not handled' : waiting ? 'Waiting for Mesiri' : asking ? 'Mesiri asked a question' : messageDetail.outcome ? 'Filed' : 'Handled'}
                    title={`Message from ${user.full_name}`}
                  >
                    <span>{at(messageDetail.received_at)}</span>
                    {messageDetail.site && <span>{messageDetail.site.name}</span>}
                  </SheetHero>

                  <SheetSection title="The message">
                    <div className="flex flex-col gap-2 rounded-lg bg-muted/30 p-3">
                      <div className="max-w-[90%] self-start rounded-xl rounded-bl-sm border bg-background px-3 py-2 text-sm whitespace-pre-wrap">
                        {messageDetail.body_text || <span className="text-muted-foreground">{messageDetail.message_type === 'image' ? 'Photo' : messageDetail.message_type === 'audio' ? 'Voice note' : 'No text'}</span>}
                      </div>
                      {messageDetail.assistant_reply && (
                        <div className="max-w-[90%] self-end rounded-xl rounded-br-sm border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm whitespace-pre-wrap dark:border-emerald-900 dark:bg-emerald-950/50">
                          <p className="mb-0.5 text-xs font-semibold text-emerald-700 dark:text-emerald-400">Mesiri</p>
                          {messageDetail.assistant_reply}
                        </div>
                      )}
                    </div>
                    {failed && (
                      <p className="flex items-start gap-1.5 text-sm text-destructive" title={messageDetail.error_code ?? undefined}>
                        <AlertTriangle className="mt-0.5 size-4 shrink-0" /> Mesiri could not handle this message. Ask them to send it again.
                      </p>
                    )}
                  </SheetSection>

                  <SheetSection title="What it became" className="border-t">
                    <Facts>
                      <Fact label="Record" missing="Nothing was filed">
                        {messageDetail.outcome && (
                          <span className="flex flex-col">
                            <span className="font-medium">{messageDetail.outcome.record_type.replace(/([A-Z])/g, ' $1').replace(/_/g, ' ').trim()}</span>
                            {messageDetail.outcome.summary && <span className="text-muted-foreground">{messageDetail.outcome.summary}</span>}
                          </span>
                        )}
                      </Fact>
                      <Fact label="Project">{messageDetail.project?.name}</Fact>
                      <Fact label="Site">{messageDetail.site?.name}</Fact>
                      {messageDetail.clarification_status !== 'none' && (
                        <Fact label="Question">
                          {asking ? 'Waiting for their answer' : messageDetail.clarification_status === 'resolved' ? 'Answered' : 'No answer came'}
                        </Fact>
                      )}
                    </Facts>
                  </SheetSection>

                  <SheetSection title="For support" className="border-t">
                    <details className="group text-sm">
                      <summary className="flex cursor-pointer items-center gap-1 text-muted-foreground select-none hover:text-foreground">
                        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" /> Technical details
                      </summary>
                      <div className="mt-3 flex flex-col gap-3">
                        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-xs text-muted-foreground">
                          <dt>Reference</dt>
                          <dd className="break-all">{messageDetail.correlation_id}</dd>
                          <dt>Status</dt>
                          <dd>{messageDetail.processing_status}{messageDetail.error_code ? ` · ${messageDetail.error_code}` : ''}</dd>
                        </dl>
                        {messageDetail.traces && messageDetail.traces.length > 0 && (
                          <ul className="divide-y rounded-lg border text-xs">
                            {messageDetail.traces.map((trace, idx) => (
                              <li key={idx} className="flex items-start justify-between gap-3 px-3 py-2">
                                <span className="min-w-0">
                                  <span className="font-medium capitalize">{trace.stage.replace(/_/g, ' ')}</span>
                                  {trace.error_message && <span className="block text-destructive">{trace.error_message}</span>}
                                </span>
                                <span className={trace.succeeded ? 'shrink-0 text-success' : 'shrink-0 text-destructive'}>
                                  {trace.succeeded ? 'OK' : 'Failed'}
                                  {trace.duration_ms !== null && trace.duration_ms !== undefined ? ` · ${trace.duration_ms} ms` : ''}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                        {messageDetail.normalized_message && (
                          <pre className="max-h-48 overflow-auto rounded-lg bg-neutral-950 p-2 text-[10px] leading-relaxed text-neutral-200">
                            {JSON.stringify(messageDetail.normalized_message, null, 2)}
                          </pre>
                        )}
                      </div>
                    </details>
                  </SheetSection>

                  <SheetFooter className="flex-row items-center gap-2 border-t px-5 py-3">
                    {number && (
                      <Button asChild size="sm" variant="outline" className="gap-1.5">
                        <Link to={`/whatsapp?with=${number}`}>
                          <MessageSquare className="size-3.5" /> Open the whole chat
                        </Link>
                      </Button>
                    )}
                  </SheetFooter>
                </>
              )
            })()
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}
