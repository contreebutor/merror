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

async function request<T>(path: string, init?: RequestInit): Promise<Result<T>> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
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
