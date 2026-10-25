import type { Finding, RunStatus, Status } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-07-01" -> "1 Jul 2026" (no time-zone shifts: the string is cut, not parsed). */
export function day(value?: string | null): string {
  if (!value) return "";
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function when(iso: string): string {
  const [date, time] = iso.split("T");
  return `${day(date)}, ${time?.slice(0, 5) ?? ""}`;
}

export function pct(share: number | null | undefined): string {
  return share == null ? "—" : `${Math.round(share * 100)}%`;
}

export function claimName(id: string): string {
  if (id === "decision") return "Decision";
  const m = id.match(/^c(\d+)$/);
  return m ? `Claim ${m[1].padStart(2, "0")}` : id;
}

export function decisionWord(value?: string | null): string {
  if (value === "approve") return "Approve account";
  if (value === "escalate") return "Escalate to EDD";
  if (value === "refer") return "Refer to an analyst";
  return value ?? "Not decided";
}

/** Status words are always shown next to colour, never colour alone. */
export const statusWord: Record<Status, string> = {
  current: "Current",
  replaced: "Replaced",
  retired: "Retired",
  nosource: "No source",
  not_retrieved: "Not retrieved",
  not_yet_effective: "Not yet in force",
};

export const runStatusWord: Record<RunStatus, string> = {
  running: "Running",
  paused: "Paused",
  completed: "Completed",
  rejected: "Rejected",
  forked: "Forked",
};

export function findingTone(f: Finding, status?: RunStatus): "bad" | "warn" | "ok" {
  if (status === "paused") return "bad";
  if (f === "confirmed_by_replay" || f === "decision_used_replaced" || f === "claim_used_replaced") return "bad";
  if (f === "unsourced" || f === "outcome_unchanged" || f === "retired_in_context") return "warn";
  return "ok";
}
