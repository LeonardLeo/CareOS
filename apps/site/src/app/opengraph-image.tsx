import { ImageResponse } from "next/og";

import { SITE_NAME } from "@/content/site";

/**
 * The card people see when a link to this site is pasted into Slack, a text, or a LinkedIn post.
 *
 * Generated at build time from the same tokens as the site rather than exported from a design
 * tool, so it cannot end up showing last quarter's positioning — the failure mode of a
 * hand-made OG image is that nobody remembers it exists.
 *
 * Deliberately not a screenshot of the product. The card is read at thumbnail size in a feed,
 * where a screenshot is an unreadable grey rectangle. It carries the one sentence that has to
 * survive being seen for half a second, and the figure that makes the case.
 *
 * No image, no external font. `next/og` renders this with Satori, which supports a subset of
 * CSS — flexbox only, no `gap` on some versions, every element needing an explicit `display`.
 * The system font stack is used on purpose: the site's variable fonts would have to be loaded
 * as binary here, and a card that fails to build is worse than one set in a plain face.
 */

// Required under `output: "export"`: a metadata route is a handler by default, and the export
// refuses to guess that this one never varies. Saying so turns it into a file at build time.
export const dynamic = "force-static";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = `${SITE_NAME} — the operating system for home-based care`;

// Matches `--paper`, `--ink`, `--signal` in `site.css`. Literal because Satori resolves no
// custom properties; `scripts/check-og.mjs` fails the build if they drift apart.
const PAPER = "#f8f6f1";
const INK = "#16130f";
const INK_2 = "#4a443c";
const SIGNAL = "#b23a26";
const RULE = "#e2dcd2";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: PAPER,
          padding: "72px 80px",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center" }}>
          <div
            style={{
              display: "flex",
              width: 40,
              height: 40,
              borderRadius: 8,
              background: INK,
              marginRight: 18,
            }}
          />
          <div style={{ display: "flex", fontSize: 30, fontWeight: 600, color: INK }}>
            {SITE_NAME}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "flex",
              fontSize: 68,
              lineHeight: 1.08,
              fontWeight: 600,
              color: INK,
              letterSpacing: "-0.03em",
              maxWidth: 940,
            }}
          >
            The workforce layer for home-based care.
          </div>
          <div
            style={{
              display: "flex",
              marginTop: 28,
              fontSize: 30,
              lineHeight: 1.35,
              color: INK_2,
              maxWidth: 880,
            }}
          >
            Agencies turn down work they cannot staff. CareOS fills it — hiring, onboarding, and
            EVV-compliant scheduling.
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            borderTop: `1px solid ${RULE}`,
            paddingTop: 26,
          }}
        >
          <div style={{ display: "flex", fontSize: 44, fontWeight: 600, color: SIGNAL }}>63.3%</div>
          <div style={{ display: "flex", marginLeft: 18, fontSize: 25, color: INK_2 }}>
            of agencies turned down cases in 2023 because they could not staff them
          </div>
        </div>
      </div>
    ),
    size,
  );
}
