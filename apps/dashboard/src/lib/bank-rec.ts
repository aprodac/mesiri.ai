import { api } from './api'

// ACC-13 / FB-03: bank reconciliation. Backend: domains/accounts/bankrec.py (GET /accounts/bank-rec/{account}).
// Amounts are exact strings, + money in, − money out (the bank account's side).

export type LineStatus = 'unmatched' | 'matched' | 'ignored'

export interface BookEntry {
  entry_id: string
  ref: string
  date: string
  words: string | null
  amount: string
}

export interface StatementLine {
  id: string
  date: string
  description: string
  reference: string | null
  amount: string
  balance: string | null
  status: LineStatus
  matched_how: 'auto' | 'manual' | 'booked' | null
  note: string | null
  decided_by: string | null
  entry: BookEntry | null
  /** Was matched, but the record behind the voucher is gone. */
  stale?: boolean
}

export interface BankRec {
  account: { id: string; name: string; account_type: string }
  date_from: string
  date_to: string
  lines: StatementLine[]
  books_unmatched: BookEntry[]
  counts: Record<LineStatus, number>
  statement_balance: string | null
  book_balance: string | null
  as_of: string
  in_unmatched: string
  out_unmatched: string
  imports: { id: string; file_name: string | null; from_date: string; to_date: string; lines_added: number; lines_repeated: number; created_at: string; by: string | null }[]
}

export async function fetchBankRec(accountId: string, period?: { date_from?: string; date_to?: string }): Promise<BankRec> {
  return (await api.get<BankRec>(`/accounts/bank-rec/${accountId}`, { params: period })).data
}

export async function importStatement(accountId: string, fileName: string, content: string) {
  return (await api.post<{ added: number; repeated: number; matched: number; skipped: { row: number; why: string }[]; from: string; to: string }>(
    `/accounts/bank-rec/${accountId}/import`, { file_name: fileName, content })).data
}

export async function autoMatch(accountId: string): Promise<{ matched: number }> {
  return (await api.post(`/accounts/bank-rec/${accountId}/auto-match`)).data
}

export async function matchLine(lineId: string, entryId: string) {
  await api.post(`/accounts/bank-rec/lines/${lineId}/match`, { entry_id: entryId })
}

export async function bookLine(lineId: string) {
  await api.post(`/accounts/bank-rec/lines/${lineId}/book`, {})
}

export async function ignoreLine(lineId: string, note: string) {
  await api.post(`/accounts/bank-rec/lines/${lineId}/ignore`, { note })
}

export async function reopenLine(lineId: string) {
  await api.post(`/accounts/bank-rec/lines/${lineId}/reopen`)
}
