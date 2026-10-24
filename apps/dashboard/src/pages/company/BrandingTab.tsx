import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Loader2, Trash2 } from 'lucide-react'
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
import { useReadOnly } from '@/lib/trial'
import { useToast } from '@/components/ui/toast-notification'

// How the company appears on its DPRs (tracker WEB-10, backed by BE-20).
// Name, address, phone and email are the company record's own fields
// (Company details); this holds only what the letterhead adds on top.
// WEB-28: flat section; the preview follows the DPR template (WEB-27) and
// its default colour is the PDF's own (channel/dpr_document/template.py
// _ACCENT), not the blue it used to show.

const DEFAULT_COLOR = '#0A8F4C'

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
  // Free trial over: saves are refused, so don't offer them (SS-15).
  const readOnly = useReadOnly()
  const queryClient = useQueryClient()
  const { data: branding, isLoading, isError, error } = useQuery({
    queryKey: ['company-branding'],
    queryFn: fetchBranding,
  })

  const [form, setForm] = React.useState<Record<keyof BrandingFields, string> | null>(null)
  const toast = useToast()
  const [logoError, setLogoError] = React.useState<string | null>(null)
  const fileInput = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    if (branding) setForm(toForm(branding))
  }, [branding])

  const onSaved = (data: CompanyBranding) => queryClient.setQueryData(['company-branding'], data)

  const save = useMutation({
    mutationFn: updateBranding,
    onSuccess: (data) => {
      onSaved(data)
      toast.success('Letterhead saved', 'The next DPR prints with it.')
    },
    onError: (err) => toast.error('Could not save', apiError(err)),
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
      <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Loading letterhead…
      </div>
    )
  }
  if (isError || !branding) {
    return <p className="py-2 text-sm text-destructive">Could not load the letterhead: {apiError(error)}</p>
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
  const busy = upload.isPending || remove.isPending || readOnly

  return (
    <div className="grid gap-6 text-sm lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-5">
        {/* Logo */}
        <section className="flex flex-col gap-2">
          <div>
            <h3 className="font-medium">Logo</h3>
            <p className="text-muted-foreground">Top left of every DPR. PNG, JPEG or WebP, up to 700 KB.</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="size-16 shrink-0 rounded-lg border bg-muted/30 flex items-center justify-center overflow-hidden">
              {branding.logo_url ? (
                <img src={branding.logo_url} alt="Company logo" className="max-h-full max-w-full object-contain" />
              ) : (
                <span className="px-1 text-center text-xs text-muted-foreground">
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
                className="gap-1.5"
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
                  className="gap-1.5 text-destructive"
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
          {logoError && <p className="text-destructive">{logoError}</p>}
        </section>

        {/* Text fields */}
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {FIELDS.map((f) => (
              <div key={f.key} className="grid gap-1.5">
                <label htmlFor={`branding-${f.key}`} className="text-sm font-medium">
                  {f.label}
                  {f.hint && <span className="ml-1.5 font-normal text-muted-foreground">· {f.hint}</span>}
                </label>
                <Input
                  id={`branding-${f.key}`}
                  value={form[f.key]}
                  placeholder={f.placeholder}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  disabled={readOnly}
                  className="h-9"
                />
              </div>
            ))}
            <div className="grid gap-1.5">
              <label htmlFor="branding-brand_color" className="text-sm font-medium">
                Brand colour
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  aria-label="Pick brand colour"
                  value={color}
                  onChange={(e) => setForm({ ...form, brand_color: e.target.value.toUpperCase() })}
                  disabled={readOnly}
                  className="h-9 w-10 shrink-0 rounded-md border bg-transparent p-0.5"
                />
                <Input
                  id="branding-brand_color"
                  value={form.brand_color}
                  placeholder={DEFAULT_COLOR}
                  onChange={(e) => setForm({ ...form, brand_color: e.target.value })}
                  disabled={readOnly}
                  className="h-9 font-mono"
                />
              </div>
            </div>
          </div>
          <p className="text-muted-foreground">Name, address, phone and email come from Company details above.</p>
          {!readOnly && (
            <div>
              <Button type="submit" size="sm" disabled={save.isPending} className="font-semibold">
                {save.isPending ? 'Saving…' : 'Save letterhead'}
              </Button>
            </div>
          )}
        </form>
      </div>

      {/* Preview: the top of a DPR, laid out as the PDF template is (WEB-27). */}
      <section className="flex flex-col gap-2 self-start lg:sticky lg:top-20">
        <h3 className="font-medium">Preview</h3>
        <div className="rounded-lg border bg-white p-5 text-neutral-900 shadow-sm">
          <div className="flex items-start justify-between gap-4 pb-3" style={{ borderBottom: `3px solid ${color}` }}>
            <div className="flex min-w-0 items-center gap-3">
              {branding.logo_url && <img src={branding.logo_url} alt="" className="h-11 max-w-[96px] object-contain" />}
              <div className="min-w-0">
                <div className="text-base font-bold leading-tight" style={{ color }}>
                  {printedName}
                </div>
                {branding.address && <div className="text-[11px] text-neutral-500">{branding.address}</div>}
                {(branding.phone || branding.email) && (
                  <div className="text-[11px] text-neutral-500">{[branding.phone, branding.email].filter(Boolean).join(' · ')}</div>
                )}
                {form.gstin && <div className="text-[11px] text-neutral-500">GSTIN: {form.gstin.toUpperCase()}</div>}
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="text-[9px] font-bold uppercase tracking-[0.12em]" style={{ color }}>
                Site report
              </div>
              <div className="text-sm font-bold">Daily Progress Report</div>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-1.5">
            {['Workers', 'Work items', 'Photos', 'Open issues'].map((k) => (
              <div key={k} className="rounded px-2 py-1.5" style={{ background: `color-mix(in srgb, ${color} 8%, white)` }}>
                <div className="text-[8px] font-semibold uppercase tracking-wide text-neutral-500">{k}</div>
                <div className="h-2.5 w-5 rounded bg-neutral-300/70" />
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-1.5 text-[11px] font-bold">
            <span className="flex size-4 items-center justify-center rounded text-[9px] text-white" style={{ background: color }}>
              1
            </span>
            Work done
          </div>
          <div className="mt-1.5 space-y-1.5">
            <div className="h-2 w-full rounded bg-neutral-100" />
            <div className="h-2 w-5/6 rounded bg-neutral-100" />
          </div>
          {(form.signatory_name || form.signatory_designation) && (
            <div className="mt-5 ml-auto w-36 border-t border-neutral-800 pt-1 text-center text-[11px]">
              <div className="font-semibold">{form.signatory_name}</div>
              <div className="text-neutral-500">{form.signatory_designation}</div>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
