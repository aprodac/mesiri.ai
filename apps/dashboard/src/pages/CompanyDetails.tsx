import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Building2, FileText, MessageSquare } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { DprSection, PageError, PageHeader } from '@/components/dpr-page'
import { fetchCompany, fetchCompanySummary } from '@/lib/api'
import { usePageTitle } from '@/lib/page-title'
import { SettingsTab } from './company/SettingsTab'
import { BrandingTab } from './company/BrandingTab'

// WEB-28: the company on one page -- its details and the DPR letterhead
// they print on -- instead of five tabs. The Team tab (a copy of the Team
// page) and the overview boxes (role counts, "integration coverage") are
// gone; the company-wide WhatsApp message log is the WhatsApp page's
// "All messages" view.

export default function CompanyDetails() {
  usePageTitle('Company')
  const [searchParams] = useSearchParams()
  const company = useQuery({ queryKey: ['company-profile'], queryFn: fetchCompany })
  const summary = useQuery({ queryKey: ['company-summary'], queryFn: fetchCompanySummary })

  // ?tab=letterhead (the getting-started checklist): scroll to it.
  const tab = searchParams.get('tab')
  React.useEffect(() => {
    if (company.data && tab) document.getElementById(tab === 'settings' ? 'details' : tab)?.scrollIntoView({ block: 'start' })
  }, [company.data, tab])

  if (company.isError) {
    return <PageError message="Your company details could not be loaded." onRetry={() => company.refetch()} back={{ to: '/today', label: 'Back to Today' }} />
  }
  const s = summary.data

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Company"
        subtitle={
          s ? (
            <>
              {company.data?.name} ·{' '}
              <Link to="/team" className="hover:text-foreground hover:underline">
                {s.active_users} {s.active_users === 1 ? 'person' : 'people'}
              </Link>{' '}
              ·{' '}
              <Link to="/projects" className="hover:text-foreground hover:underline">
                {s.total_projects} {s.total_projects === 1 ? 'project' : 'projects'}, {s.total_sites} {s.total_sites === 1 ? 'site' : 'sites'}
              </Link>
            </>
          ) : (
            company.data?.name ?? 'Loading…'
          )
        }
      />

      {company.isLoading || !company.data ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-40 rounded-lg" />
          <Skeleton className="h-64 rounded-lg" />
        </div>
      ) : (
        <div className="flex flex-col">
          <DprSection id="details" icon={Building2} title="Company details">
            <SettingsTab key={company.dataUpdatedAt} company={company.data} />
          </DprSection>
          <DprSection id="letterhead" icon={FileText} title="Letterhead on the DPR">
            <BrandingTab />
          </DprSection>
          <DprSection
            icon={MessageSquare}
            title="WhatsApp"
            meta={s ? `${s.wa_mapped_users} of ${s.total_users} people have a number` : undefined}
            action={
              <Link to="/whatsapp?view=messages" className="text-sm font-medium text-muted-foreground hover:text-foreground hover:underline">
                All messages →
              </Link>
            }
          >
            {s && s.wa_unmapped_users > 0 && (
              <p className="text-sm text-draft">
                {s.wa_unmapped_users} {s.wa_unmapped_users === 1 ? 'person has' : 'people have'} no WhatsApp number and can't send updates.{' '}
                <Link to="/team" className="font-medium underline">
                  Team
                </Link>
              </p>
            )}
          </DprSection>
        </div>
      )}
    </div>
  )
}
