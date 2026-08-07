"use client";

/**
 * The memory archive: a searchable list of everything MERROR remembers, with
 * a per-item delete.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import AddMemory from "@/components/AddMemory";
import MemoryTypeIcon from "@/components/MemoryTypeIcon";
import {
  ABORTED,
  type MemorySummary,
  deleteMemory,
  listMemories,
} from "@/lib/api";
import { relativeTime } from "@/lib/format";

/** Wait for typing to settle before searching, so each keystroke isn't a request. */
const SEARCH_DEBOUNCE_MS = 250;

export default function Sidebar({ onClose }: { onClose?: () => void }) {
  const [memories, setMemories] = useState<MemorySummary[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  // Bumped after an ingest so the list reloads without a manual refresh.
  const [refreshToken, setRefreshToken] = useState(0);

  // Cancels the previous search so a slow early request can't land after a
  // fast later one and repaint the list with stale results.
  const inFlight = useRef<AbortController | null>(null);

  const load = useCallback(async (search: string) => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setLoading(true);
    const result = await listMemories({ query: search, signal: controller.signal });

    // A superseded request has nothing to say about the current state.
    if (controller.signal.aborted) return;

    setLoading(false);
    if (!result.ok) {
      if (result.error.message === ABORTED) return;
      setError(result.error.message);
      return;
    }

    setError(null);
    setMemories(result.data.memories);
    setTotal(result.data.total);
  }, []);

  // Debounce the query; reload immediately when the refresh token changes.
  useEffect(() => {
    const timer = setTimeout(() => void load(query), query ? SEARCH_DEBOUNCE_MS : 0);
    return () => clearTimeout(timer);
  }, [query, refreshToken, load]);

  useEffect(() => () => inFlight.current?.abort(), []);

  async function confirmDelete(id: string) {
    setDeletingId(id);
    const result = await deleteMemory(id);
    setDeletingId(null);
    setConfirmingId(null);

    if (!result.ok) {
      setError(result.error.message);
      return;
    }
    // Drop it locally rather than refetching — the list is already correct.
    setMemories((current) => current.filter((memory) => memory.id !== id));
    setTotal((current) => Math.max(0, current - 1));
  }

  return (
    <aside className="glass flex h-full w-full flex-col overflow-hidden rounded-3xl">
      <header className="glass-divider flex shrink-0 items-center justify-between gap-2 border-b px-5 py-4">
        <h2 className="text-[0.65rem] uppercase tracking-[0.25em] text-white/45">
          Archive{total > 0 && <span className="ml-2 text-white/25">{total}</span>}
        </h2>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setAdding((open) => !open)}
            aria-label={adding ? "Cancel adding a memory" : "Add a memory"}
            aria-expanded={adding}
            className={`rounded-lg px-2 py-0.5 text-lg leading-none transition-colors ${
              adding ? "text-white/80" : "text-white/40 hover:text-white/80"
            }`}
          >
            {adding ? "\u2212" : "+"}
          </button>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close archive"
              className="rounded-lg px-2 py-1 text-white/40 transition-colors hover:text-white/80 lg:hidden"
            >
              ✕
            </button>
          )}
        </div>
      </header>

      {adding && (
        <div className="shrink-0 px-4 pt-4">
          <AddMemory
            onAdded={() => setRefreshToken((n) => n + 1)}
            onClose={() => setAdding(false)}
          />
        </div>
      )}

      <div className="shrink-0 px-4 pt-4">
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by meaning…"
          aria-label="Search memories"
          className="glass-raised w-full rounded-xl px-3 py-2 text-sm text-white/90 outline-none transition-colors placeholder:text-white/30 focus:border-white/25"
        />
      </div>

      <div className="subtle-scroll flex-1 overflow-y-auto px-4 py-4">
        {loading && memories.length === 0 && (
          <p className="py-8 text-center text-xs text-white/30">Loading…</p>
        )}

        {error && (
          <p role="alert" className="py-4 text-xs leading-relaxed text-red-300/80">
            {error}
          </p>
        )}

        {!loading && !error && memories.length === 0 && (
          <p className="py-10 text-center text-xs leading-relaxed text-white/30">
            {query
              ? "Nothing in the archive matches that."
              : "The archive is empty. Anything you add will show up here."}
          </p>
        )}

        <ul className="flex flex-col gap-1">
          {memories.map((memory) => {
            const isConfirming = confirmingId === memory.id;
            const isDeleting = deletingId === memory.id;

            return (
              <li
                key={memory.id}
                className={`group rounded-xl px-3 py-2.5 transition-colors ${
                  isConfirming ? "bg-red-500/10" : "hover:bg-white/[0.06]"
                } ${isDeleting ? "opacity-40" : ""}`}
              >
                <div className="flex items-start gap-2.5">
                  <MemoryTypeIcon
                    type={memory.type}
                    className="mt-0.5 size-4 shrink-0 text-white/35"
                  />

                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2">
                      <p className="truncate text-xs text-white/75">
                        {memory.title || memory.source || "Untitled"}
                      </p>
                      {memory.score !== null && (
                        <span className="shrink-0 text-[0.65rem] text-white/25">
                          {Math.round(memory.score * 100)}%
                        </span>
                      )}
                    </div>
                    <p className="mt-1 line-clamp-2 text-[0.7rem] leading-relaxed text-white/40">
                      {memory.snippet}
                    </p>
                    <p className="mt-1 text-[0.65rem] text-white/20">
                      {relativeTime(memory.created_at)}
                      {memory.chunk_count > 1 && ` · ${memory.chunk_count} parts`}
                    </p>
                  </div>

                  {!isConfirming && (
                    <button
                      type="button"
                      onClick={() => setConfirmingId(memory.id)}
                      aria-label={`Delete ${memory.title || "memory"}`}
                      // Always reachable by keyboard; revealed on hover for pointers.
                      className="shrink-0 rounded-lg px-1.5 py-0.5 text-white/0 transition-colors group-hover:text-white/30 hover:!text-red-300 focus-visible:text-white/60"
                    >
                      ✕
                    </button>
                  )}
                </div>

                {isConfirming && (
                  <div className="mt-2 flex items-center gap-2 pl-6.5">
                    <span className="text-[0.7rem] text-white/60">
                      Forget this permanently?
                    </span>
                    <button
                      type="button"
                      onClick={() => void confirmDelete(memory.id)}
                      disabled={isDeleting}
                      className="rounded-lg border border-red-400/30 bg-red-500/15 px-2 py-0.5 text-[0.7rem] text-red-200 transition-colors hover:bg-red-500/25 disabled:opacity-50"
                    >
                      {isDeleting ? "Forgetting…" : "Forget"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmingId(null)}
                      className="rounded-lg px-2 py-0.5 text-[0.7rem] text-white/45 transition-colors hover:text-white/80"
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
}
