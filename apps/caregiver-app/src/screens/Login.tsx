import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Locale, Translator } from "@/lib/i18n";
import { storeSession } from "@/lib/session";

/**
 * Sign-in.
 *
 * `inputMode="email"` and `autoComplete` are set so the phone offers the right keyboard and
 * the caregiver's saved credentials — typing an email address on a phone keyboard while
 * standing outside is exactly the friction this surface should remove.
 *
 * Deliberately no "remember me": the session token lives in sessionStorage by design (see
 * `session.ts`), and a checkbox implying a longer-lived credential would be a lie.
 */
export function Login({
  onSignedIn,
  t,
  locale,
  onLocaleChange,
}: {
  onSignedIn: () => void;
  t: Translator;
  locale: Locale;
  onLocaleChange: (locale: Locale) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<null | "credentials" | "disabled">(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(null);
    try {
      const tokens = await api.login(email, password);
      storeSession(tokens.access_token);
      onSignedIn();
    } catch (error) {
      // One message for a wrong password and an unknown address, matching the API, which
      // deliberately does not distinguish them. A disabled account is the exception, and the
      // API only says so once the password has checked out — so this reveals nothing to
      // someone guessing, and saves a caregiver whose account was disabled from trying their
      // password over and over on a phone in a client's hallway.
      const disabled = error instanceof ApiError && error.code === "ACCOUNT_INACTIVE";
      setFailed(disabled ? "disabled" : "credentials");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="topbar">
        <div className="topbar__brand">
          {t("appName")}
          <span>{t("appSubtitle")}</span>
        </div>
        {/* The accessible name says what pressing this does, in the language it switches to.
            An aria-label of just "Language" overrides the visible "ES" and leaves a screen
            reader announcing a noun with no indication of the action or the target. */}
        <button
          className="iconbutton"
          type="button"
          onClick={() => onLocaleChange(locale === "en" ? "es" : "en")}
          aria-label={locale === "en" ? "Cambiar a español" : "Switch to English"}
          lang={locale === "en" ? "es" : "en"}
        >
          {locale === "en" ? "ES" : "EN"}
        </button>
      </header>

      <div className="page">
        <h1 className="page__title">{t("signIn")}</h1>

        <form onSubmit={submit}>
          <div className="field">
            <label className="field__label" htmlFor="email">
              {t("email")}
            </label>
            <input
              className="field__input"
              id="email"
              name="email"
              type="email"
              inputMode="email"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
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
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          {failed && (
            <div className="note note--danger" role="alert">
              {t(failed === "disabled" ? "signInDisabled" : "signInFailed")}
            </div>
          )}

          <div className="action-bar">
            <button className="action" type="submit" disabled={busy}>
              {busy ? t("signingIn") : t("signIn")}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
