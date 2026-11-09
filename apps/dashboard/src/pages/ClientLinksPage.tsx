import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, Copy, ExternalLink, Link2, MessageCircle, Plus, Share2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { PageError } from '@/components/dpr-page'
import { ModuleTitle } from '@/components/page/page-kit'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import { useAuth } from '@/lib/AuthContext'
import { billDay, mayBill } from '@/lib/billing'
import { clientLinkUrl, createClientLink, fetchClientLinks, revokeClientLink, whatsappShareUrl, type ClientLink } from '@/lib/client-view'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// CV-03: Client billing › Client view. The owner, an admin or finance makes a secret link for a project and sends it
// to the client on WhatsApp; the client opens it with no login (/c/:token) and sees progress, milestones, photos
// from approved site reports, bills and payments, never rates or costs. A link is shown once, when made (only its
// fingerprint is kept); revoking it turns it off at once.

export default function ClientLinksPage() {
  usePageTitle('Client view')
  const { me } = useAuth()
  const allowed = mayBill(me?.role)
  const projectId = usePlanningProject()
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={Share2} title="Client view" />
      </header>
      <p className="text-sm text-muted-foreground">
        Send your client a link to their project. They open it on the phone, no login, and see progress, milestones,
        photos from the site reports you approved, their bills and what they have paid. Never your rates, costs or suppliers.
      </p>
      {!allowed ? (
        <p className="text-sm text-muted-foreground">Sharing with clients is for the owner, admins and finance, because the bills are on the page.</p>
      ) : !projectId ? (
        <>
          <p className="text-sm font-medium">Pick the project to share</p>
          <ProjectPickList to={(id) => `/billing/client-view?project=${id}`} empty="No projects yet." />
          <Links projectId={null} />
        </>
      ) : (
        <ProjectLinks key={projectId} projectId={projectId} />
      )}
    </div>
  )
}

function ProjectLinks({ projectId }: { projectId: string }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [label, setLabel] = React.useState('')
  const [made, setMade] = React.useState<{ link: ClientLink; token: string } | null>(null)
  const create = useMutation({
    mutationFn: () => createClientLink(projectId, label.trim() || null),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['client-links'] })
      setLabel('')
      setMade(r)
    },
    onError: (e) => toast.error('Could not make the link', apiErrorMessage(e)),
  })
  return (
    <>
      <form
        className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-end"
        onSubmit={(e) => { e.preventDefault(); create.mutate() }}
      >
        <div className="flex-1">
          <Label htmlFor="client-link-label">Who is it for? (optional)</Label>
          <Input id="client-link-label" value={label} maxLength={120} onChange={(e) => setLabel(e.target.value)} placeholder="Mr. Thomas" />
        </div>
        <Button type="submit" className="gap-1.5" disabled={create.isPending}><Plus className="size-4" /> Make a link</Button>
      </form>
      <Links projectId={projectId} />
      <Link to="/billing/client-view" className="text-sm text-muted-foreground underline-offset-2 hover:underline">All projects</Link>
      <MadeDialog made={made} onClose={() => setMade(null)} />
    </>
  )
}

function MadeDialog({ made, onClose }: { made: { link: ClientLink; token: string } | null; onClose: () => void }) {
  const toast = useToast()
  if (!made) return null
  const url = clientLinkUrl(made.token)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      toast.success('Link copied')
    } catch {
      toast.error('Could not copy', 'Select the link and copy it.')
    }
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Send this link to {made.link.label ?? 'the client'}</DialogTitle>
          <DialogDescription>
            It is shown only now. Anyone with the link can see {made.link.project_name}, so send it to the client only.
            Lost it? Make a new one and turn this one off.
          </DialogDescription>
        </DialogHeader>
        <Input readOnly value={url} onFocus={(e) => e.currentTarget.select()} className="font-mono text-xs" />
        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="outline" className="gap-1.5" onClick={copy}><Copy className="size-4" /> Copy</Button>
          <div className="flex gap-2">
            <Button variant="outline" asChild className="gap-1.5">
              <a href={url} target="_blank" rel="noreferrer"><ExternalLink className="size-4" /> Open</a>
            </Button>
            <Button asChild className="gap-1.5">
              <a href={whatsappShareUrl(made.token, made.link.project_name)} target="_blank" rel="noreferrer"><MessageCircle className="size-4" /> Send on WhatsApp</a>
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Links({ projectId }: { projectId: string | null }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['client-links', projectId], queryFn: () => fetchClientLinks(projectId) })
  const revoke = useMutation({
    mutationFn: revokeClientLink,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['client-links'] })
      toast.success('Link turned off', 'It stops working now.')
    },
    onError: (e) => toast.error('Could not turn it off', apiErrorMessage(e)),
  })
  if (query.isError) return <PageError message="The links did not load." onRetry={() => query.refetch()} back={{ to: '/billing/ra-bills', label: 'RA bills' }} />
  if (!query.data) return <Skeleton className="h-24 w-full" />
  if (query.data.length === 0) {
    return projectId ? <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No links for this project yet.</p> : null
  }
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-semibold">{projectId ? 'Links for this project' : 'Links sent'}</h2>
      <ul className="divide-y rounded-lg border">
        {query.data.map((l) => {
          const off = Boolean(l.revoked_at)
          return (
            <li key={l.id} className={cn('flex flex-wrap items-center justify-between gap-3 p-3 text-sm', off && 'text-muted-foreground')}>
              <div className="flex min-w-0 items-center gap-2.5">
                <Link2 className="size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <div className="truncate font-medium">
                    {l.label ?? 'Client'}{!projectId && <span className="font-normal text-muted-foreground"> · {l.project_name}</span>}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Made {billDay(l.created_at)}{l.created_by_name ? ` by ${l.created_by_name}` : ''} ·{' '}
                    {off ? `turned off ${billDay(l.revoked_at)}` : l.open_count ? `opened ${l.open_count} time${l.open_count === 1 ? '' : 's'}, last ${billDay(l.last_opened_at)}` : 'not opened yet'}
                  </div>
                </div>
              </div>
              {!off && (
                <Button variant="outline" size="sm" className="gap-1.5" disabled={revoke.isPending}
                  onClick={() => { if (window.confirm(`Turn off ${l.label ?? 'this'} link? It stops working now.`)) revoke.mutate(l.id) }}>
                  <Ban className="size-4" /> Turn off
                </Button>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
