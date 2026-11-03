import { useMemo, useState } from "react";
import { api, type Range } from "../api";
import { usePolling } from "../hooks/usePolling";
import { BarList } from "../components/BarList";
import { LineChart } from "../components/LineChart";
import { Skeleton, StaleNotice } from "../components/Bits";
import { IconCalendar, IconDownload } from "../components/Icons";
import { formatInt, formatPercent, localDateString } from "../lib/format";
import { stateLabel } from "../lib/states";
import type { Meta, TimelinePoint } from "../types";

type Tab = "participacion" | "resultados" | "dispositivos" | "areas";
const TABS: { id: Tab; label: string }[] = [
  { id: "participacion", label: "Participación" },
  { id: "resultados", label: "Resultados" },
  { id: "dispositivos", label: "Dispositivos" },
  { id: "areas", label: "Votos por área" },
];

/** Quita el tramo inicial sin votos para que la grafica arranque donde empieza la jornada. */
export function trimLeadingEmpty(points: TimelinePoint[]): TimelinePoint[] {
  const first = points.findIndex((p) => p.cumulativeVotes > 0);
  if (first < 0) return points;
  return points.slice(Math.max(0, first - 1));
}

function Export({ dataset, range, label }: { dataset: "results" | "participation" | "events"; range?: Range; label: string }) {
  return <a className="btn" href={api.exportUrl(dataset, range)} download><IconDownload size={15} />{label}</a>;
}

export function Reports({ meta, pollMs }: { meta: Meta; pollMs: number }) {
  const today = localDateString();
  const [tab, setTab] = useState<Tab>("participacion");
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(today);
  const invalid = from > to;
  const range: Range = useMemo(() => ({ from, to }), [from, to]);

  const timeline = usePolling((s) => (invalid ? Promise.reject(new Error("rango")) : api.timeline(range, s)), pollMs * 2, [from, to, invalid]);
  const participation = usePolling((s) => api.participation(s), pollMs * 2);
  const results = usePolling((s) => api.results(undefined, undefined, s), pollMs * 2);
  const analytics = usePolling((s) => api.analytics(range, s), pollMs * 2, [from, to]);

  const points = useMemo(() => trimLeadingEmpty(timeline.data?.points ?? []), [timeline.data]);
  const totalVoted = participation.data?.voted ?? 0;
  const byState = useMemo(() => {
    const rows = [...(participation.data?.byState ?? [])].filter((r) => r.voted > 0).sort((a, b) => b.voted - a.voted);
    return rows.map((r) => ({ label: stateLabel(r.state), value: totalVoted ? (r.voted / totalVoted) * 100 : 0 }));
  }, [participation.data, totalVoted]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Reportes y analíticas</h1>
          <p className="page-sub">{meta.title}</p>
        </div>
        <div className="range" role="group" aria-label="Rango de fechas">
          <IconCalendar size={15} />
          <input type="date" aria-label="Desde" value={from} max={to} onChange={(e) => e.target.value && setFrom(e.target.value)} />
          <span className="sep">–</span>
          <input type="date" aria-label="Hasta" value={to} min={from} onChange={(e) => e.target.value && setTo(e.target.value)} />
        </div>
      </div>

      <div className="tabs" role="tablist" aria-label="Secciones del reporte">
        {TABS.map((t) => (
          <button key={t.id} className="tab" role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls="tab-panel" onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      <div id="tab-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === "participacion" && (
          <>
            <StaleNotice error={timeline.error === "rango" ? null : timeline.error} updatedAt={timeline.updatedAt} />
            <div className="charts-grid">
              <section className="card" aria-label="Participación por hora">
                <h2 className="card-title">Participación por {timeline.data?.bucket === "day" ? "día" : "hora"}</h2>
                {invalid ? <p className="empty">La fecha inicial debe ser anterior o igual a la final.</p>
                  : timeline.loading && !timeline.data ? <Skeleton height={250} />
                  : points.length === 0 ? <p className="empty">Sin votos registrados en el rango seleccionado.</p>
                  : <LineChart points={points.map((p) => ({ label: p.label, value: p.cumulativePercent, detail: `${formatInt(p.cumulativeVotes)} votos acumulados · +${formatInt(p.votes)}` }))}
                      ariaLabel="Participación acumulada respecto del padrón" />}
                {participation.data && participation.data.untrackedVotes > 0 && (
                  <p className="page-sub">{formatInt(participation.data.untrackedVotes)} voto(s) anteriores al registro de eventos no aparecen en la serie.</p>
                )}
              </section>
              <section className="card" aria-label="Votos por entidad federativa">
                <h2 className="card-title">Votos por entidad federativa</h2>
                {participation.loading && !participation.data ? <Skeleton height={250} />
                  : byState.length === 0 ? <p className="empty">Aún no hay votos.</p>
                  : <BarList items={byState.slice(0, 8)} max={Math.max(...byState.map((i) => i.value))} />}
              </section>
            </div>
          </>
        )}

        {tab === "resultados" && (
          <>
            <div className="toolbar"><Export dataset="results" label="Exportar CSV" /></div>
            <div className="card table-card"><div className="table-wrap">
              <table className="data">
                <thead><tr><th>Cargo</th><th>Región</th><th>Candidato</th><th className="num">Votos</th><th className="num">%</th></tr></thead>
                <tbody>
                  {results.data?.candidates.map((c) => (
                    <tr key={c.candidateId}>
                      <td>{meta.offices.find((o) => o.code === c.office)?.label ?? c.office}</td>
                      <td>{[c.municipalityName, c.stateName && stateLabel(c.stateName)].filter(Boolean).join(" · ") || "Nacional"}</td>
                      <td>{c.name}</td><td className="num">{formatInt(c.votes)}</td><td className="num">{formatPercent(c.percent, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>{results.data?.candidates.length === 0 && <p className="empty">Sin candidatos registrados.</p>}</div>
          </>
        )}

        {tab === "dispositivos" && (
          <>
            <StaleNotice error={analytics.error} updatedAt={analytics.updatedAt} />
            <div className="toolbar"><Export dataset="events" range={range} label="Exportar bitácora CSV" /></div>
            <div className="card table-card">
              <h2 className="card-title">
                Eventos por tipo
                {analytics.data && <span className={`pill ${analytics.data.status}`}>{analytics.data.status}</span>}
              </h2>
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Tipo</th><th className="num">Exitosos</th><th className="num">Rechazados</th><th className="num">Errores</th><th className="num">Total</th><th className="num">Tasa de fallo</th></tr></thead>
                  <tbody>
                    {analytics.data?.byKind.map((k) => (
                      <tr key={k.kind}><td>{k.label}</td><td className="num">{formatInt(k.ok)}</td><td className="num">{formatInt(k.rejected)}</td>
                        <td className="num">{formatInt(k.error)}</td><td className="num">{formatInt(k.total)}</td><td className="num">{formatPercent(k.failureRate * 100)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {analytics.data && analytics.data.auditFlags.length > 0 && (
                <ul style={{ margin: "0 18px 14px", paddingLeft: 18, fontSize: 12 }}>{analytics.data.auditFlags.map((f) => <li key={f}>{f}</li>)}</ul>
              )}
            </div>
          </>
        )}

        {tab === "areas" && (
          <>
            <div className="toolbar"><Export dataset="participation" label="Exportar CSV" /></div>
            <div className="card table-card"><div className="table-wrap">
              <table className="data">
                <thead><tr><th>Entidad</th><th className="num">Registrados</th><th className="num">Votaron</th><th className="num">Participación</th><th style={{ width: "28%" }}>Avance</th></tr></thead>
                <tbody>
                  {participation.data?.byState.map((r) => (
                    <tr key={r.state}>
                      <td>{stateLabel(r.state)}</td><td className="num">{formatInt(r.registered)}</td><td className="num">{formatInt(r.voted)}</td>
                      <td className="num">{formatPercent(r.participation)}</td>
                      <td><div className="bar" aria-hidden="true"><span style={{ width: `${r.participation}%`, background: "#0b5bd3" }} /></div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>{participation.data?.byState.length === 0 && <p className="empty">Sin padrón registrado.</p>}</div>
          </>
        )}
      </div>
    </>
  );
}
