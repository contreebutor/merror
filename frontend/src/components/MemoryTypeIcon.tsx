import type { MemoryType } from "@/lib/api";

/**
 * Inline SVG glyphs for the three memory types.
 *
 * Hand-drawn rather than an icon package: three 16px glyphs do not justify a
 * dependency, and these inherit `currentColor` so they pick up the glass
 * palette without extra styling.
 */
const PATHS: Record<MemoryType, React.ReactNode> = {
  // Lines of writing.
  text: (
    <>
      <path d="M3.5 4h9M3.5 8h9M3.5 12h5.5" />
    </>
  ),
  // A page with a folded corner.
  document: (
    <>
      <path d="M4 1.5h5l3 3V14a.5.5 0 0 1-.5.5h-7A.5.5 0 0 1 4 14V2a.5.5 0 0 1 .5-.5Z" />
      <path d="M9 1.5v3h3" />
    </>
  ),
  // A frame with a horizon and a sun.
  image: (
    <>
      <rect x="2" y="3" width="12" height="10" rx="1.5" />
      <circle cx="5.75" cy="6.5" r="1" />
      <path d="m2.5 11 3-3 2.5 2.5L10.5 8l3 3" />
    </>
  ),
};

const LABELS: Record<MemoryType, string> = {
  text: "Note",
  document: "Document",
  image: "Image",
};

export default function MemoryTypeIcon({
  type,
  className = "",
}: {
  type: MemoryType;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role="img"
      aria-label={LABELS[type]}
    >
      {PATHS[type]}
    </svg>
  );
}
