/**
 * Multi-factor enrolment.
 *
 * `08_Security_Architecture.md` Section 1 requires MFA for owner/admin, clinical supervisor,
 * and billing/RCM. The API enforces it; this is the only place a person can actually satisfy
 * it, which is the difference between a requirement and a lockout.
 *
 * Two things about the layout are deliberate.
 *
 * **The secret is shown as text, not only as a QR code.** There is no QR here at all: rendering
 * one needs an encoder this app does not have, and manual entry works in every authenticator.
 * The `otpauth://` URI is shown too, since a desktop password manager takes it directly. A QR
 * is a genuine usability improvement and is noted in BUILD_STATUS rather than pretended away.
 *
 * **The recovery codes are on the same screen as the secret, before confirmation.** They are
 * returned once and never again — so a screen that showed them after the confirm step would
 * hand them to someone whose next action is to navigate away, and a lost phone would then be a
 * support ticket against an account nobody can get into.
 */

import { redirect } from "next/navigation";
import { Card, ErrorNote, SeverityBadge } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function SecurityPage({
  searchParams,
}: {
  searchParams: Promise<{ started?: string; required?: string; done?: string; error?: string }>;
}) {
  const session = await getSession();
  if (!session) redirect("/login");
  const t = translatorFor(await getLocale());
  const { started, required, done, error } = await searchParams;

  // The secret only exists inside the response that created it, so starting enrolment is a
  // POST from the button below rather than something this page does on load — a page that
  // minted a new secret every time it was opened would invalidate the one being scanned.
  let enrolment: Awaited<ReturnType<typeof api.startMfaEnrolment>> | null = null;
  if (started) {
    try {
      enrolment = await api.startMfaEnrolment(session.token);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : t("somethingWentWrong");
      return (
        <>
          <header className="page-header">
            <h1 className="page-title">{t("securityTitle")}</h1>
          </header>
          <ErrorNote title={t("couldNotCompleteStep")} detail={message} />
        </>
      );
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">{t("securityTitle")}</h1>
          <p className="page-subtitle">{t("securitySubtitle")}</p>
        </div>
      </header>

      {required && (
        <div className="notice">
          <SeverityBadge severity="critical">{t("mfaRequiredBadge")}</SeverityBadge>
          <span>{t("mfaRequiredNote")}</span>
        </div>
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
                {t("mfaStartExplainer")}
              </p>
              <button className="button" type="submit">
                {t("mfaStart")}
              </button>
            </form>
          ) : (
            <>
              <p className="small muted">{t("mfaScanExplainer")}</p>
              <p className="field__label" style={{ marginTop: "var(--space-4)" }}>
                {t("mfaSecretLabel")}
              </p>
              {/* Grouped in fours: this gets typed by hand into a phone. */}
              <p className="mono-block">{enrolment.secret.match(/.{1,4}/g)?.join(" ")}</p>
              <p className="field__label">{t("mfaUriLabel")}</p>
              <p className="mono-block mono-block--wrap">{enrolment.otpauth_uri}</p>

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
                {enrolment.recovery_codes.map((code) => (
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
