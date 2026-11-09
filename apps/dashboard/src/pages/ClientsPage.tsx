import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Pencil, Plus, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { PageError } from '@/components/dpr-page'
import { useAuth } from '@/lib/AuthContext'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { useScope } from '@/lib/ScopeContext'
import { createClient, fetchClients, mayBill, rupees, updateClient, type Client, type ClientInput } from '@/lib/billing'
import { ModuleTitle } from '@/components/page/page-kit'

// NXT-01: Client billing › Clients. Each client the company builds for, their projects and contract values.
// A project's terms are set from Planning › Project start (Client and contract) or the RA bills page.

const FIELDS: { key: keyof ClientInput; label: string; placeholder?: string }[] = [
  { key: 'name', label: 'Name', placeholder: 'Mr. Abdullakutty' },
  { key: 'contact_person', label: 'Contact person' },
  { key: 'phone', label: 'Phone', placeholder: '98470 12345' },
  { key: 'email', label: 'Email' },
  { key: 'gstin', label: 'GSTIN', placeholder: '32ABCDE1234F1Z5' },
  { key: 'address', label: 'Address', placeholder: 'Kondotty, Malappuram' },
]

export default function ClientsPage() {
  usePageTitle('Clients')
  const { me } = useAuth()
  const allowed = mayBill(me?.role)
  const query = useQuery({ queryKey: ['billing-clients'], queryFn: fetchClients, enabled: allowed })
  // SCP-03: with a project picked, the clients of that project.
  const { scope } = useScope()
  const projectId = scope.mode === 'portfolio' ? null : scope.projectId
  const clients = query.data && projectId ? query.data.filter((c) => c.projects?.some((p) => p.id === projectId)) : query.data
  const [editing, setEditing] = React.useState<Client | 'new' | null>(null)

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={Users} title="Clients" />
        {allowed && <Button size="sm" className="gap-1.5" onClick={() => setEditing('new')}><Plus className="size-4" /> Add a client</Button>}
      </header>
      {!allowed ? (
        <p className="text-sm text-muted-foreground">Clients, contracts and bills are for the owner, admins and finance.</p>
      ) : query.isError ? (
        <PageError message="The clients did not load." onRetry={() => query.refetch()} back={{ to: '/', label: 'Home' }} />
      ) : !clients ? (
        <Skeleton className="h-40 w-full" />
      ) : clients.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          {projectId ? 'No client is set for this project yet. Add one here,' : 'No clients yet. Add one here,'} or set a project's client and contract from Planning › Project start.
        </p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {clients.map((c) => {
            const total = c.projects?.reduce((s, p) => s + Number(p.contract_value || 0), 0) ?? 0
            return (
              <li key={c.id} className="flex flex-wrap items-start justify-between gap-3 p-3">
                <div className="min-w-0">
                  <p className="font-medium">{c.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {[c.contact_person, c.phone, c.gstin ? `GSTIN ${c.gstin}` : null, c.address].filter(Boolean).join(' · ') || 'No contact details yet'}
                  </p>
                  {!!c.projects?.length && (
                    <p className="mt-1 text-sm">
                      {c.projects.map((p, i) => (
                        <React.Fragment key={p.id}>
                          {i > 0 && ' · '}
                          <Link className="underline-offset-2 hover:underline" to={`/billing/ra-bills?project=${p.id}`}>{p.name}</Link>
                          {p.contract_value && <span className="text-muted-foreground"> {rupees(p.contract_value)}</span>}
                        </React.Fragment>
                      ))}
                      {c.projects.length > 1 && <span className="text-muted-foreground"> · total {rupees(total)}</span>}
                    </p>
                  )}
                </div>
                <Button size="sm" variant="ghost" className="gap-1.5" onClick={() => setEditing(c)}><Pencil className="size-3.5" /> Edit</Button>
              </li>
            )
          })}
        </ul>
      )}
      <ClientDialog editing={editing} onClose={() => setEditing(null)} />
    </div>
  )
}

function ClientDialog({ editing, onClose }: { editing: Client | 'new' | null; onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [form, setForm] = React.useState<Record<string, string>>({})
  React.useEffect(() => {
    if (!editing) return
    const c = editing === 'new' ? null : editing
    setForm(Object.fromEntries(FIELDS.map((f) => [f.key, (c?.[f.key as keyof Client] as string | null) ?? ''])))
  }, [editing])
  const save = useMutation({
    mutationFn: () => {
      const body: ClientInput = Object.fromEntries(FIELDS.map((f) => [f.key, form[f.key]?.trim() || null]))
      return editing === 'new' || !editing ? createClient(body) : updateClient(editing.id, body)
    },
    onSuccess: (c) => {
      toast.success(`${c.name} saved`)
      queryClient.invalidateQueries({ queryKey: ['billing-clients'] })
      onClose()
    },
    onError: (e) => toast.error('Could not save the client', apiErrorMessage(e)),
  })
  return (
    <Dialog open={!!editing} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing === 'new' ? 'Add a client' : `Edit ${editing ? editing.name : ''}`}</DialogTitle>
          <DialogDescription>Shown on the RA bills you send them.</DialogDescription>
        </DialogHeader>
        <form id="client-form" className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); if (form.name?.trim()) save.mutate() }}>
          {FIELDS.map((f) => (
            <div key={f.key} className={f.key === 'address' || f.key === 'name' ? 'grid gap-1 sm:col-span-2' : 'grid gap-1'}>
              <Label htmlFor={`cl-${f.key}`}>{f.label}</Label>
              <Input id={`cl-${f.key}`} required={f.key === 'name'} placeholder={f.placeholder} value={form[f.key] ?? ''}
                onChange={(e) => setForm((x) => ({ ...x, [f.key]: f.key === 'gstin' ? e.target.value.toUpperCase() : e.target.value }))} />
            </div>
          ))}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="client-form" disabled={save.isPending || !form.name?.trim()}>{save.isPending ? 'Saving…' : 'Save'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
