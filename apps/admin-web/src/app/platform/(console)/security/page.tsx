/**
 * Multi-factor enrolment for a CareOS operator.
 *
 * The same three deliberate properties as the agency version — the secret is minted once by
 * a POST and read here rather than re-minted by the render, the QR and the text both appear,
 * and the recovery codes are shown before confirmation because they are returned once — and
 * one difference: this is not optional and there is no setting that makes it optional. An
 * operator who has not enrolled can reach this screen and nothing else, which is enforced by
 * `requires_platform` on the API rather than by this file.
 */

import { EnrolmentQr } from "@/components/qr";
import { Card, ErrorNote, SeverityBadge } from "@/components/ui";
import { platformApi } from "@/lib/api";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getPendingPlatformEnrolment } from "@/lib/mfa-enrolment";
import { getPlatformSession } from "@/lib/platform-session";

export const dynamic = "force-dynamic";

export default async function PlatformSecurityPage({
  searchParams,
}: {
  searchParams: Promise<{ done?: string; error?: string }>;
}) {
  const session = await getPlatformSession();
  if (!session) return null;
  const t = translatorFor(await getLocale());
  const { done, error } = await searchParams;

  const enrolment = await getPendingPlatformEnrolment();
  const me = await platformApi.me(session.token).catch(() => null);
  const alreadyEnrolled = me?.mfa_enrolled === true;

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">{t("securityTitle")}</h1>
          <p className="page-subtitle">{t("platformSecuritySubtitle")}</p>
        </div>
      </header>

      {!session.mfaSatisfied && (
        <div className="notice">
          <SeverityBadge severity="critical">{t("mfaRequiredBadge")}</SeverityBadge>
          <span>{t("platformMfaRequiredNote")}</span>
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
            <form method="post" action="/platform/api/mfa/start">
              <p className="small muted" style={{ marginBottom: "var(--space-4)" }}>
                {alreadyEnrolled ? t("mfaReplaceExplainer") : t("mfaStartExplainer")}
              </p>
              {alreadyEnrolled && (
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
              <p className="mono-block">{enrolment.secret.match(/.{1,4}/g)?.join(" ")}</p>
              <p className="field__label">{t("mfaUriLabel")}</p>
              <p className="mono-block mono-block--wrap">{enrolment.otpauthUri}</p>

              <form
                method="post"
                action="/platform/api/mfa/confirm"
                style={{ marginTop: "var(--space-5)" }}
              >
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
