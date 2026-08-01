/**
 * Accessibility and layout checks for the public site.
 *
 * The checks themselves live in `tools/ui-audit/`, shared with the admin console — they were
 * written here and moved there the first time a second app needed them, rather than copied.
 * This file is the site's page list and its two site-specific decisions: the skip link is
 * exercised with real key presses, and the page list comes from the built sitemap.
 *
 *     npm run build && npx serve out -l 3002 &
 *     node scripts/a11y.mjs
 *
 * `/legal/accessibility/` claims these run on every change and fail the build. The `site` job
 * in CI is what makes that true.
 *
 * What none of it can check: whether the result is comprehensible through a screen reader.
 * Reading order, the usefulness of a label, and whether a live region announces at a helpful
 * moment are judgements that need a person using real assistive technology.
 */

import { ALL_CHECKS } from "../../../tools/ui-audit/checks.mjs";
import { audit } from "../../../tools/ui-audit/run.mjs";
import { launch, devices } from "./browser.mjs";
import { sitePages } from "./pages.mjs";

const browser = await launch();

const findings = await audit({
  browser,
  baseUrl: process.argv[2] ?? "http://localhost:3002",
  pages: sitePages(),
  checks: ALL_CHECKS,
  skipLink: true,
  devices,
});

await browser.close();
console.log(findings ? `\n${findings} violation(s)` : "\nno violations");
process.exit(findings ? 1 : 0);
