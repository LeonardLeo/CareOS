"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { Mark } from "@/components/mark";
import { NAV, SIGN_IN_URL, SITE_NAME } from "@/content/site";

/**
 * Sticky header.
 *
 * The bottom rule appears only once the page has scrolled. At the top there is nothing to
 * separate the header from, and a permanent line there reads as a seam in what should be one
 * surface.
 */
export function SiteHeader() {
  const pathname = usePathname();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className="masthead" data-scrolled={scrolled}>
      <div className="shell masthead__inner">
        <Link className="brand" href="/">
          <Mark className="brand__mark" />
          {SITE_NAME}
        </Link>

        <nav className="nav" aria-label="Primary">
          {NAV.map((item) => {
            // Trailing slashes throughout, because the export is a directory of index.html
            // files and a link without one costs a redirect on every navigation.
            const current = pathname === item.href;
            return (
              <Link
                key={item.href}
                className="nav__link nav__link--wide"
                href={item.href}
                aria-current={current ? "page" : undefined}
              >
                {item.label}
              </Link>
            );
          })}
          <a className="btn btn--ghost btn--sm" href={SIGN_IN_URL}>
            Sign in
          </a>
        </nav>
      </div>
    </header>
  );
}
