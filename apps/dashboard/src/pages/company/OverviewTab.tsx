import { Link } from 'react-router-dom'
import {
  Users,
  Building,
  MessageSquare,
  ShieldAlert,
  ArrowRight,
  Clock,
} from 'lucide-react'
import type { CompanySummary } from '@/lib/api'

interface OverviewTabProps {
  summary: CompanySummary
  onSelectTab: (tab: string) => void
}

export function OverviewTab({ summary, onSelectTab }: OverviewTabProps) {
  // Format dates
  const formatLastActive = (dateStr?: string | null) => {
    if (!dateStr) return 'No recent activity'
    return new Date(dateStr).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  }

  return (
    <div className="grid gap-6">
      {/* Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Users Card */}
        <div className="border border-border/60 bg-card rounded p-4 flex items-start gap-4">
          <div className="p-2.5 bg-primary/10 rounded text-primary">
            <Users className="size-5" />
          </div>
          <div>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Team
            </h3>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-2xl font-bold tracking-tight font-mono">
                {summary.total_users}
              </span>
              <span className="text-xs text-emerald-500 font-medium">
                {summary.active_users} Active
              </span>
            </div>
            <button
              onClick={() => onSelectTab('users')}
              className="mt-3 text-xs font-medium text-primary hover:underline inline-flex items-center gap-1"
            >
              Manage team <ArrowRight className="size-3" />
            </button>
          </div>
        </div>

        {/* Projects Card */}
        <div className="border border-border/60 bg-card rounded p-4 flex items-start gap-4">
          <div className="p-2.5 bg-primary/10 rounded text-primary">
            <Building className="size-5" />
          </div>
          <div>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Projects & sites
            </h3>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-2xl font-bold tracking-tight font-mono">
                {summary.total_projects}
              </span>
              <span className="text-xs text-muted-foreground">
                Projects
              </span>
              <span className="text-2xl font-bold tracking-tight font-mono ml-2">
                {summary.total_sites}
              </span>
              <span className="text-xs text-muted-foreground">
                Sites
              </span>
            </div>
            <Link
              to="/projects"
              className="mt-3 text-xs font-medium text-primary hover:underline inline-flex items-center gap-1"
            >
              View Projects & Sites <ArrowRight className="size-3" />
            </Link>
          </div>
        </div>

        {/* WhatsApp Card */}
        <div className="border border-border/60 bg-card rounded p-4 flex items-start gap-4">
          <div className="p-2.5 bg-primary/10 rounded text-primary">
            <MessageSquare className="size-5" />
          </div>
          <div>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              WhatsApp
            </h3>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-2xl font-bold tracking-tight font-mono">
                {summary.wa_mapped_users}
              </span>
              <span className="text-xs text-emerald-500 font-medium">
                Number added
              </span>
              <span className="text-2xl font-bold tracking-tight font-mono ml-2">
                {summary.wa_unmapped_users}
              </span>
              <span className="text-xs text-rose-500 font-medium">
                No number
              </span>
            </div>
            <button
              onClick={() => onSelectTab('messages')}
              className="mt-3 text-xs font-medium text-primary hover:underline inline-flex items-center gap-1"
            >
              Explore Messages <ArrowRight className="size-3" />
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Role Distribution */}
        <div className="border border-border/60 rounded bg-card p-5">
          <h3 className="font-semibold text-foreground text-sm mb-4">
            Role Distribution
          </h3>
          <div className="space-y-3">
            <div className="flex justify-between items-center border-b border-border/30 pb-2 text-xs">
              <span className="text-muted-foreground font-medium">Admin / Director</span>
              <span className="font-mono font-bold bg-muted px-2 py-0.5 rounded text-foreground">
                {summary.admin_count}
              </span>
            </div>
            <div className="flex justify-between items-center border-b border-border/30 pb-2 text-xs">
              <span className="text-muted-foreground font-medium">Project Manager</span>
              <span className="font-mono font-bold bg-muted px-2 py-0.5 rounded text-foreground">
                {summary.pm_count}
              </span>
            </div>
            <div className="flex justify-between items-center border-b border-border/30 pb-2 text-xs">
              <span className="text-muted-foreground font-medium">Site Engineer</span>
              <span className="font-mono font-bold bg-muted px-2 py-0.5 rounded text-foreground">
                {summary.site_engineer_count}
              </span>
            </div>
            <div className="flex justify-between items-center border-b border-border/30 pb-2 text-xs">
              <span className="text-muted-foreground font-medium">Finance / Accountant</span>
              <span className="font-mono font-bold bg-muted px-2 py-0.5 rounded text-foreground">
                {summary.finance_count}
              </span>
            </div>
          </div>
        </div>

        {/* WhatsApp Coverage / Ingestion details */}
        <div className="border border-border/60 rounded bg-card p-5 flex flex-col justify-between">
          <div>
            <h3 className="font-semibold text-foreground text-sm mb-4">
              WhatsApp Integration Coverage
            </h3>
            <div className="space-y-4 text-xs">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Active WhatsApp Conversations</span>
                <span className="font-mono font-semibold text-foreground">
                  {summary.active_conversations_count}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Messages Received Today</span>
                <span className="font-mono font-semibold text-foreground">
                  {summary.messages_received_today}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Messages Requiring Clarification</span>
                <span className="font-mono font-semibold text-amber-600 dark:text-amber-400 flex items-center gap-1">
                  {summary.messages_requiring_clarification > 0 && <ShieldAlert className="size-3.5" />}
                  {summary.messages_requiring_clarification}
                </span>
              </div>
              <div className="flex justify-between items-center border-t border-border/30 pt-3">
                <span className="text-muted-foreground flex items-center gap-1">
                  <Clock className="size-3.5" /> Last WhatsApp Activity
                </span>
                <span className="font-medium text-foreground">
                  {formatLastActive(summary.last_whatsapp_activity)}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-6 border-t border-border/40 pt-4 flex justify-end">
            <button
              onClick={() => onSelectTab('messages')}
              className="text-xs font-semibold text-primary hover:text-primary/80 transition-colors inline-flex items-center gap-1"
            >
              View WhatsApp Messages <ArrowRight className="size-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
