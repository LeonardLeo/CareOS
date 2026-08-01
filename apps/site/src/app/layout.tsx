import type { Metadata } from "next";

// Self-hosted variable fonts, as npm packages. A font CDN is a third-party request on every
// page load, a DNS lookup on a bad connection, and a record of who visited held by someone
// else. `wght` only — the other axes are set in CSS via font-variation-settings.
import "@fontsource-variable/fraunces";
import "@fontsource-variable/inter";
import "@/styles/site.css";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { SITE_ORIGIN } from "@/content/site";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_ORIGIN),
  title: {
    default: "CareOS — the operating system for home-based care",
    // Every interior page gets the product name without repeating it in each file.
    template: "%s — CareOS",
  },
  description:
    "Home care agencies turn down work they cannot staff. CareOS is the workforce layer that fills it: AI-assisted recruiting, sub-72-hour onboarding, and EVV-compliant scheduling.",
  openGraph: {
    type: "website",
    siteName: "CareOS",
    title: "CareOS — the operating system for home-based care",
    description:
      "63.3% of home care agencies turned down cases in 2023 because they could not staff them. CareOS exists to close that gap.",
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <SiteHeader />
        {/* `tabIndex={-1}` is what makes the skip link work. Without it the browser scrolls to
            the fragment but leaves focus on the link, so the next Tab goes back into the nav
            and the reader never escapes it. */}
        <main id="main" tabIndex={-1}>
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
