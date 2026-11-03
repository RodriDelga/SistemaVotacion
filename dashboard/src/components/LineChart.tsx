import { useId, useState } from "react";
import { formatPercent } from "../lib/format";

export interface LinePoint { label: string; value: number; detail?: string }

const W = 640, H = 270, L = 44, R = 14, T = 12, B = 30;

/** Linea acumulada 0-100 % con area degradada; sin dependencias. */
export function LineChart({ points, ariaLabel }: { points: LinePoint[]; ariaLabel: string }) {
  const gradient = useId();
  const [hover, setHover] = useState<number | null>(null);
  const innerW = W - L - R, innerH = H - T - B;
  const x = (i: number) => L + (points.length <= 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const y = (v: number) => T + innerH - (Math.max(0, Math.min(100, v)) / 100) * innerH;
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join("");
  const area = points.length ? `${path}L${x(points.length - 1).toFixed(1)} ${y(0)}L${x(0).toFixed(1)} ${y(0)}Z` : "";
  const step = Math.max(1, Math.ceil(points.length / 8));
  const active = hover !== null ? points[hover] : null;

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
        {points.map((p, i) => (i % step === 0 || i === points.length - 1) && (
          <text key={p.label + i} x={x(i)} y={H - 9} textAnchor="middle">{p.label}</text>
        ))}
        {area && <path d={area} fill={`url(#${gradient})`} />}
        {path && <path d={path} fill="none" stroke="#0b5bd3" strokeWidth="2" strokeLinejoin="round" />}
        {points.map((p, i) => (
          <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <circle cx={x(i)} cy={y(p.value)} r="12" fill="transparent" />
            <circle cx={x(i)} cy={y(p.value)} r={hover === i ? 4.5 : 3} fill="#fff" stroke="#0b5bd3" strokeWidth="2" />
          </g>
        ))}
      </svg>
      {active && hover !== null && (
        <div className="tooltip" style={{ left: `${(x(hover) / W) * 100}%`, top: 4, transform: "translateX(-50%)" }}>
          {active.label} · {formatPercent(active.value)}
          {active.detail && <small>{active.detail}</small>}
        </div>
      )}
    </div>
  );
}
