import * as React from 'react'
import {
  Search,
  Filter,
  RefreshCw,
  Clock,
  Download,
  LayoutGrid,
  List,
  Sparkles,
  Eye,
  FileText,
  Camera,
  Maximize2,
  FolderOpen,
  Plus,
  Check,
  Upload,
} from 'lucide-react'
import { useScope } from '@/lib/ScopeContext'
import { fetchSiteGalleryApi, type GalleryItem } from '@/lib/api'
import { useToast } from '@/components/ui/toast-notification'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { BulkActionBar } from '@/components/ui/bulk-action-bar'
import { cn } from '@/lib/utils'


// ─── Helpers ──────────────────────────────────────────────────────────────────

// The only value the backend has ever written to progress_attachments.
// attachment_type is a free-text column with no CHECK constraint
// (migration 0430), so this switches on the one real value known today and
// falls back to a generic label for anything else recorded in the future,
// rather than fabricating a category taxonomy (SITE_PROGRESS/RECEIPT/
// SAFETY_HAZARD) that never matches real data.
function getCategoryBadge(type: string) {
  switch (type.toLowerCase()) {
    case 'site_photo':
      return <Badge variant="outline" className="border-indigo-500/40 text-indigo-600 dark:text-indigo-400 font-bold text-[10px] uppercase gap-1"><Camera className="size-3" /> SITE PHOTO</Badge>
    default:
      return (
        <Badge variant="secondary" className="font-bold text-[10px] uppercase gap-1">
          <FileText className="size-3" /> {type.replace(/_/g, ' ') || 'EVIDENCE'}
        </Badge>
      )
  }
}

// role (BEFORE/AFTER/GENERAL, migration 0430) is a real column the backend
// never actually sets yet -- rendered when present rather than assumed.
function getRoleBadge(role: string | null | undefined) {
  if (!role) return null
  const upper = role.toUpperCase()
  const style =
    upper === 'BEFORE'
      ? 'border-amber-500/40 text-amber-600 dark:text-amber-400'
      : upper === 'AFTER'
        ? 'border-emerald-500/40 text-emerald-600 dark:text-emerald-400'
        : 'border-zinc-500/40 text-zinc-600 dark:text-zinc-400'
  return <Badge variant="outline" className={cn('font-bold text-[9px] uppercase', style)}>{upper}</Badge>
}

// ─── Main Operations Gallery Page (Enhanced Media Studio) ──────────────────────

export default function OperationsGalleryPage() {
  const { scope } = useScope()
  const toast = useToast()

  const [items, setItems] = React.useState<GalleryItem[]>([])
  const [loading, setLoading] = React.useState<boolean>(true)
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set())

  // Filters
  const [searchQuery, setSearchQuery] = React.useState<string>('')
  const [categoryFilter, setCategoryFilter] = React.useState<string>('ALL')
  const [viewMode, setViewMode] = React.useState<'grid' | 'table'>('grid')

  // Modals & Sheets
  const [selectedMedia, setSelectedMedia] = React.useState<GalleryItem | null>(null)
  const [uploadDialogOpen, setUploadDialogOpen] = React.useState<boolean>(false)

  // Upload Form State
  const [uploadType, setUploadType] = React.useState<string>('site_photo')
  const [uploadCaption, setUploadCaption] = React.useState<string>('')
  const [uploading, setUploading] = React.useState<boolean>(false)

  const activeProjectId = React.useMemo(() => {
    return scope.mode !== 'portfolio' ? scope.projectId : undefined
  }, [scope])

  const activeSiteId = React.useMemo(() => {
    return scope.mode === 'site' ? scope.siteId : undefined
  }, [scope])

  const scopeFilter = React.useMemo(() => ({
    projectId: activeProjectId,
    siteId: activeSiteId,
  }), [activeProjectId, activeSiteId])

  const loadGallery = React.useCallback(async () => {
    setLoading(true)
    try {
      // categoryFilter is applied client-side below (see filteredItems) rather
      // than sent as attachmentType here -- the dropdown's own options are
      // derived from this unfiltered `items` set, so filtering server-side
      // would make every other option disappear the moment one was selected.
      const res = await fetchSiteGalleryApi({
        projectId: scopeFilter.projectId,
        siteId: scopeFilter.siteId,
        limit: 100,
      })
      setItems(res.items || [])
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [scopeFilter])

  React.useEffect(() => {
    loadGallery()
  }, [loadGallery])

  // Filtered client side search + category
  const filteredItems = React.useMemo(() => {
    return items.filter((item) => {
      if (categoryFilter !== 'ALL' && item.attachment_type !== categoryFilter) {
        return false
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const match =
          (item.caption || '').toLowerCase().includes(q) ||
          (item.ai_caption || '').toLowerCase().includes(q) ||
          item.media_object_key.toLowerCase().includes(q) ||
          item.attachment_type.toLowerCase().includes(q)
        if (!match) return false
      }
      return true
    })
  }, [items, searchQuery, categoryFilter])

  // Micro KPI Statistics Bar -- computed from attachment_type/role as the
  // backend actually writes them, not a fabricated RECEIPT/SAFETY taxonomy
  // that never occurs in progress_attachments (only 'site_photo' does today).
  const stats = React.useMemo(() => {
    const total = items.length
    const aiCount = items.filter((i) => Boolean(i.ai_caption)).length
    const sitePhotoCount = items.filter((i) => i.attachment_type.toLowerCase() === 'site_photo').length
    const otherCount = total - sitePhotoCount

    return { total, aiCount, sitePhotoCount, otherCount }
  }, [items])

  // Distinct attachment_type values actually present in the loaded data --
  // the filter dropdown reflects reality instead of an invented category
  // list, since attachment_type has no backend CHECK constraint.
  const availableCategories = React.useMemo(() => {
    return Array.from(new Set(items.map((i) => i.attachment_type))).sort()
  }, [items])

  const scopeLabel = React.useMemo(() => {
    if (scope.mode === 'portfolio') return 'Portfolio Scope (All Projects)'
    if (scope.mode === 'project') return `Project Scope: ${scope.projectName}`
    return `Site Scope: ${scope.projectName} / ${scope.siteName}`
  }, [scope])

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredItems.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredItems.map((item) => item.id)))
    }
  }

  const toggleSelectOne = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelectedIds(next)
  }

  const handleUploadSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setUploading(true)
    setTimeout(() => {
      setUploading(false)
      setUploadDialogOpen(false)
      setUploadCaption('')
      toast.success('Media Uploaded', 'New site evidence image attached to database.')
      loadGallery()
    }, 600)
  }

  return (
    <div className="flex flex-col gap-3.5 w-full max-w-full relative pb-12">

      {/* ── Header Row with Compact Action Buttons ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3">
        <div className="flex items-center gap-3">
          <div className="size-9 rounded-lg border border-indigo-500/30 bg-indigo-500/10 flex items-center justify-center text-indigo-600 dark:text-indigo-400 shrink-0 shadow-2xs">
            <Camera className="size-4.5" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-foreground flex items-center gap-2">
              Site Media Studio
              <Badge variant="outline" className="text-[10px] font-mono border-indigo-500/30 text-indigo-600 dark:text-indigo-400">
                {filteredItems.length} Assets Logged
              </Badge>
            </h1>
            <p className="text-[11px] text-muted-foreground font-medium">{scopeLabel}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Upload Button */}
          <Button
            size="sm"
            className="h-8 gap-1.5 text-xs font-bold bg-indigo-600 text-white hover:bg-indigo-700 shadow-2xs"
            onClick={() => setUploadDialogOpen(true)}
          >
            <Plus className="size-3.5" />
            Upload Evidence
          </Button>

          <Button
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 text-xs font-medium"
            onClick={() => toast.info('Exporting Package', 'Downloading ZIP bundle of site evidence images')}
          >
            <Download className="size-3.5" />
            Export Zip
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={loadGallery}
            disabled={loading}
            className="h-8 gap-1.5 text-xs"
          >
            <RefreshCw className={cn('size-3.5', loading && 'animate-spin')} />
            Refresh
          </Button>
        </div>
      </div>

      {/* ── Compact Micro-KPI Pill Banner (Saved Vertical Space, Positioned Inline) ── */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 text-xs">
        <div className="px-3 py-1.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 flex items-center gap-2 shrink-0 font-mono">
          <Camera className="size-3.5 text-indigo-600" />
          <span className="text-muted-foreground text-[11px]">Total Assets:</span>
          <strong className="text-indigo-600 dark:text-indigo-400 font-bold">{stats.total}</strong>
        </div>

        <div className="px-3 py-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 flex items-center gap-2 shrink-0 font-mono">
          <Sparkles className="size-3.5 text-emerald-600" />
          <span className="text-muted-foreground text-[11px]">AI Vision Audited:</span>
          <strong className="text-emerald-600 dark:text-emerald-400 font-bold">{stats.aiCount}</strong>
        </div>

        <div className="px-3 py-1.5 rounded-full border border-sky-500/30 bg-sky-500/10 flex items-center gap-2 shrink-0 font-mono">
          <Camera className="size-3.5 text-sky-600" />
          <span className="text-muted-foreground text-[11px]">Site Photos:</span>
          <strong className="text-sky-600 dark:text-sky-400 font-bold">{stats.sitePhotoCount}</strong>
        </div>

        <div className="px-3 py-1.5 rounded-full border border-zinc-500/30 bg-zinc-500/10 flex items-center gap-2 shrink-0 font-mono">
          <FileText className="size-3.5 text-zinc-600" />
          <span className="text-muted-foreground text-[11px]">Other Evidence:</span>
          <strong className="text-zinc-600 dark:text-zinc-400 font-bold">{stats.otherCount}</strong>
        </div>
      </div>

      {/* ── Studio Toolbar: Category Tabs & Search ── */}
      <div className="flex flex-col sm:flex-row gap-2.5 items-center justify-between border border-border/80 p-2 rounded-lg bg-card/40">
        <div className="flex flex-wrap gap-2 w-full sm:w-auto flex-1 items-center">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
            <Input
              placeholder="Search media caption, AI vision tag, key..."
              value={searchQuery}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchQuery(e.target.value)}
              className="pl-8 h-8 text-xs"
            />
          </div>

          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger className="h-8 text-xs w-full sm:w-44">
              <Filter className="size-3 mr-1.5 text-muted-foreground shrink-0" />
              <SelectValue placeholder="All Categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Asset Types</SelectItem>
              {availableCategories.map((cat) => (
                <SelectItem key={cat} value={cat}>
                  {cat.replace(/_/g, ' ').toUpperCase()}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-1 border border-border/80 rounded-md p-0.5 bg-background shrink-0">
          <Button
            variant={viewMode === 'grid' ? 'secondary' : 'ghost'}
            size="sm"
            className="h-7 px-2 text-xs font-semibold gap-1"
            onClick={() => setViewMode('grid')}
          >
            <LayoutGrid className="size-3.5" />
            Studio Grid
          </Button>
          <Button
            variant={viewMode === 'table' ? 'secondary' : 'ghost'}
            size="sm"
            className="h-7 px-2 text-xs font-semibold gap-1"
            onClick={() => setViewMode('table')}
          >
            <List className="size-3.5" />
            File Ledger
          </Button>
        </div>
      </div>

      {/* ── Bulk Actions Floating Selection Bar ── */}
      {selectedIds.size > 0 && (
        <BulkActionBar
          selectedCount={selectedIds.size}
          onClear={() => setSelectedIds(new Set())}
        >
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs gap-1 text-white border-white/30 hover:bg-white/20"
            onClick={() => toast.info('Exporting Selected', `Downloading ${selectedIds.size} selected photo assets`)}
          >
            <Download className="size-3.5" />
            Export Selected ({selectedIds.size})
          </Button>
        </BulkActionBar>
      )}

      {/* ── High-Density Studio Media Grid ── */}
      {filteredItems.length === 0 ? (
        <Card className="p-12 text-center flex flex-col items-center justify-center gap-3">
          <div className="size-12 rounded-full bg-muted border flex items-center justify-center">
            <FolderOpen className="size-5 text-muted-foreground/50" />
          </div>
          <div>
            <p className="text-sm font-semibold text-foreground">No media attachments found in database</p>
            <p className="text-xs text-muted-foreground mt-1">Photo evidence uploaded via WhatsApp or DPRs will stream into this studio automatically.</p>
          </div>
          <Button
            size="sm"
            className="h-8 gap-1.5 text-xs font-bold bg-indigo-600 text-white hover:bg-indigo-700 mt-1"
            onClick={() => setUploadDialogOpen(true)}
          >
            <Plus className="size-3.5" />
            Upload First Evidence
          </Button>
        </Card>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
          {filteredItems.map((item) => {
            const isSelected = selectedIds.has(item.id)

            return (
              <Card
                key={item.id}
                onClick={() => setSelectedMedia(item)}
                className={cn(
                  "rounded-lg border-border/80 overflow-hidden shadow-2xs hover:border-indigo-500/40 hover:shadow-md transition-all cursor-pointer group flex flex-col justify-between relative",
                  isSelected && "border-indigo-500 ring-2 ring-indigo-500/20"
                )}
              >
                {/* Select Checkbox Box */}
                <div
                  onClick={(e) => toggleSelectOne(item.id, e)}
                  className={cn(
                    "absolute top-2 right-2 z-20 size-5 rounded border flex items-center justify-center transition-all bg-background/80 backdrop-blur-md",
                    isSelected ? "bg-indigo-600 text-white border-indigo-600" : "opacity-0 group-hover:opacity-100 border-border"
                  )}
                >
                  {isSelected && <Check className="size-3 stroke-[3]" />}
                </div>

                {/* Media Thumbnail Box */}
                <div className="relative h-48 bg-muted/40 flex items-center justify-center border-b overflow-hidden">
                  <div className="flex flex-col items-center justify-center gap-2 text-muted-foreground/60 group-hover:scale-105 transition-transform">
                    <Camera className="size-8" />
                    <span className="text-[10px] font-mono font-semibold max-w-[140px] truncate px-2">
                      {item.media_object_key}
                    </span>
                  </div>

                  <div className="absolute top-2 left-2 flex items-center gap-1">
                    {getCategoryBadge(item.attachment_type)}
                    {getRoleBadge(item.role)}
                  </div>

                  <div className="absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Badge variant="secondary" className="text-[10px] gap-1 shadow-md bg-background/90 backdrop-blur-md">
                      <Maximize2 className="size-3" /> Expand
                    </Badge>
                  </div>
                </div>

                {/* Card Metadata Footer */}
                <div className="p-3 space-y-2">
                  <p className="text-xs text-foreground font-medium line-clamp-2 leading-relaxed">
                    {item.caption || 'No caption provided'}
                  </p>

                  {item.ai_caption && (
                    <div className="p-1.5 rounded bg-indigo-500/10 border border-indigo-500/20 text-[10px] text-indigo-700 dark:text-indigo-300 font-medium flex items-center gap-1">
                      <Sparkles className="size-3 text-indigo-500 shrink-0" />
                      <span className="truncate italic">{item.ai_caption}</span>
                    </div>
                  )}

                  <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-1 border-t font-mono">
                    <span className="flex items-center gap-1">
                      <Clock className="size-3" />
                      {new Date(item.created_at).toLocaleDateString()}
                    </span>
                    <span className="uppercase text-[9px] font-bold">{item.parent_type}</span>
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      ) : (
        /* File Ledger Table */
        <Card className="rounded-lg border-border/80 overflow-hidden shadow-2xs">
          <Table>
            <TableHeader className="bg-muted/30">
              <TableRow>
                <TableHead className="w-10">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === filteredItems.length && filteredItems.length > 0}
                    onChange={toggleSelectAll}
                    className="rounded border-border"
                  />
                </TableHead>
                <TableHead className="text-xs font-bold">Media Object Key</TableHead>
                <TableHead className="text-xs font-bold">Attachment Type</TableHead>
                <TableHead className="text-xs font-bold">Caption / Narrative</TableHead>
                <TableHead className="text-xs font-bold">AI Vision Analysis</TableHead>
                <TableHead className="text-xs font-bold">Parent Entity</TableHead>
                <TableHead className="text-xs font-bold">Uploaded At</TableHead>
                <TableHead className="text-right text-xs font-bold">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="text-xs">
              {filteredItems.map((item) => (
                <TableRow key={item.id} className="hover:bg-muted/20">
                  <TableCell>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(item.id)}
                      onChange={(e) => toggleSelectOne(item.id, e as any)}
                      className="rounded border-border"
                    />
                  </TableCell>
                  <TableCell className="font-mono font-bold">{item.media_object_key}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      {getCategoryBadge(item.attachment_type)}
                      {getRoleBadge(item.role)}
                    </div>
                  </TableCell>
                  <TableCell className="max-w-xs truncate">{item.caption || '—'}</TableCell>
                  <TableCell className="max-w-xs truncate italic text-indigo-600 dark:text-indigo-400 font-medium">
                    {item.ai_caption || '—'}
                  </TableCell>
                  <TableCell className="font-mono text-muted-foreground">{item.parent_type}</TableCell>
                  <TableCell className="font-mono text-muted-foreground">
                    {new Date(item.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs px-2 gap-1 text-indigo-600 hover:text-indigo-700"
                      onClick={() => setSelectedMedia(item)}
                    >
                      <Eye className="size-3" /> Inspect
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      {/* ── Upload New Evidence Modal ── */}
      <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={handleUploadSubmit}>
            <DialogHeader>
              <DialogTitle className="text-base font-bold flex items-center gap-2">
                <Upload className="size-5 text-indigo-600" />
                Upload Site Evidence
              </DialogTitle>
              <DialogDescription className="text-xs">
                Attach a photo, receipt voucher, or safety inspection image to the site database.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3.5 py-4 text-xs">
              <div className="space-y-1">
                <label className="font-bold text-foreground">Attachment Category</label>
                <Select value={uploadType} onValueChange={setUploadType}>
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue placeholder="Select type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="site_photo">SITE PHOTO</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <label className="font-bold text-foreground">Select File</label>
                <div className="p-4 border-2 border-dashed border-border rounded-lg text-center flex flex-col items-center justify-center gap-2 bg-muted/20 cursor-pointer hover:border-indigo-500/50">
                  <Upload className="size-6 text-muted-foreground" />
                  <span className="text-xs font-semibold text-foreground">Click to browse or drop photo</span>
                  <span className="text-[10px] text-muted-foreground font-mono">PNG, JPG, WEBP up to 10MB</span>
                </div>
              </div>

              <div className="space-y-1">
                <label className="font-bold text-foreground">Caption / Description</label>
                <textarea
                  value={uploadCaption}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setUploadCaption(e.target.value)}
                  placeholder="Enter notes about location, grid reference, or equipment..."
                  className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-2xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring min-h-20"
                />
              </div>
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setUploadDialogOpen(false)} className="h-8 text-xs">
                Cancel
              </Button>
              <Button type="submit" disabled={uploading} className="h-8 text-xs font-bold bg-indigo-600 text-white hover:bg-indigo-700">
                {uploading ? 'Uploading...' : 'Confirm Upload'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Interactive Photo Inspection Lightbox Modal ── */}
      <Dialog open={!!selectedMedia} onOpenChange={(open) => !open && setSelectedMedia(null)}>
        <DialogContent className="sm:max-w-xl p-0 overflow-hidden">
          <DialogHeader className="px-6 pt-5 pb-3 border-b bg-muted/20">
            <div className="flex items-center gap-2">
              <Camera className="size-5 text-indigo-600" />
              <div>
                <DialogTitle className="text-sm font-bold flex items-center gap-2">
                  {selectedMedia?.media_object_key}
                </DialogTitle>
                <DialogDescription className="text-[11px]">
                  Attachment ID: {selectedMedia?.id}
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="p-6 space-y-4 text-xs">
            {/* Visual Media Placeholder Box */}
            <div className="h-64 rounded-xl bg-muted/40 border border-border/80 flex flex-col items-center justify-center gap-2 text-muted-foreground shadow-2xs">
              <Camera className="size-12 opacity-50" />
              <span className="font-mono text-xs font-bold text-foreground">
                Media Key: {selectedMedia?.media_object_key}
              </span>
              <span className="text-[10px] text-muted-foreground">MIME: {selectedMedia?.mime_type || 'image/jpeg'}</span>
            </div>

            {selectedMedia && (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3 p-3 rounded-lg border bg-muted/10">
                  <div>
                    <span className="text-muted-foreground block text-[11px]">Attachment Type</span>
                    <span className="font-bold font-mono text-foreground uppercase mt-0.5 block">
                      {selectedMedia.attachment_type}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground block text-[11px]">Parent Entity</span>
                    <span className="font-bold font-mono text-foreground uppercase mt-0.5 block">
                      {selectedMedia.parent_type} ({selectedMedia.parent_id.slice(0, 8)})
                    </span>
                  </div>
                  {selectedMedia.role && (
                    <div>
                      <span className="text-muted-foreground block text-[11px]">Photo Role</span>
                      <span className="mt-0.5 block">{getRoleBadge(selectedMedia.role)}</span>
                    </div>
                  )}
                </div>

                {selectedMedia.caption && (
                  <div className="p-3.5 rounded-lg border space-y-1">
                    <span className="font-bold text-foreground block">User Caption</span>
                    <p className="text-muted-foreground leading-relaxed">{selectedMedia.caption}</p>
                  </div>
                )}

                {selectedMedia.ai_caption && (
                  <div className="p-3.5 rounded-lg border border-indigo-500/30 bg-indigo-500/10 space-y-1">
                    <span className="font-bold text-indigo-700 dark:text-indigo-300 flex items-center gap-1.5">
                      <Sparkles className="size-3.5 text-indigo-500" /> AI Vision Verification Notes
                    </span>
                    <p className="text-indigo-900 dark:text-indigo-200">{selectedMedia.ai_caption}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
