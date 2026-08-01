/**
 * Asserts the Open Graph card's colours still match the site's tokens.
 *
 * `next/og` renders with Satori, which resolves no CSS custom properties — so the card has to
 * repeat `--paper`, `--ink`, and the rest as literals. Repeated values drift, and this one
 * drifts invisibly: nobody looks at the card, they look at the site, and the first sign is a
 * link preview in somebody else's Slack that does not look like the company.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const read = (path) => readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf8");
const css = read("../src/styles/site.css");
const card = read("../src/app/opengraph-image.tsx");

// Only the light-mode block: a card has no theme, and the tokens are redefined under
// `prefers-color-scheme: dark` further down the file.
const light = css.slice(0, css.indexOf("@media (prefers-color-scheme: dark)"));

const PAIRS = [
  ["PAPER", "--paper"],
  ["INK", "--ink"],
  ["INK_2", "--ink-2"],
  ["SIGNAL", "--signal"],
  ["RULE", "--rule"],
];

let failures = 0;
for (const [constant, token] of PAIRS) {
  const inCard = card.match(new RegExp(`const ${constant} = "(#[0-9a-fA-F]{3,8})"`))?.[1];
  const inCss = light.match(new RegExp(`${token}:\\s*(#[0-9a-fA-F]{3,8})\\s*;`))?.[1];
  if (!inCard || !inCss) {
    console.log(`FAIL ${constant} / ${token} — could not read one of them`);
    failures += 1;
  } else if (inCard.toLowerCase() !== inCss.toLowerCase()) {
    console.log(`FAIL ${constant} is ${inCard}, ${token} is ${inCss}`);
    failures += 1;
  } else {
    console.log(`ok   ${constant.padEnd(6)} ${inCard} matches ${token}`);
  }
}

console.log(failures ? `\n${failures} drifted` : "\nthe card and the stylesheet agree");
process.exit(failures ? 1 : 0);
