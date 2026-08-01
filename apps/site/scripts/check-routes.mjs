/**
 * Asserts the exported site and its sitemap describe the same set of pages.
 *
 * Two ways this drifts, and both are silent. A page added under `src/app/` but never added to
 * `NAV` or `LEGAL_PAGES` is published and unreachable — nobody links to it and no crawler
 * finds it. A route removed from `src/app/` but left in the registry becomes a link to a 404,
 * which on a policy page reads as a company hiding a document rather than as a stale constant.
 *
 * Run after `npm run build`. Exits non-zero on either kind of drift.
 *
 * One local gotcha, since it cost time once: Next caches the generated `sitemap.xml` in
 * `.next/`, and editing only `src/content/site.ts` does not always invalidate it. A failure
 * here that contradicts the source is that cache — `rm -rf .next` and build again. CI checks
 * out fresh, so it never sees this.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const out = join(root, "out");

/** Every route the export actually produced, as a trailing-slash path. */
function exported(dir = out) {
  const routes = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (entry.startsWith("_") || entry.startsWith(".")) continue;
      routes.push(...exported(path));
    } else if (entry === "index.html") {
      const rel = relative(out, dir).split("/").join("/");
      routes.push(rel ? `/${rel}/` : "/");
    }
  }
  return routes;
}

const built = new Set(exported());
// 404 is a page, not a route: it is reachable only by getting somewhere wrong, so it belongs
// in neither the sitemap nor the navigation.
built.delete("/404/");

const sitemapXml = readFileSync(join(out, "sitemap.xml"), "utf8");
const listed = new Set(
  [...sitemapXml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => new URL(m[1]).pathname),
);

const unlisted = [...built].filter((route) => !listed.has(route)).sort();
const missing = [...listed].filter((route) => !built.has(route)).sort();

for (const route of unlisted) console.log(`built but not in the sitemap: ${route}`);
for (const route of missing) console.log(`in the sitemap but not built: ${route}`);

if (unlisted.length || missing.length) {
  console.log(`\n${unlisted.length + missing.length} route(s) out of sync`);
  process.exit(1);
}
console.log(`${built.size} routes, sitemap agrees`);
