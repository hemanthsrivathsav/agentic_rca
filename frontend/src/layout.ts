// Hand-rolled layout for the evidence graph, following design v2: evidence on the left,
// one column per agent, the outcome on the right. Claims step down in run order, each
// piece of evidence sits level with the claim it feeds, and the decision sits in the
// vertical middle. Positions depend only on the graph's structure, never on statuses,
// so a run, its replay and its forks share one layout and can animate between each other.
// No graph library.
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
}

const TOP = 56; // below the column heads
const FIRST_ROW = 44; // centre of the first claim, below TOP
const CLAIM_ROW = 86;
const EVIDENCE_X = 60;
const FIRST_AGENT_X = 340;
const AGENT_W = 184;
const PILL_W = 160;
const PILL_H = 66;
const EV_GAP = 60; // least distance between two evidence dots
const FAMILY_GAP = 72; // versions of one source sit together, oldest on top
const LABEL_ROOM = 48; // labels under the lowest dots

export function radius(n: GraphNode): number {
  if (n.type === "decision") return 32;
  return Math.round(8 + Math.min(1, n.weight) * 14);
}

/** Width of the graph before any spreading: the size it is drawn at on normal screens. */
export function naturalWidth(columnCount: number): number {
  return FIRST_AGENT_X + (columnCount - 2) * AGENT_W + 40 + 120;
}

const versionOf = (n: GraphNode) => Number(n.id.match(/@v(\d+)#/)?.[1] ?? 0);

/** `extra` widens the graph on big screens: it is shared equally between the gaps between columns. */
export function layoutGraph(columns: string[], nodes: GraphNode[], edges: GraphEdge[], extra = 0): Layout {
  const gap = columns.length > 1 ? extra / (columns.length - 1) : 0;
  const colX = columns.map((_, i) => {
    if (i === 0) return EVIDENCE_X;
    if (i === columns.length - 1) return FIRST_AGENT_X + (columns.length - 2) * AGENT_W + 40 + gap * i;
    return FIRST_AGENT_X + (i - 1) * AGENT_W + PILL_W / 2 + gap * i;
  });
  const y: Record<string, number> = {};

  // claims: one row each, in run order
  const claims = nodes.filter((n) => n.type === "claim").sort((a, b) => a.step - b.step || a.id.localeCompare(b.id));
  claims.forEach((c, i) => (y[c.id] = TOP + FIRST_ROW + i * CLAIM_ROW));
  const claimY = claims.map((c) => y[c.id]);
  const middle = claimY.length ? (Math.min(...claimY) + Math.max(...claimY)) / 2 : TOP + FIRST_ROW;
  nodes.filter((n) => n.type === "decision").forEach((n) => (y[n.id] = middle));

  // evidence: level with the claim it feeds (the one it drove most, else the highest one)
  const feeds = (id: string): number | undefined => {
    const out = edges.filter((e) => e.from === id && e.type !== "replaces" && y[e.to] !== undefined);
    out.sort((a, b) => Number(b.type === "drove") - Number(a.type === "drove") || (b.share ?? 0) - (a.share ?? 0) || y[a.to] - y[b.to]);
    return out.length ? y[out[0].to] : undefined;
  };

  // versions of one source (joined by "replaces" edges) are placed as one block
  const evidence = nodes.filter((n) => n.type === "evidence");
  const groupOf: Record<string, string[]> = Object.fromEntries(evidence.map((n) => [n.id, [n.id]]));
  for (const e of edges) {
    const a = groupOf[e.from];
    const b = groupOf[e.to];
    if (e.type !== "replaces" || !a || !b || a === b) continue;
    a.push(...b);
    b.forEach((id) => (groupOf[id] = a));
  }
  const byIdIn = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const units = Array.from(new Set(Object.values(groupOf))).map((ids) => {
    const members = ids.map((id) => byIdIn[id]).sort((a, b) => versionOf(a) - versionOf(b) || a.id.localeCompare(b.id));
    const wants = members.map((m) => feeds(m.id)).filter((v): v is number => v !== undefined);
    return { members, want: wants.length ? Math.min(...wants) : Infinity };
  });
  units.sort((a, b) => a.want - b.want || a.members[0].step - b.members[0].step || a.members[0].id.localeCompare(b.members[0].id));
  let cursor = TOP + FIRST_ROW;
  for (const u of units) {
    const at = Math.max(Number.isFinite(u.want) ? u.want : cursor, cursor);
    u.members.forEach((m, k) => (y[m.id] = at + k * FAMILY_GAP));
    cursor = y[u.members[u.members.length - 1].id] + EV_GAP;
  }

  const placed: Placed[] = nodes.map((n) => {
    const circle = n.type !== "claim";
    const r = radius(n);
    return {
      ...n,
      x: colX[n.column],
      y: y[n.id] ?? cursor,
      w: circle ? r * 2 : PILL_W,
      h: circle ? r * 2 : PILL_H,
      shape: circle ? "circle" : "pill",
    };
  });

  const byId = Object.fromEntries(placed.map((p) => [p.id, p]));
  const bottom = Math.max(TOP + FIRST_ROW, ...placed.map((p) => p.y + p.h / 2));
  return {
    width: colX[colX.length - 1] + 120,
    height: bottom + LABEL_ROOM,
    columns: columns.map((name, i) => ({ name, x: colX[i] })),
    nodes: placed,
    byId,
  };
}

/** SVG path for an edge. Edges leave from the right side of a node and enter on the left. */
export function edgePath(e: GraphEdge, a: Placed, b: Placed): string {
  if (e.type === "replaces") {
    // two versions of one source: a straight line between the dots
    const [top, low] = a.y < b.y ? [a, b] : [b, a];
    return `M${top.x} ${top.y + top.h / 2} L${low.x} ${low.y - low.h / 2}`;
  }
  if (a.column === b.column) {
    const sy = a.y + a.h / 2;
    const ty = b.y - b.h / 2;
    return `M${a.x} ${sy} C${a.x} ${sy + 20}, ${b.x} ${ty - 20}, ${b.x} ${ty}`;
  }
  const sx = a.x + a.w / 2;
  // an input sitting just below the outcome comes in from underneath
  if (b.type === "decision" && a.y > b.y + b.h && b.x - b.w / 2 - sx < 80) {
    const by = b.y + b.h / 2;
    return `M${sx} ${a.y} C${b.x} ${a.y}, ${b.x} ${a.y}, ${b.x} ${by}`;
  }
  const tx = b.x - b.w / 2;
  const dx = Math.max(40, (tx - sx) / 2);
  return `M${sx} ${a.y} C${sx + dx} ${a.y}, ${tx - dx} ${b.y}, ${tx} ${b.y}`;
}
