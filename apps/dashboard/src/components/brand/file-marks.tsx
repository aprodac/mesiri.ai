// UX-15: file kinds people know by sight. A spreadsheet is a filled sheet with a grid (green on the button that
// carries it: Import from Excel, Excel / CSV export); a PDF is a page with its corner folded and "PDF" on it. Drawn in
// `currentColor`, the grid and letters in the page's ground, so both stay readable in light and dark.

export function SheetMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className}>
      <rect x="3" y="3" width="18" height="18" rx="3" fill="currentColor" />
      <path d="M3 9.5h18M3 15h18M9.5 9.5V21" stroke="var(--background)" strokeWidth="1.6" fill="none" />
    </svg>
  )
}

export function PdfMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className}>
      <path d="M6 2h8.5L20 7.5V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z" fill="currentColor" />
      <path d="M14.5 2v5.5H20" fill="none" stroke="var(--background)" strokeWidth="1.4" />
      <path d="M7.5 17.5v-5h1.6a1.5 1.5 0 0 1 0 3H7.5M12 17.5v-5h1.2a2.5 2.5 0 0 1 0 5Zm5 0v-5h2.3M17 15h1.8" fill="none" stroke="var(--background)" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
