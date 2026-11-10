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
  // The old free-text group; the material's place is `category_id` (PRC-01).
  category: string | null
  category_id: string | null
  sku: string | null
  is_active: boolean
}

// PRC-01: a company's material categories, two levels. `parent_id` null = main category.
export interface MaterialCategory {
  id: string
  parent_id: string | null
  name: string
  sort_order: number
  is_active: boolean
  // Materials directly in this category (not its sub-categories).
  material_count: number
}

export interface MaterialCategoryListResponse {
  items: MaterialCategory[]
  // Materials with no category yet.
  uncategorised: number
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
  /** WEB-78: the purchase order and goods received note this delivery came on (null when on none). */
  purchase_order_id?: string | null
  order_ref?: string | null
  grn_id?: string | null
  grn_ref?: string | null
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
  category_id: string | null
  unit: string
  total_received: string
  total_used: string
  current_stock: string
  /** PRC-27: still to come on open purchase orders for this site and material. */
  on_order?: string
  last_movement_at: string | null
  stock_state: StockState
}

export interface LedgerEntry {
  id: string
  // The delivery / use behind this entry (its inflow or outflow id).
  source_id?: string | null
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
  category_id?: string | null
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
    // null takes the material out of its category; left out, it stays.
    category_id?: string | null
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

// ---------------------------------------------------------------------
// Categories (PRC-01)
// ---------------------------------------------------------------------

export async function fetchMaterialCategories(): Promise<MaterialCategoryListResponse> {
  const res = await api.get<MaterialCategoryListResponse>('/materials/categories')
  return res.data
}

export async function createMaterialCategory(payload: { name: string; parent_id?: string | null }): Promise<MaterialCategory> {
  const res = await api.post<MaterialCategory>('/materials/categories', payload)
  return res.data
}

export async function updateMaterialCategory(
  id: string,
  payload: { name?: string; sort_order?: number; is_active?: boolean },
): Promise<MaterialCategory> {
  const res = await api.patch<MaterialCategory>(`/materials/categories/${id}`, payload)
  return res.data
}

export async function deleteMaterialCategory(id: string): Promise<void> {
  await api.delete(`/materials/categories/${id}`)
}

// The builder's standard list; places the materials a fixed rule places. Safe to repeat.
export async function applyStandardCategories(): Promise<{ categories_added: number; materials_placed: number }> {
  const res = await api.post<{ categories_added: number; materials_placed: number }>('/materials/categories/standard')
  return res.data
}

export interface CategoryPath {
  main: MaterialCategory
  sub: MaterialCategory | null
}

// id -> its main category and, for a sub-category, itself. A label for each: "Electrical › Switches & sockets".
export function categoryPaths(categories: MaterialCategory[]): Map<string, CategoryPath> {
  const byId = new Map(categories.map((c) => [c.id, c]))
  const paths = new Map<string, CategoryPath>()
  for (const c of categories) {
    const parent = c.parent_id ? byId.get(c.parent_id) : undefined
    if (c.parent_id && !parent) continue
    paths.set(c.id, parent ? { main: parent, sub: c } : { main: c, sub: null })
  }
  return paths
}

export function categoryLabel(path: CategoryPath | undefined): string {
  if (!path) return 'No category'
  return path.sub ? `${path.main.name} › ${path.sub.name}` : path.main.name
}

// Main categories in order, each with its sub-categories in order.
export function categoryTree(categories: MaterialCategory[]): { main: MaterialCategory; subs: MaterialCategory[] }[] {
  const order = (a: MaterialCategory, b: MaterialCategory) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)
  return categories
    .filter((c) => !c.parent_id)
    .sort(order)
    .map((main) => ({ main, subs: categories.filter((c) => c.parent_id === main.id).sort(order) }))
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
  /** PRC-34: the GST rate (0 = none) and whether unit_cost includes it; left out when not said. */
  gst_percent?: string
  rate_includes_gst?: boolean
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
    gst_percent?: string
    rate_includes_gst?: boolean
  }>
  /** PRC-34: the bill's GST rate and whether its line rates include it (a line's own wins). */
  gst_percent?: string
  rates_include_gst?: boolean
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

/** PRC-23: what a delivery did to the purchase orders at its site. */
export interface InflowResult {
  id: string
  status: string
  /** The open order it filled by itself (the only one that fits plainly). */
  order?: { id: string; ref: string; vendor_name: string; received: string; quantity: string; unit: string; status: string }
  /** Open orders it may belong to, offered (several, more than still to come, or another supplier). */
  open_orders?: { line_id: string; order_id: string; ref: string; vendor_name: string; pending: string; unit: string }[]
}

export async function createInflow(
  payload: CreateInflowPayload,
  idempotencyKey?: string
): Promise<InflowResult> {
  const res = await api.post<InflowResult>(
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

// ---------------------------------------------------------------------
// WA-168: Sizes -- how much ONE of a unit sites count in (a load, a drum) is
// in a material's Stock Unit, and the sizes the company was asked for.
// ---------------------------------------------------------------------

export interface UnitSize {
  material_id: string
  material: string
  from_unit_id: string
  unit: string
  unit_name: string
  stock_unit: string | null
  stock_unit_name: string | null
  one_unit_equals: string | null
  updated_at: string
}

export interface SizeRequest {
  id: string
  material_id: string
  material: string
  from_unit_id: string
  unit_name: string
  stock_unit_name: string | null
  proposed_one_unit_equals: string | null
  proposed_by_name: string | null
  requested_by_name: string | null
  waiting: number
  held_lines: { summary: string }[]
  status: 'open' | 'answered' | 'dismissed'
  created_at: string
}

export async function fetchUnitSizes(): Promise<{ items: UnitSize[] }> {
  const res = await api.get<{ items: UnitSize[] }>('/materials/unit-conversions')
  return res.data
}

export async function setUnitSize(materialId: string, fromUnitId: string, oneUnitEquals: number): Promise<void> {
  await api.put(`/materials/${materialId}/unit-conversions`, { from_unit_id: fromUnitId, one_unit_equals: oneUnitEquals })
}

export async function deleteUnitSize(materialId: string, fromUnitId: string): Promise<void> {
  await api.delete(`/materials/${materialId}/unit-conversions/${fromUnitId}`)
}

export async function fetchSizeRequests(): Promise<{ items: SizeRequest[] }> {
  const res = await api.get<{ items: SizeRequest[] }>('/materials/size-requests', { params: { status: 'open' } })
  return res.data
}

export async function answerSizeRequest(id: string, oneUnitEquals: number): Promise<{ message: string }> {
  const res = await api.post<{ message: string }>(`/materials/size-requests/${id}/answer`, { one_unit_equals: oneUnitEquals })
  return res.data
}

export async function dismissSizeRequest(id: string): Promise<void> {
  await api.post(`/materials/size-requests/${id}/dismiss`)
}

// ---------------------------------------------------------------------
// Excel import (PRC-05): items with categories, vendors, opening stock
// ---------------------------------------------------------------------

export type ImportSheet = 'Items' | 'Vendors' | 'Opening stock' | 'Minimum stock'
export type ImportResult = 'added' | 'existing' | 'placed' | 'updated' | 'removed' | 'problem'

export interface ImportReport {
  // false for a preview: nothing was saved.
  saved: boolean
  counts: Record<ImportSheet | 'Categories', Partial<Record<ImportResult, number>>>
  problems: number
  rows: { sheet: ImportSheet; row: number; name: string; result: ImportResult; message: string }[]
}

export async function downloadImportTemplate(): Promise<Blob> {
  const res = await api.get('/materials/import/template', { responseType: 'blob' })
  return res.data as Blob
}

export async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(binary)
}

// What the import would do, row by row; nothing is saved.
export async function previewImport(file: File): Promise<ImportReport> {
  const res = await api.post<ImportReport>('/materials/import/preview', { file_base64: await fileBase64(file) })
  return res.data
}

export async function runImport(file: File): Promise<ImportReport> {
  const res = await api.post<ImportReport>('/materials/import', { file_base64: await fileBase64(file) })
  return res.data
}

// ---------------------------------------------------------------------
// Stock for a period (PRC-17 / PRC-17d)
// ---------------------------------------------------------------------

export interface StockSummaryRow {
  project_id: string
  site_id: string | null
  material_id: string
  material_name: string
  unit: string
  category_id: string | null
  // "Electrical › Switches & sockets", or the main category alone; null without one.
  category: string | null
  main_category: string | null
  opening: string
  received: string
  used: string
  adjusted: string
  closing: string
  days_left: number | null
  /** PRC-27: still to come on open purchase orders (for a period that reaches today). */
  on_order?: string
  /** Counts what is on order: stock already ordered is not "what to order". PRC-47: also under the minimum set. */
  running_low: boolean
  /** PRC-47: the minimum set for this site (stock unit), how much to order when below, and whether it holds less. */
  min_qty?: string | null
  reorder_qty?: string | null
  below_min?: boolean
  // Only for roles that see the company's spending; null for the rest.
  spend: string | null
  spend_complete: boolean | null
  last_rate: string | null
}

export interface StockSummaryFilters {
  date_from?: string
  date_to?: string
  project_id?: string
  site_id?: string
  category_id?: string
  /** PRC-00: one item at every site this person can see. */
  material_id?: string
}

// ---------------------------------------------------------------------
// Minimum stock and reorder (PRC-47)
// ---------------------------------------------------------------------
export interface StockLevelSaved {
  id?: string
  site_id: string
  material_id: string
  min_qty?: string
  reorder_qty?: string | null
  removed?: boolean
  said: string
}

export interface StockLevelIn {
  site_id: string
  material_id: string
  /** 0: no minimum any more. */
  min_qty: string
  reorder_qty?: string | null
  source?: 'typed' | 'suggested'
}

export async function setStockLevel(body: StockLevelIn): Promise<StockLevelSaved> {
  const res = await api.put<StockLevelSaved>('/materials/stock-levels', body)
  return res.data
}

export async function setStockLevels(levels: StockLevelIn[]): Promise<{ items: StockLevelSaved[] }> {
  const res = await api.post<{ items: StockLevelSaved[] }>('/materials/stock-levels/bulk', { levels })
  return res.data
}

export interface StockLevelSuggestion {
  site_id: string
  material_id: string
  material: string
  unit: string
  main_category: string | null
  used_last_week: string
  closing: string
  lead_days: number
  supplier: string | null
  min_qty: string
  reorder_qty: string
  current_min: string | null
}

export async function suggestStockLevels(siteId: string): Promise<{ site_name: string; items: StockLevelSuggestion[] }> {
  const res = await api.get<{ site_name: string; items: StockLevelSuggestion[] }>('/materials/stock-levels/suggest', { params: { site_id: siteId } })
  return res.data
}

export interface BelowMinimumRow {
  site_id: string
  site_name: string
  project_id: string
  project_name: string
  material_id: string
  material: string
  unit: string
  unit_id: string
  closing: string
  on_order: string
  min_qty: string
  reorder_qty: string | null
  /** What a draft request or RFQ asks for: the reorder quantity, else back to twice the minimum. */
  to_order: string
  short_by: string
  /** "on order", "RFQ-0004", "REQ-0012": already being bought (no alert). */
  covered_by: string | null
}

export interface BelowMinimum {
  items: BelowMinimumRow[]
  total: number
  not_covered: number
  sites: { site_id: string; site_name: string; project_id: string; project_name: string; items: number; to_buy: { material_id: string; unit_id: string; quantity: string }[] }[]
}

export async function fetchBelowMinimum(params: { project_id?: string; site_id?: string } = {}): Promise<BelowMinimum> {
  const res = await api.get<BelowMinimum>('/materials/stock-levels/below', { params })
  return res.data
}

export async function fetchStockSummary(filters: StockSummaryFilters = {}): Promise<StockSummaryRow[]> {
  const res = await api.get<StockSummaryRow[]>('/materials/stock-summary', { params: filters })
  return res.data
}
