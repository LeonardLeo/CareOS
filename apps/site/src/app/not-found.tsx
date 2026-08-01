import type { Metadata } from "next";
import Link from "next/link";

import { NAV } from "@/content/site";

export const metadata: Metadata = {
  title: "Page not found",
  // A 404 that a search engine keeps in its index sends the next person to the same dead end.
  robots: { index: false, follow: true },
};

/**
 * 404.
 *
 * Offers the way onward rather than a joke. Someone who followed a broken link is already
 * slightly annoyed, and the useful thing is a list of where they might have been going.
 */
export default function NotFound() {
  return (
    <section className="section ruled">
      <div className="shell column">
        <p className="eyebrow">404</p>
        <h1 className="display d2" style={{ marginTop: "var(--s4)" }}>
          That page is not here.
        </h1>
        <p className="lede" style={{ marginTop: "var(--s4)" }}>
          Either it moved or the link was wrong. Here is everything there is.
        </p>
        <ul className="footer__links" style={{ marginTop: "var(--s6)", fontSize: "1rem" }}>
          <li>
            <Link href="/">Home</Link>
          </li>
          {NAV.map((item) => (
            <li key={item.href}>
              <Link href={item.href}>{item.label}</Link>
            </li>
          ))}
          {/* The policies are the likeliest thing to be reached by a stale link, since they are
              what gets pasted into a compliance review and read months later. */}
          <li>
            <Link href="/legal/">Policies</Link>
          </li>
        </ul>
      </div>
    </section>
  );
}
