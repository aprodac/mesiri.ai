/** PRC-34: GST on a rate (see components/procurement/gst-field.tsx and backend domains/procurement/gst.py). */

export const GST_SLABS = ['0', '5', '12', '18', '28'] as const

export interface GstValue {
  percent: string | null
  includes: boolean | null
}

export const GST_NOT_SAID: GstValue = { percent: null, includes: null }

/** The fields for the API: nothing when not said, so the backend keeps NULL ("not known"), never a guess. */
export function gstPayload(v: GstValue): { gst_percent?: string; rate_includes_gst?: boolean } {
  if (v.percent === null) return {}
  if (Number(v.percent) === 0) return { gst_percent: '0' }
  return v.includes === null ? { gst_percent: v.percent } : { gst_percent: v.percent, rate_includes_gst: v.includes }
}

/** With and before GST, for a rate as entered; null when it cannot be worked out. */
export function gstSplit(rate: string | number, v: GstValue): { before: number; gst: number; withGst: number } | null {
  const r = Number(rate)
  if (!rate || Number.isNaN(r) || v.percent === null) return null
  const pct = Number(v.percent)
  if (pct === 0) return { before: r, gst: 0, withGst: r }
  if (v.includes === null) return null
  const before = v.includes ? r / (1 + pct / 100) : r
  const withGst = v.includes ? r : r * (1 + pct / 100)
  return { before, gst: withGst - before, withGst }
}
