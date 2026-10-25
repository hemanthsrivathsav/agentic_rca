import { useState } from "react";
import { api } from "../api";
import { claimName, day, pct, statusWord } from "../format";
import type { Report, Status } from "../types";

const chipTone: Record<Status, string> = {
  current: "ok",
  replaced: "bad",
  retired: "bad",
  nosource: "warn",
  not_retrieved: "quiet",
  not_yet_effective: "quiet",
  swapped_out: "quiet",
};

export function AnalystRead({ report }: { report: Report }) {
  const tone = report.counts.replaced > 0 || report.run.status === "paused" ? "bad" : report.counts.nosource ? "warn" : "ok";
  return (
    <section className="card pad" aria-label="Analyst read">
      <div className="row gap-8 strong small">
        <span className={`dot-mark tone-bg-${tone}`} aria-hidden="true" />
        Analyst read
      </div>
      <p className="serif read">{report.read.text}</p>
      <div className="row wrap gap-6">
        {report.read.sources.map((s) => (
          <span key={s} className="source-chip">
            {s}
          </span>
        ))}
      </div>
    </section>
  );
}

export function NodeDetail({ report, id }: { report: Report; id: string | null }) {
  if (!id) {
    return (
      <section className="card pad" aria-label="Selected item">
        <p className="muted">Select a node in the graph to see what drove it.</p>
      </section>
    );
  }
  const claim = report.claims[id];
  const node = report.graph.nodes.find((n) => n.id === id);
  const ev = report.evidence[id];
  const status = (claim?.status ?? node?.status ?? "current") as Status;

  // what this item drove (outgoing) and what drove it (incoming)
  const drovers = (claim?.attribution ?? []).slice().sort((a, b) => b.share - a.share);
  const drives = Object.values(report.claims)
    .map((c) => ({ c, a: c.attribution.find((a) => a.input === id) }))
    .filter((x) => x.a && x.a.drove);

  const label = (inp: string) => report.evidence[inp]?.label ?? claimName(inp);
  return (
    <section className="card pad stack-12" aria-label="Selected item">
      <div className="row between gap-8 start">
        <div>
          <div className="muted small">
            {claim
              ? claim.kind === "decision"
                ? "Outcome"
                : `Claim by the ${claim.agent}`
              : ev
                ? ev.kind === "tool"
                  ? "Tool result"
                  : "Document"
                : node?.status === "swapped_out"
                  ? "Document, swapped out"
                  : "Document, not retrieved"}
          </div>
          <h3 className="h3">{claim ? claimName(id) : (node?.label ?? id)}</h3>
        </div>
        <span className={`status-chip tone-${chipTone[status]}`}>{statusWord[status]}</span>
      </div>
      <blockquote className={`quote tone-border-${chipTone[status]}`}>{claim?.text ?? node?.text}</blockquote>

      {ev?.version_status === "retired" && (
        <p className="small tone-bad">
          Replaced on {day(ev.retired_on)} by {ev.current_label}. It was {ev.days_out_of_date} days out of date on the run date.
        </p>
      )}
      {node?.status === "not_retrieved" && <p className="small muted">This is the version in force on the run date. The agent never saw it.</p>}
      {node?.status === "swapped_out" && <p className="small muted">This run was forked with the current version in its place, so the agents never saw this one.</p>}

      {claim && drovers.length > 0 && (
        <div>
          <div className="muted small">What drove it (leave-one-out)</div>
          <ul className="bars">
            {drovers.map((a) => (
              <li key={a.input}>
                <div className="row between small">
                  <span>{label(a.input)}</span>
                  <span className="strong">{a.drove ? pct(a.share) : "did not drive it"}</span>
                </div>
                <div className="bar">
                  <span className={a.drove ? (report.claims[a.input]?.status === "replaced" || report.evidence[a.input]?.version_status === "retired" ? "fill-bad" : "fill-ok") : ""} style={{ width: pct(a.drove ? a.share : 0) }} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {claim && drovers.length === 0 && claim.kind === "claim" && (
        <p className="small tone-warn">Nothing in the agent's context explains this claim. It most likely came from the model's own knowledge.</p>
      )}
      {drives.length > 0 && (
        <div className="small">
          <span className="muted">Drove: </span>
          {drives.map((x) => `${claimName(x.c.id)} (${pct(x.a!.share)})`).join(", ")}
        </div>
      )}
      <div className="facts small">
        <div>
          <span className="muted">Step</span>
          <strong>{claim?.step ?? node?.step}</strong>
        </div>
        <div>
          <span className="muted">Agent</span>
          <strong>{claim?.agent ?? ev?.agent ?? "—"}</strong>
        </div>
      </div>
    </section>
  );
}

export function StabilityCard({ report }: { report: Report }) {
  const st = report.stability;
  if (!st) return null;
  const order = Object.entries(st.counts).sort((a, b) => b[1] - a[1]);
  return (
    <section className="card pad" aria-label="Decision stability">
      <div className="row between">
        <h3 className="h4">How stable is the decision?</h3>
        <span className="muted small">{st.samples} samples</span>
      </div>
      <div className="stack-bar" role="img" aria-label={order.map(([k, v]) => `${v} ${k}`).join(", ")}>
        {order.map(([k, v]) => (
          <span key={k} className={k === "approve" ? "fill-ink" : "fill-ok"} style={{ width: `${(v / st.samples) * 100}%` }} />
        ))}
      </div>
      <div className="row between small">
        {order.map(([k, v]) => (
          <span key={k}>
            <strong>{v}</strong> {k}
          </span>
        ))}
      </div>
      <p className="muted small">
        {st.stable
          ? `All ${st.samples} re-samples of the decision step agree.`
          : "Re-sampling the decision step gave different answers. An unstable decision is a risk signal on its own."}
      </p>
    </section>
  );
}

export function FeedbackCard({ report }: { report: Report }) {
  const [saved, setSaved] = useState<string | null>(report.feedback[report.feedback.length - 1]?.verdict ?? null);
  const [note, setNote] = useState("");
  const send = async (verdict: "correct" | "wrong" | "needs_review") => {
    await api.feedback(report.run.id, verdict, note);
    setSaved(verdict);
    setNote("");
  };
  const words = { correct: "Correct", wrong: "Wrong", needs_review: "Needs review" } as const;
  return (
    <section className="card pad stack-12" aria-label="Mark this decision">
      <h3 className="h4">Mark this decision</h3>
      <div className="row wrap gap-6">
        {(Object.keys(words) as (keyof typeof words)[]).map((k) => (
          <button key={k} type="button" className={`chip ${saved === k ? "on" : ""}`} aria-pressed={saved === k} onClick={() => send(k)}>
            {words[k]}
          </button>
        ))}
      </div>
      <label className="field">
        <span className="small muted">Note for the audit trail (optional)</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why?" />
      </label>
      {saved && <p className="small muted">Saved as “{words[saved as keyof typeof words]}”.</p>}
    </section>
  );
}
