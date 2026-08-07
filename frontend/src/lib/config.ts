/**
 * Frontend configuration.
 *
 * Only non-secret values live here. API keys are held exclusively by the
 * backend — anything in this file is readable by anyone with devtools.
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

/** Shape of GET /config/status on the backend. */
export type ConfigStatus = {
  configured: boolean;
  missing: string[];
  features: { chat: boolean; vision: boolean; voice_in: boolean; voice_out: boolean };
  model: string;
};

export type BackendState =
  | { reachable: true; status: ConfigStatus }
  | { reachable: false; error: string };

/**
 * Ask the backend what it has configured.
 *
 * Never throws — an unreachable backend is an expected state (the user may not
 * have started it yet), so it is returned as data for the UI to render.
 */
export async function fetchConfigStatus(): Promise<BackendState> {
  try {
    const res = await fetch(`${API_URL}/config/status`, { cache: "no-store" });
    if (!res.ok) {
      return { reachable: false, error: `Backend returned ${res.status}` };
    }
    return { reachable: true, status: (await res.json()) as ConfigStatus };
  } catch {
    return {
      reachable: false,
      error: `Cannot reach the backend at ${API_URL}`,
    };
  }
}
