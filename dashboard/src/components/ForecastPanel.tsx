import { api } from "../api";
import { usePolling } from "../hooks/usePolling";
import { formatDateTime, formatInt, formatPercent } from "../lib/format";
import { Skeleton, StaleNotice } from "./Bits";
import { LineChart } from "./LineChart";

export function ForecastPanel() {
  const { data, loading, error, updatedAt } = usePolling(api.forecast, 60_000);
  const projected = data?.status === "ok";
  const { finalLow, finalHigh, interval } = data ?? {};
  const chartWindow = data?.opensAt && data.closesAt ? [data.opensAt, data.closesAt] as [string, string] : undefined;
  const observed = (data?.observed ?? []).map((p) => ({ ...p, label: formatDateTime(p.timestamp), value: p.percent, detail: "Observado" }));
  const projection = (data?.points ?? []).map((p) => ({
    ...p, label: formatDateTime(p.timestamp), value: p.percent,
    detail: `Proyección · ${formatPercent(p.low)} a ${formatPercent(p.high)}`,
  }));

  return (
    <section className="card forecast-card" aria-labelledby="forecast-title">
      <h2 id="forecast-title" className="card-title">Pronóstico de participación</h2>
      <StaleNotice error={error} updatedAt={updatedAt} />
      {loading && !data && <Skeleton height={120} />}
      {chartWindow && <p className="page-sub">Jornada del {formatDateTime(chartWindow[0])} al {formatDateTime(chartWindow[1])}</p>}
      {data?.finalPercent != null && (
        <p className="forecast-estimate">
          <strong>{formatPercent(data.finalPercent)}</strong>
          {data.status === "closed" ? " participación al cierre" : " participación estimada al cierre"}
        </p>
      )}
      {projected && finalLow != null && finalHigh != null && interval != null && (
        <p className="page-sub">Intervalo de predicción del {formatPercent(interval * 100, 0)} · {formatPercent(finalLow)} a {formatPercent(finalHigh)}</p>
      )}
      {data?.reason && <p className="page-sub" role="status">{data.reason}</p>}
      {data?.basedOnVotes != null && <p className="page-sub">{formatInt(data.basedOnVotes)} votos con hora registrada · {formatInt(data.registered ?? 0)} personas en el padrón</p>}
      {data?.asOf && <p className="page-sub">Corte de datos {formatDateTime(data.asOf)}</p>}
      {observed.length > 0 && chartWindow && (
        <>
          <LineChart points={observed} projection={projection} timeRange={chartWindow}
            ariaLabel={projected ? "Participación observada y proyección de la jornada" : "Participación observada de la jornada"} />
          <div className="forecast-legend">
            <span><i className="forecast-observed" /> Observado</span>
            {projected && <><span><i className="forecast-projection" /> Proyección</span><span><i className="forecast-band" /> Intervalo de predicción</span></>}
          </div>
        </>
      )}
    </section>
  );
}
