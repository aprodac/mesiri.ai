import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { MODULE_NAMES, useModuleEnabled, type ModuleKey } from '@/lib/modules'

/**
 * Route guard (WEB-02): renders `children` only when `module` is switched on
 * for the company, otherwise a plain explanation -- instead of a page whose
 * every request would fail with MODULE_DISABLED.
 */
export function RequireModule({ module, children }: { module: ModuleKey; children: ReactNode }) {
  const isEnabled = useModuleEnabled()
  if (isEnabled(module)) return <>{children}</>
  return (
    <div className="mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-2xl border bg-card p-8 text-center">
      <h1 className="text-lg font-semibold">{MODULE_NAMES[module]} isn't switched on</h1>
      <p className="text-sm text-muted-foreground">
        This part of Mesiri isn't included for your company. Ask the Mesiri team if you need it.
      </p>
      <Link
        to="/overview"
        className="mt-2 inline-flex min-h-10 items-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground"
      >
        Go to Today
      </Link>
    </div>
  )
}
