// Hand-rolled layout for the evidence graph: columns are agents (left to right),
// rows are steps (top to bottom). No graph library.
import type { GraphEdge, GraphNode } from "./types";

export interface Placed extends GraphNode {
  x: number; // centre
  y: number; // centre
  w: number;
  h: number;
  shape: "circle" | "pill";
}

export interface Layout {
  width: number;
  height: number;
  columns: { name: string; x: number }[];
  nodes: Placed[];
  byId: Record<string, Placed>;
  rowTops: { step: number; top: number; height: number }[];
}

const TOP = 56;
const EVIDENCE_X = 48;
const FIRST_AGENT_X = 340;
const AGENT_W = 184;
const PILL_W = 160;
const PILL_H = 66;
const EV_GAP = 56;
export const EV_LABEL_END = 236; // from the evidence dot centre
const CLAIM_GAP = 80;

export function radius(n: GraphNode): number {
  if (n.type === "decision") return 32;
  return Math.round(8 + Math.min(1, n.weight) * 14);
}

export function layoutGraph(columns: string[], nodes: GraphNode[]): Layout {
  const steps = Array.from(new Set(nodes.map((n) => n.step))).sort((a, b) => a - b);
  const colX = columns.map((_, i) => {
    if (i === 0) return EVIDENCE_X;
    if (i === columns.length - 1) return FIRST_AGENT_X + (columns.length - 2) * AGENT_W + 40;
    return FIRST_AGENT_X + (i - 1) * AGENT_W + PILL_W / 2;
  });

  const rowTops: Layout["rowTops"] = [];
  let top = TOP;
  for (const s of steps) {
    const inRow = nodes.filter((n) => n.step === s);
    const ev = inRow.filter((n) => n.column === 0).length;
    const perCol = new Map<number, number>();
    inRow.filter((n) => n.column > 0).forEach((n) => perCol.set(n.column, (perCol.get(n.column) ?? 0) + 1));
    const claims = Math.max(0, ...perCol.values());
    const height = Math.max(ev * EV_GAP, claims * CLAIM_GAP, 76) + 12;
    rowTops.push({ step: s, top, height });
    top += height;
  }

  const placed: Placed[] = [];
  for (const row of rowTops) {
    const inRow = nodes.filter((n) => n.step === row.step);
    const counters = new Map<number, number>();
    // evidence that was retrieved goes before versions that were not
    const ordered = [...inRow].sort((a, b) => Number(a.status === "not_retrieved") - Number(b.status === "not_retrieved"));
    for (const n of ordered) {
      const i = counters.get(n.column) ?? 0;
      counters.set(n.column, i + 1);
      const isEv = n.column === 0;
      const circle = n.type !== "claim";
      const r = radius(n);
      placed.push({
        ...n,
        x: colX[n.column],
        y: row.top + (isEv ? 28 + i * EV_GAP : 42 + i * CLAIM_GAP),
        w: circle ? r * 2 : PILL_W,
        h: circle ? r * 2 : PILL_H,
        shape: circle ? "circle" : "pill",
      });
    }
  }

  const byId = Object.fromEntries(placed.map((p) => [p.id, p]));
  const width = colX[colX.length - 1] + 120;
  return { width, height: top + 24, columns: columns.map((name, i) => ({ name, x: colX[i] })), nodes: placed, byId, rowTops };
}

/** SVG path for an edge. */
export function edgePath(e: GraphEdge, a: Placed, b: Placed): string {
  if (e.type === "replaces") {
    // both in the evidence column: bow out to the left
    const x = a.x - a.w / 2;
    const x2 = b.x - b.w / 2;
    const bow = Math.min(x, x2) - 26;
    return `M${x} ${a.y} C${bow} ${a.y}, ${bow} ${b.y}, ${x2} ${b.y}`;
  }
  if (a.column === b.column) {
    const sy = a.y + a.h / 2;
    const ty = b.y - b.h / 2;
    return `M${a.x} ${sy} C${a.x} ${sy + 20}, ${b.x} ${ty - 20}, ${b.x} ${ty}`;
  }
  // evidence labels sit to the right of the dot, so evidence edges start after the label
  const sx = a.type === "evidence" ? a.x + EV_LABEL_END : a.x + a.w / 2;
  const tx = b.x - b.w / 2;
  const dx = Math.max(40, (tx - sx) / 2);
  return `M${sx} ${a.y} C${sx + dx} ${a.y}, ${tx - dx} ${b.y}, ${tx} ${b.y}`;
}
