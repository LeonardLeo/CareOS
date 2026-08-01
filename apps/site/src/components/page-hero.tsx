import type { ReactNode } from "react";

import { Reveal } from "@/components/reveal";

/**
 * The opening of every page except the home page.
 *
 * One shape, used everywhere, so an interior page announces itself the same way each time.
 * The variety on this site belongs in the sections below the fold; a different hero treatment
 * per page would read as five sites rather than one.
 */
export function PageHero({
  eyebrow,
  title,
  lede,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  lede?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="section section--tight ruled">
      <div className="shell">
        <Reveal>
          <p className="eyebrow">{eyebrow}</p>
          <h1 className="display d2" style={{ marginTop: "var(--s4)", maxWidth: "18ch" }}>
            {title}
          </h1>
          {lede && (
            <p className="lede" style={{ marginTop: "var(--s5)" }}>
              {lede}
            </p>
          )}
          {children}
        </Reveal>
      </div>
    </section>
  );
}
