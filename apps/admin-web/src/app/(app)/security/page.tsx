/**
 * Multi-factor enrolment.
 *
 * `08_Security_Architecture.md` Section 1 requires MFA for owner/admin, clinical supervisor,
 * and billing/RCM. The API enforces it; this is the only place a person can actually satisfy
 * it, which is the difference between a requirement and a lockout.
 *
 * Three things about it are deliberate.
 *
 * **The secret is minted once, by a POST, and read here — never minted by this render.** The
 * first version called the enrolment endpoint from the page. That endpoint replaces the stored
 * secret on every call, by design, so each refresh — and the redirect after a mistyped code —
 * silently invalidated the secret the user had already scanned, turning one typo into an
 * authenticator that could never produce an accepted code. See `lib/mfa-enrolment.ts`.
 *
 * **The QR code is offered first, and the secret is still shown as text.** Typing a 32-character
 * secret into a phone is where people give up, so the code goes first. The text stays because a
 * QR is no use to someone enrolling a desktop password manager, reading the screen with a
 * magnifier, or working on the same phone that is displaying the page — and the `otpauth://`
 * URI stays with it, since a password manager takes that directly.
 *
 * **The recovery codes are on the same screen as the secret, before confirmation.** They are
 * returned once and never again — so a screen that showed them after the confirm step would
 * hand them to someone whose next action is to navigate away, and a lost phone would then be a
 * support ticket against an account nobody can get into.
 */

import { redirect } from "next/navigation";
import { EnrolmentQr } from "@/components/qr";
import { Card, ErrorNote, InfoNote, SeverityBadge } from "@/components/ui";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { api } from "@/lib/api";
import { getPendingEnrolment } from "@/lib/mfa-enrolment";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function SecurityPage({
  searchParams,
}: {
  searchParams: Promise<{
    required?: string;
    done?: string;
    error?: string;
    welcome?: string;
  }>;
}) {
  const session = await getSession();
  if (!session) redirect("/login");
  const t = translatorFor(await getLocale());
  const { required, done, error, welcome } = await searchParams;

  // Read, never minted. Starting enrolment is a POST to /api/mfa/start; this page only
  // renders what that POST produced. The first version called the API from here, which meant
  // every refresh — and every redirect after a mistyped code — replaced the secret the user
  // had already scanned, so their authenticator could never produce an accepted code again.
  const enrolment = await getPendingEnrolment();
  // Whether this account already has a second factor decides what the start form asks for.
  // Read from `/auth/me` because the user list is owner-admin only — a clinical supervisor
  // has no other way to learn their own state.
  const me = await api.me(session.token).catch(() => null);
  const alreadyEnrolled = me?.mfa_enrolled === true;

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">{t("securityTitle")}</h1>
          <p className="page-subtitle">{t("securitySubtitle")}</p>
        </div>
      </header>

      {/* Someone who has just signed up lands here rather than on a dashboard, because
          `owner_admin` is an MFA-required role and the session they hold reaches enrolment
          and nothing else. Arriving at a security screen with no explanation reads as an
          error, so the first thing they see says what happened and what is left. Shown
          instead of the bare requirement notice, not alongside it: two banners saying the
          same thing is how people learn to skip both. */}
      {welcome ? (
        <InfoNote title={t("welcomeTitle")} detail={t("welcomeBody")} />
      ) : (
        required && (
          <div className="notice">
            <SeverityBadge severity="critical">{t("mfaRequiredBadge")}</SeverityBadge>
            <span>{t("mfaRequiredNote")}</span>
          </div>
        )
      )}
      {done && (
        <div className="notice">
          <SeverityBadge severity="good">{t("mfaEnrolledBadge")}</SeverityBadge>
          <span>{t("mfaEnrolledNote")}</span>
        </div>
      )}
      {error && <ErrorNote title={t("couldNotCompleteStep")} detail={error} />}

      <div className="grid-2">
        <Card title={t("authenticatorApp")} subtitle={t("authenticatorAppSubtitle")}>
          {!enrolment ? (
            <form method="post" action="/api/mfa/start">
              <p className="small muted" style={{ marginBottom: "var(--space-4)" }}>
                {alreadyEnrolled ? t("mfaReplaceExplainer") : t("mfaStartExplainer")}
              </p>
              {alreadyEnrolled && (
                // Replacing an authenticator requires proving the one in force. Without it a
                // stolen session could move MFA onto the thief's device and collect fresh
                // recovery codes on the way.
                <div className="field">
                  <label className="field__label" htmlFor="current_code">
                    {t("mfaCurrentCodeLabel")}
                  </label>
                  <input
                    className="field__input"
                    id="current_code"
                    name="current_code"
                    inputMode="text"
                    autoComplete="one-time-code"
                    required
                  />
                </div>
              )}
              <button className="button" type="submit">
                {alreadyEnrolled ? t("mfaReplace") : t("mfaStart")}
              </button>
            </form>
          ) : (
            <>
              <p className="small muted">{t("mfaScanExplainer")}</p>
              <EnrolmentQr uri={enrolment.otpauthUri} label={t("mfaQrLabel")} />
              <p className="field__label" style={{ marginTop: "var(--space-4)" }}>
                {t("mfaSecretLabel")}
              </p>
              {/* Grouped in fours: this gets typed by hand into a phone. */}
              <p className="mono-block">{enrolment.secret.match(/.{1,4}/g)?.join(" ")}</p>
              <p className="field__label">{t("mfaUriLabel")}</p>
              <p className="mono-block mono-block--wrap">{enrolment.otpauthUri}</p>

              <form method="post" action="/api/mfa/confirm" style={{ marginTop: "var(--space-5)" }}>
                <div className="field">
                  <label className="field__label" htmlFor="code">
                    {t("mfaCodeLabel")}
                  </label>
                  <input
                    className="field__input"
                    id="code"
                    name="code"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    minLength={6}
                    maxLength={6}
                    required
                  />
                </div>
                <button className="button" type="submit">
                  {t("mfaConfirm")}
                </button>
              </form>
            </>
          )}
        </Card>

        <Card title={t("recoveryCodes")} subtitle={t("recoveryCodesSubtitle")}>
          {!enrolment ? (
            <p className="small muted">{t("recoveryCodesPending")}</p>
          ) : (
            <>
              <div className="notice">
                <SeverityBadge severity="warning">{t("shownOnce")}</SeverityBadge>
                <span>{t("recoveryCodesWarning")}</span>
              </div>
              <ul className="codelist">
                {enrolment.recoveryCodes.map((code) => (
                  <li key={code} className="mono-block">
                    {code}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </div>
    </>
  );
}
