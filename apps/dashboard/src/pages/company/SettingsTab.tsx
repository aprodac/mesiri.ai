import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, Check, Loader2, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { updateCompany, type Company } from '@/lib/api'
import { TimezoneSelect } from '@/components/timezone-select'

interface SettingsTabProps {
  company: Company
}

export function SettingsTab({ company }: SettingsTabProps) {
  const queryClient = useQueryClient()
  const [formData, setFormData] = React.useState({
    name: company.name || '',
    code: company.code || '',
    email: company.email || '',
    phone: company.phone || '',
    address: company.address || '',
    primary_contact: company.primary_contact || '',
    timezone: company.timezone || 'UTC',
  })
  const [success, setSuccess] = React.useState(false)

  React.useEffect(() => {
    setFormData({
      name: company.name || '',
      code: company.code || '',
      email: company.email || '',
      phone: company.phone || '',
      address: company.address || '',
      primary_contact: company.primary_contact || '',
      timezone: company.timezone || 'UTC',
    })
  }, [company])

  const mutation = useMutation({
    mutationFn: updateCompany,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['company-profile'] })
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
    },
  })

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({ ...prev, [name]: value }))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    mutation.mutate(formData)
  }

  return (
    <form onSubmit={handleSubmit} className="border border-border/60 bg-card rounded p-6 max-w-2xl space-y-6 text-xs">
      <div className="flex items-center gap-2 pb-4 border-b">
        <h3 className="font-semibold text-foreground text-sm">Company Administrative Information</h3>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Name */}
        <div className="grid gap-1.5">
          <label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Company Name</label>
          <Input
            name="name"
            value={formData.name}
            onChange={handleChange}
            required
            className="h-9 text-xs"
          />
        </div>

        {/* Short Code */}
        <div className="grid gap-1.5">
          <label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Company Code</label>
          <Input
            name="code"
            value={formData.code}
            onChange={handleChange}
            placeholder="e.g. MESIRI"
            className="h-9 text-xs"
          />
        </div>

        {/* Email */}
        <div className="grid gap-1.5">
          <label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Administrative Email</label>
          <Input
            type="email"
            name="email"
            value={formData.email}
            onChange={handleChange}
            placeholder="admin@company.com"
            className="h-9 text-xs"
          />
        </div>

        {/* Phone */}
        <div className="grid gap-1.5">
          <label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Contact Phone</label>
          <Input
            name="phone"
            value={formData.phone}
            onChange={handleChange}
            placeholder="+1 555-555-5555"
            className="h-9 text-xs"
          />
        </div>

        {/* Primary Contact Person */}
        <div className="grid gap-1.5">
          <label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Primary Contact Representative</label>
          <Input
            name="primary_contact"
            value={formData.primary_contact}
            onChange={handleChange}
            placeholder="John Doe"
            className="h-9 text-xs"
          />
        </div>

        {/* Timezone */}
        <div className="grid gap-1.5">
          <label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">System Timezone</label>
          <TimezoneSelect
            name="timezone"
            value={formData.timezone}
            onChange={(timezone) => setFormData((prev) => ({ ...prev, timezone }))}
          />
        </div>

        {/* Address */}
        <div className="grid gap-1.5 sm:col-span-2">
          <label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Headquarters Address</label>
          <Input
            name="address"
            value={formData.address}
            onChange={handleChange}
            placeholder="123 Main St, City, Country"
            className="h-9 text-xs"
          />
        </div>
      </div>

      {/* Read Only System Metadata */}
      <div className="border border-border/40 bg-muted/20 p-4 rounded space-y-2.5">
        <h4 className="font-semibold text-foreground text-[11px] flex items-center gap-1.5">
          <Info className="size-3.5 text-muted-foreground" />
          Technical Infrastructure Claims
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-[10px] text-muted-foreground">
          <div>
            <span className="block uppercase font-semibold text-[8px] opacity-75">Organization UUID</span>
            <span className="font-mono font-medium text-foreground">{company.id}</span>
          </div>
          <div>
            <span className="block uppercase font-semibold text-[8px] opacity-75">Tenant DB Database Route</span>
            <span className="font-mono font-medium text-foreground">{company.db_route}</span>
          </div>
          <div>
            <span className="block uppercase font-semibold text-[8px] opacity-75">Deployment Type</span>
            <span className="font-mono font-medium text-foreground uppercase">{company.deployment_type}</span>
          </div>
        </div>
      </div>

      {/* Submit Toolbar */}
      <div className="border-t pt-4 flex items-center justify-between">
        {success ? (
          <span className="text-emerald-500 font-semibold flex items-center gap-1">
            <Check className="size-4" /> Settings updated successfully
          </span>
        ) : mutation.isError ? (
          <span className="text-rose-500 font-medium">
            Save failed: {mutation.error instanceof Error ? mutation.error.message : 'Unknown API error.'}
          </span>
        ) : (
          <span />
        )}

        <Button
          type="submit"
          disabled={mutation.isPending}
          className="h-9 text-xs gap-1.5"
        >
          {mutation.isPending ? (
            <>
              <Loader2 className="size-3.5 animate-spin" /> Saving...
            </>
          ) : (
            <>
              <Save className="size-3.5" /> Save Settings
            </>
          )}
        </Button>
      </div>
    </form>
  )
}
