// V1 audit DSH-03: a time zone is picked from the real list, India first.
// Free text let "IST" or "India" through, and those were read as UTC.

const COMMON = ['Asia/Kolkata', 'Asia/Dubai', 'UTC']

function allZones(): string[] {
  try {
    return Intl.supportedValuesOf('timeZone')
  } catch {
    return []
  }
}

interface TimezoneSelectProps {
  id?: string
  name?: string
  value: string
  onChange: (value: string) => void
  className?: string
}

export function TimezoneSelect({ id, name, value, onChange, className }: TimezoneSelectProps) {
  const rest = allZones().filter((z) => !COMMON.includes(z))
  const known = COMMON.includes(value) || rest.includes(value)
  return (
    <select
      id={id}
      name={name}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      required
      className={className ?? 'h-9 rounded border border-input bg-background px-2 text-xs'}
    >
      {!known && value && <option value={value}>{value} (not a time zone, choose one)</option>}
      <option value="Asia/Kolkata">Asia/Kolkata (India)</option>
      <option value="Asia/Dubai">Asia/Dubai</option>
      <option value="UTC">UTC</option>
      {rest.length > 0 && <option disabled>──────────</option>}
      {rest.map((z) => (
        <option key={z} value={z}>
          {z}
        </option>
      ))}
    </select>
  )
}
