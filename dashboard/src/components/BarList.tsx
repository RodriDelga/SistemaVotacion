import { formatPercent } from "../lib/format";

export interface BarItem { label: string; value: number; display?: string }

/** Barras horizontales (Votos por entidad federativa). `value` en la escala 0-max. */
export function BarList({ items, max }: { items: BarItem[]; max?: number }) {
  const top = max ?? Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="hbars" role="list">
      {items.map((item) => (
        <div className="hbar-row" role="listitem" key={item.label}>
          <span>{item.label}</span>
          <div className="bar" aria-hidden="true">
            <span style={{ width: `${Math.max(0, Math.min(100, (item.value / top) * 100))}%`, background: "#0b5bd3" }} />
          </div>
          <b>{item.display ?? formatPercent(item.value)}</b>
        </div>
      ))}
    </div>
  );
}
