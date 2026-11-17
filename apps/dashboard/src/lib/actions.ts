import type * as React from 'react'
import {
  ArrowRight, Ban, Banknote, Receipt, CalendarClock, Camera, Check, Copy, Download, Eye, Filter, MessageSquareText, Pencil, Phone, Plus, Printer,
  RefreshCw, Send, Settings, Share2, Sparkles, Trash2, Undo2, Upload, X,
} from 'lucide-react'
import { PdfMark, SheetMark } from '@/components/brand/file-marks'
import { WhatsAppIcon } from '@/components/brand/whatsapp-icon'

// UX-15 (asked by Ilan 17 Nov 2026: "the Import from Excel button can look like an Excel icon or green"): what each
// kind of action looks like, in one table, so the same action looks the same on every page and a button is known
// before it is read. `ActionButton`, `ActionIcon` and `ActionMenuItem` (components/page/action-button.tsx) draw from
// it. Colour stays meaning (docs/DESIGN.md section 3) and sits on the icon only, never as a second filled button:
//   - sheet (green): a spreadsheet goes in or out; WhatsApp (green): it goes to WhatsApp;
//   - danger (red): it removes or refuses; good (green): it approves or confirms; ai (indigo): Mesiri does it;
//   - plain: everything else, known by its shape.
// A new kind of action is one line here.

export type ActionTone = 'plain' | 'sheet' | 'whatsapp' | 'danger' | 'good' | 'ai'

export type ActionKind =
  | 'import-excel' | 'export-excel' | 'pdf' | 'print' | 'whatsapp' | 'add' | 'edit' | 'delete' | 'approve' | 'reject'
  | 'send' | 'download' | 'upload' | 'schedule' | 'refresh' | 'undo' | 'share' | 'copy' | 'view' | 'filter' | 'photo'
  | 'call' | 'settings' | 'ai' | 'message' | 'next' | 'cancel' | 'pay' | 'bill'

export const ACTION_LOOK: Record<ActionKind, { icon: React.ComponentType<{ className?: string }>; tone: ActionTone; label: string }> = {
  'import-excel': { icon: SheetMark, tone: 'sheet', label: 'Import from Excel' },
  'export-excel': { icon: SheetMark, tone: 'sheet', label: 'Export to Excel' },
  pdf: { icon: PdfMark, tone: 'plain', label: 'PDF' },
  print: { icon: Printer, tone: 'plain', label: 'Print' },
  whatsapp: { icon: WhatsAppIcon, tone: 'whatsapp', label: 'Send on WhatsApp' },
  add: { icon: Plus, tone: 'plain', label: 'Add' },
  edit: { icon: Pencil, tone: 'plain', label: 'Edit' },
  delete: { icon: Trash2, tone: 'danger', label: 'Remove' },
  approve: { icon: Check, tone: 'good', label: 'Approve' },
  reject: { icon: Ban, tone: 'danger', label: 'Reject' },
  send: { icon: Send, tone: 'plain', label: 'Send' },
  download: { icon: Download, tone: 'plain', label: 'Download' },
  upload: { icon: Upload, tone: 'plain', label: 'Upload' },
  schedule: { icon: CalendarClock, tone: 'plain', label: 'Schedule' },
  refresh: { icon: RefreshCw, tone: 'plain', label: 'Refresh' },
  undo: { icon: Undo2, tone: 'danger', label: 'Take back' },
  share: { icon: Share2, tone: 'plain', label: 'Share' },
  copy: { icon: Copy, tone: 'plain', label: 'Copy' },
  view: { icon: Eye, tone: 'plain', label: 'View' },
  filter: { icon: Filter, tone: 'plain', label: 'Filter' },
  photo: { icon: Camera, tone: 'plain', label: 'Photo' },
  call: { icon: Phone, tone: 'plain', label: 'Call' },
  settings: { icon: Settings, tone: 'plain', label: 'Settings' },
  ai: { icon: Sparkles, tone: 'ai', label: 'Ask Mesiri' },
  message: { icon: MessageSquareText, tone: 'plain', label: 'Message' },
  next: { icon: ArrowRight, tone: 'plain', label: 'Open' },
  cancel: { icon: X, tone: 'plain', label: 'Cancel' },
  pay: { icon: Banknote, tone: 'plain', label: 'Mark paid' },
  bill: { icon: Receipt, tone: 'plain', label: 'Bill' },
}

/** The icon's colour for each tone: tokens only (index.css), so dark mode follows. */
export const ACTION_TONE_ICON: Record<ActionTone, string> = {
  plain: '',
  sheet: 'text-success',
  whatsapp: 'text-success',
  danger: 'text-destructive',
  good: 'text-success',
  ai: 'text-ai',
}
