/**
 * Drives every page in a real browser and reports what a build cannot.
 *
 *     npx serve out -l 3002 &
 *     node scripts/audit.mjs
 *
 * Three things it checks, each of which has actually gone wrong here:
 *
 * - **stuckHidden** — elements left at `data-reveal="hidden"` after the page has been
 *   scrolled end to end. Those are invisible, not merely un-animated, so any non-zero value
 *   is content a reader will never see.
 * - **overflow** — horizontal scroll on the document. The classic responsive defect, and one
 *   that is invisible in a screenshot taken at the width it was designed for.
 * - **failed requests** — a 404 on a favicon or a font is a real request on every page load.
 *
 * Not wired into CI, which has no browser. Run it before shipping a change to the site.
 */

import { launch, devices } from "./browser.mjs";
import { sitePages } from "./pages.mjs";

const OUT = process.env.SHOT_DIR ?? "/tmp/careos-site-shots";
const BASE = "http://localhost:3002";
// From the sitemap, so a page added to the site is audited without anyone remembering to add
// it here. `/nope/` is appended deliberately: the 404 is a page too, and it is the one most
// likely to be shipped broken because nobody visits it on purpose.
const PAGES = [...sitePages(), "/nope/"];

const b = await launch();

for (const width of [1440, 390]) {
  const ctx = await b.newContext(
    width === 390
      ? { ...devices["Pixel 7"], deviceScaleFactor: 1 }
      : { viewport: { width, height: 950 }, deviceScaleFactor: 1 },
  );
  const page = await ctx.newPage();
  const problems = [];
  page.on("console", (m) => {
    // Same reason as the response filter below: the browser logs the deliberate 404 as an
    // error, and it is attributed to that URL, so it can be dropped precisely.
    if (m.type() !== "error" || m.location().url.endsWith("/nope/")) return;
    problems.push(`console: ${m.text()}`);
  });
  page.on("requestfailed", (r) => problems.push(`request failed: ${r.url()}`));
  // `/nope/` is supposed to 404 — that is what it is for. Reporting it as a problem trains you
  // to ignore the PROBLEMS line, which is where a real missing font would appear.
  page.on("response", (r) => {
    if (r.status() >= 400 && !r.url().endsWith("/nope/")) problems.push(`${r.status()} ${r.url()}`);
  });

  for (const path of PAGES) {
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    await page.waitForTimeout(400);
    // The site sets `scroll-behavior: smooth`, so scripted `scrollTo` calls animate and a
    // loop of them barely moves the page — the first version of this harness reached 231px
    // of a 4612px page and reported the whole document as unrevealed. Disable it here so the
    // audit measures the page rather than the easing curve.
    await page.addStyleTag({ content: "html { scroll-behavior: auto !important; }" });
    await page.evaluate(async () => {
      const step = window.innerHeight * 0.75;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      for (let y = 0; y <= max; y += step) {
        window.scrollTo(0, y);
        await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 60)));
      }
      window.scrollTo(0, max);
      await new Promise((r) => setTimeout(r, 200));
    });
    await page.waitForTimeout(500);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    const hidden = await page.evaluate(
      () => document.querySelectorAll('[data-reveal="hidden"]').length,
    );
    const h1 = await page.evaluate(() => document.querySelectorAll("h1").length);
    const title = await page.title();
    console.log(
      `${String(width).padEnd(5)} ${path.padEnd(26)} overflow=${overflow} stuckHidden=${hidden} h1=${h1} | ${title.slice(0, 54)}`,
    );
    if (width === 1440 && process.env.SHOT_DIR) {
      const name = path === "/" ? "home" : path.replace(/\//g, "-").replace(/^-|-$/g, "");
      await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
    }
  }
  if (problems.length) console.log("PROBLEMS:", [...new Set(problems)].join(" | "));
  await ctx.close();
}
await b.close();
