import { useMemo, useState } from "react";
import { api } from "../api";
import { usePolling } from "../hooks/usePolling";
import { Avatar } from "../components/Avatar";
import { Donut } from "../components/Donut";
import { MexicoMap } from "../components/MexicoMap";
import { Skeleton, Stamp, StaleNotice } from "../components/Bits";
import { candidateColor } from "../lib/palette";
import { formatInt, formatPercent } from "../lib/format";
import { stateLabel, titleCase } from "../lib/states";
import type { CandidateResult, Meta } from "../types";

interface Group { key: string; title: string | null; items: CandidateResult[] }

export function groupCandidates(rows: CandidateResult[]): Group[] {
  const groups = new Map<string, Group>();
  for (const row of rows) {
    const key = `${row.stateName ?? ""}|${row.municipalityName ?? ""}`;
    let group = groups.get(key);
    if (!group) {
      const title = row.municipalityName ? `${titleCase(row.municipalityName)}${row.stateName ? ` · ${stateLabel(row.stateName)}` : ""}`
        : row.stateName ? stateLabel(row.stateName) : null;
      group = { key, title, items: [] };
      groups.set(key, group);
    }
    group.items.push(row);
  }
  return [...groups.values()];
}

export function Results({ meta, pollMs }: { meta: Meta; pollMs: number }) {
  const [office, setOffice] = useState("PRESIDENT");
  const [state, setState] = useState<string>(meta.states[0] ?? "");
  const needsState = office !== "PRESIDENT";
  const stateParam = needsState ? state || undefined : undefined;

  const results = usePolling((s) => api.results(office, stateParam, s), pollMs, [office, stateParam]);
  const participation = usePolling((s) => api.participation(s), pollMs);
  const officeLabel = meta.offices.find((o) => o.code === office)?.label ?? office;
  const groups = useMemo(() => groupCandidates(results.data?.candidates ?? []), [results.data]);
  const part = participation.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Resultados en tiempo real</h1>
          <p className="page-sub">Elección: <strong>{officeLabel}</strong>{needsState && state ? ` · ${stateLabel(state)}` : ""}</p>
        </div>
        <Stamp iso={results.data?.asOf} />
      </div>

      <StaleNotice error={results.error ?? participation.error} updatedAt={results.updatedAt} />

      <div className="filters">
        <label className="sr-only" htmlFor="f-office">Cargo</label>
        <select id="f-office" className="select" value={office} onChange={(e) => setOffice(e.target.value)}>
          {meta.offices.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
        </select>
        {needsState && (
          <>
            <label className="sr-only" htmlFor="f-state">Entidad</label>
            <select id="f-state" className="select" value={state} onChange={(e) => setState(e.target.value)}>
              {meta.states.map((s) => <option key={s} value={s}>{stateLabel(s)}</option>)}
            </select>
          </>
        )}
      </div>

      <section aria-label={`Resultados de ${officeLabel}`}>
        {results.loading && !results.data && <div className="cand-grid">{[0, 1, 2, 3].map((i) => <Skeleton key={i} height={96} />)}</div>}
        {results.data && groups.length === 0 && <div className="card empty">No hay candidatos registrados para esta selección.</div>}
        {groups.map((group) => (
          <div key={group.key}>
            {group.title && <h2 className="section-label">{group.title}</h2>}
            <div className="cand-grid">
              {group.items.map((c, index) => (
                <article className="card cand-card" key={c.candidateId}>
                  <Avatar color={candidateColor(index)} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="cand-name">{c.name}</div>
                    <div className="cand-pct">{formatPercent(c.percent)}</div>
                    <div className="cand-votes">{formatInt(c.votes)} {c.votes === 1 ? "voto" : "votos"}</div>
                  </div>
                  <div className="bar" role="progressbar" aria-valuenow={c.percent} aria-valuemin={0} aria-valuemax={100} aria-label={`${c.name}: ${formatPercent(c.percent)}`}>
                    <span style={{ width: `${c.percent}%`, background: candidateColor(index) }} />
                  </div>
                </article>
              ))}
            </div>
          </div>
        ))}
      </section>

      <div className="two-col">
        <section className="card" aria-label="Participación ciudadana">
          <h2 className="card-title">Participación ciudadana</h2>
          {part ? (
            <div className="donut-row">
              <Donut percent={part.participation} label="Participación ciudadana" />
              <div>
                <div className="stat"><div className="stat-label">Votos emitidos</div><div className="stat-value">{formatInt(part.voted)}</div></div>
                <div className="stat"><div className="stat-label">Total de votantes</div><div className="stat-value">{formatInt(part.registered)}</div></div>
              </div>
            </div>
          ) : <Skeleton height={160} />}
        </section>
        <section className="card" aria-label="Votación por estado">
          <h2 className="card-title">Votación por estado</h2>
          {part ? <MexicoMap data={part.byState} /> : <Skeleton height={200} />}
        </section>
      </div>
    </>
  );
}
