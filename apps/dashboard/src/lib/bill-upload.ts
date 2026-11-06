// WEB-65: a bill added to an expense from the dashboard. The server takes a photo (JPEG, PNG, WebP) or a PDF up to
// 700 KB (backend/src/mesiri/domains/expenses/bill_file.py: base64 in JSON under nginx's 1 MB body). A phone photo is
// several MB, so a photo is shrunk here to a JPEG first, still easy to read; a PDF is sent as it is.

import { readAsBase64 } from '@/lib/logo-upload'

export const BILL_MAX_BYTES = 700 * 1024
export const BILL_ACCEPT = 'image/*,application/pdf'

export interface BillFile {
  content_type: string
  data_base64: string
}

async function shrink(file: File, longEdge: number, quality: number): Promise<Blob> {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, longEdge / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('This browser cannot read the photo.')
  ctx.fillStyle = '#fff' // a transparent PNG becomes a white page, not black
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close()
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('The photo could not be read.'))), 'image/jpeg', quality),
  )
}

/** The file as the server takes it; an Error with a message to show when it cannot be sent. */
export async function billFile(file: File): Promise<BillFile> {
  if (file.type === 'application/pdf') {
    if (file.size > BILL_MAX_BYTES) throw new Error('This PDF is over 700 KB. Add a photo of the bill instead.')
    return { content_type: file.type, data_base64: await readAsBase64(file) }
  }
  if (!file.type.startsWith('image/')) throw new Error('Choose a photo or a PDF of the bill.')
  let blob: Blob | null = null
  for (const [edge, quality] of [[2000, 0.82], [1600, 0.75], [1200, 0.65]] as const) {
    blob = await shrink(file, edge, quality)
    if (blob.size <= BILL_MAX_BYTES) break
  }
  if (!blob || blob.size > BILL_MAX_BYTES) throw new Error('This photo is too big to send. Try another one.')
  return { content_type: 'image/jpeg', data_base64: await readAsBase64(new File([blob], 'bill.jpg', { type: 'image/jpeg' })) }
}
