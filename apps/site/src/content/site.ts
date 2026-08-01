/**
 * Everything that appears on more than one page.
 *
 * Navigation, contact details, and the figures. Kept in one module so a page cannot quietly
 * disagree with another about the turnover rate or the sign-in URL — which is the failure
 * mode of a marketing site assembled page by page.
 */

export const SITE_NAME = "CareOS";
export const SIGN_IN_URL = "https://app.careos.example/login";
export const CONTACT_EMAIL = "hello@careos.example";
export const SECURITY_EMAIL = "security@careos.example";
export const PRIVACY_EMAIL = "privacy@careos.example";

export const partnerMailto = (subject = "CareOS design partner") =>
  `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}`;

export const NAV = [
  { href: "/product/", label: "Product" },
  { href: "/security/", label: "Security" },
  { href: "/about/", label: "About" },
  { href: "/careers/", label: "Careers" },
  { href: "/contact/", label: "Contact" },
] as const;

export const FOOTER_GROUPS = [
  {
    heading: "Product",
    links: [
      { href: "/product/", label: "What we build" },
      { href: "/security/", label: "Security & compliance" },
      { href: SIGN_IN_URL, label: "Sign in" },
    ],
  },
  {
    heading: "Company",
    links: [
      { href: "/about/", label: "About" },
      { href: "/careers/", label: "Careers" },
      { href: "/contact/", label: "Contact" },
    ],
  },
  {
    heading: "Legal",
    links: [
      { href: "/legal/privacy/", label: "Privacy" },
      { href: "/legal/terms/", label: "Terms" },
      { href: "/legal/subprocessors/", label: "Subprocessors" },
    ],
  },
] as const;

/**
 * The figures, with their source attached to each one.
 *
 * Every number traces to `docs/01_Product_Vision_and_Executive_Summary.md` Section 2. Carrying
 * the source in the data rather than in a footnote means a figure cannot be copied onto
 * another page without it, and an agency owner can tell the difference between a statistic
 * with a citation and one without.
 */
export interface Figure {
  value: string;
  /** True paints the number in the signal red. Reserved for the two that describe loss. */
  signal?: boolean;
  label: string;
  source: string;
}

export const FIGURES: Figure[] = [
  {
    value: "63.3%",
    signal: true,
    label: "of agencies turned down cases in 2023 because they could not staff them",
    source: "Activated Insights Benchmarking Report",
  },
  {
    value: "79.2%",
    signal: true,
    label: "caregiver turnover in 2023, easing to roughly 75% in 2024",
    source: "Activated Insights Benchmarking Report",
  },
  {
    value: "$2,600",
    label: "to replace one caregiver — about $171,600 a year for an average agency",
    source: "Activated Insights Benchmarking Report",
  },
  {
    value: "12.8%",
    label: "of applicants were hired in 2023. The pipeline is not the problem; the process is",
    source: "Activated Insights Benchmarking Report",
  },
];
