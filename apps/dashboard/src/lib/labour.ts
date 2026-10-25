import {
  fetchAttendanceReportDetailApi,
  fetchAttendanceReportsApi,
  type LabourAttendanceLineItem,
  fetchLabourStatementApi,
  type LabourAttendanceSummaryItem,
  type LabourStatement,
  type LabourStatementType,
} from './api'
import { downloadTextFile, toCsv } from './export'

// Labour page helpers (WEB-22).

/** Every attendance report in the scope and dates (the endpoint pages at
 * 100), newest first; `truncated` when there were more than `cap`. */
export async function fetchAllAttendance(
  params: { project_id?: string; site_id?: string; date_from?: string; date_to?: string },
  cap = 1000,
): Promise<{ items: LabourAttendanceSummaryItem[]; truncated: boolean }> {
  const items: LabourAttendanceSummaryItem[] = []
  let total = 0
  do {
    const page = await fetchAttendanceReportsApi({ ...params, limit: 100, offset: items.length })
    items.push(...page.items)
    total = page.total
    if (page.items.length === 0) break
  } while (items.length < total && items.length < cap)
  items.sort((a, b) => b.occurred_date.localeCompare(a.occurred_date))
  return { items, truncated: items.length < total }
}

/** The four statements the old Labour Reports page offered, now an export. */
export const STATEMENTS: { type: LabourStatementType; label: string; column: string }[] = [
  { type: 'trade_breakdown', label: 'By trade', column: 'Trade' },
  { type: 'subcontractor_ledger', label: 'By contractor', column: 'Contractor' },
  { type: 'daily_attendance', label: 'By day', column: 'Date' },
  { type: 'worker_wages', label: 'By worker', column: 'Worker' },
]

/** Fetches one statement for the scope and dates and downloads it as CSV. */
export async function downloadStatement(
  type: LabourStatementType,
  params: { project_id?: string; site_id?: string; date_from?: string; date_to?: string },
): Promise<LabourStatement> {
  const statement = await fetchLabourStatementApi({ ...params, report_type: type })
  const meta = STATEMENTS.find((s) => s.type === type)!
  // The trade statement's rows are trades already; no second Trade column.
  const withTrade = type !== 'trade_breakdown'
  const csv = toCsv(
    [meta.column, ...(withTrade ? ['Trade'] : []), 'Contractor', 'Man-days', 'Man-days with a wage', 'Days worked', 'First day', 'Last day', 'Reports', 'Average daily wage (INR)', 'Cost (INR)', '% of cost'],
    statement.rows.map((r) => [
      r.title,
      ...(withTrade ? [r.category] : []),
      r.contractor,
      r.man_days,
      r.priced_man_days,
      r.days_worked,
      r.first_date,
      r.last_date,
      r.report_count,
      r.avg_daily_wage,
      r.total_cost,
      r.percentage,
    ]),
  )
  downloadTextFile(`labour-${meta.label.toLowerCase().replace(/\s+/g, '-')}-${rangeName(params.date_from, params.date_to)}.csv`, csv)
  return statement
}

/** "2026-10-01_to_2026-10-31", "from-2026-10-01", or "all-time". */
export function rangeName(from?: string, to?: string): string {
  if (from && to) return `${from}_to_${to}`
  if (from) return `from-${from}`
  if (to) return `to-${to}`
  return 'all-time'
}

/** One attendance line with the report it came from: a row of the labour
 * ledger. */
export interface AttendanceLedgerRow {
  report: LabourAttendanceSummaryItem
  line: LabourAttendanceLineItem
}

/**
 * Every line (trade or named worker) of `reports`, newest first. The list
 * endpoint returns only totals, so each report's detail is read -- six at a
 * time, the newest `cap` reports (`truncated` when there were more).
 */
export async function fetchAttendanceLines(
  reports: LabourAttendanceSummaryItem[],
  cap = 400,
): Promise<{ rows: AttendanceLedgerRow[]; truncated: boolean }> {
  const wanted = reports.slice(0, cap)
  const byReport = new Map<string, LabourAttendanceLineItem[]>()
  let next = 0
  const worker = async () => {
    while (next < wanted.length) {
      const r = wanted[next++]
      const detail = await fetchAttendanceReportDetailApi(r.id)
      byReport.set(r.id, detail.lines ?? [])
    }
  }
  await Promise.all(Array.from({ length: Math.min(6, wanted.length) }, worker))
  const rows = wanted.flatMap((report) => (byReport.get(report.id) ?? []).map((line) => ({ report, line })))
  return { rows, truncated: reports.length > cap }
}
