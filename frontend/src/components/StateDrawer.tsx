import { useEffect, useState } from "react";
import { api } from "../api";
import { claimName } from "../format";
import type { StepState } from "../types";

/** What the agents held after one step, and what changed during it. */
export default function StateDrawer({ runId, step, label, onClose }: { runId: string; step: number; label: string; onClose: () => void }) {
  const [data, setData] = useState<StepState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    api.state(runId, step).then(setData).catch((e: Error) => setError(e.message));
  }, [runId, step]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={`State after step ${step}`} onClick={(e) => e.stopPropagation()}>
        <div className="row between start">
          <div>
            <div className="muted small">State after step {step}</div>
            <h2 className="h3">{label}</h2>
          </div>
          <button type="button" className="btn btn-quiet" onClick={onClose} autoFocus>
            Close
          </button>
        </div>
        {error && <p className="error">{error}</p>}
        {!data && !error && <p className="muted">Loading…</p>}
        {data && (
          <div className="stack-16">
            <section>
              <h3 className="h4">Added to the context</h3>
              {data.diff.evidence.added.length === 0 && <p className="muted small">No new evidence.</p>}
              <ul className="list">
                {data.diff.evidence.added.map((id) => {
                  const ev = data.state.evidence[id];
                  return (
                    <li key={id}>
                      <span className="diff-add" aria-hidden="true">+</span>
                      <div>
                        <div className="strong">{ev.label}</div>
                        <div className="muted small clamp-2">{ev.text}</div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
            <section>
              <h3 className="h4">Claims made</h3>
              {data.diff.claims.added.length === 0 && <p className="muted small">No new claims.</p>}
              <ul className="list">
                {data.diff.claims.added.map((id) => (
                  <li key={id}>
                    <span className="diff-add" aria-hidden="true">+</span>
                    <div>
                      <div className="strong">{claimName(id)}</div>
                      <div className="small">{data.state.claims[id].text}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
            {data.diff.messages.added.length > 0 && (
              <section>
                <h3 className="h4">Handed over</h3>
                <ul className="list">
                  {data.diff.messages.added.map((m, i) => (
                    <li key={i}>
                      <span className="diff-add" aria-hidden="true">→</span>
                      <div className="small">
                        {m.from} to {m.to}: {m.claim_ids.map(claimName).join(", ")}
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {Object.keys(data.diff.scratch).length > 0 && (
              <section>
                <h3 className="h4">Working memory</h3>
                <pre className="code">{JSON.stringify(data.diff.scratch, null, 2)}</pre>
              </section>
            )}
            <section>
              <h3 className="h4">Calls in this step</h3>
              <div className="scroll-x">
                <table className="table compact">
                  <thead>
                    <tr>
                      <th scope="col">Kind</th>
                      <th scope="col">Name</th>
                      <th scope="col">Time</th>
                      <th scope="col">Tokens</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.spans
                      .filter((s) => s.kind !== "invoke_agent")
                      .map((s) => (
                        <tr key={s.id}>
                          <td>{s.kind.replace("_", " ")}</td>
                          <td>
                            {s.name}
                            {s.cached ? <span className="muted small"> (reused)</span> : null}
                          </td>
                          <td>{(s.ended - s.started).toFixed(2)} s</td>
                          <td>{s.tokens_in + s.tokens_out || "—"}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}
