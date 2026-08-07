"use client";

/**
 * Tells you what is not configured, before you find out by failing.
 *
 * Without this the first sign of a missing key is an error after typing a
 * message — the app looks broken rather than unconfigured. Speech-to-text runs
 * locally and needs no key, so a partially configured install still says
 * clearly what does work.
 */

import { useEffect, useState } from "react";

import { type ConfigStatus, fetchConfigStatus } from "@/lib/config";

export default function SetupNotice() {
  const [status, setStatus] = useState<ConfigStatus | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let active = true;
    void fetchConfigStatus().then((state) => {
      if (!active) return;
      if (state.reachable) setStatus(state.status);
      else setUnreachable(true);
    });
    return () => {
      active = false;
    };
  }, []);

  if (dismissed) return null;
  if (!unreachable && (!status || status.configured)) return null;

  const missing = status?.missing ?? [];
  const chatBlocked = missing.includes("ANTHROPIC_API_KEY");

  return (
    <div
      role="status"
      className="glass mb-3 flex items-start gap-3 rounded-2xl border-amber-300/20 px-4 py-3 text-xs sm:mb-4"
    >
      <span aria-hidden="true" className="mt-0.5 text-amber-300/70">
        ●
      </span>

      <div className="min-w-0 flex-1 leading-relaxed">
        {unreachable ? (
          <>
            <p className="text-white/75">The backend is not running.</p>
            <p className="mt-1 text-white/45">
              Start it with{" "}
              <code className="text-white/65">uvicorn app.main:app --reload</code> in
              the <code className="text-white/65">backend</code> directory.
            </p>
          </>
        ) : (
          <>
            <p className="text-white/75">
              {chatBlocked
                ? "MERROR needs an Anthropic API key before it can talk back."
                : "Spoken replies are switched off."}
            </p>
            <p className="mt-1 text-white/45">
              Add {missing.join(" and ")} to your{" "}
              <code className="text-white/65">.env</code> and restart the backend.
              {!chatBlocked && " Everything else works without it."}
            </p>
            {chatBlocked && (
              <p className="mt-1 text-white/35">
                Adding memories and recording voice notes work already — both run
                on this machine.
              </p>
            )}
          </>
        )}
      </div>

      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss"
        className="shrink-0 text-white/30 transition-colors hover:text-white/70"
      >
        ✕
      </button>
    </div>
  );
}
