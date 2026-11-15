import * as React from 'react'
import { Link, Navigate } from 'react-router-dom'
import { Building2, Calculator, Check, FileText, MessageSquareText, Package, Users } from 'lucide-react'
import { usePageTitle } from '@/lib/page-title'
import { useSetupProgress } from '@/lib/setup'
import { useModuleEnabled } from '@/lib/modules'
import { guideLink } from '@/lib/guide-links'
import { PageHeader, Section } from '@/components/page/page-kit'
import { Button } from '@/components/ui/button'
import { ImportDialog } from '@/components/materials/import-dialog'
import { BoqImportDialog } from '@/components/schedule/boq-import-dialog'
import { cn } from '@/lib/utils'
import { WithTerms } from '@/components/term'

// SS-32 (guided-onboarding-plan.md 6.6): everything a company already has, brought in from one place, in the order
// that makes sense, each row saying whether it is in yet. It owns no importer: each row opens the dialog or page
// that already does the job (PRC-05 materials workbook, the BOQ import, Documents), so a new import added there
// needs only a row here. Ticks come from the data (GET /company/setup-progress), never by hand.

interface Row {
  key: string
  icon: React.ComponentType<{ className?: string }>
  title: string
  about: string
  /** Undefined: there is nothing to tick (a file can always be added). */
  done?: boolean
  action: React.ReactNode
}

export default function BringDataPage() {
  usePageTitle('Bring your data')
  const setup = useSetupProgress()
  const isModuleEnabled = useModuleEnabled()
  const [materialsOpen, setMaterialsOpen] = React.useState(false)
  const [boqOpen, setBoqOpen] = React.useState(false)

  if (!setup.isCompanyAdmin || setup.isError) return <Navigate to="/today" replace />
  const p = setup.data
  const project = p?.first_project ?? null
  const number = p?.whatsapp_number

  const rows: Row[] = [
    {
      key: 'sites',
      icon: Building2,
      title: 'Projects and sites',
      about: 'Type them in',
      done: p?.has_site,
      action: <Button asChild size="sm" variant="outline"><Link to={guideLink('/projects')}>Projects & sites</Link></Button>,
    },
    {
      key: 'team',
      icon: Users,
      title: 'Your team',
      about: 'Share contacts on WhatsApp, or add a number',
      done: p?.has_team,
      action: <Button asChild size="sm" variant="outline"><Link to={guideLink('/team')}>Team</Link></Button>,
    },
    ...(isModuleEnabled('materials')
      ? [{
          key: 'materials',
          icon: Package,
          title: 'Materials, vendors and opening stock',
          about: 'Items, vendors and stock: one Excel',
          done: p?.has_vendors,
          action: <Button size="sm" variant="outline" onClick={() => setMaterialsOpen(true)}>Upload the Excel</Button>,
        }]
      : []),
    {
      key: 'boq',
      icon: Calculator,
      title: 'BOQ or estimate',
      about: project
        ? `Your estimate Excel for ${project.name}`
        : 'Add a project first',
      done: p?.has_boq,
      action: project ? (
        <Button size="sm" variant="outline" onClick={() => setBoqOpen(true)}>Upload the BOQ</Button>
      ) : (
        <Button asChild size="sm" variant="outline"><Link to={guideLink('/boq')}>BOQ</Link></Button>
      ),
    },
    {
      key: 'documents',
      icon: FileText,
      title: 'Drawings and documents',
      about: 'PDF, photo, Word, Excel, DWG',
      action: <Button asChild size="sm" variant="outline"><Link to={guideLink('/planning/documents')}>Documents</Link></Button>,
    },
  ]

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 pb-4 sm:px-2">
      <PageHeader title="Bring your data" />

      <Section title="In this order">
        <ol className="divide-y rounded-lg border">
          {rows.map((row, i) => {
            const Icon = row.icon
            return (
              <li key={row.key} className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center">
                <span
                  className={cn(
                    'flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums',
                    row.done && 'border-primary bg-primary text-primary-foreground',
                  )}
                  aria-label={row.done ? 'In' : row.done === false ? 'Not in yet' : undefined}
                >
                  {row.done ? <Check className="size-4" strokeWidth={3} /> : i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-sm font-semibold">
                    <Icon className="size-4 text-muted-foreground" aria-hidden /> {row.title}
                    {row.done && <span className="text-xs font-normal text-muted-foreground">· in</span>}
                  </span>
                  <span className="block text-sm text-muted-foreground"><WithTerms text={row.about} /></span>
                </span>
                <span className="shrink-0">{row.action}</span>
              </li>
            )
          })}
        </ol>
      </Section>

      <Section title="Something else?">
        <p className="m-0 flex items-start gap-2 text-sm text-muted-foreground">
          <MessageSquareText className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            Send the file on WhatsApp{number ? ` to ${number}` : ''}, with a line saying what it is
          </span>
        </p>
      </Section>

      {isModuleEnabled('materials') && <ImportDialog open={materialsOpen} onOpenChange={setMaterialsOpen} />}
      {project && <BoqImportDialog projectId={project.id} projectName={project.name} open={boqOpen} onOpenChange={setBoqOpen} />}
    </div>
  )
}
