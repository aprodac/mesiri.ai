// SA-20: the Overview's charts, plain SVG -- a sparkline for each KPI and a
// smooth area chart for the 14-day activity, with a crosshair that snaps to
// the nearest day. Monotone curves, so a line never dips below zero or
// overshoots between two days.

import { useLayoutEffect, useRef, useState } from 'react';

const INK = '#1C1917';

/** Monotone cubic path through the points (Fritsch–Carlson), as d3's curveMonotoneX. */
function smoothPath(pts: [number, number][]): string {
  const n = pts.length;
  if (n === 0) return '';
  if (n === 1) return `M${pts[0][0]},${pts[0][1]}`;
  const dx: number[] = [];
  const slope: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(pts[i + 1][0] - pts[i][0]);
    slope.push((pts[i + 1][1] - pts[i][1]) / (dx[i] || 1));
  }
  const t: number[] = [slope[0]];
  for (let i = 1; i < n - 1; i++) t.push(slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2);
  t.push(slope[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (slope[i] === 0) {
      t[i] = 0;
      t[i + 1] = 0;
      continue;
    }
    const a = t[i] / slope[i];
    const b = t[i + 1] / slope[i];
    const h = a * a + b * b;
    if (h > 9) {
      const k = 3 / Math.sqrt(h);
      t[i] = k * a * slope[i];
      t[i + 1] = k * b * slope[i];
    }
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const c = dx[i] / 3;
    d += `C${(pts[i][0] + c).toFixed(1)},${(pts[i][1] + c * t[i]).toFixed(1)} ${(pts[i + 1][0] - c).toFixed(1)},${(pts[i + 1][1] - c * t[i + 1]).toFixed(1)} ${pts[i + 1][0].toFixed(1)},${pts[i + 1][1].toFixed(1)}`;
  }
  return d;
}

function niceMax(max: number): number {
  if (max <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(max));
  return [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= max) ?? max;
}

function useSize<T extends HTMLElement>(): [React.RefObject<T | null>, number, number] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.floor(e.contentRect.width), h: Math.floor(e.contentRect.height) }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size.w, size.h];
}

let gradientId = 0;

/** A small trend line with a soft wash; the last point is today. */
export function Sparkline({ values, width = 84, height = 30, color = INK }: { values: number[]; width?: number; height?: number; color?: string }) {
  const [id] = useState(() => `spark-${++gradientId}`);
  if (values.length < 2) return null;
  const max = Math.max(...values, 0) || 1;
  const pts: [number, number][] = values.map((v, i) => [(i / (values.length - 1)) * (width - 4) + 2, height - 3 - (v / max) * (height - 8)]);
  const line = smoothPath(pts);
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true" style={{ display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.14" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line}L${last[0]},${height}L${pts[0][0]},${height}Z`} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      <circle cx={last[0]} cy={last[1]} r={2.5} fill={color} />
    </svg>
  );
}

/** The 14-day chart: fills its container, crosshair + tooltip on hover. */
export function AreaChart({ labels, values, format }: { labels: string[]; values: number[]; format: (v: number) => string }) {
  const [ref, w, h] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [id] = useState(() => `area-${++gradientId}`);
  const pad = { top: 10, right: 12, bottom: 26, left: 44 };
  const n = values.length;
  const top = niceMax(Math.max(0, ...values));
  const plotW = Math.max(1, w - pad.left - pad.right);
  const plotH = Math.max(1, h - pad.top - pad.bottom);
  const x = (i: number) => pad.left + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) => pad.top + (1 - v / top) * plotH;
  const pts: [number, number][] = values.map((v, i) => [x(i), y(v)]);
  const line = smoothPath(pts);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
  // About one date label per 64px, whatever the width.
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(plotW / 64))));
  const empty = values.every((v) => !v);

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - box.left) / Math.max(1, box.width);
    setHover(Math.min(n - 1, Math.max(0, Math.round(rel * (n - 1)))));
  };

  return (
    <div ref={ref} className="ac-wrap">
      {w > 0 && h > 0 && (
        <svg width={w} height={h} role="img" aria-label="Activity over the last 14 days">
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={INK} stopOpacity="0.12" />
              <stop offset="1" stopColor={INK} stopOpacity="0" />
            </linearGradient>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.left} x2={w - pad.right} y1={y(t)} y2={y(t)} stroke="#F0EEEB" strokeWidth={1} />
              <text x={pad.left - 10} y={y(t)} dy="0.32em" textAnchor="end" className="ac-tick">
                {format(t)}
              </text>
            </g>
          ))}
          {labels.map((l, i) =>
            (i % every === 0 && n - 1 - i >= every) || i === n - 1 ? (
              <text key={i} x={x(i)} y={h - 6} textAnchor={i === n - 1 ? 'end' : 'middle'} className="ac-tick">
                {i === n - 1 ? 'Today' : l}
              </text>
            ) : null,
          )}
          {!empty && (
            <>
              <path d={`${line}L${x(n - 1)},${y(0)}L${x(0)},${y(0)}Z`} fill={`url(#${id})`} />
              <path d={line} fill="none" stroke={INK} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
              <circle cx={x(n - 1)} cy={y(values[n - 1])} r={4} fill={INK} stroke="#fff" strokeWidth={2} />
            </>
          )}
          {hover !== null && !empty && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={pad.top + plotH} stroke="#D6D3D1" strokeWidth={1} />
              <circle cx={x(hover)} cy={y(values[hover])} r={4.5} fill={INK} stroke="#fff" strokeWidth={2} />
            </g>
          )}
          <rect x={pad.left} y={pad.top} width={plotW} height={plotH} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
        </svg>
      )}
      {empty && w > 0 && <div className="ac-empty">Nothing in the last 14 days yet.</div>}
      {hover !== null && !empty && (
        <div className="ac-tip" style={{ left: Math.min(Math.max(x(hover), 70), w - 70), top: Math.max(0, y(values[hover]) - 54) }}>
          <strong>{format(values[hover])}</strong>
          <span>{hover === n - 1 ? 'Today' : labels[hover]}</span>
        </div>
      )}
    </div>
  );
}
