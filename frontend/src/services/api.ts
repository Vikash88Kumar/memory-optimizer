import type {
  Conversation, EvidenceItem, GraphData, Memory, MemoryEvent, Message, NodeDetail, SystemStatus,
  TurnContextInfo, User,
} from "../types";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const TOKEN_KEY = "memora.token";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the MEMORA server. Check that the backend is running.");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep default */
    }
    if (res.status === 401) tokenStore.clear();
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  login: (username: string, password: string) =>
    request<{ token: string; user: User }>("/api/auth/login", { method: "POST", body: json({ username, password }) }),
  register: (username: string, password: string) =>
    request<{ token: string; user: User }>("/api/auth/register", { method: "POST", body: json({ username, password }) }),
  me: () => request<User>("/api/auth/me"),

  conversations: () => request<Conversation[]>("/api/conversations"),
  createConversation: () => request<Conversation>("/api/conversations", { method: "POST", body: json({}) }),
  deleteConversation: (id: string) => request<{ deleted: boolean }>(`/api/conversations/${id}`, { method: "DELETE" }),
  messages: (id: string) => request<Message[]>(`/api/conversations/${id}/messages`),
  send: (id: string, content: string) =>
    request<{ user_message: Message; assistant_message: Message; context: TurnContextInfo }>(
      `/api/conversations/${id}/messages`, { method: "POST", body: json({ content }) }),

  memories: (params: { q?: string; type?: string; status?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return request<Memory[]>(`/api/memories?${qs.toString()}`);
  },
  memory: (id: string) => request<Memory>(`/api/memories/${id}`),
  editMemory: (id: string, patch: Partial<Pick<Memory, "content" | "type" | "importance" | "scope">>) =>
    request<Memory>(`/api/memories/${id}`, { method: "PATCH", body: json(patch) }),
  confirmMemory: (id: string, accept: boolean) =>
    request<Memory>(`/api/memories/${id}/confirm`, { method: "POST", body: json({ accept }) }),
  forgetMemory: (id: string) =>
    request<{ forgotten: string[]; message: string }>(`/api/memories/${id}`, { method: "DELETE" }),
  evidence: (id: string) => request<{ evidence: EvidenceItem[]; conversation_id: string | null }>(`/api/memories/${id}/evidence`),
  history: (id: string) =>
    request<{ history: { at: string; action: string; content: string; reason: string }[];
      related: { id: string; content: string; status: string; relation: string }[]; events: MemoryEvent[] }>(
      `/api/memories/${id}/history`),

  graph: (includeSuperseded: boolean) => request<GraphData>(`/api/graph?include_superseded=${includeSuperseded}`),
  node: (id: string) => request<NodeDetail>(`/api/graph/nodes/${id}`),

  activity: (action?: string) => request<MemoryEvent[]>(`/api/activity?limit=300${action ? `&action=${action}` : ""}`),
  activityStreamUrl: () => `${BASE}/api/activity/stream?token=${encodeURIComponent(tokenStore.get() ?? "")}`,

  status: () => request<SystemStatus>("/api/system/status"),
  jobs: () => request<{ pending: number }>("/api/system/jobs"),
  advanceClock: (days: number) =>
    request<{ clock: string; offset_days: number; expired: number }>("/api/demo/clock", { method: "POST", body: json({ advance_days: days }) }),
  resetClock: () =>
    request<{ clock: string; offset_days: number; expired: number }>("/api/demo/clock", { method: "POST", body: json({ reset: true }) }),
  resetDemo: () => request<{ reset: boolean }>("/api/demo/reset", { method: "POST" }),
};
