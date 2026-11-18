import { useMemo, useState } from "react";
import { MAP, findMapState, stateLabel } from "../lib/states";
import { NO_DATA_COLOR, PARTICIPATION_BINS, binFor } from "../lib/palette";
import { formatInt, formatPercent } from "../lib/format";
import type { StateParticipation } from "../types";

/** Mapa coropletico de participacion por entidad (SVG local; funciona sin internet). */
export function MexicoMap({ data }: { data: StateParticipation[] }) {
  const [tip, setTip] = useState<{ x: number; y: number; id: string } | null>(null);
  const byId = useMemo(() => {
    const map = new Map<string, StateParticipation>();
    for (const row of data) {
      const state = findMapState(row.state);
      if (!state) continue;
      const prev = map.get(state.id); // dos nombres que resuelven a la misma entidad se suman
      map.set(state.id, prev ? mergeRows(prev, row) : row);
    }
    return map;
  }, [data]);
  const hovered = tip ? MAP.states.find((s) => s.id === tip.id) : undefined;
  const info = tip ? byId.get(tip.id) : undefined;

  return (
    <div className="map-row" onMouseLeave={() => setTip(null)}>
      <svg className="map-svg" viewBox={`0 0 ${MAP.width} ${MAP.height}`} role="img"
        aria-label="Mapa de México con participación por entidad federativa">
        {MAP.states.map((state) => {
          const row = byId.get(state.id);
          const fill = row && row.registered > 0 ? binFor(row.participation).color : NO_DATA_COLOR;
          return (
            <path key={state.id} d={state.d} fill={fill}
              onMouseMove={(event) => {
                const box = event.currentTarget.ownerSVGElement!.parentElement!.getBoundingClientRect();
                setTip({ x: event.clientX - box.left, y: event.clientY - box.top, id: state.id });
              }}>
              <title>{stateLabel(state.name)}{row ? `: ${formatPercent(row.participation)}` : ": sin datos"}</title>
            </path>
          );
        })}
      </svg>
      <ul className="legend" aria-label="Leyenda de participación">
        {PARTICIPATION_BINS.map((bin) => (
          <li key={bin.id}><i style={{ background: bin.color }} />{bin.label}</li>
        ))}
        <li><i style={{ background: NO_DATA_COLOR }} />Sin registro</li>
      </ul>
      {tip && hovered && (
        <div className="tooltip" style={{ left: tip.x + 12, top: tip.y + 12 }}>
          {hovered.name}
          <small>{info ? `${formatPercent(info.participation)} · ${formatInt(info.voted)} de ${formatInt(info.registered)}` : "Sin registro de votantes"}</small>
        </div>
      )}
    </div>
  );
}

function mergeRows(a: StateParticipation, b: StateParticipation): StateParticipation {
  const registered = a.registered + b.registered;
  const voted = a.voted + b.voted;
  return { state: a.state, registered, voted, participation: registered ? Math.round((voted / registered) * 10000) / 100 : 0 };
}
