import * as React from 'react'
import { encode } from 'uqr'
import { cn } from '@/lib/utils'

/** A QR code for `value`, drawn as SVG squares (no markup injected). */
export function QrCode({ value, className, label }: { value: string; className?: string; label: string }) {
  const qr = React.useMemo(() => encode(value, { ecc: 'M', border: 2 }), [value])
  return (
    <svg
      viewBox={`0 0 ${qr.size} ${qr.size}`}
      shapeRendering="crispEdges"
      role="img"
      aria-label={label}
      className={cn('block bg-white', className)}
    >
      {qr.data.map((row, y) =>
        row.map((on, x) => (on ? <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill="#111111" /> : null)),
      )}
    </svg>
  )
}
