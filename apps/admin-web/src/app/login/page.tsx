import Link from "next/link";
import { redirect } from "next/navigation";
import { LanguageSwitcher } from "@/components/language-switcher";
import { ErrorNote } from "@/components/ui";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  if (await getSession()) redirect("/dashboard");
  const { error } = await searchParams;
  const locale = await getLocale();
  const t = translatorFor(locale);

  return (
    <main className="login">
      <div className="login__panel">
        <div className="login__brand">
          <span className="brand__mark" aria-hidden="true">
            C
          </span>
          <div>
            <h1 className="login__title">{t("appName")}</h1>
            <p className="login__subtitle">{t("appSubtitle")}</p>
          </div>
        </div>

        {error === "suspended" ? (
          // Its own branch rather than another entry in the ladder below, because it is the
          // one failure that is not about this person's credentials at all. Telling an owner
          // their account was disabled would send them to a user list to look for a change
          // nobody in their agency made.
          <ErrorNote title={t("agencySuspendedTitle")} detail={t("agencySuspendedBody")} />
        ) : (
          error && (
            <ErrorNote
              title={t(
                error === "disabled"
                  ? "signInDisabled"
                  : error === "mfa"
                    ? "signInCodePrompt"
                    : error === "invalid"
                      ? "signInFailed"
                      : "signInUnavailable",
              )}
            />
          )
        )}

        {/*
          A plain form post to a server route handler. No client-side JavaScript touches the
          credentials or the resulting token, and the form works before hydration.
        */}
        <form method="post" action="/api/auth/login">
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

          {/* Rendered only once the API has said a code is needed. Showing it to everyone
              would ask caregivers — and anyone not yet enrolled — for something they do not
              have, and an empty optional field on a sign-in screen invites a support call from
              every one of them. The cost is one extra round trip for enrolled users. */}
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

        <p className="small" style={{ marginTop: "var(--space-5)" }}>
          {t("signUpNudge")} <Link href="/signup">{t("signUp")}</Link>
        </p>

        <p className="small muted" style={{ marginTop: "var(--space-3)" }}>
          {t("mfaNotice")}
        </p>

        {/* Before sign-in, so someone who cannot read the English form can still change it. */}
        <div style={{ marginTop: "var(--space-4)" }}>
          <LanguageSwitcher locale={locale} returnTo="/login" />
        </div>
      </div>
    </main>
  );
}
