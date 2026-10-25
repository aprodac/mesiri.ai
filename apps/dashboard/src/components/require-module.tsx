import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { MODULE_NAMES, useModuleEnabled, type ModuleKey } from '@/lib/modules'
import { useAuth } from '@/lib/AuthContext'

/**
 * Route guard (WEB-02): renders `children` only when `module` is switched on
 * for the company, otherwise a plain explanation -- instead of a page whose
 * every request would fail with MODULE_DISABLED.
 */
export function RequireModule({ module, children }: { module: ModuleKey; children: ReactNode }) {
  const isEnabled = useModuleEnabled()
  if (isEnabled(module)) return <>{children}</>
  return (
    <NotForYou
      title={`${MODULE_NAMES[module]} isn't switched on`}
      body="This part of Mesiri isn't included for your company. Ask the Mesiri team if you need it."
    />
  )
}

/**
 * Route guard (WEB-31): pages whose API answers admins only (`require_admin`),
 * e.g. the WhatsApp Inbox. Others get a plain explanation instead of an
 * error or an empty page.
 */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const { me } = useAuth()
  if (me?.role === 'ADMIN') return <>{children}</>
  return <NotForYou title="Admins only" body="Only your company's admins can open this page." />
}

function NotForYou({ title, body }: { title: string; body: string }) {
  return (
    <div className="mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-2xl border bg-card p-8 text-center">
      <h1 className="text-lg font-semibold">{title}</h1>
      <p className="text-sm text-muted-foreground">{body}</p>
      <Link
        to="/today"
        className="mt-2 inline-flex min-h-10 items-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground"
      >
        Go to Today
      </Link>
    </div>
  )
}
