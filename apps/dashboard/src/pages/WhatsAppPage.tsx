import { useSearchParams } from 'react-router-dom'
import { Segmented } from '@/components/dpr-page'
import { RequireAdmin } from '@/components/require-module'
import { useAuth } from '@/lib/AuthContext'
import { useModuleEnabled } from '@/lib/modules'
import { usePageTitle } from '@/lib/page-title'
import WhatsAppInboxPage from './WhatsAppInboxPage'
import AutomationsPage from './AutomationsPage'
import { WhatsAppMessagesTab } from './company/WhatsAppMessagesTab'

// One page for WhatsApp (sidebar sort, 24 Oct): Conversations (the inbox),
// All messages (every message and what it became; was Company >
// /company/messages) and Automations (scheduled messages; only when the
// module is on). Was "WhatsApp Inbox" and "Automations" in the sidebar.
// WEB-31: the inbox and message APIs answer admins only, so everyone else
// gets Automations alone (any role may use it), or "Admins only".

type View = 'conversations' | 'messages' | 'automations'
const TITLES: Record<View, string> = { conversations: 'Conversations', messages: 'All messages', automations: 'Automations' }

export default function WhatsAppPage() {
  const isModuleEnabled = useModuleEnabled()
  const automations = isModuleEnabled('automations')
  const { me } = useAuth()
  const isAdmin = me?.role === 'ADMIN'
  const [params, setParams] = useSearchParams()
  const raw = params.get('view')
  const view: View = !isAdmin ? 'automations' : raw === 'messages' || (raw === 'automations' && automations) ? raw : 'conversations'
  usePageTitle(`${TITLES[view]} · WhatsApp`)

  if (!isAdmin && !automations) return <RequireAdmin>{null}</RequireAdmin>

  const switchTo = (next: View) =>
    setParams(
      (prev) => {
        const kept = new URLSearchParams()
        for (const key of ['project', 'site']) {
          const v = prev.get(key)
          if (v) kept.set(key, v)
        }
        if (next !== 'conversations') kept.set('view', next)
        return kept
      },
      { replace: true },
    )

  return (
    // Full height: the conversations view is a two-pane chat that scrolls
    // inside itself; the others scroll in the area under the bar.
    <div className="-m-4 flex h-[calc(100vh-57px)] min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3 sm:px-6">
        <h1 className="text-xl font-semibold tracking-tight">WhatsApp</h1>
        {isAdmin && (
          <Segmented<View>
            label="View"
            value={view}
            onChange={switchTo}
            options={[
              { value: 'conversations', label: 'Conversations' },
              { value: 'messages', label: 'All messages' },
              ...(automations ? [{ value: 'automations' as const, label: 'Automations' }] : []),
            ]}
          />
        )}
      </div>
      {view === 'conversations' ? (
        <WhatsAppInboxPage embedded />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl p-4 sm:px-6">{view === 'messages' ? <WhatsAppMessagesTab /> : <AutomationsPage embedded />}</div>
        </div>
      )}
    </div>
  )
}
