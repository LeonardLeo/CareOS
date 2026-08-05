import { redirect } from "next/navigation";
import { AppNav, type AppNavGroup } from "@/components/app-nav";
import { LanguageSwitcher } from "@/components/language-switcher";
import { api } from "@/lib/api";
import { type StringKey, roleLabel, translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { canSee, getSession } from "@/lib/session";

// Labels are string *keys*, resolved per request. Holding the English here and translating at
// the call site would put one language in the structure and the other in a lookup, which is
// how a nav ends up half-translated.
//
// Groups match how an owner scans the console: where am I, what needs a person today, who
// works here, who can sign in. A flat list of nine links buried the counts that used to make
// the rail useful at a glance.
const NAV_GROUPS = [
  {
    labelKey: "navGroupOverview",
    items: [{ href: "/dashboard", labelKey: "navDashboard", area: "dashboard" }],
  },
  {
    labelKey: "navGroupOperations",
    items: [
      {
        href: "/scheduling",
        labelKey: "navScheduling",
        area: "scheduling",
        countKey: "gaps" as const,
      },
      { href: "/clients", labelKey: "navClients", area: "scheduling" },
      {
        href: "/exceptions",
        labelKey: "navExceptions",
        area: "exceptions",
        countKey: "exceptions" as const,
      },
    ],
  },
  {
    labelKey: "navGroupWorkforce",
    items: [
      { href: "/recruiting", labelKey: "navRecruiting", area: "recruiting" },
      {
        href: "/credentialing",
        labelKey: "navCredentialing",
        area: "credentialing",
        countKey: "expiredCredentials" as const,
      },
      { href: "/compliance", labelKey: "navCompliance", area: "compliance" },
    ],
  },
  {
    labelKey: "navGroupAdmin",
    items: [
      { href: "/users", labelKey: "navUsers", area: "users" },
      // Reachable by every role, unlike the rest of this list: MFA is required for three roles
      // and available to all of them, and a user held on the enrolment screen must be able to
      // navigate to it.
      { href: "/security", labelKey: "navSecurity", area: "security" },
    ],
  },
] as const satisfies readonly {
  labelKey: StringKey;
  items: readonly {
    href: string;
    labelKey: StringKey;
    area: string;
    countKey?: "gaps" | "exceptions" | "expiredCredentials";
  }[];
}[];

type NavCounts = {
  gaps: number;
  exceptions: number;
  expiredCredentials: number;
};

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (!session) redirect("/login");

  const locale = await getLocale();
  const t = translatorFor(locale);

  // An unattended queue should be visible without opening it. Best-effort: a nav badge is
  // never worth failing the whole layout over, so a lookup failure just omits the count.
  const counts: NavCounts = { gaps: 0, exceptions: 0, expiredCredentials: 0 };
  await Promise.all([
    api
      .exceptionSummary(session.token)
      .then((summary) => {
        counts.exceptions = summary.total_open;
      })
      .catch(() => {
        /* omit */
      }),
    api
      .gaps(session.token, 72)
      .then((gaps) => {
        counts.gaps = gaps.length;
      })
      .catch(() => {
        /* omit */
      }),
    api
      .credentialExpirations(session.token, 60)
      .then((rows) => {
        counts.expiredCredentials = rows.filter((row) => row.already_expired).length;
      })
      .catch(() => {
        /* omit */
      }),
  ]);

  // Hiding a link the role cannot use is a usability courtesy only. The real boundary is the
  // API's RBAC plus row-level security — this layout is not a security control.
  const groups: AppNavGroup[] = NAV_GROUPS.map((group) => ({
    label: t(group.labelKey),
    items: group.items
      .filter((item) => canSee(item.area, session.role))
      .map((item) => {
        const countKey = "countKey" in item ? item.countKey : undefined;
        return {
          href: item.href,
          label: t(item.labelKey),
          count: countKey ? counts[countKey] : undefined,
        };
      }),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="shell">
      {/* Nine nav links sit before the content on every screen. Without this, reaching the
          page a keyboard user actually came for costs nine tabs, on every navigation, all
          day. */}
      <a className="skip" href="#main">
        {t("skipToContent")}
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            C
          </span>
          <span className="brand__text">
            {t("appName")}
            <span className="brand__sub">{t("appSubtitle")}</span>
          </span>
        </div>

        <AppNav groups={groups} ariaLabel={t("navMain")} />

        <div className="sidebar__footer">
          <div className="sidebar__role">{roleLabel(locale, session.role)}</div>
          <LanguageSwitcher locale={locale} />
          <form method="post" action="/api/auth/logout">
            <button className="button button--ghost button--small" type="submit">
              {t("signOut")}
            </button>
          </form>
        </div>
      </aside>

      {/* `tabIndex={-1}` is what makes the skip link work. Without it the browser scrolls to
          the fragment but leaves focus on the link, so the next Tab goes back into the nav
          and the reader never escapes it. */}
      <main className="main" id="main" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
