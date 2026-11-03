import { useState } from "react";
import { api } from "../api";
import { usePolling } from "../hooks/usePolling";
import { Banner, Skeleton, Stamp, StaleNotice, STATUS_TEXT } from "../components/Bits";
import { COMPONENT_ICONS, IconChevronRight, IconParticipation } from "../components/Icons";
import { formatDateTime, relativeTime } from "../lib/format";
import type { SystemComponent } from "../types";

const COMPACT = 5;

function StatusCard({ item }: { item: SystemComponent }) {
  const Icon = COMPONENT_ICONS[item.id] ?? IconParticipation;
  const meta = item.latencyMs != null ? `${item.latencyMs} ms` : item.status === "online" ? relativeTime(item.lastSeen) : item.lastSeen ? `Visto ${relativeTime(item.lastSeen).toLowerCase()}` : "Sin reporte";
  return (
    <div className={`card status-card is-${item.status}`}>
      <div className="status-icon"><Icon size={20} /></div>
      <div>
        <div className="status-name">{item.label}</div>
        <div className={`status-state t-${item.status}`}><span className={`dot ${item.status}`} />{STATUS_TEXT[item.status]}</div>
        <div className="status-meta">{item.id === "network" ? " " : meta}</div>
      </div>
    </div>
  );
}

export function Overview({ pollMs }: { pollMs: number }) {
  const [expanded, setExpanded] = useState(false);
  const system = usePolling((s) => api.system(s), pollMs);
  const events = usePolling((s) => api.events(expanded ? 50 : COMPACT, {}, s), pollMs, [expanded]);
  const analytics = usePolling((s) => api.analytics({ from: undefined }, s), pollMs * 3);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Estado del sistema</h1>
          <p className="page-sub">Componentes de la urna y servicios conectados</p>
        </div>
        <Stamp iso={system.data?.asOf} />
      </div>

      <StaleNotice error={system.error} updatedAt={system.updatedAt} />
      {analytics.data && analytics.data.status !== "NORMAL" && (
        <Banner kind={analytics.data.status === "ALERTA" ? "alert" : "warn"}>
          <strong>Auditoría: {analytics.data.status}.</strong>
          <ul>{analytics.data.auditFlags.map((flag) => <li key={flag}>{flag}</li>)}</ul>
        </Banner>
      )}
      {system.data && system.data.components.some((c) => c.id === "kiosk" && c.status !== "online") && (
        <Banner kind="info">
          La urna no ha enviado su latido en los últimos {system.data.heartbeatTtlSeconds} s; el estado de cámara y lector RFID aparece como «Sin datos».
        </Banner>
      )}

      <section aria-label="Componentes">
        {system.loading && !system.data ? (
          <div className="status-grid">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} height={74} />)}</div>
        ) : (
          <div className="status-grid">{system.data?.components.map((item) => <StatusCard key={item.id} item={item} />)}</div>
        )}
      </section>

      <section className="card table-card" aria-label="Registros recientes">
        <h2 className="card-title">
          Registros recientes
          <button className="link-btn" onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
            {expanded ? "Ver menos" : "Ver todos"} <IconChevronRight size={12} style={{ transform: expanded ? "rotate(90deg)" : undefined }} />
          </button>
        </h2>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Fecha / Hora</th><th>Evento</th><th>Dispositivo</th><th>Estado</th></tr></thead>
            <tbody>
              {events.data?.events.map((row) => (
                <tr key={row.id}>
                  <td>{formatDateTime(row.timestamp)}</td>
                  <td>{row.event}</td>
                  <td>{row.device}</td>
                  <td><span className={`badge ${row.status}`}>{row.statusLabel}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {events.data && events.data.events.length === 0 && <p className="empty">Aún no hay eventos registrados.</p>}
        {events.loading && !events.data && <p className="empty">Cargando…</p>}
        {events.error && !events.data && <p className="empty">No se pudieron cargar los registros ({events.error}).</p>}
      </section>
    </>
  );
}
