"use client";

/**
 * An interactive timeline mark.
 *
 * The chart previously relied on the browser's `title` attribute, which is not a tooltip:
 * it is slow to appear, cannot be styled, is unreachable by keyboard, and is skipped by
 * several screen readers. This replaces it with a real hover/focus layer.
 *
 * Two rules from the interaction spec that this exists to satisfy:
 *
 * - **Keyboard focus shows the same as hover.** The mark is a `<button>`, so it is tabbable
 *   and the tooltip appears on focus as well as pointer-over.
 * - **The hit target is bigger than the mark.** A 14px-tall bar is a pinpoint target; an
 *   invisible padded hit area brings it to the ~24px minimum without changing how the
 *   chart looks.
 *
 * The tooltip enhances but never gates: the same information is in the table below the
 * chart, so nothing is reachable only by hovering.
 */

import { useState } from "react";

export function TimelineMark({
  className,
  style,
  label,
  detail,
}: {
  className: string;
  style: React.CSSProperties;
  label: string;
  detail: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <button
      type="button"
      className={className}
      style={style}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      aria-label={`${label}. ${detail}`}
    >
      {/* Invisible padded hit area — the mark stays thin, the target does not. */}
      <span className="timeline__hit" aria-hidden="true" />
      {open && (
        <span className="tooltip" role="tooltip">
          <span className="tooltip__title">{label}</span>
          <span className="tooltip__detail">{detail}</span>
        </span>
      )}
    </button>
  );
}
