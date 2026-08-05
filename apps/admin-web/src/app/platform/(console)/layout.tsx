/**
 * The operator console shell.
 *
 * A route group, so `/platform/login` and the route handlers under `/platform/api` sit
 * outside it and this guard cannot redirect to itself.
 *
 * Two things distinguish it from the agency shell and both are deliberate. The nav is marked
 * so nobody can mistake which console they are in — a CareOS employee holding an operator
 * session and a test-agency session in one browser is the normal case, not an edge one. And
 * an operator who has not enrolled an authenticator is sent to the security screen and can
 * reach nothing else, which mirrors what the API enforces rather than restating it: the
 * server refuses those requests regardless of what this file renders.
 */

import { redirect } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { LanguageSwitcher } from "@/components/language-switcher";
import { type StringKey, translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getPlatformSession } from "@/lib/platform-session";

const NAV = [
  { href: "/platform", labelKey: "platformNavFleet" },
  { href: "/platform/operators", labelKey: "platformNavOperators" },
  { href: "/platform/audit", labelKey: "platformNavAudit" },
  { href: "/platform/security", labelKey: "platformNavSecurity" },
] as const satisfies readonly { href: string; labelKey: StringKey }[];

export default async function PlatformLayout({ children }: { children: React.ReactNode }) {
  const session = await getPlatformSession();
  if (!session) redirect("/platform/login");

  const locale = await getLocale();
  const t = translatorFor(locale);

  // Until an authenticator is paired, the security screen is the only one the API will
  // answer. Sending them there beats rendering a dashboard whose every panel is a 403.
  const links = session.mfaSatisfied ? NAV : NAV.filter((i) => i.href === "/platform/security");

  return (
    <div className="shell">
      <a className="skip" href="#main">
        {t("skipToContent")}
      </a>
      <aside className="sidebar sidebar--platform">
        <div className="brand">
          <span className="brand__mark brand__mark--platform" aria-hidden="true">
            C
          </span>
          <span className="brand__text">
            {t("platformSystem")}
            <span className="brand__sub">{t("platformAppSubtitle")}</span>
          </span>
        </div>

        <AppNav
          ariaLabel={t("navMain")}
          groups={[
            {
              items: links.map((item) => ({
                href: item.href,
                label: t(item.labelKey),
              })),
            },
          ]}
        />

        <div className="sidebar__footer">
          <div className="sidebar__role">
            {t(
              session.role === "platform_admin"
                ? "platformOperatorRoleAdmin"
                : "platformOperatorRoleSupport",
            )}
          </div>
          <LanguageSwitcher locale={locale} />
          <form method="post" action="/platform/api/auth/logout">
            <button className="button button--ghost button--small" type="submit">
              {t("signOut")}
            </button>
          </form>
        </div>
      </aside>

      <main className="main" id="main" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
