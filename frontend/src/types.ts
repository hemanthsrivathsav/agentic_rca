// Shapes returned by the Supersede API (backend/supersede/service.py).

export type Status = "current" | "replaced" | "nosource" | "retired" | "not_retrieved" | "not_yet_effective";
export type RunStatus = "running" | "paused" | "completed" | "rejected" | "forked";
export type Finding =
  | "healthy"
  | "unsourced"
  | "retired_in_context"
  | "claim_used_replaced"
  | "decision_used_replaced"
  | "outcome_unchanged"
  | "confirmed_by_replay";

export interface Run {
  id: string;
  workflow: string;
  subject: string;
  status: RunStatus;
  run_time: string;
  parent_run_id: string | null;
  forked_at: number | null;
  fork_reason: string | null;
  paused_at: number | null;
  pause_reason: string | null;
  options: { breakpoints?: boolean; guard?: boolean; swaps?: Record<string, string>; rules?: Record<string, boolean> };
  created_at: string;
}

export interface Counts {
  claims: number;
  current: number;
  replaced: number;
  nosource: number;
  evidence: number;
  unused_evidence: number;
}

export interface Stability {
  samples: number;
  counts: Record<string, number>;
  stable: boolean;
  agreement: number;
}

export interface RunSummary {
  id: string;
  workflow: string;
  subject: string;
  status: RunStatus;
  run_time: string;
  created_at: string;
  paused_at: number | null;
  decision: string | null;
  finding: Finding;
  finding_label: string;
  counts: Counts;
  days_out_of_date: number;
  replay_decision: string | null;
  stability: Stability | null;
  forks: number;
}

export interface Overview {
  totals: {
    runs: number;
    paused: number;
    used_replaced: number;
    decision_affected: number;
    unsourced_claims: number;
    runs_with_unsourced: number;
  };
  ranked: RunSummary[];
  replaced: { old: string; new: string; on: string; on_label: string; kind: string; runs_using_old: string[] }[];
  llm: string;
}

export interface Evidence {
  id: string;
  kind: "chunk" | "tool";
  label: string;
  text: string;
  step: number;
  agent: string;
  chunk_id?: string;
  version_status?: Status;
  days_out_of_date?: number;
  current_label?: string;
  retired_on?: string | null;
}

export interface Attribution {
  input: string;
  share: number;
  change: number;
  drove: boolean;
  supports: boolean | null;
}

export interface Claim {
  id: string;
  text: string;
  agent: string;
  step: number;
  inputs: string[];
  value: string | number | null;
  kind: "claim" | "decision";
  status: Status;
  replaced_via: string[];
  attribution: Attribution[];
  main_source: string | null;
}

export interface GraphNode {
  id: string;
  type: "evidence" | "claim" | "decision";
  kind?: string;
  label: string;
  text: string;
  value?: string | number | null;
  column: number;
  step: number;
  agent: string | null;
  status: Status;
  weight: number;
  on_path: boolean;
  retired_on?: string | null;
  days_out_of_date?: number;
}

export interface GraphEdge {
  from: string;
  to: string;
  type: "drove" | "context" | "replaces";
  share: number | null;
  on_path: boolean;
  status: "replaced" | "current" | "replaces";
}

export interface StepRow {
  step: number;
  name: string;
  label: string;
  agent: string;
  irreversible: boolean;
  ran: boolean;
  cached: boolean;
  seconds: number;
  tokens: number;
  model_calls: number;
  tool_calls: number;
  retrievals: number;
}

export interface Replay {
  run_id: string;
  status: RunStatus;
  from_step: number;
  swaps: Record<string, string>;
  decision_before: string | null;
  decision_after: string | null;
  decision_changed: boolean;
  claims: { id: string; before: string; after: string | null; changed: boolean }[];
}

export interface RunEvent {
  id: string;
  run_id: string;
  step: number | null;
  kind: "breakpoint" | "resumed" | "forked" | "blocked" | "rejected";
  detail: Record<string, unknown> & { message?: string; rule?: string; suggested_swaps?: Record<string, string> };
  at: string;
}

export interface Brief {
  id: string;
  status: RunStatus;
  forked_at: number | null;
  fork_reason: string | null;
  swaps: Record<string, string>;
  created_at: string;
}

export interface Rule {
  key: string;
  label: string;
  when: "before" | "after";
  default_on: boolean;
  on: boolean;
}

export interface Report {
  run: Run;
  last_step: number;
  decision: { value: string; text: string } | null;
  finding: Finding;
  finding_label: string;
  first_wrong_step: { step: number; agent: string; label: string } | null;
  days_out_of_date: number;
  evidence: Record<string, Evidence>;
  claims: Record<string, Claim>;
  decision_path: string[];
  replay: Replay | null;
  stability: Stability | null;
  steps: StepRow[];
  counts: Counts;
  graph: { columns: string[]; nodes: GraphNode[]; edges: GraphEdge[] };
  read: { headline: string; text: string; sources: string[] };
  events: RunEvent[];
  feedback: { id: string; verdict: string; note: string; author: string; at: string }[];
  forks: Brief[];
  parent: Brief | null;
  rules: Rule[];
}

export interface Span {
  id: string;
  step: number;
  agent: string;
  kind: string;
  name: string;
  input: unknown;
  output: unknown;
  chunk_ids: string[];
  tokens_in: number;
  tokens_out: number;
  started: number;
  ended: number;
  error: string | null;
  cached: number;
}

export interface StepState {
  run_id: string;
  step: number;
  state: {
    evidence: Record<string, Evidence>;
    claims: Record<string, Claim>;
    messages: { from: string; to: string; step: number; claim_ids: string[] }[];
    scratch: Record<string, Record<string, unknown>>;
    decision: { value: string; text: string } | null;
  };
  diff: {
    evidence: { added: string[]; changed: string[]; removed: string[] };
    claims: { added: string[]; changed: string[]; removed: string[] };
    messages: { added: { from: string; to: string; claim_ids: string[] }[] };
    scratch: Record<string, Record<string, unknown>>;
    decision: { value: string; text: string } | null;
  };
  spans: Span[];
}
