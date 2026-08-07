"use client";

/**
 * The app shell: archive alongside conversation.
 *
 * Above `lg` both columns sit side by side. Below it the archive becomes an
 * overlay — a 320px sidebar on a phone would leave the chat unusable, and the
 * conversation is the primary surface.
 */

import { useState } from "react";

import Chat from "@/components/Chat";
import MemoryMap from "@/components/MemoryMap";
import SetupNotice from "@/components/SetupNotice";
import Sidebar from "@/components/Sidebar";

export default function Workspace() {
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);

  return (
    <main className="flex h-dvh gap-3 p-3 sm:gap-4 sm:p-6">
      {/* Persistent column on wide screens. */}
      <div className="hidden w-80 shrink-0 lg:block">
        <Sidebar />
      </div>

      {/* Overlay on narrow screens. Rendered only while open so the list is
          not fetched for a panel nobody has asked for. */}
      {archiveOpen && (
        <div className="fixed inset-0 z-20 lg:hidden">
          <button
            type="button"
            aria-label="Close archive"
            onClick={() => setArchiveOpen(false)}
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
          />
          <div className="absolute inset-y-3 left-3 w-[min(20rem,calc(100vw-1.5rem))]">
            <Sidebar onClose={() => setArchiveOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <SetupNotice />
        {mapOpen ? (
          <div className="min-h-0 flex-1">
            <MemoryMap onClose={() => setMapOpen(false)} />
          </div>
        ) : (
          <div className="min-h-0 flex-1">
          <Chat
            onOpenArchive={() => setArchiveOpen(true)}
            onOpenMap={() => setMapOpen(true)}
          />
          </div>
        )}
      </div>
    </main>
  );
}
