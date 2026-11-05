import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftRight, Banknote, Filter, Landmark, MoreHorizontal, Plus, TriangleAlert, Undo2, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Callout, PageHeader, Segmented, StatStrip } from '@/components/dpr-page'
import { FilterSelect, PeriodSelect } from '@/components/filter-select'
import { AccountDetailSheet } from '@/components/accounts/account-detail-sheet'
import { CreateAccountDialog } from '@/components/accounts/create-account-dialog'
import { RenameAccountDialog } from '@/components/accounts/rename-account-dialog'
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
import { deleteAccountApi, fetchAccountsApi, fetchFinanceSettingsApi, fetchTransactionsApi, reverseTransferApi } from '@/lib/api'

// WEB-51 (Ilan, 5 Nov): Finance > Money, one page for what used to be Accounts, Petty cash, Transactions and the
// transfers. Accounts: the company's bank accounts, each site's petty cash and the rest, with what each holds; a row
// opens it, its menu transfers, tops up petty cash, records a petty cash voucher, renames or closes it. Transactions:
// every money movement, filtered by account, kind and period (dropdowns, in the address); a transfer can be undone.
// The old pages filled gaps with made-up text ("Site Supervisor", "Project Site", "Direct Payee", two invented
// banks in the top-up dialog); this page shows only what the API returns.

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
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [view, setView] = useUrlState<View>('view', 'accounts')
  const [account, setAccount] = useUrlState<string>('account', 'all')
  const [kind, setKind] = useUrlState<string>('kind', 'all')
  const [period, setPeriod] = useUrlState<Period>('period', '30d')
  const [from, setFrom] = useUrlState<string>('from', '')
  const [to, setTo] = useUrlState<string>('to', '')
  const [dialog, setDialog] = React.useState<'create' | 'transfer' | 'topup' | 'voucher' | null>(null)
  const [opened, setOpened] = React.useState<Account | null>(null)
  const [renaming, setRenaming] = React.useState<Account | null>(null)
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
    opening_balance: a.opening,
    currency: a.currency,
    custodian_name: a.custodian ?? undefined,
    project_name: a.site_id ? siteNames.get(a.site_id)?.project : undefined,
    site_name: a.site_id ? siteNames.get(a.site_id)?.name : undefined,
    status: a.status,
  })

  const header = (
    <PageHeader
      title="Money"
      actions={
        !readOnly && (
          <>
            <Button size="sm" variant="outline" className="gap-1.5" disabled={active.length < 2} onClick={() => setDialog('transfer')}>
              <ArrowLeftRight className="size-4" /> <span className="hidden sm:inline">Transfer</span>
            </Button>
            <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setDialog('create')}>
              <Plus className="size-4" /> Add account
            </Button>
          </>
        )
      }
    />
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
              {(a.custodian || where(a)) && (
                <span className="text-xs text-muted-foreground">{[a.custodian, where(a)].filter(Boolean).join(' · ')}</span>
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
                    {a.kind === 'petty' && <DropdownMenuItem onClick={() => setDialog('topup')}>Top up</DropdownMenuItem>}
                    {a.kind === 'petty' && <DropdownMenuItem onClick={() => setDialog('voucher')}>Record a voucher</DropdownMenuItem>}
                    <DropdownMenuItem onClick={() => setRenaming(a)}>Rename</DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setClosing(a)}>
                      Close account
                    </DropdownMenuItem>
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
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <Landmark className="size-6 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm font-medium">No accounts yet</p>
              <p className="max-w-sm text-sm text-muted-foreground">Add the company's bank account and each site's petty cash to see what is spent from where.</p>
              {!readOnly && (
                <Button size="sm" onClick={() => setDialog('create')}>
                  Add account
                </Button>
              )}
            </div>
          ) : (
            <>
              <StatStrip
                stats={[
                  { label: 'In bank', value: rupees(banks.reduce((n, a) => n + a.balance, 0)), icon: Landmark },
                  {
                    label: 'Petty cash',
                    value: rupees(petty.reduce((n, a) => n + a.balance, 0)),
                    icon: Wallet,
                    tone: petty.some((a) => a.balance < LOW_PETTY) ? 'warn' : 'default',
                    hint: petty.some((a) => a.balance < LOW_PETTY) ? `${petty.filter((a) => a.balance < LOW_PETTY).length} low` : undefined,
                  },
                  { label: 'All accounts', value: rupees(active.reduce((n, a) => n + a.balance, 0)), icon: Banknote },
                ]}
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
                      {k === 'petty' && !readOnly && (
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
                            disabled={tx.transaction_type !== 'expense_payment' || !tx.source_id}
                            onClick={() => navigate(`/finance/expenses/${tx.source_id}`)}
                          >
                            <span className="flex flex-wrap items-center gap-2">
                              <span className="font-medium">{TX_LABEL[tx.transaction_type] ?? tx.transaction_type}</span>
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
                            {tx.transaction_type === 'transfer' && !readOnly && (
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

      <CreateAccountDialog open={dialog === 'create'} onOpenChange={(o) => setDialog(o ? 'create' : null)} scope={scope} onAccountCreated={refresh} />
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
      <RenameAccountDialog
        open={renaming !== null}
        onOpenChange={(o) => !o && setRenaming(null)}
        accountId={renaming?.id ?? null}
        currentName={renaming?.name ?? ''}
        onRenamed={() => {
          setRenaming(null)
          refresh()
        }}
      />
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
          onTransferClick={() => setDialog('transfer')}
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
