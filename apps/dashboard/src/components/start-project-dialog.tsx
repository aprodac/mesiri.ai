import * as React from 'react'
import { useLocation } from 'react-router-dom'
import { Building2, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useAuth } from '@/lib/AuthContext'
import { useAllowedScopes, useScope } from '@/lib/ScopeContext'
import { SCOPE_TONE, useScopeTree } from '@/lib/scope-look'
import { readStartProject, saveStartProject } from '@/lib/scope-recent'

// SCP-05: asked once, of a project manager who has more than one project and was never asked: which project do they
// mostly work on? Every later login starts there. The owner and finance start on all projects and a site engineer on
// their site, so they are never asked. Not shown over a link that already names a project, nor on the welcome page.
export function StartProjectDialog() {
  const { me } = useAuth()
  const allowed = useAllowedScopes()
  const { scope, arrivedFrom, setProjectScope } = useScope()
  const { pathname } = useLocation()
  const { tree, loading } = useScopeTree()
  const [answered, setAnswered] = React.useState(false)

  const userId = me?.user_id
  const asks = allowed.includes('project') && !allowed.includes('portfolio')
  const open =
    !answered && asks && !loading && tree.length > 1 && !arrivedFrom && pathname !== '/welcome' && readStartProject(userId) === null

  const answer = (projectId: string | 'skip') => {
    saveStartProject(userId, projectId)
    setAnswered(true)
    const t = tree.find((x) => x.project.id === projectId)
    if (t && (scope.mode === 'portfolio' || scope.projectId !== t.project.id)) setProjectScope(t.project)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && answer('skip')}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Which project do you mostly work on?</DialogTitle>
          <DialogDescription>Mesiri will open on it each time you log in. You can switch any time from the top bar.</DialogDescription>
        </DialogHeader>
        <ul className="-mx-1 grid max-h-[50svh] gap-1 overflow-y-auto">
          {tree.map(({ project, sites }) => (
            <li key={project.id}>
              <button
                type="button"
                onClick={() => answer(project.id)}
                className="flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left hover:border-foreground/25 hover:bg-muted/50"
              >
                <span className={`flex size-8 shrink-0 items-center justify-center rounded-md ${SCOPE_TONE.project}`}>
                  <Building2 className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{project.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {sites.length ? sites.map((s) => s.name).join(', ') : 'No sites yet'}
                  </span>
                </span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
        <DialogFooter>
          <Button variant="ghost" onClick={() => answer('skip')}>
            Not now
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
