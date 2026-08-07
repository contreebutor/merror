"use client";

/**
 * Microphone recording via MediaRecorder.
 *
 * Kept out of the component because the lifecycle is fiddly: the stream has to
 * be stopped explicitly or the browser keeps showing a recording indicator, and
 * the final chunk only arrives after `onstop`.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type RecorderState = "idle" | "requesting" | "recording" | "stopping";

/** Codecs in preference order; Safari and Chrome disagree on what they support. */
const CANDIDATE_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return CANDIDATE_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

/** Extension matching the negotiated container, so the backend can route it. */
function extensionFor(mimeType: string): string {
  if (mimeType.includes("mp4")) return ".mp4";
  if (mimeType.includes("ogg")) return ".ogg";
  return ".webm";
}

export function useRecorder() {
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const resolveRef = useRef<((result: { blob: Blob; filename: string } | null) => void) | null>(
    null,
  );

  /** Release the microphone so the browser's recording indicator turns off. */
  const releaseStream = useCallback(() => {
    recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
    recorderRef.current = null;
  }, []);

  useEffect(() => releaseStream, [releaseStream]);

  const start = useCallback(async () => {
    setError(null);

    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError("This browser cannot record audio.");
      return false;
    }

    setState("requesting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (cause) {
      setState("idle");
      // Distinguish "said no" from "no microphone" — the fixes differ.
      const denied = cause instanceof DOMException && cause.name === "NotAllowedError";
      setError(
        denied
          ? "Microphone access was blocked. Allow it in your browser settings to use voice."
          : "No microphone was found.",
      );
      return false;
    }

    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorderRef.current = recorder;
    chunksRef.current = [];

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };

    recorder.onstop = () => {
      const type = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(chunksRef.current, { type });
      chunksRef.current = [];
      releaseStream();
      setState("idle");

      // A blob under a few hundred bytes is a misfire, not speech.
      resolveRef.current?.(
        blob.size > 512 ? { blob, filename: `recording${extensionFor(type)}` } : null,
      );
      resolveRef.current = null;
    };

    recorder.start();
    setState("recording");
    return true;
  }, [releaseStream]);

  /** Stop recording and resolve with the audio, or null if nothing usable was captured. */
  const stop = useCallback((): Promise<{ blob: Blob; filename: string } | null> => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return Promise.resolve(null);

    setState("stopping");
    return new Promise((resolve) => {
      resolveRef.current = resolve;
      recorder.stop();
    });
  }, []);

  /** Abandon a recording without transcribing it. */
  const cancel = useCallback(() => {
    resolveRef.current?.(null);
    resolveRef.current = null;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    releaseStream();
    setState("idle");
  }, [releaseStream]);

  return { state, error, start, stop, cancel, setError };
}
