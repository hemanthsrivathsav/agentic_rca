import type { Overview, Report, RunSummary, StepState } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* body was not JSON */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  overview: () => request<Overview>("/overview"),
  runs: () => request<RunSummary[]>("/runs"),
  report: (id: string) => request<Report>(`/runs/${encodeURIComponent(id)}`),
  state: (id: string, step: number) => request<StepState>(`/runs/${encodeURIComponent(id)}/steps/${step}/state`),
  resume: (id: string, action: "approve" | "edit" | "reject", swaps?: Record<string, string>) =>
    post<Report>(`/runs/${encodeURIComponent(id)}/resume`, { action, swaps }),
  fork: (id: string, fromStep: number, swaps: Record<string, string>, reason: string) =>
    post<Report>(`/runs/${encodeURIComponent(id)}/fork`, { from_step: fromStep, swaps, reason }),
  setRule: (id: string, key: string, on: boolean) => post<Report>(`/runs/${encodeURIComponent(id)}/rules`, { key, on }),
  feedback: (id: string, verdict: "correct" | "wrong" | "needs_review", note = "") =>
    post<{ run_id: string }>(`/runs/${encodeURIComponent(id)}/feedback`, { verdict, note }),
  startRun: (customerId: string) => post<Report>("/runs", { customer_id: customerId, options: { breakpoints: true } }),
  resetDemo: () => post<{ ok: boolean }>("/demo/reset", {}),
};
