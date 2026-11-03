import type { ReactNode } from "react";
import { IconAlert, IconRefresh } from "./Icons";
import { formatClock } from "../lib/format";

export const STATUS_TEXT = { online: "En línea", offline: "Sin conexión", unknown: "Sin datos" } as const;

export function Banner({ kind, children }: { kind: "warn" | "alert" | "info"; children: ReactNode }) {
  return (
    <div className={`banner ${kind}`} role={kind === "info" ? "status" : "alert"}>
      <IconAlert size={16} style={{ flexShrink: 0, marginTop: 1 }} />
      <div>{children}</div>
    </div>
  );
}

/** Aviso cuando la ultima consulta fallo y se muestran datos previos. */
export function StaleNotice({ error, updatedAt }: { error: string | null; updatedAt: number | null }) {
  if (!error) return null;
  return (
    <Banner kind="warn">
      No se pudo actualizar ({error}).{" "}
      {updatedAt ? `Se muestran los datos de las ${formatClock(new Date(updatedAt).toISOString())}.` : "Reintentando…"}
    </Banner>
  );
}

export function Stamp({ iso }: { iso?: string | null }) {
  return (
    <span className="stamp">
      <IconRefresh size={13} />
      Última actualización: {iso ? formatClock(iso) : "—"}
    </span>
  );
}

export function Skeleton({ height = 90 }: { height?: number }) {
  return <div className="skeleton" style={{ height }} aria-hidden="true" />;
}
