/**
 * Find user-facing text that is not going through the translator.
 *
 * A localization pass is finished when no English is left hardcoded, and that is exactly the
 * kind of claim nobody can check by reading a diff — one missed heading renders a Spanish page
 * with an English title, which is the half-translated state that is worse than not translating
 * at all. So it is checked mechanically, in CI.
 *
 * Two kinds of literal are reported:
 *
 * 1. **JSX text nodes** — `<h1>Dashboard</h1>`.
 * 2. **String props that reach the user** — `title=`, `label=`, `caption=`, `placeholder=`,
 *    `aria-label=`, and friends.
 *
 * Deliberately a heuristic, and deliberately noisy in one direction. Anything it flags that is
 * genuinely not user-facing goes in `ALLOWED` with a reason, so the exceptions are a list
 * somebody has to look at rather than a rule that quietly stops matching.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const SRC = join(ROOT, "src");

/** Props whose values are rendered to a person. */
const USER_FACING_PROPS = [
  "title",
  "subtitle",
  "label",
  "caption",
  "detail",
  "hint",
  "placeholder",
  "aria-label",
  "summary",
  "emptyMessage",
];

/**
 * Literals that look user-facing but are not, each with the reason.
 *
 * Kept as exact strings rather than patterns so that adding one is a deliberate act and the
 * list can be read as documentation of what this app renders untranslated.
 */
const ALLOWED = new Map([
  ["CareOS", "a product name, identical in both languages"],
  ["C", "the single-letter brand mark, aria-hidden"],
  ["Español", "a language name, deliberately in its own language"],
  ["English", "a language name, deliberately in its own language"],
  ["Main", "replaced by a translated aria-label; kept here for the nav landmark fallback"],
]);

/** Values that are data or markup rather than prose. */
function looksLikeCode(text) {
  return (
    /^[A-Z0-9_;=,.:/\-+ ]+$/.test(text) || // RRULEs, service codes, enum values
    /^[a-z0-9-]+$/.test(text) || // css classes, hrefs, identifiers
    /^\{.*\}$/.test(text) ||
    /^https?:\/\//.test(text) ||
    text.includes("--") // css custom properties
  );
}

function walk(dir) {
  const found = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) found.push(...walk(full));
    else if (/\.tsx$/.test(entry)) found.push(full);
  }
  return found;
}

function findings(file) {
  const source = readFileSync(file, "utf8");
  const rel = relative(ROOT, file);
  const out = [];

  // Strip comments first: prose in a comment is not rendered, and this file is full of it.
  const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  // 1. JSX text nodes: `>Some words<`, at least two letters and a space or sentence shape.
  for (const match of code.matchAll(/>\s*([A-Za-z][^<>{}]*?)\s*</g)) {
    const text = match[1].trim();
    if (!text || text.length < 2) continue;
    // `=>` and a later `<` make the regex span an arrow function, catching code as prose.
    // Rendered text has none of these, so requiring their absence removes the artifacts
    // without narrowing what counts as a user-facing string.
    if (/[;=()\n]|\.\w/.test(text)) continue;
    if (ALLOWED.has(text) || looksLikeCode(text)) continue;
    if (!/[A-Za-z]{2,}/.test(text)) continue;
    out.push({ file: rel, kind: "jsx-text", text });
  }

  // 2. User-facing string props.
  const propPattern = new RegExp(`\\b(${USER_FACING_PROPS.join("|")})=\\{?"([^"]{2,})"`, "g");
  for (const match of code.matchAll(propPattern)) {
    const [, prop, text] = match;
    if (ALLOWED.has(text) || looksLikeCode(text)) continue;
    out.push({ file: rel, kind: `prop:${prop}`, text });
  }

  return out;
}

const all = walk(SRC).flatMap(findings);

if (all.length > 0) {
  console.error(`${all.length} user-facing literal(s) not going through the translator:\n`);
  for (const { file, kind, text } of all) {
    console.error(`  ${file}  [${kind}]  ${JSON.stringify(text)}`);
  }
  console.error(
    "\nMove each into src/lib/i18n.ts and render it with t(...), or — if it is genuinely" +
      "\nnot user-facing — add it to ALLOWED in this script with the reason.",
  );
  process.exit(1);
}

console.log("No untranslated user-facing literals found.");
