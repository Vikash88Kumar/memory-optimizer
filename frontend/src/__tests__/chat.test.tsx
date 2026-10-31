import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

vi.mock("../services/api", () => {
  const ctx = {
    memories_used: [{ ref: "M1", id: "mem_1", tier: "core", type: "preference", content: "Prefers code-first explanations",
      scope: "global", confidence: 0.95, importance: 0.8, score: 0.8, similarity: 0.7, strength: 0.9, activation: null,
      reasons: ["Core profile"], evidence_message_ids: [], confirmation: "not_required", expires_at: null }],
    overridden: [], episode: { id: "ep", title: "Binary search", turns: 1, switched: false, bridge: null, closed_episode_id: null },
    tokens: { core: 10, bridge: 0, episode: 0, memories: 0, evidence: 0, total: 10, full_history: 20 },
    evidence: [], evidence_reason: "", retrieval_backend: "mongodb_vector_search", offline_model: false, trivial: false,
    extraction_scheduled: false,
  };
  return {
    api: {
      conversations: vi.fn().mockResolvedValue([{ id: "c1", title: "Binary search", updated_at: "", message_count: 0, total_tokens: 0 }]),
      messages: vi.fn().mockResolvedValue([]),
      createConversation: vi.fn(),
      jobs: vi.fn().mockResolvedValue({ pending: 0 }),
      send: vi.fn().mockResolvedValue({
        user_message: { id: "u1", conversation_id: "c1", role: "user", content: "Explain binary search.", created_at: "" },
        assistant_message: { id: "a1", conversation_id: "c1", role: "assistant", content: "Here is the code first...", created_at: "", context: ctx },
        context: ctx,
      }),
    },
  };
});
import { ChatPage } from "../pages/ChatPage";
import { api } from "../services/api";

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

test("sending a message shows the answer and the memories used", async () => {
  render(<MemoryRouter><ChatPage /></MemoryRouter>);
  await waitFor(() => expect(api.messages).toHaveBeenCalledWith("c1"));
  const box = screen.getByLabelText("Message");
  fireEvent.change(box, { target: { value: "Explain binary search." } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(screen.getByText("Here is the code first...")).toBeInTheDocument());
  expect(api.send).toHaveBeenCalledWith("c1", "Explain binary search.");
  expect(screen.getByRole("button", { name: /memories used: 1/i })).toBeInTheDocument();
});
