import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CalendarRange, Calculator, CheckCircle2, Download, FileSpreadsheet, ShieldAlert, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { formatRupees } from '@/lib/boq'
import { downloadBlob } from '@/lib/export'
import { downloadBoqTemplate, previewBoqImport, runBoqImport, type BoqImportReport } from '@/lib/schedule'
import { cn } from '@/lib/utils'

// ST-03: the estimate Excel becomes the BOQ, the budget and the first schedule. Any sheet with Work / Unit /
// Quantity columns works (heading rows become sections); the template is for those starting fresh. A preview
// first, nothing saved until Import.

const COLUMN_WORDS: Record<string, string> = {
  work: 'Work', unit: 'Unit', quantity: 'Quantity', code: 'Item no.', section: 'Section', client_rate: 'Client rate',
  labour_rate: 'Labour rate', material_rate: 'Material rate', subcontract_rate: 'Subcontract rate', start: 'Start',
  finish: 'Finish', after: 'Starts after',
}

export function BoqImportDialog({
  projectId,
  projectName,
  open,
  onOpenChange,
}: {
  projectId: string
  projectName?: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [file, setFile] = React.useState<File | null>(null)
  const [dragging, setDragging] = React.useState(false)
  const [error, setError] = React.useState('')
  const inputRef = React.useRef<HTMLInputElement>(null)
  const detail = (err: any, fallback: string) => err?.response?.data?.detail || fallback

  const preview = useMutation({
    mutationFn: (f: File) => previewBoqImport(projectId, f),
    onError: (err) => setError(detail(err, 'The file could not be read.')),
  })
  const run = useMutation({
    mutationFn: (f: File) => runBoqImport(projectId, f),
    onSuccess: () => {
      for (const key of ['boq', 'schedule', 'project-start', 'lifecycle']) queryClient.invalidateQueries({ queryKey: [key] })
    },
    onError: (err) => setError(detail(err, 'The import did not go through. Nothing was saved.')),
  })
  const template = useMutation({
    mutationFn: () => downloadBoqTemplate(projectId),
    onSuccess: (blob) => downloadBlob('mesiri-boq-import.xlsx', blob),
  })

  const reset = () => {
    setError('')
    preview.reset()
    run.reset()
    setFile(null)
    if (inputRef.current) inputRef.current.value = ''
  }
  const choose = (f: File | null) => {
    setError('')
    preview.reset()
    run.reset()
    setFile(f)
    if (f) preview.mutate(f)
  }
  const report: BoqImportReport | undefined = run.data ?? preview.data
  const problems = report?.rows.filter((r) => r.result === 'problem') ?? []

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) reset(); onOpenChange(o) }}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base font-semibold">
            <FileSpreadsheet className="size-4 text-success" /> BOQ from Excel{projectName ? ` · ${projectName}` : ''}
          </DialogTitle>
          <DialogDescription>
            Upload the estimate you already have. Mesiri finds the Description, Unit, Qty and Rate columns; heading rows
            (like “A. EARTHWORK”) become sections. You see everything before it is saved.
          </DialogDescription>
        </DialogHeader>

        {!report?.saved && (
          <label
            htmlFor="boqFile"
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              choose(e.dataTransfer.files?.[0] ?? null)
            }}
            className={cn(
              'flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center text-sm transition',
              dragging ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40',
            )}
          >
            <Upload className="size-6 text-muted-foreground" />
            <span className="font-medium">{file ? file.name : 'Drop your BOQ / estimate .xlsx here, or click to choose'}</span>
            <span className="text-xs text-muted-foreground">Up to 5 MB · Rows already in the BOQ are left as they are</span>
            <input
              ref={inputRef}
              id="boqFile"
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="sr-only"
              onChange={(e) => choose(e.target.files?.[0] ?? null)}
            />
          </label>
        )}
        {!report && (
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            No estimate yet?
            <Button type="button" variant="link" size="sm" className="h-auto gap-1 p-0" disabled={template.isPending} onClick={() => template.mutate()}>
              <Download className="size-3.5" /> {template.isPending ? 'Preparing…' : 'Download a template with examples'}
            </Button>
          </div>
        )}

        {error && (
          <p className="flex items-center gap-2 text-sm text-destructive">
            <ShieldAlert className="size-4 shrink-0" /> {error}
          </p>
        )}
        {(preview.isPending || run.isPending) && (
          <p className="animate-pulse text-sm text-muted-foreground">{run.isPending ? 'Importing…' : `Reading ${file?.name}…`}</p>
        )}

        {report && (
          <section className="flex flex-col gap-3 text-sm">
            {report.saved ? (
              <div className="flex flex-col gap-3 rounded-xl border border-success/25 bg-success-soft p-4">
                <p className="flex items-center gap-2 text-base font-semibold text-success">
                  <CheckCircle2 className="size-5" /> {report.lines_added} BOQ lines are in.
                </p>
                <p className="text-foreground/80">
                  {report.sections_added} new sections{report.dated_sections ? `, ${report.dated_sections} with dates on the schedule` : ''}.
                  From tomorrow, every work update the site sends on WhatsApp counts against these lines.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button asChild size="sm" className="gap-1.5"><Link to={`/planning/schedule?project=${projectId}`} onClick={() => onOpenChange(false)}><CalendarRange className="size-4" /> Plan the schedule <ArrowRight className="size-3.5" /></Link></Button>
                  <Button asChild size="sm" variant="outline" className="gap-1.5"><Link to={`/projects/${projectId}/boq`} onClick={() => onOpenChange(false)}><Calculator className="size-4" /> Open the BOQ</Link></Button>
                </div>
              </div>
            ) : (
              <p className="font-medium">
                Found in “{report.sheet}”: <span className="text-success">{report.lines_added} lines to add</span>
                {report.lines_kept ? `, ${report.lines_kept} already in the BOQ` : ''}
                {report.problems ? <span className="text-destructive">, {report.problems} cannot go in</span> : ''}. Nothing is saved yet.
              </p>
            )}

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Figure label="Sections" value={`${report.sections_added + report.sections_found}`} hint={report.sections_found ? `${report.sections_found} already there` : 'new'} />
              <Figure label="Lines" value={`${report.lines_added}`} hint={report.lines_kept ? `+${report.lines_kept} kept` : 'to add'} />
              <Figure label="Contract value" value={formatRupees(report.contract_value)} hint="qty × client rate" />
              <Figure label="Budget cost" value={formatRupees(report.budget_cost)} hint="qty × your rates" />
            </div>

            <p className="text-xs text-muted-foreground">
              Columns read: {Object.keys(report.columns).map((k) => `${COLUMN_WORDS[k] ?? k} (“${report.columns[k]}”)`).join(', ')}
              {report.ignored_columns.length ? `. Not used: ${report.ignored_columns.join(', ')}` : ''}.
            </p>

            {report.sections.length > 0 && (
              <div className="overflow-hidden rounded-lg border">
                <table className="w-full text-left text-sm">
                  <thead className="bg-muted/50 text-xs text-muted-foreground">
                    <tr><th className="px-3 py-1.5 font-medium">Section</th><th className="px-3 py-1.5 text-right font-medium">Lines</th><th className="px-3 py-1.5 text-right font-medium">Value</th><th className="hidden px-3 py-1.5 font-medium sm:table-cell">Dates</th></tr>
                  </thead>
                  <tbody className="divide-y">
                    {report.sections.map((s) => (
                      <tr key={s.id}>
                        <td className="px-3 py-1.5 font-medium">{s.name}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{s.lines}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{Number(s.contract_value) ? formatRupees(s.contract_value) : '—'}</td>
                        <td className="hidden px-3 py-1.5 text-muted-foreground tabular-nums sm:table-cell">{s.start ? `${s.start} → ${s.finish ?? s.start}` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {problems.length > 0 && (
              <div className="overflow-hidden rounded-lg border border-destructive/30">
                <p className="bg-destructive/5 px-3 py-1.5 text-xs font-semibold text-destructive">Rows that cannot go in: fix them in Excel and import again</p>
                <ul className="max-h-48 divide-y overflow-y-auto">
                  {problems.map((r) => (
                    <li key={`${r.row}-${r.what}`} className="flex gap-3 px-3 py-1.5">
                      <span className="w-14 shrink-0 text-muted-foreground tabular-nums">Row {r.row}</span>
                      <span className="min-w-0 flex-1"><span className="font-medium">{r.what || '—'}</span> <span className="text-muted-foreground">· {r.message}</span></span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {!report.saved && (
              <div className="flex flex-wrap justify-end gap-2 border-t pt-3">
                <Button variant="outline" onClick={reset}>Choose another file</Button>
                <Button disabled={!file || run.isPending || report.lines_added + report.sections_added === 0} onClick={() => file && run.mutate(file)} className="gap-1.5">
                  <CheckCircle2 className="size-4" /> Import {report.lines_added} lines
                </Button>
              </div>
            )}
          </section>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Figure({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="truncate text-lg font-semibold tabular-nums">{value}</div>
      <div className="text-[11px] text-muted-foreground">{hint}</div>
    </div>
  )
}
