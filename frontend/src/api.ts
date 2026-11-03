export interface Report {
  id: string; titulo: string; descripcion: string; tipo: string; severidad: string;
  activo_afectado: string | null; origen: string; motivo_revision: string | null;
  responsable: string | null; recibido_at: string; notificado_at: string | null;
  vence_respuesta_at: string | null; vence_resolucion_at: string | null;
  respondido_at: string | null; resuelto_at: string | null;
}
export type Role = "administrador" | "analista" | "gestor" | "auditor";
export interface User { id: string; username: string; role: Role; active: number }
export interface Metrics {
  total: number; asignados: number; requieren_revision: number;
  respuesta_a_tiempo: number; respuesta_evaluable: number;
  resolucion_a_tiempo: number; resolucion_evaluable: number;
}
export interface Baseline { label: string; sample_count: number; average_seconds: number; is_demo: number }
export interface Triage {
  baseline: Baseline | null; measured_reports: number; comparable_reports: number;
  pending_review_measurements: number; average_cycle_seconds: number | null;
  estimated_hours_saved: number | null; demo_comparisons: number;
}
export interface Audit {
  id: string; user_id: string; role: string; action: string; module: string; ip: string;
  occurred_at: string; phase: string; status_code: number | null; entity_id: string | null;
  request_id: string | null;
  outcome: string | null;
}
export interface Event { accion: string; actor: string; ocurrido_at: string; detalle: string }
export function stage(report: Report) {
  if (!report.notificado_at || !report.respondido_at) return 0;
  return report.resuelto_at ? 2 : 1;
}
export function selectedReports(reports: Report[], filter: string) {
  return reports.filter((report) => {
    if (filter === "pendientes") return stage(report) !== 2;
    if (filter === "resueltos") return stage(report) === 2;
    if (filter === "revision") return Boolean(report.motivo_revision);
    return true;
  });
}
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export async function request<T>(path: string, token = "", options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, typeof data.detail === "string" ? data.detail : data.detail?.[0]?.msg || `HTTP ${response.status}`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
export function readPreference(key: string, fallback: string) {
  try { return localStorage.getItem(`soc-${key}`) || fallback; } catch { return fallback; }
}

export async function downloadFile(path: string, token: string, filename: string) {
  const response = await fetch(path, { headers: { Authorization: "Bearer " + token }, cache: "no-store" });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(response.status, typeof error.detail === "string" ? error.detail : "HTTP " + response.status);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
