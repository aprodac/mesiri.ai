import axios from 'axios'
import { TRIAL_EXPIRED_CODE, markTrialExpired } from './trial'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TOKEN_KEY = 'mesiri_dashboard_token'

export const api = axios.create({ baseURL: BASE_URL })

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// A token in localStorage is not proof of a valid session — it may be
// expired, malformed, or revoked. Only a 401 (the backend rejecting the
// token itself) means the session is stale; a 403 means the session is
// valid but this particular resource is off-limits for the user's role,
// and must not log out a user who is otherwise legitimately signed in.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // A save refused because the free trial has ended (SS-08's read-only
    // guard): the body's `detail` is {code, message}. Pages show `detail` as
    // text, so hand them the message, and switch the app to read-only.
    const detail = error.response?.data?.detail
    if (error.response?.status === 403 && detail?.code === TRIAL_EXPIRED_CODE) {
      const message = String(detail.message || 'Your free trial has ended, so your data is read-only.')
      error.response.data.detail = message
      error.message = message
      markTrialExpired(message)
    }
    // A 401 from a login or signup call is a wrong password or code, not a
    // stale session: the page shows it, nothing to clear.
    const publicAuthCall = /^\/auth\/(login|code\/|signup)/.test(error.config?.url ?? '')
    if (error.response?.status === 401 && !publicAuthCall) {
      clearToken()
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export type AccessPolicy = {
  mode: 'all_projects' | 'custom_projects'
  projects: Array<{
    projectId: string
    siteAccess?: { mode: 'all_sites' | 'custom_sites'; siteIds?: string[] }
  }>
}

export interface Me {
  user_id: string
  organization_id: string
  organization_name: string | null
  role: string
  full_name: string
  access_policy: AccessPolicy
  // What the production /auth/me (apps/whatsapp-assistant/src/auth/router.py)
  // actually returns. The four fields above come from the backend identity
  // router, which production does not mount -- read both shapes until the
  // two are reconciled (see companyName / userName in app-sidebar.tsx).
  org_id?: string
  org_name?: string
  name?: string
  is_platform_admin?: boolean
  // Product modules switched on for the company (tracker BE-06 / WEB-02).
  enabled_modules?: string[]
  // The company's trial status (SS-15); null for a platform admin.
  company?: {
    status: 'trial' | 'active' | 'expired' | 'suspended' | string
    trial_ends_at: string | null
    trial_days_left: number | null
    continue_requested: boolean
  } | null
}

export async function login(email: string, password: string): Promise<void> {
  const res = await api.post('/auth/login', { email, password })
  setToken(res.data.access_token)
}

// Login by a code sent on WhatsApp, and web signup (SS-06, WEB-12):
// apps/whatsapp-assistant/src/auth/code_login.py.
export type CodePurpose = 'login' | 'signup'

export interface CodeRequested {
  resend_after_s: number
  expires_in_s: number
  /** Only from a test server that sends nothing (MESIRI_LOGIN_CODE_SENDER=dev). */
  dev_code: string | null
}

export async function requestCode(phone: string, purpose: CodePurpose): Promise<CodeRequested> {
  const res = await api.post<CodeRequested>('/auth/code/request', { phone, purpose })
  return res.data
}

export async function loginWithCode(phone: string, code: string): Promise<void> {
  const res = await api.post('/auth/code/login', { phone, code })
  setToken(res.data.access_token)
}

/** A right signup code gives a short-lived ticket for the signup itself. */
export async function verifySignupCode(phone: string, code: string): Promise<string> {
  const res = await api.post<{ signup_token: string }>('/auth/code/verify', { phone, code })
  return res.data.signup_token
}

export async function signup(body: {
  signup_token: string
  owner_name: string
  company_name: string
  site_name: string
}): Promise<void> {
  const res = await api.post('/auth/signup', body)
  setToken(res.data.access_token)
}

export async function logout(): Promise<void> {
  clearToken()
}

export async function fetchMe(): Promise<Me> {
  const res = await api.get<Me>('/auth/me')
  return res.data
}

export interface User {
  id: string
  email: string
  full_name: string
  role: 'ADMIN' | 'PROJECT_MANAGER' | 'SITE_ENGINEER' | 'FINANCE'
  whatsapp_number?: string | null
  status: 'active' | 'inactive' | 'suspended' | 'invited'
  access_policy?: AccessPolicy | null
}

export interface UserCreatePayload {
  full_name: string
  /** Left out for someone who works on WhatsApp only (WEB-17). */
  email?: string
  password?: string
  role: string
  whatsapp_number?: string | null
}

export interface UserUpdatePayload {
  full_name?: string
  role?: string
  whatsapp_number?: string | null
  password?: string
}

export async function fetchUsers(): Promise<User[]> {
  const res = await api.get<User[]>('/users')
  return res.data
}

export async function fetchUser(userId: string): Promise<User> {
  const res = await api.get<User>(`/users/${userId}`)
  return res.data
}

export async function createUser(payload: UserCreatePayload): Promise<User> {
  const res = await api.post<User>('/users', payload)
  return res.data
}

export async function updateUser(userId: string, payload: UserUpdatePayload): Promise<User> {
  const res = await api.patch<User>(`/users/${userId}`, payload)
  return res.data
}

export async function updateUserStatus(userId: string, status: string): Promise<User> {
  const res = await api.patch<User>(`/users/${userId}/status`, { status })
  return res.data
}

export async function fetchUserAccess(userId: string): Promise<AccessPolicy> {
  const res = await api.get<AccessPolicy>(`/users/${userId}/access`)
  return res.data
}

export async function updateUserAccess(userId: string, policy: AccessPolicy): Promise<AccessPolicy> {
  const res = await api.put<AccessPolicy>(`/users/${userId}/access`, policy)
  return res.data
}

export async function deleteUser(userId: string): Promise<void> {
  await api.delete(`/users/${userId}`)
}

export interface Company {
  id: string
  name: string
  deployment_type: string
  db_route: string
  status: string
  code?: string | null
  email?: string | null
  phone?: string | null
  address?: string | null
  primary_contact?: string | null
  timezone: string
  created_at: string
  updated_at: string
}

export interface CompanySummary {
  total_users: number
  active_users: number
  admin_count: number
  pm_count: number
  site_engineer_count: number
  finance_count: number
  total_projects: number
  total_sites: number
  wa_mapped_users: number
  wa_unmapped_users: number
  active_conversations_count: number
  messages_received_today: number
  messages_requiring_clarification: number
  last_whatsapp_activity?: string | null
}

export interface MessageMinUser {
  id: string
  email: string
  full_name: string
  role: string
  status: string
  whatsapp_number?: string | null
}

export interface CompanyMessage {
  id: string
  correlation_id: string
  direction: 'inbound' | 'outbound'
  sender_wa_id: string
  message_type: string
  body: string
  processing_status: string
  error_code?: string | null
  timestamp: string
  member?: MessageMinUser | null
  project_id?: string | null
  project_name?: string | null
  site_id?: string | null
  site_name?: string | null
}

export interface CompanyMessageList {
  items: CompanyMessage[]
  total: number
}

export interface JourneyTrace {
  stage: string
  succeeded: boolean
  duration_ms?: number | null
  error_code?: string | null
  error_message?: string | null
  created_at: string
}

export interface ProviderExecution {
  stage: string
  provider: string
  operation: string
  model?: string | null
  latency_ms?: number | null
  succeeded: boolean
  created_at: string
}

export interface TimelineEntryMin {
  id: string
  event_type: string
  summary: string
  source_aggregate_type: string
  source_aggregate_id: string
  occurred_at: string
}

export interface InteractionMin {
  id: string
  kind: string
  prompt: string
  status: string
  created_at: string
  resolved_at?: string | null
}

export interface CompanyMessageDetail extends CompanyMessage {
  body_text?: string | null
  raw_payload_captured: boolean
  assistant_reply?: string | null
  raw_payload?: any | null
  normalized_message?: any | null
  media_object_key?: string | null
  received_at: string
  processed_at?: string | null
  traces: JourneyTrace[]
  providers: ProviderExecution[]
  timeline_entries: TimelineEntryMin[]
  interactions: InteractionMin[]
}

export interface TimelineApiEntry {
  id: string
  project_id: string | null
  site_id: string | null
  event_type: string
  summary: string
  payload?: any
  occurred_at: string
  correlation_id?: string | null
  source_aggregate_type?: string | null
  source_aggregate_id?: string | null
  created_at?: string
}

export interface TimelineListResponse {
  items: TimelineApiEntry[]
  total: number
}

export async function fetchTimelineEntriesApi(params: {
  projectId?: string
  siteId?: string
  eventType?: string
  dateFrom?: string
  dateTo?: string
  limit?: number
  offset?: number
} = {}): Promise<TimelineListResponse> {
  const res = await api.get<TimelineListResponse>('/timeline', {
    params: {
      project_id: params.projectId,
      site_id: params.siteId,
      event_type: params.eventType && params.eventType !== 'ALL' ? params.eventType : undefined,
      date_from: params.dateFrom || undefined,
      date_to: params.dateTo || undefined,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    },
  })
  return res.data
}

export interface SiteIssueItem {

  id: string
  organization_id: string
  project_id: string
  site_id: string
  activity_id?: string | null
  work_package_id?: string | null
  location_id?: string | null
  issue_type: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | string
  narrative?: string | null
  delay_duration_minutes?: number | null
  occurred_at: string
  resolved_at?: string | null
  status: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | 'WONT_FIX' | 'CANCELLED' | string
  resolution_notes?: string | null
  assigned_user_id?: string | null
  reported_by_user_id?: string | null
  created_at: string
  updated_at: string
}

export interface SiteIssuesListResponse {
  items: SiteIssueItem[]
  total: number
}

export async function fetchSiteIssuesApi(params: {
  projectId?: string
  siteId?: string
  status?: string
  severity?: string
  limit?: number
  offset?: number
} = {}): Promise<SiteIssuesListResponse> {
  const res = await api.get<SiteIssuesListResponse>('/progress/issues', {
    params: {
      project_id: params.projectId,
      site_id: params.siteId,
      status: params.status && params.status !== 'ALL' ? params.status : undefined,
      severity: params.severity && params.severity !== 'ALL' ? params.severity : undefined,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    },
  })
  return res.data
}

export async function createSiteIssueApi(payload: {
  project_id: string
  site_id: string
  issue_type: string
  severity: string
  narrative?: string
  delay_duration_minutes?: number
}): Promise<SiteIssueItem> {
  const res = await api.post<SiteIssueItem>('/progress/issues', payload)
  return res.data
}

export async function resolveSiteIssueApi(
  issueId: string,
  resolutionNotes?: string
): Promise<{ status: string; message: string }> {
  const res = await api.post<{ status: string; message: string }>(
    `/progress/issues/${issueId}/resolve`,
    { resolution_notes: resolutionNotes }
  )
  return res.data
}

export interface GalleryItem {
  id: string
  organization_id: string
  project_id: string
  site_id: string
  parent_type: string
  parent_id: string
  media_object_key: string
  attachment_type: string
  mime_type?: string | null
  caption?: string | null
  ai_caption?: string | null
  role?: string | null
  captured_at?: string | null
  created_at: string
  /** Short-lived link to the photo (WEB-24); null when storage can't give one. */
  url?: string | null
  /** The work item's (or issue's) date and title (WEB-24). */
  work_date?: string | null
  parent_title?: string | null
}

export interface GalleryListResponse {
  items: GalleryItem[]
  total: number
}

export async function fetchSiteGalleryApi(params: {
  projectId?: string
  siteId?: string
  attachmentType?: string
  limit?: number
  offset?: number
} = {}): Promise<GalleryListResponse> {
  const res = await api.get<GalleryListResponse>('/progress/gallery', {
    params: {
      project_id: params.projectId,
      site_id: params.siteId,
      attachment_type: params.attachmentType && params.attachmentType !== 'ALL' ? params.attachmentType : undefined,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    },
  })
  return res.data
}

export interface OperationsSettingsItem {
  auto_approve_dprs: boolean
  require_photo_evidence: boolean
  allow_overrun_quantities: boolean
  default_shift: string
  whatsapp_nudge_hours: number
  auto_flag_weather_delays: boolean
  supervisor_phone_numbers: string[]
}


export async function fetchOperationsSettingsApi(): Promise<OperationsSettingsItem> {
  const res = await api.get<OperationsSettingsItem>('/progress/settings')
  return res.data
}

export async function updateOperationsSettingsApi(
  payload: Partial<OperationsSettingsItem>
): Promise<OperationsSettingsItem> {
  const res = await api.patch<OperationsSettingsItem>('/progress/settings', payload)
  return res.data
}



export async function acknowledgeSiteIssueApi(
  issueId: string
): Promise<{ status: string; message: string }> {
  const res = await api.post<{ status: string; message: string }>(
    `/progress/issues/${issueId}/acknowledge`
  )
  return res.data
}

export async function wontFixSiteIssueApi(
  issueId: string,
  resolutionNotes?: string
): Promise<{ status: string; message: string }> {
  const res = await api.post<{ status: string; message: string }>(
    `/progress/issues/${issueId}/wont-fix`,
    { resolution_notes: resolutionNotes }
  )
  return res.data
}

export async function fetchCompany(): Promise<Company> {


  const res = await api.get<Company>('/company')
  return res.data
}

export async function updateCompany(payload: Partial<Company>): Promise<Company> {
  const res = await api.patch<Company>('/company', payload)
  return res.data
}

// Company letterhead for DPRs (tracker BE-20 / WEB-10). Name, address, phone
// and email come from the company record and are edited through updateCompany.
export interface CompanyBranding {
  company_name: string
  address: string | null
  phone: string | null
  email: string | null
  letterhead_name: string | null
  brand_color: string | null
  gstin: string | null
  signatory_name: string | null
  signatory_designation: string | null
  has_logo: boolean
  logo_url: string | null
}

export type BrandingFields = Partial<
  Pick<
    CompanyBranding,
    'letterhead_name' | 'brand_color' | 'gstin' | 'signatory_name' | 'signatory_designation'
  >
>

export async function fetchBranding(): Promise<CompanyBranding> {
  const res = await api.get<CompanyBranding>('/company/branding')
  return res.data
}

export async function updateBranding(payload: BrandingFields): Promise<CompanyBranding> {
  const res = await api.put<CompanyBranding>('/company/branding', payload)
  return res.data
}

export async function uploadCompanyLogo(contentType: string, dataBase64: string): Promise<CompanyBranding> {
  const res = await api.put<CompanyBranding>('/company/branding/logo', {
    content_type: contentType,
    data_base64: dataBase64,
  })
  return res.data
}

export async function removeCompanyLogo(): Promise<CompanyBranding> {
  const res = await api.delete<CompanyBranding>('/company/branding/logo')
  return res.data
}

export async function fetchCompanySummary(): Promise<CompanySummary> {
  const res = await api.get<CompanySummary>('/company/summary')
  return res.data
}

export interface FetchMessagesParams {
  direction?: string
  search?: string
  member_id?: string
  message_type?: string
  project_id?: string
  site_id?: string
  processing_status?: string
  has_attachments?: boolean
  mapped_participant?: string
  limit?: number
  offset?: number
}

export async function fetchCompanyMessages(params?: FetchMessagesParams): Promise<CompanyMessageList> {
  const res = await api.get<CompanyMessageList>('/company/whatsapp/messages', { params })
  return res.data
}

export async function fetchCompanyMessageDetail(messageId: string): Promise<CompanyMessageDetail> {
  const res = await api.get<CompanyMessageDetail>(`/company/whatsapp/messages/${messageId}`)
  return res.data
}

export async function fetchConversationMessages(conversationId: string): Promise<CompanyMessage[]> {
  const res = await api.get<CompanyMessage[]>(`/company/whatsapp/conversations/${conversationId}/messages`)
  return res.data
}

export interface ConversationMember {
  id: string
  email: string
  full_name: string
  role: string
  status: string
  whatsapp_number?: string | null
}

export interface Conversation {
  sender_wa_id: string
  member?: ConversationMember | null
  last_message_preview: string
  last_direction: 'inbound' | 'outbound'
  last_activity: string
  message_count: number
  processing_status?: string | null
  error_code?: string | null
}

export interface ConversationList {
  items: Conversation[]
  total: number
}

export interface FetchConversationsParams {
  search?: string
  limit?: number
  offset?: number
}

export async function fetchConversations(params?: FetchConversationsParams): Promise<ConversationList> {
  const res = await api.get<ConversationList>('/company/whatsapp/conversations', { params })
  return res.data
}


export interface MessageOutcome {
  record_type: string
  record_id: string
  summary: string
}

export interface MessageProject {
  id: string
  name: string
}

export interface MessageSite {
  id: string
  name: string
}

export interface UserWhatsAppMessage {
  id: string
  correlation_id: string
  sender_wa_id: string
  message_type: string
  body_text?: string | null
  media_object_key?: string | null
  occurred_at: string
  direction: 'inbound' | 'outbound'
  processing_status: string
  error_code?: string | null
  clarification_status: 'none' | 'awaiting_user' | 'resolved' | 'expired'
  project?: MessageProject | null
  site?: MessageSite | null
  outcome?: MessageOutcome | null
}

export interface UserWhatsAppMessageList {
  items: UserWhatsAppMessage[]
  total: number
}

export interface MessageTrace {
  stage: string
  succeeded: boolean
  duration_ms?: number | null
  error_code?: string | null
  error_message?: string | null
  severity: string
  event_source: string
  created_at: string
}

export interface MessageProviderExecution {
  stage: string
  provider: string
  operation: string
  model?: string | null
  latency_ms?: number | null
  succeeded: boolean
  error_code?: string | null
  created_at: string
}

export interface UserWhatsAppMessageDetail {
  id: string
  correlation_id: string
  sender_wa_id: string
  message_type: string
  body_text?: string | null
  media_object_key?: string | null
  received_at: string
  processed_at?: string | null
  processing_status: string
  error_code?: string | null
  assistant_reply?: string | null
  raw_payload?: any
  normalized_message?: any
  clarification_status: 'none' | 'awaiting_user' | 'resolved' | 'expired'
  project?: MessageProject | null
  site?: MessageSite | null
  outcome?: MessageOutcome | null
  traces: MessageTrace[]
  providers: MessageProviderExecution[]
}

export interface UserWhatsAppMessageFilters {
  wa_id?: string
  direction?: string
  message_type?: string
  project_id?: string
  site_id?: string
  processing_status?: string
  clarification_status?: string
  has_attachments?: boolean
  search?: string
  date_from?: string
  date_to?: string
  sort?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

export async function fetchUserWhatsAppMessages(
  userId: string,
  filters: UserWhatsAppMessageFilters = {}
): Promise<UserWhatsAppMessageList> {
  const res = await api.get<UserWhatsAppMessageList>(`/users/${userId}/whatsapp/messages`, {
    params: filters,
  })
  return res.data
}

export async function fetchUserWhatsAppMessageDetail(
  userId: string,
  messageId: string
): Promise<UserWhatsAppMessageDetail> {
  const res = await api.get<UserWhatsAppMessageDetail>(`/users/${userId}/whatsapp/messages/${messageId}`)
  return res.data
}

// --- Finance, Expenses, Accounts, and Petty Cash API Integrations ---

export interface RecordExpenseApiPayload {
  project_id: string
  // Either category_id (picked from a real fetched list) or category_text
  // (a free-typed name the backend resolves against expense_categories, or
  // falls back to "Uncategorized" for) works -- at least one should be sent.
  category_id?: string
  category_text?: string
  amount: number
  occurred_date: string
  site_id?: string
  vendor_id?: string
  vendor_text?: string
  // Paid immediately from this org account (e.g. a petty cash box) -- omit
  // to record an unpaid expense, as before this field existed.
  account_id?: string
  currency?: string
  description?: string
  source?: string
}

export async function recordExpenseApi(payload: RecordExpenseApiPayload, idempotencyKey: string) {
  const res = await api.post('/expenses', payload, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
  return res.data
}

export async function fetchExpenseApi(expenseId: string) {
  const res = await api.get(`/expenses/${expenseId}`)
  return res.data
}

export interface CategoryItem {
  id: string
  name: string
  code: string | null
  status: 'active' | 'inactive'
  expense_count: number
  total_amount_spent: number
}

export async function fetchCategoriesApi(): Promise<CategoryItem[]> {
  const res = await api.get('/expenses/categories')
  return res.data
}

export async function createCategoryApi(payload: { name: string; code?: string }): Promise<CategoryItem> {
  const res = await api.post('/expenses/categories', payload)
  return res.data
}

export async function updateCategoryApi(
  categoryId: string,
  payload: { name?: string; code?: string; status?: 'active' | 'inactive' }
): Promise<CategoryItem> {
  const res = await api.patch(`/expenses/categories/${categoryId}`, payload)
  return res.data
}

export interface VendorItem {
  id: string
  name: string
  status: 'active' | 'inactive'
  expense_count: number
  total_amount_paid: number
}

export async function fetchVendorsApi(): Promise<VendorItem[]> {
  const res = await api.get('/finance/vendors')
  return res.data
}

export async function createVendorApi(payload: { name: string }): Promise<VendorItem> {
  const res = await api.post('/finance/vendors', payload)
  return res.data
}

export async function updateVendorApi(
  vendorId: string,
  payload: { name?: string; status?: 'active' | 'inactive' }
): Promise<VendorItem> {
  const res = await api.patch(`/finance/vendors/${vendorId}`, payload)
  return res.data
}

export async function fetchExpensesApi(params?: {
  project_id?: string
  site_id?: string
  category_id?: string
  vendor_id?: string
}) {
  const res = await api.get('/expenses', { params })
  return res.data
}

export async function reverseExpenseApi(expenseId: string) {
  const res = await api.post(`/expenses/${expenseId}/reverse`, {}, {
    headers: {
      'Idempotency-Key': `rev_${Date.now()}_${expenseId}`,
    },
  })
  return res.data
}

export interface ExpenseAttachmentApiItem {
  id: string
  expense_id: string
  attachment_type: string
  created_at: string | null
  url: string
}

export async function fetchExpenseAttachmentsApi(expenseId: string): Promise<ExpenseAttachmentApiItem[]> {
  const res = await api.get(`/expenses/${expenseId}/attachments`)
  return res.data
}

export interface ExpenseAttachmentGalleryApiItem extends ExpenseAttachmentApiItem {
  amount: number
  description: string | null
  occurred_date: string
  project_id: string
  category_name: string | null
  vendor_name: string | null
}

export async function fetchAllExpenseAttachmentsApi(params?: {
  project_id?: string
  site_id?: string
  start_date?: string
  end_date?: string
  limit?: number
  offset?: number
}): Promise<ExpenseAttachmentGalleryApiItem[]> {
  const res = await api.get('/expenses/attachments', { params })
  return res.data
}

export interface CreateAccountApiPayload {
  name: string
  account_type: 'bank' | 'cash' | 'employee_advance' | 'other'
  currency: string
  opening_balance: number
  account_number?: string
  bank_name?: string
  ifsc_code?: string
  custodian_name?: string
  owner_user_id?: string
  project_id?: string
  site_id?: string
}

export async function createAccountApi(payload: CreateAccountApiPayload) {
  const res = await api.post('/finance/accounts', payload)
  return res.data
}

export async function deleteAccountApi(accountId: string) {
  const res = await api.delete(`/finance/accounts/${accountId}`)
  return res.data
}

export async function renameAccountApi(accountId: string, name: string) {
  const res = await api.patch(`/finance/accounts/${accountId}`, { name })
  return res.data
}

export async function fetchAccountsApi(params?: { project_id?: string; site_id?: string }) {
  const res = await api.get('/finance/accounts', { params })
  return res.data
}

export interface TransferMoneyApiPayload {
  from_account_id: string
  to_account_id: string
  amount: number
  description?: string
  occurred_date?: string
}

export async function transferMoneyApi(payload: TransferMoneyApiPayload, idempotencyKey: string) {
  const res = await api.post('/finance/transfers', payload, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
  return res.data
}

export async function reverseTransferApi(transferId: string) {
  const res = await api.post(
    `/finance/transfers/${transferId}/reverse`,
    {},
    { headers: { 'Idempotency-Key': `rev-${transferId}-${Date.now()}` } }
  )
  return res.data
}

export interface RecordVoucherApiPayload {
  cash_box_id: string
  // Required to record a real expense (POST /expenses needs it) -- the
  // cash box's own project_id, passed through by the caller.
  project_id: string
  site_id?: string
  amount: number
  category: string
  vendor_name?: string
  description: string
  date: string
  target_account_id?: string
}

export async function recordVoucherApi(payload: RecordVoucherApiPayload) {
  const key = `vch-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  if (payload.target_account_id) {
    return transferMoneyApi(
      {
        from_account_id: payload.cash_box_id,
        to_account_id: payload.target_account_id,
        amount: payload.amount,
        description: `${payload.category}: ${payload.description}`,
        occurred_date: payload.date,
      },
      key
    )
  }
  // A real expense paid immediately from the cash box account -- the same
  // mechanism WhatsApp's petty-cash-adjacent expense capture already uses
  // (RecordExpenseCommand.account_id), just reached via the dashboard.
  // category/vendor are free-typed here (the dialog offers a fixed picklist,
  // not real category ids), so they travel as category_text/vendor_text for
  // the backend's resolver to match against real categories/vendors (or
  // create them on first use, or fall back to "Uncategorized") -- never a
  // hard rejection over an unmatched name.
  return recordExpenseApi(
    {
      project_id: payload.project_id,
      site_id: payload.site_id,
      account_id: payload.cash_box_id,
      category_text: payload.category,
      vendor_text: payload.vendor_name,
      amount: payload.amount,
      occurred_date: payload.date,
      description: payload.description,
      source: 'web',
    },
    key
  )
}

export interface ReplenishFloatApiPayload {
  cash_box_id: string
  source_account_id: string
  amount: number
  notes?: string
}

export async function replenishFloatApi(payload: ReplenishFloatApiPayload) {
  const key = `repl-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  return transferMoneyApi(
    {
      from_account_id: payload.source_account_id,
      to_account_id: payload.cash_box_id,
      amount: payload.amount,
      description: payload.notes || 'Petty cash float replenishment',
    },
    key
  )
}

export async function fetchAccountTransactionsApi(accountId: string) {
  const res = await api.get(`/finance/accounts/${accountId}/transactions`)
  return res.data
}

export async function fetchVouchersApi(cashBoxId?: string) {
  const res = await api.get('/finance/petty-cash/vouchers', {
    params: cashBoxId ? { cash_box_id: cashBoxId } : undefined,
  })
  return res.data
}

export interface MoneyTransactionItem {
  id: string
  organization_id: string
  transaction_type: string
  amount: number
  occurred_date: string
  created_by: string
  from_account_id: string | null
  from_account_name: string | null
  to_account_id: string | null
  to_account_name: string | null
  source_type: string | null
  source_id: string | null
  description: string | null
  correlation_id: string | null
}

export async function fetchTransactionsApi(params?: {
  transaction_type?: string
  account_id?: string
  start_date?: string
  end_date?: string
  limit?: number
}): Promise<MoneyTransactionItem[]> {
  const res = await api.get('/finance/transactions', { params })
  return res.data
}

export interface CategoryBreakdownItem {
  id: string
  name: string
  amount: number
}

export interface MonthlyTrendItem {
  month: string
  amount: number
  count: number
}

export interface TopVendorItem {
  id: string
  name: string
  total_spent: number
  unpaid_amount: number
}

export interface PettyCashSummaryItem {
  id: string
  name: string
  custodian_name: string
  current_balance: number
  opening_balance: number
}

export interface FinanceHealthAlerts {
  low_float_count: number
  unpaid_invoice_count: number
  total_unpaid_amount: number
}

export interface FinanceSummaryItem {
  total_liquidity: number
  total_expenses: number
  unpaid_expenses: number
  active_accounts_count: number
  active_vendors_count: number
  active_categories_count: number
  category_breakdown: CategoryBreakdownItem[]
  monthly_trend: MonthlyTrendItem[]
  top_vendors: TopVendorItem[]
  petty_cash_accounts: PettyCashSummaryItem[]
  health_alerts: FinanceHealthAlerts
}

export async function fetchFinanceSummaryApi(): Promise<FinanceSummaryItem> {
  const res = await api.get('/finance/summary')
  return res.data
}

export interface FinanceSettingsItem {
  base_currency: string
  currency_symbol: string
  fiscal_year_start: string
  low_float_threshold: number
  auto_approval_limit: number
  require_receipt_above: number
  duplicate_window_hours: number
  default_tax_rate: number
  enabled_payment_methods: string[]
  low_balance_warning_enabled?: boolean
  transfer_receipt_enabled?: boolean
  expense_card_enabled?: boolean
  weekly_digest_enabled?: boolean
  weekly_digest_schedule?: string
}

export async function fetchFinanceSettingsApi(): Promise<FinanceSettingsItem> {
  const res = await api.get('/finance/settings')
  return res.data
}

export async function updateFinanceSettingsApi(
  payload: Partial<FinanceSettingsItem>
): Promise<FinanceSettingsItem> {
  const res = await api.patch('/finance/settings', payload)
  return res.data
}

export interface SandboxSimulationResult {
  intent: string
  confidence: string
  fields: Record<string, any>
  workflow_decision: string
  reply_message: string
}

export async function simulateWhatsAppSandboxApi(message: string): Promise<SandboxSimulationResult> {
  const res = await api.post('/finance/whatsapp/sandbox/simulate', { message })
  return res.data
}

export interface FinanceReportRow {
  id: string
  code: string | null
  title: string
  category: string | null
  account_name: string | null
  amount: number
  percentage: number | null
  status: string | null
  notes: string | null
}

export interface FinanceReportStatementItem {
  report_type: string
  title: string
  subtitle: string
  generated_at: string
  total_inflows: number
  total_outflows: number
  net_margin: number
  rows: FinanceReportRow[]
}

export async function fetchFinanceReportApi(params?: {
  report_type?: string
  project_id?: string
}): Promise<FinanceReportStatementItem> {
  const res = await api.get('/finance/reports/statement', { params })
  return res.data
}

// --- Labour & Workforce Module API Types & Helpers ---

export interface LabourSettingsItem {
  missing_report_reminder_enabled: boolean
  missing_report_reminder_time: string
  headcount_anomaly_alert_enabled: boolean
  wage_change_alert_enabled: boolean
  require_dashboard_approval_for_new_worker: boolean
}

export async function fetchLabourSettingsApi(): Promise<LabourSettingsItem> {
  const res = await api.get('/labour/settings')
  return res.data
}

export async function updateLabourSettingsApi(
  payload: Partial<LabourSettingsItem>
): Promise<LabourSettingsItem> {
  const res = await api.patch('/labour/settings', payload)
  return res.data
}

export interface LabourSandboxSimulationResult {
  intent: string
  confidence: string
  fields: Record<string, any>
  workflow_decision: string
  reply_message: string
  line_summaries?: string[]
}

export async function simulateLabourWhatsAppSandboxApi(
  message: string
): Promise<LabourSandboxSimulationResult> {
  const res = await api.post('/labour/whatsapp/sandbox/simulate', { message })
  return res.data
}

export interface WorkforceWorkerItem {
  id: string
  organization_id: string
  name: string
  trade: string | null
  worker_type: 'permanent' | 'temporary' | 'contractor'
  default_daily_wage: number | null
  contractor: string | null
  status: 'active' | 'inactive'
}

/** One worker's attendance history, derived on read from
 *  labour_attendance_lines. Nothing here is stored or editable — these are
 *  facts about what happened, not fields on a person. */
export interface WorkerStatistics {
  key: string
  /** Null for a temporary worker never promoted into the register. */
  worker_id: string | null
  name: string
  is_registered: boolean
  /** Distinct dates present. Never an assumed 10 or 30. */
  days_worked: number
  /** Reports they appear in — higher than days_worked when someone is
   *  recorded on two sites the same day. */
  attendance_count: number
  man_days: number
  priced_man_days: number
  unpriced_man_days: number
  total_earnings: number
  avg_daily_wage: number
  first_seen: string | null
  last_seen: string | null
  /** Every trade/contractor they have actually worked under, not just the
   *  current one on their register row. */
  trades: string[]
  contractors: string[]
  /** Populated only by the single-worker endpoint. Empty from the list
   *  endpoint means "not requested", not "never worked". */
  dates_worked: string[]
}

export async function fetchWorkerStatisticsApi(params?: {
  project_id?: string
  site_id?: string
  date_from?: string
  date_to?: string
}): Promise<{ items: WorkerStatistics[]; total: number }> {
  const res = await api.get('/labour/workers/statistics', { params })
  return res.data
}

export async function fetchOneWorkerStatisticsApi(
  workerId: string
): Promise<WorkerStatistics> {
  const res = await api.get(`/labour/workers/${workerId}/statistics`)
  return res.data
}

export interface CreateWorkerPayload {
  name: string
  trade?: string
  worker_type?: 'permanent' | 'temporary' | 'contractor'
  default_daily_wage?: number
  contractor?: string
  status?: 'active' | 'inactive'
}

export async function fetchWorkersApi(params?: {
  status?: string
  search?: string
  limit?: number
  offset?: number
}): Promise<{ items: WorkforceWorkerItem[]; total: number }> {
  const res = await api.get('/labour/workers', { params })
  return res.data
}

export async function createWorkerApi(
  payload: CreateWorkerPayload
): Promise<WorkforceWorkerItem> {
  const res = await api.post('/labour/workers', payload)
  return res.data
}

export async function updateWorkerApi(
  workerId: string,
  payload: Partial<CreateWorkerPayload>
): Promise<WorkforceWorkerItem> {
  const res = await api.patch(`/labour/workers/${workerId}`, payload)
  return res.data
}

export interface LabourAttendanceSummaryItem {
  id: string
  organization_id: string
  project_id: string | null
  site_id: string | null
  occurred_date: string
  recorded_via: string
  notes: string | null
  line_count: number
  total_headcount: number
  total_cost: number
}

export interface LabourAttendanceLineItem {
  id: string
  worker_id: string | null
  worker_name: string | null
  worker_name_original: string | null
  trade: string | null
  headcount: number
  daily_wage: number | null
  contractor: string | null
  activity: string | null
}

export interface LabourAttendanceAttachmentItem {
  id: string
  attachment_type: string
  /** Null when the photo cannot be linked right now (storage misconfigured,
   *  or a key the provider no longer resolves). The attachment is still
   *  listed, because the record should stay truthful about what was
   *  captured even when the image can't be opened. */
  url: string | null
}

export interface LabourAttendanceDetailItem extends LabourAttendanceSummaryItem {
  lines: LabourAttendanceLineItem[]
  attachments: LabourAttendanceAttachmentItem[]
}

export async function fetchAttendanceReportsApi(params?: {
  project_id?: string
  site_id?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}): Promise<{ items: LabourAttendanceSummaryItem[]; total: number }> {
  const res = await api.get('/labour/attendance', { params })
  return res.data
}

/** Development cleanup only. 403 unless MESIRI_ALLOW_LABOUR_DELETE is set and
 *  the caller is ADMIN. Returns 409 while the worker still appears on any
 *  attendance line — delete those reports first. */
export async function deleteWorkerApi(workerId: string): Promise<{ worker_id: string; name: string }> {
  const res = await api.delete(`/labour/workers/${workerId}`)
  return res.data
}

export interface DeleteAttendanceResult {
  report_id: string
  deleted_lines: number
  deleted_attachments: number
  deleted_outbox_events: number
  unlinked_corrections: number
  /** Always 0 — deleting attendance never deletes a worker. */
  deleted_workers: number
}

/** Development cleanup only. Returns 403 unless MESIRI_ALLOW_LABOUR_DELETE is
 *  set on the server AND the caller is an ADMIN, so this is inert on any
 *  environment where it has not been deliberately enabled. */
export async function deleteAttendanceReportApi(
  reportId: string
): Promise<DeleteAttendanceResult> {
  const res = await api.delete(`/labour/attendance/${reportId}`)
  return res.data
}

export async function fetchAttendanceReportDetailApi(
  reportId: string
): Promise<LabourAttendanceDetailItem> {
  const res = await api.get(`/labour/attendance/${reportId}`)
  return res.data
}

// --- Backend-generated labour statements -----------------------------------
// GET /labour/reports/statement. Every figure is aggregated in SQL from
// labour_attendance_lines, so nothing here is capped by a page size or
// computed in the browser.
//
// This replaced a browser-side `fetchLabourReportApi` that priced the *worker
// register* at an assumed 800/day and asserted a 10- or 30-day month for
// everyone on it, including workers who had never appeared on site. It is
// deleted rather than deprecated so it cannot be reached again.

export interface LabourStatementRow {
  id: string
  code: string | null
  title: string
  category: string | null
  contractor: string | null
  /** Person-days recorded. Not an assumed 10 or 30. */
  man_days: number
  /** Of those, the ones whose attendance line carried a wage. */
  priced_man_days: number
  days_worked: number
  first_date: string | null
  last_date: string | null
  report_count: number
  avg_daily_wage: number
  total_cost: number
  percentage: number
}

export interface LabourStatement {
  report_type: string
  title: string
  subtitle: string
  generated_at: string
  date_from: string | null
  date_to: string | null
  total_man_days: number
  priced_man_days: number
  /** Above zero when some attendance was recorded without pay rates, so the
   *  screen can say the cost covers only part of the man-days. */
  unpriced_man_days: number
  total_cost: number
  avg_daily_wage: number
  rows: LabourStatementRow[]
}

export type LabourStatementType =
  | 'trade_breakdown'
  | 'subcontractor_ledger'
  | 'daily_attendance'
  | 'worker_wages'

export async function fetchLabourStatementApi(params?: {
  report_type?: LabourStatementType
  project_id?: string
  site_id?: string
  date_from?: string
  date_to?: string
}): Promise<LabourStatement> {
  const res = await api.get('/labour/reports/statement', { params })
  return res.data
}

// ---------------------------------------------------------------------------
// Progress Activities API Types & Functions
// ---------------------------------------------------------------------------

export interface ActivityQuantity {
  id: string
  work_type?: string | null
  unit_id?: string | null
  unit?: string | null
  quantity: number | string
  measurement_type: string
}

export interface ProgressUpdate {
  id: string
  occurred_at: string
  update_kind: string
  narrative?: string | null
  quantity?: number | string | null
  unit_id?: string | null
  unit?: string | null
  // Set when this row corrected a previous one (ADR-D14) -- the old row
  // is never edited or deleted, so both remain in the list below.
  supersedes_id?: string | null
  reported_by_user_id?: string | null
  source: string
  created_at: string
}

export interface ActivityAttachment {
  id: string
  media_object_key: string
  attachment_type: string
  mime_type?: string | null
  caption?: string | null
  ai_caption?: string | null
  role?: string | null
  captured_at?: string | null
  created_at: string
}

export interface ActivitySummary {
  id: string
  organization_id: string
  project_id: string
  site_id: string
  work_package_id?: string | null
  location_id?: string | null
  work_type?: string | null
  activity_date: string
  started_at?: string | null
  ended_at?: string | null
  status: string
  narrative?: string | null
  contractor?: string | null
  reported_by_user_id?: string | null
  source: string
  created_at: string
  updated_at: string
}

export interface ActivitiesListResponse {
  items: ActivitySummary[]
  total: number
}

export interface ActivityDetailResponse extends ActivitySummary {
  quantities: ActivityQuantity[]
  progress_updates: ProgressUpdate[]
  attachments: ActivityAttachment[]
}

export async function fetchActivitiesApi(params?: {
  project_id?: string
  site_id?: string
  status?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}): Promise<ActivitiesListResponse> {
  const res = await api.get<ActivitiesListResponse>('/progress/activities', { params })
  return res.data
}

export async function fetchActivityDetailApi(activityId: string): Promise<ActivityDetailResponse> {
  const res = await api.get<ActivityDetailResponse>(`/progress/activities/${activityId}`)
  return res.data
}

// ─── Activity corrections & undo (ADR-D14/D15) ─────────────────────────────

export interface CorrectActivityPayload {
  work_type?: string | null
  location_id?: string | null
  contractor?: string | null
  narrative?: string | null
  activity_date?: string | null
  reason?: string | null
}

export interface CorrectProgressUpdatePayload {
  quantity?: number | string | null
  unit_id?: string | null
  narrative?: string | null
  reason?: string | null
}

export interface ActivityCorrection {
  id: string
  activity_id: string
  field_name: string
  old_value: unknown
  new_value: unknown
  reason?: string | null
  corrected_by_user_id?: string | null
  correlation_id?: string | null
  created_at: string
}

export interface ActivityCorrectionsListResponse {
  items: ActivityCorrection[]
}

/** Correct one or more Activity header fields (work_type, location_id,
 * contractor, narrative, activity_date). Allowed even once the day is part
 * of an approved daily report -- that report is revised, not left wrong. */
export async function correctActivityApi(
  activityId: string,
  payload: CorrectActivityPayload,
): Promise<ActivityDetailResponse> {
  const res = await api.patch<ActivityDetailResponse>(`/progress/activities/${activityId}`, payload)
  return res.data
}

/** Undo an Activity entirely (soft delete). Refused once the day is part
 * of an approved daily report. */
export async function voidActivityApi(activityId: string, reason: string): Promise<void> {
  await api.delete(`/progress/activities/${activityId}`, { data: { reason } })
}

/** Correct a Progress Update's quantity/unit/narrative by appending a new
 * row that supersedes it -- the old row is never edited or deleted. */
export async function correctProgressUpdateApi(
  activityId: string,
  updateId: string,
  payload: CorrectProgressUpdatePayload,
): Promise<ActivityDetailResponse> {
  const res = await api.patch<ActivityDetailResponse>(
    `/progress/activities/${activityId}/updates/${updateId}`,
    payload,
  )
  return res.data
}

/** Undo a single Progress Update (soft delete). Refused once the day is
 * part of an approved daily report. */
export async function voidProgressUpdateApi(
  activityId: string,
  updateId: string,
  reason: string,
): Promise<void> {
  await api.delete(`/progress/activities/${activityId}/updates/${updateId}`, { data: { reason } })
}

export async function fetchActivityCorrectionsApi(
  activityId: string,
): Promise<ActivityCorrectionsListResponse> {
  const res = await api.get<ActivityCorrectionsListResponse>(
    `/progress/activities/${activityId}/corrections`,
  )
  return res.data
}

// ─── The site's working day (BE-08 / BE-14 / BE-16, Today page WEB-03) ───────

export type SiteDayStatus =
  | 'draft'
  | 'needs_details'
  | 'ready'
  | 'in_review'
  | 'approved'
  | 'published'
  | 'not_reported'

export interface SiteDayItem {
  site_id: string
  site_name: string
  project_id: string
  project_name: string
  daily_report_id: string | null
  code: string | null
  status: SiteDayStatus
  missing_sections: { blocking: string[]; optional: string[] } | null
  site_working: 'full' | 'half' | 'none' | null
  workers: number
  work_items: number
  photos: number
  open_issues: number
  /** The day's other entries (WEB-32): materials, issues raised that day,
   * progress on work started earlier. */
  materials: number
  issues_today: number
  progress_updates: number
  last_update_at: string | null
  last_update_by: string | null
  latest_update: string | null
  /** Items saved from WhatsApp still waiting to be confirmed (BE-09). */
  drafts?: number
}

export interface ProjectDayItem {
  project_id: string
  project_name: string
  reporting_cutoff_time: string | null
  dpr_send_deadline: string | null
  auto_generate_dpr: boolean
  sent: boolean
  send_requested: boolean
  site_count: number
  project_report_status: SiteDayStatus | null
  project_report_id: string | null
}

export interface SiteDaysResponse {
  date: string
  items: SiteDayItem[]
  projects: ProjectDayItem[]
}

export async function fetchSiteDaysApi(date: string, projectId?: string): Promise<SiteDaysResponse> {
  const res = await api.get<SiteDaysResponse>('/dpr/site-days', {
    params: { date, project_id: projectId },
  })
  return res.data
}

export interface SiteDayConditions {
  weather?: 'sunny' | 'cloudy' | 'rainy' | 'windy' | 'extreme_heat' | null
  hours_lost?: number | null
  site_working?: 'full' | 'half' | 'none' | null
  tomorrow_plan?: string | null
}

export async function setSiteDayConditionsApi(
  siteId: string,
  date: string,
  conditions: SiteDayConditions,
): Promise<void> {
  await api.patch(`/dpr/site-days/${siteId}/conditions`, conditions, { params: { date } })
}

export async function sendProjectDprNowApi(projectId: string): Promise<void> {
  await api.post(`/dpr/projects/${projectId}/send`)
}

export async function approveDailyReportApi(reportId: string, notes?: string): Promise<void> {
  await api.post(`/dpr/daily-reports/${reportId}/approve`, { notes })
}

/** Fetches the DPR PDF as a Blob -- the PDF WhatsApp sent when one exists,
 * otherwise printed now from the same template (BE-47). */
export async function fetchDailyReportPdfApi(reportId: string, versionId?: string): Promise<Blob> {
  const res = await api.get(`/dpr/daily-reports/${reportId}/document.pdf`, {
    responseType: 'blob',
    params: versionId ? { version_id: versionId } : undefined,
  })
  return res.data
}

// ─── One site's day, for the site DPR page (WEB-04) ──────────────────────────

export type FactType = 'activity' | 'labour_report' | 'material_receipt' | 'material_usage' | 'site_issue'

/** One item the engineer can confirm or remove (GET /dpr/site-days/{id}). */
export interface ReviewItem {
  fact_type: FactType
  id: string
  section: 'work' | 'labour' | 'materials' | 'issues'
  title: string | null
  detail: string | null
  review: 'draft' | 'confirmed'
  flags: ('possible_duplicate' | 'beyond_stock')[]
  quantities?: { work_type: string | null; quantity: string; unit: string }[]
  evidence_count?: number
  severity?: string | null
  status?: string | null
}

export interface SiteDayMaterialLine {
  material_name: string | null
  unit: string | null
  received: string
  used: string
  adjusted: string
  opening: string | null
  closing: string | null
  beyond_stock: boolean
}

/** The report as it stands now (the payload a version stores). */
export interface SiteDayReport {
  activity_count: number
  evidence_count: number
  labour: { headcount: number; named_count: number; trades: { trade: string; headcount: number }[]; total_cost: string }
  materials: SiteDayMaterialLine[]
  conditions: {
    weather: SiteDayConditions['weather']
    site_working: SiteDayConditions['site_working']
    tomorrow_plan: string | null
    hours_lost: string | null
    hours_lost_source: 'entered' | 'issues' | null
  }
  late_entries: { report_date: string; summary: string; outcome: string }[]
}

export interface DprVersion {
  id: string
  version_no: number
  created_at: string
  approved_at: string | null
  approved_by: string | null
  revision_reason: string | null
  is_current: boolean
}

export interface SiteDayDetail {
  date: string
  site_id: string
  project_id: string
  day: SiteDayItem | null
  project: ProjectDayItem | null
  report: SiteDayReport
  items: ReviewItem[]
  drafts: number
  versions: DprVersion[]
  /** BE-18: AI summary of the confirmed report; null until it has one. */
  summary: string | null
}

export async function fetchSiteDayApi(siteId: string, date: string): Promise<SiteDayDetail> {
  const res = await api.get<SiteDayDetail>(`/dpr/site-days/${siteId}`, { params: { date } })
  return res.data
}

// ─── The Daily Reports history (WEB-06) ─────────────────────────────────────

/** One site or project DPR, with the figures from its current version. */
export interface DprHistoryItem {
  id: string
  dpr_number: string
  report_date: string
  level: 'site' | 'project'
  project_id: string
  project_name: string
  site_id: string | null
  site_name: string | null
  workflow_status: SiteDayStatus
  weather: string | null
  work_items: number
  workers: number
  labour_cost: string
  open_issues: number
  photos: number
  /** Project DPRs only: confirmed sites in it, of all active sites. */
  reported_sites: number | null
  total_sites: number | null
  /** Null when the day has no version yet (nothing to show or print). */
  version_no: number | null
  approved_at: string | null
  approved_by: string | null
  /** BE-18: AI summary of the confirmed report; null when it has none. */
  summary: string | null
  created_at: string
}

export async function fetchDprHistoryApi(params: {
  project_id?: string
  level?: 'site' | 'project'
  status?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}): Promise<{ items: DprHistoryItem[]; total: number }> {
  const res = await api.get<{ items: DprHistoryItem[]; total: number }>('/dpr/daily-reports', { params })
  return res.data
}

// ─── One project's day, for the project DPR page (WEB-05) ───────────────────

/** One site's line in the project DPR: `reported` false = "Not reported". */
export interface ProjectReportSite {
  site_name: string | null
  reported: boolean
  activity_count: number
  open_issue_count: number
  headcount: number
  labour_cost: string
  stock_flags: number
  possible_duplicates: number
}

/** The PROJECT payload: a roll-up of the confirmed site DPRs (BE-16). */
export interface ProjectReport {
  level: 'PROJECT'
  project_name: string | null
  report_date: string
  sites: ProjectReportSite[]
  reported_site_count: number
  total_site_count: number
  activity_count: number
  open_issue_count: number
  evidence_count: number
  issues: {
    site_name: string | null
    issue_type: string | null
    severity: string | null
    narrative: string | null
    status: string | null
  }[]
  stock_flags: number
  possible_duplicates: number
  labour: { headcount: number; total_cost: string }
  materials: { material_name: string | null; unit: string | null; received: string; used: string }[]
}

export interface ProjectDayDetail {
  date: string
  project_id: string
  project: ProjectDayItem
  sites: SiteDayItem[]
  report: ProjectReport
  /** "sent": the DPR as it went out; "preview": what would go out now. */
  report_source: 'sent' | 'preview'
  versions: DprVersion[]
  /** BE-18: AI summary of the DPR as it went out; null for a preview. */
  summary: string | null
}

export async function fetchProjectDayApi(projectId: string, date: string): Promise<ProjectDayDetail> {
  const res = await api.get<ProjectDayDetail>(`/dpr/projects/${projectId}/day`, { params: { date } })
  return res.data
}

export interface FactSources {
  messages: {
    id: string
    type: string
    text: string | null
    media_url: string | null
    received_at: string | null
    sender_name: string | null
    sender_number: string | null
    /** Where it came in: 'whatsapp', or 'dashboard' for Tell Mesiri (WEB-36). */
    source?: string
  }[]
  readings: {
    provider: string | null
    model: string | null
    confidence: string | null
    extracted: Record<string, unknown>
    created_at: string | null
  }[]
  photos: { url: string | null; mime_type: string | null; caption: string | null }[]
  history: { state: string; note: string | null; at: string | null; by: string | null }[]
}

export async function fetchFactSourcesApi(factType: FactType, factId: string): Promise<FactSources> {
  const res = await api.get<FactSources>(`/dpr/facts/${factType}/${factId}/sources`)
  return res.data
}

/** Confirm one draft (BE-09). */
export async function confirmFactApi(factType: FactType, factId: string): Promise<void> {
  await api.post(`/dpr/facts/${factType}/${factId}/confirm`)
}

/** Remove one draft (BE-09): withdrawn through its own module's undo. */
export async function rejectFactApi(factType: FactType, factId: string, reason: string): Promise<void> {
  await api.post(`/dpr/facts/${factType}/${factId}/reject`, { reason })
}

// ---------------------------------------------------------------------------
// Automations -- user-defined recurring schedules (backend/src/mesiri/
// domains/automations/router.py). "Every day at 5pm send me the DPR", "at
// 3pm tell me who hasn't reported", "remind Ilan and Hysam" all become one
// of these rows; the scheduler (apps/whatsapp-assistant/src/runtime/
// automation_runner.py) fires them over WhatsApp. Run history (including
// *why* a recipient was skipped, e.g. outside the WhatsApp 24h session
// window) reads straight from the notifications queue -- see
// fetchAutomationRunsApi.
// ---------------------------------------------------------------------------

export type AutomationAction = 'SEND_DPR' | 'COMPLIANCE_SUMMARY' | 'REMINDER'
export type AutomationAudience = 'SELF' | 'USERS' | 'ROLE' | 'NON_REPORTERS'
export type AutomationFrequency = 'DAILY' | 'WEEKDAYS' | 'WEEKLY'

export interface AutomationItem {
  id: string
  project_id: string | null
  site_id: string | null
  action: AutomationAction
  audience: AutomationAudience
  audience_user_ids: string[]
  audience_role: string | null
  message: string | null
  frequency: AutomationFrequency
  day_of_week: number | null
  time_of_day: string
  timezone: string
  enabled: boolean
  last_run_on: string | null
  created_at: string | null
}

export interface AutomationPayload {
  project_id?: string | null
  site_id?: string | null
  action: AutomationAction
  audience: AutomationAudience
  audience_user_ids?: string[] | null
  audience_role?: string | null
  message?: string | null
  frequency?: AutomationFrequency
  day_of_week?: number | null
  time_of_day: string
  timezone?: string
}

export interface AutomationRun {
  id: string
  recipient_name: string | null
  occurred_on: string
  status: string
  skip_reason: string | null
  sent_at: string | null
  created_at: string
}

export async function fetchAutomationsApi(): Promise<AutomationItem[]> {
  const res = await api.get<{ items: AutomationItem[] }>('/automations')
  return res.data.items
}

export async function createAutomationApi(payload: AutomationPayload): Promise<AutomationItem> {
  const res = await api.post<AutomationItem>('/automations', payload)
  return res.data
}

export async function updateAutomationApi(
  automationId: string,
  payload: Partial<AutomationPayload> & { enabled?: boolean }
): Promise<AutomationItem> {
  const res = await api.patch<AutomationItem>(`/automations/${automationId}`, payload)
  return res.data
}

export async function deleteAutomationApi(automationId: string): Promise<void> {
  await api.delete(`/automations/${automationId}`)
}

export async function fetchAutomationRunsApi(automationId: string): Promise<AutomationRun[]> {
  const res = await api.get<{ items: AutomationRun[] }>(`/automations/${automationId}/runs`)
  return res.data.items
}



// Getting-started checklist (SS-07): backend/src/mesiri/domains/organizations/setup_router.py.
// Every item is worked out from what already happened; nothing is ticked by hand.
export interface SetupProgress {
  has_team: boolean
  has_site: boolean
  has_logo: boolean
  report_time_set: boolean
  first_update_at: string | null
  first_dpr_sent_at: string | null
  first_project: { id: string; name: string; send_time: string; auto_dpr?: boolean } | null
  effective_status: string
  trial_days_left: number | null
  /** Mesiri's own WhatsApp number, for inviting people to send updates (SS-18). */
  whatsapp_number?: string | null
  /** "Hide for now", for the whole company until then (SS-19); null: showing. */
  hidden_until?: string | null
}

export async function fetchSetupProgress(): Promise<SetupProgress> {
  const res = await api.get<SetupProgress>('/company/setup-progress')
  return res.data
}

/** "The default report time is fine": the one item the data can't show.
 * Answers the WhatsApp setup question too (SS-14), so it isn't asked again. */
export async function confirmReportTime(): Promise<SetupProgress> {
  const res = await api.post<SetupProgress>('/company/setup-progress/report-time-ok')
  return res.data
}

/** Hide the getting-started card for the company for a week (SS-19). */
export async function hideSetupCard(): Promise<SetupProgress> {
  const res = await api.post<SetupProgress>('/company/setup-progress/hide')
  return res.data
}

/** Bring it back (the sidebar's "Finish setup"). */
export async function showSetupCard(): Promise<SetupProgress> {
  const res = await api.post<SetupProgress>('/company/setup-progress/show')
  return res.data
}

/** "Continue with Mesiri" after (or near the end of) the free trial (SS-08):
 * apps/whatsapp-assistant/src/trial/router.py. Owners only. */
export async function requestContinue(): Promise<{ requested: boolean; already_requested: boolean }> {
  const res = await api.post('/company/trial/continue')
  return res.data
}

// ─── Analytics (WEB-24) ──────────────────────────────────────────────────────

export interface AnalyticsDay {
  day: string
  workers: number
  work_items: number
  photos: number
  issues: number
  delay_minutes: number
}

export interface AnalyticsSummary {
  date_from: string
  date_to: string
  days: AnalyticsDay[]
  /** Open (or acknowledged) issues now, by type and severity. */
  open_issues: { issue_type: string; severity: string; count: number }[]
  /** Each active site: days it sent anything, days its site DPR was confirmed. */
  sites: { site_id: string; site_name: string; project_name: string; days_with_updates: number; days_confirmed: number }[]
}

/** GET /dpr/analytics: aggregated over the whole range in SQL. */
export async function fetchAnalyticsApi(params: {
  dateFrom: string
  dateTo: string
  projectId?: string
  siteId?: string
}): Promise<AnalyticsSummary> {
  const res = await api.get<AnalyticsSummary>('/dpr/analytics', {
    params: { date_from: params.dateFrom, date_to: params.dateTo, project_id: params.projectId, site_id: params.siteId },
  })
  return res.data
}

// ─── The DPR as a document, live (WEB-27) ────────────────────────────────────

/** The site DPR as the PDF will look (HTML), from the day as it stands now. */
export async function fetchSiteDayDocumentApi(siteId: string, date: string): Promise<string> {
  const res = await api.get<string>(`/dpr/site-days/${siteId}/document`, { params: { date }, responseType: 'text' })
  return res.data
}

/** The project DPR as a document: as sent once it has gone out, else a preview. */
export async function fetchProjectDayDocumentApi(projectId: string, date: string): Promise<string> {
  const res = await api.get<string>(`/dpr/project-days/${projectId}/document`, { params: { date }, responseType: 'text' })
  return res.data
}

// ─── Tell Mesiri from the dashboard (WEB-36) ─────────────────────────────────
// apps/whatsapp-assistant/src/web_assistant/router.py: the same handler as a
// WhatsApp message, as the signed-in user; Mesiri's replies come back here.

export interface AssistantReplyOption {
  id: string
  title: string
  description?: string | null
}

export interface AssistantReply {
  type: 'text' | 'buttons' | 'list'
  text: string
  buttons: AssistantReplyOption[]
  list_rows: AssistantReplyOption[]
  button_label?: string | null
}

export interface AssistantResponse {
  message_id: string
  replies: AssistantReply[]
  /** A voice note's words, as Mesiri heard them. */
  transcript: string | null
}

/** Mesiri can take up to a minute (voice + model); the request waits for it. */
const ASSISTANT_TIMEOUT_MS = 90_000

export async function sendToMesiri(body: { text?: string; interactive_reply_id?: string }): Promise<AssistantResponse> {
  const res = await api.post<AssistantResponse>('/assistant/messages', body, { timeout: ASSISTANT_TIMEOUT_MS })
  return res.data
}

export async function sendVoiceToMesiri(audio: Blob): Promise<AssistantResponse> {
  const res = await api.post<AssistantResponse>('/assistant/messages/voice', audio, {
    headers: { 'Content-Type': 'audio/ogg' },
    timeout: ASSISTANT_TIMEOUT_MS,
  })
  return res.data
}

