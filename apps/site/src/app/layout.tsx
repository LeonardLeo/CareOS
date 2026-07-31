import type { Metadata } from "next";
import "@/styles/site.css";

/**
 * The public site's shell.
 *
 * Metadata is the whole job of this file. The page is most often first seen as a link
 * pasted into a Slack channel or a text message, so the title, description, and social card
 * are the actual first impression — more people will read those than will read the page.
 */
export const metadata: Metadata = {
  title: "CareOS — the operating system for home-based care",
  description:
    "Agencies turn down cases they cannot staff. CareOS is the workforce layer that fills them: AI-assisted recruiting, sub-72-hour onboarding, and EVV-compliant scheduling.",
  openGraph: {
    title: "CareOS — the operating system for home-based care",
    description:
      "63.3% of home care agencies turned down cases in 2023 because they could not staff them. CareOS exists to close that gap.",
    type: "website",
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
