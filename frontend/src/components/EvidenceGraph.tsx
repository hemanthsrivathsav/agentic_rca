import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { edgePath, layoutGraph, naturalWidth, type Placed } from "../layout";
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

const WRAP_PADDING = 24; // .graph-wrap horizontal padding
const MAX_SPREAD = 1.35; // widest the columns spread, relative to the natural width
const MAX_SCALE = 1.35; // largest zoom on very wide canvases

const versionOf = (label: string) => Number(label.match(/ v(\d+) /)?.[1] ?? 1);

function EvidenceNote({ n }: { n: Placed }) {
  if (n.status === "retired") return <span className="dot-note bad">retired, {n.days_out_of_date} days old</span>;
  if (n.status === "not_retrieved") return <span className="dot-note good">in force, replaces v{versionOf(n.label) - 1}; not retrieved</span>;
  if (n.status === "swapped_out") return <span className="dot-note">swapped out in this run</span>;
  if (n.swapped_in) return <span className="dot-note good">swapped in for v{versionOf(n.label) - 1}</span>;
  if (n.kind === "tool") return <span className="dot-note">tool result</span>;
  return null;
}

/** Evidence on the left, one column per agent, the outcome on the right; size shows how much a node drove the decision. */
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

  // Fit the graph to the canvas. Narrow: scale down (never below 0.7; then scroll).
  // Wide: first spread the columns apart, then scale up so text stays readable on big screens.
  const wrap = useRef<HTMLDivElement>(null);
  const [avail, setAvail] = useState(0);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setAvail(el.clientWidth - WRAP_PADDING));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const natural = naturalWidth(columns.length);
  const spread = avail > natural ? Math.min(avail, natural * MAX_SPREAD) : natural;
  const scale = avail <= 0 ? 1 : avail <= natural ? Math.max(0.7, avail / natural) : Math.min(MAX_SCALE, avail / spread);
  const extra = spread - natural;
  const layout = useMemo(() => layoutGraph(columns, shownNodes, edges, extra), [columns, shownNodes, edges, extra]);

  const visible = (id: string) => (layout.byId[id]?.step ?? 99) <= visibleStep;
  // On the decision path: replaced links glow coral, current links glow teal
  // when the run is healthy (replay), and stay neutral otherwise.
  const healthy = tone === "now" || report.counts.replaced === 0;
  const flowTone = (status: string) => (status === "replaced" ? "bad" : healthy ? "good" : "neutral");

  return (
    <div className="graph-wrap" ref={wrap}>
      <div className="graph-sizer" style={{ width: layout.width * scale, height: layout.height * scale }}>
        <div className="graph-stage" style={{ width: layout.width, height: layout.height, transform: `scale(${scale})` }}>
          {layout.columns.map((c, i) => {
            const half = i === 0 ? c.x : 80;
            return (
              <div key={c.name} className="col-head" style={{ left: c.x - half, width: half * 2 }}>
                {c.name}
              </div>
            );
          })}

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
                    ? a.status === "nosource"
                      ? "edge edge-nosource"
                      : "edge edge-context"
                    : e.on_path
                      ? `edge edge-path ${flowTone(e.status)}`
                      : e.status === "replaced"
                        ? "edge edge-bad"
                        : "edge edge-drove";
              const w = e.type === "drove" ? 1.25 + (e.share ?? 0) * 2.25 : 1.25;
              const [top, low] = a.y < b.y ? [a, b] : [b, a];
              return (
                <g key={`${e.from}-${e.to}`} className={on ? "" : "is-hidden"}>
                  <path d={d} className={cls} strokeWidth={w} />
                  {e.on_path && <path d={d} className={`edge-flow ${flowTone(e.status)}`} />}
                  {e.type === "replaces" && (
                    <text className="edge-label" x={top.x - 10} y={(top.y + top.h / 2 + low.y - low.h / 2) / 2 + 4} textAnchor="end">
                      replaces
                    </text>
                  )}
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
                  // to the right of the dot, under the edge that leaves it
                  <div className="dot-label" style={{ left: n.w + 8, top: n.h / 2 + 3 }}>
                    <span className="dot-title">{n.label}</span>
                    <EvidenceNote n={n} />
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
