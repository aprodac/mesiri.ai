// SA-17: the Reply Insights page's charts, drawn as plain SVG (the control
// panel has no chart library): a line chart with a crosshair tooltip (reply
// time over time), stacked columns (tokens over time) and horizontal bars
// (reply-speed bands). One y-axis each; legends for two or more series.

import { useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

const GRID = 'var(--neutral-200)';
const AXIS_TEXT = 'var(--neutral-500)';
const PAD = { top: 12, right: 16, bottom: 28, left: 56 };
const HEIGHT = 220;
const FIXED_HEIGHT = HEIGHT;

export interface Series {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
}

/** The container's size, kept current, so text stays crisp (no viewBox scaling). */
function useSize<T extends HTMLElement>(): [React.RefObject<T | null>, number, number] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: Math.floor(entry.contentRect.width), height: Math.floor(entry.contentRect.height) }),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size.width, size.height];
}

/** Clean, rounded y ticks from 0 to just above `max`. */
function ticks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) out.push(v);
  if (out[out.length - 1] < max) out.push(out[out.length - 1] + step);
  return out;
}

/** About six evenly spaced x labels, whatever the point count. */
function labelEvery(n: number): number {
  return Math.max(1, Math.ceil(n / 6));
}

/** Keys mirror the mark: a short line for line charts, a swatch for bars. */
export function Legend({ series, line }: { series: Pick<Series, 'key' | 'label' | 'color'>[]; line?: boolean }) {
  return (
    <div style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap', fontSize: '12px', color: 'var(--neutral-600)' }}>
      {series.map((s) => (
        <span key={s.key} style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
          <span style={line ? { width: 14, height: 2, borderRadius: 1, background: s.color } : { width: 10, height: 10, borderRadius: 3, background: s.color }} />
          {s.label}
        </span>
      ))}
    </div>
  );
}

function Tooltip({ x, width, children }: { x: number; width: number; children: ReactNode }) {
  const flip = x > width - 190;
  return (
    <div
      role="status"
      style={{
        position: 'absolute',
        top: PAD.top,
        left: flip ? undefined : x + 12,
        right: flip ? width - x + 12 : undefined,
        background: 'var(--surface-primary)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-sm)',
        boxShadow: 'var(--shadow-3)',
        padding: '8px 10px',
        fontSize: '12px',
        pointerEvents: 'none',
        minWidth: 150,
        zIndex: 2,
      }}
    >
      {children}
    </div>
  );
}

function TipRow({ color, label, value, line }: { color: string; label: string; value: string; line?: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
      <span
        style={
          line
            ? { width: 12, height: 2, borderRadius: 1, background: color }
            : { width: 8, height: 8, borderRadius: 2, background: color }
        }
      />
      <strong style={{ color: 'var(--neutral-900)', fontVariantNumeric: 'tabular-nums' }}>{value}</strong>
      <span style={{ color: 'var(--neutral-500)' }}>{label}</span>
    </div>
  );
}

function YAxis({ values, y, width, format }: { values: number[]; y: (v: number) => number; width: number; format: (v: number) => string }) {
  return (
    <g>
      {values.map((v) => (
        <g key={v}>
          <line x1={PAD.left} x2={width - PAD.right} y1={y(v)} y2={y(v)} stroke={GRID} strokeWidth={1} />
          <text x={PAD.left - 8} y={y(v)} dy="0.32em" textAnchor="end" fontSize={11} fill={AXIS_TEXT} style={{ fontVariantNumeric: 'tabular-nums' }}>
            {format(v)}
          </text>
        </g>
      ))}
    </g>
  );
}

function XLabels({ labels, x, height = HEIGHT }: { labels: string[]; x: (i: number) => number; height?: number }) {
  const every = labelEvery(labels.length);
  return (
    <g>
      {labels.map((l, i) =>
        i % every === 0 ? (
          <text key={i} x={x(i)} y={height - 8} textAnchor="middle" fontSize={11} fill={AXIS_TEXT}>
            {l}
          </text>
        ) : null,
      )}
    </g>
  );
}

/** Lines over time with a crosshair that snaps to the nearest point and
 *  lists every series there. Gaps (null) break the line. */
export function LineChart({
  series,
  labels,
  format,
  empty,
}: {
  series: Series[];
  labels: string[];
  format: (v: number) => string;
  empty: string;
}) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const n = labels.length;
  const max = Math.max(0, ...series.flatMap((s) => s.values.map((v) => v ?? 0)));
  const yTicks = ticks(max);
  const top = yTicks[yTicks.length - 1] || 1;
  const plotW = Math.max(1, width - PAD.left - PAD.right);
  const x = (i: number) => PAD.left + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) => PAD.top + (1 - v / top) * (HEIGHT - PAD.top - PAD.bottom);

  const path = (values: (number | null)[]) => {
    let d = '';
    let pen = false;
    values.forEach((v, i) => {
      if (v === null) {
        pen = false;
        return;
      }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - box.left) / Math.max(1, box.width);
    setHover(Math.min(n - 1, Math.max(0, Math.round(rel * (n - 1)))));
  };

  const hasData = series.some((s) => s.values.some((v) => v !== null));

  return (
    <div ref={ref} style={{ position: 'relative', height: HEIGHT }}>
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label={series.map((s) => s.label).join(' and ')}>
          <YAxis values={yTicks} y={y} width={width} format={format} />
          <XLabels labels={labels} x={x} />
          {series.map((s) => (
            <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {/* Lone points (a value with gaps both sides) get a dot so they show. */}
          {series.map((s) =>
            s.values.map((v, i) =>
              v !== null && (s.values[i - 1] ?? null) === null && (s.values[i + 1] ?? null) === null ? (
                <circle key={`${s.key}-${i}`} cx={x(i)} cy={y(v)} r={4} fill={s.color} stroke="var(--surface-primary)" strokeWidth={2} />
              ) : null,
            ),
          )}
          {hover !== null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke="var(--neutral-400)" strokeWidth={1} />
              {series.map((s) =>
                s.values[hover] !== null ? (
                  <circle key={s.key} cx={x(hover)} cy={y(s.values[hover] as number)} r={4.5} fill={s.color} stroke="var(--surface-primary)" strokeWidth={2} />
                ) : null,
              )}
            </g>
          )}
          <rect
            x={PAD.left}
            y={PAD.top}
            width={plotW}
            height={HEIGHT - PAD.top - PAD.bottom}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
          />
        </svg>
      )}
      {!hasData && width > 0 && (
        <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'var(--neutral-500)', fontSize: '13px' }}>
          {empty}
        </div>
      )}
      {hover !== null && hasData && (
        <Tooltip x={x(hover)} width={width}>
          <div style={{ color: 'var(--neutral-500)' }}>{labels[hover]}</div>
          {series.map((s) => (
            <TipRow key={s.key} line color={s.color} label={s.label} value={s.values[hover] === null ? '—' : format(s.values[hover] as number)} />
          ))}
        </Tooltip>
      )}
    </div>
  );
}

/** Stacked columns over time; each column is its own hover target. */
export function StackedColumns({
  series,
  labels,
  format,
  empty,
  fill,
}: {
  series: Series[];
  labels: string[];
  format: (v: number) => string;
  empty: string;
  /** Fill the container's height (it must have one) instead of the fixed 220px. */
  fill?: boolean;
}) {
  const [ref, width, measured] = useSize<HTMLDivElement>();
  const HEIGHT = fill ? Math.max(120, measured) : FIXED_HEIGHT;
  const [hover, setHover] = useState<number | null>(null);
  const n = labels.length;
  const totals = labels.map((_, i) => series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0));
  const yTicks = ticks(Math.max(0, ...totals));
  const top = yTicks[yTicks.length - 1] || 1;
  const plotW = Math.max(1, width - PAD.left - PAD.right);
  const slot = plotW / Math.max(1, n);
  const barW = Math.min(24, Math.max(2, slot - 4));
  const cx = (i: number) => PAD.left + slot * (i + 0.5);
  const y = (v: number) => PAD.top + (1 - v / top) * (HEIGHT - PAD.top - PAD.bottom);
  const hasData = totals.some((t) => t > 0);
  const GAP = 2;
  const R = 4;

  return (
    <div ref={ref} style={{ position: 'relative', height: fill ? '100%' : HEIGHT, minHeight: fill ? 120 : undefined }}>
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label={series.map((s) => s.label).join(', ')}>
          <YAxis values={yTicks} y={y} width={width} format={format} />
          <XLabels labels={labels} x={cx} height={HEIGHT} />
          {labels.map((_, i) => {
            let base = 0;
            const visible = series.filter((s) => (s.values[i] ?? 0) > 0);
            return (
              <g key={i} opacity={hover === null || hover === i ? 1 : 0.55}>
                {visible.map((s, k) => {
                  const v = s.values[i] ?? 0;
                  const y0 = y(base);
                  const y1 = y(base + v);
                  base += v;
                  const isTop = k === visible.length - 1;
                  // 2px surface gap between segments: trim the top of every lower one.
                  const h = Math.max(1, y0 - y1 - (isTop ? 0 : GAP));
                  const left = cx(i) - barW / 2;
                  const top0 = isTop ? y1 : y1 + GAP;
                  if (!isTop || h <= R) {
                    return <rect key={s.key} x={left} y={top0} width={barW} height={h} fill={s.color} />;
                  }
                  // Rounded data-end on top, square at the baseline.
                  const r = Math.min(R, barW / 2);
                  const d = `M${left},${top0 + h}V${top0 + r}Q${left},${top0} ${left + r},${top0}H${left + barW - r}Q${left + barW},${top0} ${left + barW},${top0 + r}V${top0 + h}Z`;
                  return <path key={s.key} d={d} fill={s.color} />;
                })}
                <rect
                  x={cx(i) - slot / 2}
                  y={PAD.top}
                  width={slot}
                  height={HEIGHT - PAD.top - PAD.bottom}
                  fill="transparent"
                  onPointerEnter={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                />
              </g>
            );
          })}
        </svg>
      )}
      {!hasData && width > 0 && (
        <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'var(--neutral-500)', fontSize: '13px' }}>
          {empty}
        </div>
      )}
      {hover !== null && hasData && (
        <Tooltip x={cx(hover)} width={width}>
          <div style={{ color: 'var(--neutral-500)' }}>{labels[hover]}</div>
          {[...series].reverse().map((s) => (
            <TipRow key={s.key} color={s.color} label={s.label} value={format(s.values[hover] ?? 0)} />
          ))}
          {series.length > 1 && (
            <div style={{ borderTop: '1px solid var(--border-default)', marginTop: 6, paddingTop: 4 }}>
              <strong style={{ fontVariantNumeric: 'tabular-nums' }}>{format(totals[hover])}</strong>{' '}
              <span style={{ color: 'var(--neutral-500)' }}>total</span>
            </div>
          )}
        </Tooltip>
      )}
    </div>
  );
}

/** One horizontal bar per band, in one hue, count and share at the tip. */
export function BandBars({ bands, color }: { bands: { label: string; count: number }[]; color: string }) {
  const total = bands.reduce((s, b) => s + b.count, 0);
  const max = Math.max(1, ...bands.map((b) => b.count));
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {bands.map((b) => {
        const pct = total ? Math.round((b.count / total) * 100) : 0;
        return (
          <div
            key={b.label}
            title={`${b.label}: ${b.count} replies (${pct}%)`}
            style={{ display: 'grid', gridTemplateColumns: '84px 1fr 92px', alignItems: 'center', gap: 10, fontSize: '13px' }}
          >
            <span style={{ color: 'var(--neutral-600)' }}>{b.label}</span>
            <div style={{ height: 14, background: 'var(--neutral-100)', borderRadius: 4 }}>
              <div
                style={{
                  width: `${(b.count / max) * 100}%`,
                  minWidth: b.count ? 3 : 0,
                  height: '100%',
                  background: color,
                  borderRadius: '0 4px 4px 0',
                  transition: 'width var(--transition-default)',
                }}
              />
            </div>
            <span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--neutral-800)' }}>
              {b.count.toLocaleString('en-IN')} <span style={{ color: 'var(--neutral-500)' }}>· {pct}%</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
