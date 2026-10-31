import type { GraphData } from "../types";

export interface Positioned { id: string; x: number; y: number }

const KIND_ORDER = ["preference", "goal", "topic", "skill", "difficulty", "strategy", "constraint", "experience",
  "decision", "feedback", "fact", "tool", "concept", "other"];

/** Radial layout: the user in the centre, directly-related nodes on an inner ring grouped by kind,
 *  everything else (topics linked to those nodes) on an outer ring next to its parent. */
export function radialLayout(data: GraphData, inner = 240, outer = 420): Positioned[] {
  const user = data.nodes.find((n) => n.kind === "user");
  const out: Positioned[] = [];
  if (!user) return data.nodes.map((n, i) => ({ id: n.id, x: (i % 6) * 200, y: Math.floor(i / 6) * 140 }));
  out.push({ id: user.id, x: 0, y: 0 });
  const direct = new Set(data.edges.filter((e) => e.source === user.id).map((e) => e.target));
  const firstRing = data.nodes
    .filter((n) => direct.has(n.id))
    .sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) || a.label.localeCompare(b.label));
  const angleOf = new Map<string, number>();
  firstRing.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(firstRing.length, 1) - Math.PI / 2;
    angleOf.set(n.id, a);
    out.push({ id: n.id, x: Math.cos(a) * inner, y: Math.sin(a) * inner });
  });
  const placed = new Set(out.map((p) => p.id));
  const rest = data.nodes.filter((n) => !placed.has(n.id));
  const childCount = new Map<string, number>();
  rest.forEach((n, i) => {
    const parentEdge = data.edges.find((e) => (e.target === n.id && angleOf.has(e.source)) || (e.source === n.id && angleOf.has(e.target)));
    const parent = parentEdge ? (angleOf.has(parentEdge.source) ? parentEdge.source : parentEdge.target) : null;
    let a: number;
    if (parent) {
      const k = childCount.get(parent) ?? 0;
      childCount.set(parent, k + 1);
      a = (angleOf.get(parent) ?? 0) + (k % 2 === 0 ? 1 : -1) * Math.ceil(k / 2) * 0.28;
    } else {
      a = (2 * Math.PI * i) / Math.max(rest.length, 1);
    }
    out.push({ id: n.id, x: Math.cos(a) * outer, y: Math.sin(a) * outer });
  });
  return out;
}
