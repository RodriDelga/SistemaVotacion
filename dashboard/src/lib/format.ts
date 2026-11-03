let timeZone = "America/Mexico_City";
export function setTimeZone(tz: string) {
  try {
    new Intl.DateTimeFormat("es-MX", { timeZone: tz });
    timeZone = tz;
  } catch { /* zona desconocida: se conserva la actual */ }
}
export const getTimeZone = () => timeZone;

const intFmt = new Intl.NumberFormat("es-MX");
export const formatInt = (value: number) => intFmt.format(Math.round(value));
export const formatPercent = (value: number, digits = 1) =>
  `${value.toLocaleString("es-MX", { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;

function parts(iso: string, options: Intl.DateTimeFormatOptions): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of new Intl.DateTimeFormat("es-MX", { timeZone, hourCycle: "h23", ...options }).formatToParts(new Date(iso))) {
    out[part.type] = part.value;
  }
  return out;
}

/** "03/10/2026 10:37" (formato de la tabla de registros). */
export function formatDateTime(iso: string): string {
  const p = parts(iso, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  return `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}`;
}

/** "10:42 AM" (ultima actualizacion). */
export function formatClock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { timeZone, hour: "2-digit", minute: "2-digit", hour12: true }).format(date);
}

/** YYYY-MM-DD en la zona del servidor. */
export function localDateString(date: Date = new Date()): string {
  const p = parts(date.toISOString(), { year: "numeric", month: "2-digit", day: "2-digit" });
  return `${p.year}-${p.month}-${p.day}`;
}

export function relativeTime(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "Sin reporte";
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 10) return "Ahora mismo";
  if (seconds < 60) return `Hace ${seconds} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `Hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `Hace ${hours} h`;
  return `Hace ${Math.round(hours / 24)} d`;
}
