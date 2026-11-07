import * as React from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { AppScope } from '@/lib/scope-types'
import { apiErrorMessage } from '@/lib/logo-upload'
import { createAccountApi, fetchUsers, updateAccountApi } from '@/lib/api'
import { useSiteNames } from '@/lib/site-names'

// WEB-66 (Ilan, 5 Nov: "what about bank accounts page", "bank account connecting it to a user"): one dialog adds or
// edits a money account: its name, kind, who holds it (a person in the team) and, for a bank account, the bank, IFSC
// and the last 4 digits of the number (the full number is never kept). Replaces the add dialog that dropped the bank
// details and a rename-only dialog.

export interface AccountForEdit {
  id: string
  name: string
  type: string
  owner_user_id?: string | null
  bank_name?: string | null
  ifsc_code?: string | null
  account_last4?: string | null
}

type Kind = 'bank' | 'cash' | 'employee_advance' | 'other'
const KINDS: { value: Kind; label: string }[] = [
  { value: 'bank', label: 'Bank account' },
  { value: 'cash', label: 'Petty cash at a site' },
  { value: 'employee_advance', label: "A person's cash advance" },
  { value: 'other', label: 'Other' },
]
const NOBODY = 'nobody'

interface AccountDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  scope: AppScope
  /** The account to edit; null to add one. */
  account: AccountForEdit | null
  /** A new account's kind, site and name to start from (the Money page's setup guide: "Add petty cash for Block A"). */
  preset?: { type: Kind; site_id?: string; name?: string } | null
  onSaved: () => void
}

export function AccountDialog({ open, onOpenChange, scope, account, preset, onSaved }: AccountDialogProps) {
  const editing = account !== null
  const [name, setName] = React.useState('')
  const [kind, setKind] = React.useState<Kind>('bank')
  const [opening, setOpening] = React.useState('')
  const [holder, setHolder] = React.useState(NOBODY)
  const [bank, setBank] = React.useState('')
  const [ifsc, setIfsc] = React.useState('')
  const [last4, setLast4] = React.useState('')
  // PRC-18 (7 Nov): a site's petty cash says which site. It was linked only when the page was in one site's view, so
  // one added from the company view belonged to no site.
  const [siteId, setSiteId] = React.useState('')
  const siteNames = useSiteNames()
  const sites = [...siteNames.entries()]
    .filter(([, s]) => scope.mode === 'portfolio' || s.projectId === scope.projectId)
    .sort((a, b) => `${a[1].project} ${a[1].name}`.localeCompare(`${b[1].project} ${b[1].name}`))
  const users = useQuery({ queryKey: ['users'], queryFn: fetchUsers, enabled: open })
  const team = (users.data ?? []).filter((u) => u.status === 'active' || u.id === account?.owner_user_id)

  React.useEffect(() => {
    if (!open) return
    setName(account?.name ?? preset?.name ?? '')
    setKind((['bank', 'cash', 'employee_advance', 'other'].includes(account?.type ?? '') ? account?.type : preset?.type ?? 'bank') as Kind)
    setSiteId(preset?.site_id ?? (scope.mode === 'site' ? scope.siteId : ''))
    setOpening('')
    setHolder(account?.owner_user_id ?? NOBODY)
    setBank(account?.bank_name ?? '')
    setIfsc(account?.ifsc_code ?? '')
    setLast4(account?.account_last4 ?? '')
  }, [open, account, preset]) // eslint-disable-line react-hooks/exhaustive-deps

  const isBank = kind === 'bank'
  const save = useMutation({
    mutationFn: async () => {
      const details = {
        owner_user_id: holder === NOBODY ? null : holder,
        bank_name: isBank ? bank : '',
        ifsc_code: isBank ? ifsc : '',
        account_last4: isBank ? last4 : '',
      }
      if (editing) return updateAccountApi(account!.id, { name: name.trim(), ...details })
      return createAccountApi({
        name: name.trim(),
        account_type: kind,
        currency: 'INR',
        opening_balance: Number(opening) || 0,
        project_id: kind === 'cash' && siteId ? siteNames.get(siteId)?.projectId : scope.mode !== 'portfolio' ? scope.projectId : undefined,
        site_id: kind === 'cash' && siteId ? siteId : scope.mode === 'site' ? scope.siteId : undefined,
        ...details,
        owner_user_id: details.owner_user_id ?? undefined,
      })
    },
    onSuccess: () => {
      onSaved()
      onOpenChange(false)
    },
  })
  React.useEffect(() => save.reset(), [open]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">{editing ? `Edit ${account!.name}` : 'Add an account'}</DialogTitle>
        </DialogHeader>
        <form
          id="account-form"
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) save.mutate()
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="acc-name">Name</Label>
            <Input id="acc-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="HDFC current account" required />
          </div>
          {!editing && (
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-1.5">
                <Label>Kind</Label>
                <Select value={kind} onValueChange={(v) => setKind(v as Kind)}>
                  <SelectTrigger className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {KINDS.map((k) => (
                      <SelectItem key={k.value} value={k.value}>
                        {k.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="acc-opening">Money in it now (₹)</Label>
                <Input id="acc-opening" type="number" min={0} step="any" inputMode="decimal" value={opening} onChange={(e) => setOpening(e.target.value)} placeholder="0" />
              </div>
            </div>
          )}
          {!editing && kind === 'cash' && (
            <div className="grid gap-1.5">
              <Label>Site</Label>
              <Select value={siteId} onValueChange={setSiteId}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Which site keeps this cash" />
                </SelectTrigger>
                <SelectContent>
                  {sites.map(([id, s]) => (
                    <SelectItem key={id} value={id}>
                      {s.project} › {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="grid gap-1.5">
            <Label>{isBank ? 'Who looks after it' : 'Who holds the cash'}</Label>
            <Select value={holder} onValueChange={setHolder}>
              <SelectTrigger className="h-9">
                <SelectValue placeholder="Nobody" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NOBODY}>Nobody</SelectItem>
                {team.map((u) => (
                  <SelectItem key={u.id} value={u.id}>
                    {u.full_name || u.email}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {isBank && (
            <>
              <div className="grid gap-1.5">
                <Label htmlFor="acc-bank">Bank</Label>
                <Input id="acc-bank" value={bank} onChange={(e) => setBank(e.target.value)} placeholder="HDFC Bank" maxLength={80} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-1.5">
                  <Label htmlFor="acc-ifsc">IFSC</Label>
                  <Input id="acc-ifsc" value={ifsc} onChange={(e) => setIfsc(e.target.value.toUpperCase())} placeholder="HDFC0001234" maxLength={11} autoCapitalize="characters" />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="acc-last4">Last 4 digits</Label>
                  <Input id="acc-last4" value={last4} onChange={(e) => setLast4(e.target.value.replace(/\D/g, '').slice(-4))} placeholder="7890" inputMode="numeric" />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">Only the last 4 digits are kept, to tell accounts apart.</p>
            </>
          )}
          {save.isError && <p className="text-sm text-destructive">{apiErrorMessage(save.error)}</p>}
        </form>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form="account-form" disabled={save.isPending || !name.trim() || (!editing && kind === 'cash' && sites.length > 0 && !siteId)}>
            {save.isPending ? 'Saving…' : editing ? 'Save' : 'Add account'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
