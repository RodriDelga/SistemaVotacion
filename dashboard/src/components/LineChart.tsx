import { useId, useState } from "react";
import { formatClock, formatPercent } from "../lib/format";

export interface LinePoint { label: string; value: number; detail?: string; timestamp?: string }
interface ProjectionPoint extends LinePoint { low: number; high: number }

const W = 640, H = 270, L = 44, R = 14, T = 12, B = 30;

/** Linea acumulada 0-100 % con area degradada; sin dependencias. */
export function LineChart({ points, ariaLabel, projection = [], timeRange }: {
  points: LinePoint[];
  ariaLabel: string;
  projection?: ProjectionPoint[];
  timeRange?: [string, string];
}) {
  const gradient = useId();
  const [hover, setHover] = useState<number | null>(null);
  const innerW = W - L - R, innerH = H - T - B;
  const [start, end] = timeRange?.map(Date.parse) ?? [0, 0];
  const x = (point: LinePoint, index: number) => L + innerW * (
    point.timestamp && end > start ? Math.max(0, Math.min(1, (Date.parse(point.timestamp) - start) / (end - start)))
      : points.length <= 1 ? 0.5 : index / (points.length - 1)
  );
  const y = (v: number) => T + innerH - (Math.max(0, Math.min(100, v)) / 100) * innerH;
  const line = (series: LinePoint[]) => series.map((p, i) => `${i ? "L" : "M"}${x(p, i).toFixed(1)} ${y(p.value).toFixed(1)}`).join("");
  const path = line(points);
  const last = points.length - 1;
  const area = path ? `${path}L${x(points[last], last)} ${y(0)}L${x(points[0], 0)} ${y(0)}Z` : "";
  const band = [
    ...projection.map((p, i) => `${x(p, i)},${y(p.high)}`),
    ...projection.map((p, i) => `${x(p, i)},${y(p.low)}`).reverse(),
  ].join(" ");
  const step = Math.max(1, Math.ceil(points.length / 8));
  const markers = [...points, ...projection];
  const active = hover !== null ? markers[hover] : null;

  return (
    <div className="chart-box" style={{ position: "relative" }}>
      <svg className="line-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel} width="100%">
        <defs>
          <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0b5bd3" stopOpacity=".22" />
            <stop offset="100%" stopColor="#0b5bd3" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 25, 50, 75, 100].map((tick) => (
          <g key={tick}>
            <line x1={L} x2={W - R} y1={y(tick)} y2={y(tick)} stroke="#e3eaf4" strokeWidth="1" />
            <text x={L - 8} y={y(tick) + 3.5} textAnchor="end">{tick}%</text>
          </g>
        ))}
        {timeRange ? [0, 0.25, 0.5, 0.75, 1].map((fraction) => (
          <text key={fraction} x={L + fraction * innerW} y={H - 9} textAnchor={fraction === 1 ? "end" : "middle"}>
            {formatClock(new Date(start + fraction * (end - start)).toISOString())}
          </text>
        )) : points.map((p, i) => (i % step === 0 || i === last) && (
          <text key={p.label + i} x={x(p, i)} y={H - 9} textAnchor="middle">{p.label}</text>
        ))}
        {area && <path d={area} fill={`url(#${gradient})`} />}
        {path && <path d={path} fill="none" stroke="#0b5bd3" strokeWidth="2" strokeLinejoin="round" />}
        {band && <polygon points={band} fill="#9351c8" opacity=".19" />}
        {projection.length > 0 && <path d={line(projection)} fill="none" stroke="#7439a4" strokeWidth="2" strokeDasharray="6 4" />}
        {markers.map((p, i) => (
          <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <circle cx={x(p, i)} cy={y(p.value)} r="12" fill="transparent" />
            {(hover === i || !timeRange) && <circle cx={x(p, i)} cy={y(p.value)} r={hover === i ? 4.5 : 3} fill="#fff" stroke={i < points.length ? "#0b5bd3" : "#7439a4"} strokeWidth="2" />}
          </g>
        ))}
      </svg>
      {active && hover !== null && (
        <div className="tooltip" style={{ left: `${(x(active, hover) / W) * 100}%`, top: 4, transform: "translateX(-50%)" }}>
          {active.label} · {formatPercent(active.value)}
          {active.detail && <small>{active.detail}</small>}
        </div>
      )}
    </div>
  );
}
