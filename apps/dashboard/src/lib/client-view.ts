import axios from 'axios'
import { api } from './api'

// CV-01..CV-03: the client sees their project from a secret link. Backend: domains/client_view/router.py.
// Links are made by the owner, admins and finance (the bills are on the page). The token is returned once.

export interface ClientLink {
  id: string
  project_id: string
  project_name: string
  label: string | null
  created_at: string
  created_by_name: string | null
  revoked_at: string | null
  last_opened_at: string | null
  open_count: number
}

export async function fetchClientLinks(projectId?: string | null): Promise<ClientLink[]> {
  const url = projectId ? `/projects/${projectId}/client-links` : '/client-links'
  return (await api.get<{ links?: ClientLink[] }>(url)).data?.links ?? []
}

export async function createClientLink(projectId: string, label: string | null): Promise<{ link: ClientLink; token: string }> {
  return (await api.post(`/projects/${projectId}/client-links`, { label })).data
}

export async function revokeClientLink(id: string): Promise<ClientLink> {
  return (await api.post<{ link: ClientLink }>(`/client-links/${id}/revoke`)).data.link
}

/** The address the client opens: this dashboard's own origin, so it works wherever the dashboard is served. */
export function clientLinkUrl(token: string): string {
  return `${window.location.origin}/c/${token}`
}

/** A WhatsApp message with the link, ready to send (wa.me opens WhatsApp with the text filled in). */
export function whatsappShareUrl(token: string, projectName: string, company?: string | null): string {
  const text = `Your project ${projectName}: progress, photos and bills${company ? ` from ${company}` : ''}. Open: ${clientLinkUrl(token)}`
  return `https://wa.me/?text=${encodeURIComponent(text)}`
}

// -- The client's page (no login) --------------------------------------------------------------------------------

export interface ClientPage {
  company: { name: string | null; phone: string | null; brand_color: string | null; logo_url: string | null }
  project: {
    name: string
    stage: string | null
    start_date: string | null
    contract_finish: string | null
    forecast_finish: string | null
    slip_days: number
    progress: number | null
    contract_value: string | null
    client_name: string | null
  }
  today: string
  schedule: {
    name: string
    milestone: boolean
    start: string | null
    end: string | null
    actual_start: string | null
    actual_end: string | null
    done: boolean
    progress: number | null
    state: string
    forecast_end: string | null
  }[]
  schedule_kind: 'milestones' | 'activities'
  photos: { url: string; caption: string | null; date: string; work: string | null }[]
  bills: {
    ref: string
    bill_date: string
    period_to: string | null
    status: 'submitted' | 'certified'
    gross: string | null
    retention: string | null
    advance_recovery: string | null
    gst: string | null
    tds: string | null
    net: string | null
    certified_amount: string | null
    certified_on: string | null
    received: string | null
    left: string | null
  }[]
  payments: { received_on: string; amount: string; kind: 'bill' | 'on_account' | 'advance'; bill_ref: string | null }[]
  totals: { billed: string; received: string; due: string; advance_received: string }
}

// Its own client: never sends a signed-in user's token, and a 401/403 must not log anyone out.
const publicApi = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000' })

export async function fetchClientPage(token: string): Promise<ClientPage> {
  return (await publicApi.get<ClientPage>(`/client/${encodeURIComponent(token)}`)).data
}
