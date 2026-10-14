import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ImagePlus, Loader2, Save, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  fetchBranding,
  removeCompanyLogo,
  updateBranding,
  uploadCompanyLogo,
  type BrandingFields,
  type CompanyBranding,
} from '@/lib/api'
import { LOGO_TYPES, apiErrorMessage as apiError, logoFileProblem, readAsBase64 } from '@/lib/logo-upload'

// How the company appears on its DPRs (tracker WEB-10, backed by BE-20).
// Name, address, phone and email are the company record's own fields
// (Settings tab); this tab holds only what the letterhead adds on top.

const DEFAULT_COLOR = '#1F6FEB'

const FIELDS: { key: keyof BrandingFields; label: string; placeholder: string; hint?: string }[] = [
  {
    key: 'letterhead_name',
    label: 'Name on letterhead',
    placeholder: 'Leave empty to use the company name',
  },
  {
    key: 'gstin',
    label: 'GSTIN',
    placeholder: '27AAPFU0939F1ZV',
    hint: '15 characters',
  },
  { key: 'signatory_name', label: 'Signatory name', placeholder: 'R. Rao' },
  { key: 'signatory_designation', label: 'Signatory designation', placeholder: 'Project Director' },
]

function toForm(b: CompanyBranding): Record<keyof BrandingFields, string> {
  return {
    letterhead_name: b.letterhead_name ?? '',
    brand_color: b.brand_color ?? '',
    gstin: b.gstin ?? '',
    signatory_name: b.signatory_name ?? '',
    signatory_designation: b.signatory_designation ?? '',
  }
}

export function BrandingTab() {
  const queryClient = useQueryClient()
  const { data: branding, isLoading, isError, error } = useQuery({
    queryKey: ['company-branding'],
    queryFn: fetchBranding,
  })

  const [form, setForm] = React.useState<Record<keyof BrandingFields, string> | null>(null)
  const [saved, setSaved] = React.useState(false)
  const [logoError, setLogoError] = React.useState<string | null>(null)
  const fileInput = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    if (branding) setForm(toForm(branding))
  }, [branding])

  const onSaved = (data: CompanyBranding) => queryClient.setQueryData(['company-branding'], data)

  const save = useMutation({
    mutationFn: updateBranding,
    // A new attempt clears the last "saved" note, so a failure is never
    // hidden behind it.
    onMutate: () => setSaved(false),
    onSuccess: (data) => {
      onSaved(data)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  const upload = useMutation({
    mutationFn: async (file: File) => uploadCompanyLogo(file.type, await readAsBase64(file)),
    onSuccess: onSaved,
    onError: (err) => setLogoError(apiError(err)),
  })

  const remove = useMutation({
    mutationFn: removeCompanyLogo,
    onSuccess: onSaved,
    onError: (err) => setLogoError(apiError(err)),
  })

  if (isLoading || !form) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground p-6">
        <Loader2 className="size-4 animate-spin" /> Loading letterhead…
      </div>
    )
  }
  if (isError || !branding) {
    return <p className="text-xs text-rose-500 p-6">Could not load the letterhead: {apiError(error)}</p>
  }

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    setLogoError(null)
    if (!file) return
    const problem = logoFileProblem(file)
    if (problem) {
      setLogoError(problem)
      return
    }
    upload.mutate(file)
  }

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    save.mutate(form)
  }

  const color = form.brand_color || DEFAULT_COLOR
  const printedName = form.letterhead_name || branding.company_name
  const busy = upload.isPending || remove.isPending

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] max-w-5xl text-xs">
      <div className="space-y-6">
        {/* Logo */}
        <section className="border border-border/60 bg-card rounded p-6 space-y-4">
          <div>
            <h3 className="font-semibold text-foreground text-sm">Company logo</h3>
            <p className="text-muted-foreground mt-1">
              Printed at the top of every DPR. PNG, JPEG or WebP, up to 700 KB.
            </p>
          </div>
          <div className="flex items-center gap-4">
            <div className="size-20 rounded border border-border/60 bg-muted/30 flex items-center justify-center overflow-hidden">
              {branding.logo_url ? (
                <img src={branding.logo_url} alt="Company logo" className="max-h-full max-w-full object-contain" />
              ) : (
                <span className="text-[10px] text-muted-foreground text-center px-1">
                  {branding.has_logo ? 'Preview unavailable' : 'No logo'}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              <input
                ref={fileInput}
                type="file"
                accept={LOGO_TYPES.join(',')}
                className="hidden"
                onChange={onPick}
              />
              <Button
                type="button"
                variant="outline"
                className="h-9 text-xs gap-1.5"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
              >
                {upload.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <ImagePlus className="size-3.5" />}
                {branding.has_logo ? 'Replace logo' : 'Upload logo'}
              </Button>
              {branding.has_logo && (
                <Button
                  type="button"
                  variant="ghost"
                  className="h-9 text-xs gap-1.5 text-rose-600"
                  disabled={busy}
                  onClick={() => {
                    setLogoError(null)
                    remove.mutate()
                  }}
                >
                  <Trash2 className="size-3.5" /> Remove
                </Button>
              )}
            </div>
          </div>
          {logoError && <p className="text-rose-500">{logoError}</p>}
        </section>

        {/* Text fields */}
        <form onSubmit={onSubmit} className="border border-border/60 bg-card rounded p-6 space-y-4">
          <h3 className="font-semibold text-foreground text-sm">Letterhead details</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            {FIELDS.map((f) => (
              <div key={f.key} className="grid gap-1.5">
                <label htmlFor={`branding-${f.key}`} className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                  {f.label}
                  {f.hint && <span className="normal-case font-normal ml-1">({f.hint})</span>}
                </label>
                <Input
                  id={`branding-${f.key}`}
                  value={form[f.key]}
                  placeholder={f.placeholder}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  className="h-9 text-xs"
                />
              </div>
            ))}
            <div className="grid gap-1.5">
              <label htmlFor="branding-brand_color" className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                Brand colour
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  aria-label="Pick brand colour"
                  value={color}
                  onChange={(e) => setForm({ ...form, brand_color: e.target.value.toUpperCase() })}
                  className="h-9 w-10 rounded border border-border/60 bg-transparent p-0.5"
                />
                <Input
                  id="branding-brand_color"
                  value={form.brand_color}
                  placeholder={DEFAULT_COLOR}
                  onChange={(e) => setForm({ ...form, brand_color: e.target.value })}
                  className="h-9 text-xs font-mono"
                />
              </div>
            </div>
          </div>
          <p className="text-muted-foreground">
            Address, phone and email come from the Settings tab.
          </p>
          <div className="border-t pt-4 flex items-center justify-between gap-3">
            {saved ? (
              <span className="text-emerald-500 font-semibold flex items-center gap-1">
                <Check className="size-4" /> Letterhead saved
              </span>
            ) : save.isError ? (
              <span className="text-rose-500">{apiError(save.error)}</span>
            ) : (
              <span />
            )}
            <Button type="submit" disabled={save.isPending} className="h-9 text-xs gap-1.5">
              {save.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
              Save letterhead
            </Button>
          </div>
        </form>
      </div>

      {/* Preview: roughly how the top of a DPR will look */}
      <section className="border border-border/60 bg-card rounded p-6 space-y-3 self-start">
        <h3 className="font-semibold text-foreground text-sm">Preview</h3>
        <div className="rounded border border-border/60 bg-white text-neutral-900 p-5 shadow-sm">
          <div className="flex items-start gap-4 pb-3" style={{ borderBottom: `3px solid ${color}` }}>
            {branding.logo_url && (
              <img src={branding.logo_url} alt="" className="h-12 max-w-[96px] object-contain" />
            )}
            <div className="min-w-0">
              <div className="text-base font-bold leading-tight" style={{ color }}>
                {printedName}
              </div>
              {branding.address && <div className="text-[11px] text-neutral-600">{branding.address}</div>}
              <div className="text-[11px] text-neutral-600">
                {[branding.phone, branding.email].filter(Boolean).join(' · ')}
              </div>
              {form.gstin && <div className="text-[11px] text-neutral-600">GSTIN: {form.gstin.toUpperCase()}</div>}
            </div>
          </div>
          <div className="pt-3 text-[11px] font-semibold tracking-wide uppercase text-neutral-500">
            Daily Progress Report
          </div>
          <div className="mt-2 space-y-1.5">
            <div className="h-2 rounded bg-neutral-100 w-full" />
            <div className="h-2 rounded bg-neutral-100 w-5/6" />
            <div className="h-2 rounded bg-neutral-100 w-2/3" />
          </div>
          {(form.signatory_name || form.signatory_designation) && (
            <div className="mt-4 text-right text-[11px]">
              <div className="font-semibold">{form.signatory_name}</div>
              <div className="text-neutral-600">{form.signatory_designation}</div>
            </div>
          )}
          <div className="mt-4 text-center text-[9px] text-neutral-400">Generated with Mesiri</div>
        </div>
      </section>
    </div>
  )
}
