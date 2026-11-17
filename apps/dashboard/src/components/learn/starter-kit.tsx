import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Download, FileSpreadsheet, FileText, Lightbulb } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useScope } from '@/lib/ScopeContext'
import { urlWithScope } from '@/lib/scope-url'

// SS-73 (guided-demo-plan.md section 16.2): Green Villa's paperwork, to bring into the sample company yourself. The
// files and what each one is for are made by scripts/learn_kit/make_kit.py into public/learn/kit (kit.json lists them),
// so this card never goes out of step with the files. "What to look for" stays folded: finding the catch is the point.

interface KitFile {
  file: string
  title: string
  kind: 'excel' | 'pdf'
  page: string
  what: string
  goes: string
  catch: string
  /** More files that go with this one (the other quotes, the subcontractor's bill). */
  also?: string[]
}

interface Kit {
  name: string
  zip: string
  files: KitFile[]
}

const BASE = '/learn/kit/'

/** A short name for one of several files: "Malabar Cements Agency" from "Quote - Malabar Cements Agency.pdf". */
function fileLabel(name: string, i: number): string {
  const base = name.replace(/\.[a-z]+$/i, '')
  const part = base.includes(' - ') ? base.split(' - ').slice(1).join(' - ') : base
  return part ? part[0].toUpperCase() + part.slice(1) : `File ${i + 1}`
}

export function StarterKit() {
  const { scope } = useScope()
  const kit = useQuery({
    queryKey: ['learn-kit'],
    queryFn: async () => {
      const res = await fetch(`${BASE}kit.json`)
      if (!res.ok) throw new Error('No starter kit')
      return (await res.json()) as Kit
    },
    staleTime: Infinity,
    retry: false,
  })
  const [shown, setShown] = React.useState<string | null>(null)
  if (!kit.data) return null
  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-4" data-guide="learn.kit">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="m-0 text-base font-semibold">Starter kit: Green Villa's paperwork</h2>
          <p className="m-0 text-sm text-muted-foreground">
            The files a real project runs on. Bring them into your sample company yourself; each one hides something Mesiri catches.
          </p>
        </div>
        <Button asChild size="sm" variant="outline" className="gap-1.5">
          <a href={`${BASE}${kit.data.zip}`} download>
            <Download className="size-3.5" aria-hidden /> Download all
          </a>
        </Button>
      </div>
      <ul className="flex flex-col divide-y rounded-lg border">
        {kit.data.files.map((f) => {
          const Icon = f.kind === 'excel' ? FileSpreadsheet : FileText
          const open = shown === f.file
          return (
            <li key={f.file} className="flex flex-col gap-2 px-3 py-3 sm:flex-row sm:items-start">
              {/* DESIGN.md: colour means status (green done, red bad), so a file's kind is its icon, not a colour. */}
              <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-foreground/70">
                <Icon className="size-4" aria-hidden />
              </span>
              <div className="min-w-0 flex-1 text-sm">
                <p className="m-0 font-medium">{f.title}</p>
                <p className="m-0 text-muted-foreground">{f.what}</p>
                <p className="m-0 mt-1 text-xs">
                  Goes into{' '}
                  <Link to={urlWithScope(f.page, scope)} className="inline-flex items-center gap-0.5 font-medium underline underline-offset-2">
                    {f.goes} <ArrowRight className="size-3" aria-hidden />
                  </Link>
                </p>
                {open ? (
                  <p className="m-0 mt-2 flex gap-2 rounded-md bg-primary/10 px-2.5 py-1.5 text-xs">
                    <Lightbulb className="mt-0.5 size-3.5 shrink-0 text-primary-ink" aria-hidden /> {f.catch}
                  </p>
                ) : (
                  <button type="button" onClick={() => setShown(f.file)} className="mt-1 text-xs text-muted-foreground underline underline-offset-2">
                    What to look for
                  </button>
                )}
              </div>
              <div className="flex shrink-0 flex-col items-start gap-0.5 sm:items-end">
                {[f.file, ...(f.also ?? [])].map((name, i) => (
                  <Button key={name} asChild size="sm" variant="ghost" className="h-7 gap-1.5 px-2">
                    <a href={`${BASE}${encodeURIComponent(name)}`} download title={name}>
                      <Download className="size-3.5" aria-hidden /> {f.also?.length ? fileLabel(name, i) : 'Download'}
                    </a>
                  </Button>
                ))}
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
