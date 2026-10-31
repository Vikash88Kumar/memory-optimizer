export type MemoryType =
  | "preference" | "interest" | "knowledge" | "learning_difficulty" | "goal" | "decision"
  | "constraint" | "experience" | "feedback" | "strategy" | "fact";

export type MemoryStatus = "active" | "superseded" | "expired" | "deleted" | "rejected";

export interface User {
  id: string;
  username: string;
  display_name: string | null;
  is_demo: boolean;
  workspaces: string[];
  clock_offset_seconds: number;
}

export interface Memory {
  id: string;
  type: MemoryType;
  key: string | null;
  content: string;
  scope: string;
  confidence: number;
  importance: number;
  origin: "explicit" | "inferred" | "assistant";
  status: MemoryStatus;
  confirmation: "not_required" | "pending" | "confirmed" | "rejected";
  temporary: boolean;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
  strength_now?: number;
  evidence_message_ids: string[];
  source: { conversation_id: string | null; message_ids: string[]; origin?: string };
  superseded_by: string | null;
  supersedes: string[];
  seed?: boolean;
  retrieval_count?: number;
}

export interface UsedMemory {
  ref: string;
  id: string;
  tier: "core" | "retrieved";
  type: MemoryType;
  content: string;
  scope: string;
  confidence: number;
  importance: number;
  score: number;
  similarity: number;
  strength: number;
  activation: number | null;
  reasons: string[];
  evidence_message_ids: string[];
  confirmation: string;
  expires_at: string | null;
}

export interface TokenUsage {
  core: number;
  bridge: number;
  episode: number;
  memories: number;
  evidence: number;
  total: number;
  full_history: number;
}

export interface TurnContextInfo {
  memories_used: UsedMemory[];
  overridden: { id: string; content: string; type: string; reason: string }[];
  episode: { id: string; title: string; turns: number; switched: boolean; bridge: string | null; closed_episode_id: string | null };
  tokens: TokenUsage;
  evidence: { kind: string; episode_id?: string; title?: string; message_id?: string }[];
  evidence_reason: string;
  retrieval_backend: "mongodb_vector_search" | "local_fallback";
  offline_model: boolean;
  extraction_scheduled?: boolean;
  trivial: boolean;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  redacted?: boolean;
  context?: TurnContextInfo;
}

export interface Conversation {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
  total_tokens: number;
  seed?: boolean;
}

export interface EvidenceItem {
  message_id: string;
  conversation_id?: string;
  role?: string;
  created_at?: string;
  content?: string;
  redacted?: boolean;
  missing?: boolean;
  note?: string;
}

export interface MemoryEvent {
  id: string;
  action: string;
  reason: string;
  memory_id: string | null;
  memory_ids: string[];
  memory_type: string | null;
  content_preview: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface GraphNode { id: string; label: string; kind: string; memory_ids: string[] }
export interface GraphEdge { id: string; source: string; target: string; relation: string; status: string; memory_ids: string[] }
export interface GraphData { nodes: GraphNode[]; edges: GraphEdge[] }

export interface NodeDetail {
  node: { id: string; label: string; kind: string; created_at: string };
  relationships: { id: string; relation: string; status: string; direction: "in" | "out"; other: string; memory_ids: string[] }[];
  memories: Memory[];
}

export interface SystemStatus {
  llm_provider: string;
  llm_offline: boolean;
  chat_model: string | null;
  embedding_provider: string;
  embedding_offline: boolean;
  retrieval_backend: string;
  change_streams: boolean;
  vector_index_status: string;
  demo_tools: boolean;
  user_clock: string;
  pending_jobs: number;
}
