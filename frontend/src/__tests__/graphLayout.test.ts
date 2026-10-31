import { radialLayout } from "../lib/graphLayout";
import type { GraphData } from "../types";

const data: GraphData = {
  nodes: [
    { id: "u", label: "Ana", kind: "user", memory_ids: [] },
    { id: "p", label: "Code-first explanations", kind: "preference", memory_ids: ["m1"] },
    { id: "g", label: "AI Agents", kind: "goal", memory_ids: ["m2"] },
    { id: "t", label: "NLP", kind: "topic", memory_ids: ["m2"] },
  ],
  edges: [
    { id: "e1", source: "u", target: "p", relation: "prefers", status: "active", memory_ids: ["m1"] },
    { id: "e2", source: "u", target: "g", relation: "wants_to", status: "active", memory_ids: ["m2"] },
    { id: "e3", source: "g", target: "t", relation: "builds_on", status: "active", memory_ids: ["m2"] },
  ],
};

test("places the user at the centre and every node exactly once", () => {
  const pos = radialLayout(data);
  expect(pos).toHaveLength(4);
  expect(new Set(pos.map((p) => p.id)).size).toBe(4);
  expect(pos.find((p) => p.id === "u")).toMatchObject({ x: 0, y: 0 });
});

test("direct neighbours sit on the inner ring and second-hop nodes further out", () => {
  const pos = new Map(radialLayout(data, 200, 400).map((p) => [p.id, p]));
  const r = (id: string) => Math.hypot(pos.get(id)!.x, pos.get(id)!.y);
  expect(r("p")).toBeCloseTo(200);
  expect(r("g")).toBeCloseTo(200);
  expect(r("t")).toBeCloseTo(400);
});
