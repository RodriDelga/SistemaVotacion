import { formatPercent } from "../lib/format";

export function Donut({ percent, label }: { percent: number; label: string }) {
  const value = Math.max(0, Math.min(100, percent));
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <svg width="150" height="150" viewBox="0 0 150 150" role="img" aria-label={`${label}: ${formatPercent(value)}`}>
      <circle cx="75" cy="75" r={r} fill="none" stroke="#dce8fa" strokeWidth="16" />
      <circle cx="75" cy="75" r={r} fill="none" stroke="#0b5bd3" strokeWidth="16" strokeLinecap="butt"
        strokeDasharray={`${(value / 100) * c} ${c}`} transform="rotate(-90 75 75)"
        style={{ transition: "stroke-dasharray .6s ease" }} />
      <text x="75" y="82" textAnchor="middle" fontSize="23" fontWeight="800" fill="#0f2342">{formatPercent(value)}</text>
    </svg>
  );
}
