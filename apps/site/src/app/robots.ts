import type { MetadataRoute } from "next";

import { SITE_ORIGIN } from "@/content/site";

/**
 * Everything here is meant to be found, so the rule is `allow: "/"` with no exceptions.
 *
 * Worth stating rather than leaving to a default: a `robots.txt` that disallows nothing is a
 * deliberate position on a site whose whole purpose is to be read by someone evaluating us.
 */
// Required under `output: "export"`: a metadata route is a handler by default, and the export
// refuses to guess that this one never varies. Saying so turns it into a file at build time.
export const dynamic = "force-static";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/" }],
    sitemap: new URL("/sitemap.xml", SITE_ORIGIN).toString(),
  };
}
