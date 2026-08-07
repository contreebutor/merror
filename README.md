# MERROR

*mirror → another version of me → my clone*

A private, local-first chatbot that acts as a reflective conversational mirror.
It talks to you using Claude, grounded in a personal memory store built from
things you feed it — raw text, documents, and images. The goal is
self-understanding through conversation with "yourself."

Everything runs on your machine. The only data that leaves it goes directly to
Anthropic (for reasoning) and ElevenLabs (for voice) — nothing else, nowhere else.

## Status

Under active construction, built in reviewable slices. Currently at **Slice 11 —
visual design**: usable end to end, with the glass-and-gradient interface in
place. Add an `ANTHROPIC_API_KEY`, start both services, and you can talk to your
archive in the browser. No memory sidebar, upload UI, or voice yet.

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
| `ANTHROPIC_MODEL` | backend | Claude model (default `claude-opus-5`) |
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

### Chunking

Documents are split **paragraph-aware with a size cap** (`app/chunking.py`):

1. Split on blank lines into paragraphs.
2. Pack consecutive paragraphs together up to **1200 characters**, so a run of
   short notes becomes one coherent chunk rather than context-free fragments.
3. Split any oversized paragraph at **sentence boundaries**, never mid-sentence.
4. Carry **150 characters** of trailing context into the next chunk, so a fact
   spanning a boundary stays retrievable from both sides.

The 1200-character cap keeps chunks inside the embedding model's 256 word-piece
window; text beyond that window is silently ignored rather than erroring, which
is why the cap matters.

### Supported uploads

**Documents** — `.pdf`, `.docx`, `.txt`, `.md`, up to 25 MB, parsed in-process.
Legacy `.doc` is not supported (different binary format); re-save as `.docx`.
Scanned PDFs have no text layer and are rejected with a message pointing at
image upload. Documents are **not retained on disk** — only the extracted text
is stored, since that is all retrieval needs.

**Images** — `.jpg`, `.png`, `.gif`, `.webp`, up to 3.5 MB. File type is
determined by *magic bytes*, not the extension, so a mislabelled file is
rejected before anything is sent anywhere. Unlike documents, the original image
**is** kept under `backend/data/uploads/images/`, named after its memory id — the
picture itself is the thing being remembered.

> **Images are the one ingestion path that leaves this machine.** The image is
> sent to Anthropic so Claude can describe it; that description is what gets
> embedded and searched. Everything else — text, documents, all embeddings —
> stays local. If Claude declines to describe an image, nothing is stored.

## API

Full interactive docs at http://localhost:8000/docs.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/memories/text` | Remember pasted text |
| `POST` | `/memories/document` | Remember an uploaded document |
| `POST` | `/memories/image` | Remember an uploaded image |
| `GET` | `/memories` | List newest-first, or search with `?q=` |
| `GET` | `/memories/{id}` | One memory, with full content |
| `GET` | `/memories/{id}/image` | The original image for an image memory |
| `DELETE` | `/memories/{id}` | Forget a memory, chunks and image included |
| `GET` | `/memories/supported-types` | Accepted file types and size limits |
| `POST` | `/chat` | Say something; retrieves memories and replies |
| `GET` | `/conversations` | List past conversations |
| `GET` | `/conversations/{id}` | Read one conversation |
| `DELETE` | `/conversations/{id}` | Delete a conversation |
| `POST` | `/conversations/{id}/promote` | Turn a message into a memory |
| `GET` | `/config/status` | Which features have their keys configured |

**Search is semantic, not keyword.** `?q=` embeds the query locally and compares
it against stored memories, so *"quiet reflection in the early hours"* finds a
memory about walking at dawn that shares none of those words. Results carry a
`score` in `[0, 1]`; plain listings carry `null`.

List responses return **snippets only** — fetch a single memory for its full
text — and never include server filesystem paths. Image memories expose
`has_image: true`; the bytes come from `/memories/{id}/image`.

## Chat and conversations

Each message retrieves the most relevant memories from the archive (top 6, above
a 0.30 similarity floor so weak matches don't invite the model to invent
connections) and puts them in front of Claude as context. Replies come back with
the list of memories that informed them, so you can always see the sources.

**Conversations are stored separately from the memory archive.** They live as
plain JSON under `backend/data/conversations/` — readable without this app,
since it's your own record of your thinking — and are **not** embedded
automatically. A message becomes a searchable memory only when you promote it
via `POST /conversations/{id}/promote`.

That separation is deliberate. Auto-embedding a chat would mean Claude's
speculation about you gets retrieved later as though it were established fact,
and then it builds on its own guesses. Promotion keeps the archive to things you
decided were worth remembering. Promoted memories are independent — deleting the
conversation doesn't remove them.

Memory text reaching the model is wrapped in `<memories>` tags, and the system
prompt states that archived text is data and never instruction — so an uploaded
document containing "ignore previous instructions" is treated as a fact about
that document.

Tests:

```bash
cd backend
.venv/bin/python -m pytest
```

## Interface

Dark by design — a dark field lets the background read as light moving behind
glass rather than as a coloured page.

The background is four large, heavily blurred colour fields drifting on
**coprime periods** (37s, 43s, 53s, 61s), so the composition takes hours to
repeat rather than looping visibly every minute. It is pure CSS: only
`transform` is animated, which the compositor owns, so nothing runs per frame
and the 90px blur is rasterised once. No canvas, no WebGL, no JavaScript.

Fine noise sits over the gradient. Large smooth gradients band badly on 8-bit
displays; a little grain dithers the steps away.

Glass panels use `backdrop-filter: blur(24px) saturate(150%)` — the saturation
lift matters, since blur alone drains colour to grey — plus a hairline inset
highlight along the top edge for the bevel that reads as physical.

Two things the design gives way on:

- **`prefers-reduced-motion`** holds the gradient still. It is decorative; if
  someone has asked their system for less motion, they get the composition
  without the drift.
- **Browsers without `backdrop-filter`** get a near-opaque panel instead, so
  content stays legible rather than dissolving into an outline.

Your memories, uploaded files, vector database, and conversation history are all
gitignored and stay on this machine. Only chat messages (with retrieved memory
context) and voice text reach the external APIs.
