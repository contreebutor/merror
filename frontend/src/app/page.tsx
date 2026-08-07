"use client";

import { useEffect, useState } from "react";
import { API_URL, fetchConfigStatus, type BackendState } from "@/lib/config";

export default function Home() {
  const [state, setState] = useState<BackendState | null>(null);

  useEffect(() => {
    fetchConfigStatus().then(setState);
  }, []);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <div className="text-center">
        <h1 className="text-4xl font-light tracking-[0.3em]">MERROR</h1>
        <p className="mt-1 text-sm opacity-50">frontend placeholder — slice 3</p>
      </div>

      <div className="w-full max-w-md rounded border border-white/15 p-4 text-sm">
        <div className="mb-2 font-medium opacity-70">Configuration</div>
        {state === null && <p className="opacity-50">Checking backend…</p>}

        {state?.reachable === false && (
          <div className="space-y-1">
            <p className="text-red-400">{state.error}</p>
            <p className="opacity-50">
              Start it with{" "}
              <code className="opacity-80">uvicorn app.main:app --reload</code>
            </p>
          </div>
        )}

        {state?.reachable === true && (
          <ul className="space-y-1">
            {Object.entries(state.status.features).map(([feature, ready]) => (
              <li key={feature} className="flex justify-between">
                <span className="capitalize opacity-70">{feature}</span>
                <span className={ready ? "text-green-400" : "text-amber-400"}>
                  {ready ? "ready" : "missing key"}
                </span>
              </li>
            ))}
            {state.status.missing.length > 0 && (
              <li className="pt-2 opacity-50">
                Add {state.status.missing.join(", ")} to <code>.env</code> and
                restart the backend.
              </li>
            )}
          </ul>
        )}
      </div>

      <p className="text-xs opacity-30">{API_URL}</p>
    </main>
  );
}
