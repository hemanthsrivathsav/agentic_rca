import { useEffect, useState } from "react";
import { claimName, decisionWord } from "../format";
import type { Claim } from "../types";

/** "Prove it": the experiments behind one claim. Every row is a re-run that
 * actually happened (hide an input, or swap in the current version of a source),
 * which is what separates this from a model's explanation of a trace. */
export default function ProofDialog({ claim, onClose }: { claim: Claim; onClose: () => void }) {
  const proof = claim.proof;
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Long tables (pair-wise experiments) collapse to the rows that changed something.
  const quiet = proof.rows.filter((r) => r.kind === "hide" && !r.changed);
  const collapse = quiet.length > 4 && !showAll;
  const rows = collapse ? proof.rows.filter((r) => r.kind !== "hide" || r.changed) : proof.rows;
  const isDecision = claim.kind === "decision";
  const show = (text: string, value: string | number | null) => (isDecision && typeof value === "string" ? decisionWord(value) : text);

  return (
    <div className="drawer-backdrop center-dialog" onClick={onClose}>
      <div className="proof" role="dialog" aria-modal="true" aria-label={`Proof for ${claimName(claim.id)}`} onClick={(e) => e.stopPropagation()}>
        <div className="row between start gap-8">
          <div>
            <div className="muted small">Prove it: {claimName(claim.id)}</div>
            <h2 className="proof-title serif">{isDecision ? decisionWord(String(claim.value)) : claim.text}</h2>
          </div>
          <button type="button" className="btn btn-quiet" onClick={onClose} autoFocus>
            Close
          </button>
        </div>

        <p className="muted small">
          Each row ran the step again with one change. Nothing here is the agent explaining itself: if the answer changed, that input
          mattered.
        </p>

        <div className="scroll-x">
          <table className="table proof-table">
            <thead>
              <tr>
                <th scope="col">Experiment</th>
                <th scope="col">What the agent said</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={`proof-${r.kind} ${r.changed ? "is-changed" : ""}`}>
                  <td className="strong">{r.label}</td>
                  <td>{show(r.text, r.value)}</td>
                  <td>
                    {r.kind === "baseline" ? (
                      <span className="result-chip quiet">Baseline</span>
                    ) : r.changed ? (
                      <span className={`result-chip ${r.kind === "swap" ? "good" : "bad"}`}>
                        {r.kind === "swap" ? (isDecision ? "Decision flips" : "Changes") : "Changed: it mattered"}
                      </span>
                    ) : (
                      <span className="result-chip quiet">No change</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {collapse && (
          <button type="button" className="btn btn-quiet btn-sm" onClick={() => setShowAll(true)}>
            Show {quiet.length} experiments that changed nothing
          </button>
        )}

        <div className={`verdict ${proof.proven ? (proof.cause_confirmed ? "confirmed" : "proven") : "unproven"}`}>
          <div className="verdict-head">
            {proof.cause_confirmed ? "Cause confirmed" : proof.proven ? "Drivers proven" : "Cannot be proven from evidence"}
            <span className="muted small">
              {proof.reruns} re-runs, {proof.model_calls} model calls
            </span>
          </div>
          <p>{proof.verdict}</p>
        </div>
      </div>
    </div>
  );
}
