import { api } from './api'

// NXT-03: what clients owe and money received from them. Backend: domains/billing/router.py (receivables, receipts),
// rules in domains/billing/receivables.py. Owner, admin and finance only (D-N3).

export type Bucket = '0_30' | '31_60' | '61_90' | '90_plus'

export interface OpenBill {
  id: string
  ref: string
  project_id: string
  project: string | null
  bill_date: string
  due: string
  received: string
  left: string
  days: number
  bucket: Bucket | null
}

export interface ClientOwes {
  client_id: string | null
  client: string
  outstanding: string
  buckets: Record<Bucket, string>
  open_bills: OpenBill[]
  unapplied: string
  advance_received: string
  last_received_on: string | null
}

export interface Receivables {
  date: string
  outstanding: string
  buckets: Record<Bucket, string>
  clients: ClientOwes[]
}

export type ReceiptKind = 'bill' | 'on_account' | 'advance'

export interface ClientReceipt {
  id: string
  project_id: string
  project: string
  client: string | null
  bill_ref: string | null
  kind: ReceiptKind
  amount: string
  received_on: string
  account: string
  method: string | null
  reference: string | null
  status: 'confirmed' | 'cancelled'
  recorded_by: string | null
}

export interface ReceiptInput {
  kind: ReceiptKind
  ra_bill_id?: string
  project_id?: string
  amount: string
  received_on?: string
  account_id: string
  method?: string
  reference?: string
}

export const BUCKET_LABEL: Record<Bucket, string> = { '0_30': '0–30 days', '31_60': '31–60 days', '61_90': '61–90 days', '90_plus': 'Over 90 days' }

export async function fetchReceivables(): Promise<Receivables> {
  return (await api.get<Receivables>('/billing/receivables')).data
}

export async function fetchClientReceipts(): Promise<ClientReceipt[]> {
  return (await api.get<{ receipts: ClientReceipt[] }>('/billing/receipts')).data.receipts
}

export async function recordClientReceipt(body: ReceiptInput) {
  return (await api.post('/billing/receipts', body)).data
}

export async function cancelClientReceipt(id: string): Promise<ClientReceipt> {
  return (await api.post<ClientReceipt>(`/billing/receipts/${id}/cancel`)).data
}
