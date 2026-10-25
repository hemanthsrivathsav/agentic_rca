// Hand-rolled layout and edge routing for the evidence graph, following design v2:
// evidence on the left, one column per agent, the outcome on the right. No graph library.
//
// Layout. Every claim gets a row of its own, in run order; each piece of evidence sits
// level with the claim it feeds; versions of one source are grouped; the decision sits
// in the vertical middle. Positions depend only on the graph's structure, never on
// statuses, so a run, its replay and its forks share one layout and animate between
// each other.
//
// Routing. Because no two claims share a row, a horizontal line along a claim's row can
// never hit another box. Edges therefore run horizontally along a row and only turn in
// the empty lanes between columns, each edge in its own slot of the lane, and each edge
// enters or leaves a box at its own port. That keeps any number of agents, steps and
// inputs readable: lines never cross boxes and never run on top of each other.
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
  /** usable x-range of the lane on the left of each column (index 1..n-1) */
  lanes: { from: number; to: number }[];
}

export type Point = [number, number];
export interface Route {
  d: string; // SVG path
  pts: Point[]; // the polyline before corners are rounded
}

const TOP = 56; // below the column heads
const FIRST_ROW = 44; // centre of the first claim, below TOP
const CLAIM_ROW = 86;
const EVIDENCE_X = 60;
const EV_LABEL_W = 196; // .dot-label width
const EV_MAX_R = 22; // largest evidence dot radius
const FIRST_AGENT_X = 350; // left edge of the first agent column
const AGENT_W = 210; // column pitch: a pill plus a 50px lane for edges
const PILL_W = 160;
const PILL_H = 66;
const DECISION_R = 32;
const DECISION_LABEL_W = 140; // .decision-label width: lanes stop before it
const STRAIGHT_DY = 20; // ends closer than this (one row) are joined by a straight line, not a turn
const EV_GAP = 60; // least distance between two evidence dots
const FAMILY_GAP = 72; // versions of one source sit together, oldest on top
const LABEL_ROOM = 48; // labels under the lowest dots
const PORT_GAP = 12; // spacing between edges on one side of a box
const LANE_PAD = 8; // keep turns this far from the boxes on either side of a lane
const MIN_SLOT = 8; // least spacing between two edges turning in one lane; lanes widen to fit
const MAX_DECISION_R = 64; // the outcome grows (up to this) so every input gets its own port
const MAX_CORNER = 28;

export function radius(n: GraphNode): number {
  if (n.type === "decision") return DECISION_R;
  return Math.round(8 + Math.min(1, n.weight) * 14);
}

const versionOf = (n: GraphNode) => Number(n.id.match(/@v(\d+)#/)?.[1] ?? 0);

/** Which lane an edge turns in: the lane on the left of that column index. */
function laneOf(a: GraphNode, b: GraphNode, last: number): number {
  if (a.column < b.column) return a.type === "evidence" ? 1 : b.column;
  if (a.column > b.column) return b.column + 1;
  return Math.min(last, a.column + 1);
}

/**
 * `extra` widens the graph on big screens: it is shared equally between the gaps between
 * columns. Call with `extra = 0` to get the natural width.
 */
export function layoutGraph(columns: string[], nodes: GraphNode[], edges: GraphEdge[], extra = 0): Layout {
  const last = columns.length - 1;
  const agents = Math.max(0, columns.length - 2);
  const gap = columns.length > 1 ? extra / (columns.length - 1) : 0;
  const byIdIn = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const links = edges.filter((e) => e.type !== "replaces" && byIdIn[e.from] && byIdIn[e.to]);

  // the outcome grows with its inputs, so each one gets its own port on the circle
  const inputs = Math.max(0, ...nodes.filter((n) => n.type === "decision").map((d) => links.filter((e) => e.to === d.id).length));
  const decisionR = Math.min(MAX_DECISION_R, Math.max(DECISION_R, ((inputs - 1) * PORT_GAP) / 2 + 10));

  // the outcome column reaches as far left as its circle or its label, whichever is wider
  const reach = Math.max(decisionR, DECISION_LABEL_W / 2);

  // columns: fixed pitch, then each lane widens to fit the edges that turn in it, then the spread
  const base = columns.map((_, i) => {
    if (i === 0) return EVIDENCE_X;
    if (i === last) return FIRST_AGENT_X + agents * AGENT_W + reach;
    return FIRST_AGENT_X + PILL_W / 2 + (i - 1) * AGENT_W;
  });
  const leftOf = (xs: number[], i: number) => (i === last ? xs[i] - reach : xs[i] - PILL_W / 2);
  const rightOf = (xs: number[], i: number) => (i === 0 ? EVIDENCE_X + EV_MAX_R + 8 + EV_LABEL_W : xs[i] + PILL_W / 2);
  const demand = columns.map(() => 0);
  for (const e of links) demand[laneOf(byIdIn[e.from], byIdIn[e.to], last)]++;
  let shift = 0;
  const colX = base.map((x, i) => {
    if (i > 0) {
      const have = leftOf(base, i) - rightOf(base, i - 1);
      shift += Math.max(0, demand[i] * MIN_SLOT + 2 * LANE_PAD - have) + gap;
    }
    return x + shift;
  });
  const lanes = columns.map((_, i) => (i === 0 ? { from: 0, to: 0 } : { from: rightOf(colX, i - 1) + LANE_PAD, to: leftOf(colX, i) - LANE_PAD }));

  const y: Record<string, number> = {};

  // claims: one row each, in run order
  const claims = nodes.filter((n) => n.type === "claim").sort((a, b) => a.step - b.step || a.id.localeCompare(b.id));
  claims.forEach((c, i) => (y[c.id] = TOP + FIRST_ROW + i * CLAIM_ROW));
  const claimY = claims.map((c) => y[c.id]);
  const middle = claimY.length ? (Math.min(...claimY) + Math.max(...claimY)) / 2 : TOP + FIRST_ROW;
  // outcomes: around the vertical middle (one per row if there are several)
  const outcomes = nodes.filter((n) => n.type === "decision").sort((a, b) => a.step - b.step || a.id.localeCompare(b.id));
  outcomes.forEach((n, i) => (y[n.id] = Math.max(TOP + FIRST_ROW, middle + (i - (outcomes.length - 1) / 2) * CLAIM_ROW)));

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
    const r = n.type === "decision" ? decisionR : radius(n);
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
    width: colX[last] + reach + 24,
    height: bottom + LABEL_ROOM,
    columns: columns.map((name, i) => ({ name, x: colX[i] })),
    nodes: placed,
    byId,
    lanes,
  };
}

// --------------------------------------------------------------------------
// Edge routing
// --------------------------------------------------------------------------

type Side = "L" | "R";
interface Plan {
  key: string;
  e: GraphEdge;
  a: Placed;
  b: Placed;
  kind: "straight-down" | "forward" | "backward" | "around";
  aSide: Side | null; // null: leave from the centre (evidence dots)
  bSide: Side;
  lane: number; // lane the edge turns in
}

const keyOf = (e: GraphEdge) => `${e.from}-${e.to}`;

/** Point on the side of a node at vertical offset `off` from its centre. */
function portX(n: Placed, side: Side, off: number): number {
  const dir = side === "L" ? -1 : 1;
  if (n.shape === "pill") return n.x + (dir * n.w) / 2;
  const r = n.w / 2;
  return n.x + dir * Math.sqrt(Math.max(0, r * r - off * off));
}

/** Polyline to SVG path with rounded corners (radius limited by the segments next to it). */
function rounded(pts: Point[]): string {
  const f = (v: number) => Math.round(v * 10) / 10;
  let d = `M${f(pts[0][0])} ${f(pts[0][1])}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i - 1];
    const [x, y] = pts[i];
    const [nx, ny] = pts[i + 1];
    const lin = Math.hypot(x - px, y - py);
    const lout = Math.hypot(nx - x, ny - y);
    if (lin < 0.5 || lout < 0.5) continue;
    const r = Math.min(MAX_CORNER, lin / 2, lout / 2);
    d += ` L${f(x - ((x - px) / lin) * r)} ${f(y - ((y - py) / lin) * r)}`;
    d += ` Q${f(x)} ${f(y)} ${f(x + ((nx - x) / lout) * r)} ${f(y + ((ny - y) / lout) * r)}`;
  }
  const [lx, ly] = pts[pts.length - 1];
  return `${d} L${f(lx)} ${f(ly)}`;
}

/**
 * Route every edge. Rules:
 * - an edge travels along a row (its source's row, or for evidence its target's row) and turns
 *   only inside the lane between two columns;
 * - each edge gets its own port on the side of a box and its own slot in the lane;
 * - backward edges (an agent that works again later) and edges between two claims of one column
 *   with another box in between go around through the lane beside the column.
 */
export function routeEdges(layout: Layout, edges: GraphEdge[]): Record<string, Route> {
  const { byId, lanes, nodes } = layout;
  const last = layout.columns.length - 1;
  const out: Record<string, Route> = {};
  const plans: Plan[] = [];

  for (const e of edges) {
    const a = byId[e.from];
    const b = byId[e.to];
    if (!a || !b) continue;
    const key = keyOf(e);
    if (e.type === "replaces") {
      // two versions of one source: a straight line between the dots
      const [top, low] = a.y < b.y ? [a, b] : [b, a];
      const pts: Point[] = [[top.x, top.y + top.h / 2], [low.x, low.y - low.h / 2]];
      out[key] = { d: rounded(pts), pts };
      continue;
    }
    const lane = laneOf(a, b, last);
    if (a.column < b.column) {
      plans.push({ key, e, a, b, kind: "forward", aSide: a.type === "evidence" ? null : "R", bSide: "L", lane });
    } else if (a.column > b.column) {
      plans.push({ key, e, a, b, kind: "backward", aSide: "L", bSide: "R", lane });
    } else {
      const [lo, hi] = a.y < b.y ? [a.y, b.y] : [b.y, a.y];
      const blocked = nodes.some((n) => n.column === a.column && n.id !== a.id && n.id !== b.id && n.y > lo && n.y < hi);
      plans.push({ key, e, a, b, kind: blocked ? "around" : "straight-down", aSide: blocked ? "R" : null, bSide: blocked ? "R" : "L", lane });
    }
  }

  // ports: spread the edges on each side of a box, ordered by where their other end is
  const sides: Record<string, { plan: Plan; end: "a" | "b"; other: Placed }[]> = {};
  for (const p of plans) {
    if (p.kind === "straight-down") continue;
    if (p.aSide) (sides[`${p.a.id}|${p.aSide}`] ??= []).push({ plan: p, end: "a", other: p.b });
    (sides[`${p.b.id}|${p.bSide}`] ??= []).push({ plan: p, end: "b", other: p.a });
  }
  const offset: Record<string, number> = {}; // `${key}|a` or `${key}|b`
  for (const [sideKey, list] of Object.entries(sides)) {
    const n = byId[sideKey.split("|")[0]];
    list.sort((p, q) => p.other.y - q.other.y || p.other.x - q.other.x);
    const inset = n.shape === "pill" ? 12 : 8;
    const sp = list.length > 1 ? Math.min(PORT_GAP, (n.h - 2 * inset) / (list.length - 1)) : 0;
    list.forEach((it, i) => (offset[`${it.plan.key}|${it.end}`] = (i - (list.length - 1) / 2) * sp));
  }

  // end points of every planned edge
  const ends = new Map<string, { sx: number; sy: number; tx: number; ty: number }>();
  for (const p of plans) {
    if (p.kind === "straight-down") continue;
    const oa = offset[`${p.key}|a`] ?? 0;
    const ob = offset[`${p.key}|b`] ?? 0;
    const sy = p.a.y + (p.aSide ? oa : 0);
    const sx = p.aSide ? portX(p.a, p.aSide, oa) : p.a.x + p.a.w / 2;
    const ty = p.b.y + ob;
    ends.set(p.key, { sx, sy, tx: portX(p.b, p.bSide, ob), ty });
  }

  // lane slots: every edge that has to turn gets its own x in its lane. Ordered so that turns
  // nest instead of crossing: edges that turn just before their target put the longest drop
  // nearest the target; edges that turn just after their source put it nearest the source.
  const turning: Record<number, { key: string; sortKey: number }[]> = {};
  for (const p of plans) {
    const end = ends.get(p.key);
    // nearly level ends (within one row's band) are joined straight: that band holds no other box
    if (!end || (p.kind !== "around" && Math.abs(end.sy - end.ty) < STRAIGHT_DY)) continue;
    const dy = Math.abs(end.sy - end.ty);
    const nearTarget = p.kind === "forward" && p.aSide !== null; // claim -> later column
    (turning[p.lane] ??= []).push({ key: p.key, sortKey: nearTarget ? dy : -dy });
  }
  const slotX: Record<string, number> = {};
  for (const [laneIdx, list] of Object.entries(turning)) {
    const lane = lanes[Number(laneIdx)] ?? { from: 0, to: 0 };
    list.sort((p, q) => p.sortKey - q.sortKey || p.key.localeCompare(q.key));
    const width = Math.max(0, lane.to - lane.from);
    list.forEach((it, i) => (slotX[it.key] = lane.from + ((i + 0.5) * width) / list.length));
  }

  for (const p of plans) {
    let pts: Point[];
    if (p.kind === "straight-down") {
      const [top, low] = p.a.y < p.b.y ? [p.a, p.b] : [p.b, p.a];
      pts = [[top.x, top.y + top.h / 2], [low.x, low.y - low.h / 2]];
      if (p.a !== top) pts.reverse();
    } else {
      const { sx, sy, tx, ty } = ends.get(p.key)!;
      const x = slotX[p.key];
      pts = x === undefined ? [[sx, sy], [tx, ty]] : [[sx, sy], [x, sy], [x, ty], [tx, ty]];
    }
    out[p.key] = { d: rounded(pts), pts };
  }
  return out;
}
