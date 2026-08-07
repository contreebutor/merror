/**
 * Typed client for the MERROR backend.
 *
 * Mirrors the response shapes in `backend/app/schemas.py`. Errors are returned
 * as values rather than thrown, because every failure here is one the UI has to
 * render anyway — an unreachable backend, a missing API key, a refused message.
 */

import { API_URL } from "./config";

export type MessageRole = "user" | "assistant";

export type MemoryType = "text" | "document" | "image";

/** A memory that informed a reply. */
export type RetrievedMemory = {
  id: string;
  title: string;
  type: MemoryType;
  snippet: string;
  score: number;
};

export type ChatMessage = {
  id: string;
  role: MessageRole;
  content: string;
  created_at: string;
  memory_ids: string[];
};

export type ChatResponse = {
  conversation_id: string;
  message: ChatMessage;
  retrieved: RetrievedMemory[];
};

export type ConversationDetail = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
};

/** A failed request, described in terms the user can act on. */
export type ApiError = {
  /** HTTP status, or 0 when the request never reached the server. */
  status: number;
  message: string;
  /** True when the backend is running but missing an API key. */
  needsConfiguration: boolean;
};

export type Result<T> = { ok: true; data: T } | { ok: false; error: ApiError };

/**
 * Pull a readable message out of a FastAPI error body.
 *
 * FastAPI uses three different shapes: `{detail: "..."}` for raised errors,
 * `{detail: [{msg, loc}, ...]}` for validation failures, and this app's own
 * `{error, detail}` for missing configuration.
 */
function extractMessage(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null) {
    const detail = (body as { detail?: unknown }).detail;

    if (typeof detail === "string") return detail;

    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          typeof item === "object" && item !== null
            ? String((item as { msg?: unknown }).msg ?? "")
            : "",
        )
        .filter(Boolean);
      if (messages.length > 0) return messages.join("; ");
    }
  }
  return `Request failed with status ${status}.`;
}

/** Raised for a request the caller deliberately cancelled — never shown to the user. */
export const ABORTED = "aborted" as const;

async function request<T>(path: string, init?: RequestInit): Promise<Result<T>> {
  let response: Response;
  try {
    const isFormData = init?.body instanceof FormData;
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        // Let the browser set multipart/form-data with its own boundary.
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch (cause) {
    // A superseded search is not a failure — the caller aborted it on purpose.
    if (cause instanceof DOMException && cause.name === "AbortError") {
      return { ok: false, error: { status: 0, message: ABORTED, needsConfiguration: false } };
    }
    return {
      ok: false,
      error: {
        status: 0,
        message: `Cannot reach the backend at ${API_URL}. Is it running?`,
        needsConfiguration: false,
      },
    };
  }

  // Read the body once — a 204 or an HTML error page has no JSON to parse.
  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    return {
      ok: false,
      error: {
        status: response.status,
        message: extractMessage(body, response.status),
        needsConfiguration: response.status === 503,
      },
    };
  }

  return { ok: true, data: body as T };
}

/** Send a message. Omit `conversationId` to start a new conversation. */
export function sendMessage(
  message: string,
  conversationId?: string | null,
): Promise<Result<ChatResponse>> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      ...(conversationId ? { conversation_id: conversationId } : {}),
    }),
  });
}

export function getConversation(id: string): Promise<Result<ConversationDetail>> {
  return request<ConversationDetail>(`/conversations/${id}`);
}

/* --------------------------------------------------------------------------
   Memories
   -------------------------------------------------------------------------- */

/** A memory as it appears in a list — snippet only, no full content. */
export type MemorySummary = {
  id: string;
  snippet: string;
  type: MemoryType;
  title: string;
  source: string;
  created_at: string;
  chunk_count: number;
  has_image: boolean;
  score: number | null;
};

export type MemoryListResponse = {
  memories: MemorySummary[];
  total: number;
  limit: number;
  offset: number;
  query: string;
};

export type DeleteResult = {
  id: string;
  deleted: boolean;
  image_deleted: boolean;
};

/**
 * List memories, newest first — or ranked by meaning when `query` is given.
 *
 * Pass a `signal` so a superseded search can be cancelled; otherwise a slow
 * earlier request can land after a faster later one and show stale results.
 */
export function listMemories(
  options: { query?: string; type?: MemoryType | null; signal?: AbortSignal } = {},
): Promise<Result<MemoryListResponse>> {
  const params = new URLSearchParams();
  if (options.query?.trim()) params.set("q", options.query.trim());
  if (options.type) params.set("type", options.type);

  const suffix = params.toString() ? `?${params}` : "";
  return request<MemoryListResponse>(`/memories${suffix}`, { signal: options.signal });
}

export function deleteMemory(id: string): Promise<Result<DeleteResult>> {
  return request<DeleteResult>(`/memories/${id}`, { method: "DELETE" });
}

/** URL for an image memory's original file. */
export function memoryImageUrl(id: string): string {
  return `${API_URL}/memories/${id}/image`;
}

/* --------------------------------------------------------------------------
   Ingestion
   -------------------------------------------------------------------------- */

export type MemoryDetail = MemorySummary & { content: string };

export type SupportedTypes = {
  extensions: string[];
  max_bytes: number;
  image_extensions: string[];
  image_max_bytes: number;
};

export function getSupportedTypes(): Promise<Result<SupportedTypes>> {
  return request<SupportedTypes>("/memories/supported-types");
}

export function createTextMemory(
  content: string,
  title = "",
): Promise<Result<MemoryDetail>> {
  return request<MemoryDetail>("/memories/text", {
    method: "POST",
    body: JSON.stringify({ content, title }),
  });
}

/**
 * Upload a file as a document or image memory.
 *
 * Deliberately does not set Content-Type: the browser must generate the
 * multipart boundary itself, and an explicit header would omit it and make the
 * body unparseable server-side.
 */
export function uploadFile(
  kind: "document" | "image",
  file: File,
  title = "",
): Promise<Result<MemoryDetail>> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);

  return request<MemoryDetail>(`/memories/${kind}`, {
    method: "POST",
    body: form,
    headers: {},
  });
}

/* --------------------------------------------------------------------------
   Voice
   -------------------------------------------------------------------------- */

export type Transcription = { text: string; language: string };

/** Transcribe a recording. Runs locally on the backend — audio never leaves the machine. */
export function transcribeAudio(blob: Blob, filename = "recording.webm") {
  const form = new FormData();
  form.append("file", blob, filename);
  return request<Transcription>("/voice/transcribe", {
    method: "POST",
    body: form,
    headers: {},
  });
}

/**
 * Synthesize speech and return it as a playable object URL.
 *
 * Returns a blob URL rather than raw bytes so the caller can hand it straight
 * to an <audio> element; the caller owns revoking it.
 */
export async function speak(text: string): Promise<Result<string>> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/voice/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  } catch {
    return {
      ok: false,
      error: {
        status: 0,
        message: `Cannot reach the backend at ${API_URL}.`,
        needsConfiguration: false,
      },
    };
  }

  if (!response.ok) {
    // The error path returns JSON even though success returns audio.
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return {
      ok: false,
      error: {
        status: response.status,
        message: extractMessage(body, response.status),
        needsConfiguration: response.status === 503,
      },
    };
  }

  return { ok: true, data: URL.createObjectURL(await response.blob()) };
}

/* --------------------------------------------------------------------------
   Memory map
   -------------------------------------------------------------------------- */

export type MapNode = {
  id: string;
  title: string;
  type: MemoryType;
  snippet: string;
  created_at: string;
  has_image: boolean;
  x: number;
  y: number;
  cluster: number;
};

export type MapEdge = { source: string; target: string; similarity: number };

export type MemoryMap = { nodes: MapNode[]; edges: MapEdge[]; clusters: number };

export function getMemoryMap(): Promise<Result<MemoryMap>> {
  return request<MemoryMap>("/memories/map");
}
