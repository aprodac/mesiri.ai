import * as React from 'react'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatQuantity, formatRupees } from '@/lib/boq'
import type { BudgetLine, LabourGroup } from '@/lib/cost'

// CC-05: a site's day of one trade (from attendance) put on BOQ lines by man-days. The suggested line is
// preselected and all the man-days not on a line are offered; a person presses Put on line. Several lines split
// the day ("3 masons on plastering, 1 on brickwork"). Nothing is ever put on a line by itself.
// The caller keys a row by its man-days left and suggestion, so the picker starts afresh after each save.

function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

const add = (a: string, b: string) => String(Math.round((Number(a) + Number(b)) * 100) / 100)

export function LabourGroupRow({
  group,
  lines,
  readOnly,
  saving,
  onSave,
}: {
  group: LabourGroup
  lines: BudgetLine[]
  readOnly: boolean
  saving: boolean
  /** The full set of lines the group is on after the change. */
  onSave: (next: { line_id: string; man_days: string }[]) => void
}) {
  const left = group.not_on_a_line.man_days
  const [lineId, setLineId] = React.useState(group.suggested_line_id ?? '')
  const [manDays, setManDays] = React.useState(left)

  const current = group.on_lines.map((p) => ({ line_id: p.line_id, man_days: p.man_days }))
  const md = Number(manDays)
  const valid = !!lineId && md > 0 && md <= Number(left) + 1e-9
  const put = () => {
    const existing = current.find((p) => p.line_id === lineId)
    onSave(
      existing
        ? current.map((p) => (p.line_id === lineId ? { ...p, man_days: add(p.man_days, manDays) } : p))
        : [...current, { line_id: lineId, man_days: manDays }],
    )
  }
  const takeOff = (id: string) => onSave(current.filter((p) => p.line_id !== id))
  const who = group.trade ? group.trade : 'No trade said'

  return (
    <li className="flex flex-col gap-2 px-3 py-2.5">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-3">
        <div className="min-w-0">
          <p className="font-medium capitalize">{who}</p>
          <p className="text-xs text-muted-foreground">
            {formatDay(group.date)}
            {group.site_name ? ` · ${group.site_name}` : ''} ·{' '}
            <span className="tabular-nums">
              {formatQuantity(group.man_days)} man-days{group.cost ? ` · ${formatRupees(group.cost)}` : ' · no wage'}
            </span>
            {group.activities.length > 0 && <> · said: {group.activities.join(', ')}</>}
          </p>
        </div>
        {Number(left) > 0 && Number(left) < Number(group.man_days) && (
          <span className="text-xs text-muted-foreground tabular-nums">{formatQuantity(left)} man-days left</span>
        )}
      </div>

      {group.on_lines.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="On BOQ lines">
          {group.on_lines.map((p) => (
            <li key={p.line_id} className="inline-flex items-center gap-1 rounded-full border bg-muted/50 py-0.5 pl-2.5 pr-1 text-xs">
              <span className="max-w-[220px] truncate">{p.work ?? 'BOQ line'}</span>
              <span className="tabular-nums text-muted-foreground">
                {formatQuantity(p.man_days)} md{p.cost ? ` · ${formatRupees(p.cost)}` : ''}
              </span>
              {!readOnly && (
                <button
                  type="button"
                  className="rounded-full p-0.5 hover:bg-muted"
                  aria-label={`Take ${who} off ${p.work ?? 'this line'}`}
                  disabled={saving}
                  onClick={() => takeOff(p.line_id)}
                >
                  <X className="size-3" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {group.over_allocated && (
        <p className="text-xs text-amber-600 dark:text-amber-400">
          Attendance for this day was sent again with fewer people. The lines share what it cost now; check the split.
        </p>
      )}

      {!readOnly && Number(left) > 0 && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Select value={lineId} onValueChange={setLineId}>
            <SelectTrigger className="h-9 w-full sm:w-[300px]" aria-label={`BOQ line for ${who} on ${formatDay(group.date)}`}>
              <SelectValue placeholder="Pick the BOQ line they worked on" />
            </SelectTrigger>
            <SelectContent>
              {lines.map((l) => (
                <SelectItem key={l.id} value={l.id}>
                  {l.boq_code ? `${l.boq_code} · ` : ''}
                  {l.work}
                  {l.id === group.suggested_line_id ? ' (suggested)' : ''}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              inputMode="decimal"
              min="0.5"
              step="0.5"
              max={left}
              value={manDays}
              onChange={(e) => setManDays(e.target.value)}
              className="h-9 w-24 tabular-nums"
              aria-label="Man-days"
            />
            <span className="text-xs text-muted-foreground">man-days</span>
            <Button size="sm" disabled={!valid || saving} onClick={put}>
              Put on line
            </Button>
          </div>
        </div>
      )}
    </li>
  )
}
