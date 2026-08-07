"use client";

/**
 * The chat surface — a glass panel floating over the animated gradient.
 *
 * Slice 11 is a visual pass only: the behaviour here (optimistic send, restore
 * on failure, source disclosure) is unchanged from Slice 10.
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

export default function Chat({ onOpenArchive }: { onOpenArchive?: () => void }) {
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
    <div className="glass mx-auto flex h-full w-full max-w-3xl flex-col overflow-hidden rounded-3xl">
      <header className="glass-divider flex shrink-0 items-center gap-3 border-b px-5 py-4 sm:px-6">
        {onOpenArchive && (
          <button
            type="button"
            onClick={onOpenArchive}
            aria-label="Open archive"
            className="rounded-lg px-1 py-0.5 text-white/40 transition-colors hover:text-white/80 lg:hidden"
          >
            {/* Three stacked lines: the archive as a list. */}
            <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
              <path d="M2.5 4h11M2.5 8h11M2.5 12h11" />
            </svg>
          </button>
        )}
        <h1 className="text-[0.7rem] font-light tracking-[0.42em] text-white/80">
          MERROR
        </h1>
      </header>

      <div className="subtle-scroll flex-1 overflow-y-auto px-6 py-8">
        <div className="flex flex-col gap-7">
          {turns.length === 0 && !pending && (
            <p className="py-20 text-center text-sm font-light text-white/35">
              Say something to your archive.
            </p>
          )}

          {turns.map((turn) => (
            <article key={turn.id} className="flex flex-col gap-2">
              <div className="text-[0.65rem] uppercase tracking-[0.2em] text-white/35">
                {turn.role === "user" ? "You" : "Mirror"}
              </div>
              <div
                className={
                  turn.role === "user"
                    ? "whitespace-pre-wrap leading-relaxed text-white/75"
                    : "whitespace-pre-wrap leading-relaxed text-white/95"
                }
              >
                {turn.content}
              </div>

              {turn.retrieved && turn.retrieved.length > 0 && (
                <details className="group mt-1.5">
                  <summary className="cursor-pointer list-none text-xs text-white/35 transition-colors hover:text-white/60">
                    <span className="inline-block transition-transform group-open:rotate-90">
                      ›
                    </span>{" "}
                    Drew on {turn.retrieved.length}{" "}
                    {turn.retrieved.length === 1 ? "memory" : "memories"}
                  </summary>
                  <ul className="mt-3 flex flex-col gap-3 border-l border-white/10 pl-4">
                    {turn.retrieved.map((memory) => (
                      <li key={memory.id} className="text-xs">
                        <div className="flex items-baseline gap-2">
                          <span className="text-white/65">
                            {memory.title || memory.type}
                          </span>
                          <span className="text-white/25">
                            {Math.round(memory.score * 100)}%
                          </span>
                        </div>
                        <p className="mt-1 leading-relaxed text-white/40">
                          {memory.snippet}
                        </p>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </article>
          ))}

          {pending && (
            <div className="flex flex-col gap-2">
              <div className="text-[0.65rem] uppercase tracking-[0.2em] text-white/35">
                Mirror
              </div>
              <div className="animate-pulse text-sm text-white/35">Thinking…</div>
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="rounded-2xl border border-red-400/25 bg-red-500/10 px-4 py-3 text-sm"
            >
              <p className="text-red-200/90">{error.message}</p>
              {error.needsConfiguration && (
                <p className="mt-2 text-xs leading-relaxed text-white/50">
                  Copy <code className="text-white/70">.env.example</code> to{" "}
                  <code className="text-white/70">.env</code>, add your{" "}
                  <code className="text-white/70">ANTHROPIC_API_KEY</code>, and
                  restart the backend.
                </p>
              )}
            </div>
          )}

          <div ref={endRef} />
        </div>
      </div>

      <div className="glass-divider shrink-0 border-t px-4 py-4 sm:px-6">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Say something…"
            aria-label="Message"
            disabled={pending}
            className="glass-raised max-h-40 flex-1 resize-none rounded-2xl px-4 py-3 text-sm text-white/90 outline-none transition-colors placeholder:text-white/30 focus:border-white/25 disabled:opacity-40"
          />
          <button
            type="button"
            onClick={() => void submit()}
            disabled={pending || !input.trim()}
            className="glass-button rounded-2xl px-5 py-3 text-sm text-white/85 disabled:opacity-25"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
