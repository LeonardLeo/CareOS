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

import { chromium, devices } from "playwright";

const OUT = process.env.SHOT_DIR ?? "/tmp/careos-site-shots";
const BASE = "http://localhost:3002";
const PAGES = [
  "/",
  "/product/",
  "/security/",
  "/about/",
  "/careers/",
  "/contact/",
  "/legal/privacy/",
  "/legal/terms/",
  "/legal/subprocessors/",
  "/nope/",
];

const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" });

for (const width of [1440, 390]) {
  const ctx = await b.newContext(
    width === 390
      ? { ...devices["Pixel 7"], deviceScaleFactor: 1 }
      : { viewport: { width, height: 950 }, deviceScaleFactor: 1 },
  );
  const page = await ctx.newPage();
  const problems = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
  page.on("requestfailed", (r) => problems.push(`request failed: ${r.url()}`));
  page.on("response", (r) => { if (r.status() >= 400) problems.push(`${r.status()} ${r.url()}`); });

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
