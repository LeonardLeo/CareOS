/**
 * Sign-in for CareOS staff.
 *
 * Outside the `(console)` route group, so it is not behind the layout that requires an
 * operator session — which is what stops the guard redirecting to itself.
 *
 * Visually the same panel as the agency sign-in, with one deliberate difference: it says
 * whose console this is and that agencies belong elsewhere. A page that looked identical to
 * the customer login would be a good phishing template and a bad wayfinding cue.
 */

import Link from "next/link";
import { redirect } from "next/navigation";
import { LanguageSwitcher } from "@/components/language-switcher";
import { ErrorNote } from "@/components/ui";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getPlatformSession } from "@/lib/platform-session";

export const dynamic = "force-dynamic";

export default async function PlatformLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  if (await getPlatformSession()) redirect("/platform");
  const { error } = await searchParams;
  const locale = await getLocale();
  const t = translatorFor(locale);

  return (
    <main className="login">
      <div className="login__panel">
        <div className="login__brand">
          <span className="brand__mark brand__mark--platform" aria-hidden="true">
            C
          </span>
          <div>
            <h1 className="login__title">{t("platformSignInTitle")}</h1>
            <p className="login__subtitle">{t("platformAppSubtitle")}</p>
          </div>
        </div>

        {error && (
          <ErrorNote
            title={t(
              error === "disabled"
                ? "platformSignInDisabled"
                : error === "mfa"
                  ? "signInCodePrompt"
                  : error === "invalid"
                    ? "platformSignInFailed"
                    : "signInUnavailable",
            )}
          />
        )}

        <form method="post" action="/platform/api/auth/login">
          <div className="field">
            <label className="field__label" htmlFor="email">
              {t("email")}
            </label>
            <input
              className="field__input"
              id="email"
              name="email"
              type="email"
              autoComplete="username"
              required
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="password">
              {t("password")}
            </label>
            <input
              className="field__input"
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </div>

          {/* Rendered only once the API has said a code is needed, exactly as on the agency
              form. Unlike that one, every account here will eventually have a factor — MFA
              is unconditional for operators — so this field appears on the second attempt
              for everybody after their first day. */}
          {error === "mfa" && (
            <div className="field">
              <label className="field__label" htmlFor="mfa_code">
                {t("signInCodeLabel")}
              </label>
              <input
                className="field__input"
                id="mfa_code"
                name="mfa_code"
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                required
              />
            </div>
          )}

          <button className="button" type="submit" style={{ width: "100%" }}>
            {t("signIn")}
          </button>
        </form>

        <p className="small muted" style={{ marginTop: "var(--space-5)" }}>
          {t("platformSignInSubtitle")}
        </p>

        <p className="small" style={{ marginTop: "var(--space-3)" }}>
          <Link href="/login">{t("signInTitle")}</Link>
        </p>

        <div style={{ marginTop: "var(--space-4)" }}>
          <LanguageSwitcher locale={locale} returnTo="/platform/login" />
        </div>
      </div>
    </main>
  );
}
