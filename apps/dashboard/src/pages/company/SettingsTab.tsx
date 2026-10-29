import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import { updateCompany, type Company } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { useReadOnly } from '@/lib/trial'

// The company record (WEB-10; flat form in WEB-28). Name, address, phone
// and email print on the DPR letterhead. The old "Technical Infrastructure
// Claims" box (organisation id, database route) is gone: nothing a customer
// can act on.

type Fields = 'name' | 'code' | 'email' | 'phone' | 'address' | 'primary_contact' | 'timezone'

const FIELDS: { key: Fields; label: string; placeholder?: string; wide?: boolean; type?: string; required?: boolean; hint?: string }[] = [
  { key: 'name', label: 'Company name', required: true, hint: 'On the DPR letterhead' },
  { key: 'primary_contact', label: 'Main contact', placeholder: 'Who Mesiri talks to' },
  { key: 'phone', label: 'Phone', placeholder: '+91 98765 43210', hint: 'On the letterhead' },
  { key: 'email', label: 'Email', type: 'email', placeholder: 'office@company.in', hint: 'On the letterhead' },
  { key: 'address', label: 'Address', placeholder: 'Office address', wide: true, hint: 'On the letterhead' },
  { key: 'code', label: 'Short code', placeholder: 'e.g. SB' },
  { key: 'timezone', label: 'Time zone', placeholder: 'Asia/Kolkata', required: true },
]

const fromCompany = (c: Company): Record<Fields, string> => ({
  name: c.name || '',
  code: c.code || '',
  email: c.email || '',
  phone: c.phone || '',
  address: c.address || '',
  primary_contact: c.primary_contact || '',
  timezone: c.timezone || 'Asia/Kolkata',
})

export function SettingsTab({ company }: { company: Company }) {
  const readOnly = useReadOnly()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [form, setForm] = React.useState(() => fromCompany(company))
  const original = fromCompany(company)
  const dirty = (Object.keys(form) as Fields[]).some((k) => form[k] !== original[k])

  const mutation = useMutation({
    mutationFn: updateCompany,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['company-profile'] })
      queryClient.invalidateQueries({ queryKey: ['company-branding'] })
      toast.success('Saved', 'The company details are updated.')
    },
    onError: (err) => toast.error('Could not save', apiErrorMessage(err)),
  })

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        mutation.mutate(form)
      }}
      className="flex flex-col gap-4 text-sm"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {FIELDS.map((f) => (
          <div key={f.key} className={f.wide ? 'grid gap-1.5 sm:col-span-2' : 'grid gap-1.5'}>
            <Label htmlFor={`company-${f.key}`}>
              {f.label}
              {f.hint && <span className="ml-1.5 font-normal text-muted-foreground">· {f.hint}</span>}
            </Label>
            <Input
              id={`company-${f.key}`}
              type={f.type ?? 'text'}
              list={f.key === 'timezone' ? 'company-timezones' : undefined}
              value={form[f.key]}
              placeholder={f.placeholder}
              required={f.required}
              disabled={readOnly}
              onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
              className="h-9"
            />
          </div>
        ))}
        <datalist id="company-timezones">
          {['Asia/Kolkata', 'Asia/Dubai', 'Asia/Singapore', 'Europe/London', 'UTC'].map((z) => (
            <option key={z} value={z} />
          ))}
        </datalist>
      </div>
      {!readOnly && (
        <div className="flex items-center gap-2">
          <Button type="submit" size="sm" disabled={mutation.isPending || !dirty} className="font-semibold">
            {mutation.isPending ? 'Saving…' : 'Save'}
          </Button>
          {dirty && (
            <Button type="button" variant="ghost" size="sm" onClick={() => setForm(original)}>
              Undo changes
            </Button>
          )}
        </div>
      )}
    </form>
  )
}
