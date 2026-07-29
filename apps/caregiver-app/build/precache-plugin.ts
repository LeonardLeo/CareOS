import { readFile, readdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { Plugin } from "vite";

/**
 * Writes the real list of built assets into the service worker's precache manifest.
 *
 * The first version of this app hand-maintained that list in `public/sw.js`, and it was wrong
 * within one build: the stylesheet is emitted as `assets/index.css` while the list named
 * `assets/app.css`. The failure mode is nasty and quiet — the shell caches, the stylesheet does
 * not, and a caregiver opening the app with no signal gets an unstyled page with an 88px button
 * rendered as a default-sized one.
 *
 * Deriving the list from the emitted bundle removes the possibility rather than fixing the
 * instance. If a future change adds a chunk, splits the CSS, or renames the entry, the manifest
 * follows automatically.
 */
export function precacheManifest(): Plugin {
  return {
    name: "careos-precache-manifest",
    // `closeBundle` rather than `writeBundle`: the public directory (which holds sw.js) is
    // copied as part of the build, and this has to run after that copy or it rewrites a file
    // that is about to be overwritten.
    async closeBundle() {
      const dist = join(process.cwd(), "dist");
      const swPath = join(dist, "sw.js");

      let source: string;
      try {
        source = await readFile(swPath, "utf8");
      } catch {
        // No service worker in this build (e.g. a library build). Nothing to rewrite.
        return;
      }

      const assets = await readdir(join(dist, "assets")).catch(() => [] as string[]);
      const urls = [
        "/",
        "/index.html",
        "/manifest.webmanifest",
        "/icon.svg",
        ...assets.map((name) => `/assets/${name}`),
      ];

      const marker = "__PRECACHE_MANIFEST__";
      if (!source.includes(marker)) {
        this.warn(`sw.js has no ${marker} placeholder; precache list left untouched`);
        return;
      }

      await writeFile(swPath, source.replace(marker, JSON.stringify(urls)), "utf8");
      this.info(`precached ${urls.length} shell assets`);
    },
  };
}
