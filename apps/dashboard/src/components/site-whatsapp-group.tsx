import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, MessageCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { createSiteWhatsAppGroup, fetchSiteWhatsAppGroup, type SiteWhatsAppGroup } from '@/lib/projects'
import { apiErrorMessage } from '@/lib/logo-upload'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// WA-87: one site's WhatsApp group with Mesiri in it. Mesiri makes the group,
// sends the invite to the site team and the link to the owner; here the owner
// can make it and copy the link for the client. Admins only (the API answers
// 403 to anyone else) and only once groups are switched on: otherwise nothing shows.

export function SiteWhatsAppGroupButton({ projectId, siteId }: { projectId: string; siteId: string }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const queryKey = ['site-whatsapp-group', projectId, siteId]
  const groupQuery = useQuery<SiteWhatsAppGroup>({
    queryKey,
    queryFn: () => fetchSiteWhatsAppGroup(projectId, siteId),
    retry: false,
    // A group being made turns active within a minute or so.
    refetchInterval: (query) => (query.state.data?.status === 'creating' ? 15_000 : false),
  })
  const create = useMutation({
    mutationFn: () => createSiteWhatsAppGroup(projectId, siteId),
    onSuccess: (group) => {
      toast.success('WhatsApp group', group.message ?? 'Making the group.')
      queryClient.setQueryData(queryKey, group)
    },
    onError: (err) => toast.error('Could not make the WhatsApp group', apiErrorMessage(err)),
  })

  const group = groupQuery.data
  if (!group || !group.enabled) return null

  if (group.status === 'creating') {
    return (
      <span className={cn(CHIP, 'shrink-0 bg-draft-soft text-draft')} title="WhatsApp group being made">
        <span className="sm:hidden">Group…</span>
        <span className="hidden sm:inline">WhatsApp group being made</span>
      </span>
    )
  }
  if (group.status === 'active' && group.inviteLink) {
    const link = group.inviteLink
    return (
      <Button
        variant="ghost"
        size="sm"
        className="shrink-0 gap-1.5"
        aria-label="Copy the WhatsApp group invite link"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(link)
            toast.success('Invite link copied', 'Send it to the client. Mesiri asks you before letting them in.')
          } catch {
            toast.error('Could not copy', link)
          }
        }}
      >
        <Copy className="size-3.5" /> <span className="hidden sm:inline">Group invite link</span>
      </Button>
    )
  }
  return (
    <Button
      variant="ghost"
      size="sm"
      className="shrink-0 gap-1.5"
      aria-label="Make a WhatsApp group for this site"
      disabled={create.isPending}
      onClick={() => create.mutate()}
    >
      <MessageCircle className="size-3.5" />{' '}
      <span className="hidden sm:inline">{create.isPending ? 'Making group…' : 'WhatsApp group'}</span>
    </Button>
  )
}
