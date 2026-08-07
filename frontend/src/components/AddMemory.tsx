"use client";

/**
 * Adding to the archive: paste text, or drop a document or image.
 *
 * One panel with two modes rather than three separate forms — documents and
 * images differ only in which endpoint they hit, and the file picker can tell
 * them apart from the extension.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  type SupportedTypes,
  createTextMemory,
  getSupportedTypes,
  uploadFile,
} from "@/lib/api";

type Mode = "text" | "file";

type Status =
  | { kind: "idle" }
  | { kind: "busy"; label: string }
  | { kind: "done"; label: string }
  | { kind: "failed"; message: string };

/** Fallbacks used only until the backend reports its real limits. */
const FALLBACK: SupportedTypes = {
  extensions: [".pdf", ".docx", ".txt", ".md"],
  max_bytes: 25 * 1024 * 1024,
  image_extensions: [".jpg", ".jpeg", ".png", ".gif", ".webp"],
  image_max_bytes: 3_750_000,
};

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

export default function AddMemory({
  onAdded,
  onClose,
}: {
  onAdded: () => void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<Mode>("text");
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const [types, setTypes] = useState<SupportedTypes>(FALLBACK);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Ask the backend what it accepts rather than duplicating the limits here,
  // so the two can never drift apart.
  useEffect(() => {
    let active = true;
    void getSupportedTypes().then((result) => {
      if (active && result.ok) setTypes(result.data);
    });
    return () => {
      active = false;
    };
  }, []);

  // Memoised: this feeds submitFile's dependency list, and a fresh array each
  // render would re-create the callback every time.
  const accepted = useMemo(
    () => [...types.extensions, ...types.image_extensions],
    [types],
  );

  const submitFile = useCallback(
    async (file: File) => {
      const extension = extensionOf(file.name);
      const isImage = types.image_extensions.includes(extension);
      const isDocument = types.extensions.includes(extension);

      if (!isImage && !isDocument) {
        setStatus({
          kind: "failed",
          message: `Cannot read ${extension || file.name}. Accepted: ${accepted.join(", ")}.`,
        });
        return;
      }

      // Check size before uploading — failing fast beats sending 25 MB to be
      // rejected, especially for images, which also cost an API call.
      const limit = isImage ? types.image_max_bytes : types.max_bytes;
      if (file.size > limit) {
        setStatus({
          kind: "failed",
          message: `${file.name} is ${(file.size / 1_048_576).toFixed(1)} MB, over the ${(
            limit / 1_048_576
          ).toFixed(1)} MB limit.`,
        });
        return;
      }

      setStatus({
        kind: "busy",
        // Image ingestion waits on a vision call, so it is worth saying why
        // this one takes longer than a document.
        label: isImage ? "Looking at the image…" : "Reading the document…",
      });

      const result = await uploadFile(isImage ? "image" : "document", file, title.trim());

      if (!result.ok) {
        setStatus({ kind: "failed", message: result.error.message });
        return;
      }

      setStatus({ kind: "done", label: `Remembered ${file.name}` });
      setTitle("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      onAdded();
    },
    [accepted, onAdded, title, types],
  );

  async function submitText() {
    const content = text.trim();
    if (!content) return;

    setStatus({ kind: "busy", label: "Remembering…" });
    const result = await createTextMemory(content, title.trim());

    if (!result.ok) {
      setStatus({ kind: "failed", message: result.error.message });
      return;
    }

    setStatus({ kind: "done", label: "Remembered" });
    setText("");
    setTitle("");
    onAdded();
  }

  const busy = status.kind === "busy";

  return (
    <section className="glass shrink-0 rounded-2xl p-4">
      <header className="mb-3 flex items-center justify-between">
        <div className="flex gap-1" role="tablist" aria-label="What to add">
          {(["text", "file"] as Mode[]).map((option) => (
            <button
              key={option}
              type="button"
              role="tab"
              aria-selected={mode === option}
              onClick={() => {
                setMode(option);
                setStatus({ kind: "idle" });
              }}
              className={`rounded-lg px-2.5 py-1 text-[0.7rem] transition-colors ${
                mode === option
                  ? "bg-white/12 text-white/85"
                  : "text-white/40 hover:text-white/70"
              }`}
            >
              {option === "text" ? "Write" : "Upload"}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="rounded-lg px-1.5 text-white/35 transition-colors hover:text-white/75"
        >
          ✕
        </button>
      </header>

      <input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder="Title (optional)"
        aria-label="Title"
        disabled={busy}
        className="glass-raised mb-2 w-full rounded-xl px-3 py-2 text-xs text-white/85 outline-none placeholder:text-white/25 focus:border-white/25 disabled:opacity-40"
      />

      {mode === "text" ? (
        <>
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              // ⌘/Ctrl+Enter saves, matching the send shortcut in chat.
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                void submitText();
              }
            }}
            rows={4}
            placeholder="Something worth remembering…"
            aria-label="Memory text"
            disabled={busy}
            className="glass-raised w-full resize-none rounded-xl px-3 py-2 text-xs leading-relaxed text-white/85 outline-none placeholder:text-white/25 focus:border-white/25 disabled:opacity-40"
          />
          <button
            type="button"
            onClick={() => void submitText()}
            disabled={busy || !text.trim()}
            className="glass-button mt-2 w-full rounded-xl py-2 text-xs text-white/80 disabled:opacity-25"
          >
            {busy ? status.label : "Remember this"}
          </button>
        </>
      ) : (
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            const file = event.dataTransfer.files?.[0];
            if (file) void submitFile(file);
          }}
          className={`rounded-xl border border-dashed px-4 py-7 text-center transition-colors ${
            dragging ? "border-white/45 bg-white/[0.07]" : "border-white/15"
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={accepted.join(",")}
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void submitFile(file);
            }}
            className="sr-only"
            id="memory-file"
          />
          <label
            htmlFor="memory-file"
            className="cursor-pointer text-xs text-white/55 transition-colors hover:text-white/85"
          >
            {busy ? status.label : "Drop a file, or choose one"}
          </label>
          <p className="mt-2 text-[0.65rem] leading-relaxed text-white/25">
            {types.extensions.join(" ")} · {types.image_extensions.join(" ")}
          </p>
        </div>
      )}

      {status.kind === "failed" && (
        <p role="alert" className="wrap-anywhere mt-2 text-[0.7rem] leading-relaxed text-red-300/85">
          {status.message}
        </p>
      )}
      {status.kind === "done" && (
        <p role="status" className="mt-2 text-[0.7rem] text-emerald-300/70">
          {status.label}
        </p>
      )}
    </section>
  );
}
