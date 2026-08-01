/**
 * Everything that appears on more than one page.
 *
 * Navigation, contact details, and the figures. Kept in one module so a page cannot quietly
 * disagree with another about the turnover rate or the sign-in URL — which is the failure
 * mode of a marketing site assembled page by page.
 */

export const SITE_NAME = "CareOS";
/** The canonical origin. One constant, so the sitemap and the metadata base cannot diverge. */
export const SITE_ORIGIN = "https://careos.example";
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
      { href: "/legal/cookies/", label: "Cookies" },
      // The index rather than eight more rows. A footer that lists every policy buries the
      // three people actually look for.
      { href: "/legal/", label: "All policies" },
    ],
  },
] as const;

/**
 * Every policy page, in the order the index lists them.
 *
 * Shared so the index, the sitemap, and any future navigation cannot disagree about which
 * policies exist — a legal page that is published but unlinked is one nobody can find, and a
 * link to one that was never written is worse.
 */
export const LEGAL_PAGES = [
  {
    href: "/legal/privacy/",
    title: "Privacy",
    summary:
      "What this website collects, what the product holds on an agency's behalf, and why those are two different questions.",
  },
  {
    href: "/legal/terms/",
    title: "Terms of use",
    summary:
      "Terms for this website. The product is governed by a signed agreement, not by a page you scrolled past.",
  },
  {
    href: "/legal/cookies/",
    title: "Cookies and tracking",
    summary:
      "There are none. This page exists because its absence would look like evasion rather than like an answer.",
  },
  {
    href: "/legal/hipaa/",
    title: "HIPAA and business associate agreements",
    summary:
      "Where we sit in the HIPAA relationship, what we sign before receiving PHI, and what we will not do with it.",
  },
  {
    href: "/legal/acceptable-use/",
    title: "Acceptable use",
    summary:
      "What an agency may and may not do with the product, written around the two things that actually cause harm here.",
  },
  {
    href: "/legal/availability/",
    title: "Availability and support",
    summary:
      "What we commit to today, which is less than a service level agreement, said plainly rather than implied.",
  },
  {
    href: "/legal/subprocessors/",
    title: "Subprocessors",
    summary:
      "Every company that could touch protected health information, what it does, and where.",
  },
  {
    href: "/legal/accessibility/",
    title: "Accessibility",
    summary:
      "What we build to, what we have tested, and what we know is not there yet.",
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
