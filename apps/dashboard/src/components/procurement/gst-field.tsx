/**
 * PRC-34: GST on a rate, the same control on every form that takes a price (delivery, order line, bill).
 *
 * Chips for the usual slabs (or "Not said"), and once a slab above 0 is picked, whether the rate already includes
 * it. Under it, what the rate means: "₹400 + ₹72 GST = ₹472 a bag". The API keeps both facts beside the rate;
 * Rates compares suppliers on what a unit really costs (domains/procurement/gst.py).
 */
import { cn } from '@/lib/utils'
import { GST_NOT_SAID, GST_SLABS, gstSplit, type GstValue } from '@/lib/gst'

const inr = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

function Chip({ on, children, onClick, label }: { on: boolean; children: React.ReactNode; onClick: () => void; label?: string }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={label}
      onClick={onClick}
      className={cn(
        'h-7 rounded-full border px-2.5 text-[11px] font-semibold tabular-nums transition-colors',
        on ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-transparent text-muted-foreground hover:bg-muted',
      )}
    >
      {children}
    </button>
  )
}

export function GstField({
  value,
  onChange,
  rate,
  unit,
  compact = false,
}: {
  value: GstValue
  onChange: (v: GstValue) => void
  /** The rate as entered, to show what it means with and before GST. */
  rate?: string
  unit?: string
  compact?: boolean
}) {
  const pct = value.percent === null ? null : Number(value.percent)
  const split = rate ? gstSplit(rate, value) : null
  return (
    <div className="grid gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="GST">
        {!compact && <span className="mr-1 text-xs font-medium">GST</span>}
        <Chip on={value.percent === null} onClick={() => onChange(GST_NOT_SAID)}>
          Not said
        </Chip>
        {GST_SLABS.map((s) => (
          <Chip
            key={s}
            on={value.percent !== null && Number(value.percent) === Number(s)}
            label={`GST ${s}%`}
            onClick={() => onChange({ percent: s, includes: s === '0' ? null : value.includes ?? true })}
          >
            {s === '0' ? 'No GST' : `${s}%`}
          </Chip>
        ))}
      </div>
      {pct !== null && pct > 0 && (
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Rate includes GST">
          <Chip on={value.includes === true} onClick={() => onChange({ ...value, includes: true })}>
            Rate includes GST
          </Chip>
          <Chip on={value.includes === false} onClick={() => onChange({ ...value, includes: false })}>
            + GST on top
          </Chip>
        </div>
      )}
      {split && split.gst > 0 && (
        <p className="text-[11px] text-muted-foreground tabular-nums">
          {inr(split.before)} + {inr(split.gst)} GST = <span className="font-semibold text-foreground">{inr(split.withGst)}</span>
          {unit ? ` a ${unit}` : ''}
        </p>
      )}
    </div>
  )
}
