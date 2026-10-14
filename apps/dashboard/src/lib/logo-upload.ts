// Shared by the company logo (Company -> Letterhead) and project client logo
// (Project -> Settings) uploads. Mirrors the server's rules in
// backend/src/mesiri/domains/organizations/branding.py, so a bad file is
// caught before it is sent; the server checks again.

export const LOGO_TYPES = ['image/png', 'image/jpeg', 'image/webp']
export const LOGO_MAX_BYTES = 700 * 1024

/** A message to show for a file the server would refuse, or null if it looks fine. */
export function logoFileProblem(file: File): string | null {
  if (!LOGO_TYPES.includes(file.type)) return 'Use a PNG, JPEG or WebP image.'
  if (file.size > LOGO_MAX_BYTES) return 'The logo must be 700 KB or smaller.'
  return null
}

export function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '')
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

/** The server's own message (FastAPI `detail`) when there is one. */
export function apiErrorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  return err instanceof Error ? err.message : 'Something went wrong.'
}
