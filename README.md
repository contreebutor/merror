# MERROR

*mirror → another version of me → my clone*

A private, local-first chatbot that acts as a reflective conversational mirror.
It talks to you using Claude, grounded in a personal memory store built from
things you feed it — raw text, documents, and images. The goal is
self-understanding through conversation with "yourself."

Everything runs on your machine. The only data that leaves it goes directly to
Anthropic (for reasoning) and ElevenLabs (for voice) — nothing else, nowhere else.

## Status

Under active construction, built in reviewable slices. Currently at **Slice 5 —
raw-text ingestion**: text can be posted to the API, embedded locally, and
stored. No document/image upload, chat, or voice yet.

## Architecture

| Layer | Choice |
|---|---|
| Frontend | Next.js 16 (App Router) + TypeScript + Tailwind 4 |
| Backend | Python 3.12 + FastAPI |
| Vector DB | ChromaDB (embedded, persisted to local disk) |
| LLM | Anthropic Claude API |
| Voice | ElevenLabs (TTS) + Whisper (STT) |

```
merror-app/
├── frontend/          Next.js app (UI, chat, memory views)
│   └── src/app/       App Router pages
├── backend/           FastAPI service (ingestion, embeddings, RAG, voice)
│   ├── app/           Application package
│   └── requirements.txt
└── README.md
```

## Requirements

- **Node.js** 20+ (developed against v25)
- **Python 3.12** — not 3.13/3.14; ChromaDB's dependency chain does not yet
  ship wheels for those, and building from source is a bad time.

## Setup

### Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

## Running

Two terminals. Backend first:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Then the frontend:

```bash
cd frontend
npm run dev
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

## Configuration

Copy the template and fill in your keys:

```bash
cp .env.example .env
```

A single repo-root `.env` configures both services. It is gitignored and never
committed.

| Variable | Used by | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | backend | Chat reasoning, image understanding |
| `ELEVENLABS_API_KEY` | backend | Text-to-speech |
| `ANTHROPIC_MODEL` | backend | Claude model (default `claude-sonnet-5`) |
| `ELEVENLABS_VOICE_ID` | backend | Voice selection |
| `CHROMA_DIR` / `UPLOADS_DIR` | backend | Local storage paths, relative to `backend/` |
| `FRONTEND_ORIGIN` | backend | CORS allowlist |
| `NEXT_PUBLIC_API_URL` | frontend | Backend base URL |

**Only `NEXT_PUBLIC_*` variables reach the browser.** `next.config.ts` reads the
root `.env` through a strict prefix allowlist, so API keys stay backend-side and
cannot end up in the client bundle.

Missing keys do not prevent startup — the backend prints a banner naming what is
absent, `GET /config/status` reports which features are available, and any route
needing an unset key returns a `503` explaining how to fix it. This keeps the app
usable while partially configured.

Settings are read once at boot; **restart the backend after editing `.env`**.

## Memory store

Memories live in a local ChromaDB collection under `backend/data/chroma`.
Embeddings are computed **on this machine** by Chroma's default model
(all-MiniLM-L6-v2, 384 dimensions, cached to `~/.cache/chroma` on first use —
about 80 MB). Memory content is never sent anywhere to be embedded.

One Chroma record holds one *chunk*. A short note is a single chunk; a long
document becomes many, sharing a `memory_id`. That keeps retrieval accurate on
long documents while still letting a memory be listed and deleted as one unit.

Tests:

```bash
cd backend
.venv/bin/python -m pytest
```

## Privacy

Your memories, uploaded files, vector database, and conversation history are all
gitignored and stay on this machine. Only chat messages (with retrieved memory
context) and voice text reach the external APIs.
