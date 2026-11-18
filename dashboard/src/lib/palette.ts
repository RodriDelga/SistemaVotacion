// Colores de candidatos tomados del diseno (A azul, B rojo, C naranja, D morado) y extendidos.
export const CANDIDATE_COLORS = ["#1d5fd1", "#e0364a", "#f29a2e", "#7a43d6", "#12a594", "#8a6f2a", "#c2347f", "#4b5d73"];
export const candidateColor = (index: number) => CANDIDATE_COLORS[index % CANDIDATE_COLORS.length];

export interface Bin { id: string; label: string; color: string; test: (value: number) => boolean }
// Niveles de participacion del mapa (leyenda del diseno).
export const PARTICIPATION_BINS: Bin[] = [
  { id: "high", label: "> 70%", color: "#0b4fc4", test: (v) => v > 70 },
  { id: "mid", label: "50% – 70%", color: "#3f86e6", test: (v) => v > 50 },
  { id: "low", label: "30% – 50%", color: "#8dbcf2", test: (v) => v > 30 },
  { id: "min", label: "< 30%", color: "#d3e4fa", test: () => true },
];
export const NO_DATA_COLOR = "#e6ebf2";
export const binFor = (value: number) => PARTICIPATION_BINS.find((b) => b.test(value)) ?? PARTICIPATION_BINS[3];
