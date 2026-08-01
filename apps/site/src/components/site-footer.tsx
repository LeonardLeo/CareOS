import Link from "next/link";

import { Mark } from "@/components/mark";
import { CONTACT_EMAIL, FOOTER_GROUPS, SITE_NAME } from "@/content/site";

/**
 * Footer.
 *
 * Says plainly that the product is pre-launch. A footer that reads like an established
 * company's — offices, press, a customer logo wall — is the cheapest lie on a website and the
 * first thing a design partner checks.
 */
export function SiteFooter() {
  return (
    <footer className="footer">
      <div className="shell">
        <div className="footer__grid">
          <div>
            <Link className="brand" href="/">
              <Mark className="brand__mark" />
              {SITE_NAME}
            </Link>
            <p style={{ marginTop: "var(--s3)", color: "var(--ink-2)", maxWidth: "30ch" }}>
              The workforce layer for home-based care. In active development, building with a
              small number of agencies.
            </p>
            <p style={{ marginTop: "var(--s4)" }}>
              <a className="textlink" href={`mailto:${CONTACT_EMAIL}`}>
                {CONTACT_EMAIL}
              </a>
            </p>
          </div>

          {FOOTER_GROUPS.map((group) => (
            <div key={group.heading}>
              <h2 className="footer__heading">{group.heading}</h2>
              <ul className="footer__links">
                {group.links.map((link) => (
                  <li key={link.href}>
                    {link.href.startsWith("http") ? (
                      <a href={link.href}>{link.label}</a>
                    ) : (
                      <Link href={link.href}>{link.label}</Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="footer__base">
          <span>
            © {new Date().getFullYear()} {SITE_NAME}
          </span>
          <span>Built in the open, one agency at a time.</span>
        </div>
      </div>
    </footer>
  );
}
