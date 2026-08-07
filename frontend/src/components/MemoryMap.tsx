"use client";

/**
 * The archive as a shape: memories placed by meaning, close ones linked.
 *
 * Inline SVG rather than React Flow or D3. The server already computed the
 * layout, so a graph library would add weight to do pan and zoom that is a
 * handful of lines here — and SVG inherits the glass palette for free.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import MemoryTypeIcon from "@/components/MemoryTypeIcon";
import {
  type MapNode,
  type MemoryMap as MemoryMapData,
  deleteMemory,
  getMemoryMap,
  memoryImageUrl,
} from "@/lib/api";
import { relativeTime } from "@/lib/format";

/** Cluster colours, matched to the aurora palette so the map belongs to the app. */
const CLUSTER_COLOURS = [
  "#8b8ae0", // indigo
  "#5fb3c4", // teal
  "#c48ab8", // mauve
  "#d9a06a", // ember
  "#7fc4a0", // sage
  "#c98b8b", // clay
  "#9db4e0", // slate blue
  "#d4c47f", // straw
];

function colourFor(cluster: number): string {
  return CLUSTER_COLOURS[cluster % CLUSTER_COLOURS.length];
}

/** Server coordinates are [-1, 1]; the viewBox adds room for labels at the edge. */
const VIEW = 2.6;

export default function MemoryMap({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<MemoryMapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<MapNode | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });

  const dragState = useRef<{ x: number; y: number; panX: number; panY: number } | null>(
    null,
  );

  /** Apply a fetched map. Split out so the effect never setStates synchronously. */
  const apply = useCallback((result: Awaited<ReturnType<typeof getMemoryMap>>) => {
    setLoading(false);
    if (!result.ok) {
      setError(result.error.message);
      return;
    }
    setError(null);
    setData(result.data);
  }, []);

  // State changes only inside the promise callback: calling setState directly
  // in an effect body triggers cascading renders.
  useEffect(() => {
    let active = true;
    void getMemoryMap().then((result) => {
      if (active) apply(result);
    });
    return () => {
      active = false;
    };
  }, [apply]);

  /** Re-fetch after a change. Safe to setState here — it runs from an event. */
  const reload = useCallback(async () => {
    setLoading(true);
    apply(await getMemoryMap());
  }, [apply]);

  // Escape closes the selection first, then the map — the usual layered
  // expectation for a dismissible overlay.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (selected) setSelected(null);
      else onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, onClose]);

  async function forget(id: string) {
    const result = await deleteMemory(id);
    if (!result.ok) {
      setError(result.error.message);
      return;
    }
    setSelected(null);
    // Re-fetch rather than splicing: removing a memory changes the projection
    // for every other one, so the whole layout has to be recomputed.
    void reload();
  }

  const nodes = data?.nodes ?? [];
  const byId = new Map(nodes.map((node) => [node.id, node]));

  return (
    <div className="glass relative flex h-full w-full flex-col overflow-hidden rounded-3xl">
      <header className="glass-divider flex shrink-0 items-center gap-3 border-b px-5 py-4">
        <h2 className="text-[0.65rem] uppercase tracking-[0.25em] text-white/45">
          Map
          {nodes.length > 0 && (
            <span className="ml-2 text-white/25">
              {nodes.length} · {data?.clusters} clusters
            </span>
          )}
        </h2>

        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
            }}
            className="rounded-lg px-2 py-1 text-[0.65rem] text-white/35 transition-colors hover:text-white/75"
          >
            Reset
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close map"
            className="rounded-lg px-2 py-1 text-white/40 transition-colors hover:text-white/80"
          >
            ✕
          </button>
        </div>
      </header>

      <div className="relative flex-1 overflow-hidden">
        {loading && (
          <p className="absolute inset-0 grid place-items-center text-xs text-white/30">
            Laying out the archive…
          </p>
        )}

        {error && (
          <p
            role="alert"
            className="absolute inset-0 grid place-items-center px-8 text-center text-xs text-red-300/80"
          >
            {error}
          </p>
        )}

        {!loading && !error && nodes.length === 0 && (
          <p className="absolute inset-0 grid place-items-center px-10 text-center text-xs leading-relaxed text-white/30">
            Nothing to map yet. Add a few memories and their shape will appear
            here.
          </p>
        )}

        {nodes.length > 0 && (
          <svg
            viewBox={`${-VIEW / 2} ${-VIEW / 2} ${VIEW} ${VIEW}`}
            className="size-full cursor-grab touch-none active:cursor-grabbing"
            role="img"
            aria-label={`Memory map with ${nodes.length} memories`}
            onPointerDown={(event) => {
              dragState.current = {
                x: event.clientX,
                y: event.clientY,
                panX: pan.x,
                panY: pan.y,
              };
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => {
              const start = dragState.current;
              if (!start) return;
              // Convert pixel movement into viewBox units so dragging tracks
              // the cursor at any zoom level.
              const scale = VIEW / event.currentTarget.clientWidth / zoom;
              setPan({
                x: start.panX + (event.clientX - start.x) * scale,
                y: start.panY + (event.clientY - start.y) * scale,
              });
            }}
            onPointerUp={() => {
              dragState.current = null;
            }}
            onWheel={(event) => {
              setZoom((current) =>
                Math.min(6, Math.max(0.5, current * (event.deltaY < 0 ? 1.12 : 0.89))),
              );
            }}
          >
            <g transform={`scale(${zoom}) translate(${pan.x} ${pan.y})`}>
              {/* Edges first so nodes draw over them. */}
              {(data?.edges ?? []).map((edge) => {
                const source = byId.get(edge.source);
                const target = byId.get(edge.target);
                if (!source || !target) return null;
                return (
                  <line
                    key={`${edge.source}-${edge.target}`}
                    x1={source.x}
                    y1={source.y}
                    x2={target.x}
                    y2={target.y}
                    stroke="white"
                    // Stronger similarity draws a more visible thread.
                    strokeOpacity={0.06 + edge.similarity * 0.22}
                    strokeWidth={0.004}
                  />
                );
              })}

              {nodes.map((node) => {
                const isSelected = selected?.id === node.id;
                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x} ${node.y})`}
                    onPointerUp={(event) => {
                      // Ignore the pointer-up that ends a drag.
                      event.stopPropagation();
                      if (dragState.current) return;
                      setSelected(node);
                    }}
                    className="cursor-pointer"
                  >
                    <circle
                      r={isSelected ? 0.038 : 0.024}
                      fill={colourFor(node.cluster)}
                      fillOpacity={isSelected ? 1 : 0.85}
                      stroke="white"
                      strokeOpacity={isSelected ? 0.9 : 0.2}
                      strokeWidth={0.006}
                    />
                    {/* Scale the label inversely so text stays readable as the
                        map zooms. */}
                    <text
                      x={0}
                      y={0.06}
                      textAnchor="middle"
                      fill="white"
                      fillOpacity={0.45}
                      style={{ fontSize: `${0.05 / Math.max(zoom, 1) ** 0.35}px` }}
                    >
                      {node.title.length > 22
                        ? `${node.title.slice(0, 21)}…`
                        : node.title}
                    </text>
                  </g>
                );
              })}
            </g>
          </svg>
        )}

        {selected && (
          <aside className="glass-raised absolute inset-x-3 bottom-3 rounded-2xl p-4 sm:inset-x-auto sm:right-3 sm:w-72">
            <div className="flex items-start gap-2">
              <MemoryTypeIcon
                type={selected.type}
                className="mt-0.5 size-4 shrink-0"
                // Tie the panel to the dot the user clicked.
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs text-white/85">{selected.title}</p>
                <p className="text-[0.65rem] text-white/30">
                  {relativeTime(selected.created_at)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                aria-label="Close details"
                className="text-white/35 transition-colors hover:text-white/75"
              >
                ✕
              </button>
            </div>

            {selected.has_image && (
              /* Served by the local backend, so next/image optimisation does
                 not apply. */
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={memoryImageUrl(selected.id)}
                alt={selected.title}
                className="mt-3 max-h-32 w-full rounded-lg object-cover"
              />
            )}

            <p className="mt-3 text-[0.7rem] leading-relaxed text-white/50">
              {selected.snippet}
            </p>

            <button
              type="button"
              onClick={() => void forget(selected.id)}
              className="mt-3 w-full rounded-lg border border-red-400/25 bg-red-500/10 py-1.5 text-[0.7rem] text-red-200/90 transition-colors hover:bg-red-500/20"
            >
              Forget this
            </button>
          </aside>
        )}
      </div>
    </div>
  );
}
