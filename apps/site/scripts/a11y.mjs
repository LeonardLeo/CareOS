/**
 * An accessibility check that runs against the rendered pages.
 *
 * Deliberately not a wrapper around a scoring library. Each check below corresponds to a
 * specific claim made on `/legal/accessibility/`, so that the page describes something
 * verified rather than something intended — and so that a regression fails here rather than
 * being discovered by the person it excludes.
 *
 * What it checks:
 *   contrast   every rendered text node against its effective background, at the WCAG 2.1 AA
 *              thresholds (4.5:1, or 3:1 for text at 24px, or 18.66px bold and above)
 *   names      every link and button resolves to a non-empty accessible name
 *   labels     every form control resolves to one
 *   headings   exactly one h1, and no level skipped on the way down
 *   landmarks  a main element, and one that the skip link actually targets
 *   skip       the first focusable element is the skip link, and it moves focus
 *   tabindex   no positive tabindex anywhere
 *   lang       html carries a language
 *   alt        every img has an alt attribute (empty is fine and means decorative)
 *
 * What it cannot check, and what the page therefore does not claim: whether the result is
 * *comprehensible* through a screen reader. Reading order, the usefulness of a label, and
 * whether a live region announces at a helpful moment are judgements, and they need a person
 * using real assistive technology.
 *
 * Usage: node scripts/a11y.mjs [baseUrl]     (default http://localhost:3002)
 * Exits non-zero on any violation.
 */

import { launch, devices } from "./browser.mjs";
import { sitePages } from "./pages.mjs";

const BASE = process.argv[2] ?? "http://localhost:3002";
const PAGES = sitePages();

/** Runs in the page. Returns a flat list of violations, each `{ check, detail }`. */
function inspect() {
  const out = [];
  const add = (check, detail) => out.push({ check, detail });
  const where = (el) => {
    const id = el.id ? `#${el.id}` : "";
    const cls = el.className && typeof el.className === "string" ? `.${el.className.trim().split(/\s+/)[0]}` : "";
    const text = (el.textContent ?? "").trim().slice(0, 40);
    return `${el.tagName.toLowerCase()}${id}${cls}${text ? ` "${text}"` : ""}`;
  };

  // --- contrast -----------------------------------------------------------------------
  /**
   * Reads a computed colour.
   *
   * Two syntaxes reach here and they are on different scales. `rgb()`/`rgba()` gives 0-255,
   * but anything derived from `color-mix()` — the translucent masthead, the muted text inside
   * dark sections — computes to `color(srgb 0.97 0.96 0.94 / 0.86)`, whose channels are 0-1.
   * Reading those as 0-255 makes near-white parse as near-black, which is how the first run of
   * this script reported the site header at 1.18:1 and sent me looking for a bug in the CSS.
   */
  const parse = (value) => {
    const n = (value.match(/[\d.]+/g) ?? []).map(Number);
    if (n.length < 3) return null;
    const scale = value.startsWith("color(") ? 255 : 1;
    return { r: n[0] * scale, g: n[1] * scale, b: n[2] * scale, a: n.length > 3 ? n[3] : 1 };
  };
  const relative = ({ r, g, b }) => {
    const f = (c) => {
      const s = c / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  });
  /** Walks ancestors until something is opaque enough to be the background actually seen. */
  const backdrop = (el) => {
    let layer = { r: 255, g: 255, b: 255, a: 1 };
    const stack = [];
    for (let node = el; node && node !== document.documentElement.parentNode; node = node.parentElement) {
      const c = parse(getComputedStyle(node).backgroundColor);
      if (c && c.a > 0) stack.push(c);
      if (c && c.a === 1) break;
    }
    for (const c of stack.reverse()) layer = over(c, layer);
    return layer;
  };

  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none" || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  for (const el of document.querySelectorAll("body *")) {
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (!own || !visible(el)) continue;
    // The skip link is off-screen until focused; it is checked separately, when focused.
    if (el.classList.contains("skip")) continue;
    const s = getComputedStyle(el);
    const fg = parse(s.color);
    if (!fg) continue;
    const bg = backdrop(el);
    const composed = fg.a < 1 ? over(fg, bg) : fg;
    const [hi, lo] = [relative(composed), relative(bg)].sort((a, b) => b - a);
    const ratio = (hi + 0.05) / (lo + 0.05);
    const size = parseFloat(s.fontSize);
    const bold = Number(s.fontWeight) >= 700;
    const large = size >= 24 || (bold && size >= 18.66);
    const need = large ? 3 : 4.5;
    if (ratio < need) {
      add("contrast", `${where(el)} — ${ratio.toFixed(2)}:1, needs ${need}:1 (${s.color} on rgb(${Math.round(bg.r)},${Math.round(bg.g)},${Math.round(bg.b)}))`);
    }
  }

  // --- accessible names ---------------------------------------------------------------
  const named = (el) => {
    const label = el.getAttribute("aria-label");
    if (label && label.trim()) return true;
    const by = el.getAttribute("aria-labelledby");
    if (by && by.split(/\s+/).some((id) => document.getElementById(id)?.textContent.trim())) return true;
    if ((el.textContent ?? "").trim()) return true;
    return [...el.querySelectorAll("img[alt], svg title")].some(
      (n) => (n.getAttribute("alt") ?? n.textContent ?? "").trim(),
    );
  };
  for (const el of document.querySelectorAll("a[href], button")) {
    if (visible(el) && !named(el)) add("names", where(el));
  }

  // --- form labels --------------------------------------------------------------------
  for (const el of document.querySelectorAll("input:not([type=hidden]), select, textarea")) {
    const byFor = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    const wrapped = el.closest("label");
    const aria = el.getAttribute("aria-label") || el.getAttribute("aria-labelledby");
    if (!byFor && !wrapped && !aria) add("labels", where(el));
  }

  // --- headings -----------------------------------------------------------------------
  const headings = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].filter(visible);
  const h1s = headings.filter((h) => h.tagName === "H1");
  if (h1s.length !== 1) add("headings", `${h1s.length} h1 elements, expected exactly 1`);
  let previous = 0;
  for (const h of headings) {
    const level = Number(h.tagName[1]);
    if (previous && level > previous + 1) add("headings", `${where(h)} — h${previous} jumps to h${level}`);
    previous = level;
  }

  // --- landmarks ----------------------------------------------------------------------
  if (!document.querySelector("main")) add("landmarks", "no main element");
  const skip = document.querySelector("a.skip");
  if (!skip) add("landmarks", "no skip link");
  else if (!document.querySelector(skip.getAttribute("href")))
    add("landmarks", `skip link points at ${skip.getAttribute("href")}, which does not exist`);

  // --- misc ---------------------------------------------------------------------------
  for (const el of document.querySelectorAll("[tabindex]")) {
    if (Number(el.getAttribute("tabindex")) > 0) add("tabindex", `${where(el)} — positive tabindex`);
  }
  if (!document.documentElement.lang) add("lang", "html has no lang attribute");
  for (const img of document.querySelectorAll("img")) {
    if (!img.hasAttribute("alt")) add("alt", where(img));
  }

  return out;
}

const browser = await launch();

let failures = 0;
// Dark is a separate pass rather than a spot check: the palette inverts wholesale, so a token
// that reads fine on paper can fail on ink and nothing in the light pass would notice.
for (const [width, scheme, label] of [
  [1440, "light", "desktop"],
  [1440, "dark", "dark   "],
  [390, "light", "mobile "],
]) {
  const context = await browser.newContext(
    width === 390
      ? { ...devices["Pixel 7"], deviceScaleFactor: 1, colorScheme: scheme }
      : { viewport: { width, height: 950 }, deviceScaleFactor: 1, colorScheme: scheme },
  );
  const page = await context.newPage();

  for (const path of PAGES) {
    const response = await page.goto(BASE + path, { waitUntil: "networkidle" });
    if (!response || response.status() >= 400) {
      console.log(`FAIL ${label} ${path} — HTTP ${response?.status() ?? "no response"}`);
      failures += 1;
      continue;
    }
    const problems = await page.evaluate(inspect);

    // Keyboard: the first Tab must land on the skip link, and activating it must move focus
    // into the main region. Checked here rather than in the page script because it needs real
    // key events — a synthetic focus() would pass while the tab order was wrong.
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
    if (!first.isSkip) problems.push({ check: "skip", detail: `first Tab landed on ${first.tag}` });
    else if (first.outline.startsWith("none"))
      problems.push({ check: "skip", detail: "skip link has no visible focus outline" });
    else {
      await page.keyboard.press("Enter");
      const moved = await page.evaluate(() => {
        const el = document.activeElement;
        return !!el && (el.id === "main" || !!el.closest("#main"));
      });
      if (!moved) problems.push({ check: "skip", detail: "activating the skip link did not move focus into #main" });
    }

    if (problems.length) {
      failures += problems.length;
      console.log(`FAIL ${label} ${path}`);
      for (const p of problems) console.log(`       ${p.check.padEnd(10)} ${p.detail}`);
    } else {
      console.log(`ok   ${label} ${path}`);
    }
  }
  await context.close();
}

await browser.close();
console.log(failures ? `\n${failures} violation(s)` : "\nno violations");
process.exit(failures ? 1 : 0);
