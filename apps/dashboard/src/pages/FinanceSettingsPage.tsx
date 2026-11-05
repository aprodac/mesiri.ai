import * as React from 'react'
import {
  Settings,
  DollarSign,
  Landmark,
  Save,
  MessageSquare,
  Receipt,
  Check,
} from 'lucide-react'
import { useToast } from '@/components/ui/toast-notification'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  fetchFinanceSettingsApi,
  updateFinanceSettingsApi,
} from '@/lib/api'

const PAYMENT_METHODS_LIST = [
  { id: 'bank_transfer', label: 'Bank Transfer (NEFT / RTGS / IMPS)', description: 'Direct account-to-account payouts' },
  { id: 'upi', label: 'UPI / QR Code', description: 'Instant digital wallet payments via WhatsApp or Web' },
  { id: 'cash', label: 'Petty Cash Desk', description: 'Cash float disbursements by site custodians' },
  { id: 'cheque', label: 'Cheque Disbursement', description: 'Physical cheque issues' },
  { id: 'card', label: 'Corporate Card', description: 'Executive credit & debit cards' },
]

export default function FinanceSettingsPage() {
  const toast = useToast()

  const [saving, setSaving] = React.useState(false)

  // Settings State
  const [baseCurrency, setBaseCurrency] = React.useState('INR')
  const [currencySymbol, setCurrencySymbol] = React.useState('₹')
  const [fiscalYearStart, setFiscalYearStart] = React.useState('04-01')
  const [lowFloatThreshold, setLowFloatThreshold] = React.useState('50000')
  const [autoApprovalLimit, setAutoApprovalLimit] = React.useState('5000')
  const [requireReceiptAbove, setRequireReceiptAbove] = React.useState('1000')
  const [duplicateWindowHours, setDuplicateWindowHours] = React.useState('24')
  const [defaultTaxRate, setDefaultTaxRate] = React.useState('18')
  const [enabledPaymentMethods, setEnabledPaymentMethods] = React.useState<string[]>([
    'bank_transfer',
    'cash',
    'upi',
    'cheque',
    'card',
  ])

  const loadSettings = React.useCallback(async () => {
    try {
      const data = await fetchFinanceSettingsApi()
      if (data) {
        setBaseCurrency(data.base_currency || 'INR')
        setCurrencySymbol(data.currency_symbol || '₹')
        setFiscalYearStart(data.fiscal_year_start || '04-01')
        setLowFloatThreshold(String(data.low_float_threshold || 50000))
        setAutoApprovalLimit(String(data.auto_approval_limit || 5000))
        setRequireReceiptAbove(String(data.require_receipt_above || 1000))
        setDuplicateWindowHours(String(data.duplicate_window_hours || 24))
        setDefaultTaxRate(String(data.default_tax_rate || 18))
        if (Array.isArray(data.enabled_payment_methods)) {
          setEnabledPaymentMethods(data.enabled_payment_methods)
        }
      }
    } catch (err) {
      console.warn('Failed to load finance settings from backend:', err)
    }
  }, [])

  React.useEffect(() => {
    loadSettings()
  }, [loadSettings])

  const togglePaymentMethod = (id: string) => {
    setEnabledPaymentMethods((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id]
    )
  }

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await updateFinanceSettingsApi({
        base_currency: baseCurrency,
        currency_symbol: currencySymbol,
        fiscal_year_start: fiscalYearStart,
        low_float_threshold: parseFloat(lowFloatThreshold) || 50000,
        auto_approval_limit: parseFloat(autoApprovalLimit) || 5000,
        require_receipt_above: parseFloat(requireReceiptAbove) || 1000,
        duplicate_window_hours: parseInt(duplicateWindowHours) || 24,
        default_tax_rate: parseFloat(defaultTaxRate) || 18,
        enabled_payment_methods: enabledPaymentMethods,
      })
      toast.success('Finance preferences saved', 'Organization policies updated successfully')
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err.message || 'Failed to save settings'
      toast.error('Save failed', msg)
    } finally {
      setSaving(false)
    }
  }


  return (
    <div className="flex flex-col gap-5 w-full max-w-full relative pb-20">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b pb-4">
        <div className="flex items-center gap-3">
          <div className="size-11 rounded-xl border border-slate-500/30 bg-slate-500/10 flex items-center justify-center text-slate-700 dark:text-slate-300 shrink-0 shadow-2xs">
            <Settings className="size-6" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Finance settings</h1>
          </div>
        </div>
      </div>

      <form onSubmit={handleSaveSettings}>
        <Tabs defaultValue="general" className="w-full">
          <TabsList className="grid grid-cols-3 w-full max-w-md h-9 text-xs mb-4">
            <TabsTrigger value="general" className="text-xs">General & Tax</TabsTrigger>
            <TabsTrigger value="whatsapp" className="text-xs">WhatsApp Assistant</TabsTrigger>
            <TabsTrigger value="payments" className="text-xs">Payment Methods</TabsTrigger>
          </TabsList>

          {/* Tab 1: General & Tax */}
          <TabsContent value="general" className="flex flex-col gap-4">
            <Card className="p-5 border flex flex-col gap-4 shadow-2xs">
              <div className="flex items-center gap-2 border-b pb-3 text-emerald-600 dark:text-emerald-400">
                <DollarSign className="size-5" />
                <h3 className="font-bold text-sm text-foreground">Base Currency & Fiscal Year</h3>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-semibold">Base Currency</Label>
                  <Select value={baseCurrency} onValueChange={(val) => {
                    setBaseCurrency(val)
                    if (val === 'INR') setCurrencySymbol('₹')
                    else if (val === 'USD') setCurrencySymbol('$')
                    else if (val === 'EUR') setCurrencySymbol('€')
                    else if (val === 'AED') setCurrencySymbol('AED')
                  }}>
                    <SelectTrigger className="h-9 text-xs">
                      <SelectValue placeholder="Select currency" />
                    </SelectTrigger>
                    <SelectContent className="text-xs">
                      <SelectItem value="INR">INR (₹) — Indian Rupee</SelectItem>
                      <SelectItem value="USD">USD ($) — US Dollar</SelectItem>
                      <SelectItem value="EUR">EUR (€) — Euro</SelectItem>
                      <SelectItem value="AED">AED (AED) — UAE Dirham</SelectItem>
                    </SelectContent>
                  </Select>
                  <span className="text-[11px] text-muted-foreground">Main ledger accounting currency.</span>
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-semibold">Fiscal Year Start Date</Label>
                  <Select value={fiscalYearStart} onValueChange={setFiscalYearStart}>
                    <SelectTrigger className="h-9 text-xs">
                      <SelectValue placeholder="Select FY start" />
                    </SelectTrigger>
                    <SelectContent className="text-xs">
                      <SelectItem value="04-01">April 1st (India FY: Apr — Mar)</SelectItem>
                      <SelectItem value="01-01">January 1st (Calendar FY: Jan — Dec)</SelectItem>
                    </SelectContent>
                  </Select>
                  <span className="text-[11px] text-muted-foreground">Used for annual budget & tax reporting.</span>
                </div>
              </div>
            </Card>

            <Card className="p-5 border flex flex-col gap-4 shadow-2xs">
              <div className="flex items-center gap-2 border-b pb-3 text-purple-600 dark:text-purple-400">
                <Receipt className="size-5" />
                <h3 className="font-bold text-sm text-foreground">Tax & GST Configuration</h3>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-semibold">Default Tax / GST Rate (%)</Label>
                  <Select value={defaultTaxRate} onValueChange={setDefaultTaxRate}>
                    <SelectTrigger className="h-9 text-xs">
                      <SelectValue placeholder="Select GST rate" />
                    </SelectTrigger>
                    <SelectContent className="text-xs">
                      <SelectItem value="0">0% — Exempt / Nil Rated</SelectItem>
                      <SelectItem value="5">5% — Reduced GST</SelectItem>
                      <SelectItem value="12">12% — Standard Goods GST</SelectItem>
                      <SelectItem value="18">18% — Services / Supplies GST</SelectItem>
                      <SelectItem value="28">28% — Luxury / Equipment GST</SelectItem>
                    </SelectContent>
                  </Select>
                  <span className="text-[11px] text-muted-foreground">Applied to new corporate expense entries.</span>
                </div>
              </div>
            </Card>
          </TabsContent>

          {/* Tab 2: WhatsApp Assistant Policies */}
          <TabsContent value="whatsapp" className="flex flex-col gap-4">
            <Card className="p-5 border flex flex-col gap-4 shadow-2xs">
              <div className="flex items-center gap-2 border-b pb-3 text-blue-600 dark:text-blue-400">
                <MessageSquare className="size-5" />
                <h3 className="font-bold text-sm text-foreground">WhatsApp Automation & Limits</h3>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-semibold">Auto-Approval Expense Limit ({currencySymbol})</Label>
                  <Input
                    type="number"
                    value={autoApprovalLimit}
                    onChange={(e) => setAutoApprovalLimit(e.target.value)}
                    className="h-9 text-xs font-mono"
                    placeholder="5000"
                  />
                  <span className="text-[11px] text-muted-foreground">
                    Expenses at or below this amount recorded via WhatsApp are auto-confirmed.
                  </span>
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-semibold">Mandatory Receipt Photo Threshold ({currencySymbol})</Label>
                  <Input
                    type="number"
                    value={requireReceiptAbove}
                    onChange={(e) => setRequireReceiptAbove(e.target.value)}
                    className="h-9 text-xs font-mono"
                    placeholder="1000"
                  />
                  <span className="text-[11px] text-muted-foreground">
                    WhatsApp assistant prompts user for receipt image if amount exceeds threshold.
                  </span>
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-semibold">Petty Cash Low-Float Warning ({currencySymbol})</Label>
                  <Input
                    type="number"
                    value={lowFloatThreshold}
                    onChange={(e) => setLowFloatThreshold(e.target.value)}
                    className="h-9 text-xs font-mono"
                    placeholder="50000"
                  />
                  <span className="text-[11px] text-muted-foreground">
                    Triggers low float badge alert when custodian balance drops below threshold.
                  </span>
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-semibold">Duplicate Check Lookback Window</Label>
                  <Select value={duplicateWindowHours} onValueChange={setDuplicateWindowHours}>
                    <SelectTrigger className="h-9 text-xs">
                      <SelectValue placeholder="Select lookback hours" />
                    </SelectTrigger>
                    <SelectContent className="text-xs">
                      <SelectItem value="12">12 Hours</SelectItem>
                      <SelectItem value="24">24 Hours (Recommended)</SelectItem>
                      <SelectItem value="48">48 Hours</SelectItem>
                    </SelectContent>
                  </Select>
                  <span className="text-[11px] text-muted-foreground">
                    Flags duplicate expense submissions within window.
                  </span>
                </div>
              </div>
            </Card>
          </TabsContent>

          {/* Tab 3: Payment Methods */}
          <TabsContent value="payments" className="flex flex-col gap-4">
            <Card className="p-5 border flex flex-col gap-4 shadow-2xs">
              <div className="flex items-center gap-2 border-b pb-3 text-indigo-600 dark:text-indigo-400">
                <Landmark className="size-5" />
                <h3 className="font-bold text-sm text-foreground">Enabled Payment & Payout Methods</h3>
              </div>

              <div className="flex flex-col gap-3 text-xs">
                {PAYMENT_METHODS_LIST.map((method) => {
                  const isChecked = enabledPaymentMethods.includes(method.id)
                  return (
                    <div
                      key={method.id}
                      onClick={() => togglePaymentMethod(method.id)}
                      className={`p-3.5 rounded-lg border flex items-center justify-between cursor-pointer transition-all ${
                        isChecked
                          ? 'border-indigo-500/50 bg-indigo-500/5 text-foreground'
                          : 'border-border bg-card hover:bg-muted/30 text-muted-foreground'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className={`size-5 rounded border flex items-center justify-center transition-colors ${
                          isChecked ? 'bg-indigo-600 border-indigo-600 text-white' : 'border-border'
                        }`}>
                          {isChecked && <Check className="size-3.5 stroke-[3]" />}
                        </div>
                        <div className="flex flex-col">
                          <span className="font-bold text-xs text-foreground">{method.label}</span>
                          <span className="text-[11px] text-muted-foreground">{method.description}</span>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </Card>
          </TabsContent>
        </Tabs>

        {/* Floating / Bottom Save Bar */}
        <div className="fixed bottom-4 right-4 sm:right-6 z-40 bg-card/90 backdrop-blur-md border shadow-lg rounded-xl p-3 flex items-center gap-3">
          <span className="text-xs text-muted-foreground hidden sm:inline">
            All changes apply across Web Dashboard & WhatsApp Assistant
          </span>
          <Button
            type="submit"
            disabled={saving}
            size="sm"
            className="h-8 text-xs font-semibold gap-1.5 shadow-2xs"
          >
            <Save className="size-3.5" />
            {saving ? 'Saving Preferences...' : 'Save Preferences'}
          </Button>
        </div>
      </form>
    </div>
  )
}
