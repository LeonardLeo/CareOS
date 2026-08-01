/**
 * Drives a set of pages through `checks.mjs` at several viewports and colour schemes.
 *
 * Shared by the public site, the admin console, and the caregiver app. Each of those supplies
 * its own page list and, where the screens are behind a login, a `prepare` hook that signs in
 * once per browser context.
 */

import { inspect } from "./checks.mjs";

/** Desktop, tablet, phone, and dark. Dark is a full pass: the palette inverts wholesale, so a
 * token that reads fine on paper can fail on ink and no light-mode run would notice. */
export const DEFAULT_VIEWPORTS = [
  { label: "desktop", width: 1440, height: 950, scheme: "light" },
  { label: "tablet ", width: 1024, height: 900, scheme: "light" },
  { label: "mobile ", width: 390, height: 844, scheme: "light", phone: true },
  { label: "dark   ", width: 1440, height: 950, scheme: "dark" },
];

/**
 * Scrolls a page end to end so everything has been laid out and any reveal animation has run.
 *
 * `scroll-behavior: smooth` turns a scripted loop into a measurement of the easing curve — the
 * first version of this reached 231px of a 4612px page and reported the whole document as
 * unrevealed. Disabling it here measures the page instead.
 */
async function settle(page) {
  await page.addStyleTag({ content: "html { scroll-behavior: auto !important; }" });
  await page.evaluate(async () => {
    const step = window.innerHeight * 0.75;
    const max = document.documentElement.scrollHeight - window.innerHeight;
    for (let y = 0; y <= max; y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 50)));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(350);
}

/**
 * The skip link, exercised with real key events.
 *
 * A scripted `focus()` would pass while the tab order was wrong, and the defect this was
 * written for was exactly that: the link scrolled but never moved focus, because `main` had no
 * `tabindex="-1"`, so the next Tab went straight back into the nav.
 */
async function checkSkipLink(page) {
  const problems = [];
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.keyboard.press("Tab");
  const first = await page.evaluate(() => {
    const el = document.activeElement;
    const style = el ? getComputedStyle(el) : null;
    return {
      isSkip: !!el?.classList.contains("skip"),
      tag: el?.tagName.toLowerCase() ?? "none",
      outline: style ? `${style.outlineStyle} ${style.outlineWidth}` : "",
    };
  });
  if (!first.isSkip) {
    problems.push({ check: "skip", detail: `first Tab landed on ${first.tag}` });
    return problems;
  }
  if (first.outline.startsWith("none")) {
    problems.push({ check: "skip", detail: "skip link has no visible focus outline" });
    return problems;
  }
  await page.keyboard.press("Enter");
  const moved = await page.evaluate(() => {
    const el = document.activeElement;
    return !!el && (el.id === "main" || !!el.closest("#main"));
  });
  if (!moved) {
    problems.push({ check: "skip", detail: "activating the skip link did not move focus into #main" });
  }
  return problems;
}

/**
 * @param {object} config
 * @param {object} config.browser      a launched Playwright browser
 * @param {string} config.baseUrl
 * @param {string[]} config.pages      paths to walk
 * @param {string[]} config.checks     which checks from `checks.mjs` to run
 * @param {string[]} [config.ignore]   selectors to skip, each with a stated reason
 * @param {boolean} [config.skipLink]  exercise the skip link with real key presses
 * @param {(context, page) => Promise<void>} [config.prepare]  sign in, once per context
 * @param {object} [config.devices]    Playwright's device registry, for the phone viewport
 * @returns {Promise<number>} the number of findings
 */
export async function audit({
  browser,
  baseUrl,
  pages,
  checks,
  ignore = [],
  skipLink = false,
  prepare,
  devices,
  viewports = DEFAULT_VIEWPORTS,
}) {
  let findings = 0;

  for (const view of viewports) {
    const context = await browser.newContext(
      view.phone && devices
        ? { ...devices["Pixel 7"], deviceScaleFactor: 1, colorScheme: view.scheme }
        : {
            viewport: { width: view.width, height: view.height },
            deviceScaleFactor: 1,
            colorScheme: view.scheme,
          },
    );
    const page = await context.newPage();
    if (prepare) await prepare(context, page);

    for (const path of pages) {
      const response = await page.goto(baseUrl + path, { waitUntil: "networkidle" });
      if (!response || response.status() >= 400) {
        console.log(`FAIL ${view.label} ${path} — HTTP ${response?.status() ?? "no response"}`);
        findings += 1;
        continue;
      }
      // A screen that quietly redirected to the login page is not the screen under audit, and
      // auditing the login page eleven times would look like a pass.
      const landed = new URL(page.url()).pathname;
      if (landed !== path && !path.startsWith(landed)) {
        console.log(`FAIL ${view.label} ${path} — redirected to ${landed}`);
        findings += 1;
        continue;
      }

      await settle(page);
      const problems = await page.evaluate(inspect, { checks, ignore });
      if (skipLink) problems.push(...(await checkSkipLink(page)));

      if (problems.length) {
        findings += problems.length;
        console.log(`FAIL ${view.label} ${path}`);
        for (const p of problems) console.log(`       ${p.check.padEnd(10)} ${p.detail}`);
      } else {
        console.log(`ok   ${view.label} ${path}`);
      }
    }
    await context.close();
  }

  return findings;
}
