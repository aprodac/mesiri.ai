import * as React from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { ModuleTitle } from '@/components/page/page-kit'
import { cn } from '@/lib/utils'

/**
 * UX-47 (18 Nov 2026, first on the Planning pages): a module page's header as one band: a soft brand tint, the
 * module title (`ModuleTitle`: icon tile, module name, title, an optional chip) and the page's controls on the right.
 * No subtitle sentence (docs/DESIGN.md "Cues, not words"): what the page is for lives in Help. `back` adds an arrow
 * for a page reached from another (a project's BOQ).
 */
export function ModuleHeader({
  icon,
  title,
  chip,
  module: moduleName,
  back,
  children,
  className,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: React.ReactNode
  chip?: React.ReactNode
  /** Only for a page outside the module map. */
  module?: string
  back?: { to: string; label: string }
  /** The page's controls: switches, links, the one primary button. */
  children?: React.ReactNode
  className?: string
}) {
  return (
    <header
      className={cn(
        'flex flex-wrap items-center justify-between gap-x-4 gap-y-3 rounded-2xl border bg-gradient-to-br from-primary/10 via-card to-card px-4 py-3.5 sm:px-5',
        className,
      )}
    >
      <div className="flex min-w-0 items-center gap-1">
        {back && (
          <Link
            to={back.to}
            className="-ml-1.5 inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            title={`Back to ${back.label}`}
            aria-label={`Back to ${back.label}`}
          >
            <ArrowLeft className="size-[18px]" />
          </Link>
        )}
        <ModuleTitle icon={icon} title={title} chip={chip} module={moduleName} />
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </header>
  )
}
