/**
 * Every UI check, in one place, for every app.
 *
 * These began as two scripts inside `apps/site`. They moved here the first time a second app
 * needed them, rather than being copied — a check that exists in three files is a check that
 * is true in one of them.
 *
 * `inspect` is serialised into the page by `page.evaluate`, so it closes over nothing and
 * imports nothing. Everything it needs arrives in `options`.
 *
 * The checks, and the defect each was written for:
 *
 *   contrast   text against the background actually behind it, composited through
 *              transparency, at WCAG 2.1 AA (4.5:1, or 3:1 for large text). Found muted text
 *              at 3.97:1 across every eyebrow and figure source on the public site.
 *   squeezed   a sentence laid out into a column too narrow to hold it. Found a list item
 *              rendered 1096px tall, one word per line.
 *   anon-item  a bare text node inside a multi-track grid, which is placed in the next track
 *              rather than beside its sibling. The cause of the above.
 *   clipped    content larger than its own `overflow: hidden` box.
 *   escapes    a child painted outside its parent's padding box.
 *   overlap    two text elements sharing pixels, compared per line box. Found a footer whose
 *              brand column collapsed to 20px and painted the wordmark over the next column.
 *   names      links and buttons with no accessible name; form controls with no label.
 *   headings   exactly one h1, no level skipped.
 *   landmarks  a main element, and a skip link that points at something real.
 *   tap        an interactive target under 24x24 on a phone (WCAG 2.2, 2.5.8).
 *   misc       positive tabindex, missing `lang`, missing `alt`.
 *
 * What none of them can check: whether the result is *comprehensible* through a screen
 * reader. Reading order, the usefulness of a label, and whether a live region announces at a
 * helpful moment are judgements that need a person using real assistive technology.
 */

/**
 * @param {object} options
 * @param {string[]} options.checks   which checks to run
 * @param {string[]} [options.ignore] CSS selectors to skip entirely, with a reason in the code
 *                                   that adds them — never as a way to quiet a real finding
 */
export function inspect(options) {
  const enabled = new Set(options.checks);
  const ignore = options.ignore ?? [];
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

  const skipped = (el) => ignore.some((selector) => el.closest(selector));

  const all = [...document.querySelectorAll("body *")].filter((el) => visible(el) && !skipped(el));

  // --- colour ------------------------------------------------------------------------------
  /**
   * Reads a computed colour.
   *
   * Two syntaxes reach here on different scales. `rgb()`/`rgba()` gives 0-255, but anything
   * derived from `color-mix()` computes to `color(srgb 0.97 0.96 0.94 / 0.86)`, whose channels
   * are 0-1. Reading those as 0-255 makes near-white parse as near-black — the first run of
   * this check accused a near-white site header of 1.18:1 before it accused itself.
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

  const ownsText = (el) =>
    [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 0);

  if (enabled.has("contrast")) {
    for (const el of all) {
      if (!ownsText(el)) continue;
      // Off-screen until focused; checked separately, when focused.
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
      const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
      if (ratio < need) {
        add(
          "contrast",
          `${where(el)} — ${ratio.toFixed(2)}:1, needs ${need}:1 (${s.color} on rgb(${Math.round(bg.r)},${Math.round(bg.g)},${Math.round(bg.b)}))`,
        );
      }
    }
  }

  // --- squeezed text -------------------------------------------------------------------
  if (enabled.has("squeezed")) {
    const MIN_LINE = 80;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.textContent.trim();
      if (text.length <= 30) continue;
      const parent = node.parentElement;
      if (!parent || !visible(parent) || skipped(parent)) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const rects = [...range.getClientRects()];
      if (rects.length < 2) continue;
      const widest = Math.max(...rects.map((r) => r.width));
      if (widest < MIN_LINE) {
        add(
          "squeezed",
          `${where(parent)} — "${text.slice(0, 34)}" over ${rects.length} lines, widest ${Math.round(widest)}px`,
        );
      }
    }
  }

  // --- anonymous items in a multi-track grid -------------------------------------------
  /*
   * Narrower than "any flex or grid container with a stray text node", because that idiom is
   * usually correct: a button laid out as a single-row flex, holding its label beside an arrow
   * span, wants the label to be an anonymous item — that is how the gap works. The version
   * that flagged those reported 60 findings, none of them defects, which is how a check gets
   * ignored. In a grid with more than one column track the text is placed in the *next* track
   * instead, whatever that track was sized for.
   */
  if (enabled.has("anon-item")) {
    for (const el of all) {
      const s = getComputedStyle(el);
      if (!/^(inline-)?grid$/.test(s.display)) continue;
      if (s.gridTemplateColumns.split(/\s+/).filter(Boolean).length < 2) continue;
      if (el.firstElementChild === null) continue;
      if (ownsText(el)) {
        add("anon-item", `${where(el)} — multi-track grid with a bare text node`);
      }
    }
  }

  // --- clipped content ------------------------------------------------------------------
  if (enabled.has("clipped")) {
    for (const el of all) {
      const s = getComputedStyle(el);
      if (s.overflowX !== "hidden" && s.overflowY !== "hidden") continue;
      // The visually-hidden pattern is a 1px box with `overflow: hidden` holding a whole
      // sentence for a screen reader. It is meant to clip; that is the entire technique.
      if (el.clientWidth <= 2 || el.clientHeight <= 2) continue;
      const slackY = el.scrollHeight - el.clientHeight;
      const slackX = el.scrollWidth - el.clientWidth;
      if (s.overflowY === "hidden" && slackY > 4)
        add("clipped", `${where(el)} — ${slackY}px of content below the fold of its own box`);
      if (s.overflowX === "hidden" && slackX > 4)
        add("clipped", `${where(el)} — ${slackX}px of content past its right edge`);
    }
  }

  // --- children escaping their parent ---------------------------------------------------
  if (enabled.has("escapes")) {
    const scrolls = (el) => {
      const s = getComputedStyle(el);
      return /auto|scroll/.test(s.overflowX) || /auto|scroll/.test(s.overflowY);
    };
    for (const el of all) {
      const parent = el.parentElement;
      if (!parent || parent === document.body || !visible(parent)) continue;
      const s = getComputedStyle(el);
      // Positioned and transformed elements are placed deliberately — a bullet marker, a
      // tooltip. Reporting them would bury everything else.
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
  }

  // --- overlapping text -----------------------------------------------------------------
  /*
   * Compared per line box, not by bounding rect. An inline element that wraps has a bounding
   * rect covering the whole block it wraps within, so two `<strong>`s in one paragraph read as
   * stacked — an artefact, not a defect. `getClientRects()` is what the reader sees.
   */
  if (enabled.has("overlap")) {
    /*
     * Rects clipped by their scroll containers first. A table inside `overflow-x: auto` is
     * wider than the box that shows it, so the cells scrolled out of view still report rects
     * — sitting, on paper, on top of whatever is beside the wrapper. Comparing raw geometry
     * reported fifteen overlaps between a scrolled table and the panel next to it, none of
     * which a reader could see. Intersecting with each clipping ancestor measures what is
     * actually on screen.
     */
    const clipOf = (el) => {
      let box = { left: -Infinity, top: -Infinity, right: Infinity, bottom: Infinity };
      for (let node = el.parentElement; node; node = node.parentElement) {
        const s = getComputedStyle(node);
        if (s.overflowX === "visible" && s.overflowY === "visible") continue;
        const r = node.getBoundingClientRect();
        box = {
          left: Math.max(box.left, r.left),
          top: Math.max(box.top, r.top),
          right: Math.min(box.right, r.right),
          bottom: Math.min(box.bottom, r.bottom),
        };
      }
      return box;
    };
    const clipRect = (rect, clip) => {
      const left = Math.max(rect.left, clip.left);
      const top = Math.max(rect.top, clip.top);
      const right = Math.min(rect.right, clip.right);
      const bottom = Math.min(rect.bottom, clip.bottom);
      return right - left > 0 && bottom - top > 0 ? { left, top, right, bottom } : null;
    };

    const leaves = all.filter((el) => ownsText(el) && getComputedStyle(el).position === "static");
    const boxes = leaves.map((el) => {
      const clip = clipOf(el);
      return [...el.getClientRects()].map((r) => clipRect(r, clip)).filter(Boolean);
    });
    for (let i = 0; i < leaves.length; i += 1) {
      for (let j = i + 1; j < leaves.length; j += 1) {
        if (leaves[i].contains(leaves[j]) || leaves[j].contains(leaves[i])) continue;
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
            `${where(leaves[i])} over ${where(leaves[j])} — ${Math.round(worst.w)}x${Math.round(worst.h)}px`,
          );
        }
      }
    }
  }

  // --- accessible names and labels ------------------------------------------------------
  if (enabled.has("names")) {
    const named = (el) => {
      const label = el.getAttribute("aria-label");
      if (label && label.trim()) return true;
      const by = el.getAttribute("aria-labelledby");
      if (by && by.split(/\s+/).some((id) => document.getElementById(id)?.textContent.trim()))
        return true;
      if ((el.textContent ?? "").trim()) return true;
      if (el.title && el.title.trim()) return true;
      return [...el.querySelectorAll("img[alt], svg title")].some(
        (n) => (n.getAttribute("alt") ?? n.textContent ?? "").trim(),
      );
    };
    for (const el of document.querySelectorAll("a[href], button")) {
      if (visible(el) && !skipped(el) && !named(el)) add("names", where(el));
    }
    for (const el of document.querySelectorAll("input:not([type=hidden]), select, textarea")) {
      if (skipped(el)) continue;
      const byFor = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      const aria = el.getAttribute("aria-label") || el.getAttribute("aria-labelledby");
      if (!byFor && !el.closest("label") && !aria) add("labels", where(el));
    }
  }

  // --- headings and landmarks -----------------------------------------------------------
  if (enabled.has("headings")) {
    const headings = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].filter(
      (h) => visible(h) && !skipped(h),
    );
    const h1s = headings.filter((h) => h.tagName === "H1");
    if (h1s.length !== 1) add("headings", `${h1s.length} h1 elements, expected exactly 1`);
    let previous = 0;
    for (const h of headings) {
      const level = Number(h.tagName[1]);
      if (previous && level > previous + 1)
        add("headings", `${where(h)} — h${previous} jumps to h${level}`);
      previous = level;
    }
  }

  if (enabled.has("landmarks")) {
    if (!document.querySelector("main")) add("landmarks", "no main element");
    const skip = document.querySelector("a.skip");
    if (!skip) add("landmarks", "no skip link");
    else if (!document.querySelector(skip.getAttribute("href")))
      add("landmarks", `skip link points at ${skip.getAttribute("href")}, which does not exist`);
  }

  // --- tap targets ------------------------------------------------------------------------
  if (enabled.has("tap") && window.innerWidth < 500) {
    for (const el of document.querySelectorAll("a[href], button, input, select, textarea")) {
      if (!visible(el) || skipped(el)) continue;
      // Inline links inside a sentence are exempt under 2.5.8; they have no other placement.
      if (el.tagName === "A" && getComputedStyle(el).display === "inline") continue;
      const r = el.getBoundingClientRect();
      if (r.width < 24 || r.height < 24)
        add("tap", `${where(el)} — ${Math.round(r.width)}x${Math.round(r.height)}px`);
    }
  }

  // --- misc ---------------------------------------------------------------------------------
  if (enabled.has("misc")) {
    for (const el of document.querySelectorAll("[tabindex]")) {
      if (Number(el.getAttribute("tabindex")) > 0)
        add("tabindex", `${where(el)} — positive tabindex`);
    }
    if (!document.documentElement.lang) add("lang", "html has no lang attribute");
    for (const img of document.querySelectorAll("img")) {
      if (!img.hasAttribute("alt")) add("alt", where(img));
    }
  }

  return out;
}

/** Everything. The default for a new surface, so opting out is a decision someone wrote down. */
export const ALL_CHECKS = [
  "contrast",
  "squeezed",
  "anon-item",
  "clipped",
  "escapes",
  "overlap",
  "names",
  "headings",
  "landmarks",
  "tap",
  "misc",
];
