"use client";

import { useEffect, useRef, type ElementType, type ReactNode } from "react";

/**
 * Reveals its children once they have reached the viewport.
 *
 * **The base state is visible.** `data-reveal="hidden"` is applied by the effect below, on
 * mount, so a browser with no JavaScript — or a crawler, or a reader mode — gets an ordinary
 * page rather than a blank one. Hiding only ever happens where something exists to un-hide it.
 *
 * **A rect check rather than IntersectionObserver.** Both work. This one is preferred because
 * it holds no per-element observer and has no threshold to reason about: it asks, on each
 * settled frame, whether the element has reached the fold yet. One shared listener serves
 * every instance, and the pending set empties as the page is read, so the cost falls away.
 *
 * The state it can reach is worth stating plainly, because it is the one that matters: an
 * element left at `data-reveal="hidden"` is *invisible*, not merely un-animated. Any change
 * here should be checked by scrolling a whole page and asserting nothing is still hidden —
 * `scripts/audit.mjs` does that across every page at two widths. Note that the site sets
 * `scroll-behavior: smooth`, so a scripted scroll loop must disable it first or it measures
 * the easing curve instead of the page.
 */

/** Elements still waiting to be shown. Module-level, so all instances share one listener. */
const pending = new Set<HTMLElement>();
let frame = 0;
let listening = false;

/** Fraction of the viewport an element must clear before it is revealed. */
const TRIGGER_MARGIN = 0.06;

function sweep() {
  frame = 0;
  const fold = window.innerHeight * (1 - TRIGGER_MARGIN);
  for (const node of [...pending]) {
    if (node.getBoundingClientRect().top < fold) {
      node.dataset.reveal = "shown";
      pending.delete(node);
    }
  }
  if (pending.size === 0) stopListening();
}

function schedule() {
  if (frame) return;
  frame = requestAnimationFrame(sweep);
}

function startListening() {
  if (listening) return;
  listening = true;
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule, { passive: true });
}

function stopListening() {
  if (!listening) return;
  listening = false;
  window.removeEventListener("scroll", schedule);
  window.removeEventListener("resize", schedule);
}

export function Reveal({
  children,
  as: Tag = "div",
  delay = 0,
  className,
}: {
  children: ReactNode;
  as?: ElementType;
  /** Stagger, in milliseconds. Sparingly: a long cascade reads as a slow page. */
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    // Respect the setting rather than merely animating faster. Someone who asked for reduced
    // motion usually asked because motion makes them unwell.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    node.dataset.reveal = "hidden";
    pending.add(node);
    startListening();
    // Sweep once immediately, so anything already above the fold appears on this frame
    // instead of waiting for the reader to scroll.
    schedule();

    return () => {
      pending.delete(node);
      if (pending.size === 0) stopListening();
    };
  }, []);

  return (
    <Tag ref={ref} className={className} style={{ "--reveal-delay": `${delay}ms` } as object}>
      {children}
    </Tag>
  );
}
