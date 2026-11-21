import { Platform } from 'react-native'
import { getSecret, setSecret } from './storage'

// The same API the dashboard uses (production: https://api.whatsapp.mesiri.ai). Every call acts as the
// signed-in person, so roles, sites and module switches are the API's, never the app's.

export const API_URL = (process.env.EXPO_PUBLIC_API_URL || 'https://api.whatsapp.mesiri.ai').replace(/\/$/, '')
const TOKEN_KEY = 'mesiri_access_token'
/** Tells the assistant's door the message came from the app (MOB-03). */
const CLIENT = { 'X-Mesiri-Client': 'app' }

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

let token: string | null = null
let onSignedOut: (() => void) | null = null

export async function loadToken(): Promise<string | null> {
  token = await getSecret(TOKEN_KEY)
  return token
}

export async function saveToken(value: string | null): Promise<void> {
  token = value
  await setSecret(TOKEN_KEY, value)
}

/** Called when the API says the sign-in is no longer good (401). */
export function whenSignedOut(callback: () => void): void {
  onSignedOut = callback
}

function detailOf(body: unknown): string | null {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0] && typeof detail[0].msg === 'string') return detail[0].msg
    // A refusal with a reason the person can act on ("more than ordered"): its message.
    if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') {
      return (detail as { message: string }).message
    }
  }
  return null
}

type Query = Record<string, string | number | boolean | null | undefined>

function withQuery(path: string, query?: Query): string {
  if (!query) return path
  const parts = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  return parts.length ? `${path}?${parts.join('&')}` : path
}

export async function request<T>(
  method: string,
  path: string,
  options: {
    query?: Query
    json?: unknown
    body?: BodyInit
    contentType?: string
    timeoutMs?: number
    headers?: Record<string, string>
  } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...CLIENT, ...(options.headers ?? {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined = options.body
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  } else if (options.contentType) {
    headers['Content-Type'] = options.contentType
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 20_000)
  let res: Response
  try {
    res = await fetch(`${API_URL}${withQuery(path, options.query)}`, { method, headers, body, signal: controller.signal })
  } catch {
    throw new ApiError('No connection to Mesiri. Check the signal and try again.', 0)
  } finally {
    clearTimeout(timer)
  }
  const text = await res.text()
  let parsed: unknown = null
  try {
    parsed = text ? JSON.parse(text) : null
  } catch {
    parsed = null
  }
  if (!res.ok) {
    if (res.status === 401 && token && !path.startsWith('/auth/')) {
      await saveToken(null)
      onSignedOut?.()
    }
    throw new ApiError(detailOf(parsed) ?? 'Something went wrong. Try again.', res.status)
  }
  return parsed as T
}

export const get = <T>(path: string, query?: Query) => request<T>('GET', path, { query })
export const post = <T>(path: string, json?: unknown, timeoutMs?: number) =>
  request<T>('POST', path, { json: json ?? {}, timeoutMs })
export const patch = <T>(path: string, json: unknown, query?: Query) => request<T>('PATCH', path, { json, query })

/** A file the phone recorded, as bytes for a request body. */
export async function fileBody(uri: string): Promise<Blob> {
  const res = await fetch(uri)
  return res.blob()
}

export const isWeb = Platform.OS === 'web'
