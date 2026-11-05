import * as React from 'react'
import {
  FileText,
  Download,
  Printer,
  Calendar,
  Search,
  DollarSign,
  TrendingDown,
  TrendingUp,
  PieChart as PieIcon,
  Store,
  Wallet,
  Landmark,
  RefreshCw,
} from 'lucide-react'
import { useToast } from '@/components/ui/toast-notification'
import { KpiCard } from '@/components/ui/kpi-card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { toLocalISODate } from '@/lib/utils'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  fetchFinanceReportApi,
  type FinanceReportStatementItem,
} from '@/lib/api'

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

const REPORT_TYPES = [
  { id: 'pnl', label: 'Income & Expense (P&L)', icon: FileText, desc: 'Revenue vs Operational Expenditure' },
  { id: 'category_breakdown', label: 'Category Expenditure Audit', icon: PieIcon, desc: 'Detailed cost breakdown by category' },
  { id: 'cashflow', label: 'Cash Flow & Accounts', icon: Landmark, desc: 'Liquidity movement across bank/cash accounts' },
  { id: 'vendor_ledger', label: 'Vendor Outstandings', icon: Store, desc: 'Supplier payables & outstanding bills' },
  { id: 'petty_cash', label: 'Petty Cash Reconciliation', icon: Wallet, desc: 'Custodian float allocation & claims' },
]

export default function FinanceReportsPage() {
  const toast = useToast()

  const [activeReport, setActiveReport] = React.useState('pnl')
  const [datePreset, setDatePreset] = React.useState('ALL')
  const [search, setSearch] = React.useState('')
  const [statement, setStatement] = React.useState<FinanceReportStatementItem | null>(null)
  const [loading, setLoading] = React.useState(true)

  const loadStatement = React.useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchFinanceReportApi({ report_type: activeReport })
      if (data) setStatement(data)
    } catch (err) {
      console.warn('Failed to load financial report statement:', err)
    } finally {
      setLoading(false)
    }
  }, [activeReport])

  React.useEffect(() => {
    loadStatement()
  }, [loadStatement])

  const filteredRows = React.useMemo(() => {
    if (!statement?.rows) return []
    return statement.rows.filter((r) => {
      const query = search.toLowerCase()
      return (
        r.title.toLowerCase().includes(query) ||
        (r.category && r.category.toLowerCase().includes(query)) ||
        (r.code && r.code.toLowerCase().includes(query))
      )
    })
  }, [statement, search])

  const handleExportCSV = () => {
    if (!statement || !statement.rows) return

    const headers = ['Line Item / Title', 'Code', 'Category', 'Tax', 'Status', 'Percentage (%)', 'Amount (INR)', 'Notes']
    const csvRows = [headers.join(',')]

    for (const r of statement.rows) {
      const rowData = [
        `"${r.title.replace(/"/g, '""')}"`,
        `"${r.code || ''}"`,
        `"${r.category || ''}"`,
        `"${(r as any).tax_amount ? `₹${(r as any).tax_amount}` : '—'}"`,
        `"${r.status || 'Active'}"`,
        `"${r.percentage ? `${r.percentage}%` : 'N/A'}"`,
        `"${parseFloat(String(r.amount)) || 0}"`,
        `"${r.notes || ''}"`,
      ]
      csvRows.push(rowData.join(','))
    }

    const csvContent = 'data:text/csv;charset=utf-8,' + csvRows.join('\n')
    const encodedUri = encodeURI(csvContent)
    const link = document.createElement('a')
    link.setAttribute('href', encodedUri)
    link.setAttribute('download', `Finance_Report_${activeReport}_${toLocalISODate()}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    toast.success('Report exported to CSV', `Saved statement ${activeReport.toUpperCase()} formatted for Excel`)
  }

  const handlePrint = () => {
    window.print()
  }


  return (
    <div className="flex flex-col gap-5 w-full max-w-full relative pb-16">
      {/* Header & Export Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b pb-4">
        <div className="flex items-center gap-3">
          <div className="size-11 rounded-xl border border-indigo-500/30 bg-indigo-500/10 flex items-center justify-center text-indigo-600 dark:text-indigo-400 shrink-0 shadow-2xs">
            <FileText className="size-6" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Finance reports</h1>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs font-semibold gap-1.5 shadow-2xs"
            onClick={loadStatement}
          >
            <RefreshCw className="size-3.5" />
            Refresh
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs font-semibold gap-1.5 shadow-2xs"
            onClick={handlePrint}
          >
            <Printer className="size-3.5" />
            Print / PDF
          </Button>
          <Button
            size="sm"
            className="h-8 text-xs font-semibold gap-1.5 shadow-2xs"
            onClick={handleExportCSV}
          >
            <Download className="size-3.5" />
            Export CSV
          </Button>
        </div>
      </div>

      {/* Report Type Selector Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {REPORT_TYPES.map((rep) => {
          const Icon = rep.icon
          const isSelected = activeReport === rep.id
          return (
            <Card
              key={rep.id}
              onClick={() => setActiveReport(rep.id)}
              className={`p-3.5 border cursor-pointer transition-all duration-200 flex flex-col gap-2 relative overflow-hidden ${
                isSelected
                  ? 'border-emerald-500/60 bg-emerald-500/5 shadow-2xs'
                  : 'bg-card hover:bg-muted/40 text-muted-foreground'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className={`p-1.5 rounded-md ${isSelected ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-muted text-muted-foreground'}`}>
                  <Icon className="size-4" />
                </div>
                {isSelected && (
                  <Badge className="bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[9px] px-1 py-0">
                    Active
                  </Badge>
                )}
              </div>
              <div>
                <h3 className={`font-bold text-xs ${isSelected ? 'text-foreground' : 'text-foreground/90'}`}>
                  {rep.label}
                </h3>
                <p className="text-[10px] text-muted-foreground line-clamp-1 mt-0.5">{rep.desc}</p>
              </div>
            </Card>
          )
        })}
      </div>

      {/* Statement Header KPI Summary Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <KpiCard
          title="Total operating revenues"
          value={
            <span>
              {formatCurrency(parseFloat(String(statement?.total_inflows || 0)))}
            </span>
          }
          description="Total client payments & inflows"
          icon={<TrendingUp  />}
        />
        <KpiCard
          title="Total operational disbursements"
          value={
            <span>
              {formatCurrency(parseFloat(String(statement?.total_outflows || 0)))}
            </span>
          }
          description="Total confirmed expenditure"
          icon={<TrendingDown  />}
        />
        <KpiCard
          title="Net operating margin"
          value={
            <span className={parseFloat(String(statement?.net_margin || 0)) >= 0 ? 'text-emerald-600' : 'text-rose-600 dark:text-rose-400'}>
              {formatCurrency(parseFloat(String(statement?.net_margin || 0)))}
            </span>
          }
          description="Revenues minus total expenses"
          icon={<DollarSign  />}
        />
      </div>

      {/* Filter & Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-muted/20 p-3 rounded-lg border">
        <div className="relative w-full sm:w-72">
          <Search className="size-3.5 absolute left-3 top-2.5 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter statement line items..."
            className="pl-8 h-8 text-xs bg-background"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <Select value={datePreset} onValueChange={setDatePreset}>
            <SelectTrigger className="h-8 text-xs w-[160px] bg-background">
              <SelectValue placeholder="Select period" />
            </SelectTrigger>
            <SelectContent className="text-xs">
              <SelectItem value="ALL">All Time</SelectItem>
              <SelectItem value="THIS_MONTH">This Month</SelectItem>
              <SelectItem value="LAST_MONTH">Last Month</SelectItem>
              <SelectItem value="THIS_QUARTER">This Quarter</SelectItem>
              <SelectItem value="YTD">Year to Date (YTD)</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Statement Document Container */}
      <Card className="p-6 border shadow-2xs flex flex-col gap-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-2 border-b pb-4">
          <div>
            <h2 className="text-base font-bold text-foreground">{statement?.title || 'Financial Statement'}</h2>
            <p className="text-xs text-muted-foreground">{statement?.subtitle}</p>
          </div>

          <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
            <Calendar className="size-3.5 text-emerald-500" />
            Generated: {statement?.generated_at || 'Live Data'}
          </div>
        </div>

        {/* Statement Data Table */}
        <div className="border rounded-lg overflow-hidden bg-card">
          <Table>
            <TableHeader className="bg-muted/50">
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs font-semibold h-10">Code / Ref</TableHead>
                <TableHead className="text-xs font-semibold h-10">Line Item Description</TableHead>
                <TableHead className="text-xs font-semibold h-10">Classification</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-center">Share (%)</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right">Amount (₹)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-xs text-muted-foreground">
                    Generating statement line items...
                  </TableCell>
                </TableRow>
              ) : filteredRows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-xs text-muted-foreground">
                    No statement line items found matching your criteria.
                  </TableCell>
                </TableRow>
              ) : (
                filteredRows.map((r) => {
                  const amount = parseFloat(String(r.amount)) || 0
                  return (
                    <TableRow key={r.id} className="hover:bg-muted/40 transition-colors">
                      <TableCell className="font-mono text-xs text-muted-foreground font-medium">
                        {r.code || 'SYS-LINE'}
                      </TableCell>
                      <TableCell className="font-semibold text-xs text-foreground">
                        <div>{r.title}</div>
                        {r.notes && <span className="text-[10px] text-muted-foreground block">{r.notes}</span>}
                      </TableCell>
                      <TableCell className="text-xs">
                        <Badge variant="outline" className="text-[10px]">
                          {r.category || 'Disbursement'}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs font-mono text-center">
                        {r.percentage !== null && r.percentage !== undefined ? `${r.percentage}%` : '—'}
                      </TableCell>
                      <TableCell className="text-xs font-mono font-bold text-right tabular-nums text-foreground">
                        {formatCurrency(amount)}
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>

          {/* Statement Footer Totals */}
          <div className="flex items-center justify-between p-3.5 bg-muted/40 border-t text-xs font-bold">
            <span>Statement Total Expenditure</span>
            <span className="font-mono text-sm text-foreground">
              {formatCurrency(parseFloat(String(statement?.total_outflows || 0)))}
            </span>
          </div>
        </div>
      </Card>
    </div>
  )
}
