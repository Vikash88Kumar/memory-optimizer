import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { MemoriesUsed } from "../components/MemoriesUsed";
import { ContextBudget } from "../components/ContextBudget";
import { ActivityTimeline } from "../pages/ActivityPage";
import type { Memory, MemoryEvent, TurnContextInfo } from "../types";

vi.mock("../services/api", () => ({
  api: {
    evidence: vi.fn().mockResolvedValue({ conversation_id: "c1", evidence: [
      { message_id: "m1", role: "user", content: "I prefer learning algorithms with visual examples.", created_at: "2026-10-31T10:00:00Z" },
    ] }),
    forgetMemory: vi.fn().mockResolvedValue({ forgotten: ["mem_1"], message: "ok" }),
    confirmMemory: vi.fn().mockResolvedValue({}),
    editMemory: vi.fn().mockResolvedValue({}),
    history: vi.fn().mockResolvedValue({ history: [], related: [], events: [] }),
  },
}));
import { api } from "../services/api";
import { MemoryRow } from "../pages/MemoryExplorerPage";

const ctx: TurnContextInfo = {
  memories_used: [{
    ref: "M1", id: "mem_1", tier: "core", type: "preference", content: "Prefers visual examples when learning algorithms",
    scope: "global", confidence: 0.95, importance: 0.8, score: 0.8, similarity: 0.7, strength: 0.9, activation: null,
    reasons: ["Core profile: high-confidence item pinned for this session"], evidence_message_ids: ["m1"],
    confirmation: "not_required", expires_at: null,
  }],
  overridden: [{ id: "mem_2", content: "Prefers short explanations", type: "preference", reason: "Overridden by a topic-specific preference for this question" }],
  episode: { id: "ep", title: "Binary search", turns: 1, switched: false, bridge: null, closed_episode_id: null },
  tokens: { core: 12, bridge: 0, episode: 30, memories: 20, evidence: 0, total: 62, full_history: 900 },
  evidence: [], evidence_reason: "", retrieval_backend: "mongodb_vector_search", offline_model: false, trivial: false,
};

test("Memories used panel shows count, reasons, overrides and loads original messages", async () => {
  render(<MemoriesUsed context={ctx} />);
  const toggle = screen.getByRole("button", { name: /memories used: 1/i });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(toggle);
  expect(screen.getByText("Prefers visual examples when learning algorithms")).toBeInTheDocument();
  expect(screen.getByText(/pinned for this session/)).toBeInTheDocument();
  expect(screen.getByText("Prefers short explanations")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /show original messages/i }));
  await waitFor(() => expect(screen.getByText(/I prefer learning algorithms/)).toBeInTheDocument());
  expect(api.evidence).toHaveBeenCalledWith("mem_1");
});

test("Context budget compares memory context with the full history", () => {
  render(<ContextBudget tokens={ctx.tokens} />);
  expect(screen.getByText(/62 tokens of memory context/)).toBeInTheDocument();
  expect(screen.getByText(/conversation so far: 900 tokens/)).toBeInTheDocument();
});

const memory: Memory = {
  id: "mem_1", type: "learning_difficulty", key: "difficulty_recursion", content: "Struggles with recursion",
  scope: "global", confidence: 0.9, importance: 0.7, origin: "explicit", status: "active", confirmation: "not_required",
  temporary: false, expires_at: null, created_at: "2026-10-30T10:00:00Z", updated_at: "2026-10-30T10:00:00Z",
  strength_now: 0.8, evidence_message_ids: ["m1"], source: { conversation_id: "conv_123456", message_ids: ["m1"] },
  superseded_by: null, supersedes: [],
};

test("Forgetting a memory asks for confirmation and calls the API", async () => {
  const onChanged = vi.fn();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ul><MemoryRow memory={memory} onChanged={onChanged} /></ul>);
  fireEvent.click(screen.getByRole("button", { name: /forget/i }));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  expect(api.forgetMemory).toHaveBeenCalledWith("mem_1");
});

test("Pending memories offer confirm and reject", async () => {
  const onChanged = vi.fn();
  render(<ul><MemoryRow memory={{ ...memory, confirmation: "pending", origin: "inferred" }} onChanged={onChanged} /></ul>);
  fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
  await waitFor(() => expect(api.confirmMemory).toHaveBeenCalledWith("mem_1", true));
});

test("Activity timeline renders events with reasons, grouped by day", () => {
  const events: MemoryEvent[] = [
    { id: "e2", action: "superseded", reason: "Replaced by a newer statement", memory_id: "m1", memory_ids: ["m1"],
      memory_type: "preference", content_preview: "Prefers visual examples", details: {}, created_at: "2026-10-31T11:00:00Z" },
    { id: "e1", action: "created", reason: "User stated a preference", memory_id: "m1", memory_ids: ["m1"],
      memory_type: "preference", content_preview: "Prefers visual examples", details: {}, created_at: "2026-10-31T10:00:00Z" },
  ];
  render(<ActivityTimeline events={events} />);
  expect(screen.getByText("Memory replaced")).toBeInTheDocument();
  expect(screen.getByText("Memory created")).toBeInTheDocument();
  expect(screen.getByText("Replaced by a newer statement")).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);
});
