import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage } from "@/components/legal-page";
import { PRIVACY_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "Cookies and tracking",
  description:
    "This site sets no cookies and loads nothing from a third party. This page explains why there is no consent banner.",
};

/**
 * The cookie page.
 *
 * The site genuinely sets nothing — verified in a browser rather than assumed — so the page
 * says that and explains the consequence, which is that a consent banner would be theatre.
 * It exists at all because a missing cookie policy reads as evasion, and because the honest
 * answer is a better advertisement than the banner would be.
 */
export default function CookiesPage() {
  return (
    <LegalPage
      eyebrow="Legal"
      title="Cookies and tracking"
      lede="There are none. That is the entire policy, and the rest of this page explains what it means and how you can check."
      updated="31 July 2026"
    >
      <h2>What this site sets</h2>
      <p>
        Nothing. No cookies, no local storage, no session storage, no fingerprinting, no
        pixel, no analytics, and no third-party request of any kind. The typefaces are served
        from our own origin as part of the site, not fetched from a font service.
      </p>
      <p>
        You do not have to take that on trust. Open your browser&rsquo;s developer tools,
        visit any page here, and look at the network tab and the storage panel. One host, no
        cookies. We check the same thing automatically before shipping a change.
      </p>

      <h2>Why there is no consent banner</h2>
      <p>
        Consent banners exist because sites set things that require consent. This one does
        not, so a banner would be asking permission for something that is not happening —
        which teaches people to click through prompts without reading them, and makes the
        prompts that do matter less effective.
      </p>
      <p>
        If we ever add something that needs consent, the banner arrives with it and this page
        changes first.
      </p>

      <h2>The product is different</h2>
      <p>
        The CareOS application, which agencies sign into, uses a strictly necessary session
        cookie. It exists to keep you signed in and does nothing else — it carries no
        advertising identifier and is not shared with anyone. It is set only after you sign
        in, and it is <code>HttpOnly</code>, which means the page&rsquo;s own JavaScript
        cannot read it.
      </p>
      <p>
        The caregiver mobile app stores your schedule on the device so that clock-in works
        with no signal. That data is wiped the moment your access is revoked. Both are covered
        in the{" "}
        <Link className="textlink" href="/legal/privacy/">
          privacy notice
        </Link>
        .
      </p>

      <h2>Server logs</h2>
      <p>
        Our host records ordinary access logs — an IP address, a timestamp, the page
        requested — for security and troubleshooting. Those are not cookies and cannot be
        declined, because serving you the page requires receiving the request. We do not join
        them to anything else or use them to build a profile.
      </p>

      <h2>Questions</h2>
      <p>
        Write to{" "}
        <a className="textlink" href={`mailto:${PRIVACY_EMAIL}`}>
          {PRIVACY_EMAIL}
        </a>
        .
      </p>
    </LegalPage>
  );
}
