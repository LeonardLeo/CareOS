import type { ReactNode } from "react";

import { PageHero } from "@/components/page-hero";
import { Reveal } from "@/components/reveal";

/**
 * The shared shell for legal pages.
 *
 * Set at a comfortable reading measure with real paragraph rhythm, because these are the
 * pages most likely to be rendered as an unreadable wall and the ones a compliance officer
 * actually reads end to end.
 *
 * `updated` is required rather than optional. A policy with no date is one nobody can tell
 * has been reviewed.
 */
export function LegalPage({
  eyebrow,
  title,
  lede,
  updated,
  children,
}: {
  eyebrow: string;
  title: string;
  lede: string;
  updated: string;
  children: ReactNode;
}) {
  return (
    <>
      <PageHero eyebrow={eyebrow} title={title} lede={lede}>
        <p className="field__hint" style={{ marginTop: "var(--s5)" }}>
          Last updated {updated}
        </p>
      </PageHero>

      <section className="section section--tight">
        <div className="shell shell--narrow">
          <Reveal>
            <div className="legal">{children}</div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
