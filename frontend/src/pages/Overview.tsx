import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { decisionWord, findingTone, runStatusWord, when } from "../format";
import { go, runPath } from "../router";
import type { Overview as OverviewData, RunSummary } from "../types";

type Filter = "all" | "bad" | "warn" | "ok";

export default function Overview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    Promise.all([api.overview(), api.runs()])
      .then(([o, r]) => {
        setData(o);
        setRuns(r);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const shown = useMemo(
    () => runs.filter((r) => filter === "all" || findingTone(r.finding, r.status) === filter),
    [runs, filter],
  );

  async function act(fn: () => Promise<unknown>, after?: (v: unknown) => void) {
    setBusy(true);
    try {
      const v = await fn();
      after ? after(v) : await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) return <main className="page"><p className="error" role="alert">Could not reach the API: {error}. Start the backend on port 8000.</p></main>;
  if (!data) return <main className="page"><p className="muted">Loading runs…</p></main>;

  const t = data.totals;
  const worst = data.ranked[0];
  const count = (tone: Filter) => runs.filter((r) => tone === "all" || findingTone(r.finding, r.status) === tone).length;

  return (
    <main className="page stack">
      <section className="attention" aria-label="What needs attention">
        <div className="attention-lead">
          <h1 className="serif">
            {t.decision_affected > 0
              ? `${t.decision_affected} ${t.decision_affected === 1 ? "decision rests" : "decisions rest"} on a retired policy.`
              : "No decision rests on a retired policy."}
          </h1>
          <p>
            {t.used_replaced} of {t.runs} runs read a replaced source. Replay with the current version shows which of them
            would have decided differently. Standard tracing marked every one of these runs as successful.
          </p>
          <div className="row gap-8">
            {worst && (
              <a className="btn btn-light" href={`#${runPath(worst.id)}`}>
                Open the worst case
              </a>
            )}
            <button
              type="button"
              className="btn btn-ghost-dark"
              disabled={busy}
              onClick={() => act(() => api.startRun("KYC-2041"), (r) => go(runPath((r as { run: { id: string } }).run.id)))}
            >
              Run KYC-2041 again with breakpoints on
            </button>
          </div>
        </div>
        <ol className="ranked" aria-label="Ranked by exposure">
          {data.ranked.map((r, i) => (
            <li key={r.id}>
              <span className="muted-dark">{i + 1}</span>
              <div className="min0">
                <a className="ranked-title" href={`#${runPath(r.id)}`}>
                  {r.id}, {r.subject}
                </a>
                <div className="muted-dark small">
                  {r.status === "paused"
                    ? `Paused at step ${r.paused_at}, waiting for a reviewer`
                    : `${decisionWord(r.decision)} as run; replay with current versions: ${decisionWord(r.replay_decision)}`}
                </div>
              </div>
              <span className={`ranked-tag ${r.finding === "confirmed_by_replay" || r.status === "paused" ? "bad" : "warn"}`}>
                {r.status === "paused" ? "Decision on hold" : r.finding_label}
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section className="tiles" aria-label="Totals">
        <Tile label="Runs traced" value={t.runs} note="KYC onboarding" />
        <Tile label="Paused by a breakpoint" value={t.paused} note="waiting for a reviewer" />
        <Tile label="Read a replaced source" value={t.used_replaced} note={`decision changed on replay: ${t.decision_affected}`} tone="bad" />
        <Tile label="Claims without a source" value={t.unsourced_claims} note={`in ${t.runs_with_unsourced} runs`} tone="warn" />
      </section>

      <div className="split">
        <section className="card grow" aria-label="All runs">
          <div className="card-head">
            <h2>All runs</h2>
            <div className="row gap-6" role="group" aria-label="Filter runs">
              {(
                [
                  ["all", `All ${count("all")}`],
                  ["bad", `Needs action ${count("bad")}`],
                  ["warn", `Check ${count("warn")}`],
                  ["ok", `Healthy ${count("ok")}`],
                ] as [Filter, string][]
              ).map(([k, label]) => (
                <button key={k} type="button" className={`chip ${filter === k ? "on" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="scroll-x">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col">Subject</th>
                  <th scope="col">Decision</th>
                  <th scope="col">Claims</th>
                  <th scope="col">Finding</th>
                  <th scope="col">When</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <a className="strong" href={`#${runPath(r.id)}`}>
                        {r.id}
                      </a>
                      <div className="muted small">{runStatusWord[r.status]}</div>
                    </td>
                    <td>{r.subject}</td>
                    <td>{r.status === "paused" ? `Paused at step ${r.paused_at}` : decisionWord(r.decision)}</td>
                    <td>
                      <HealthBar counts={r.counts} />
                    </td>
                    <td className={`strong tone-${findingTone(r.finding, r.status)}`}>
                      {r.status === "paused" ? "Waiting at a breakpoint" : r.finding_label}
                    </td>
                    <td className="muted">{when(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="card side" aria-label="Recently replaced">
          <h2>Recently replaced</h2>
          <p className="muted small">Sources that changed, and the runs still reading the old version.</p>
          <ol className="timeline">
            {data.replaced.map((x) => (
              <li key={x.old}>
                <div className="muted small">
                  {x.on_label}, {x.kind}
                </div>
                <div className="strong">
                  {x.new} replaced {x.old.replace(/^.* (v\d+ §.*)$/, "$1")}
                </div>
                <div className={`small ${x.runs_using_old.length ? "tone-bad" : "tone-ok"}`}>
                  {x.runs_using_old.length ? `${x.runs_using_old.length} runs still read the old version` : "No runs affected"}
                </div>
              </li>
            ))}
          </ol>
          <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => act(api.resetDemo)}>
            Reset demo data
          </button>
          <p className="muted small">Model: {data.llm === "mock" ? "offline mock (scripted)" : data.llm}</p>
        </aside>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </main>
  );
}

function Tile({ label, value, note, tone }: { label: string; value: number; note: string; tone?: "bad" | "warn" }) {
  return (
    <div className="card tile">
      <div className="muted small">{label}</div>
      <div className={`tile-value ${tone ? `tone-${tone}` : ""}`}>{value}</div>
      <div className="muted small">{note}</div>
    </div>
  );
}

function HealthBar({ counts }: { counts: RunSummary["counts"] }) {
  const total = Math.max(1, counts.claims);
  const label = `${counts.current} current, ${counts.replaced} replaced, ${counts.nosource} without a source`;
  return (
    <div>
      <div className="health" role="img" aria-label={label}>
        <span className="h-ok" style={{ width: `${(counts.current / total) * 100}%` }} />
        <span className="h-bad" style={{ width: `${(counts.replaced / total) * 100}%` }} />
        <span className="h-warn" style={{ width: `${(counts.nosource / total) * 100}%` }} />
      </div>
      <div className="muted small">{label}</div>
    </div>
  );
}
