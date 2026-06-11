// API client for the VFIED backend (MIGRATION.md Turn 3 endpoints).
// Every dashboard number traces through here to a frozen-engine output.

const BASE = "/api/v1";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new ApiError(res.status, detail?.detail || res.statusText);
  }
  return res.json();
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// ---- Types (mirror the API payloads) ----
export type Suite = { slug: string; profile_version: string; probe_count: number };
export type Connection = {
  id: string; kind: "key_based" | "endpoint_based"; display_name: string;
  provider?: string; model?: string; api_key_last4?: string; endpoint?: string;
};
export type PreviewResult = {
  run_id: string; suite: string; probe_count: number; probe_set_hash: string;
  embedder_id: string; billing_note: string; cap: { max_probes: number; within_cap: boolean };
};
export type RunStatus = {
  run_id: string; status: string;
  progress: { completed_probes: number; total_probes: number };
  risk_score: number | null; status_label: string | null; avg_lambda: number | null;
  error: string | null;
};
export type Family = {
  family: string; count: number; avg_lambda: number;
  is_top_weakness: boolean; is_top_safe: boolean;
};
export type Results = {
  run_id: string; risk_score: number; status_label: string; avg_lambda: number;
  top_weakness_family: string; top_safe_family: string;
  families: Family[]; rw_weights: any;
};
export type Incident = {
  response_id: string; family: string; prompt_text: string; response_preview: string;
  response_type: string; lambda: number; oat_p: number; oat_o: number;
  semantic_score: number | null; active_cues: string[]; is_failure: boolean;
};

// ---- Calls ----
export const createProject = (name: string) =>
  http<{ id: string; name: string }>("/projects", { method: "POST", body: JSON.stringify({ name }) });

export const createConnection = (projectId: string, body: any) =>
  http<Connection>(`/projects/${projectId}/connections`, { method: "POST", body: JSON.stringify(body) });

export const listSuites = () => http<Suite[]>("/suites");

export const previewRun = (projectId: string, connectionId: string, suite: string) =>
  http<PreviewResult>(`/projects/${projectId}/runs/preview`, {
    method: "POST", body: JSON.stringify({ connection_id: connectionId, suite }),
  });

export const submitRun = (projectId: string, runId: string, ackCount: number, hash: string) =>
  http<{ run_id: string; status: string; poll: string }>(`/projects/${projectId}/runs`, {
    method: "POST",
    body: JSON.stringify({ run_id: runId, acknowledged_probe_count: ackCount, probe_set_hash: hash }),
  });

export const getRun = (runId: string) => http<RunStatus>(`/runs/${runId}`);
export const getResults = (runId: string) => http<Results>(`/runs/${runId}/results`);
export const getIncidents = (runId: string, onlyFailures = true) =>
  http<{ items: Incident[] }>(`/runs/${runId}/incidents?only_failures=${onlyFailures}`);
