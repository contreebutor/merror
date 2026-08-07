import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { NextConfig } from "next";

/**
 * Load the repo-root `.env` so there is a single source of truth for config.
 *
 * Next.js only reads .env files inside the app directory, so we parse the root
 * one here. Only NEXT_PUBLIC_* values are forwarded — the Anthropic and
 * ElevenLabs keys stay backend-side and must never reach the browser bundle.
 */
function loadPublicRootEnv(): Record<string, string> {
  const envPath = resolve(__dirname, "..", ".env");
  if (!existsSync(envPath)) return {};

  const publicVars: Record<string, string> = {};
  for (const line of readFileSync(envPath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;

    const key = trimmed.slice(0, eq).trim();
    if (!key.startsWith("NEXT_PUBLIC_")) continue;

    // Strip matched surrounding quotes, if present.
    const value = trimmed
      .slice(eq + 1)
      .trim()
      .replace(/^(['"])(.*)\1$/, "$2");
    publicVars[key] = value;
  }
  return publicVars;
}

const nextConfig: NextConfig = {
  env: loadPublicRootEnv(),
};

export default nextConfig;
