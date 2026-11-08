import * as React from 'react'
import { FileSpreadsheet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast-notification'
import { downloadCostExcel } from '@/lib/cost'
import { downloadBlob } from '@/lib/export'
import { apiErrorMessage } from '@/lib/logo-upload'

/** CC-21: the project's cost control as one Excel workbook (Summary, BOQ lines, Green-red, Materials). */
export function CostExportButton({
  projectId,
  projectName,
  period,
}: {
  projectId: string
  projectName?: string
  period?: { date_from: string; date_to: string }
}) {
  const toast = useToast()
  const [busy, setBusy] = React.useState(false)
  const download = async () => {
    setBusy(true)
    try {
      const { blob, filename } = await downloadCostExcel(projectId, period, projectName)
      downloadBlob(filename, blob)
    } catch (err) {
      toast.error('Could not make the Excel file', apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button size="sm" variant="outline" className="gap-1.5" onClick={download} disabled={busy}>
      <FileSpreadsheet className="size-3.5" /> {busy ? 'Preparing…' : 'Excel'}
    </Button>
  )
}
