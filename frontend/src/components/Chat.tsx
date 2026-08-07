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
  speak,
  transcribeAudio,
} from "@/lib/api";
import { useRecorder } from "@/lib/useRecorder";

/** A message plus the memories retrieved for it, if any. */
type Turn = ChatMessage & { retrieved?: RetrievedMemory[] };

/** A locally-created id for the user's own turn, which the server has not seen yet. */
function localId(): string {
  return `local-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function Chat({
  onOpenArchive,
  onOpenMap,
}: {
  onOpenArchive?: () => void;
  onOpenMap?: () => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);

  const [voiceMode, setVoiceMode] = useState(false);
  const [transcribing, setTranscribing] = useState(false);

  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);

  const recorder = useRecorder();

  /** Play a reply aloud, replacing anything already playing. */
  const playAloud = useCallback(async (text: string) => {
    const result = await speak(text);
    if (!result.ok) {
      // Speech failing must not hide the reply, which is already on screen.
      setError(result.error);
      return;
    }

    audioRef.current?.pause();
    // Blob URLs leak until revoked; release the previous one before replacing it.
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    audioUrlRef.current = result.data;

    const audio = new Audio(result.data);
    audioRef.current = audio;
    // Autoplay can still be refused if the tab has no user gesture yet.
    void audio.play().catch(() => undefined);
  }, []);

  // Stop playback and free the blob URL when the component goes away.
  useEffect(
    () => () => {
      audioRef.current?.pause();
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    },
    [],
  );

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

    if (voiceMode) void playAloud(result.data.message.content);
  }, [input, pending, conversationId, voiceMode, playAloud]);

  /** Tap to start recording, tap again to transcribe and send. */
  const toggleRecording = useCallback(async () => {
    if (recorder.state === "recording") {
      const captured = await recorder.stop();
      if (!captured) return;

      setTranscribing(true);
      const result = await transcribeAudio(captured.blob, captured.filename);
      setTranscribing(false);

      if (!result.ok) {
        setError(result.error);
        return;
      }
      // Land the transcript in the input rather than sending it blind, so a
      // misheard word can be fixed before it becomes part of the record.
      setInput(result.data.text);
      inputRef.current?.focus();
      return;
    }

    await recorder.start();
  }, [recorder]);

  const isRecording = recorder.state === "recording" || recorder.state === "requesting";
  const hasConversation = turns.length > 0;

  /** Clear the screen and start fresh. The old conversation stays on disk. */
  function startNewConversation() {
    audioRef.current?.pause();
    setTurns([]);
    setConversationId(null);
    setError(null);
    setInput("");
    inputRef.current?.focus();
  }

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

        <div className="ml-auto flex items-center gap-1">
        {hasConversation && (
          <button
            type="button"
            onClick={startNewConversation}
            title="Start a new conversation (this one is kept)"
            className="ml-auto rounded-lg px-2 py-1 text-[0.65rem] uppercase tracking-[0.15em] text-white/30 transition-colors hover:text-white/70"
          >
            New
          </button>
        )}

        {onOpenMap && (
          <button
            type="button"
            onClick={onOpenMap}
            aria-label="Open the memory map"
            title="See the archive as a map"
            className="rounded-lg px-2 py-1 text-white/30 transition-colors hover:text-white/70"
          >
            {/* Connected nodes: the archive as a shape. */}
            <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.2">
              <circle cx="4" cy="4.5" r="1.8" />
              <circle cx="12" cy="6.5" r="1.6" />
              <circle cx="7" cy="12" r="1.6" />
              <path d="M5.6 5.3 10.4 6M5 6.2 6.5 10.4M8.5 11.2 11 8" strokeLinecap="round" />
            </svg>
          </button>
        )}

        <button
          type="button"
          onClick={() => {
            const next = !voiceMode;
            setVoiceMode(next);
            // Turning voice off should silence anything mid-sentence.
            if (!next) audioRef.current?.pause();
          }}
          aria-pressed={voiceMode}
          title={voiceMode ? "Replies are spoken aloud" : "Replies are text only"}
          className={`flex items-center gap-1.5 rounded-lg px-2 py-1 text-[0.65rem] uppercase tracking-[0.15em] transition-colors ${
            voiceMode ? "text-white/80" : "text-white/30 hover:text-white/60"
          }`}
        >
          <svg viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
            <path d="M8 2.5v11M4.5 5.5v5M11.5 5.5v5M1.5 7.5v1M14.5 7.5v1" />
          </svg>
          Voice
        </button>
        </div>
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
                    ? "wrap-anywhere whitespace-pre-wrap leading-relaxed text-white/75"
                    : "wrap-anywhere whitespace-pre-wrap leading-relaxed text-white/95"
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
                        <p className="wrap-anywhere mt-1 leading-relaxed text-white/40">
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
              <div className="flex items-start gap-2">
                <p className="wrap-anywhere flex-1 text-red-200/90">{error.message}</p>
                <button
                  type="button"
                  onClick={() => setError(null)}
                  aria-label="Dismiss error"
                  className="shrink-0 text-red-200/50 transition-colors hover:text-red-200"
                >
                  ✕
                </button>
              </div>
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
        {(isRecording || transcribing || recorder.error) && (
          <div className="mb-2 flex items-center gap-2 text-[0.7rem]">
            {isRecording && (
              <>
                <span className="size-1.5 animate-pulse rounded-full bg-red-400" />
                <span className="text-white/55">Listening… tap the square to stop</span>
                <button
                  type="button"
                  onClick={recorder.cancel}
                  className="ml-auto text-white/35 transition-colors hover:text-white/70"
                >
                  Discard
                </button>
              </>
            )}
            {transcribing && (
              <span className="text-white/45">Transcribing on this machine…</span>
            )}
            {recorder.error && !isRecording && (
              <span role="alert" className="text-red-300/85">
                {recorder.error}
              </span>
            )}
          </div>
        )}
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
            onClick={() => void toggleRecording()}
            disabled={pending || transcribing}
            aria-label={isRecording ? "Stop recording and transcribe" : "Record a message"}
            aria-pressed={isRecording}
            className={`glass-button rounded-2xl px-4 py-3 transition-colors disabled:opacity-25 ${
              isRecording ? "!border-red-400/40 !bg-red-500/20 text-red-200" : "text-white/70"
            }`}
          >
            {isRecording ? (
              // A square reads as "stop" more clearly than a mic that is
              // already active.
              <span className="block size-4 rounded-[3px] bg-current" />
            ) : (
              <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
                <rect x="5.75" y="1.75" width="4.5" height="8" rx="2.25" />
                <path d="M3.25 7.5a4.75 4.75 0 0 0 9.5 0M8 12.25v2" />
              </svg>
            )}
          </button>
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
