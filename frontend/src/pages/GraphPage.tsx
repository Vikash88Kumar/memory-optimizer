import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Empty, ErrorBanner, Loading } from "../components/Feedback";
import { MemoryRow } from "./MemoryExplorerPage";
import { radialLayout } from "../lib/graphLayout";
import { api } from "../services/api";
import type { GraphData, NodeDetail } from "../types";

const KIND_STYLE: Record<string, { bg: string; border: string }> = {
  user: { bg: "#1B2430", border: "#1B2430" },
  preference: { bg: "#FBF1C2", border: "#D9BC2D" },
  goal: { bg: "#E3ECFB", border: "#2F6FDE" },
  difficulty: { bg: "#F8E3DF", border: "#C2412D" },
  strategy: { bg: "#E3F0E8", border: "#3C7A55" },
  constraint: { bg: "#F3E8FA", border: "#8A55B5" },
};
const DEFAULT_STYLE = { bg: "#FFFFFF", border: "#CBD3DC" };

type GraphNodeData = { label: string; kind: string; selected: boolean };
const CENTER_HANDLE = { top: "50%", left: "50%", transform: "translate(-50%, -50%)", opacity: 0, width: 1, height: 1,
  minWidth: 0, minHeight: 0, border: 0, pointerEvents: "none" as const };

/** Handles sit at the node centre so straight edges run centre to centre (floating-edge look). */
function GraphNodeView({ data }: NodeProps<Node<GraphNodeData>>) {
  const s = KIND_STYLE[data.kind] ?? DEFAULT_STYLE;
  const isUser = data.kind === "user";
  return (
    <div style={{
      background: s.bg, border: `1.5px solid ${s.border}`, borderRadius: isUser ? 999 : 6, color: isUser ? "#EEF1F4" : "#1B2430",
      fontSize: 13, padding: isUser ? "10px 16px" : "6px 10px", maxWidth: 190, fontWeight: data.selected || isUser ? 700 : 400,
      boxShadow: data.selected ? "0 0 0 3px #F2D64B" : "none", cursor: "pointer",
    }}>
      {data.label}
      <Handle type="target" position={Position.Top} style={CENTER_HANDLE} />
      <Handle type="source" position={Position.Bottom} style={CENTER_HANDLE} />
    </div>
  );
}
const NODE_TYPES = { memory: GraphNodeView };

export function GraphPage() {
  const [data, setData] = useState<GraphData | null>(null);
  const [history, setHistory] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.graph(history));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [history]);
  useEffect(() => void load(), [load]);
  useEffect(() => {
    const h = () => void load();
    window.addEventListener("memora:refresh", h);
    return () => window.removeEventListener("memora:refresh", h);
  }, [load]);

  const loadDetail = useCallback(async (id: string) => {
    try {
      setDetail(await api.node(id));
    } catch {
      setDetail(null);
      setSelected(null);
    }
  }, []);
  useEffect(() => {
    if (selected) void loadDetail(selected);
  }, [selected, loadDetail]);

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [] as Node<GraphNodeData>[], edges: [] as Edge[] };
    const pos = new Map(radialLayout(data).map((p) => [p.id, p]));
    const nodes: Node<GraphNodeData>[] = data.nodes.map((n) => {
      const p = pos.get(n.id) ?? { x: 0, y: 0 };
      return { id: n.id, type: "memory", position: { x: p.x, y: p.y },
        data: { label: n.kind === "user" ? "You" : n.label, kind: n.kind, selected: selected === n.id } };
    });
    const edges: Edge[] = data.edges.map((e) => ({
      id: e.id, source: e.source, target: e.target, type: "straight", label: e.relation.replace(/_/g, " "),
      style: { stroke: e.status === "superseded" ? "#9AA4B1" : "#5B6675", strokeDasharray: e.status === "superseded" ? "5 4" : undefined },
      labelStyle: { fontSize: 11, fill: "#5B6675" }, labelBgStyle: { fill: "#EEF1F4" },
    }));
    return { nodes, edges };
  }, [data, selected]);

  return (
    <div className="grid h-screen grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px]">
      <section className="flex min-h-[420px] flex-col">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-5 py-3">
          <div>
            <h1 className="text-2xl">Knowledge graph</h1>
            <p className="text-xs text-graphite">Built from your stored memories. Every link points back to the memories that support it.</p>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} />
            Show replaced links (dashed)
          </label>
        </header>
        <div className="relative flex-1">
          {error && <div className="p-5"><ErrorBanner message={error} onRetry={load} /></div>}
          {!data && !error && <div className="p-5"><Loading label="Building graph" /></div>}
          {data && data.nodes.length <= 1 && <Empty title="No connections yet">Share a preference, goal or difficulty in Chat to grow the graph.</Empty>}
          {data && data.nodes.length > 1 && (
            <ReactFlow key={`${history}-${data.nodes.length}-${data.edges.length}`} nodes={nodes} edges={edges} nodeTypes={NODE_TYPES} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.2} onNodeClick={(_, n) => setSelected(n.id)}
              nodesConnectable={false} proOptions={{ hideAttribution: true }}>
              <Background gap={24} color="#CBD3DC" />
              <Controls showInteractive={false} />
            </ReactFlow>
          )}
        </div>
      </section>
      <aside className="overflow-y-auto border-l border-rule bg-sheet px-4 py-4" aria-label="Node details">
        {!detail ? (
          <p className="text-sm text-graphite">Select a node to see its relationships, the memories behind it and their evidence.</p>
        ) : (
          <div className="space-y-4">
            <div>
              <h2 className="text-xl">{detail.node.kind === "user" ? "You" : detail.node.label}</h2>
              <p className="text-xs text-graphite">{detail.node.kind}</p>
            </div>
            <section>
              <h3 className="text-sm font-bold font-sans">Relationships</h3>
              <ul className="mt-1 space-y-1 text-sm">
                {detail.relationships.map((r) => (
                  <li key={r.id} className={r.status === "superseded" ? "text-graphite line-through" : ""}>
                    {r.direction === "out" ? `${r.relation.replace(/_/g, " ")} ${r.other}` : `${r.other} ${r.relation.replace(/_/g, " ")} this`}
                  </li>
                ))}
              </ul>
            </section>
            {detail.memories.length > 0 && (
              <section>
                <h3 className="text-sm font-bold font-sans">Linked memories</h3>
                <ul className="divide-y divide-rule">
                  {detail.memories.map((m) => (
                    <MemoryRow key={m.id} memory={m} onChanged={() => { void load(); if (selected) void loadDetail(selected); }} />
                  ))}
                </ul>
              </section>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
