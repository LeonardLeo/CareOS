import Link from "next/link";
import { redirect } from "next/navigation";
import { LanguageSwitcher } from "@/components/language-switcher";
import { api } from "@/lib/api";
import { type StringKey, roleLabel, translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { canSee, getSession } from "@/lib/session";

// Labels are string *keys*, resolved per request. Holding the English here and translating at
// the call site would put one language in the structure and the other in a lookup, which is
// how a nav ends up half-translated.
const NAV = [
  { href: "/dashboard", labelKey: "navDashboard", area: "dashboard" },
  { href: "/scheduling", labelKey: "navScheduling", area: "scheduling" },
  { href: "/clients", labelKey: "navClients", area: "scheduling" },
  { href: "/exceptions", labelKey: "navExceptions", area: "exceptions" },
  { href: "/recruiting", labelKey: "navRecruiting", area: "recruiting" },
  { href: "/credentialing", labelKey: "navCredentialing", area: "credentialing" },
  { href: "/compliance", labelKey: "navCompliance", area: "compliance" },
  { href: "/users", labelKey: "navUsers", area: "users" },
] as const satisfies readonly { href: string; labelKey: StringKey; area: string }[];

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (!session) redirect("/login");

  const locale = await getLocale();
  const t = translatorFor(locale);

  // Hiding a link the role cannot use is a usability courtesy only. The real boundary is the
  // API's RBAC plus row-level security — this layout is not a security control.
  const links = NAV.filter((item) => canSee(item.area, session.role));

  // An unattended queue should be visible without opening it. Best-effort: a nav badge is
  // never worth failing the whole layout over, so a lookup failure just omits the count.
  let openExceptions = 0;
  try {
    openExceptions = (await api.exceptionSummary(session.token)).total_open;
  } catch {
    openExceptions = 0;
  }

  return (
    <div className="shell">
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

        <nav className="nav" aria-label={t("navMain")}>
          {links.map((item) => (
            <Link key={item.href} className="nav__link" href={item.href}>
              <span>{t(item.labelKey)}</span>
              {item.href === "/exceptions" && openExceptions > 0 && (
                <span className="nav__count">{openExceptions}</span>
              )}
            </Link>
          ))}
        </nav>

        <div className="sidebar__footer">
          <div className="sidebar__role">{roleLabel(locale, session.role)}</div>
          <LanguageSwitcher locale={locale} returnTo="/dashboard" />
          <form method="post" action="/api/auth/logout">
            <button className="button button--ghost button--small" type="submit">
              {t("signOut")}
            </button>
          </form>
        </div>
      </aside>

      <main className="main">{children}</main>
    </div>
  );
}
