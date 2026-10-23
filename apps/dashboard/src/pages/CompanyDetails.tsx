import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  Building2,
  Users,
  MessageSquare,
  Settings,
  Briefcase,
  Loader2,
  FileText,
} from 'lucide-react'
import { fetchCompany, fetchCompanySummary } from '@/lib/api'
import { OverviewTab } from './company/OverviewTab'
import { UsersTab } from './company/UsersTab'
import { WhatsAppMessagesTab } from './company/WhatsAppMessagesTab'
import { SettingsTab } from './company/SettingsTab'
import { BrandingTab } from './company/BrandingTab'
import { Badge } from '@/components/ui/badge'

type TabType = 'overview' | 'users' | 'messages' | 'letterhead' | 'settings'

export default function CompanyDetails() {
  const [searchParams] = useSearchParams()
  // ?tab=letterhead opens a tab directly (the getting-started checklist links here).
  const [activeTab, setActiveTab] = React.useState<TabType>(() => {
    const tab = searchParams.get('tab')
    return tab && ['users', 'messages', 'letterhead', 'settings'].includes(tab) ? (tab as TabType) : 'overview'
  })

  // Fetch Company Profile
  const {
    data: company,
    isLoading: isLoadingCompany,
    isError: isErrorCompany,
    error: errorCompany,
  } = useQuery({
    queryKey: ['company-profile'],
    queryFn: fetchCompany,
  })

  // Fetch Company Summary Metrics
  const {
    data: summary,
    isLoading: isLoadingSummary,
    isError: isErrorSummary,
    error: errorSummary,
  } = useQuery({
    queryKey: ['company-summary'],
    queryFn: fetchCompanySummary,
    refetchInterval: activeTab === 'overview' ? 30000 : false, // Poll only on overview tab
  })

  if (isLoadingCompany || isLoadingSummary) {
    return (
      <div className="flex h-screen items-center justify-center text-xs text-muted-foreground gap-2">
        <Loader2 className="size-4 animate-spin text-primary" />
        Loading company details...
      </div>
    )
  }

  if (isErrorCompany || isErrorSummary) {
    const errorMsg =
      (errorCompany instanceof Error ? errorCompany.message : '') ||
      (errorSummary instanceof Error ? errorSummary.message : '') ||
      'Failed to load organization settings.'
    return (
      <div className="p-6">
        <div className="bg-destructive/10 border border-destructive text-destructive text-xs p-4 rounded text-center max-w-xl mx-auto">
          <p className="font-semibold mb-1">Data Retrieval Error</p>
          <p>{errorMsg}</p>
        </div>
      </div>
    )
  }

  if (!company || !summary) return null

  return (
    <div className="flex-1 space-y-6 p-6">
      {/* Header section */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center border-b pb-4 gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold tracking-tight text-foreground">{company.name}</h1>
            <Badge
              variant={company.status === 'active' ? 'default' : 'outline'}
              className={`text-[9px] rounded px-1.5 py-0.2 uppercase font-semibold ${
                company.status === 'active'
                  ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-none'
                  : 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-none'
              }`}
            >
              {company.status}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5 font-normal">
            <Briefcase className="size-3.5" /> Your company's details, team and letterhead
          </p>
        </div>

      </div>

      {/* Navigation tabs row */}
      <div className="flex border-b border-border/60 gap-1 overflow-x-auto">
        <button
          onClick={() => setActiveTab('overview')}
          className={`flex items-center gap-1.5 px-4 py-2 border-b-2 font-medium text-xs transition-colors whitespace-nowrap ${
            activeTab === 'overview'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <Building2 className="size-3.5" />
          Overview
        </button>
        <button
          onClick={() => setActiveTab('users')}
          className={`flex items-center gap-1.5 px-4 py-2 border-b-2 font-medium text-xs transition-colors whitespace-nowrap ${
            activeTab === 'users'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <Users className="size-3.5" />
          Team
        </button>
        <button
          onClick={() => setActiveTab('messages')}
          className={`flex items-center gap-1.5 px-4 py-2 border-b-2 font-medium text-xs transition-colors whitespace-nowrap ${
            activeTab === 'messages'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <MessageSquare className="size-3.5" />
          WhatsApp History
        </button>
        <button
          onClick={() => setActiveTab('letterhead')}
          className={`flex items-center gap-1.5 px-4 py-2 border-b-2 font-medium text-xs transition-colors whitespace-nowrap ${
            activeTab === 'letterhead'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <FileText className="size-3.5" />
          Letterhead
        </button>
        <button
          onClick={() => setActiveTab('settings')}
          className={`flex items-center gap-1.5 px-4 py-2 border-b-2 font-medium text-xs transition-colors whitespace-nowrap ${
            activeTab === 'settings'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <Settings className="size-3.5" />
          Settings
        </button>
      </div>

      {/* Tab Panel contents */}
      <div className="mt-4">
        {activeTab === 'overview' && (
          <OverviewTab summary={summary} onSelectTab={(tab) => setActiveTab(tab as TabType)} />
        )}
        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'messages' && <WhatsAppMessagesTab />}
        {activeTab === 'letterhead' && <BrandingTab />}
        {activeTab === 'settings' && <SettingsTab company={company} />}
      </div>
    </div>
  )
}
