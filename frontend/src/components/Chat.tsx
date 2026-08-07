"use client";

/**
 * The chat surface.
 *
 * Deliberately unstyled beyond layout — Slice 11 adds the glass and gradient.
 * Everything here is about behaviour: sending, pending state, failure states,
 * and showing which memories informed a reply.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type ApiError,
  type ChatMessage,
  type RetrievedMemory,
  sendMessage,
} from "@/lib/api";

/** A message plus the memories retrieved for it, if any. */
type Turn = ChatMessage & { retrieved?: RetrievedMemory[] };

/** A locally-created id for the user's own turn, which the server has not seen yet. */
function localId(): string {
  return `local-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function Chat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);

  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Keep the newest turn in view as the conversation grows.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, pending]);

  const submit = useCallback(async () => {
    const message = input.trim();
    if (!message || pending) return;

    // Show the user's own words immediately — waiting on the round trip to
    // echo them back makes the app feel broken.
    const optimistic: Turn = {
      id: localId(),
      role: "user",
      content: message,
      created_at: new Date().toISOString(),
      memory_ids: [],
    };
    setTurns((current) => [...current, optimistic]);
    setInput("");
    setError(null);
    setPending(true);

    const result = await sendMessage(message, conversationId);
    setPending(false);

    if (!result.ok) {
      setError(result.error);
      // Put the text back so nothing typed is lost to a failed request.
      setTurns((current) => current.filter((turn) => turn.id !== optimistic.id));
      setInput(message);
      inputRef.current?.focus();
      return;
    }

    setConversationId(result.data.conversation_id);
    setTurns((current) => [
      ...current,
      { ...result.data.message, retrieved: result.data.retrieved },
    ]);
  }, [input, pending, conversationId]);

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter is a newline.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="border-b border-white/15 px-4 py-3">
        <h1 className="text-sm font-light tracking-[0.3em]">MERROR</h1>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-6">
          {turns.length === 0 && !pending && (
            <p className="py-16 text-center text-sm opacity-40">
              Say something to your archive.
            </p>
          )}

          {turns.map((turn) => (
            <article key={turn.id} className="flex flex-col gap-2">
              <div className="text-xs uppercase tracking-wider opacity-40">
                {turn.role === "user" ? "You" : "Mirror"}
              </div>
              <div className="whitespace-pre-wrap leading-relaxed">{turn.content}</div>

              {turn.retrieved && turn.retrieved.length > 0 && (
                <details className="mt-1 text-xs opacity-50">
                  <summary className="cursor-pointer">
                    Drew on {turn.retrieved.length}{" "}
                    {turn.retrieved.length === 1 ? "memory" : "memories"}
                  </summary>
                  <ul className="mt-2 flex flex-col gap-2 border-l border-white/15 pl-3">
                    {turn.retrieved.map((memory) => (
                      <li key={memory.id}>
                        <span className="opacity-70">{memory.title || memory.type}</span>{" "}
                        <span className="opacity-40">
                          ({Math.round(memory.score * 100)}% match)
                        </span>
                        <p className="mt-0.5 opacity-60">{memory.snippet}</p>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </article>
          ))}

          {pending && (
            <div className="flex flex-col gap-2">
              <div className="text-xs uppercase tracking-wider opacity-40">Mirror</div>
              <div className="animate-pulse text-sm opacity-40">Thinking…</div>
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="rounded border border-red-500/40 bg-red-500/5 p-3 text-sm"
            >
              <p className="text-red-400">{error.message}</p>
              {error.needsConfiguration && (
                <p className="mt-2 opacity-60">
                  Copy <code>.env.example</code> to <code>.env</code>, add your{" "}
                  <code>ANTHROPIC_API_KEY</code>, and restart the backend.
                </p>
              )}
            </div>
          )}

          <div ref={endRef} />
        </div>
      </div>

      <div className="border-t border-white/15 px-4 py-4">
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Say something…"
            aria-label="Message"
            disabled={pending}
            className="flex-1 resize-none rounded border border-white/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-white/40 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void submit()}
            disabled={pending || !input.trim()}
            className="rounded border border-white/15 px-4 py-2 text-sm disabled:opacity-30"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
