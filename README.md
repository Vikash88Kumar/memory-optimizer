# MEMORA: a structured persistent memory engine for AI agents

MEMORA is a learning assistant that remembers how a student learns, shows exactly which memories
shaped each answer, and corrects, expires or forgets memories on request. Built for the MongoDB
Student Hackathon, **Track 1: Agentic Memory** (UNCHARTED 2026, NEXUS × SVNIT Surat).

**The problem.** AI tutors forget everything between sessions: goals, weak topics, deadlines, how
the student likes things explained. Replaying the whole chat history is expensive and has no notion
of correction, expiry or privacy.

**What MEMORA does.**
- Extracts typed memories (preferences, goals, difficulties, constraints, strategies, and more) from
  conversations with a separate extraction agent that returns validated JSON.
- Stores each memory as a MongoDB document with evidence pointers back to the exact messages, then
  retrieves memories with **MongoDB Atlas Vector Search** plus metadata filters, a knowledge graph
  and weighted ranking, and explains every retrieval.
- Builds a compact, token-budgeted **working memory** per turn (core profile, episode bridge,
  current episode, retrieved memories, gated evidence) instead of resending the conversation.
- Manages the lifecycle: create, update, merge, supersede, temporary expiry (TTL), confirm or reject,
  and forget, with an audit trail of every operation and its reason.
- Models time explicitly: memory strength decays continuously (SSM-inspired, `alpha = exp(-lambda * dt)`),
  conversations are segmented into episodes that are summarised and consolidated.

## Architecture at a glance

```
React (Chat | Memories | Graph | Activity)
        │  REST + server-sent events
FastAPI ─┬─ Main agent ────────── working memory controller ── retrieval engine ── Atlas $vectorSearch
         │                                   │                       │
         └─ background worker ── extraction agent → consolidator ── lifecycle ── knowledge graph
                                                   MongoDB Atlas (source of truth)
users · conversations · messages · memories · entities · relationships · memory_events
episodes · sessions · context_logs · tombstones
```
Full details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Demo script: [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md).
What was built and tested: [docs/IMPLEMENTATION_REPORT.md](docs/IMPLEMENTATION_REPORT.md).

## Technology stack

| Layer | Choice |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, React Flow (`@xyflow/react`), Lucide icons |
| Backend | Python 3.12, FastAPI, Pydantic v2, PyMongo async API (`AsyncMongoClient`; Motor is deprecated) |
| Database | MongoDB Atlas: Vector Search, TTL indexes, change streams |
| AI | Configurable LLM (Anthropic or OpenAI-compatible) and embeddings (Voyage AI or OpenAI) |
| Background work | In-process asyncio worker with per-user locks and retries (no Redis needed for one instance) |
| Deployment | Docker, Docker Compose, Render blueprint |

## 1. MongoDB Atlas setup

1. Create a cluster (the free tier is enough for the demo) and a database user; allow your IP
   (and your hosting provider) under Network Access.
2. Copy the connection string into `MONGODB_URI` in `.env`.
3. Run `python scripts/setup_db.py`. It creates the collections, all regular and TTL indexes, the two
   Vector Search indexes and the demo account.

### Vector Search indexes
`setup_db.py` creates `memory_vector_index` (on `memories`) and `episode_vector_index` (on `episodes`)
through the driver. If your cluster tier or permissions do not allow that, create them manually in
Atlas (Search & Vector Search, Create Search Index, Vector Search, JSON editor) using
`scripts/atlas_vector_indexes.json` (generated for 1024 dimensions; regenerate for another model with
`python scripts/setup_db.py --print-index`). Wait until each index shows **READY**.

`numDimensions` must equal `EMBEDDING_DIMENSIONS` and the embedding model's output size. If you change
the embedding model, drop the indexes and re-embed (start with a fresh database for the hackathon).

### TTL indexes (created automatically)
- `memories.expires_at` with `expireAfterSeconds = TTL_GRACE_SECONDS`: temporary memories are physically
  removed after expiry plus a grace period, after the app has marked them `expired` and logged an event.
  Because TTL deletion runs only about once a minute, retrieval also excludes anything past `expires_at`.
- `messages.expires_at` (only when `MESSAGE_RETENTION_DAYS > 0`) and `episodes.expires_at` (episode retention).

### Change streams
The Activity page subscribes to a server-sent-event stream. On Atlas (a replica set) it uses a change
stream on `memory_events`; elsewhere it falls back to polling. The sidebar shows which mode is active.

## 2. LLM and embedding configuration

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `anthropic`, `openai` (any OpenAI-compatible endpoint via `OPENAI_BASE_URL`) or `mock` |
| `CHAT_MODEL`, `EXTRACTOR_MODEL` | Main agent model, and a fast model for extraction and summaries |
| `EMBEDDING_PROVIDER` | `voyage`, `openai` or `hash` |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | Must match each other and the Vector Search index |

`mock` and `hash` are **offline fallbacks** for development and automated tests. The mock model does
not generate answers (it reports which memories a real model would use), and the UI labels it in red.
With `LLM_PROVIDER=mock`, extraction uses a pattern-based extractor that covers the demo scenarios
only. Use a real provider for the hackathon demo.

## 3. Local installation

```bash
cp .env.example .env            # fill in MONGODB_URI, API keys, AUTH_SECRET
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt
python scripts/setup_db.py
cd backend && uvicorn app.main:app --reload --port 8000

# second terminal
cd frontend && npm ci && npm run dev    # http://localhost:5173 (proxies /api to :8000)
```
Sign in with the demo account (`demo` / `memora-demo` unless changed) or create an account.

## 4. Docker

```bash
cp .env.example .env            # fill it in
docker compose up --build       # frontend http://localhost:8080, API http://localhost:8000
```
Fully local alternative with Vector Search (MongoDB's `mongodb-atlas-local` image, evaluation only):
set `MONGODB_URI=mongodb://mongodb:27017/?directConnection=true` and run
`docker compose --profile local-atlas up --build`, then `python scripts/setup_db.py` against it.

## 5. Deployment (required by the hackathon rules)

`render.yaml` deploys the API (Docker, one instance) and the frontend (static site). Set
`MONGODB_URI`, API keys, `CORS_ORIGINS` (the frontend URL) and `VITE_API_BASE_URL` (the API URL).
Allow Render's outbound IPs (or `0.0.0.0/0` for the event) in Atlas Network Access. Any host that runs
a Docker container and a static site works the same way. Keep the API at **one instance**: background
memory jobs run in-process.

Give judges the demo account credentials (not personal ones).

## 6. Testing

```bash
cd backend && pytest -q                         # 36 tests: unit, lifecycle, retrieval, API scenarios
cd frontend && npm run typecheck && npm test && npm run build
```
Automated tests use an in-memory MongoDB mock, the local vector fallback and mocked LLM HTTP calls.
They verify the exact `$vectorSearch` stage and index definitions but cannot execute Atlas Vector
Search; run the demo guide against Atlas to verify that path.

## 7. Demo scenarios

All six required scenarios (learning preference, new session, correction, conflicting scope, temporary
memory, forgetting), plus the episode switch and evidence recall, are scripted in
[docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md). Sample data exists only in the dedicated demo account and
is flagged as sample data in the UI.

## Known limitations

- The background worker is in-process: one API instance, and jobs in flight are lost on restart.
  Swap `app/workers/jobs.py` for a queue (Redis, Celery or similar) to scale horizontally.
- The offline heuristic extractor covers common English first-person patterns only.
- Episode boundaries, ranking weights and thresholds are hand-tuned defaults; tune them on real usage.
- Token counts are estimates (about 4 characters per token), not provider tokenizer counts.
- Forget redacts supporting messages and episode summaries; it cannot remove information a user
  repeats verbatim in a new message after the forget request (by design, that is a new decision).
- Access tokens are kept in `localStorage` and passed as a query parameter for the activity stream
  (EventSource cannot set headers); access logs are disabled for that reason.
#   m e m o r y - o p t i m i z e r  
 