import { Link } from 'react-router-dom'
import { Building, Building2, ChevronRight, Clock, History, ListChecks, MessageSquare, Puzzle, Upload, Users } from 'lucide-react'
import { MODULE_KEYS, MODULE_NAMES, useModuleEnabled, type ModuleKey } from '@/lib/modules'
import { SETUP_URL, setupCounts, useGuideSteps, useSetupProgress } from '@/lib/setup'
import { usePageTitle } from '@/lib/page-title'
import { PageHeader, Section } from '@/components/page/page-kit'
import { cn } from '@/lib/utils'

// UX-04: everything an admin sets up once, in one place at the bottom of the sidebar. Each row opens the page
// that already does the job (their addresses are unchanged), so this page owns no settings of its own.

const ROWS = [
  { title: 'Company', about: 'Name, GSTIN, logo, report time', url: '/company', icon: Building },
  { title: 'Projects & sites', about: 'Sites and who reports', url: '/projects', icon: Building2 },
  { title: 'Team', about: 'People, roles and sites', url: '/team', icon: Users },
  { title: 'WhatsApp', about: 'Messages and site groups', url: '/whatsapp', icon: MessageSquare },
  { title: 'Bring your data', about: 'Excel and files in', url: '/bring-data', icon: Upload },
  { title: 'Activity log', about: 'Who changed what, when', url: '/settings/activity', icon: History },
  { title: 'Scheduled messages', about: 'Reminders on a timetable', url: '/whatsapp?view=automations', icon: Clock, module: 'automations' as ModuleKey },
]


export default function SettingsPage() {
  usePageTitle('Settings')
  const isModuleEnabled = useModuleEnabled()
  const setup = useSetupProgress()
  const guideSteps = useGuideSteps()
  const counts = setup.data ? setupCounts(setup.data, guideSteps) : null

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-4 sm:px-2">
      <PageHeader title="Settings" />

      {counts && counts.done < counts.total && (
        <Link
          to={SETUP_URL}
          data-guide="settings.finish"
          className="flex items-center gap-3 rounded-lg border border-draft/30 bg-draft-soft px-4 py-3 text-sm transition-colors hover:border-draft/60"
        >
          <ListChecks className="size-5 shrink-0 text-draft" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="font-semibold text-foreground">Finish setting up</span>
            <span className="block text-muted-foreground">
              {counts.done} of {counts.total} steps done. The rest takes a few minutes.
            </span>
          </span>
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        </Link>
      )}

      <Section title="Set up">
        <ul className="divide-y rounded-lg border" data-guide="settings.setup">
          {ROWS.filter((row) => isModuleEnabled(row.module)).map((row) => {
            const Icon = row.icon
            return (
              <li key={row.url}>
                <Link to={row.url} className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/60">
                  <Icon className="size-5 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold">{row.title}</span>
                    <span className="block text-sm text-muted-foreground">{row.about}</span>
                  </span>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                </Link>
              </li>
            )
          })}
        </ul>
      </Section>

      <Section title="Modules" note="Switched on by the Mesiri team. Ask us to add one.">
        <ul className="flex flex-wrap gap-2" data-guide="settings.modules">
          {MODULE_KEYS.map((key) => {
            const on = isModuleEnabled(key)
            return (
              <li
                key={key}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm',
                  on ? 'border-success/30 bg-success-soft text-success' : 'text-muted-foreground',
                )}
              >
                <Puzzle className="size-3.5" aria-hidden />
                {MODULE_NAMES[key]}
                <span className="sr-only">{on ? 'on' : 'off'}</span>
                {!on && <span className="text-xs">· off</span>}
              </li>
            )
          })}
        </ul>
      </Section>
    </div>
  )
}
