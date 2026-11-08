import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageCircle, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast-notification'
import { apiErrorMessage } from '@/lib/logo-upload'
import { cn } from '@/lib/utils'
import { addContact, editContact, fetchContacts } from '@/lib/subcontracts'

// NXT-16 (option B, approved by Alan 8 Nov 2026): who of this subcontractor may message Mesiri on WhatsApp. They can
// ask what is pending, send bills and report work; all of it waits for the company's check, and they see nothing else.

export function SubcontractorContacts({ vendorId, vendorName, canManage }: { vendorId: string; vendorName: string; canManage: boolean }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['vendors', 'contacts', vendorId], queryFn: () => fetchContacts(vendorId), retry: false })
  const [name, setName] = React.useState('')
  const [phone, setPhone] = React.useState('')
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['vendors', 'contacts', vendorId] })
  const add = useMutation({
    mutationFn: () => addContact(vendorId, { name: name.trim(), phone }),
    onSuccess: (c) => { refresh(); setName(''); setPhone(''); toast.success(`${c.name} can use Mesiri on WhatsApp`, 'Tell them to message the company’s Mesiri number.') },
    onError: (e) => toast.error('Not added', apiErrorMessage(e)),
  })
  const toggle = useMutation({
    mutationFn: (c: { id: string; status: string }) => editContact(vendorId, c.id, { status: c.status === 'active' ? 'inactive' : 'active' }),
    onSuccess: refresh, onError: (e) => toast.error('Not changed', apiErrorMessage(e)),
  })
  if (q.isError) return null
  const list = q.data?.contacts ?? []
  return (
    <section className="flex flex-col gap-2 rounded-xl border bg-card p-3">
      <div className="flex items-center gap-2">
        <MessageCircle className="size-4 text-muted-foreground" />
        <h3 className="font-semibold">{vendorName} on WhatsApp</h3>
      </div>
      {q.data && !q.data.partner_access && (
        <p className="rounded-md bg-draft-soft px-3 py-2 text-sm text-draft">Subcontractors on WhatsApp is off for the company: turn it on in <Link to="/finance/settings" className="font-semibold underline">Finance › Settings</Link>.</p>
      )}
      <p className="text-xs text-muted-foreground">They can ask what is pending, send their bill and report work done. Bills wait for your check and work for the site engineer; they never see anything else of the company.</p>
      {list.length > 0 && (
        <ul className="divide-y rounded-lg border text-sm">
          {list.map((c) => (
            <li key={c.id} className={cn('flex items-center gap-2 px-3 py-2', c.status !== 'active' && 'opacity-60')}>
              <span className="min-w-0 flex-1"><span className="font-medium">{c.name}</span> <span className="text-muted-foreground">{c.phone}</span>
                <span className="block text-xs text-muted-foreground">{c.status !== 'active' ? 'switched off' : c.last_seen_at ? `last message ${new Date(c.last_seen_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}` : 'has not messaged yet'}</span></span>
              {canManage && <Button size="sm" variant="outline" disabled={toggle.isPending} onClick={() => toggle.mutate(c)}>{c.status === 'active' ? 'Switch off' : 'Switch on'}</Button>}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim() && phone.trim()) add.mutate() }}>
          <Input aria-label="Contact name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (Ravi)" className="h-9 w-40" />
          <Input aria-label="WhatsApp number" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="98470 12345" className="h-9 w-40" />
          <Button type="submit" size="sm" className="gap-1" disabled={!name.trim() || !phone.trim() || add.isPending}><UserPlus className="size-4" /> Add</Button>
        </form>
      )}
    </section>
  )
}
