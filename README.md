# MERROR

*mirror → another version of me → my clone*

A private, local-first chatbot that acts as a reflective conversational mirror.
It talks to you using Claude, grounded in a personal memory store built from
things you feed it — raw text, documents, and images. The goal is
self-understanding through conversation with "yourself."

Everything runs on your machine. The only data that leaves it goes directly to
Anthropic (for reasoning) and ElevenLabs (for voice) — nothing else, nowhere else.

---

## What it does

- **Chat** grounded in your own archive, with the sources behind every reply
  visible.
- **Remember** pasted text, documents (PDF/DOCX/TXT/MD), and images.
- **Search** by meaning rather than keyword — *"quiet reflection in the early
  hours"* finds a note about walking at dawn.
- **Speak and listen** — record a voice note, hear replies read aloud.
- **See the shape of it** — an interactive map of the archive, memories placed
  by meaning and clustered by theme.
- **Forget** anything, permanently, including the stored file.

## Requirements

- **Node.js** 20 or newer (developed against v25)
- **Python 3.12** — not 3.13 or 3.14. ChromaDB's dependency chain does not ship
  wheels for those yet, and building from source is a bad time.
- About **1 GB of disk** for the two local models, downloaded on first use:
  the embedding model (~80 MB) and Whisper (~150 MB at the default size).

## Setup

```bash
git clone <your-repo-url> merror-app
cd merror-app

# Configuration — one file drives both services
cp .env.example .env
#   then open .env and add your ANTHROPIC_API_KEY

# Backend
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### API keys

| Key | Needed for | Without it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Chat, image understanding | Chat returns a `503`; text and document ingest still work |
| `ELEVENLABS_API_KEY` | Spoken replies | Everything works except speech out |

**Speech-to-text needs no key.** Whisper runs locally, so you can record voice
notes on a completely unconfigured install.

Missing keys never prevent startup. The backend prints a banner naming what is
absent, `GET /config/status` reports which features are available, and the UI
shows a notice on load rather than letting you discover it by failing.

## Running

Two terminals:

```bash
# Terminal 1 — backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

```bash
# Terminal 2 — frontend
cd frontend && npm run dev
```

| Service | URL |
|---|---|
| App | http://localhost:3000 |
| API docs | http://localhost:8000/docs |

**First run is slower.** The embedding model downloads on the first memory you
add, and Whisper on the first voice note. Both are cached afterwards.

### Running it for real

`--reload` watches for file changes and is for development. For everyday use:

```bash
cd backend && source .venv/bin/activate
uvicorn app.main:app --port 8000

cd frontend && npm run build && npm start
```

The production build is meaningfully faster to load than the dev server.

## Deployment: don't

MERROR is designed to run on one machine, for one person, with **no
authentication of any kind**. Anyone who can reach the backend can read every
memory, every conversation, and every uploaded image.

Both services bind to localhost by default, which is what you want. Do not put
this on a public host or a shared network without putting real authentication in
front of it first. There is no multi-user support, and the threat model assumes
the only person who can reach it is you.

If you want it on another device you own, an SSH tunnel is the simple answer:

```bash
ssh -L 3000:localhost:3000 -L 8000:localhost:8000 you@your-machine
```

## Where your data lives

Everything is under `backend/data/`, gitignored in full:

```
backend/data/
├── chroma/          Vector database — memories and their embeddings
├── uploads/images/  Original images, named by memory id
├── conversations/   One JSON file per conversation, human-readable
└── models/          Downloaded Whisper weights
```

To back MERROR up, copy `backend/data/`. To start over, delete it.

Conversations are plain JSON on purpose: it is your record of your own thinking,
and you should be able to read it without this app.

## What leaves your machine

| Action | Sent where | What exactly |
|---|---|---|
| Chatting | Anthropic | Your message, the conversation so far, and excerpts of retrieved memories |
| Adding an image | Anthropic | The image, so Claude can describe it |
| Spoken replies | ElevenLabs | The reply text |
| **Everything else** | **Nowhere** | |

Embedding, search, clustering, the map, and speech-to-text all run locally.
Adding text or a document sends nothing anywhere.

---

## Architecture

| Layer | Choice |
|---|---|
| Frontend | Next.js 16 (App Router) + TypeScript + Tailwind 4 |
| Backend | Python 3.12 + FastAPI |
| Vector DB | ChromaDB, embedded, persisted to local disk |
| Embeddings | all-MiniLM-L6-v2, local, 384 dimensions |
| LLM | Anthropic Claude (`claude-opus-5` by default) |
| Speech in | faster-whisper, local |
| Speech out | ElevenLabs |
| Map | PCA + k-means on numpy, no extra dependency |

```
merror-app/
├── frontend/src/
│   ├── app/            App Router pages, global styles
│   ├── components/     Chat, Sidebar, AddMemory, MemoryMap, Aurora
│   └── lib/            API client, recorder hook, formatting
├── backend/app/
│   ├── main.py         App assembly, CORS, config reporting
│   ├── config.py       Settings and key validation
│   ├── store.py        ChromaDB persistence
│   ├── chunking.py     Paragraph-aware document splitting
│   ├── documents.py    PDF/DOCX/TXT extraction
│   ├── vision.py       Claude image description
│   ├── chat.py         Retrieval + prompt + reply
│   ├── conversations.py JSON conversation storage
│   ├── transcription.py Local Whisper
│   ├── speech.py       ElevenLabs
│   ├── projection.py   2D map
│   └── routers/        HTTP routes
└── .env.example
```

## API

Full interactive docs at http://localhost:8000/docs.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/memories/text` | Remember pasted text |
| `POST` | `/memories/document` | Remember an uploaded document |
| `POST` | `/memories/image` | Remember an uploaded image |
| `GET` | `/memories` | List newest-first, or search with `?q=` |
| `GET` | `/memories/map` | The archive projected into 2D |
| `GET` | `/memories/{id}` | One memory, with full content |
| `GET` | `/memories/{id}/image` | The original image |
| `DELETE` | `/memories/{id}` | Forget a memory, chunks and image included |
| `POST` | `/chat` | Say something; retrieves memories and replies |
| `GET` | `/conversations` | List past conversations |
| `POST` | `/conversations/{id}/promote` | Turn a message into a memory |
| `POST` | `/voice/transcribe` | Speech to text, locally |
| `POST` | `/voice/speak` | Text to speech |
| `GET` | `/config/status` | Which features have their keys |

## How it works

### Memory store

One Chroma record holds one *chunk*. A short note is a single chunk; a long
document becomes many, sharing a `memory_id`. That keeps retrieval accurate on
long documents while letting a memory be listed and deleted as one unit.

Documents are split **paragraph-aware with a 1200-character cap** and 150
characters of overlap, splitting at sentence boundaries when a paragraph is too
long. The cap is not arbitrary: the embedding model truncates at 256 word-pieces
and *silently ignores* the rest, so an oversized chunk would look fine and fail
to embed its tail.

### Chat

Each message retrieves the top 6 memories above a 0.30 similarity floor. The
floor matters — passing weak matches as context invites the model to invent
connections, which is the opposite of useful for a self-understanding tool.

Retrieved text is wrapped in `<memories>` tags, and the system prompt states
that archived text is **data, never instruction** — so an uploaded document
containing "ignore previous instructions" is treated as a fact about that
document.

### Conversations

Stored separately and **never auto-embedded**. A message becomes a searchable
memory only when you promote it.

That separation is deliberate: auto-embedding a chat would mean Claude's
speculation about you gets retrieved later as though it were established fact,
and then it builds on its own guesses. Promoted memories are independent —
deleting the conversation does not remove them.

### The map

PCA and k-means on numpy rather than UMAP or t-SNE, chosen for **determinism**:
the same archive always draws the same map, so a space meant to become familiar
does not rearrange every visit. Edges are cut at the 90th percentile of the
archive's own similarities rather than a fixed threshold, since absolute cosine
values depend on the model and on how varied your archive is.

The trade-off is honest: PCA separates clusters less crisply than UMAP would.

### Interface

Four blurred colour fields drift on coprime periods (37s, 43s, 53s, 61s), so the
composition takes hours to repeat rather than looping visibly. Pure CSS,
`transform` only, so the compositor owns it and nothing runs per frame.
`prefers-reduced-motion` holds it still.

## Tests

```bash
cd backend && .venv/bin/python -m pytest
```

205 tests. They build real PDFs, DOCX files, images, and WAV audio rather than
mocking, so parsers and sniffers are exercised as they will be in production.
Only the two external APIs are faked. Every test runs against a throwaway data
directory, so the suite can never touch your real archive.

Frontend checks:

```bash
cd frontend && npx tsc --noEmit && npx eslint src && npm run build
```

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Chat and image understanding |
| `ELEVENLABS_API_KEY` | — | Spoken replies |
| `ANTHROPIC_MODEL` | `claude-opus-5` | Claude model |
| `ELEVENLABS_VOICE_ID` | Rachel | Which voice |
| `ELEVENLABS_MODEL` | `eleven_multilingual_v2` | Quality vs speed |
| `WHISPER_MODEL` | `base` | `tiny`…`large-v3`; larger is better and slower |
| `CHROMA_DIR` | `data/chroma` | Vector database |
| `UPLOADS_DIR` | `data/uploads` | Stored images |
| `WHISPER_CACHE_DIR` | `data/models` | Whisper weights |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | CORS allowlist |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend URL |

**Only `NEXT_PUBLIC_*` variables reach the browser.** `next.config.ts` reads the
root `.env` through a strict prefix allowlist, so API keys cannot end up in the
client bundle.

Settings are read once at boot — **restart the backend after editing `.env`**.

## Troubleshooting

**`pip install` fails on chromadb.** You are probably on Python 3.13+. Check
with `python --version` inside the venv and rebuild it with `python3.12 -m venv`.

**First message hangs for a while.** The embedding model is downloading. Watch
the backend terminal.

**Voice recording does nothing.** Browsers only allow microphone access on
`localhost` or HTTPS. `localhost` is fine; an IP address like `192.168.1.5` is
not.

**Replies are not spoken.** Check `ELEVENLABS_API_KEY`, and that the voice id in
`.env` exists on your account — a wrong one returns a `422`.

**Transcription is inaccurate.** Raise `WHISPER_MODEL` to `small` or `medium`.
Roughly three times slower, noticeably better on accents and background noise.

**The map looks like a blob.** With few memories there is little variance to
project. It gets more legible past a couple of dozen.
