import mapData from "../assets/mexico-states.json";

export interface MapState { id: string; name: string; key: string; d: string }
export const MAP: { width: number; height: number; states: MapState[] } = mapData;

/** La base guarda estados normalizados (MAYUSCULAS sin acentos); el mapa usa el mismo criterio. */
export function normalizeName(raw: string): string {
  return raw.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().trim().replace(/\s+/g, " ");
}

const ALIASES: Record<string, string> = {
  "ESTADO DE MEXICO": "MEXICO",
  "CDMX": "CIUDAD DE MEXICO",
  "DISTRITO FEDERAL": "CIUDAD DE MEXICO",
  "COAHUILA DE ZARAGOZA": "COAHUILA",
  "MICHOACAN DE OCAMPO": "MICHOACAN",
  "VERACRUZ DE IGNACIO DE LA LLAVE": "VERACRUZ",
  "QUERETARO DE ARTEAGA": "QUERETARO",
};

export const stateKey = (raw: string) => {
  const key = normalizeName(raw);
  return ALIASES[key] ?? key;
};

const BY_KEY = new Map(MAP.states.map((s) => [s.key, s]));
export const findMapState = (raw: string) => BY_KEY.get(stateKey(raw));

const LOWER = new Set(["de", "del", "la", "las", "los", "y", "el"]);
export function titleCase(raw: string): string {
  return raw.toLowerCase().split(" ").map((w, i) => (i > 0 && LOWER.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1))).join(" ");
}

/** Nombre para mostrar: el del mapa (con acentos) si existe, si no una version legible. */
export function stateLabel(raw: string): string {
  return findMapState(raw)?.name ?? titleCase(raw);
}
