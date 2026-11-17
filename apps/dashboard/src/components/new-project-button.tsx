import * as React from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AddEditProjectDialog } from '@/components/project-dialogs'
import { useAuth } from '@/lib/AuthContext'
import { mayCreateProject } from '@/lib/permissions'
import { useReadOnly } from '@/lib/trial'

/**
 * WEB-100: the one "New project" button (Projects & Sites, Project start). Shown only to the people the API lets make
 * one (owner, project manager) and never in a read-only trial, so nobody is offered a button that answers "not allowed".
 * `afterCreate` says where the new project opens; without it, its project page.
 */
export function NewProjectButton({
  afterCreate,
  size = 'sm',
  variant = 'default',
  className,
  guide,
}: {
  afterCreate?: (projectId: string) => string
  size?: 'sm' | 'default'
  variant?: 'default' | 'outline'
  className?: string
  guide?: string
}) {
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const [open, setOpen] = React.useState(false)
  if (readOnly || !mayCreateProject(me?.role)) return null
  return (
    <>
      <Button size={size} variant={variant} className={className ?? 'gap-1.5 font-semibold'} onClick={() => setOpen(true)} data-guide={guide}>
        <Plus className="size-4" /> New project
      </Button>
      <AddEditProjectDialog open={open} onOpenChange={setOpen} onSuccess={() => undefined} afterCreate={afterCreate} />
    </>
  )
}
