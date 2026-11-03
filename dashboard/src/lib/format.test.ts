import { describe, expect, it } from "vitest";
import { formatInt, formatPercent, relativeTime, setTimeZone, formatDateTime, formatClock } from "./format";
import { stateKey, stateLabel, findMapState, MAP } from "./states";
import { binFor } from "./palette";

describe("formato", () => {
  it("formatea enteros y porcentajes en es-MX", () => {
    expect(formatInt(6230154)).toBe("6,230,154");
    expect(formatPercent(62.3)).toBe("62.3%");
    expect(formatPercent(7, 0)).toBe("7%");
  });
  it("usa la zona horaria del servidor", () => {
    setTimeZone("America/Mexico_City");
    expect(formatDateTime("2026-10-03T16:37:00+00:00")).toBe("03/10/2026 10:37");
    expect(formatClock("2026-10-03T16:42:00+00:00")).toBe("10:42 AM");
  });
  it("describe tiempos relativos", () => {
    const now = Date.parse("2026-10-03T12:00:00Z");
    expect(relativeTime(null, now)).toBe("Sin reporte");
    expect(relativeTime("2026-10-03T11:59:55Z", now)).toBe("Ahora mismo");
    expect(relativeTime("2026-10-03T11:58:00Z", now)).toBe("Hace 2 min");
  });
});

describe("estados", () => {
  it("el mapa trae las 32 entidades", () => expect(MAP.states).toHaveLength(32));
  it("resuelve alias y acentos", () => {
    expect(stateKey("Estado de México")).toBe("MEXICO");
    expect(findMapState("CIUDAD DE MEXICO")?.name).toBe("Ciudad de México");
    expect(findMapState("Veracruz de Ignacio de la Llave")?.id).toBe("MX-VER");
    expect(stateLabel("SINALOA")).toBe("Sinaloa");
    expect(stateLabel("ESTADO DESCONOCIDO")).toBe("Estado Desconocido");
  });
});

describe("niveles de participacion", () => {
  it("clasifica segun la leyenda", () => {
    expect(binFor(70.1).id).toBe("high");
    expect(binFor(70).id).toBe("mid");
    expect(binFor(50).id).toBe("low");
    expect(binFor(30).id).toBe("min");
  });
});
