# MERROR

*mirror → another version of me → my clone*

A private, local-first chatbot that acts as a reflective conversational mirror.
It talks to you using Claude, grounded in a personal memory store built from
things you feed it — raw text, documents, and images. The goal is
self-understanding through conversation with "yourself."

Everything runs on your machine. The only data that leaves it goes directly to
Anthropic (for reasoning) and ElevenLabs (for voice) — nothing else, nowhere else.

## Status

Under active construction, built in reviewable slices. Currently at **Slice 2 —
repo scaffold**: both services start and serve a placeholder. No memory, chat,
or voice functionality yet.

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

API keys live in a gitignored `.env` and are never committed. Setup arrives in
Slice 3 — until then no keys are required, because nothing calls out yet.

## Privacy

Your memories, uploaded files, vector database, and conversation history are all
gitignored and stay on this machine. Only chat messages (with retrieved memory
context) and voice text reach the external APIs.
