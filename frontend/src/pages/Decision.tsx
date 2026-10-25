import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import EvidenceGraph, { type GraphFilters } from "../components/EvidenceGraph";
import { AnalystRead, FeedbackCard, NodeDetail, StabilityCard } from "../components/Panels";
import StateDrawer from "../components/StateDrawer";
import { claimName, day, decisionWord, pct, runStatusWord, statusWord } from "../format";
import { go, runPath } from "../router";
import type { Report } from "../types";

const PLAY_MS = 900;

/** "edd-policy@v4#2.1" -> "v4 §2.1" */
const shortVersion = (chunkId: string) => chunkId.replace(/^(.*)@v(\d+)#(.*)$/, "v$2 §$3");

export default function Decision({ runId }: { runId: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const [replay, setReplay] = useState<Report | null>(null);
  const [mode, setMode] = useState<"run" | "now">("run");
  const [view, setView] = useState<"graph" | "table">("graph");
  const [visibleStep, setVisibleStep] = useState(99);
  const [playing, setPlaying] = useState(false);
  const [simPause, setSimPause] = useState(false);
  const [bpPassed, setBpPassed] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [drawerStep, setDrawerStep] = useState<number | null>(null);
  const [filters, setFilters] = useState<GraphFilters>({ documents: true, tools: true, context: true });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  // set when a report for the next run is already in hand (after a fork or resume)
  const preloaded = useRef<string | null>(null);

  // Show a report. The page stays mounted when the run changes, so the graph keeps its
  // nodes and animates from the old run to the new one instead of reloading.
  // `playFrom` replays the new run from that step to its end.
  const show = useCallback(async (rep: Report, playFrom?: number) => {
    stop();
    setReport(rep);
    setMode("run");
    setSimPause(false);
    setBpPassed(false);
    setError(null);
    setSelected((cur) => {
      if (cur && (rep.claims[cur] || rep.graph.nodes.some((n) => n.id === cur))) return cur;
      const firstBad = Object.values(rep.evidence).find((e) => e.version_status === "retired");
      return firstBad ? firstBad.id : "decision" in rep.claims ? "decision" : null;
    });
    if (playFrom !== undefined) startPlay(rep.last_step, playFrom, null, true);
    else setVisibleStep(rep.last_step);
    setReplay(rep.replay ? await api.report(rep.replay.run_id) : null);
  }, []);

  useEffect(() => {
    if (preloaded.current === runId) {
      preloaded.current = null;
      return;
    }
    let live = true;
    api
      .report(runId)
      .then((rep) => {
        if (live) show(rep);
      })
      .catch((e: Error) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [runId, show]);

  useEffect(() => () => stop(), []);

  const shown = mode === "now" && replay ? replay : report;

  const staleRuleOn = report?.rules.find((r) => r.key === "stale_evidence")?.on ?? false;
  // A completed run that read a retired source: during Play, show where a breakpoint would have fired.
  const simStep = report && mode === "run" && report.run.status === "completed" && report.first_wrong_step && staleRuleOn ? report.first_wrong_step.step : null;
  const realPause = report && mode === "run" && report.run.status === "paused";
  const pauseEvent = realPause ? [...report.events].reverse().find((e) => e.kind === "breakpoint") : undefined;

  function stop() {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
    setPlaying(false);
  }

  /** Advance the scrubber one step every PLAY_MS from `from` to `max`, stopping once at `sim` (a simulated breakpoint). */
  function startPlay(max: number, from: number, sim: number | null, passedAlready: boolean) {
    stop();
    let step = from;
    let passed = passedAlready;
    setVisibleStep(step);
    if (step >= max) return;
    setPlaying(true);
    timer.current = window.setInterval(() => {
      step += 1;
      setVisibleStep(step);
      if (sim && !passed && step === sim) {
        passed = true;
        setBpPassed(true);
        setSimPause(true);
        stop();
        return;
      }
      if (step >= max) stop();
    }, PLAY_MS);
  }

  /** At the simulated breakpoint: carry on with the current version, like design v2.
   * The automatic replay is exactly this fork (same step, same swap), and it is
   * already loaded, so switch to it and keep playing on the same graph: the evidence
   * re-points from v3 to v4 and the toggle moves to "With current versions". */
  function forkAndContinue() {
    if (!report || !simStep) return;
    if (replay) {
      setSimPause(false);
      setMode("now");
      startPlay(replay.last_step, simStep, null, true);
      return;
    }
    // replay not loaded (should not happen): make the fork on the server and open it
    act(() => api.fork(report.run.id, simStep, report.replay?.swaps ?? {}, "forked at breakpoint"), (r) => openRun(r, simStep));
  }

  function play() {
    if (!shown) return;
    if (playing) return stop();
    setSimPause(false);
    const max = shown.last_step;
    const restart = visibleStep >= max;
    const passed = restart ? false : bpPassed;
    setBpPassed(passed);
    startPlay(max, restart ? 0 : visibleStep, simStep, passed);
  }

  async function act<T>(fn: () => Promise<T>, then: (v: T) => void) {
    setBusy(true);
    try {
      then(await fn());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  /** Show the run an action produced, in place, and play it on from `playFrom`. */
  const openRun = (rep: Report, playFrom?: number) => {
    if (rep.run.id !== runId) {
      preloaded.current = rep.run.id;
      go(runPath(rep.run.id));
    }
    show(rep, playFrom);
  };

  const stats = useMemo(() => {
    if (!shown) return null;
    const secs = shown.steps.reduce((s, r) => s + r.seconds, 0);
    const toks = shown.steps.reduce((s, r) => s + r.tokens, 0);
    const calls = shown.steps.reduce((s, r) => s + r.model_calls, 0);
    return { secs, toks, calls };
  }, [shown]);

  if (error && !report) return <main className="page"><p className="error" role="alert">{error}</p></main>;
  if (!report || !shown || !stats) return <main className="page"><p className="muted">Loading run…</p></main>;

  const run = report.run;
  const bad = mode === "run" && report.counts.replaced > 0;
  const fw = report.first_wrong_step;
  const headline =
    mode === "now" && report.replay
      ? report.replay.decision_changed
        ? `With current versions, the decision becomes “${decisionWord(report.replay.decision_after)}”.`
        : `With current versions, the decision stays “${decisionWord(report.replay.decision_after)}”.`
      : realPause
        ? report.read.headline
        : shown.read.headline;
  const subhead =
    mode === "now" && replay && report.replay
      ? `Replayed from step ${report.replay.from_step} with ${Object.values(report.replay.swaps).map(shortVersion).join(", ")}. Steps 1 to ${report.replay.from_step - 1} were reused unchanged.`
      : realPause
        ? `Paused at step ${run.paused_at}. Choose how to continue.`
        : fw
          ? `First went wrong at step ${fw.step}, when the ${fw.agent} read a replaced source. Every span still reported success.`
          : report.parent && run.forked_at
            ? `Forked from ${report.parent.id} at step ${run.forked_at}${Object.keys(run.options.swaps ?? {}).length ? ` with ${Object.values(run.options.swaps ?? {}).map(shortVersion).join(", ")}` : ""}. Steps 1 to ${run.forked_at - 1} were reused.`
            : "No step read a replaced source.";

  return (
    <main className="page decision">
      <aside className="rail stack-16" aria-label="Run and filters">
        <section className="card pad">
          <div className="muted small">
            <a href="#/">Runs</a> / {run.id}
          </div>
          <h1 className="h2">{run.subject}</h1>
          <p className="muted small">
            KYC onboarding, run date {day(run.run_time)}
            <br />
            {runStatusWord[run.status]}, {report.counts.evidence} evidence items, {report.counts.claims} claims
          </p>
          {report.parent && (
            <p className="small">
              Fork of <a href={`#${runPath(report.parent.id)}`}>{report.parent.id}</a> from step {run.forked_at}
              {run.fork_reason ? ` (${run.fork_reason})` : ""}.
            </p>
          )}
        </section>

        <section className="card pad stack-4" aria-label="Show">
          <h2 className="h4">Show</h2>
          {(
            [
              ["documents", "Documents"],
              ["tools", "Tool results"],
              ["context", "Inputs that did not drive a claim"],
            ] as [keyof GraphFilters, string][]
          ).map(([k, label]) => (
            <label key={k} className="check">
              <input type="checkbox" checked={filters[k]} onChange={(e) => setFilters({ ...filters, [k]: e.target.checked })} />
              {label}
            </label>
          ))}
        </section>

        <section className="card pad stack-4" aria-label="Breakpoint rules">
          <h2 className="h4">Pause the run when</h2>
          {report.rules.map((r) => (
            <label key={r.key} className="check">
              <input
                type="checkbox"
                className="check-bad"
                checked={r.on}
                disabled={busy}
                onChange={(e) => act(() => api.setRule(run.id, r.key, e.target.checked), setReport)}
              />
              {r.label}
            </label>
          ))}
          <p className="muted small">Rules apply to new runs and forks of this run.</p>
        </section>

        <section className="legend small" aria-label="Legend">
          <div><span className="lg lg-ok" />Current evidence</div>
          <div><span className="lg lg-bad" />Replaced evidence</div>
          <div><span className="lg lg-warn" />No source found</div>
          <div><span className="lg lg-size" />Size shows how much it drove the decision</div>
        </section>
      </aside>

      <section className="center stack-16">
        <div className="canvas" aria-label="Evidence canvas">
          <div className="canvas-head">
            <div className="canvas-title">
              <h2 className="serif">{headline}</h2>
              <p>{subhead}</p>
            </div>
            <div className="canvas-controls">
              {report.replay && (
                <div className="seg" role="group" aria-label="Evidence shown">
                  <button type="button" aria-pressed={mode === "run"} onClick={() => { stop(); setMode("run"); setVisibleStep(report.last_step); }}>
                    As the agents ran it
                  </button>
                  <button type="button" aria-pressed={mode === "now"} onClick={() => { stop(); setSimPause(false); setMode("now"); setVisibleStep(replay?.last_step ?? 99); }}>
                    With current versions
                  </button>
                </div>
              )}
              <div className="seg seg-small" role="group" aria-label="View">
                <button type="button" aria-pressed={view === "graph"} onClick={() => setView("graph")}>Graph</button>
                <button type="button" aria-pressed={view === "table"} onClick={() => setView("table")}>Table</button>
              </div>
            </div>
          </div>

          {/* The pause card floats over the graph (as in design v2), so showing or hiding it never moves the page. */}
          <div className="canvas-body">
          {view === "graph" ? (
            <EvidenceGraph report={shown} tone={mode} visibleStep={visibleStep} selected={selected} onSelect={setSelected} filters={filters} />
          ) : (
            <ClaimsTable report={shown} />
          )}

          {(simPause || realPause) && (
            <div className="pause-banner" role="alert">
              <div className="pause-title">
                <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><rect x="2" y="1.5" width="3.5" height="11" rx="1" /><rect x="8.5" y="1.5" width="3.5" height="11" rx="1" /></svg>
                {realPause ? `Run paused at step ${run.paused_at}` : `With breakpoints on, this run would pause at step ${simStep}`}
              </div>
              <p>{realPause ? pauseEvent?.detail.message : `The ${fw?.agent} retrieved a replaced source. Nothing would have been decided yet.`}</p>
              <div className="row wrap gap-8">
                {realPause ? (
                  <>
                    {pauseEvent?.detail.suggested_swaps && (
                      <button type="button" className="btn btn-dark" disabled={busy} onClick={() => act(() => api.resume(run.id, "edit", pauseEvent?.detail.suggested_swaps), (r) => openRun(r, run.paused_at ?? undefined))}>
                        Swap in the current version
                      </button>
                    )}
                    <button type="button" className="btn btn-light-line" disabled={busy} onClick={() => act(() => api.resume(run.id, "approve"), (r) => openRun(r, run.paused_at ?? undefined))}>
                      Approve and continue
                    </button>
                    <button type="button" className="btn btn-light-line" disabled={busy} onClick={() => act(() => api.resume(run.id, "reject"), (r) => openRun(r))}>
                      Reject
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" className="btn btn-dark" disabled={busy} onClick={forkAndContinue}>
                      {report.replay ? `Fork with ${Object.values(report.replay.swaps).map(shortVersion).join(", ")} and continue` : "Fork with the current version"}
                    </button>
                    <button type="button" className="btn btn-light-line" onClick={() => { setSimPause(false); play(); }}>
                      Continue as it ran
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
          </div>

          <div className="scrubber">
            <button type="button" className="play" onClick={play} aria-label={playing ? "Pause" : "Play the run step by step"}>
              {playing ? (
                <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><rect x="2" y="1.5" width="3.5" height="11" rx="1" /><rect x="8.5" y="1.5" width="3.5" height="11" rx="1" /></svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 1.5v11l9.5-5.5z" /></svg>
              )}
            </button>
            <ol className="steps">
              {shown.steps.map((s) => {
                const done = s.ran && s.step <= visibleStep;
                const isBad = bad && fw && s.step >= fw.step && s.ran;
                const pin = (simStep === s.step && mode === "run") || (realPause && run.paused_at === s.step);
                return (
                  <li key={s.step}>
                    <button
                      type="button"
                      aria-current={s.step === visibleStep ? "step" : undefined}
                      className={`step ${done ? "done" : ""} ${isBad ? "bad" : ""}`}
                      onClick={() => { stop(); setVisibleStep(s.step); setSimPause(false); }}
                    >
                      <span className="step-bar" />
                      <span className="step-label">
                        {s.step}. {s.label}
                      </span>
                      <span className="step-meta">
                        {s.ran ? `${s.seconds.toFixed(1)} s, ${s.tokens} tok${s.cached ? ", reused" : ""}` : "not run"}
                      </span>
                    </button>
                    {pin && <span className="bp-pin" title="Breakpoint" />}
                  </li>
                );
              })}
            </ol>
          </div>
          <div className="canvas-foot">
            <span>
              {shown.steps.filter((s) => s.ran).length} steps, {stats.secs.toFixed(1)} s, {stats.toks.toLocaleString()} tokens, {stats.calls} model calls
            </span>
            <button
              type="button"
              className="btn btn-ghost-dark btn-sm"
              onClick={() => setDrawerStep(Math.min(visibleStep, shown.last_step))}
              disabled={visibleStep < 1}
            >
              Inspect state at step {Math.min(visibleStep, shown.last_step)}
            </button>
          </div>
        </div>

        <Branches report={report} />

        <section className="tiles" aria-label="Claims summary">
          <div className="card tile">
            <div className="muted small">Claims on current evidence</div>
            <div className="tile-value">{shown.counts.current} of {shown.counts.claims}</div>
          </div>
          <div className="card tile">
            <div className="muted small">Built on replaced evidence</div>
            <div className={`tile-value ${shown.counts.replaced ? "tone-bad" : "tone-ok"}`}>{shown.counts.replaced}</div>
          </div>
          <div className="card tile">
            <div className="muted small">Without a source</div>
            <div className={`tile-value ${shown.counts.nosource ? "tone-warn" : ""}`}>{shown.counts.nosource}</div>
          </div>
          <div className="card tile">
            <div className="muted small">Retrieved but unused</div>
            <div className="tile-value">{shown.counts.unused_evidence} of {shown.counts.evidence}</div>
          </div>
        </section>
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      <aside className="rail-right stack-16" aria-label="Explanation">
        <AnalystRead report={realPause ? report : shown} />
        <NodeDetail report={shown} id={selected && (shown.claims[selected] || shown.graph.nodes.some((n) => n.id === selected)) ? selected : null} />
        <StabilityCard report={shown} />
        {shown.decision && <FeedbackCard key={shown.run.id} report={shown} />}
      </aside>

      {drawerStep !== null && (
        <StateDrawer
          runId={shown.run.id}
          step={drawerStep}
          label={shown.steps.find((s) => s.step === drawerStep)?.label ?? ""}
          onClose={() => setDrawerStep(null)}
        />
      )}
    </main>
  );
}

function ClaimsTable({ report }: { report: Report }) {
  const rows = Object.values(report.claims).sort((a, b) => a.step - b.step);
  return (
    <div className="scroll-x table-dark-wrap">
      <table className="table table-dark">
        <thead>
          <tr>
            <th scope="col">Claim</th>
            <th scope="col">Agent</th>
            <th scope="col">Main source</th>
            <th scope="col">Drove</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const main = c.attribution.find((a) => a.input === c.main_source);
            return (
              <tr key={c.id}>
                <td>
                  <div className="strong">{claimName(c.id)}</div>
                  <div className="small">{c.kind === "decision" ? decisionWord(String(c.value)) : c.text}</div>
                </td>
                <td>{c.agent}</td>
                <td>{c.main_source ? report.evidence[c.main_source]?.label ?? claimName(c.main_source) : "None found"}</td>
                <td>{main ? pct(main.share) : "—"}</td>
                <td className={`strong on-dark-${c.status}`}>{statusWord[c.status]}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Built only from the report on screen: while the next run loads, `runId` is already the
// new id but the report is still the old one, and mixing the two would repeat a run.
function Branches({ report }: { report: Report }) {
  const current = report.run.id;
  const all = [
    ...(report.parent ? [{ id: report.parent.id, text: `Parent run`, sub: runStatusWord[report.parent.status] }] : []),
    { id: current, text: "This run", sub: runStatusWord[report.run.status] },
    ...report.forks.map((f) => ({
      id: f.id,
      text: `Fork from step ${f.forked_at}`,
      sub: f.fork_reason ?? "",
    })),
  ];
  const items = all.filter((b, i) => all.findIndex((x) => x.id === b.id) === i);
  if (items.length < 2) return null;
  return (
    <nav className="branches" aria-label="Forks of this run">
      <span className="muted small">Branches</span>
      {items.map((b) => (
        <a key={b.id} href={`#${runPath(b.id)}`} className={`branch ${b.id === current ? "on" : ""}`} aria-current={b.id === current ? "page" : undefined}>
          <span className="strong">{b.text}</span>
          <span className="muted small">
            {b.id}, {b.sub}
          </span>
        </a>
      ))}
    </nav>
  );
}
