# Implementation report

## Implemented
- **Backend (FastAPI, modular monolith):** auth (signed tokens, PBKDF2 passwords), user and workspace
  isolation on every query, conversations and messages, chat orchestration, memory explorer API
  (search, filter, edit, confirm/reject, forget, evidence, history), knowledge graph API, activity
  timeline with a server-sent-event stream (change streams when available, polling otherwise),
  context logs, system status, demo tools (per-user clock, demo reset).
- **Memory engine:** extraction agent with a strict Pydantic schema and one repair attempt; an offline
  heuristic extractor that emits the same schema; consolidator with server-side ref mapping;
  lifecycle (create, update, merge, supersede, expire, forget, confirm/reject) with events and reasons;
  scope-aware conflict resolution; duplicate detection; secret and prompt-injection guards; tombstones;
  evidence pointers; knowledge graph in `entities` + `relationships`.
- **Retrieval:** `$vectorSearch` with user, workspace and status filters (or a clearly labelled local
  fallback), graph expansion, configurable weighted ranking with explanations, app-side expiry check,
  scope overrides.
- **Time and working memory:** SSM-inspired strength decay and reinforcement; episodes with boundary
  detection (topic shift, time gap, explicit cue, soft-boundary confirmation), bridges, background
  summarisation and consolidation; tiered token budgets; delta retrieval with turn-level activation
  decay and eviction; gated episodic evidence; per-turn token logging.
- **Background work:** in-process asyncio worker with per-user locks, retries with backoff, failure
  events, extraction batching and a cheap extraction gate.
- **Frontend (React, TypeScript, Vite, Tailwind, React Flow):** login/sign-up, Chat (conversation list,
  memories-used panel with reasons and original messages, working-memory panel with token budget,
  episode dividers, memory-update indicator), Memory Explorer, Knowledge Graph (radial layout, node
  details with linked memories and actions, replaced links), Activity timeline (live).
- **Ops:** Dockerfiles, Docker Compose (Atlas, or the local `mongodb-atlas-local` profile), Render
  blueprint, `.env.example`, `scripts/setup_db.py`, `scripts/context_report.py`, generated Vector
  Search index JSON.

## Tests actually executed (in this build environment)

| Check | Result |
|---|---|
| Backend `pytest` (36 tests) | 36 passed |
| Frontend `vitest` (8 tests) | 8 passed |
| TypeScript check (`tsc -b --noEmit`) | passed, no errors |
| Production frontend build (`vite build`) | passed |
| Backend startup with full lifespan (collections, indexes, change-stream probe, demo seeding) | passed against an in-memory MongoDB mock (`backend/tests/smoke_inmemory_server.py`) |
| End-to-end browser run (Playwright, headless Chromium) of login, chat, memory explorer, graph, activity | passed against the same smoke server; screenshots reviewed |
| `docker-compose.yml` and `render.yaml` | parsed as valid YAML; **not** built or run (no Docker in the build environment) |

Backend tests cover: memory creation, duplicate merging, conflict superseding, scope and temporary
coexistence, expiry (excluded before TTL runs), forgetting (graph cleanup, evidence and event
redaction, cascade, tombstone blocking, fresh restatement allowed), confirm/reject, update, merge,
user isolation, evidence pointer resolution (including cross-user), structured extraction validation
and repair, unknown-ref rejection, origin downgrade, budget packing, decay, episode boundaries and
switching, gated episodic retrieval, activation decay and eviction, Anthropic and OpenAI request
shapes with retries (mocked HTTP), the exact `$vectorSearch` stage and index definitions, all six demo
scenarios through the HTTP API, the online (non-offline) LLM code path with a fake provider, demo
seeding and reset.

## Requires external credentials (implemented, not executed here)
- **MongoDB Atlas Vector Search** and Atlas change streams: the build environment cannot reach Atlas.
  Tests assert the query and index shapes; run `scripts/setup_db.py` and the demo guide on your cluster.
- **Anthropic / OpenAI chat and Voyage / OpenAI embeddings:** tested with mocked HTTP only.
- **Docker images and Render deployment.**

## Limitations
See "Known limitations" in the README. Most important for the hackathon: keep the API at one
instance (in-process worker), use a real LLM and embedding provider for the demo, and confirm the
sidebar says "MongoDB Vector Search" before recording.

## How to start
`cp .env.example .env` → fill in → `pip install -r backend/requirements-dev.txt` →
`python scripts/setup_db.py` → `cd backend && uvicorn app.main:app --port 8000` →
`cd frontend && npm ci && npm run dev`. Or `docker compose up --build`.
