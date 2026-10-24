import { api } from './api'

// Typed boundary for the /materials domain — Material catalog, Inflows
// (receipts), Outflows (usage), aggregated Inventory, and the per-site,
// per-material movement Ledger. See backend/src/mesiri/domains/materials
// for the source of truth on shapes and authorization rules.

export interface MaterialCatalog {
  id: string
  organization_id: string
  name: string
  default_unit: string | null
  // The material's Stock Unit — every receipt/outflow for this material must
  // use this unit_id; no unit conversion, and it can't change once the
  // material has any recorded movement (see backend PATCH /materials/{id}).
  default_unit_id: string
  category: string | null
  sku: string | null
  is_active: boolean
}

export interface MaterialCatalogListResponse {
  items: MaterialCatalog[]
  total: number
}

export interface UnitOfMeasure {
  id: string
  code: string
  display_name: string
  is_active: boolean
}

export interface UnitsOfMeasureListResponse {
  items: UnitOfMeasure[]
}

export type InflowReason =
  | 'RECEIVED'
  | 'TRANSFER_IN'
  | 'RETURN_IN'
  | 'ADJUSTMENT_IN'
  // What was already on site when it started using Mesiri. Once per site and
  // material (the backend 409s a second one).
  | 'OPENING_STOCK'
export type OutflowReason = 'CONSUMED' | 'TRANSFER_OUT' | 'RETURN_TO_VENDOR' | 'WASTAGE' | 'ADJUSTMENT_OUT'

export interface MaterialReceipt {
  id: string
  organization_id: string
  project_id: string
  site_id: string | null
  material_name: string
  quantity: string
  unit: string
  unit_id: string
  unit_cost: string | null
  total_cost: string | null
  supplier: string | null
  // A correction was posted against this purchase — its cost must be left out
  // of spend totals, because that money was netted off.
  is_reversed?: boolean
  // Set when this purchase came from a supplier invoice — several purchases
  // can share one, and the original document hangs off it.
  invoice_id?: string | null
  occurred_date: string
  occurred_time: string | null
  correlation_id: string | null
  source: string
  occurred_date_source: string | null
  material_id: string | null
  movement_reason: InflowReason
  notes: string | null
  reverses_movement_id: string | null
  // Set on both halves of a transfer between sites: such a movement is
  // corrected through its transfer, never alone.
  transfer_id?: string | null
  // Only populated by the detail endpoints — a correction has already been
  // posted against this movement, so offering "Correct" again would 409.
  already_reversed?: boolean
  created_at: string
  created_by: string | null
  updated_at: string | null
  updated_by: string | null
}

export interface MaterialUsage {
  id: string
  organization_id: string
  project_id: string
  site_id: string | null
  material_name: string
  quantity: string
  unit: string
  unit_id: string
  work_item: string | null
  occurred_date: string
  occurred_time: string | null
  correlation_id: string | null
  source: string
  occurred_date_source: string | null
  material_id: string | null
  movement_reason: OutflowReason
  notes: string | null
  reverses_movement_id: string | null
  // Set on both halves of a transfer between sites: such a movement is
  // corrected through its transfer, never alone.
  transfer_id?: string | null
  // Only populated by the detail endpoints — a correction has already been
  // posted against this movement, so offering "Correct" again would 409.
  already_reversed?: boolean
  created_at: string
  created_by: string | null
  updated_at: string | null
  updated_by: string | null
}

// Client-side merged shape for "one movement" rendering (used by the
// details sheet caller and any UI that treats inflow/outflow uniformly).
export type MaterialMovement =
  | ({ direction: 'IN' } & MaterialReceipt)
  | ({ direction: 'OUT' } & MaterialUsage)

export interface MaterialMovementListResponse<T> {
  items: T[]
  total: number
}

export interface MovementFilters {
  project_id?: string
  site_id?: string
  material_id?: string
  material_name?: string
  movement_reason?: string
  source?: string
  recorded_by_user_id?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}

export type StockState = 'AVAILABLE' | 'OUT_OF_STOCK' | 'NEGATIVE_STOCK'

export interface MaterialStock {
  organization_id: string
  project_id: string
  site_id: string
  material_id: string
  material_name: string
  unit: string
  total_received: string
  total_used: string
  current_stock: string
  last_movement_at: string | null
  stock_state: StockState
}

export interface LedgerEntry {
  id: string
  direction: 'IN' | 'OUT'
  movement_reason: string
  quantity: string
  unit: string
  occurred_date: string
  occurred_time: string | null
  source: string
  notes: string | null
  context: string | null
  reverses_movement_id: string | null
  created_by: string | null
  created_at: string
  running_balance: string
}

export interface LedgerResponse {
  items: LedgerEntry[]
  total: number
  current_balance: string
  unit: string
}

// ---------------------------------------------------------------------
// Material catalog
// ---------------------------------------------------------------------

export interface MaterialCatalogFilters {
  search?: string
  is_active?: boolean
  limit?: number
  offset?: number
}

export async function fetchMaterials(
  filters: MaterialCatalogFilters = {}
): Promise<MaterialCatalogListResponse> {
  const res = await api.get<MaterialCatalogListResponse>('/materials', { params: filters })
  return res.data
}

export async function fetchMaterial(id: string): Promise<MaterialCatalog> {
  const res = await api.get<MaterialCatalog>(`/materials/${id}`)
  return res.data
}

export async function createMaterial(payload: {
  name: string
  default_unit_id: string
  category?: string
  sku?: string
}): Promise<MaterialCatalog> {
  const res = await api.post<MaterialCatalog>('/materials', payload)
  return res.data
}

export async function updateMaterial(
  id: string,
  payload: {
    name?: string
    default_unit_id?: string
    category?: string
    sku?: string
    is_active?: boolean
  }
): Promise<MaterialCatalog> {
  const res = await api.patch<MaterialCatalog>(`/materials/${id}`, payload)
  return res.data
}

export async function deleteMaterial(id: string): Promise<void> {
  await api.delete(`/materials/${id}`)
}

export async function setMaterialActive(id: string, isActive: boolean): Promise<MaterialCatalog> {
  return updateMaterial(id, { is_active: isActive })
}

export async function fetchUnitsOfMeasure(): Promise<UnitsOfMeasureListResponse> {
  const res = await api.get<UnitsOfMeasureListResponse>('/materials/units-of-measure')
  return res.data
}

// ---------------------------------------------------------------------
// Inflows (receipts)
// ---------------------------------------------------------------------

export async function fetchInflows(
  filters: MovementFilters = {}
): Promise<MaterialMovementListResponse<MaterialReceipt>> {
  const res = await api.get<MaterialMovementListResponse<MaterialReceipt>>('/materials/inflows', {
    params: filters,
  })
  return res.data
}

export async function fetchInflow(id: string): Promise<MaterialReceipt> {
  const res = await api.get<MaterialReceipt>(`/materials/inflows/${id}`)
  return res.data
}

export interface CreateInflowPayload {
  project_id: string
  site_id?: string
  material_id: string
  unit_id: string
  quantity: string | number
  movement_reason?: InflowReason
  supplier?: string
  notes?: string
  occurred_date: string
  // Both optional. Leave them out when the price genuinely wasn't recorded —
  // the backend stores NULL, never 0, so "not recorded" can never masquerade
  // as "free" in a spend total.
  unit_cost?: string | number
  total_cost?: string | number
}

// ---------------------------------------------------------------------
// Supplier invoices
// ---------------------------------------------------------------------

export interface MaterialInvoiceLine {
  id: string
  material_id: string
  material_name: string
  quantity: string
  unit: string
  unit_cost: string | null
  total_cost: string | null
}

export interface MaterialInvoice {
  id: string
  organization_id: string
  project_id: string
  site_id: string | null
  vendor_id: string | null
  vendor_name: string | null
  supplier_name: string | null
  invoice_number: string | null
  invoice_date: string | null
  // As printed on the document. Legitimately differs from the sum of the lines
  // because tax and freight are not extracted — never treat the gap as an error.
  invoice_total: string | null
  currency: string
  // The Finance expense this invoice created, if any.
  expense_id: string | null
  notes: string | null
  created_at: string
  lines: MaterialInvoiceLine[]
  has_attachment: boolean
  attachment_count: number
}

export async function fetchInvoice(id: string): Promise<MaterialInvoice> {
  const res = await api.get<MaterialInvoice>(`/materials/invoices/${id}`)
  return res.data
}

export interface InvoiceAttachment {
  url: string
  attachment_type: string
}

// Resolves the stored document to a short-lived link. Throws 404 when nothing
// was attached — callers should treat that as "no document", not an error.
export async function fetchInvoiceAttachment(id: string): Promise<InvoiceAttachment> {
  const res = await api.get<InvoiceAttachment>(`/materials/invoices/${id}/attachment`)
  return res.data
}

export interface CreateInvoicePayload {
  project_id: string
  site_id?: string
  lines: Array<{
    material_id: string
    unit_id: string
    quantity: string | number
    unit_cost?: string | number
    total_cost?: string | number
  }>
  supplier_name?: string
  vendor_id?: string
  invoice_number?: string
  invoice_date?: string
  invoice_total?: string | number
  notes?: string
  media_object_key?: string
  correlation_id?: string
  create_expense?: boolean
}

export interface CreateInvoiceResult {
  id: string
  receipt_ids: string[]
  expense_id: string | null
  status: string
}

// One call records every purchase on the document, updates stock, links the
// stored file and creates the unpaid Finance expense — all in one transaction.
export async function createInvoice(
  payload: CreateInvoicePayload,
  idempotencyKey?: string
): Promise<CreateInvoiceResult> {
  const res = await api.post<CreateInvoiceResult>(
    '/materials/invoices',
    payload,
    idempotencyHeaders(idempotencyKey)
  )
  return res.data
}

export interface LastPurchase {
  material_id: string
  unit_cost: string | null
  unit?: string
  occurred_date?: string
  supplier?: string | null
}

// The last rate paid for this material, org-wide — shown while recording so a
// price that has jumped gets noticed while it can still be questioned.
export async function fetchLastPurchase(materialId: string): Promise<LastPurchase> {
  const res = await api.get<LastPurchase>('/materials/last-purchase', {
    params: { material_id: materialId },
  })
  return res.data
}

// Money that was never recorded is not zero. Rendering it as ₹0 would claim
// the delivery was free and quietly drag every total downward.
export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return 'Not recorded'
  const n = Number(value)
  if (Number.isNaN(n)) return 'Not recorded'
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

// A retried request must not become a second delivery. The key is generated
// once when a record dialog opens and reused for every submit attempt from
// that dialog, so a double tap or a resend after a timeout replays the first
// result instead of recording again. See the backend's _claim_idempotency_key.
export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}

function idempotencyHeaders(key?: string) {
  return key ? { headers: { 'Idempotency-Key': key } } : undefined
}

export async function createInflow(
  payload: CreateInflowPayload,
  idempotencyKey?: string
): Promise<{ id: string; status: string }> {
  const res = await api.post<{ id: string; status: string }>(
    '/materials/inflows',
    payload,
    idempotencyHeaders(idempotencyKey)
  )
  return res.data
}

export async function reverseInflow(
  id: string,
  payload: { reason_note?: string; occurred_date?: string } = {}
): Promise<{ id: string; status: string }> {
  const res = await api.post<{ id: string; status: string }>(`/materials/inflows/${id}/reverse`, payload)
  return res.data
}

// ---------------------------------------------------------------------
// Outflows (usage)
// ---------------------------------------------------------------------

export async function fetchOutflows(
  filters: MovementFilters = {}
): Promise<MaterialMovementListResponse<MaterialUsage>> {
  const res = await api.get<MaterialMovementListResponse<MaterialUsage>>('/materials/outflows', {
    params: filters,
  })
  return res.data
}

export async function fetchOutflow(id: string): Promise<MaterialUsage> {
  const res = await api.get<MaterialUsage>(`/materials/outflows/${id}`)
  return res.data
}

export interface CreateOutflowPayload {
  project_id: string
  site_id?: string
  material_id: string
  unit_id: string
  quantity: string | number
  movement_reason?: OutflowReason
  work_item?: string
  notes?: string
  occurred_date: string
  // Send false to have the backend refuse an issue that would take stock
  // below zero (it returns a 409 carrying the real balance). Defaults to true
  // server-side so WhatsApp and mobile are unaffected; the dashboard opts in
  // and turns the refusal into a confirmation.
  allow_negative?: boolean
}

export async function createOutflow(
  payload: CreateOutflowPayload,
  idempotencyKey?: string
): Promise<{ id: string; status: string }> {
  const res = await api.post<{ id: string; status: string }>(
    '/materials/outflows',
    payload,
    idempotencyHeaders(idempotencyKey)
  )
  return res.data
}

export interface StockCheck {
  material_id: string
  site_id: string | null
  available: string
  unit: string | null
}

// The balance the backend's own guard will use, so the dialog can warn before
// submitting rather than after a rejection.
export async function fetchStockCheck(
  materialId: string,
  siteId?: string | null
): Promise<StockCheck> {
  const res = await api.get<StockCheck>('/materials/stock-check', {
    params: { material_id: materialId, site_id: siteId ?? undefined },
  })
  return res.data
}

// Shape of the 409 body the outflow endpoint returns when a quantity exceeds
// available stock and allow_negative was not set.
export interface OverStockConflict {
  message: string
  available: string
  requested: string
  unit: string
  material_name: string
}

export function asOverStockConflict(err: any): OverStockConflict | null {
  const detail = err?.response?.data?.detail
  if (err?.response?.status === 409 && detail && typeof detail === 'object' && 'available' in detail) {
    return detail as OverStockConflict
  }
  return null
}

export async function reverseOutflow(
  id: string,
  payload: { reason_note?: string; occurred_date?: string } = {}
): Promise<{ id: string; status: string }> {
  const res = await api.post<{ id: string; status: string }>(`/materials/outflows/${id}/reverse`, payload)
  return res.data
}

// ---------------------------------------------------------------------
// Inventory + Ledger
// ---------------------------------------------------------------------

export interface InventoryFilters {
  project_id?: string
  site_id?: string
  material_id?: string
}

export async function fetchInventory(filters: InventoryFilters = {}): Promise<MaterialStock[]> {
  const res = await api.get<MaterialStock[]>('/materials/inventory', { params: filters })
  return res.data
}

export async function fetchLedger(
  siteId: string,
  materialId: string,
  params: { limit?: number; offset?: number } = {}
): Promise<LedgerResponse> {
  const res = await api.get<LedgerResponse>(`/materials/ledger/${siteId}/${materialId}`, { params })
  return res.data
}

// Reasons that require ADMIN/PROJECT_MANAGER to submit — see backend
// authorization rules on POST /materials/inflows and /materials/outflows.
export const ADJUSTMENT_REASONS = new Set(['ADJUSTMENT_IN', 'ADJUSTMENT_OUT', 'OPENING_STOCK'])

// Recorded only through a transfer (POST /materials/transfers), which writes
// both halves together -- so the record dialogs don't offer them, though the
// list filters do.
export const TRANSFER_REASONS = new Set(['TRANSFER_IN', 'TRANSFER_OUT'])

export const INFLOW_REASONS: Array<{ value: InflowReason; label: string }> = [
  { value: 'RECEIVED', label: 'Delivery' },
  { value: 'TRANSFER_IN', label: 'From another site' },
  { value: 'RETURN_IN', label: 'Returned to site' },
  { value: 'ADJUSTMENT_IN', label: 'Stock correction' },
  { value: 'OPENING_STOCK', label: 'Opening Stock' },
]

export const OUTFLOW_REASONS: Array<{ value: OutflowReason; label: string }> = [
  { value: 'CONSUMED', label: 'Used' },
  { value: 'TRANSFER_OUT', label: 'To another site' },
  { value: 'RETURN_TO_VENDOR', label: 'Returned to supplier' },
  { value: 'WASTAGE', label: 'Wastage' },
  { value: 'ADJUSTMENT_OUT', label: 'Stock correction' },
]

// ---------------------------------------------------------------------
// Transfers between sites
// ---------------------------------------------------------------------

export interface CreateTransferPayload {
  from_site_id: string
  to_site_id: string
  material_id: string
  unit_id: string
  quantity: string | number
  occurred_date: string
  notes?: string
  // As for outflows: false makes the backend refuse sending more than the
  // sending site holds (409 with the real balance).
  allow_negative?: boolean
}

export interface MaterialTransfer {
  id: string
  material_id: string
  material_name: string
  quantity: string
  unit: string
  occurred_date: string
  notes: string | null
  created_by: string | null
  outflow_id: string
  from_project_id: string
  from_site_id: string
  from_site_name: string | null
  inflow_id: string
  to_project_id: string
  to_site_id: string
  to_site_name: string | null
  is_reversed: boolean
}

export async function createTransfer(
  payload: CreateTransferPayload,
  idempotencyKey?: string
): Promise<{ id: string; outflow_id: string; inflow_id: string; status: string }> {
  const res = await api.post<{ id: string; outflow_id: string; inflow_id: string; status: string }>(
    '/materials/transfers',
    payload,
    idempotencyHeaders(idempotencyKey)
  )
  return res.data
}

export async function fetchTransfers(
  params: { project_id?: string; limit?: number; offset?: number } = {}
): Promise<MaterialMovementListResponse<MaterialTransfer>> {
  const res = await api.get<MaterialMovementListResponse<MaterialTransfer>>('/materials/transfers', {
    params,
  })
  return res.data
}

export async function reverseTransfer(
  id: string,
  payload: { reason_note?: string; occurred_date?: string } = {}
): Promise<{ id: string; status: string }> {
  const res = await api.post<{ id: string; status: string }>(`/materials/transfers/${id}/reverse`, payload)
  return res.data
}

// What each movement reason is called on screen (WEB-29): the words people
// use on site, not the codes.
export const REASON_WORDS: Record<InflowReason | OutflowReason, string> = {
  RECEIVED: 'Delivery',
  TRANSFER_IN: 'From another site',
  RETURN_IN: 'Returned to site',
  ADJUSTMENT_IN: 'Stock correction',
  OPENING_STOCK: 'Opening stock',
  CONSUMED: 'Used',
  TRANSFER_OUT: 'To another site',
  RETURN_TO_VENDOR: 'Returned to supplier',
  WASTAGE: 'Wastage',
  ADJUSTMENT_OUT: 'Stock correction',
}

// ---------------------------------------------------------------------
// One ledger of every movement (WEB-30)
// ---------------------------------------------------------------------

/** A movement in or out, as one row of the materials ledger. */
export type LedgerRow =
  | ({ direction: 'IN' } & MaterialReceipt)
  | ({ direction: 'OUT' } & MaterialUsage)

/** How many movements of each direction the ledger loads at most. */
export const LEDGER_CAP = 1000

async function fetchAllPages<T>(fetchPage: (offset: number) => Promise<MaterialMovementListResponse<T>>, cap: number) {
  const items: T[] = []
  let total = 0
  do {
    const page = await fetchPage(items.length)
    items.push(...page.items)
    total = page.total
    if (page.items.length === 0) break
  } while (items.length < total && items.length < cap)
  return { items, total }
}

/**
 * Every delivery and use matching `filters`, oldest first, merged into one
 * list (the in/out endpoints page at 100; this pages through up to
 * LEDGER_CAP of each). `truncated` says when there were more.
 */
export async function fetchLedgerRows(
  filters: Omit<MovementFilters, 'limit' | 'offset' | 'movement_reason'>,
): Promise<{ rows: LedgerRow[]; truncated: boolean }> {
  const [ins, outs] = await Promise.all([
    fetchAllPages((offset) => fetchInflows({ ...filters, limit: 100, offset }), LEDGER_CAP),
    fetchAllPages((offset) => fetchOutflows({ ...filters, limit: 100, offset }), LEDGER_CAP),
  ])
  const rows: LedgerRow[] = [
    ...ins.items.map((m) => ({ ...m, direction: 'IN' as const })),
    ...outs.items.map((m) => ({ ...m, direction: 'OUT' as const })),
  ]
  rows.sort(
    (a, b) =>
      a.occurred_date.localeCompare(b.occurred_date) ||
      (a.occurred_time ?? '').localeCompare(b.occurred_time ?? '') ||
      a.created_at.localeCompare(b.created_at),
  )
  return { rows, truncated: ins.items.length < ins.total || outs.items.length < outs.total }
}
