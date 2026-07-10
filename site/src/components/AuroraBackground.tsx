/** Three fixed blurred radial-gradient blobs drifting on slow keyframe loops
 * (design handoff v2). Pure decoration: pointer-events none, and the drift
 * animations are disabled under prefers-reduced-motion in global.css. */
export function AuroraBackground() {
  return (
    <div className="aurora" aria-hidden="true">
      <div className="blob-1" />
      <div className="blob-2" />
      <div className="blob-3" />
    </div>
  )
}
