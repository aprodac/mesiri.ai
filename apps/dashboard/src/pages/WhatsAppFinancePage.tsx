import * as React from 'react'
import {
  Zap,
  Smartphone,
  Terminal,
  AlertTriangle,
  ArrowLeftRight,
  CreditCard,
  BellRing,
} from 'lucide-react'
import { KpiCard } from '@/components/ui/kpi-card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { VpsHealthBar } from '@/components/whatsapp/vps-health-bar'
import { WhatsAppPhoneMockup } from '@/components/whatsapp/whatsapp-phone-mockup'
import { AutomationRuleCard } from '@/components/whatsapp/automation-rule-card'
import { PhoneMappingTable } from '@/components/whatsapp/phone-mapping-table'
import { WhatsAppTraceLogs } from '@/components/whatsapp/whatsapp-trace-logs'
import { WhatsAppSandboxDialog } from '@/components/whatsapp/whatsapp-sandbox-dialog'

import {
  fetchCompanySummary,
  type CompanySummary,
  fetchFinanceSettingsApi,
  updateFinanceSettingsApi,
} from '@/lib/api'

export default function WhatsAppFinancePage() {
  const [summary, setSummary] = React.useState<CompanySummary | null>(null)

  // Rule Toggles & Values
  const [lowBalanceEnabled, setLowBalanceEnabled] = React.useState(true)
  const [lowBalanceThreshold, setLowBalanceThreshold] = React.useState(50000)
  const [transferReceiptEnabled, setTransferReceiptEnabled] = React.useState(true)
  const [expenseCardEnabled, setExpenseCardEnabled] = React.useState(true)
  const [showVisualCard] = React.useState(true)
  const [weeklyDigestEnabled, setWeeklyDigestEnabled] = React.useState(true)
  const [weeklyDigestSchedule, setWeeklyDigestSchedule] = React.useState('weekly_monday')

  React.useEffect(() => {
    let active = true
    async function loadData() {
      try {
        const [sum, settings] = await Promise.all([
          fetchCompanySummary().catch(() => null),
          fetchFinanceSettingsApi().catch(() => null),
        ])
        if (active) {
          if (sum) setSummary(sum)
          if (settings) {
            if (settings.low_float_threshold) setLowBalanceThreshold(Number(settings.low_float_threshold))
            if (settings.low_balance_warning_enabled !== undefined) setLowBalanceEnabled(settings.low_balance_warning_enabled)
            if (settings.transfer_receipt_enabled !== undefined) setTransferReceiptEnabled(settings.transfer_receipt_enabled)
            if (settings.expense_card_enabled !== undefined) setExpenseCardEnabled(settings.expense_card_enabled)
            if (settings.weekly_digest_enabled !== undefined) setWeeklyDigestEnabled(settings.weekly_digest_enabled)
            if (settings.weekly_digest_schedule) setWeeklyDigestSchedule(settings.weekly_digest_schedule)
          }
        }
      } catch (err) {
        console.warn('Failed to load initial data for WhatsApp page:', err)
      }
    }
    loadData()
    return () => {
      active = false
    }
  }, [])

  // Automation Rule Tab state
  const [activeRuleTab, setActiveRuleTab] = React.useState('low_balance')
  // Sandbox Dialog State
  const [sandboxOpen, setSandboxOpen] = React.useState(false)

  const handleToggleLowBalance = async (enabled: boolean) => {
    setLowBalanceEnabled(enabled)
    try {
      await updateFinanceSettingsApi({ low_balance_warning_enabled: enabled })
    } catch (err) {
      console.warn('Failed to update low balance setting:', err)
    }
  }

  const handleThresholdChange = async (val: number) => {
    setLowBalanceThreshold(val)
    try {
      await updateFinanceSettingsApi({ low_float_threshold: val })
    } catch (err) {
      console.warn('Failed to update threshold:', err)
    }
  }

  const handleToggleTransfer = async (enabled: boolean) => {
    setTransferReceiptEnabled(enabled)
    try {
      await updateFinanceSettingsApi({ transfer_receipt_enabled: enabled })
    } catch (err) {
      console.warn('Failed to update transfer receipt setting:', err)
    }
  }

  const handleToggleExpenseCard = async (enabled: boolean) => {
    setExpenseCardEnabled(enabled)
    try {
      await updateFinanceSettingsApi({ expense_card_enabled: enabled })
    } catch (err) {
      console.warn('Failed to update expense card setting:', err)
    }
  }

  const handleToggleWeeklyDigest = async (enabled: boolean) => {
    setWeeklyDigestEnabled(enabled)
    try {
      await updateFinanceSettingsApi({ weekly_digest_enabled: enabled })
    } catch (err) {
      console.warn('Failed to update weekly digest setting:', err)
    }
  }

  const handleWeeklyDigestScheduleChange = async (val: string) => {
    setWeeklyDigestSchedule(val)
    try {
      await updateFinanceSettingsApi({ weekly_digest_schedule: val })
    } catch (err) {
      console.warn('Failed to update weekly digest schedule:', err)
    }
  }


  return (
    <div className="flex flex-col gap-4 w-full max-w-full relative pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3.5">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Finance on WhatsApp</h1>
          </div>
        </div>
      </div>

      {/* VPS Bot Live Health Banner */}
      <VpsHealthBar onOpenSandbox={() => setSandboxOpen(true)} />

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          title="Registered personnel"
          value={
            <span>
              {summary ? `${summary.total_users} Members` : 'Live DB'}
            </span>
          }
          description="Organization team members"
          icon={<Smartphone  />}
        />
        <KpiCard
          title="Active projects"
          value={
            <span>
              {summary ? `${summary.total_projects} Projects` : 'Live DB'}
            </span>
          }
          description="Managed project scopes"
          icon={<CreditCard  />}
        />
        <KpiCard
          title="Active sites"
          value={
            <span>
              {summary ? `${summary.total_sites} Sites` : 'Live DB'}
            </span>
          }
          description="Active construction sites"
          icon={<BellRing  />}
        />
      </div>

      {/* Core Tabs: Automations vs Custodians vs Logs */}
      <Tabs defaultValue="automations" className="w-full">
        <TabsList className="w-full sm:w-auto grid grid-cols-3 h-9 bg-muted/60 p-1">
          <TabsTrigger value="automations" className="text-xs gap-1.5 font-semibold">
            <Zap className="size-3.5 text-emerald-500" />
            Automations & Triggers
          </TabsTrigger>
          <TabsTrigger value="custodians" className="text-xs gap-1.5 font-semibold">
            <Smartphone className="size-3.5 text-blue-500" />
            Custodian Phone Mappings
          </TabsTrigger>
          <TabsTrigger value="logs" className="text-xs gap-1.5 font-semibold">
            <Terminal className="size-3.5 text-purple-500" />
            WhatsApp Activity Audit Log
          </TabsTrigger>
        </TabsList>

        {/* Tab 1: Automations & Triggers (Split-View Rule Builder + Phone Mockup) */}
        <TabsContent value="automations" className="pt-3">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
            {/* Left Column: Rule Cards list */}
            <div className="lg:col-span-7 flex flex-col gap-3">
              <h2 className="text-sm font-bold text-foreground flex items-center justify-between border-b pb-2">
                <span>Configure WhatsApp Triggers</span>
                <span className="text-[11px] text-muted-foreground font-normal">
                  Click a rule card to preview on phone
                </span>
              </h2>

              <AutomationRuleCard
                id="low_balance"
                title="Low Petty Cash Float Warning"
                description="Automatically sends a WhatsApp alert to the Site PM & Finance Controller when site petty cash drops below threshold."
                enabled={lowBalanceEnabled}
                icon={<AlertTriangle className="size-4" />}
                badgeText="Treasury Alert"
                active={activeRuleTab === 'low_balance'}
                onSelect={() => setActiveRuleTab('low_balance')}
                onToggle={handleToggleLowBalance}
                thresholdValue={lowBalanceThreshold}
                onThresholdChange={handleThresholdChange}
              />

              <AutomationRuleCard
                id="transfer_receipt"
                title="Inter-Account Transfer Confirmation"
                description="Sends an instant WhatsApp transfer receipt to the site custodian when funds are moved on the web dashboard."
                enabled={transferReceiptEnabled}
                icon={<ArrowLeftRight className="size-4" />}
                badgeText="Transfer Receipt"
                active={activeRuleTab === 'transfer_receipt'}
                onSelect={() => setActiveRuleTab('transfer_receipt')}
                onToggle={handleToggleTransfer}
              />

              <AutomationRuleCard
                id="expense_card"
                title="Post-Confirmation PNG Receipt Cards"
                description="Renders a Jinja2 Playwright visual PNG receipt card and replies on WhatsApp whenever an expense is logged."
                enabled={expenseCardEnabled}
                icon={<CreditCard className="size-4" />}
                badgeText="Visual Card"
                active={activeRuleTab === 'expense_card'}
                onSelect={() => setActiveRuleTab('expense_card')}
                onToggle={handleToggleExpenseCard}
              />

              <AutomationRuleCard
                id="weekly_digest"
                title="Weekly Outstanding Expense Digest"
                description="Sends an automated summary of unpaid vendor expenses to finance managers every Monday morning."
                enabled={weeklyDigestEnabled}
                icon={<BellRing className="size-4" />}
                badgeText="Scheduled Cron"
                active={activeRuleTab === 'weekly_digest'}
                onSelect={() => setActiveRuleTab('weekly_digest')}
                onToggle={handleToggleWeeklyDigest}
                scheduleValue={weeklyDigestSchedule}
                onScheduleChange={handleWeeklyDigestScheduleChange}
              />
            </div>

            {/* Right Column: Live Phone Mockup Preview */}
            <div className="lg:col-span-5 flex flex-col items-center gap-2 border p-4 rounded-xl bg-card/40 sticky top-4">
              <span className="text-xs font-bold text-foreground flex items-center gap-1.5">
                <Smartphone className="size-4 text-emerald-500" />
                Live WhatsApp Screen Mockup
              </span>
              <p className="text-[11px] text-muted-foreground text-center mb-2">
                Real-time preview of how messages appear on field worker phones.
              </p>

              <WhatsAppPhoneMockup
                activeRule={activeRuleTab}
                lowBalanceThreshold={lowBalanceThreshold}
                showTransferReceipt={transferReceiptEnabled}
                showVisualCard={showVisualCard}
              />
            </div>
          </div>
        </TabsContent>

        {/* Tab 2: Custodians & Phone Mappings */}
        <TabsContent value="custodians" className="pt-3">
          <PhoneMappingTable />
        </TabsContent>

        {/* Tab 3: Live Trace Stream */}
        <TabsContent value="logs" className="pt-3">
          <WhatsAppTraceLogs />
        </TabsContent>
      </Tabs>

      {/* Testing Sandbox Modal */}
      <WhatsAppSandboxDialog open={sandboxOpen} onOpenChange={setSandboxOpen} />
    </div>
  )
}
