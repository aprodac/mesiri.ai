/**
 * QA-04 step 2: several sites typed at once. One name per line or comma; "Villa 1-4" (or "Villa 1 to 4") is Villa 1,
 * Villa 2, Villa 3, Villa 4. A name that only looks like a range ("Block 2-B") stays as typed. Repeats (any case or
 * spacing) are kept once, in order. The server still refuses a name the project already has (application/projects/
 * site_names.py); `sameSiteName` is the same comparison, so the preview can say so first.
 */

/** More sites in one go than a real project needs: "Villa 1-400" is a typo, not 400 sites. */
export const MAX_SITES_AT_ONCE = 50

export function sameSiteName(name: string | null | undefined): string {
  return String(name ?? '').normalize('NFKC').toLocaleLowerCase().split(/\s+/).filter(Boolean).join(' ')
}

const RANGE = /^(.*?)(\d+)\s*(?:-|–|to)\s*(\d+)$/i

export function expandSiteNames(text: string): { names: string[]; tooMany: boolean } {
  const names: string[] = []
  const seen = new Set<string>()
  let tooMany = false
  for (const raw of String(text ?? '').split(/[\n,;]+/)) {
    const part = raw.split(/\s+/).filter(Boolean).join(' ')
    if (!part) continue
    let expanded = [part]
    const m = RANGE.exec(part)
    if (m) {
      const start = Number(m[2])
      const end = Number(m[3])
      if (start < end) {
        if (end - start + 1 > MAX_SITES_AT_ONCE) tooMany = true
        else expanded = Array.from({ length: end - start + 1 }, (_, i) => `${m[1]}${start + i}`.trim())
      }
    }
    for (const name of expanded) {
      const key = sameSiteName(name)
      if (key && !seen.has(key)) {
        seen.add(key)
        names.push(name)
      }
    }
  }
  return { names, tooMany }
}
