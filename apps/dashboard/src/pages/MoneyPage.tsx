import * as React from 'react'
import { BooksLink } from '@/components/accounts/books'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftRight, CheckCircle2, ChevronRight, Download, Filter, HandCoins, Landmark, MoreHorizontal, PiggyBank, Plus, TriangleAlert, Undo2, Wallet } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Callout, Segmented } from '@/components/dpr-page'
import { FilterSelect, PeriodSelect } from '@/components/filter-select'
import { AccountDetailSheet } from '@/components/accounts/account-detail-sheet'
import { AccountDialog } from '@/components/accounts/account-dialog'
import { TransferMoneyDialog } from '@/components/accounts/transfer-money-dialog'
import { CashBoxDetailSheet } from '@/components/petty-cash/cash-box-detail-sheet'
import { RecordVoucherDialog } from '@/components/petty-cash/record-voucher-dialog'
import { ReplenishFloatDialog } from '@/components/petty-cash/replenish-float-dialog'
import { useScope } from '@/lib/ScopeContext'
import { useSiteNames } from '@/lib/site-names'
import { useReadOnly } from '@/lib/trial'
import { useUrlState } from '@/lib/url-state'
import { usePageTitle } from '@/lib/page-title'
import { periodRange, type Period } from '@/lib/period'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { vendorUrl } from '@/lib/vendors'
import { deleteAccountApi, fetchAccountsApi, fetchFinanceSettingsApi, fetchTransactionsApi, reverseTransferApi } from '@/lib/api'
import { exportCsv } from '@/lib/export'
import { compact, fetchExpenses, mayManageMoney, mayMoveMoney } from '@/lib/expenses'
import { useAuth } from '@/lib/AuthContext'
import type { AccountForEdit } from '@/components/accounts/account-dialog'

// WEB-51 (Ilan, 5 Nov): Finance > Money, one page for what used to be Accounts, Petty cash, Transactions and the
// transfers. Accounts: the company's bank accounts, each site's petty cash and the rest, with what each holds; a row
// opens it, its menu transfers, tops up petty cash, records a petty cash voucher, renames or closes it. Transactions:
// every money movement, filtered by account, kind and period (dropdowns, in the address); a transfer can be undone.
// The old pages filled gaps with made-up text ("Site Supervisor", "Project Site", "Direct Payee", two invented
// banks in the top-up dialog); this page shows only what the API returns.
// PRC-18 (7 Nov): four tiles -- in the bank, petty cash, owed back to staff, unpaid bills -- the last two open
// Expenses filtered; each account says what was spent from it in 30 days; a setup guide names what is missing (the
// bank account, each site's petty cash); transactions show money in, out and net, and export.

type View = 'accounts' | 'transactions'
type Kind = 'bank' | 'petty' | 'other'

interface Account {
  id: string
  name: string
  type: string
  kind: Kind
  balance: number
  opening: number
  currency: string
  custodian: string | null
  owner_user_id: string | null
  bank_name: string | null
  ifsc_code: string | null
  account_last4: string | null
  project_id?: string
  site_id?: string
  status: string
}

// A site's petty cash is "low" below the company's Finance settings line (low_float_threshold; ₹50,000 by default).
const rupees = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`
const KIND_LABEL: Record<Kind, string> = { bank: 'Bank accounts', petty: 'Petty cash at sites', other: 'Other accounts' }
const TX_LABEL: Record<string, string> = {
  expense_payment: 'Expense paid',
  transfer: 'Transfer',
  fund_received: 'Money in',
  reversal: 'Reversed',
}
const dayLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

function kindOf(type: string): Kind {
  if (type === 'bank' || type === 'bank_account') return 'bank'
  if (type === 'cash' || type === 'petty_cash' || type === 'employee_advance') return 'petty'
  return 'other'
}

export default function MoneyPage() {
  usePageTitle('Money')
  const { scope } = useScope()
  const siteNames = useSiteNames()
  const readOnly = useReadOnly()
  const { me } = useAuth()
  // SEC-03 (7 Nov): accounts and undo for the owner, admins and finance; transfers and top-ups also project managers.
  const canManage = mayManageMoney(me?.role) && !readOnly
  const canMove = mayMoveMoney(me?.role) && !readOnly
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [view, setView] = useUrlState<View>('view', 'accounts')
  const [account, setAccount] = useUrlState<string>('account', 'all')
  const [kind, setKind] = useUrlState<string>('kind', 'all')
  const [period, setPeriod] = useUrlState<Period>('period', '30d')
  const [from, setFrom] = useUrlState<string>('from', '')
  const [to, setTo] = useUrlState<string>('to', '')
  const [dialog, setDialog] = React.useState<'transfer' | 'topup' | 'voucher' | null>(null)
  const [opened, setOpened] = React.useState<Account | null>(null)
  const [editing, setEditing] = React.useState<Account | null | undefined>(undefined) // null: a new account
  const [preset, setPreset] = React.useState<{ type: 'bank' | 'cash'; site_id?: string; name?: string } | null>(null)
  const [closing, setClosing] = React.useState<Account | null>(null)
  const [undoing, setUndoing] = React.useState<any | null>(null)

  const scoped = {
    project_id: scope.mode !== 'portfolio' ? scope.projectId : undefined,
    site_id: scope.mode === 'site' ? scope.siteId : undefined,
  }
  const accounts = useQuery({
    queryKey: ['finance', 'accounts', scoped],
    queryFn: async (): Promise<Account[]> =>
      ((await fetchAccountsApi(scoped)) as any[]).map((a) => ({
        id: String(a.id),
        name: a.name,
        type: a.account_type,
        kind: kindOf(a.account_type),
        balance: Number(a.current_balance) || 0,
        opening: Number(a.opening_balance) || 0,
        currency: a.currency || 'INR',
        custodian: a.custodian_name ?? null,
        owner_user_id: a.owner_user_id ? String(a.owner_user_id) : null,
        bank_name: a.bank_name ?? null,
        ifsc_code: a.ifsc_code ?? null,
        account_last4: a.account_last4 ?? null,
        project_id: a.project_id ? String(a.project_id) : undefined,
        site_id: a.site_id ? String(a.site_id) : undefined,
        status: a.status,
      })),
  })
  const { from: rangeFrom, to: rangeTo } = periodRange(period, from, to)
  const txFilters = {
    account_id: account !== 'all' ? account : undefined,
    transaction_type: kind !== 'all' ? kind : undefined,
    start_date: rangeFrom,
    end_date: rangeTo,
    limit: 500,
  }
  const transactions = useQuery({
    queryKey: ['finance', 'transactions', txFilters],
    queryFn: () => fetchTransactionsApi(txFilters),
    enabled: view === 'transactions',
  })
  const settings = useQuery({ queryKey: ['finance', 'settings'], queryFn: fetchFinanceSettingsApi, staleTime: 60_000 })
  // Every expense in scope (no dates): what is still owed back to staff or unpaid, and each account's last 30 days.
  const expenses = useQuery({ queryKey: ['finance', 'expenses', { ...scoped, all: true }], queryFn: () => fetchExpenses(scoped), retry: false })
  const since = periodRange('30d', '', '').from ?? ''
  const spent30 = React.useMemo(() => {
    const m = new Map<string, number>()
    for (const e of expenses.data ?? []) if (e.account_id && e.date >= since) m.set(e.account_id, (m.get(e.account_id) ?? 0) + e.amount)
    return m
  }, [expenses.data, since])
  const owed = (expenses.data ?? []).filter((e) => e.paid_via === 'own_pocket')
  const unpaidBills = (expenses.data ?? []).filter((e) => e.paid_via === 'unpaid')
  const addAccount = (p: typeof preset) => {
    setPreset(p)
    setEditing(null)
  }
  const LOW_PETTY = Number((settings.data as any)?.low_float_threshold ?? 50000)
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['finance'] })
  const close = useMutation({
    mutationFn: (a: Account) => deleteAccountApi(a.id),
    onSuccess: () => {
      setClosing(null)
      refresh()
    },
  })
  const undo = useMutation({
    mutationFn: (tx: any) => reverseTransferApi(String(tx.id)),
    onSuccess: () => {
      setUndoing(null)
      refresh()
    },
  })

  const all = accounts.data ?? []
  const active = all.filter((a) => a.status !== 'inactive')
  const petty = active.filter((a) => a.kind === 'petty')
  const banks = active.filter((a) => a.kind === 'bank')
  const where = (a: Account) => {
    const site = a.site_id ? siteNames.get(a.site_id) : undefined
    return site ? `${site.name}${site.project ? ` · ${site.project}` : ''}` : null
  }
  const pettyBoxes = petty.map((a) => ({
    id: a.id,
    name: a.name,
    current_balance: a.balance,
    opening_balance: a.opening,
    custodian_name: a.custodian ?? '',
    project_name: a.site_id ? siteNames.get(a.site_id)?.project ?? '' : '',
    project_id: a.project_id,
    site_id: a.site_id,
    site_name: a.site_id ? siteNames.get(a.site_id)?.name : undefined,
  }))
  const sheetAccount = (a: Account) => ({
    id: a.id,
    name: a.name,
    account_type: a.type,
    current_balance: a.balance,
    currency: a.currency,
    holder: a.custodian,
    where: where(a),
    bank_name: a.bank_name,
    ifsc_code: a.ifsc_code,
    account_last4: a.account_last4,
    status: a.status,
  })
  // WEB-66: a bank account's row says which bank and which number; every row says who holds it.
  const bankLine = (a: Account) =>
    a.kind === 'bank' ? [a.bank_name, a.account_last4 ? `•••• ${a.account_last4}` : null].filter(Boolean).join(' ') || null : null

  const header = (
    <header className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <span className="inline-flex size-10 items-center justify-center rounded-xl bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
          <PiggyBank className="size-5" />
        </span>
        <div>
          <div className="text-xs text-muted-foreground">Finance</div>
          <h1 className="text-2xl leading-tight font-semibold tracking-tight">Money</h1>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <BooksLink to="/accounts/ledgers?kind=money" label="Bank & cash books" className="hidden sm:inline-flex" />
      {canMove && (
        <div className="flex items-center gap-2">
          <Button variant="outline" className="gap-2" disabled={active.length < 2} onClick={() => setDialog('transfer')}>
            <ArrowLeftRight className="size-4" /> <span className="hidden sm:inline">Transfer</span>
          </Button>
          {canManage && (
            <Button className="gap-2 font-semibold" onClick={() => addAccount(null)}>
              <Plus className="size-4" /> <span className="hidden sm:inline">Add account</span>
            </Button>
          )}
        </div>
      )}
      </div>
    </header>
  )
  const switcher = (
    <Segmented<View>
      label="View"
      value={view}
      onChange={setView}
      options={[
        { value: 'accounts', label: 'Accounts' },
        { value: 'transactions', label: 'Transactions' },
      ]}
    />
  )

  const accountRows = (list: Account[]) => (
    <ul className="divide-y rounded-lg border">
      {list.map((a) => {
        const low = a.kind === 'petty' && a.balance < LOW_PETTY
        return (
          <li key={a.id} className={cn('relative flex items-start gap-3 px-3 py-2 hover:bg-muted/30', a.status === 'inactive' && 'opacity-60')}>
            <button type="button" className="flex min-w-0 flex-1 flex-col gap-0.5 text-left after:absolute after:inset-0" onClick={() => setOpened(a)}>
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{a.name}</span>
                {low && <span className={cn(CHIP, 'bg-draft-soft text-draft')}>Low</span>}
                {a.status === 'inactive' && <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Closed</span>}
              </span>
              {(bankLine(a) || a.custodian || where(a) || spent30.get(a.id)) && (
                <span className="text-xs text-muted-foreground">
                  {[bankLine(a), a.custodian, where(a), spent30.get(a.id) ? `${rupees(spent30.get(a.id)!)} spent in 30 days` : null].filter(Boolean).join(' · ')}
                </span>
              )}
            </button>
            <span className="flex shrink-0 items-center gap-1">
              <span className={cn('font-semibold tabular-nums', a.balance < 0 && 'text-destructive')}>{rupees(a.balance)}</span>
              {!readOnly && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button type="button" variant="ghost" size="icon" className="relative z-10 size-8" aria-label={`More for ${a.name}`}>
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-52">
                    <DropdownMenuItem onClick={() => setOpened(a)}>Open</DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => {
                        setAccount(a.id)
                        setView('transactions')
                      }}
                    >
                      Its transactions
                    </DropdownMenuItem>
                    {a.kind === 'petty' && canMove && <DropdownMenuItem onClick={() => setDialog('topup')}>Top up</DropdownMenuItem>}
                    {a.kind === 'petty' && <DropdownMenuItem onClick={() => setDialog('voucher')}>Record a voucher</DropdownMenuItem>}
                    {canManage && (
                      <>
                        <DropdownMenuItem onClick={() => setEditing(a)}>Edit</DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setClosing(a)}>
                          Close account
                        </DropdownMenuItem>
                      </>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </span>
          </li>
        )
      })}
    </ul>
  )

  const txRows = React.useMemo(() => (transactions.data ?? []) as any[], [transactions.data])
  const txDays = React.useMemo(() => {
    const out: { date: string; rows: any[] }[] = []
    for (const tx of [...txRows].sort((a, b) => String(b.occurred_date).localeCompare(String(a.occurred_date)))) {
      const last = out[out.length - 1]
      if (last?.date === tx.occurred_date) last.rows.push(tx)
      else out.push({ date: tx.occurred_date, rows: [tx] })
    }
    return out
  }, [txRows])

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      {header}

      {view === 'accounts' ? (
        <>
          <div className="flex flex-wrap items-center gap-2">{switcher}</div>
          {accounts.isError ? (
            <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => accounts.refetch()}>Try again</Button>}>
              The accounts could not be loaded.
            </Callout>
          ) : accounts.isLoading ? (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-12 rounded-lg" />
              ))}
            </div>
          ) : all.length === 0 ? (
            <>
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <Landmark className="size-6 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm font-medium">No accounts yet</p>
              <p className="max-w-sm text-sm text-muted-foreground">Add the company's bank account and each site's petty cash to see what is spent from where.</p>
              {canManage && (
                <Button size="sm" onClick={() => addAccount(null)}>
                  Add account
                </Button>
              )}
            </div>
            <SetupGuide
              hasBank={false}
              sitesWithoutCash={[...siteNames.entries()]
                .filter(([id, st]) => (scope.mode === 'portfolio' || st.projectId === scope.projectId) && (scope.mode !== 'site' || id === scope.siteId))
                .map(([id, st]) => ({ id, name: st.name, project: st.project }))}
              readOnly={!canManage}
              onAdd={addAccount}
            />
            </>
          ) : (
            <>
              <MoneyTiles
                tiles={[
                  { label: 'In the bank', value: compact(banks.reduce((n, a) => n + a.balance, 0)), hint: `${banks.length} ${banks.length === 1 ? 'account' : 'accounts'}`, icon: Landmark, tone: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100' },
                  {
                    label: 'Petty cash',
                    value: compact(petty.reduce((n, a) => n + a.balance, 0)),
                    hint: petty.some((a) => a.balance < LOW_PETTY) ? `${petty.filter((a) => a.balance < LOW_PETTY).length} running low` : `${petty.length} at sites`,
                    warn: petty.some((a) => a.balance < LOW_PETTY),
                    icon: Wallet,
                    tone: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100',
                  },
                  {
                    label: 'Owed back to staff',
                    value: compact(owed.reduce((n, e) => n + e.amount, 0)),
                    hint: owed.length ? `${owed.length} paid from their pocket` : 'Nothing owed',
                    icon: HandCoins,
                    tone: 'bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-100',
                    to: owed.length ? '/finance/expenses?paid=own_pocket&period=all' : undefined,
                  },
                  {
                    label: 'Unpaid bills',
                    value: compact(unpaidBills.reduce((n, e) => n + e.amount, 0)),
                    hint: unpaidBills.length ? `${unpaidBills.length} not paid yet` : 'All paid',
                    warn: unpaidBills.length > 0,
                    icon: TriangleAlert,
                    tone: 'bg-orange-200 text-orange-950 dark:bg-orange-900 dark:text-orange-100',
                    to: unpaidBills.length ? '/finance/expenses?paid=unpaid&period=all' : undefined,
                  },
                ]}
                onOpen={(to) => navigate(to)}
              />
              <SetupGuide
                hasBank={banks.length > 0}
                sitesWithoutCash={[...siteNames.entries()]
                  .filter(([id, st]) => (scope.mode === 'portfolio' || st.projectId === scope.projectId) && (scope.mode !== 'site' || id === scope.siteId) && !petty.some((a) => a.site_id === id))
                  .map(([id, st]) => ({ id, name: st.name, project: st.project }))}
                readOnly={!canManage}
                onAdd={addAccount}
              />
              {(['bank', 'petty', 'other'] as Kind[]).map((k) => {
                const list = all.filter((a) => a.kind === k)
                if (list.length === 0) return null
                return (
                  <section key={k} className="flex flex-col gap-1.5">
                    <h3 className="flex items-center justify-between text-sm font-semibold">
                      <span>
                        {KIND_LABEL[k]} <span className="font-normal text-muted-foreground">{list.length}</span>
                      </span>
                      {k === 'petty' && canMove && (
                        <span className="flex gap-1">
                          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setDialog('topup')}>
                            Top up
                          </Button>
                          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setDialog('voucher')}>
                            Record a voucher
                          </Button>
                        </span>
                      )}
                    </h3>
                    {accountRows(list)}
                  </section>
                )
              })}
            </>
          )}
        </>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {switcher}
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <FilterSelect
                label="Account"
                value={account}
                onChange={setAccount}
                icon={Landmark}
                className="w-[170px]"
                options={[{ value: 'all', label: 'All accounts' }, ...all.map((a) => ({ value: a.id, label: a.name }))]}
              />
              <FilterSelect
                label="Kind"
                value={kind}
                onChange={setKind}
                icon={Filter}
                className="w-[150px]"
                options={[{ value: 'all', label: 'Every kind' }, ...Object.entries(TX_LABEL).map(([value, label]) => ({ value, label }))]}
              />
              <PeriodSelect value={period} onChange={setPeriod} from={from} to={to} onFrom={setFrom} onTo={setTo} />
            </div>
          </div>
          {transactions.isError ? (
            <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => transactions.refetch()}>Try again</Button>}>
              The transactions could not be loaded.
            </Callout>
          ) : transactions.isLoading ? (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 rounded-lg" />
              ))}
            </div>
          ) : txRows.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-10 text-center">
              <ArrowLeftRight className="size-6 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm text-muted-foreground">No money moved in this period{account !== 'all' || kind !== 'all' ? ' for these filters' : ''}.</p>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <TxSummary rows={txRows} account={account !== 'all' ? account : null} onExport={() => exportTx(txRows, account !== 'all' ? account : null)} />
              {txDays.map((day) => (
                <section key={day.date} className="flex flex-col gap-1">
                  <h3 className="text-xs font-semibold text-muted-foreground">{dayLabel(day.date)}</h3>
                  <ul className="divide-y rounded-lg border">
                    {day.rows.map((tx) => {
                      const into = account !== 'all' && String(tx.to_account_id) === account
                      const outOf = account !== 'all' && String(tx.from_account_id) === account
                      return (
                        <li key={tx.id} className="relative flex items-start gap-3 px-3 py-2 hover:bg-muted/30">
                          <button
                            type="button"
                            className="flex min-w-0 flex-1 flex-col gap-0.5 text-left after:absolute after:inset-0 disabled:cursor-default"
                            disabled={tx.transaction_type !== 'expense_payment' || !(tx.expense_id || tx.vendor_id)}
                            onClick={() => navigate(tx.expense_id ? `/finance/expenses/${tx.expense_id}` : vendorUrl(tx.vendor_id!, 'payments'))}
                          >
                            <span className="flex flex-wrap items-center gap-2">
                              <span className="font-medium">
                                {tx.transaction_type === 'expense_payment' && tx.vendor_name ? `Paid to ${tx.vendor_name}` : TX_LABEL[tx.transaction_type] ?? tx.transaction_type}
                              </span>
                              {tx.description && <span className="line-clamp-1 text-xs text-muted-foreground">{tx.description}</span>}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {[tx.from_account_name, tx.to_account_name].filter(Boolean).join(' → ') || '—'}
                            </span>
                          </button>
                          <span className="flex shrink-0 items-center gap-1">
                            <span className={cn('font-semibold tabular-nums', into && 'text-success', outOf && 'text-destructive')}>
                              {into ? '+' : outOf ? '−' : ''}
                              {rupees(Number(tx.amount) || 0)}
                            </span>
                            {tx.transaction_type === 'transfer' && canManage && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="relative z-10 size-8 text-muted-foreground"
                                title="Undo this transfer"
                                aria-label="Undo this transfer"
                                onClick={() => setUndoing(tx)}
                              >
                                <Undo2 className="size-4" />
                              </Button>
                            )}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </>
      )}

      <AccountDialog
        open={editing !== undefined}
        onOpenChange={(o) => !o && setEditing(undefined)}
        scope={scope}
        account={editing ? ({ id: editing.id, name: editing.name, type: editing.type, owner_user_id: editing.owner_user_id, bank_name: editing.bank_name, ifsc_code: editing.ifsc_code, account_last4: editing.account_last4 } satisfies AccountForEdit) : null}
        preset={editing === null ? preset : null}
        onSaved={refresh}
      />
      <TransferMoneyDialog
        open={dialog === 'transfer'}
        onOpenChange={(o) => setDialog(o ? 'transfer' : null)}
        accounts={active.map((a) => ({ id: a.id, name: a.name, current_balance: a.balance, currency: a.currency }))}
        onTransferCompleted={refresh}
      />
      <ReplenishFloatDialog
        open={dialog === 'topup'}
        onOpenChange={(o) => setDialog(o ? 'topup' : null)}
        cashBoxes={pettyBoxes}
        bankAccounts={banks.map((a) => ({ id: a.id, name: a.name, current_balance: a.balance }))}
        onReplenishCompleted={refresh}
      />
      <RecordVoucherDialog open={dialog === 'voucher'} onOpenChange={(o) => setDialog(o ? 'voucher' : null)} cashBoxes={pettyBoxes} onVoucherCreated={refresh} />
      {opened?.kind === 'petty' ? (
        <CashBoxDetailSheet
          cashBox={pettyBoxes.find((b) => b.id === opened.id) ?? null}
          open
          onOpenChange={(o) => !o && setOpened(null)}
          onReplenishClick={() => setDialog('topup')}
        />
      ) : (
        <AccountDetailSheet
          account={opened ? sheetAccount(opened) : null}
          open={opened !== null}
          onOpenChange={(o) => !o && setOpened(null)}
          onEdit={
            !canManage
              ? undefined
              : () => {
                  setEditing(opened)
                  setOpened(null)
                }
          }
        />
      )}

      <Dialog open={closing !== null} onOpenChange={(o) => !o && setClosing(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Close {closing?.name}?</DialogTitle>
            <DialogDescription>
              It holds {closing ? rupees(closing.balance) : ''}. A closed account is no longer offered for payments and transfers; its
              history stays. Move what it holds to another account first.
            </DialogDescription>
          </DialogHeader>
          {close.isError && <p className="text-sm text-destructive">{(close.error as any)?.response?.data?.detail || 'It could not be closed.'}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setClosing(null)}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={close.isPending} onClick={() => closing && close.mutate(closing)}>
              {close.isPending ? 'Closing…' : 'Close account'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={undoing !== null} onOpenChange={(o) => !o && setUndoing(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Undo this transfer?</DialogTitle>
            <DialogDescription>
              {undoing && `${rupees(Number(undoing.amount) || 0)} from ${undoing.from_account_name ?? 'an account'} to ${undoing.to_account_name ?? 'an account'}. `}
              The money goes back, and both entries stay in the list.
            </DialogDescription>
          </DialogHeader>
          {undo.isError && <p className="text-sm text-destructive">{(undo.error as any)?.response?.data?.detail || 'It could not be undone.'}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setUndoing(null)}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={undo.isPending} onClick={() => undoing && undo.mutate(undoing)}>
              {undo.isPending ? 'Undoing…' : 'Undo transfer'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/* eslint-disable @typescript-eslint/no-explicit-any */
function exportTx(rows: any[], account: string | null): void {
  exportCsv(
    `money-transactions-${new Date().toISOString().slice(0, 10)}.csv`,
    ['Date', 'Kind', 'From', 'To', 'Description', 'Amount', ...(account ? ['In / out'] : [])],
    rows.map((tx) => [
      tx.occurred_date, TX_LABEL[tx.transaction_type] ?? tx.transaction_type, tx.from_account_name ?? '', tx.to_account_name ?? '', tx.description ?? '', Number(tx.amount) || 0,
      ...(account ? [String(tx.to_account_id) === account ? 'in' : String(tx.from_account_id) === account ? 'out' : ''] : []),
    ]),
  )
}

/** Money in, out and net for the account chosen; otherwise how much moved, by kind. */
function TxSummary({ rows, account, onExport }: { rows: any[]; account: string | null; onExport: () => void }) {
  const amount = (tx: any) => Number(tx.amount) || 0
  const inn = account ? rows.filter((tx) => String(tx.to_account_id) === account).reduce((n, tx) => n + amount(tx), 0) : 0
  const out = account ? rows.filter((tx) => String(tx.from_account_id) === account).reduce((n, tx) => n + amount(tx), 0) : 0
  const kinds = new Map<string, number>()
  for (const tx of rows) kinds.set(tx.transaction_type, (kinds.get(tx.transaction_type) ?? 0) + amount(tx))
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border bg-card px-4 py-3 text-sm">
      {account ? (
        <>
          <span>
            In <strong className="tabular-nums text-success">+{rupees(inn)}</strong>
          </span>
          <span>
            Out <strong className="tabular-nums text-destructive">−{rupees(out)}</strong>
          </span>
          <span>
            Net <strong className={cn('tabular-nums', inn - out < 0 && 'text-destructive')}>{inn - out < 0 ? '−' : '+'}{rupees(Math.abs(inn - out))}</strong>
          </span>
        </>
      ) : (
        [...kinds.entries()].map(([k, v]) => (
          <span key={k}>
            {TX_LABEL[k] ?? k} <strong className="tabular-nums">{rupees(v)}</strong>
          </span>
        ))
      )}
      <span className="text-muted-foreground">
        {rows.length} {rows.length === 1 ? 'entry' : 'entries'}
      </span>
      <Button size="sm" variant="outline" className="ml-auto gap-1.5" onClick={onExport}>
        <Download className="size-3.5" /> Export
      </Button>
    </div>
  )
}
/* eslint-enable @typescript-eslint/no-explicit-any */

function MoneyTiles({
  tiles,
  onOpen,
}: {
  tiles: { label: string; value: string; hint: string; icon: LucideIcon; tone: string; warn?: boolean; to?: string }[]
  onOpen: (to: string) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
      {tiles.map((t) => {
        const body = (
          <>
            <span className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', t.tone)}>
              <t.icon className="size-4 sm:size-5" />
            </span>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-lg leading-none font-semibold tabular-nums sm:text-2xl">{t.value}</span>
              <span className="truncate text-xs text-foreground/80 sm:text-sm">{t.label}</span>
              <span className={cn('truncate text-[11px] text-muted-foreground', t.warn && 'font-semibold text-draft')}>{t.hint}</span>
            </span>
            {t.to && <ChevronRight className="size-4 shrink-0 text-muted-foreground" />}
          </>
        )
        return t.to ? (
          <button key={t.label} type="button" onClick={() => onOpen(t.to!)} className="flex items-center gap-3 rounded-xl border bg-card p-3 text-left transition hover:-translate-y-px sm:p-3.5">
            {body}
          </button>
        ) : (
          <div key={t.label} className="flex items-center gap-3 rounded-xl border bg-card p-3 sm:p-3.5">
            {body}
          </div>
        )
      })}
    </div>
  )
}

/** What is missing for "spent from where" to work: the company's bank account and each site's petty cash. */
function SetupGuide({
  hasBank,
  sitesWithoutCash,
  readOnly,
  onAdd,
}: {
  hasBank: boolean
  sitesWithoutCash: { id: string; name: string; project: string }[]
  readOnly: boolean
  onAdd: (preset: { type: 'bank' | 'cash'; site_id?: string; name?: string }) => void
}) {
  if (readOnly || (hasBank && sitesWithoutCash.length === 0)) return null
  const shown = sitesWithoutCash.slice(0, 4)
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-sky-200 bg-sky-50/60 p-4 dark:border-sky-900 dark:bg-sky-950/30">
      <div>
        <h3 className="text-sm font-semibold">Set up where money is kept</h3>
        <p className="text-sm text-muted-foreground">
          Then every expense says whether it came from the bank or a site's petty cash, and the totals split both ways.
        </p>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2">
        <li className="flex items-center gap-3 rounded-lg border bg-background px-3 py-2">
          {hasBank ? <CheckCircle2 className="size-5 shrink-0 text-success" /> : <Landmark className="size-5 shrink-0 text-sky-700 dark:text-sky-300" />}
          <span className="min-w-0 flex-1 text-sm font-medium">{hasBank ? 'Bank account added' : "The company's bank account"}</span>
          {!hasBank && (
            <Button size="sm" variant="outline" onClick={() => onAdd({ type: 'bank' })}>
              Add
            </Button>
          )}
        </li>
        {shown.map((site) => (
          <li key={site.id} className="flex items-center gap-3 rounded-lg border bg-background px-3 py-2">
            <Wallet className="size-5 shrink-0 text-amber-700 dark:text-amber-300" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-sm font-medium">Petty cash at {site.name}</span>
              <span className="truncate text-xs text-muted-foreground">{site.project}</span>
            </span>
            <Button size="sm" variant="outline" onClick={() => onAdd({ type: 'cash', site_id: site.id, name: `${site.name} petty cash` })}>
              Add
            </Button>
          </li>
        ))}
      </ul>
      {sitesWithoutCash.length > shown.length && (
        <p className="text-xs text-muted-foreground">{sitesWithoutCash.length - shown.length} more sites have no petty cash account yet.</p>
      )}
    </section>
  )
}
