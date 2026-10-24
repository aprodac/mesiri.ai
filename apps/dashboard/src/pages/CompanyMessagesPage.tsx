import { DprHeader } from '@/components/dpr-page'
import { usePageTitle } from '@/lib/page-title'
import { WhatsAppMessagesTab } from './company/WhatsAppMessagesTab'

/** Every WhatsApp message the company received, filterable by project, site
 * and how it was handled (WEB-28: was the Company page's "WhatsApp History"
 * tab). The Inbox shows the same messages as conversations. */
export default function CompanyMessagesPage() {
  usePageTitle('WhatsApp messages')
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader back={{ to: '/company', label: 'Company' }} crumb="WhatsApp" title="WhatsApp messages" date="Everything sent to Mesiri, and what it became" />
      <WhatsAppMessagesTab />
    </div>
  )
}
