import * as React from 'react'
import { ListPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { NewTaskDialog } from '@/components/tasks/new-task-dialog'
import { useAuth } from '@/lib/AuthContext'
import { useModuleEnabled } from '@/lib/modules'
import { useScope } from '@/lib/ScopeContext'
import { CREATE_ROLES, type TaskPrefill } from '@/lib/tasks'
import { useReadOnly } from '@/lib/trial'

// TSK-03: "Make a task" from what needs one: an issue, a schedule activity. Shown only when the company has Tasks
// and this person may give tasks (the API's own rule, logic.may_create); the new task links back to where it came from.

export function MakeTaskButton({ prefill, size = 'sm', variant = 'outline' }: {
  prefill: TaskPrefill
  size?: 'sm' | 'default'
  variant?: 'outline' | 'ghost' | 'default'
}) {
  const { me } = useAuth()
  const { scope } = useScope()
  const readOnly = useReadOnly()
  const enabled = useModuleEnabled()
  const [open, setOpen] = React.useState(false)
  if (!me || readOnly || !enabled('tasks') || !CREATE_ROLES.includes((me.role || '').toUpperCase())) return null
  return (
    <>
      <Button size={size} variant={variant} className="gap-1.5" onClick={() => setOpen(true)}>
        <ListPlus className="size-4" /> Make a task
      </Button>
      <NewTaskDialog open={open} onOpenChange={setOpen} scope={scope} prefill={prefill} />
    </>
  )
}
