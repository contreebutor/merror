/**
 * The animated gradient field behind everything.
 *
 * Pure CSS — four blurred blobs drifting on coprime periods. No canvas, no
 * WebGL, no JavaScript running per frame: the compositor owns it, so it costs
 * essentially nothing while the app is idle.
 *
 * Rendered once in the root layout and sits at z-index -2, so every screen
 * gets the same continuous background rather than restarting it per route.
 */
export default function Aurora() {
  return (
    <div className="aurora" aria-hidden="true">
      <div className="aurora-blob aurora-blob-1" />
      <div className="aurora-blob aurora-blob-2" />
      <div className="aurora-blob aurora-blob-3" />
      <div className="aurora-blob aurora-blob-4" />
    </div>
  );
}
