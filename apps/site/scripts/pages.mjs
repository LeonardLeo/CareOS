/**
 * The list of pages the audits walk, read from the built sitemap.
 *
 * Derived rather than typed out, because two scripts each keeping their own copy is how a new
 * page ends up audited by neither. The sitemap is itself generated from `src/content/site.ts`,
 * and `check-routes.mjs` asserts it matches what was actually exported — so this list is the
 * real set of pages, transitively.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const SITEMAP = fileURLToPath(new URL("../out/sitemap.xml", import.meta.url));

export function sitePages() {
  let xml;
  try {
    xml = readFileSync(SITEMAP, "utf8");
  } catch {
    console.error("out/sitemap.xml is missing. Run `npm run build` first.");
    process.exit(2);
  }
  return [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => new URL(m[1]).pathname);
}
