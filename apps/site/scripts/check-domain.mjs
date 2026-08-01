/**
 * Asserts `security.txt` names the same domain as the rest of the site.
 *
 * Everything else derives from `SITE_DOMAIN`. `public/.well-known/security.txt` cannot: it is
 * a static file served verbatim, and RFC 9116 wants absolute URLs in it. So it is the one
 * place the domain is written a second time, and this is what keeps the two from drifting.
 *
 * The failure it prevents is specific and quiet. A researcher who finds something reads
 * `security.txt`, mails the address in it, and hears nothing — because that address still
 * points at the domain the site had a year ago.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const source = readFileSync(fileURLToPath(new URL("../src/content/site.ts", import.meta.url)), "utf8");
const match = source.match(/export const SITE_DOMAIN = "([^"]+)"/);
if (!match) {
  console.error("could not find SITE_DOMAIN in src/content/site.ts");
  process.exit(2);
}
const domain = match[1];

const securityTxt = readFileSync(
  fileURLToPath(new URL("../public/.well-known/security.txt", import.meta.url)),
  "utf8",
);

const hosts = [...securityTxt.matchAll(/(?:https:\/\/|mailto:[^@\s]+@)([^\/\s]+)/g)].map((m) => m[1]);
const wrong = [...new Set(hosts)].filter((host) => host !== domain && host !== `www.${domain}`);

if (wrong.length) {
  console.error(`security.txt names ${wrong.join(", ")}; SITE_DOMAIN is ${domain}`);
  process.exit(1);
}
console.log(`security.txt and SITE_DOMAIN both say ${domain} (${hosts.length} references)`);
