/**
 * The brand mark: a schedule week with one shift missing.
 *
 * Inline SVG rather than a file, so it inherits `currentColor` and costs no request. The
 * whole identity is one idea — a grid of time with a hole in it — and this is that idea at
 * 24 pixels.
 */
export function Mark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      role="img"
      aria-label="CareOS"
      focusable="false"
    >
      <rect width="24" height="24" rx="6" fill="var(--accent)" />
      <g fill="var(--on-accent)">
        <rect x="5" y="6.5" width="10" height="2.2" rx="1.1" />
        <rect x="5" y="10.9" width="14" height="2.2" rx="1.1" />
        <rect x="5" y="15.3" width="6" height="2.2" rx="1.1" />
      </g>
      {/* The gap. Same red as an unfilled shift on the board, for the same reason. */}
      <rect x="12.6" y="15.3" width="6.4" height="2.2" rx="1.1" fill="var(--signal)" />
    </svg>
  );
}
