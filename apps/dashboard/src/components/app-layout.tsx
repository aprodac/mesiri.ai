import { Outlet } from 'react-router-dom'
import { AppSidebar } from '@/components/app-sidebar'
import { ScopeBar } from '@/components/scope-bar'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import { RequireAuth } from '@/lib/AuthContext'
import { TrialBanner } from '@/components/trial-banner'

export function AppLayout() {
  return (
    <RequireAuth>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger />
            <Separator orientation="vertical" className="mr-2 h-4" />
            <ScopeBar />
          </header>
          <div className="flex flex-1 flex-col gap-4 p-4">
            <TrialBanner />
            <Outlet />
          </div>
        </SidebarInset>
      </SidebarProvider>
    </RequireAuth>
  )
}
