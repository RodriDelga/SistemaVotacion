// Contratos de la API administrativa (dashboard_api.py). Mantener sincronizado con docs/DASHBOARD_MANUAL.md.
export type Status = "online" | "offline" | "unknown";
export type EventStatus = "ok" | "rejected" | "error";

export interface Meta {
  title: string;
  timezone: string;
  offices: { code: string; label: string }[];
  states: string[];
  pollSeconds: number;
  serverTime: string;
}

export interface CandidateResult {
  candidateId: number;
  name: string;
  office: string;
  stateName: string | null;
  municipalityName: string | null;
  votes: number;
  percent: number;
  regionTotal: number;
}

export interface Results {
  asOf: string;
  office: string | null;
  state: string | null;
  totalVotes: number;
  candidates: CandidateResult[];
}

export interface StateParticipation {
  state: string;
  registered: number;
  voted: number;
  participation: number;
}

export interface Participation {
  asOf: string;
  registered: number;
  voted: number;
  pending: number;
  participation: number;
  untrackedVotes: number;
  byState: StateParticipation[];
}

export interface TimelinePoint {
  timestamp: string;
  label: string;
  votes: number;
  cumulativeVotes: number;
  cumulativePercent: number;
}

export interface Timeline {
  bucket: "hour" | "day";
  registered: number;
  points: TimelinePoint[];
}

export interface SystemComponent {
  id: string;
  label: string;
  status: Status;
  lastSeen: string | null;
  latencyMs?: number | null;
}

export interface SystemStatus {
  asOf: string;
  overall: Status;
  heartbeatTtlSeconds: number;
  components: SystemComponent[];
}

export interface EventRow {
  id: number;
  timestamp: string;
  kind: string;
  event: string;
  device: string;
  status: EventStatus;
  statusLabel: string;
}

export interface EventsResponse {
  asOf: string;
  events: EventRow[];
}

export interface AnalyticsKind {
  kind: string;
  label: string;
  ok: number;
  rejected: number;
  error: number;
  total: number;
  failureRate: number;
}

export interface Analytics {
  asOf: string;
  status: "NORMAL" | "PRECAUCIÓN" | "ALERTA";
  auditFlags: string[];
  byKind: AnalyticsKind[];
}

export interface AuthState {
  authenticated: boolean;
  role: string | null;
}
