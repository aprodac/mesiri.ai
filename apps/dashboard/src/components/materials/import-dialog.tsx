import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Download, FileSpreadsheet, ShieldAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { downloadBlob } from '@/lib/export'
import { cn } from '@/lib/utils'
import {
  downloadImportTemplate,
  previewImport,
  runImport,
  type ImportReport,
  type ImportResult,
  type ImportSheet,
} from '@/lib/materials'

// PRC-05: the onboarding import. Download the template, fill Items / Vendors / Opening stock, upload, see what
// will happen row by row, then import. Rows already in Mesiri are left as they are; a refused row says why.

const SHEETS: ImportSheet[] = ['Items', 'Vendors', 'Opening stock']
const WORDS: Record<ImportResult, string> = {
  added: 'new',
  placed: 'put in a category',
  updated: 'details updated',
  existing: 'already in Mesiri',
  problem: 'cannot go in',
}

export function ImportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient()
  const [file, setFile] = React.useState<File | null>(null)
  const [error, setError] = React.useState('')
  const inputRef = React.useRef<HTMLInputElement>(null)
  const detail = (err: any, fallback: string) => err?.response?.data?.detail || fallback

  const preview = useMutation({
    mutationFn: (f: File) => previewImport(f),
    onError: (err) => setError(detail(err, 'The file could not be read.')),
  })
  const run = useMutation({
    mutationFn: (f: File) => runImport(f),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['materials'] }),
    onError: (err) => setError(detail(err, 'The import did not go through. Nothing was saved.')),
  })
  const template = useMutation({
    mutationFn: downloadImportTemplate,
    onSuccess: (blob) => downloadBlob('mesiri-materials-import.xlsx', blob),
  })

  const clearResults = () => {
    setError('')
    preview.reset()
    run.reset()
  }
  const reset = () => {
    clearResults()
    setFile(null)
    if (inputRef.current) inputRef.current.value = ''
  }
  // A new file: the earlier results go, the chosen file stays in the box.
  const choose = (f: File | null) => {
    clearResults()
    setFile(f)
    if (f) preview.mutate(f)
  }
  const report: ImportReport | undefined = run.data ?? preview.data
  const goingIn = report
    ? SHEETS.reduce((n, s) => n + (report.counts[s]?.added ?? 0) + (report.counts[s]?.placed ?? 0) + (report.counts[s]?.updated ?? 0), 0)
    : 0

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset()
        onOpenChange(o)
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">Import from Excel</DialogTitle>
          <DialogDescription>
            Your items with their categories, your vendors and each site's opening stock, from one workbook. You see what will
            happen before anything is saved.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" className="gap-1.5" disabled={template.isPending} onClick={() => template.mutate()}>
              <Download className="size-3.5" /> {template.isPending ? 'Preparing…' : 'Download the template'}
            </Button>
            <span className="text-muted-foreground">Sheets: Items, Vendors, Opening stock.</span>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="importFile">Your filled workbook (.xlsx)</Label>
            <input
              ref={inputRef}
              id="importFile"
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="text-sm file:mr-3 file:rounded-md file:border file:bg-background file:px-3 file:py-1.5 file:text-sm"
              onChange={(e) => choose(e.target.files?.[0] ?? null)}
            />
          </div>

          {error && (
            <p className="flex items-center gap-2 text-destructive">
              <ShieldAlert className="size-4 shrink-0" /> {error}
            </p>
          )}
          {preview.isPending && <p className="text-muted-foreground">Reading {file?.name}…</p>}

          {report && (
            <section className="flex flex-col gap-3">
              {report.saved ? (
                <p className="flex items-center gap-2 font-medium text-success">
                  <CheckCircle2 className="size-4" /> Imported. {report.problems ? `${report.problems} rows could not go in (below).` : ''}
                </p>
              ) : (
                <p className="font-medium">
                  <FileSpreadsheet className="mr-1.5 inline size-4" />
                  {goingIn} rows will go in{report.problems ? `, ${report.problems} cannot (below)` : ''}. Nothing is saved yet.
                </p>
              )}
              <div className="grid gap-2 sm:grid-cols-3">
                {SHEETS.map((s) => (
                  <div key={s} className="rounded-lg border p-3">
                    <div className="text-xs font-semibold text-muted-foreground">{s}</div>
                    {Object.entries(report.counts[s] ?? {}).length === 0 ? (
                      <div className="text-muted-foreground">Empty</div>
                    ) : (
                      Object.entries(report.counts[s] ?? {}).map(([k, n]) => (
                        <div key={k} className={cn(k === 'problem' && 'text-destructive')}>
                          {n} {WORDS[k as ImportResult]}
                        </div>
                      ))
                    )}
                  </div>
                ))}
              </div>
              {(report.counts.Categories?.added ?? 0) > 0 && (
                <p className="text-muted-foreground">{report.counts.Categories.added} new categories.</p>
              )}
              {report.problems > 0 && (
                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-muted/50 text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 font-semibold">Sheet</th>
                        <th className="px-3 py-2 font-semibold">Row</th>
                        <th className="px-3 py-2 font-semibold">Item / vendor</th>
                        <th className="px-3 py-2 font-semibold">Why it cannot go in</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {report.rows
                        .filter((r) => r.result === 'problem')
                        .map((r) => (
                          <tr key={`${r.sheet}:${r.row}`}>
                            <td className="px-3 py-2 whitespace-nowrap">{r.sheet}</td>
                            <td className="px-3 py-2 tabular-nums">{r.row}</td>
                            <td className="px-3 py-2">{r.name || '—'}</td>
                            <td className="px-3 py-2">{r.message}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {report?.saved ? 'Close' : 'Cancel'}
          </Button>
          {!report?.saved && (
            <Button type="button" disabled={!file || !preview.data || goingIn === 0 || run.isPending} onClick={() => file && run.mutate(file)}>
              {run.isPending ? 'Importing…' : preview.data && goingIn === 0 ? 'Nothing new to import' : `Import ${goingIn} rows`}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
