import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { edgePath, layoutGraph } from "../layout";
import { claimName, decisionWord, statusWord } from "../format";
import type { Report } from "../types";

export interface GraphFilters {
  documents: boolean;
  tools: boolean;
  context: boolean; // show inputs that were in context but did not drive the claim
}

interface Props {
  report: Report;
  tone: "run" | "now";
  visibleStep: number;
  selected: string | null;
  onSelect: (id: string) => void;
  filters: GraphFilters;
  children?: ReactNode; // overlays (pause card)
}

const versionOf = (label: string) => Number(label.match(/ v(\d+) /)?.[1] ?? 1);

/** Columns are agents, rows are steps; size shows how much a node drove the decision. */
export default function EvidenceGraph({ report, tone, visibleStep, selected, onSelect, filters, children }: Props) {
  const { columns, nodes, edges } = report.graph;
  const shownNodes = useMemo(
    () =>
      nodes.filter((n) => {
        if (n.type !== "evidence") return true;
        if (n.kind === "tool") return filters.tools;
        return filters.documents;
      }),
    [nodes, filters],
  );
  const layout = useMemo(() => layoutGraph(columns, shownNodes), [columns, shownNodes]);

  // scale the stage down to fit narrow containers (never below 0.7; then scroll)
  const wrap = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setScale(Math.max(0.7, Math.min(1, el.clientWidth / layout.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [layout.width]);

  const visible = (id: string) => (layout.byId[id]?.step ?? 99) <= visibleStep;
  // On the decision path: replaced links glow coral, current links glow teal
  // when the run is healthy (replay), and stay neutral otherwise.
  const healthy = tone === "now" || report.counts.replaced === 0;
  const flowTone = (status: string) => (status === "replaced" ? "bad" : healthy ? "good" : "neutral");

  return (
    <div className="graph-wrap" ref={wrap}>
      <div className="graph-sizer" style={{ width: layout.width * scale, height: layout.height * scale }}>
        <div className="graph-stage" style={{ width: layout.width, height: layout.height, transform: `scale(${scale})` }}>
          {layout.columns.map((c, i) => (
            <div key={c.name} className="col-head" style={{ left: i === 0 ? 8 : c.x - 80, width: i === 0 ? 200 : 160, textAlign: i === 0 ? "left" : "center" }}>
              {c.name}
            </div>
          ))}
          {layout.rowTops.map((r) => (
            <div key={r.step} className="row-rule" style={{ top: r.top }} aria-hidden="true">
              <span>Step {r.step}</span>
            </div>
          ))}

          <svg className="edges" width={layout.width} height={layout.height} aria-hidden="true">
            {edges.map((e) => {
              const a = layout.byId[e.from];
              const b = layout.byId[e.to];
              if (!a || !b) return null;
              if (e.type === "context" && !filters.context) return null;
              const d = edgePath(e, a, b);
              const on = visible(e.from) && visible(e.to);
              const cls =
                e.type === "replaces"
                  ? "edge edge-replaces"
                  : e.type === "context"
                    ? "edge edge-context"
                    : e.on_path
                      ? `edge edge-path ${flowTone(e.status)}`
                      : e.status === "replaced"
                        ? "edge edge-bad"
                        : "edge edge-drove";
              const w = e.type === "drove" ? 1.25 + (e.share ?? 0) * 2.25 : 1.25;
              return (
                <g key={`${e.from}-${e.to}`} className={on ? "" : "is-hidden"}>
                  <path d={d} className={cls} strokeWidth={w} />
                  {e.on_path && <path d={d} className={`edge-flow ${flowTone(e.status)}`} />}
                </g>
              );
            })}
          </svg>

          {layout.nodes.map((n) => {
            const hidden = !visible(n.id);
            const sel = selected === n.id ? "is-selected" : "";
            const status = `n-${n.status}`;
            if (n.shape === "pill") {
              return (
                <button
                  key={n.id}
                  type="button"
                  className={`node pill ${status} ${sel} ${hidden ? "is-hidden" : ""}`}
                  style={{ left: n.x - n.w / 2, top: n.y - n.h / 2, width: n.w, height: n.h }}
                  onClick={() => onSelect(n.id)}
                  aria-label={`${claimName(n.id)}, ${statusWord[n.status]}: ${n.text}`}
                  aria-pressed={selected === n.id}
                >
                  <span className="pill-top">
                    {claimName(n.id)}
                    {n.status !== "current" && <span className="pill-status">{statusWord[n.status]}</span>}
                  </span>
                  <span className="pill-text">{n.text}</span>
                </button>
              );
            }
            const isDecision = n.type === "decision";
            return (
              <div key={n.id} className={`node-wrap ${hidden ? "is-hidden" : ""}`} style={{ left: n.x - n.w / 2, top: n.y - n.h / 2 }}>
                <button
                  type="button"
                  className={`node dot ${isDecision ? "decision" : ""} ${status} ${sel}`}
                  style={{ width: n.w, height: n.h }}
                  onClick={() => onSelect(n.id)}
                  aria-label={`${isDecision ? "Decision" : n.label}, ${statusWord[n.status]}`}
                  aria-pressed={selected === n.id}
                />
                {isDecision ? (
                  <div className="dot-label decision-label" style={{ top: n.h + 8, left: n.w / 2 - 70 }}>
                    {decisionWord(String(n.value ?? ""))}
                  </div>
                ) : (
                  <div className="dot-label" style={{ left: n.w + 10, top: n.h / 2 - 10 }}>
                    <span className="dot-title">{n.label}</span>
                    {n.status === "retired" && <span className="dot-note bad">retired, {n.days_out_of_date} days old</span>}
                    {n.status === "not_retrieved" && <span className="dot-note good">in force, replaces v{versionOf(n.label) - 1}; not retrieved</span>}
                    {n.kind === "tool" && <span className="dot-note">tool result</span>}
                  </div>
                )}
              </div>
            );
          })}
          {children}
        </div>
      </div>
    </div>
  );
}
