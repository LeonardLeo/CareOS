/**
 * Layout defects that a build cannot see and a screenshot at one width will not show you.
 *
 * Written after `.legal ul li` shipped as a two-column grid whose items were `<strong>Lead-in.
 * </strong> the rest` — every child of a grid container is a grid item, including an anonymous
 * run of text, so the rest of each sentence was placed in the 0.9rem *marker* track and wrapped
 * at 14px. Items rendered 1096px tall. Nothing caught it: no horizontal overflow, nothing
 * hidden, every colour and label correct.
 *
 * `a11y.mjs` now catches the symptom (text squeezed into a narrow column). This catches the
 * cause, and four neighbouring failure modes, so the next instance is reported before it is
 * ugly enough for somebody to notice:
 *
 *   anon-item   a flex or grid container holding both element children and a bare text node.
 *               The text becomes its own anonymous item and is laid out in whatever track
 *               comes next, which is almost never what the author meant.
 *   clipped     `overflow: hidden` on a box whose content is meaningfully larger than it.
 *               Content silently amputated, most often at a width nobody tested.
 *   escapes     a child painted past its parent's padding box, where the parent does not
 *               scroll. Either the child is too wide or the parent forgot to constrain it.
 *   overlap     two text-bearing elements sharing pixels. Always a defect in this layout;
 *               nothing here is deliberately stacked.
 *   tap         an interactive target under 24x24 CSS px on a phone, per WCAG 2.2 (2.5.8).
 *
 * Usage: node scripts/layout.mjs [baseUrl]     (default http://localhost:3002)
 * Exits non-zero on any finding.
 */

import { launch, devices } from "./browser.mjs";
import { sitePages } from "./pages.mjs";

const BASE = process.argv[2] ?? "http://localhost:3002";

function inspect() {
  const out = [];
  const add = (check, detail) => out.push({ check, detail });
  const where = (el) => {
    if (!el) return "(none)";
    const id = el.id ? `#${el.id}` : "";
    const cls =
      typeof el.className === "string" && el.className.trim()
        ? `.${el.className.trim().split(/\s+/).join(".")}`
        : "";
    const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 34);
    return `${el.tagName.toLowerCase()}${id}${cls}${text ? ` "${text}"` : ""}`;
  };
  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none" || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  const all = [...document.querySelectorAll("body *")].filter((el) => visible(el));

  // --- anonymous items in a multi-track grid ----------------------------------------------
  /*
   * Narrower than "any flex or grid container with a stray text node", because that idiom is
   * usually correct: a button laid out as a single-row flex, holding its label and an arrow
   * span, wants the label to be an anonymous item — that is how the gap works. The version of
   * this check that flagged those reported 60 findings, none of them defects, which is how a
   * check gets ignored.
   *
   * The dangerous case is a grid with more than one column track. There, an anonymous run of
   * text does not sit beside its sibling; it is placed in the *next* track, whatever that
   * track was sized for. That is exactly what put a sentence in a 0.9rem bullet column.
   */
  for (const el of all) {
    const s = getComputedStyle(el);
    if (!/^(inline-)?grid$/.test(s.display)) continue;
    const tracks = s.gridTemplateColumns.split(/\s+/).filter(Boolean).length;
    if (tracks < 2) continue;
    if (el.firstElementChild === null) continue;
    const strayText = [...el.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim().length > 0,
    );
    if (strayText) {
      add(
        "anon-item",
        `${where(el)} — ${tracks}-track grid with a bare text node, which lands in the next track`,
      );
    }
  }

  // --- clipped content -------------------------------------------------------------------
  for (const el of all) {
    const s = getComputedStyle(el);
    // A scroller is doing its job; `hidden` is the one that loses content with no way back.
    if (s.overflowX !== "hidden" && s.overflowY !== "hidden") continue;
    // Ignore boxes that clip on purpose because something inside them is transformed or
    // absolutely placed — the reveal wrappers and the coverage board bars, for instance.
    // The visually-hidden pattern is a 1px box with `overflow: hidden` holding a whole
    // sentence for a screen reader. It is meant to clip; that is the entire technique.
    if (el.clientWidth <= 2 || el.clientHeight <= 2) continue;
    const slackY = el.scrollHeight - el.clientHeight;
    const slackX = el.scrollWidth - el.clientWidth;
    if (s.overflowY === "hidden" && slackY > 4 && el.clientHeight > 0)
      add("clipped", `${where(el)} — ${slackY}px of content below the fold of its own box`);
    if (s.overflowX === "hidden" && slackX > 4 && el.clientWidth > 0)
      add("clipped", `${where(el)} — ${slackX}px of content past its right edge`);
  }

  // --- children escaping their parent -----------------------------------------------------
  const scrolls = (el) => {
    const s = getComputedStyle(el);
    return /auto|scroll/.test(s.overflowX) || /auto|scroll/.test(s.overflowY);
  };
  for (const el of all) {
    const parent = el.parentElement;
    if (!parent || parent === document.body || !visible(parent)) continue;
    const s = getComputedStyle(el);
    // Positioned and transformed elements are placed deliberately; the marker dot on a legal
    // list item is exactly that, and reporting it would bury everything else.
    if (s.position !== "static" || s.transform !== "none" || s.float !== "none") continue;
    if (scrolls(parent) || getComputedStyle(parent).position === "fixed") continue;
    const child = el.getBoundingClientRect();
    const box = parent.getBoundingClientRect();
    const pad = getComputedStyle(parent);
    const right = box.right - parseFloat(pad.paddingRight) - parseFloat(pad.borderRightWidth);
    const left = box.left + parseFloat(pad.paddingLeft) + parseFloat(pad.borderLeftWidth);
    const spill = Math.max(child.right - right, left - child.left);
    if (spill > 2) add("escapes", `${where(el)} — ${Math.round(spill)}px outside ${where(parent)}`);
  }

  // --- overlapping text -------------------------------------------------------------------
  const leaves = all.filter(
    (el) =>
      [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 0) &&
      getComputedStyle(el).position === "static",
  );
  /*
   * Compared per line box, not by bounding rect. An inline element that wraps across lines has
   * a bounding rect covering the whole block it wraps within, so two `<strong>`s in the same
   * paragraph "overlap" by that measure — the first version of this check reported exactly
   * that on the HIPAA page and it was an artefact, not a defect. `getClientRects()` returns
   * one rect per line, which is what the reader actually sees.
   */
  const boxes = leaves.map((el) => [...el.getClientRects()]);
  for (let i = 0; i < leaves.length; i += 1) {
    for (let j = i + 1; j < leaves.length; j += 1) {
      const a = leaves[i];
      const b = leaves[j];
      if (a.contains(b) || b.contains(a)) continue;
      let worst = null;
      for (const ra of boxes[i]) {
        for (const rb of boxes[j]) {
          const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
          const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
          // A few pixels is line-box slop between neighbours, not two things stacked.
          if (w > 6 && h > 6 && (!worst || w * h > worst.w * worst.h)) worst = { w, h };
        }
      }
      if (worst) {
        add(
          "overlap",
          `${where(a)} over ${where(b)} — ${Math.round(worst.w)}x${Math.round(worst.h)}px`,
        );
      }
    }
  }

  // --- tap targets ------------------------------------------------------------------------
  if (window.innerWidth < 500) {
    for (const el of document.querySelectorAll("a[href], button, input, select, textarea")) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      // Inline links inside a sentence are exempt under 2.5.8; they have no other placement.
      if (el.tagName === "A" && getComputedStyle(el).display === "inline") continue;
      if (r.width < 24 || r.height < 24)
        add("tap", `${where(el)} — ${Math.round(r.width)}x${Math.round(r.height)}px`);
    }
  }

  return out;
}

const browser = await launch();
const PAGES = sitePages();

let findings = 0;
for (const [width, scheme, label] of [
  [1440, "light", "desktop"],
  [1024, "light", "tablet "],
  [390, "light", "mobile "],
  [1440, "dark", "dark   "],
]) {
  const context = await browser.newContext(
    width === 390
      ? { ...devices["Pixel 7"], deviceScaleFactor: 1, colorScheme: scheme }
      : { viewport: { width, height: 950 }, deviceScaleFactor: 1, colorScheme: scheme },
  );
  const page = await context.newPage();

  for (const path of PAGES) {
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    // Everything below measures painted geometry, so the page has to be fully revealed first.
    // `scroll-behavior: smooth` turns a scripted loop into a measurement of the easing curve.
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
    await page.waitForTimeout(400);

    const problems = await page.evaluate(inspect);
    if (problems.length) {
      findings += problems.length;
      console.log(`FAIL ${label} ${path}`);
      for (const p of problems) console.log(`       ${p.check.padEnd(10)} ${p.detail}`);
    } else {
      console.log(`ok   ${label} ${path}`);
    }
  }
  await context.close();
}

await browser.close();
console.log(findings ? `\n${findings} finding(s)` : "\nno layout defects");
process.exit(findings ? 1 : 0);
