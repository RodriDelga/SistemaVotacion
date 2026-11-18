import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { TurnoutForecast } from "../types";
import { ForecastPanel } from "./ForecastPanel";

vi.mock("../api", () => ({ api: { forecast: vi.fn() } }));
afterEach(cleanup);

const opensAt = "2026-11-08T14:00:00Z";
const asOf = "2026-11-08T20:00:00Z";
const closesAt = "2026-11-09T00:00:00Z";
const sample = {
  asOf, opensAt, closesAt, basedOnVotes: 400, registered: 1000,
  observed: [{ timestamp: opensAt, percent: 0 }, { timestamp: asOf, percent: 40 }],
} satisfies Partial<TurnoutForecast>;

describe("ForecastPanel", () => {
  it("dibuja el intervalo y la línea proyectada junto a la observada", async () => {
    vi.mocked(api.forecast).mockResolvedValue({
      ...sample, status: "ok", reason: null, finalPercent: 60, finalLow: 52, finalHigh: 68, interval: 0.8,
      points: [{ timestamp: asOf, percent: 40, low: 40, high: 40 }, { timestamp: closesAt, percent: 60, low: 52, high: 68 }],
    });
    render(<ForecastPanel />);
    const chart = await screen.findByRole("img", { name: "Participación observada y proyección de la jornada" });
    expect(chart.querySelector("path[stroke-dasharray]")).not.toBeNull();
    expect(chart.querySelector("polygon")).not.toBeNull();
    expect(screen.getByText(/intervalo de predicción del 80%/i)).toBeTruthy();
  });

  it("explica la baja confianza sin mostrar una estimación", async () => {
    vi.mocked(api.forecast).mockResolvedValue({
      ...sample, status: "low_confidence", reason: "Aún es pronto.", finalPercent: null, points: [],
    });
    render(<ForecastPanel />);
    expect(await screen.findByText("Aún es pronto.")).toBeTruthy();
    expect(screen.queryByText(/participación estimada al cierre/i)).toBeNull();
    const chart = screen.getByRole("img", { name: "Participación observada de la jornada" });
    expect(chart.querySelector("polygon")).toBeNull();
  });
});
