import type { ReactNode } from 'react'
import { ArrowDown, Check } from 'lucide-react'
import { MesiriLogo, MesiriWordmark } from '@/components/brand/mesiri-logo'

// WEB-35: the frame for Sign in and Start a free trial. Wide screens get a
// panel that shows what Mesiri does -- a site's WhatsApp message becoming a
// line in the daily report -- beside the form; phones get the form alone.
// Only the look: the forms and what they call are unchanged. The panel uses
// the dark sidebar colour (app-sidebar.tsx) so the two feel like one product.

const POINTS = ['Your site team keeps using WhatsApp', 'The daily report writes itself', 'You and your client get it every day']

function Example() {
  return (
    <div className="flex max-w-sm flex-col items-center gap-3" aria-hidden="true">
      <div className="w-full rounded-xl rounded-bl-sm bg-white/95 px-3.5 py-2.5 text-sm text-neutral-900 shadow-sm">
        <p className="text-xs font-semibold text-emerald-700">Ravi · Block A</p>
        <p>12 masons, 8 helpers today. 2nd floor slab shuttering done 👍</p>
        <p className="mt-0.5 text-right text-[11px] text-neutral-500">5:42 pm</p>
      </div>
      <ArrowDown className="size-4 opacity-60" />
      <div className="w-full rounded-xl bg-white px-4 py-3 text-sm text-neutral-900 shadow-sm">
        <p className="flex items-baseline justify-between border-b border-neutral-200 pb-1.5">
          <span className="font-semibold">Daily progress report</span>
          <span className="text-xs text-neutral-500">Block A</span>
        </p>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <dt className="text-neutral-500">Workers</dt>
          <dd>20 (12 masons, 8 helpers)</dd>
          <dt className="text-neutral-500">Work</dt>
          <dd>2nd floor slab shuttering, done</dd>
        </dl>
      </div>
    </div>
  )
}

export function AuthShell({ title, subtitle, children, footer }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-svh bg-background lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="hidden flex-col justify-between bg-[#3E3C3D] p-10 text-[#EEF1F6] lg:flex">
        <MesiriWordmark className="text-2xl" />
        <div className="flex flex-col gap-8">
          <h2 className="max-w-md text-3xl leading-tight font-semibold tracking-tight">Your sites' WhatsApp updates, as a daily progress report.</h2>
          <Example />
          <ul className="flex flex-col gap-2 text-sm">
            {POINTS.map((p) => (
              <li key={p} className="flex items-center gap-2">
                <Check className="size-4 shrink-0 text-emerald-400" aria-hidden="true" /> {p}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs opacity-60">Built for construction companies in India.</p>
      </aside>

      <main className="flex flex-col items-center justify-center px-4 py-10 sm:px-8">
        <div className="flex w-full max-w-sm flex-col gap-6">
          <div className="flex flex-col gap-1.5">
            <MesiriLogo className="mb-4 lg:hidden" />
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
          </div>
          {children}
          {footer && <p className="text-sm text-muted-foreground">{footer}</p>}
        </div>
      </main>
    </div>
  )
}
