/**
 * Shared browser setup for the site's audit scripts.
 *
 * This module exists because the first version of `audit.mjs` imported `"playwright"` by bare
 * specifier while it was not a dependency of this package: the script was committed, and
 * broken, and nothing noticed, because a script outside the build is only exercised when
 * somebody runs it. Playwright is a devDependency here now, and the failure — if it ever
 * happens again — is one readable line rather than a module-resolution stack.
 */

import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

let chromium;
let devices;
try {
  ({ chromium, devices } = await import("playwright"));
} catch {
  console.error("playwright is not installed. Run `npm ci` in apps/site.");
  process.exit(2);
}

/**
 * Finds the pre-installed Chromium.
 *
 * The directory carries a build number that changes with Playwright's version, so it is
 * discovered rather than hardcoded — a pinned `chromium-1194` becomes a confusing failure the
 * first time the browser bundle is updated.
 */
function executablePath() {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH;
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH ?? "/opt/pw-browsers";
  if (!existsSync(root)) return undefined;
  for (const entry of readdirSync(root)) {
    if (!entry.startsWith("chromium")) continue;
    const candidate = join(root, entry, "chrome-linux", "chrome");
    if (existsSync(candidate)) return candidate;
  }
  // Undefined lets Playwright use whatever it downloaded itself, which is right on a laptop.
  return undefined;
}

export async function launch() {
  return chromium.launch({ executablePath: executablePath() });
}

export { devices };
