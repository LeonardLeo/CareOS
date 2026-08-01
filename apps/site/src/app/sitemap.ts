import type { MetadataRoute } from "next";

import { LEGAL_PAGES, NAV, SITE_ORIGIN } from "@/content/site";

/**
 * The sitemap, derived rather than written.
 *
 * Built from the same `NAV` and `LEGAL_PAGES` the header, footer, and policy index render, so
 * a page cannot be added to the site and forgotten here — the failure mode of a hand-kept
 * sitemap is that it silently describes last quarter's site.
 *
 * `output: "export"` turns this into a static `sitemap.xml` at build time.
 */
export const dynamic = "force-static";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const paths = ["/", ...NAV.map((item) => item.href), "/legal/", ...LEGAL_PAGES.map((p) => p.href)];

  return paths.map((path) => ({
    url: new URL(path, SITE_ORIGIN).toString(),
    lastModified: now,
    // The home page is the entry point; the marketing pages are the argument; the policies are
    // reference. Ordering them tells a crawler what to re-check, and nothing more than that.
    changeFrequency: path === "/" ? "weekly" : "monthly",
    priority: path === "/" ? 1 : path.startsWith("/legal/") ? 0.3 : 0.7,
  }));
}
